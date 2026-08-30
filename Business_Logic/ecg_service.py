import queue
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

class ECGPeakDetector(QThread):
    """Thread 2: Finds peaks and calculates robust RR intervals."""
    # Emits: (bpm, x_peaks_ui, y_peaks_ui, rr_intervals_ms)
    analysis_results = pyqtSignal(int, list, list, list) 
    
    def __init__(self, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        self.data_queue = queue.Queue()
        self.is_running = True
        
        # --- Robust RR Tracking Variables ---
        self.absolute_sample_count = 0 
        self.last_peak_absolute_time = 0 

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
            # --- ROBUST RR CALCULATION ---
            # Convert local buffer peaks to ABSOLUTE timeline peaks
            absolute_peaks = [int(p) + self.absolute_sample_count for p in peaks]
            
            rr_intervals_ms = []
            
            # 1. Calculate RR between the LAST peak of the previous buffer and the FIRST peak of this buffer
            if self.last_peak_absolute_time > 0:
                rr_time_sec = (absolute_peaks[0] - self.last_peak_absolute_time) / self.sample_rate
                rr_ms = rr_time_sec * 1000.0
                # Sanity filter: Human RR is between 300ms (200 BPM) and 2000ms (30 BPM)
                if 300 < rr_ms < 2000:
                    rr_intervals_ms.append(rr_ms)
            
            # 2. Calculate RR between peaks INSIDE the current buffer
            for i in range(1, len(absolute_peaks)):
                rr_time_sec = (absolute_peaks[i] - absolute_peaks[i-1]) / self.sample_rate
                rr_ms = rr_time_sec * 1000.0
                if 300 < rr_ms < 2000:
                    rr_intervals_ms.append(rr_ms)
            
            # Update trackers for the next buffer
            self.last_peak_absolute_time = absolute_peaks[-1]
            self.absolute_sample_count += len(raw_data)
            
            # Calculate Instantaneous BPM from the latest RR
            latest_rr_sec = rr_intervals_ms[-1] / 1000.0 if rr_intervals_ms else 1.0
            real_bpm = int(60 / latest_rr_sec) if rr_intervals_ms else 0
            
            # Map to UI (1000 samples)
            ui_window_size = 1000  
            offset = len(raw_data) - ui_window_size  
            x_indices = [int(p - offset) for p in peaks if p >= offset]
            y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
            
            # Emit: BPM, X-peaks, Y-peaks, RR-intervals
            self.analysis_results.emit(real_bpm, x_indices, y_values, rr_intervals_ms)
        else:
            self.absolute_sample_count += len(raw_data)
            self.analysis_results.emit(0, [], [], [])

    def stop(self):
        self.is_running = False
        self.wait()


class ECGService(QObject):
    """Coordinates threads and routes RR data to UI"""
    live_sample_ready = pyqtSignal(int)
    bpm_updated = pyqtSignal(int)
    rr_updated = pyqtSignal(list)  # NEW: Emits list of RR intervals in ms
    peaks_detected = pyqtSignal(list, list)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
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

    def _handle_analysis_results(self, bpm, x_peaks, y_peaks, rr_intervals_ms):
        """Receives data from Peak Detector and routes to UI."""
        self.bpm_updated.emit(bpm)
        self.rr_updated.emit(rr_intervals_ms)
        self.peaks_detected.emit(x_peaks, y_peaks)

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.peak_detector.last_peak_absolute_time = 0 # Reset RR tracking
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")