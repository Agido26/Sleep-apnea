from PyQt6.QtCore import QObject, pyqtSignal
# Import ONLY from the Data Layer here
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np

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

        # Example placeholder for your peak detection logic
        # r_peaks = self.find_peaks_algorithm(data)
        # r_r_intervals = np.diff(r_peaks) / self.sample_rate
        
        # Simulated BPM calculation for demonstration:
        estimated_bpm = 72  # Replace with actual calculated BPM
        self.bpm_updated.emit(estimated_bpm)

        # Deterministic Apnea Screening Rule (Bradycardia/Tachycardia pattern check)
        # if self.detect_apnea_pattern(r_r_intervals):
        #     self.apnea_warning_triggered.emit(True, "WARNING: Apnea Pattern Detected!")
        # else:
        #     self.apnea_warning_triggered.emit(False, "Normal Breathing Pattern")

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected (Leads-Off)!")
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Connection Error: {error_msg}")