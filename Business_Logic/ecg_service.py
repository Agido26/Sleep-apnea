from PyQt6.QtCore import QObject, pyqtSignal
# Import ONLY from the Data Layer here
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
from scipy.signal import find_peaks

class ECGService(QObject):
    """
    Business Logic Layer:
    Acts as the mediator between raw serial acquisition and the UI.
    Performs signal processing, peak detection, and apnea screening.
    """
    # Signals sent ONLY to the UI Layer
    live_sample_ready = pyqtSignal(int)            # Raw or filtered sample for charting
    bpm_updated = pyqtSignal(int)                  # Calculated Heart Rate
    apnea_warning_triggered = pyqtSignal(bool, str) # (is_apnea, status_message)
    sensor_status_changed = pyqtSignal(bool, str)  # (is_connected, message)

    def __init__(self, port="COM3", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
        # 1. Instantiate the Data Layer receiver
        self.reader = ECGSerialReader(
            port=port, 
            baudrate=baudrate, 
            sample_rate=sample_rate
        )

        # 2. Wire Data Layer signals to internal Business Layer methods
        self.reader.new_sample_received.connect(self._handle_raw_sample)
        self.reader.buffer_updated.connect(self._analyze_10s_window)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)

    def start_monitoring(self):
        """Starts the data acquisition thread."""
        self.reader.start()

    def stop_monitoring(self):
        """Stops data acquisition safely."""
        self.reader.stop()

    # --- Internal Business Logic Methods ---

    def _handle_raw_sample(self, value: int):
        """
        Optional: Apply a light bandpass/moving-average filter here
        before sending the sample to the UI for smooth plotting.
        """
        self.live_sample_ready.emit(value)

    def _analyze_10s_window(self, raw_buffer: list):
        """
        Core Deterministic Rule-Based Algorithm:
        Executes Peak Detection -> R-R Interval -> BPM -> Apnea Screening.
        """
        data = np.array(raw_buffer)

        # A good rule of thumb: The R-peak is significantly higher than the mean signal
        threshold = np.mean(data) + 1.0 * np.std(data)
        
        # We assume a maximum heart rate of ~150 BPM, meaning peaks are at least 0.4 seconds apart
        # 0.4s * 250 samples/sec = 100 samples minimum distance between peaks
        min_distance = int(self.sample_rate * 0.4)

        peaks, _ = find_peaks(data, height=threshold, distance=min_distance)

        if len(peaks) > 1:
            # Calculate time difference between consecutive R-peaks in seconds
            r_r_intervals = np.diff(peaks) / self.sample_rate
            
            # Calculate Average Heart Rate (60 seconds / average R-R interval)
            mean_rr = np.mean(r_r_intervals)
            real_bpm = int(60 / mean_rr)
            
            self.bpm_updated.emit(real_bpm)

            # --- APNEA DETECTION LOGIC (Placeholder for next step) ---
            # if we see a standard deviation in r_r_intervals that matches the Bradycardia/Tachycardia pattern:
            #     self.apnea_warning_triggered.emit(True, "WARNING: Apnea Pattern Detected!")
        else:
            # Not enough peaks found in 10 seconds (Sensor might be disconnected or noisy)
            self.bpm_updated.emit(0)

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected (Leads-Off)!")
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Connection Error: {error_msg}")