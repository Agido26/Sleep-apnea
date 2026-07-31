from PyQt6.QtCore import QObject, pyqtSignal
# Import ONLY from the Data Layer here
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

class ECGService(QObject):
    """
    Business Logic Layer:
    Acts as the mediator between raw serial acquisition and the UI.
    Performs signal processing, peak detection, and apnea screening.
    """
    # Signals sent ONLY to the UI Layer
   # Signals sent ONLY to the UI Layer
    live_sample_ready = pyqtSignal(int)            # Continuous live sample
    bpm_updated = pyqtSignal(int)                  # Calculated Heart Rate
    hrv_updated = pyqtSignal(float)                # Calculated HRV (SDNN in ms)
    peaks_detected = pyqtSignal(list, list)        # (x_indices, y_values) for Red Dots
    apnea_warning_triggered = pyqtSignal(bool, str)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM3", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
        # State variables for the live-plot Exponential Moving Average (EMA) filter
        self.ema_value = 0.0
        self.ema_alpha = 0.3  # Smoothing factor (Lower = smoother but slightly delayed)

        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)

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
    def _butter_bandpass_filter(self, data, lowcut=0.5, highcut=40.0, fs=250.0, order=3):
        """
        Applies a zero-phase Butterworth bandpass filter.
        - lowcut (0.5Hz): Removes baseline wander (breathing/movement).
        - highcut (40Hz): Removes muscle noise and 50Hz/60Hz electrical grid interference.
        """
        nyquist = 0.5 * fs
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        # filtfilt applies the filter forward and backward to prevent phase shifting (keeps peaks exact)
        y = filtfilt(b, a, data)
        return y

    def _handle_raw_sample(self, value: int):
        """
        Applies a lightweight Exponential Moving Average (EMA) filter here
        before sending the sample to the UI for smooth, lag-free plotting.
        """
        if self.ema_value == 0.0:
            self.ema_value = value  # Initialize on first sample
        else:
            # Formula: (New Value * alpha) + (Old Value * (1 - alpha))
            self.ema_value = (self.ema_alpha * value) + ((1 - self.ema_alpha) * self.ema_value)
            
        # Send the smoothed integer to the UI dashboard
        self.live_sample_ready.emit(int(self.ema_value))


    def _analyze_10s_window(self, raw_buffer: list):
        """
        Core Deterministic Rule-Based Algorithm:
        Executes Bandpass Filter -> Peak Detection -> R-R Interval -> BPM -> HRV -> UI Verification.
        """
        raw_data = np.array(raw_buffer)

        # 1. APPLY BANDPASS FILTER to clean the window completely before math
        filtered_data = self._butter_bandpass_filter(raw_data, lowcut=0.5, highcut=40.0, fs=self.sample_rate)

        # 2. Dynamic Thresholding on the FILTERED data
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)

        # 3. Find peaks on the clean data
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)

        if len(peaks) > 1:
            # Calculate time difference between consecutive R-peaks in seconds
            r_r_intervals = np.diff(peaks) / self.sample_rate
            
            # --- BPM Calculation ---
            mean_rr = np.mean(r_r_intervals)
            real_bpm = int(60 / mean_rr)
            self.bpm_updated.emit(real_bpm)

            # --- NEW 1: HRV (SDNN) Calculation ---
            # Convert seconds to milliseconds, then find the Standard Deviation
            rr_intervals_ms = r_r_intervals * 1000.0
            hrv_sdnn = float(np.std(rr_intervals_ms))
            self.hrv_updated.emit(hrv_sdnn)

            # --- NEW 2: Peak Coordinates for UI (Red Dots) ---
            # EXTREMELY IMPORTANT: We use X-indices from 'peaks', but grab the Y-values 
            # from 'raw_data' so the dots perfectly align with the live UI line!
            x_indices = peaks.tolist()
            y_values = raw_data[peaks].tolist()
            self.peaks_detected.emit(x_indices, y_values)

            # --- APNEA DETECTION LOGIC (Placeholder for next step) ---
            # if we see a standard deviation in r_r_intervals that matches the Bradycardia/Tachycardia pattern:
            #     self.apnea_warning_triggered.emit(True, "WARNING: Apnea Pattern Detected!")
            
        else:
            # Not enough peaks found in 10 seconds (Sensor might be disconnected or noisy)
            self.bpm_updated.emit(0)
            self.hrv_updated.emit(0.0)
            self.peaks_detected.emit([], []) # Clear red dots if sensor is off
            
    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected (Leads-Off)!")
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Connection Error: {error_msg}")