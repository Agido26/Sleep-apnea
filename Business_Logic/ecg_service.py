import queue
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
# Added lfilter and lfilter_zi to your existing imports
from scipy.signal import find_peaks, butter, filtfilt, lfilter, lfilter_zi
from scipy.interpolate import interp1d

class ECGPeakDetector(QThread):
    """Thread 2: Finds peaks, calculates RR, and extracts EDR (Respiration)."""
    # Emits: (bpm, x_peaks_ui, y_peaks_ui, rr_intervals_ms, edr_time, edr_signal, breath_x, breath_y, brpm)
    analysis_results = pyqtSignal(int, list, list, list, list, list, list, list, float) 
    
    def __init__(self, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        self.data_queue = queue.Queue()
        self.is_running = True
        
        # Robust RR Tracking
        self.absolute_sample_count = 0 
        self.last_peak_absolute_time = 0 
        
        # EDR (Respiration) Tracking
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
        
        # 1. Filter & Detect Peaks
        filtered_data = self._butter_bandpass_filter(raw_data, 0.5, 40.0, self.sample_rate)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)
        
        if len(peaks) > 0:
            absolute_peaks = [int(p) + self.absolute_sample_count for p in peaks]
            
            # --- EDR: Extract Amplitudes and Absolute Times ---
            new_amps = [float(filtered_data[p]) for p in peaks]
            new_times = [float(p) / self.sample_rate for p in absolute_peaks]
            
            self.edr_amps.extend(new_amps)
            self.edr_times.extend(new_times)
            
            # Keep only the last 60 seconds for EDR calculation
            if self.edr_times:
                cutoff = self.edr_times[-1] - 60.0
                valid_data = [(t, a) for t, a in zip(self.edr_times, self.edr_amps) if t > cutoff]
                self.edr_times = [v[0] for v in valid_data]
                self.edr_amps = [v[1] for v in valid_data]

            # --- Robust RR Calculation ---
            rr_intervals_ms = []
            if self.last_peak_absolute_time > 0:
                rr_time_sec = (absolute_peaks[0] - self.last_peak_absolute_time) / self.sample_rate
                rr_ms = rr_time_sec * 1000.0
                if 300 < rr_ms < 2000: rr_intervals_ms.append(rr_ms)
            
            for i in range(1, len(absolute_peaks)):
                rr_time_sec = (absolute_peaks[i] - absolute_peaks[i-1]) / self.sample_rate
                rr_ms = rr_time_sec * 1000.0
                if 300 < rr_ms < 2000: rr_intervals_ms.append(rr_ms)
            
            self.last_peak_absolute_time = absolute_peaks[-1]
            self.absolute_sample_count += len(raw_data)
            
            latest_rr_sec = rr_intervals_ms[-1] / 1000.0 if rr_intervals_ms else 1.0
            real_bpm = int(60 / latest_rr_sec) if rr_intervals_ms else 0
            
            # Map ECG peaks to UI (1000 samples)
            ui_window_size = 1000  
            offset = len(raw_data) - ui_window_size  
            x_indices = [int(p - offset) for p in peaks if p >= offset]
            y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
            
            edr_t_ui, edr_signal_ui, breath_x, breath_y = [], [], [], []
            brpm = 0.0

            if len(self.edr_times) > 10:
                try:
                    # Interpolate to uniform 4Hz sampling rate
                    f = interp1d(self.edr_times, self.edr_amps, kind='cubic', fill_value="extrapolate")
                    t_uniform = np.arange(self.edr_times[0], self.edr_times[-1], 0.25) 
                    edr_signal = f(t_uniform)
                    
                    # التعديل 1: توسيع الفلتر ليسمح بترددات من 3 أنفاس (0.05Hz) إلى 36 نفساً (0.6Hz)
                    edr_filtered = self._butter_bandpass_filter(edr_signal, 0.05, 0.6, 4.0)
                    
                    # التعديل 2: حساب الانحراف المعياري للإشارة لمعرفة هل هناك تنفس حقيقي أم كتم نفس (مسطح)
                    signal_std = np.std(edr_filtered)
                    
                    # التعديل 3: إضافة prominence للبحث عن القمم الواضحة فقط وتجاهل الضوضاء أثناء كتم النفس
                    breath_peaks, _ = find_peaks(edr_filtered, distance=6, prominence=signal_std * 0.6)
                    
                    # --- Calculate Breaths Per Minute (BrPM) ---
                    if len(breath_peaks) > 1 and signal_std > 0.5: 
                        breath_intervals_sec = np.diff(breath_peaks) * 0.25 
                        avg_interval = np.mean(breath_intervals_sec)
                        brpm = 60.0 / avg_interval
                        
                        # Sanity check
                        if not (3.0 < brpm < 40.0):
                            brpm = 0.0
                    else:
                        brpm = 0.0

                    # Map to UI (Show last 30 seconds of respiration)
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
                    
                self.analysis_results.emit(real_bpm, x_indices, y_values, rr_intervals_ms, 
                                       edr_t_ui, edr_signal_ui, breath_x, breath_y, brpm)
            else:
                self.absolute_sample_count += len(raw_data)
                self.analysis_results.emit(0, [], [], [], [], [], [], [], 0.0)

    def stop(self):
        self.is_running = False
        self.wait()


