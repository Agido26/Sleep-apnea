import queue
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt
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
            
            # --- EDR: Interpolate, Filter, and Find Breath Peaks ---
            edr_t_ui, edr_signal_ui, breath_x, breath_y = [], [], [], []
            brpm = 0.0
            
            if len(self.edr_times) > 10:
                try:
                    # Interpolate to uniform 4Hz sampling rate
                    f = interp1d(self.edr_times, self.edr_amps, kind='cubic', fill_value="extrapolate")
                    t_uniform = np.arange(self.edr_times[0], self.edr_times[-1], 0.25) 
                    edr_signal = f(t_uniform)
                    
                    # Respiratory Bandpass Filter (0.15Hz - 0.4Hz)
                    edr_filtered = self._butter_bandpass_filter(edr_signal, 0.15, 0.4, 4.0)
                    
                    # Find breath peaks (minimum distance ~1.5s = 6 samples at 4Hz)
                    breath_peaks, _ = find_peaks(edr_filtered, distance=6)
                    
                    # --- Calculate Breaths Per Minute (BrPM) ---
                    if len(breath_peaks) > 1:
                        breath_intervals_sec = np.diff(breath_peaks) * 0.25 
                        avg_interval = np.mean(breath_intervals_sec)
                        brpm = 60.0 / avg_interval
                        
                        # Sanity check: Normal human breathing is 10-25 BrPM
                        if not (8.0 < brpm < 30.0):
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
                            
                except Exception:
                    pass

            # Emit everything including the new brpm
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
    # --- ALL REQUIRED SIGNALS ---
    live_sample_ready = pyqtSignal(int)
    bpm_updated = pyqtSignal(int)
    rr_updated = pyqtSignal(list)
    brpm_updated = pyqtSignal(float)  # NEW: Breaths Per Minute
    edr_graph_updated = pyqtSignal(list, list, list, list)  # NEW: (time, signal, breath_x, breath_y)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)  # FIXED: This was missing!
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        self.peak_detector = ECGPeakDetector(sample_rate=self.sample_rate)
        self.peak_detector.start()
        
        self.reader.new_sample_ready.connect(self.live_sample_ready.emit)
        self.reader.buffer_updated.connect(self.peak_detector.add_buffer)
        self.peak_detector.analysis_results.connect(self._handle_analysis_results)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)

    def start_monitoring(self):
        self.reader.start()

    def stop_monitoring(self):
        self.reader.stop()
        self.peak_detector.stop()

    def _handle_analysis_results(self, bpm, x_peaks, y_peaks, rr_intervals_ms, 
                                 edr_t, edr_sig, breath_x, breath_y, brpm):
        self.bpm_updated.emit(bpm)
        self.rr_updated.emit(rr_intervals_ms)
        self.brpm_updated.emit(brpm)  # NEW
        self.peaks_detected.emit(x_peaks, y_peaks)
        
        # Emit EDR data to UI
        if edr_t:
            self.edr_graph_updated.emit(edr_t, edr_sig, breath_x, breath_y)

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.peak_detector.last_peak_absolute_time = 0
            self.peak_detector.edr_times = []
            self.peak_detector.edr_amps = []
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")