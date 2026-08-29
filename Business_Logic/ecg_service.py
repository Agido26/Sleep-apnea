import queue
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

class ECGPeakDetector(QThread):
    """Thread 2: Finds peaks and calculates instantaneous RR intervals."""
    # Emits: (bpm, hrv_sdnn, x_peaks_ui, y_peaks_ui, rr_intervals_ms, absolute_peak_times)
    analysis_results = pyqtSignal(int, float, list, list, list, list) 
    
    def __init__(self, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        self.data_queue = queue.Queue()
        self.is_running = True
        
        # Track absolute time to calculate accurate RR intervals across buffers
        self.absolute_sample_count = 0 
        self.peak_timestamps = [] # Stores absolute sample index of every detected peak

    def add_buffer(self, raw_buffer, smoothed_buffer):
        self.data_queue.put((raw_buffer, smoothed_buffer))

    def _butter_bandpass_filter(self, data, lowcut=0.5, highcut=40.0, fs=250.0, order=3):
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
        filtered_data = self._butter_bandpass_filter(raw_data)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)
        
        if len(peaks) > 1:
            # --- Calculate Absolute Peak Times ---
            # The peaks array contains indices relative to the current 10s buffer.
            # We add the absolute_sample_count to get their true timeline position.
            absolute_peaks = [p + self.absolute_sample_count for p in peaks]
            
            # Update the global counter
            self.absolute_sample_count += len(raw_data)
            
            # Add new peaks to our master timeline
            self.peak_timestamps.extend(absolute_peaks)
            
            # Keep only the last 60 seconds of peaks (60s * 250Hz = 15000 samples)
            cutoff = self.absolute_sample_count - (60 * self.sample_rate)
            self.peak_timestamps = [t for t in self.peak_timestamps if t > cutoff]
            
            # --- Calculate RR Intervals (in milliseconds) ---
            rr_intervals_ms = []
            for i in range(1, len(self.peak_timestamps)):
                rr_time_sec = (self.peak_timestamps[i] - self.peak_timestamps[i-1]) / self.sample_rate
                rr_intervals_ms.append(rr_time_sec * 1000.0)
            
            # --- Calculate Instantaneous BPM & HRV (SDNN) ---
            if len(rr_intervals_ms) > 0:
                mean_rr = np.mean(rr_intervals_ms) / 1000.0 # convert back to seconds
                real_bpm = int(60 / mean_rr)
                hrv_sdnn = float(np.std(rr_intervals_ms))
            else:
                real_bpm = 0
                hrv_sdnn = 0.0
                
            # --- Map Peaks to UI Graph (1000 samples) ---
            ui_window_size = 1000  
            offset = len(raw_data) - ui_window_size  
            x_indices = [int(p - offset) for p in peaks if p >= offset]
            y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
            
            # Emit everything to the Service Layer
            self.analysis_results.emit(real_bpm, hrv_sdnn, x_indices, y_values, rr_intervals_ms, self.peak_timestamps)
        else:
            self.absolute_sample_count += len(raw_data)
            self.analysis_results.emit(0, 0.0, [], [], [], self.peak_timestamps)

    def stop(self):
        self.is_running = False
        self.wait()


class ECGService(QObject):
    """Coordinates threads and runs the 60-second Apnea Detection Logic (Pathway A)"""
    live_sample_ready = pyqtSignal(int)
    bpm_updated = pyqtSignal(int)
    hrv_updated = pyqtSignal(float)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
        # Apnea Detection State (Pathway A)
        self.bpm_history = []       # Stores smoothed BPM over 60s
        self.apnea_event_count = 0  # Tally of detected apnea events
        
        # Thread 1: Serial Reading
        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        
        # Thread 2: Peak Detection
        self.peak_detector = ECGPeakDetector(sample_rate=self.sample_rate)
        self.peak_detector.start()
        
        # Wire signals
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

    def _handle_analysis_results(self, bpm, hrv, x_peaks, y_peaks, rr_intervals_ms, peak_timestamps):
        """Receives data from Peak Detector and runs the 60s Apnea Logic."""
        # 1. Update UI with basic metrics
        self.bpm_updated.emit(bpm)
        self.hrv_updated.emit(hrv)
        self.peaks_detected.emit(x_peaks, y_peaks)
        
        # 2. Pathway A: Apnea Detection (V-Shape Logic)
        if bpm > 0 and len(rr_intervals_ms) > 0:
            self._detect_apnea_v_shape(bpm, rr_intervals_ms)

    def _detect_apnea_v_shape(self, current_bpm, rr_intervals_ms):
        """
        Proposal Phase 3, Pathway A:
        Scans the 60-second window for Bradycardia (drop) followed by Tachycardia (spike).
        """
        # Add current BPM to history
        self.bpm_history.append(current_bpm)
        
        # Keep only the last 60 seconds of BPM data (approx 60 readings if updated every 1s)
        if len(self.bpm_history) > 60:
            self.bpm_history.pop(0)
            
        # We need at least 30 seconds of data to establish a baseline and detect a cycle
        if len(self.bpm_history) < 30:
            return

        # Calculate Baseline (Average BPM over the last 60s)
        baseline_bpm = np.mean(self.bpm_history)
        
        # Define Thresholds (Adjust these based on your real-world testing)
        bradycardia_threshold = baseline_bpm - 10  # Drop of 10 BPM
        tachycardia_threshold = baseline_bpm + 10  # Spike of 10 BPM
        
        # Look for the V-Shape in the last 30 seconds
        recent_history = self.bpm_history[-30:]
        
        has_brady = any(bpm < bradycardia_threshold for bpm in recent_history)
        has_tachy = any(bpm > tachycardia_threshold for bpm in recent_history)
        
        # Fusion Logic: If we see both a drop and a spike, it's a confirmed Apnea event
        if has_brady and has_tachy:
            self.apnea_event_count += 1
            self.apnea_warning_triggered.emit(True, f"⚠️ APNEA EVENT DETECTED! (Total: {self.apnea_event_count})")
            
            # Reset history to prevent double-counting the same event immediately
            self.bpm_history = [] 
        else:
            self.apnea_warning_triggered.emit(False, "Normal Breathing Pattern")

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.bpm_history = [] # Reset apnea tracking if sensor falls off
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")