class ECGService(QObject):
    """Coordinates threads and routes data to UI"""
    live_chunk_ready = pyqtSignal(list)
    bpm_updated = pyqtSignal(int)
    rr_updated = pyqtSignal(list)
    brpm_updated = pyqtSignal(float)
    edr_graph_updated = pyqtSignal(list, list, list, list)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
        # --- NEW: Real-Time IIR Filter Setup for UI Graph Chunks ---
        nyquist = 0.5 * self.sample_rate
        self.live_b, self.live_a = butter(2, [0.5 / nyquist, 40.0 / nyquist], btype='band')
        self.live_zi = lfilter_zi(self.live_b, self.live_a)
        self.is_first_chunk = True
        
        # --- NEW: Rolling Average for Breathing Rate (BrPM) Stabilization ---
        self.brpm_history = []
        
        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        self.peak_detector = ECGPeakDetector(sample_rate=self.sample_rate)
        self.peak_detector.start()
        
        # Intercept the chunk to apply lfilter before sending to UI
        self.reader.new_chunk_ready.connect(self._process_live_chunk)
        self.reader.buffer_updated.connect(self.peak_detector.add_buffer)
        self.peak_detector.analysis_results.connect(self._handle_analysis_results)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)

    def start_monitoring(self):
        self.reader.start()

    def stop_monitoring(self):
        self.reader.stop()
        self.peak_detector.stop()

    def _process_live_chunk(self, raw_chunk: list):
        """Applies the real-time continuous IIR filter to incoming chunks."""
        if not raw_chunk:
            return
            
        if self.is_first_chunk:
            # Initialize filter memory state on the very first sample
            self.live_zi = self.live_zi * raw_chunk[0]
            self.is_first_chunk = False
            
        # lfilter efficiently processes the entire chunk array at once
        filtered_chunk, self.live_zi = lfilter(self.live_b, self.live_a, raw_chunk, zi=self.live_zi)
        
        # Bandpass centers the wave at 0. Re-add 512 to center it on the UI (range 0-1023)
        clean_chunk = [int(val + 512) for val in filtered_chunk]
        self.live_chunk_ready.emit(clean_chunk)

    def _handle_analysis_results(self, bpm, x_peaks, y_peaks, rr_intervals_ms, 
                                 edr_t, edr_sig, breath_x, breath_y, brpm):
        self.bpm_updated.emit(bpm)
        self.rr_updated.emit(rr_intervals_ms)
        self.peaks_detected.emit(x_peaks, y_peaks)
        
        # --- NEW: Stabilize Respiration Rate (BrPM) using Rolling Average ---
        if brpm > 0:
            self.brpm_history.append(brpm)
            if len(self.brpm_history) > 6:  # Average the last 6 valid updates
                self.brpm_history.pop(0)
            smoothed_brpm = sum(self.brpm_history) / len(self.brpm_history)
            self.brpm_updated.emit(smoothed_brpm)
        else:
            self.brpm_updated.emit(0.0)
            
        # Emit EDR data to UI
        if edr_t:
            self.edr_graph_updated.emit(edr_t, edr_sig, breath_x, breath_y)

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.peak_detector.last_peak_absolute_time = 0
            self.peak_detector.edr_times = []
            self.peak_detector.edr_amps = []
            self.is_first_chunk = True # Reset filter state on reconnect
            self.brpm_history.clear()
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")