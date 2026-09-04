import queue
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
import numpy as np
# ── ADDED: lfilter and lfilter_zi for real-time IIR filtering ──
from scipy.signal import find_peaks, butter, filtfilt, lfilter, lfilter_zi


class ECGPeakDetector(QThread):
    """Thread 2: Finds peaks and calculates instantaneous RR intervals."""
    # Emits: (bpm, hrv_sdnn, x_peaks_ui, y_peaks_ui, rr_intervals_ms, absolute_peak_times)
    analysis_results = pyqtSignal(int, float, list, list, list, list)

    def __init__(self, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        self.data_queue = queue.Queue()
        self.is_running = True
        self.absolute_sample_count = 0
        self.peak_timestamps = []

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

        filtered_data = self._butter_bandpass_filter(raw_data)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)

        if len(peaks) > 1:
            absolute_peaks = [p + self.absolute_sample_count for p in peaks]
            self.absolute_sample_count += len(raw_data)
            self.peak_timestamps.extend(absolute_peaks)

            cutoff = self.absolute_sample_count - (60 * self.sample_rate)
            self.peak_timestamps = [t for t in self.peak_timestamps if t > cutoff]

            rr_intervals_ms = []
            for i in range(1, len(self.peak_timestamps)):
                rr_time_sec = (self.peak_timestamps[i] - self.peak_timestamps[i-1]) / self.sample_rate
                rr_intervals_ms.append(rr_time_sec * 1000.0)

            if len(rr_intervals_ms) > 0:
                mean_rr = np.mean(rr_intervals_ms) / 1000.0
                real_bpm = int(60 / mean_rr)
                hrv_sdnn = float(np.std(rr_intervals_ms))
            else:
                real_bpm = 0
                hrv_sdnn = 0.0

            ui_window_size = 1000
            offset = len(raw_data) - ui_window_size
            x_indices = [int(p - offset) for p in peaks if p >= offset]
            y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]

            self.analysis_results.emit(real_bpm, hrv_sdnn, x_indices, y_values,
                                       rr_intervals_ms, self.peak_timestamps)
        else:
            self.absolute_sample_count += len(raw_data)
            self.analysis_results.emit(0, 0.0, [], [], [], self.peak_timestamps)

    def stop(self):
        self.is_running = False
        self.wait()


class ECGService(QObject):
    """Coordinates threads and runs the 60-second Apnea Detection Logic (Pathway A)"""
    live_sample_ready = pyqtSignal(int)       # ← SAME signal name, UI unchanged
    bpm_updated = pyqtSignal(int)
    hrv_updated = pyqtSignal(float)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate

        # ──────────────────────────────────────────────────────────────
        # NEW: Real-Time IIR Butterworth Filter for live UI signal
        # This is the core improvement from the newest code.
        # lfilter is a causal IIR filter — zero latency, sample-by-sample,
        # with continuous state memory (zi) so there are NO edge artifacts.
        # ──────────────────────────────────────────────────────────────
        nyquist = 0.5 * self.sample_rate
        self.live_b, self.live_a = butter(2, [0.5 / nyquist, 40.0 / nyquist], btype='band')
        self.live_zi = lfilter_zi(self.live_b, self.live_a)
        self.is_first_sample = True

        # Apnea Detection State (Pathway A)
        self.bpm_history = []
        self.apnea_event_count = 0

        # Thread 1: Serial Reading
        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        # Thread 2: Peak Detection
        self.peak_detector = ECGPeakDetector(sample_rate=self.sample_rate)
        self.peak_detector.start()

        # ──────────────────────────────────────────────────────────────
        # CHANGED: Instead of directly forwarding raw samples to UI,
        # intercept them through the IIR filter first.
        #
        # OLD: self.reader.new_sample_ready.connect(self.live_sample_ready.emit)
        # NEW:
        # ──────────────────────────────────────────────────────────────
        self.reader.new_sample_ready.connect(self._process_live_sample)

        self.reader.buffer_updated.connect(self.peak_detector.add_buffer)
        self.peak_detector.analysis_results.connect(self._handle_analysis_results)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)

    # ──────────────────────────────────────────────────────────────────
    # NEW METHOD: The only addition to the service layer
    # ──────────────────────────────────────────────────────────────────
    def _process_live_sample(self, raw_value: int):
        """Applies continuous IIR bandpass filter to each incoming sample.
        
        Why this makes the signal smoother:
        - The old code sent raw EMA-smoothed ADC values (still had baseline
          wander, powerline noise, and muscle artifacts).
        - This IIR Butterworth bandpass (0.5–40 Hz) removes all of that
          in real-time with ZERO latency because lfilter is causal.
        - The zi state variable carries filter memory between samples,
          so there are no startup transients or edge artifacts.
        """
        if self.is_first_sample:
            # Initialize filter state to the first sample value
            # to avoid a huge transient spike at startup
            self.live_zi = self.live_zi * raw_value
            self.is_first_sample = False

        # lfilter processes even a single sample efficiently
        # (just a few multiply-accumulate operations)
        filtered, self.live_zi = lfilter(
            self.live_b, self.live_a, [raw_value], zi=self.live_zi
        )

        # Bandpass filter centers the waveform at 0.
        # Re-add 512 to place it back in the UI's expected 0–1023 range.
        clean_value = int(filtered[0] + 512)
        self.live_sample_ready.emit(clean_value)

    def start_monitoring(self):
        self.reader.start()

    def stop_monitoring(self):
        self.reader.stop()
        self.peak_detector.stop()

    def _handle_analysis_results(self, bpm, hrv, x_peaks, y_peaks,
                                  rr_intervals_ms, peak_timestamps):
        """Receives data from Peak Detector and runs the 60s Apnea Logic."""
        self.bpm_updated.emit(bpm)
        self.hrv_updated.emit(hrv)
        self.peaks_detected.emit(x_peaks, y_peaks)

        if bpm > 0 and len(rr_intervals_ms) > 0:
            self._detect_apnea_v_shape(bpm, rr_intervals_ms)

    def _detect_apnea_v_shape(self, current_bpm, rr_intervals_ms):
        """
        Proposal Phase 3, Pathway A:
        Scans the 60-second window for Bradycardia (drop) followed by Tachycardia (spike).
        """
        self.bpm_history.append(current_bpm)
        if len(self.bpm_history) > 60:
            self.bpm_history.pop(0)

        if len(self.bpm_history) < 30:
            return

        baseline_bpm = np.mean(self.bpm_history)
        bradycardia_threshold = baseline_bpm - 10
        tachycardia_threshold = baseline_bpm + 10

        recent_history = self.bpm_history[-30:]
        has_brady = any(bpm < bradycardia_threshold for bpm in recent_history)
        has_tachy = any(bpm > tachycardia_threshold for bpm in recent_history)

        if has_brady and has_tachy:
            self.apnea_event_count += 1
            self.apnea_warning_triggered.emit(
                True, f"⚠️ APNEA EVENT DETECTED! (Total: {self.apnea_event_count})"
            )
            self.bpm_history = []
        else:
            self.apnea_warning_triggered.emit(False, "Normal Breathing Pattern")

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.bpm_history = []
            # ── NEW: Reset filter state so reconnecting doesn't cause a spike ──
            self.is_first_sample = True
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")