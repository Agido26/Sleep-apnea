import queue
import numpy as np
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
from scipy.signal import find_peaks, butter, filtfilt, lfilter, lfilter_zi
from scipy.interpolate import interp1d

class ECGPeakDetector(QThread):
    """Thread 2: Peak detection, RR, and EDR extraction"""
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

    def _process_buffer(self, raw_buffer, smoothed_buffer):
        raw_data = np.array(raw_buffer)
        smoothed_data = np.array(smoothed_buffer)

        filtered_data, peaks = self._detect_r_peaks(raw_data)
        self.absolute_sample_count += len(raw_data)

        if len(peaks) > 0:
            absolute_peaks = [int(p) + self.absolute_sample_count - len(raw_data) for p in peaks]
            self._update_edr_history(peaks, filtered_data, absolute_peaks)
            rr_intervals_ms = self._calculate_rr_intervals(absolute_peaks)
            self.last_peak_absolute_time = absolute_peaks[-1]
            real_bpm = self._calculate_bpm(rr_intervals_ms)
            x_indices, y_values = self._map_ecg_peaks_to_ui(peaks, smoothed_data, len(raw_data))
            edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm = self._process_edr_and_respiration()

            self.analysis_results.emit(real_bpm, x_indices, y_values, rr_intervals_ms, 
                                       edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm)
        else:
            self.analysis_results.emit(0, [], [], [], [], [], [], [], 0.0)

    def _detect_r_peaks(self, raw_data):
        filtered_data = self._butter_bandpass_filter(raw_data, 0.5, 40.0, self.sample_rate)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)
        return filtered_data, peaks

    def _update_edr_history(self, peaks, filtered_data, absolute_peaks):
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
        rr_intervals_ms = []
        if self.last_peak_absolute_time > 0:
            rr_time_sec = (absolute_peaks[0] - self.last_peak_absolute_time) / self.sample_rate
            rr_ms = rr_time_sec * 1000.0
            if 300 < rr_ms < 2000: rr_intervals_ms.append(rr_ms)
        
        for i in range(1, len(absolute_peaks)):
            rr_time_sec = (absolute_peaks[i] - absolute_peaks[i-1]) / self.sample_rate
            rr_ms = rr_time_sec * 1000.0
            if 300 < rr_ms < 2000: rr_intervals_ms.append(rr_ms)
        return rr_intervals_ms

    def _calculate_bpm(self, rr_intervals_ms):
        latest_rr_sec = rr_intervals_ms[-1] / 1000.0 if rr_intervals_ms else 1.0
        return int(60 / latest_rr_sec) if rr_intervals_ms else 0

    def _map_ecg_peaks_to_ui(self, peaks, smoothed_data, buffer_len):
        ui_window_size = 1000  
        offset = buffer_len - ui_window_size  
        x_indices = [int(p - offset) for p in peaks if p >= offset]
        y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
        return x_indices, y_values

    def _process_edr_and_respiration(self):
        edr_t_ui, edr_signal_ui, breath_x, breath_y = [], [], [], []
        brpm = 0.0

        if len(self.edr_times) <= 10:
            return edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm

        try:
            f = interp1d(self.edr_times, self.edr_amps, kind='cubic', fill_value="extrapolate")
            t_uniform = np.arange(self.edr_times[0], self.edr_times[-1], 0.25) 
            edr_signal = f(t_uniform)
            
            edr_filtered = self._butter_bandpass_filter(edr_signal, 0.15, 0.4, 4.0)
            breath_peaks = self._detect_breath_peaks(edr_filtered)
            
            # --- ACCURACY IMPROVEMENT: Median Filtering & Outlier Rejection ---
            brpm = self._calculate_brpm_from_peaks(breath_peaks)
            
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
        p95 = np.percentile(edr_filtered, 95)
        p5 = np.percentile(edr_filtered, 5)
        signal_range = p95 - p5 
        max_abs_amp = np.max(np.abs(edr_filtered))
        
        if max_abs_amp > 0 and signal_range < (max_abs_amp * 0.15):
            return []
        
        min_prominence = signal_range * 0.25
        breath_peaks, _ = find_peaks(edr_filtered, distance=8, prominence=min_prominence)
        return breath_peaks

    def _calculate_brpm_from_peaks(self, breath_peaks):
        """
        ACCURACY IMPROVEMENT:
        1. Converts intervals to BrPM.
        2. Rejects outliers (faster than 40 BrPM or slower than 5 BrPM).
        3. Uses Median instead of Mean to ignore double-detected noise.
        """
        if len(breath_peaks) > 1:
            breath_intervals_sec = np.diff(breath_peaks) * 0.25 
            brpm_values = 60.0 / breath_intervals_sec
            
            # Outlier rejection
            valid_brpm = [b for b in brpm_values if 5.0 < b < 40.0]
            
            if valid_brpm:
                return float(np.median(valid_brpm))
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
    """Coordinates threads and calculates Apnea Index"""
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

        nyquist = 0.5 * self.sample_rate
        self.live_b, self.live_a = butter(2, [0.5 / nyquist, 40.0 / nyquist], btype='band')
        self.live_zi = lfilter_zi(self.live_b, self.live_a)
        self.is_first_chunk = True

        self._live_buffer = []
        self._chunk_size = 10

        self.rr_history = deque(maxlen=150)
        self.baseline_rmssd = deque(maxlen=60)
        self.baseline_sdrr = deque(maxlen=60)
        self.ai_history = deque(maxlen=60)
        self.consecutive_apnea_windows = 0
        self.apnea_event_count = 0
        self.apnea_cooldown = 0 

        # --- STABILITY IMPROVEMENT: BrPM Smoothing State ---
        self.last_valid_brpm = 0.0
        self.ema_brpm = 0.0
        self.last_emitted_brpm = 0.0
        self.brpm_grace_counter = 0
        self.BRPM_GRACE_LIMIT = 3      # Hold last value for 3 updates (~3 seconds)
        self.BRPM_SLEW_RATE = 2.0      # Max change of 2 BrPM per update
        self.BRPM_EMA_ALPHA = 0.3      # Smoothing factor

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

    def _process_live_sample(self, value: int):
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
                                 edr_t, edr_sig, breath_x, breath_y, raw_brpm):
        self.bpm_updated.emit(bpm)
        self.rr_updated.emit(rr_intervals_ms)
        self.peaks_detected.emit(x_peaks, y_peaks)
        if edr_t:
            self.edr_graph_updated.emit(edr_t, edr_sig, breath_x, breath_y)

        # --- STABILITY IMPROVEMENT: Apply Smoothing Pipeline ---
        self._update_and_emit_brpm(raw_brpm)

        if rr_intervals_ms:
            self._process_rr_for_hrv(rr_intervals_ms)

    def _update_and_emit_brpm(self, raw_brpm):
        """
        STABILITY IMPROVEMENT:
        1. Zero-hold grace period.
        2. Exponential Moving Average (EMA).
        3. Slew-rate limiter.
        """
        # 1. Zero-hold grace period
        if raw_brpm == 0.0:
            self.brpm_grace_counter += 1
            if self.brpm_grace_counter < self.BRPM_GRACE_LIMIT:
                # Still in grace period, emit last valid smoothed value
                self.brpm_updated.emit(self.ema_brpm if self.ema_brpm > 0 else self.last_valid_brpm)
                return
            else:
                # Grace period over, signal is truly lost
                self.brpm_updated.emit(0.0)
                self.last_valid_brpm = 0.0
                self.ema_brpm = 0.0
                self.last_emitted_brpm = 0.0
                return
        else:
            # Reset grace counter on valid signal
            self.brpm_grace_counter = 0
            self.last_valid_brpm = raw_brpm

        # 2. Exponential Moving Average (EMA)
        if self.ema_brpm == 0.0:
            self.ema_brpm = raw_brpm
        else:
            self.ema_brpm = (self.BRPM_EMA_ALPHA * raw_brpm) + ((1 - self.BRPM_EMA_ALPHA) * self.ema_brpm)

        # 3. Slew-rate limiter
        if self.last_emitted_brpm > 0:
            diff = self.ema_brpm - self.last_emitted_brpm
            if abs(diff) > self.BRPM_SLEW_RATE:
                self.ema_brpm = self.last_emitted_brpm + (self.BRPM_SLEW_RATE if diff > 0 else -self.BRPM_SLEW_RATE)
        
        self.last_emitted_brpm = self.ema_brpm
        self.brpm_updated.emit(self.ema_brpm)

    def _process_rr_for_hrv(self, rr_intervals_ms):
        """إضافة فترات RR وتنظيفها وإجراء التحليل عند توفر نافذة زمنية كافية"""
        for rr in rr_intervals_ms:
            self.rr_history.append(rr)
        
        # التقييم يبدأ عند توفر 40 نبضة على الأقل (حوالي 40-50 ثانية)
        if len(self.rr_history) >= 40:
            self._evaluate_apnea_index()

    def _evaluate_apnea_index(self):
        """المعالج الرئيسي لمؤشر Apnea Index المعدل"""
        current_rr = list(self.rr_history)
        rmssd_t, sdrr_t, sd2_ratio = self._calculate_hrv_features(current_rr)

        # إرسال RMSSD الدقيق للواجهة
        self.hrv_updated.emit(round(rmssd_t, 1))

        if rmssd_t == 0 or sdrr_t == 0:
            return

        z_rmssd, z_sdrr = self._update_baseline_and_calculate_z_scores(rmssd_t, sdrr_t)
        if z_rmssd is None:
            return

        # 3. معادلة Apnea Index معدلة تشمل انخفاض RMSSD مع ارتفاع SDRR ونسبة Poincaré
        ai = self._calculate_apnea_index_score(z_rmssd, z_sdrr, sd2_ratio)
        self.apnea_index_updated.emit(round(ai, 2))

        self._run_apnea_state_machine(ai)
    
    def _clean_rr_series(self, raw_rr_list):
        """1. إزالة الضربات الهاجرة (Ectopic Beats) والتشوهات النسبية"""
        if len(raw_rr_list) < 5:
            return raw_rr_list

        med_rr = np.median(raw_rr_list)
        clean_rr = []

        for i, rr in enumerate(raw_rr_list):
            # استبعاد النبضات التي تنحرف بأكثر من 20% عن وسيط النافذة
            if 0.8 * med_rr <= rr <= 1.2 * med_rr:
                if clean_rr and abs(rr - clean_rr[-1]) > (0.25 * clean_rr[-1]):
                    continue  # استبعاد التغيرات المفاجئة جداً بين نبضتين متتاليتين (Artifacts)
                clean_rr.append(rr)

        return clean_rr if len(clean_rr) >= 10 else list(raw_rr_list)

    def _calculate_hrv_features(self, rr_list):
        """2. حساب مؤشرات الوقت (RMSSD, SDRR) ومؤشرات Poincaré (SD1, SD2)"""
        clean_rr = self._clean_rr_series(rr_list)
        
        rmssd = self._calculate_rmssd(clean_rr)
        sdrr = self._calculate_sdrr(clean_rr)
        sd1, sd2_ratio = self._calculate_poincare_metrics(clean_rr)

        return rmssd, sdrr, sd2_ratio
    
    def _update_baseline_and_calculate_z_scores(self, rmssd_t, sdrr_t):
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

    def _calculate_poincare_metrics(self, clean_rr):
        """حساب نسبة SD1/SD2 للتفرقة بين التنشيط الجارسمبثاوي والسمبثاوي"""
        if len(clean_rr) < 4:
            return 0.0, 1.0

        diff_rr = np.diff(clean_rr)
        var_diff = np.var(diff_rr)
        var_rr = np.var(clean_rr)

        sd1 = np.sqrt(0.5 * var_diff)
        
        # حماية إضافية: في حالات الضوضاء الشديدة، قد تصبح sd2_sq سالبة بسبب أخطاء الفاصلة العائمة
        sd2_sq = (2 * var_rr) - (0.5 * var_diff)
        sd2 = np.sqrt(max(1e-5, sd2_sq)) # استخدام 1e-5 بدلاً من 1.0 للحفاظ على الدقة الرياضية

        # حماية من القسمة على صفر
        ratio = float(sd1 / sd2) if sd2 > 0 else 1.0 

        return float(sd1), ratio
    
    def _calculate_apnea_index_score(self, z_rmssd, z_sdrr, sd2_ratio):
        """
        حساب الدرجة:
        - انخفاض Z_RMSSD (قيمة سالبة) يشير إلى كتم النفس/انخفاض HRV المتردد
        - ارتفاع Z_SDRR (قيمة موجبة) يشير إلى عدم انتظام النبض الدوري (CVHR)
        """
        rmssd_drop = max(0.0, -z_rmssd)
        sdrr_surge = max(0.0, z_sdrr)
        
        # كتم النفس يقلل من نسبة SD1/SD2 (SD2 يرتفع بسبب التباين الكلي)
        poincare_factor = 1.2 if sd2_ratio < 0.5 else 1.0

        return float(rmssd_drop * (1.0 + sdrr_surge) * poincare_factor)

    def _run_apnea_state_machine(self, ai):
        self.ai_history.append(ai)

        if self.apnea_cooldown > 0:
            self.apnea_cooldown -= 1
            if ai < (np.mean(self.ai_history) if self.ai_history else 2.5):
                self.consecutive_apnea_windows = 0
            return

        if len(self.ai_history) > 15:
            threshold = np.mean(self.ai_history) + 2.5 * np.std(self.ai_history)
            threshold = max(threshold, 2.5)
            
            if ai > threshold:
                self.consecutive_apnea_windows += 1
            else:
                self.consecutive_apnea_windows = 0

            if self.consecutive_apnea_windows >= 3:
                self.apnea_event_count += 1
                self.apnea_warning_triggered.emit(True, f"⚠️ CONFIRMED APNEA EVENT #{self.apnea_event_count}")
                self.consecutive_apnea_windows = 0
                self.apnea_cooldown = 15
            else:
                self.apnea_warning_triggered.emit(False, "Normal HRV Pattern")

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

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.peak_detector.last_peak_absolute_time = 0
            self.peak_detector.edr_times = []
            self.peak_detector.edr_amps = []
            self.is_first_chunk = True
            self._live_buffer = []
            self.rr_history.clear()
            self.baseline_rmssd.clear()
            self.baseline_sdrr.clear()
            self.ai_history.clear()
            self.consecutive_apnea_windows = 0
            self.apnea_cooldown = 0
            # Reset BrPM stability state
            self.last_valid_brpm = 0.0
            self.ema_brpm = 0.0
            self.last_emitted_brpm = 0.0
            self.brpm_grace_counter = 0
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")