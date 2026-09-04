import queue
import numpy as np
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
from scipy.signal import find_peaks, butter, filtfilt, lfilter, lfilter_zi
from scipy.interpolate import interp1d

class ECGPeakDetector(QThread):
    """الخيط الثاني: اكتشاف القمم، حساب RR، واستخراج إشارة التنفس (EDR)"""
    analysis_results = pyqtSignal(int, list, list, list, list, list, list, list, float)

    def __init__(self, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        self.data_queue = queue.Queue()
        self.is_running = True
        self.absolute_sample_count = 0 
        self.last_peak_absolute_time = 0 
        self.edr_times = []
        self.edr_amps = []

    def add_buffer(self, raw_buffer, smoothed_buffer):
        self.data_queue.put((raw_buffer, smoothed_buffer))

    def run(self):
        while self.is_running:
            try:
                raw_buffer, smoothed_buffer = self.data_queue.get(timeout=1)
                self._process_buffer(raw_buffer, smoothed_buffer)
            except queue.Empty:
                continue

    # =====================================================================
    # الدالة الرئيسية (الموجهة) - تقوم فقط بتوزيع المهام على الدوال الفرعية
    # =====================================================================
    def _process_buffer(self, raw_buffer, smoothed_buffer):
        raw_data = np.array(raw_buffer)
        smoothed_data = np.array(smoothed_buffer)

        # 1. اكتشاف القمم
        filtered_data, peaks = self._detect_r_peaks(raw_data)
        self.absolute_sample_count += len(raw_data)

        if len(peaks) > 0:
            absolute_peaks = [int(p) + self.absolute_sample_count - len(raw_data) for p in peaks]
            
            # 2. تحديث بيانات التنفس (EDR)
            self._update_edr_history(peaks, filtered_data, absolute_peaks)

            # 3. حساب فترات RR
            rr_intervals_ms = self._calculate_rr_intervals(absolute_peaks)
            self.last_peak_absolute_time = absolute_peaks[-1]

            # 4. حساب معدل ضربات القلب
            real_bpm = self._calculate_bpm(rr_intervals_ms)

            # 5. تجهيز إحداثيات القمم للواجهة
            x_indices, y_values = self._map_ecg_peaks_to_ui(peaks, smoothed_data, len(raw_data))

            # 6. معالجة إشارة التنفس وحساب معدله
            edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm = self._process_edr_and_respiration()

            # إرسال النتائج النهائية
            self.analysis_results.emit(real_bpm, x_indices, y_values, rr_intervals_ms, 
                                       edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm)
        else:
            self.analysis_results.emit(0, [], [], [], [], [], [], [], 0.0)

    # =====================================================================
    # الدوال الفرعية لـ ECGPeakDetector (كل دالة لها مهمة واحدة)
    # =====================================================================
    def _detect_r_peaks(self, raw_data):
        """تصفية الإشارة واكتشاف قمم R-Peaks"""
        filtered_data = self._butter_bandpass_filter(raw_data, 0.5, 40.0, self.sample_rate)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)
        return filtered_data, peaks

    def _update_edr_history(self, peaks, filtered_data, absolute_peaks):
        """استخراج سعة القمم وتحديث سجل التنفس (آخر 60 ثانية)"""
        new_amps = [float(filtered_data[p]) for p in peaks]
        new_times = [float(p) / self.sample_rate for p in absolute_peaks]
        self.edr_amps.extend(new_amps)
        self.edr_times.extend(new_times)

        if self.edr_times:
            cutoff = self.edr_times[-1] - 60.0
            valid_data = [(t, a) for t, a in zip(self.edr_times, self.edr_amps) if t > cutoff]
            self.edr_times = [v[0] for v in valid_data]
            self.edr_amps = [v[1] for v in valid_data]

    def _calculate_rr_intervals(self, absolute_peaks):
        """حساب فترات RR وتنظيفها من الضوضاء (300ms - 2000ms)"""
        rr_intervals_ms = []
        if self.last_peak_absolute_time > 0:
            rr_time_sec = (absolute_peaks[0] - self.last_peak_absolute_time) / self.sample_rate
            rr_ms = rr_time_sec * 1000.0
            if 300 < rr_ms < 2000:
                rr_intervals_ms.append(rr_ms)
        
        for i in range(1, len(absolute_peaks)):
            rr_time_sec = (absolute_peaks[i] - absolute_peaks[i-1]) / self.sample_rate
            rr_ms = rr_time_sec * 1000.0
            if 300 < rr_ms < 2000:
                rr_intervals_ms.append(rr_ms)
        return rr_intervals_ms

    def _calculate_bpm(self, rr_intervals_ms):
        """حساب معدل ضربات القلب اللحظي"""
        latest_rr_sec = rr_intervals_ms[-1] / 1000.0 if rr_intervals_ms else 1.0
        return int(60 / latest_rr_sec) if rr_intervals_ms else 0

    def _map_ecg_peaks_to_ui(self, peaks, smoothed_data, buffer_len):
        """تحويل إحداثيات القمم لتناسب نافذة الرسم في الواجهة (1000 عينة)"""
        ui_window_size = 1000  
        offset = buffer_len - ui_window_size  
        x_indices = [int(p - offset) for p in peaks if p >= offset]
        y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
        return x_indices, y_values

    def _process_edr_and_respiration(self):
        """المعالج الرئيسي لإشارة التنفس: استيفاء، فلترة، اكتشاف القمم، وحساب المعدل"""
        edr_t_ui, edr_signal_ui, breath_x, breath_y = [], [], [], []
        brpm = 0.0

        if len(self.edr_times) <= 10:
            return edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm

        try:
            # 1. استيفاء الإشارة (Interpolation)
            f = interp1d(self.edr_times, self.edr_amps, kind='cubic', fill_value="extrapolate")
            t_uniform = np.arange(self.edr_times[0], self.edr_times[-1], 0.25) 
            edr_signal = f(t_uniform)
            
            # 2. فلترة إشارة التنفس
            edr_filtered = self._butter_bandpass_filter(edr_signal, 0.05, 0.6, 4.0)
            
            # 3. التحقق من وجود تنفس حقيقي (تجاهل كتم النفس/الخط المسطح)
            breath_peaks = self._detect_breath_peaks(edr_filtered)
            
            # 4. حساب معدل التنفس
            brpm = self._calculate_brpm_from_peaks(breath_peaks)
            
            # 5. تجهيز البيانات للواجهة (آخر 30 ثانية)
            ui_cutoff = t_uniform[-1] - 30.0
            ui_mask = t_uniform >= ui_cutoff
            edr_t_ui = t_uniform[ui_mask].tolist()
            edr_signal_ui = edr_filtered[ui_mask].tolist()
            
            for bp in breath_peaks:
                if t_uniform[bp] >= ui_cutoff:
                    breath_x.append(t_uniform[bp])
                    breath_y.append(edr_filtered[bp])            
        except Exception as e:
            print(f"EDR Calculation Error: {e}") 
        
        return edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm

    def _detect_breath_peaks(self, edr_filtered):
        """اكتشاف قمم التنفس باستخدام النطاق الديناميكي وتجاهل الضوضاء"""
        p95 = np.percentile(edr_filtered, 95)
        p5 = np.percentile(edr_filtered, 5)
        signal_range = p95 - p5 
        max_abs_amp = np.max(np.abs(edr_filtered))
        
        # شرط الخط المسطح (Apnea/Flatline)
        if max_abs_amp > 0 and signal_range < (max_abs_amp * 0.15):
            return []
        
        min_prominence = signal_range * 0.25
        breath_peaks, _ = find_peaks(edr_filtered, distance=8, prominence=min_prominence)
        return breath_peaks

    def _calculate_brpm_from_peaks(self, breath_peaks):
        """حساب عدد الأنفاس في الدقيقة من القمم المكتشفة"""
        if len(breath_peaks) > 1:
            breath_intervals_sec = np.diff(breath_peaks) * 0.25 
            avg_interval = np.mean(breath_intervals_sec)
            brpm = 60.0 / avg_interval
            if not (3.0 < brpm < 35.0): 
                return 0.0
            return brpm
        return 0.0

    def _butter_bandpass_filter(self, data, lowcut, highcut, fs, order=3):
        nyquist = 0.5 * fs
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        return filtfilt(b, a, data)

    def stop(self):
        self.is_running = False
        self.wait()


