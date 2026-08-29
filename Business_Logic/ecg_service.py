import queue
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

class ECGPeakDetector(QThread):
    """Thread 2: ONLY does heavy peak detection and HRV calculation in the background."""
    analysis_results = pyqtSignal(int, float, list, list)  # bpm, hrv, x_peaks, y_peaks
    
    def __init__(self, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        # Thread-safe queue to receive buffers from the serial thread
        self.data_queue = queue.Queue()
        self.is_running = True
    
    def add_buffer(self, raw_buffer, smoothed_buffer):
        """Add buffer to queue for processing (Thread-safe)"""
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
                # Wait for a buffer (blocks until available, preventing 100% CPU usage)
                raw_buffer, smoothed_buffer = self.data_queue.get(timeout=1)
                self._process_buffer(raw_buffer, smoothed_buffer)
            except queue.Empty:
                continue
    
    def _process_buffer(self, raw_buffer, smoothed_buffer):
        raw_data = np.array(raw_buffer)
        smoothed_data = np.array(smoothed_buffer)
        
        # 1. Heavy Bandpass filter
        filtered_data = self._butter_bandpass_filter(raw_data)
        
        # 2. Dynamic thresholding & Peak Detection
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)
        
        if len(peaks) > 1:
            # --- BPM & HRV Calculations ---
            r_r_intervals = np.diff(peaks) / self.sample_rate
            real_bpm = int(60 / np.mean(r_r_intervals))
            hrv_sdnn = float(np.std(r_r_intervals * 1000.0))
            
            # --- MAP PEAKS TO UI GRAPH ---
            ui_window_size = 1000  
            offset = len(raw_data) - ui_window_size  
            x_indices = [int(p - offset) for p in peaks if p >= offset]
            
            # Use smoothed buffer Y-value so dot sits directly on the blue line
            y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
            
            self.analysis_results.emit(real_bpm, hrv_sdnn, x_indices, y_values)
        else:
            self.analysis_results.emit(0, 0.0, [], [])
    
    def stop(self):
        self.is_running = False
        self.wait()


class ECGService(QObject):
    """Coordinates between Serial Thread and Peak Detection Thread"""
    live_sample_ready = pyqtSignal(int)
    bpm_updated = pyqtSignal(int)
    hrv_updated = pyqtSignal(float)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
        # Thread 1: Serial Reading
        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        
        # Thread 2: Peak Detection & Analysis
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

    def _handle_analysis_results(self, bpm, hrv, x_peaks, y_peaks):
        self.bpm_updated.emit(bpm)
        self.hrv_updated.emit(hrv)
        self.peaks_detected.emit(x_peaks, y_peaks)

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")