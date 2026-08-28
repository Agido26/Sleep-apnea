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

        # Buffer to keep track of EMA-smoothed values for 10s analysis
        self.smoothed_buffer = []

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
            self.ema_value = float(value)  # Initialize on first sample
        else:
            # Formula: (New Value * alpha) + (Old Value * (1 - alpha))
            self.ema_value = (self.ema_alpha * value) + ((1 - self.ema_alpha) * self.ema_value)

        smoothed_int = int(self.ema_value)
        
        # Maintain a parallel smoothed buffer matching the serial buffer size (2500 samples)
        self.smoothed_buffer.append(smoothed_int)
        if len(self.smoothed_buffer) > (self.sample_rate * 10):
            self.smoothed_buffer.pop(0)   
        
        # Send the smoothed integer to the UI dashboard
        self.live_sample_ready.emit(int(smoothed_int))


    def _analyze_10s_window(self, raw_buffer: list):
        raw_data = np.array(raw_buffer)

        # 1. Bandpass filter for accurate R-peak detection
        filtered_data = self._butter_bandpass_filter(raw_data, lowcut=0.5, highcut=40.0, fs=self.sample_rate)

        # 2. Dynamic thresholding
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)

        # 3. Detect peaks on filtered signal
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)

        if len(peaks) > 1:
            # --- BPM & HRV Calculations ---
            r_r_intervals = np.diff(peaks) / self.sample_rate
            mean_rr = np.mean(r_r_intervals)
            real_bpm = int(60 / mean_rr)
            self.bpm_updated.emit(real_bpm)

            rr_intervals_ms = r_r_intervals * 1000.0
            hrv_sdnn = float(np.std(rr_intervals_ms))
            self.hrv_updated.emit(hrv_sdnn)

            # --- MAP PEAKS TO UI GRAPH (Fix X and Y shifts) ---
            ui_window_size = 1000  # Matching maxlen of deque in ecg_dashboard.py
            buffer_len = len(raw_buffer)
            offset = buffer_len - ui_window_size  # 2500 - 1000 = 1500

            x_indices = []
            y_values = []
            smoothed_arr = np.array(self.smoothed_buffer)

            for p in peaks:
                # Only include peaks that fall inside the current 1000-sample UI window
                if p >= offset:
                    rel_x = p - offset  # Adjust X relative to graph window (0 to 999)
                    x_indices.append(rel_x)
                    # Use smoothed buffer Y-value so dot sits directly on the blue line
                    y_values.append(int(smoothed_arr[p]))

            self.peaks_detected.emit(x_indices, y_values)
        else:
            self.bpm_updated.emit(0)
            self.hrv_updated.emit(0.0)
            self.peaks_detected.emit([], [])

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected (Leads-Off)!")
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Connection Error: {error_msg}")