class ECGService(QObject):
    """منسق الخيوط وحساب مؤشر انقطاع التنفس المتقدم (HRV-based Apnea Index)"""
    live_chunk_ready = pyqtSignal(list)
    bpm_updated = pyqtSignal(int)
    rr_updated = pyqtSignal(list)
    brpm_updated = pyqtSignal(float)
    hrv_updated = pyqtSignal(float)
    edr_graph_updated = pyqtSignal(list, list, list, list)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)
    sensor_status_changed = pyqtSignal(bool, str)
    apnea_index_updated = pyqtSignal(float)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate

        # إعدادات الفلتر الحي للواجهة
        nyquist = 0.5 * self.sample_rate
        self.live_b, self.live_a = butter(2, [0.5 / nyquist, 40.0 / nyquist], btype='band')
        self.live_zi = lfilter_zi(self.live_b, self.live_a)
        self.is_first_chunk = True
        self.brpm_history = []

        # متغيرات لتجميع العينات الفردية في حزم (Chunks)
        self._live_buffer = []
        self._chunk_size = 10

        # حالة حساب HRV ومؤشر انقطاع التنفس
        self.rr_history = deque(maxlen=150)
        self.baseline_rmssd = deque(maxlen=60)
        self.baseline_sdrr = deque(maxlen=60)
        self.ai_history = deque(maxlen=60)
        self.consecutive_apnea_windows = 0
        self.apnea_event_count = 0

        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        self.peak_detector = ECGPeakDetector(sample_rate=self.sample_rate)
        self.peak_detector.start()

        self.reader.new_sample_ready.connect(self._process_live_sample)
        self.reader.buffer_updated.connect(self.peak_detector.add_buffer)
        self.peak_detector.analysis_results.connect(self._handle_analysis_results)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)

    def start_monitoring(self): self.reader.start()
    def stop_monitoring(self):
        self.reader.stop()
        self.peak_detector.stop()

    # =====================================================================
    # دوال استقبال وتوجيه البيانات
    # =====================================================================
    def _process_live_sample(self, value: int):
        """تجميع العينات الفردية في حزم وتطبيق الفلتر الحي"""
        self._live_buffer.append(value)
        if len(self._live_buffer) >= self._chunk_size:
            if self.is_first_chunk:
                self.live_zi = self.live_zi * self._live_buffer[0]
                self.is_first_chunk = False
                
            filtered_chunk, self.live_zi = lfilter(self.live_b, self.live_a, self._live_buffer, zi=self.live_zi)
            clean_chunk = [int(val + 512) for val in filtered_chunk]
            
            self.live_chunk_ready.emit(clean_chunk)
            self._live_buffer = []

    def _handle_analysis_results(self, bpm, x_peaks, y_peaks, rr_intervals_ms, 
                                 edr_t, edr_sig, breath_x, breath_y, brpm):
        """استقبال نتائج الخيط الثاني وتوزيعها على الواجهة ومنطق التحليل"""
        # 1. تحديث الواجهة بالبيانات الأساسية
        self.bpm_updated.emit(bpm)
        self.rr_updated.emit(rr_intervals_ms)
        self.peaks_detected.emit(x_peaks, y_peaks)
        if edr_t:
            self.edr_graph_updated.emit(edr_t, edr_sig, breath_x, breath_y)

        # 2. تحديث معدل التنفس
        self._update_and_emit_brpm(brpm)

        # 3. معالجة RR وتقييم انقطاع التنفس
        if rr_intervals_ms:
            self._process_rr_for_hrv(rr_intervals_ms)

    # =====================================================================
    # دوال حساب معدل التنفس (BrPM)
    # =====================================================================
    def _update_and_emit_brpm(self, brpm):
        """تنعيم معدل التنفس باستخدام المتوسط المتحرك وإرساله للواجهة"""
        if brpm > 0:
            self.brpm_history.append(brpm)
            if len(self.brpm_history) > 6:
                self.brpm_history.pop(0)
            smoothed_brpm = sum(self.brpm_history) / len(self.brpm_history)
            self.brpm_updated.emit(smoothed_brpm)
        else:
            self.brpm_updated.emit(0.0)

    # =====================================================================
    # دوال حساب HRV ومؤشر انقطاع التنفس (Apnea Index)
    # =====================================================================
    def _process_rr_for_hrv(self, rr_intervals_ms):
        """إضافة فترات RR للسجل واستدعاء التقييم إذا توفر حد أدنى من البيانات"""
        for rr in rr_intervals_ms:
            self.rr_history.append(rr)
        
        if len(self.rr_history) >= 30:
            self._evaluate_apnea_index()

    def _evaluate_apnea_index(self):
        """المعالج الرئيسي لمؤشر انقطاع التنفس (يوجه العمليات الفرعية)"""
        current_rr = list(self.rr_history)
        rmssd_t, sdrr_t = self._calculate_hrv_features(current_rr)
        
        self.hrv_updated.emit(rmssd_t)
        if rmssd_t == 0 or sdrr_t == 0:
            return

        z_rmssd, z_sdrr = self._update_baseline_and_calculate_z_scores(rmssd_t, sdrr_t)
        if z_rmssd is None:  # لم يتوفر خط أساس كافٍ بعد
            return

        ai = self._calculate_apnea_index_score(z_rmssd, z_sdrr)
        self.apnea_index_updated.emit(ai)

        self._run_apnea_state_machine(ai)

    def _calculate_hrv_features(self, rr_list):
        """حساب مؤشرات التغير في نبضات القلب (RMSSD و SDRR)"""
        rmssd = self._calculate_rmssd(rr_list)
        sdrr = self._calculate_sdrr(rr_list)
        return rmssd, sdrr

    def _update_baseline_and_calculate_z_scores(self, rmssd_t, sdrr_t):
        """تحديث خط الأساس المتحرك وحساب الانحراف المعياري (Z-Score)"""
        self.baseline_rmssd.append(rmssd_t)
        self.baseline_sdrr.append(sdrr_t)
        
        if len(self.baseline_rmssd) < 10:
            return None, None

        med_rmssd = np.median(self.baseline_rmssd)
        mad_rmssd = self._calculate_mad(self.baseline_rmssd)
        med_sdrr = np.median(self.baseline_sdrr)
        mad_sdrr = self._calculate_mad(self.baseline_sdrr)

        z_rmssd = (rmssd_t - med_rmssd) / (1.4826 * mad_rmssd)
        z_sdrr = (sdrr_t - med_sdrr) / (1.4826 * mad_sdrr)
        return z_rmssd, z_sdrr

    def _calculate_apnea_index_score(self, z_rmssd, z_sdrr):
        """حساب درجة مؤشر انقطاع التنفس (المعادلة الرياضية)"""
        return max(0.0, -z_rmssd) * (1.0 + max(0.0, z_sdrr))

    def _run_apnea_state_machine(self, ai):
        """آلية منع الإنذار الكاذب (تتطلب استمرارية النمط لتأكيد الحدث)"""
        self.ai_history.append(ai)

        if len(self.ai_history) > 15:
            threshold = np.mean(self.ai_history) + 2.5 * np.std(self.ai_history)
            threshold = max(threshold, 2.5)
            
            if ai > threshold:
                self.consecutive_apnea_windows += 1
            else:
                self.consecutive_apnea_windows = 0

            if self.consecutive_apnea_windows >= 3:
                self.apnea_event_count += 1
                self.apnea_warning_triggered.emit(True, f"⚠️ انقطاع تنفس محتمل (HRV Pattern) #{self.apnea_event_count}")
                self.consecutive_apnea_windows = 0
            else:
                self.apnea_warning_triggered.emit(False, "نمط HRV طبيعي")

    # =====================================================================
    # دوال رياضية مساعدة (Helper Functions)
    # =====================================================================
    def _calculate_rmssd(self, rr_list):
        if len(rr_list) < 2: return 0.0
        diff_rr = np.diff(rr_list)
        return float(np.sqrt(np.mean(diff_rr**2)))

    def _calculate_sdrr(self, rr_list):
        if len(rr_list) < 2: return 0.0
        return float(np.std(rr_list))

    def _calculate_mad(self, data):
        if not data: return 1.0
        median = np.median(data)
        mad = float(np.median(np.abs(data - median)))
        return mad if mad > 0 else 1.0

    # =====================================================================
    # دوال إدارة حالة المستشعر
    # =====================================================================
    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.peak_detector.last_peak_absolute_time = 0
            self.peak_detector.edr_times = []
            self.peak_detector.edr_amps = []
            self.is_first_chunk = True
            self._live_buffer = []
            self.brpm_history.clear()
            self.rr_history.clear()
            self.baseline_rmssd.clear()
            self.baseline_sdrr.clear()
            self.ai_history.clear()
            self.consecutive_apnea_windows = 0
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")