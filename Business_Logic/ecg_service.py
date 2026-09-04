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

    def _butter_bandpass_filter(self, data, lowcut, highcut, fs, order=3):
        nyquist = 0.5 * fs
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        return filtfilt(b, a, data)

    def run(self):
        while self.is_running:
            try:
                raw_buffer, smoothed_buffer = self.data_queue.get(timeout=1)
                self._process_buffer(raw_buffer, smoothed_buffer)
            except queue.Empty:
                continue

    def _process_buffer(self, raw_buffer, smoothed_buffer):
        raw_data = np.array(raw_buffer)
        smoothed_data = np.array(smoothed_buffer)

        # 1. تصفية الإشارة واكتشاف القمم
        filtered_data = self._butter_bandpass_filter(raw_data, 0.5, 40.0, self.sample_rate)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)

        if len(peaks) > 0:
            absolute_peaks = [int(p) + self.absolute_sample_count for p in peaks]
            
            # --- استخراج سعة القمم لحساب التنفس (EDR) ---
            new_amps = [float(filtered_data[p]) for p in peaks]
            new_times = [float(p) / self.sample_rate for p in absolute_peaks]
            self.edr_amps.extend(new_amps)
            self.edr_times.extend(new_times)

            if self.edr_times:
                cutoff = self.edr_times[-1] - 60.0
                valid_data = [(t, a) for t, a in zip(self.edr_times, self.edr_amps) if t > cutoff]
                self.edr_times = [v[0] for v in valid_data]
                self.edr_amps = [v[1] for v in valid_data]

            # --- حساب فترات RR وتنظيفها ---
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
                    
            self.last_peak_absolute_time = absolute_peaks[-1]
            self.absolute_sample_count += len(raw_data)

            latest_rr_sec = rr_intervals_ms[-1] / 1000.0 if rr_intervals_ms else 1.0
            real_bpm = int(60 / latest_rr_sec) if rr_intervals_ms else 0

            # تعيين القمم للرسم على الواجهة
            ui_window_size = 1000  
            offset = len(raw_data) - ui_window_size  
            x_indices = [int(p - offset) for p in peaks if p >= offset]
            y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]

            edr_t_ui, edr_signal_ui, breath_x, breath_y = [], [], [], []
            brpm = 0.0

            if len(self.edr_times) > 10:
                try:
                    # 1. Interpolate to uniform 4Hz
                    f = interp1d(self.edr_times, self.edr_amps, kind='cubic', fill_value="extrapolate")
                    t_uniform = np.arange(self.edr_times[0], self.edr_times[-1], 0.25) 
                    edr_signal = f(t_uniform)
                    
                    # 2. Bandpass Filter (0.05Hz to 0.6Hz)
                    edr_filtered = self._butter_bandpass_filter(edr_signal, 0.05, 0.6, 4.0)
                    
                    # ==========================================================
                    # التعديل الجذري: اكتشاف التنفس الحقيقي وتجاهل الضوضاء
                    # ==========================================================
                    
                    # أ. حساب "النطاق الحقيقي" للإشارة (Robust Range) باستخدام المئينات
                    # هذا يتجاهل القمم الشاذة (Outliers) ويقيس فقط سعة موجة التنفس الفعلية
                    p95 = np.percentile(edr_filtered, 95)
                    p5 = np.percentile(edr_filtered, 5)
                    signal_range = p95 - p5 
                    
                    # ب. حساب أقصى سعة مطلقة للإشارة (لجعل العتبات مستقلة عن قوة جهازك)
                    max_abs_amp = np.max(np.abs(edr_filtered))
                    
                    # ج. شرط "الخط المسطح" (Flatline / Apnea Check)
                    # إذا كان التذبذب الحقيقي (signal_range) أقل من 15% من أقصى سعة، 
                    # فهذا يعني أن الموجة مسطحة (أنت تحبس نفسك أو لا يوجد تنفس كافٍ)
                    if max_abs_amp > 0 and signal_range < (max_abs_amp * 0.15):
                        brpm = 0.0
                        breath_peaks = []
                    else:
                        # د. حساب عتبة البروز (Prominence) ديناميكياً
                        # يجب أن تكون القمة بارزة بمقدار 25% على الأقل من سعة الموجة الكلية 
                        # لكي تُحسب "نفساً". هذا يتجاهل تماماً التموجات الصغيرة للضوضاء.
                        min_prominence = signal_range * 0.25
                        
                        # هـ. اكتشاف القمز مع زيادة المسافة الدنيا 
                        # distance=8 عند تردد 4Hz تعني 2 ثانية (أي الحد الأقصى 30 نفس/دقيقة)
                        # هذا يمنع فيزيائياً احتساب الضوضاء السريعة كتنفس.
                        breath_peaks, _ = find_peaks(edr_filtered, distance=8, prominence=min_prominence)
                        
                        if len(breath_peaks) > 1:
                            breath_intervals_sec = np.diff(breath_peaks) * 0.25 
                            avg_interval = np.mean(breath_intervals_sec)
                            brpm = 60.0 / avg_interval
                            
                            # Sanity check: تضييق النطاق المقبول قليلاً
                            if not (3.0 < brpm < 35.0): 
                                brpm = 0.0
                        else:
                            brpm = 0.0
                            
                    # ==========================================================
                    
                    # Map to UI (Show last 30 seconds of respiration)
                    ui_cutoff = t_uniform[-1] - 30.0
                    ui_mask = t_uniform >= ui_cutoff
                    edr_t_ui = t_uniform[ui_mask].tolist()
                    edr_signal_ui = edr_filtered[ui_mask].tolist()
                    
                    breath_x, breath_y = [], []
                    for bp in breath_peaks:
                        if t_uniform[bp] >= ui_cutoff:
                            breath_x.append(t_uniform[bp])
                            breath_y.append(edr_filtered[bp])            
                except Exception as e:
                    print(f"EDR Calculation Error: {e}") 
            
            self.analysis_results.emit(real_bpm, x_indices, y_values, rr_intervals_ms, 
                                       edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm)
        else:
            self.absolute_sample_count += len(raw_data)
            self.analysis_results.emit(0, [], [], [], [], [], [], [], 0.0)

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

        # --- إعدادات الفلتر الحي للواجهة ---
        nyquist = 0.5 * self.sample_rate
        self.live_b, self.live_a = butter(2, [0.5 / nyquist, 40.0 / nyquist], btype='band')
        self.live_zi = lfilter_zi(self.live_b, self.live_a)
        self.is_first_chunk = True
        self.brpm_history = []

        # 🔴 التعديل الأهم: متغيرات لتجميع العينات الفردية في حزم (Chunks)
        self._live_buffer = []
        self._chunk_size = 10

        # --- حالة حساب HRV ومؤشر انقطاع التنفس ---
        self.rr_history = deque(maxlen=150)
        self.baseline_rmssd = deque(maxlen=60)
        self.baseline_sdrr = deque(maxlen=60)
        self.ai_history = deque(maxlen=60)
        self.consecutive_apnea_windows = 0
        self.apnea_event_count = 0

        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        self.peak_detector = ECGPeakDetector(sample_rate=self.sample_rate)
        self.peak_detector.start()

        # 🔴 الربط بـ new_sample_ready (عينة واحدة) بدلاً من new_chunk_ready
        self.reader.new_sample_ready.connect(self._process_live_sample)
        self.reader.buffer_updated.connect(self.peak_detector.add_buffer)
        self.peak_detector.analysis_results.connect(self._handle_analysis_results)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)

    def start_monitoring(self):
        self.reader.start()

    def stop_monitoring(self):
        self.reader.stop()
        self.peak_detector.stop()

    # 🔴 دالة جديدة لتجميع العينات الفردية في حزم (Chunks)
    def _process_live_sample(self, value: int):
        """تجمع العينات الفردية القادمة من الـ Serial Reader في حزم بحجم 10 لتطبيق الفلتر."""
        self._live_buffer.append(value)
        
        # عندما تكتمل الحزمة (10 عينات = 40 مللي ثانية)
        if len(self._live_buffer) >= self._chunk_size:
            if self.is_first_chunk:
                self.live_zi = self.live_zi * self._live_buffer[0]
                self.is_first_chunk = False
                
            # تطبيق الفلتر على الحزمة كاملة
            filtered_chunk, self.live_zi = lfilter(self.live_b, self.live_a, self._live_buffer, zi=self.live_zi)
            clean_chunk = [int(val + 512) for val in filtered_chunk]
            
            # إرسال الحزمة للواجهة (الواجهة ستستقبلها عبر store_live_chunk)
            self.live_chunk_ready.emit(clean_chunk)
            self._live_buffer = [] # تفريغ الحزمة لتجميع العينات التالية

    def _handle_analysis_results(self, bpm, x_peaks, y_peaks, rr_intervals_ms, 
                                 edr_t, edr_sig, breath_x, breath_y, brpm):
        # 1. تحديث الواجهة بالبيانات الأساسية
        self.bpm_updated.emit(bpm)
        self.rr_updated.emit(rr_intervals_ms)
        self.peaks_detected.emit(x_peaks, y_peaks)

        if brpm > 0:
            self.brpm_history.append(brpm)
            if len(self.brpm_history) > 6:
                self.brpm_history.pop(0)
            self.brpm_updated.emit(sum(self.brpm_history) / len(self.brpm_history))
        else:
            self.brpm_updated.emit(0.0)

        if edr_t:
            self.edr_graph_updated.emit(edr_t, edr_sig, breath_x, breath_y)

        # 2. المنطق المتقدم: حساب HRV ومؤشر انقطاع التنفس
        if rr_intervals_ms:
            for rr in rr_intervals_ms:
                self.rr_history.append(rr)
            
            if len(self.rr_history) >= 30:
                self._evaluate_apnea_index()

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

    def _evaluate_apnea_index(self):
        current_rr = list(self.rr_history)
        rmssd_t = self._calculate_rmssd(current_rr)
        sdrr_t = self._calculate_sdrr(current_rr)
        
        self.hrv_updated.emit(rmssd_t)

        if rmssd_t == 0 or sdrr_t == 0:
            return

        self.baseline_rmssd.append(rmssd_t)
        self.baseline_sdrr.append(sdrr_t)
        
        if len(self.baseline_rmssd) < 10:
            return

        med_rmssd = np.median(self.baseline_rmssd)
        mad_rmssd = self._calculate_mad(self.baseline_rmssd)
        med_sdrr = np.median(self.baseline_sdrr)
        mad_sdrr = self._calculate_mad(self.baseline_sdrr)

        z_rmssd = (rmssd_t - med_rmssd) / (1.4826 * mad_rmssd)
        z_sdrr = (sdrr_t - med_sdrr) / (1.4826 * mad_sdrr)

        ai = max(0.0, -z_rmssd) * (1.0 + max(0.0, z_sdrr))
        
        self.ai_history.append(ai)
        self.apnea_index_updated.emit(ai)

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

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.peak_detector.last_peak_absolute_time = 0
            self.peak_detector.edr_times = []
            self.peak_detector.edr_amps = []
            self.is_first_chunk = True
            self._live_buffer = [] # 🔴 تفريغ الحزمة المؤقتة عند فصل المستشعر
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