import queue
import numpy as np
from collections import deque
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader
from scipy.signal import find_peaks, butter, filtfilt, lfilter, lfilter_zi
import csv
from datetime import datetime
from pathlib import Path

class ECGPeakDetector(QThread):
    """Thread 2: Peak detection, RR, and HRV extraction"""
    # Emits: (bpm, x_peaks_ui, y_peaks_ui, rr_intervals_ms)
    analysis_results = pyqtSignal(int, list, list, list)

    def __init__(self, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        self.data_queue = queue.Queue()
        self.is_running = True
        self.absolute_sample_count = 0 
        self.last_peak_absolute_time = 0 

    def add_buffer(self, raw_buffer, smoothed_buffer):
        self.data_queue.put((raw_buffer, smoothed_buffer))

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
            absolute_peaks = [int(p) + self.absolute_sample_count - len(raw_data) for p in peaks]
            rr_intervals_ms = self._calculate_rr_intervals(absolute_peaks)
            self.last_peak_absolute_time = absolute_peaks[-1]
            real_bpm = self._calculate_bpm(rr_intervals_ms)
            x_indices, y_values = self._map_ecg_peaks_to_ui(peaks, smoothed_data, len(raw_data))

            # Emit 4 arguments ONLY (NO EDR)
            self.analysis_results.emit(real_bpm, x_indices, y_values, rr_intervals_ms)
        else:
            self.absolute_sample_count += len(raw_data)
            self.analysis_results.emit(0, [], [], [])

    def _calculate_rr_intervals(self, absolute_peaks):
        rr_intervals_ms = []
        if self.last_peak_absolute_time > 0:
            rr_time_sec = (absolute_peaks[0] - self.last_peak_absolute_time) / self.sample_rate
            rr_ms = rr_time_sec * 1000.0
            if 300 < rr_ms < 2000: rr_intervals_ms.append(rr_ms)
        
        for i in range(1, len(absolute_peaks)):
            rr_time_sec = (absolute_peaks[i] - absolute_peaks[i-1]) / self.sample_rate
            rr_ms = rr_time_sec * 1000.0
            if 300 < rr_ms < 2000: rr_intervals_ms.append(rr_ms)
        return rr_intervals_ms

    def _calculate_bpm(self, rr_intervals_ms):
        latest_rr_sec = rr_intervals_ms[-1] / 1000.0 if rr_intervals_ms else 1.0
        return int(60 / latest_rr_sec) if rr_intervals_ms else 0

    def _map_ecg_peaks_to_ui(self, peaks, smoothed_data, buffer_len):
        ui_window_size = 1000  
        offset = buffer_len - ui_window_size  
        x_indices = [int(p - offset) for p in peaks if p >= offset]
        y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
        return x_indices, y_values

    def _butter_bandpass_filter(self, data, lowcut, highcut, fs, order=3):
        nyquist = 0.5 * fs
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        return filtfilt(b, a, data)

    def stop(self):
        self.is_running = False
        self.wait()


class ECGService(QObject):
    """Coordinates threads and calculates Apnea Index"""
    live_chunk_ready = pyqtSignal(list)
    bpm_updated = pyqtSignal(int)
    rr_updated = pyqtSignal(list)
    hrv_updated = pyqtSignal(float)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)
    apnea_event_count_updated = pyqtSignal(int)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        nyquist = 0.5 * self.sample_rate
        self.live_b, self.live_a = butter(2, [0.5 / nyquist, 40.0 / nyquist], btype='band')
        self.live_zi = lfilter_zi(self.live_b, self.live_a)
        self.is_first_chunk = True
        self._live_buffer = []
        self._chunk_size = 10

        # Advanced HRV & Apnea State Variables
        self.rr_history = deque(maxlen=150)
        self.baseline_rmssd = deque(maxlen=60)
        self.ai_history = deque(maxlen=60)
        self.consecutive_apnea_windows = 0
        self.apnea_event_count = 0
        self.apnea_cooldown = 0 

        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        self.peak_detector = ECGPeakDetector(sample_rate=self.sample_rate)
        self.peak_detector.start()

        self.reader.new_chunk_ready.connect(self._process_live_chunk)
        self.reader.buffer_updated.connect(self.peak_detector.add_buffer)
        self.peak_detector.analysis_results.connect(self._handle_analysis_results)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)
        # CSV Logging
        self.session_folder = None
        self.csv_file = None
        self.csv_writer = None
        self.create_session_folder()

    def start_monitoring(self): 
        self.reader.start()

    def stop_monitoring(self):
        self.reader.stop()
        self.peak_detector.stop()
        self.close_session()  # Close CSV file

    def _process_live_chunk(self, chunk: list):
        if self.is_first_chunk:
            self.live_zi = self.live_zi * chunk[0]
            self.is_first_chunk = False
        filtered_chunk, self.live_zi = lfilter(self.live_b, self.live_a, chunk, zi=self.live_zi)
        clean_chunk = [int(val + 512) for val in filtered_chunk]
        self.live_chunk_ready.emit(clean_chunk)

    def _handle_analysis_results(self, bpm, x_peaks, y_peaks, rr_intervals_ms):
        self.bpm_updated.emit(bpm)
        self.rr_updated.emit(rr_intervals_ms)
        self.peaks_detected.emit(x_peaks, y_peaks)
        
        # Calculate and emit HRV
        if rr_intervals_ms and len(rr_intervals_ms) >= 2:
            hrv_value = self._calculate_rmssd(rr_intervals_ms)
            self.hrv_updated.emit(round(hrv_value, 1))
        
        if rr_intervals_ms:
            latest_rr = rr_intervals_ms[-1]
            # Log the reading
            self.log_reading(bpm, latest_rr, hrv_value if rr_intervals_ms else 0.0, is_apnea=False)

    def _process_rr_for_hrv(self, rr_intervals_ms):
        for rr in rr_intervals_ms:
            self.rr_history.append(rr)
        if len(self.rr_history) >= 40:
            self._evaluate_apnea_index()

    def _clean_rr_series(self, raw_rr_list):
        if len(raw_rr_list) < 5: 
            return raw_rr_list
        med_rr = np.median(raw_rr_list)
        clean_rr = []
        for rr in raw_rr_list:
            if 0.8 * med_rr <= rr <= 1.2 * med_rr:
                if clean_rr and abs(rr - clean_rr[-1]) > (0.25 * clean_rr[-1]):
                    continue
                clean_rr.append(rr)
        return clean_rr if len(clean_rr) >= 10 else list(raw_rr_list)

    def _calculate_hrv_features(self, rr_list):
        clean_rr = self._clean_rr_series(rr_list)
        rmssd = self._calculate_rmssd(clean_rr)
        sdrr = self._calculate_sdrr(clean_rr)
        return rmssd, sdrr

    def _evaluate_apnea_index(self):
        current_rr = list(self.rr_history)
        rmssd_t, sdrr_t = self._calculate_hrv_features(current_rr)
        self.hrv_updated.emit(round(rmssd_t, 1))

        if rmssd_t == 0 or sdrr_t == 0: 
            return

        # Simple baseline calculation
        if len(self.baseline_rmssd) < 10:
            self.baseline_rmssd.append(rmssd_t)
            return

        normal_rmssd = np.median(self.baseline_rmssd)
        drop_ratio = rmssd_t / normal_rmssd if normal_rmssd > 0 else 1.0

        if drop_ratio >= 0.75:
            self.baseline_rmssd.append(rmssd_t)

        self._run_simplified_state_machine(drop_ratio, rmssd_t, normal_rmssd)

    def _run_simplified_state_machine(self, drop_ratio, current_rmssd, normal_rmssd):
        is_apnea_suspected = drop_ratio < 0.55 

        if self.apnea_cooldown > 0:
            self.apnea_cooldown -= 1
            if not is_apnea_suspected:
                self.consecutive_apnea_windows = 0
            return

        if is_apnea_suspected:
            self.consecutive_apnea_windows += 1
        else:
            self.consecutive_apnea_windows = 0

        if self.consecutive_apnea_windows >= 2:
            self.apnea_event_count += 1
            msg = f"⚠️ Apnea Event! (HRV dropped from {int(normal_rmssd)} to {int(current_rmssd)})"
            self.apnea_warning_triggered.emit(True, msg)
            self.apnea_event_count_updated.emit(self.apnea_event_count)
            self.consecutive_apnea_windows = 0
            self.apnea_cooldown = 15
        else:
            self.apnea_warning_triggered.emit(False, f"Normal HRV: {int(current_rmssd)} ms")

    def _calculate_rmssd(self, rr_list):
        """Calculate RMSSD from RR intervals"""
        if len(rr_list) < 2: 
            return 0.0
        diff_rr = np.diff(rr_list)
        return float(np.sqrt(np.mean(diff_rr**2)))

    def _calculate_sdrr(self, rr_list):
        if len(rr_list) < 2: 
            return 0.0
        return float(np.std(rr_list))

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
            self.peak_detector.last_peak_absolute_time = 0
            self.is_first_chunk = True
            self._live_buffer = []
            self.rr_history.clear()
            self.baseline_rmssd.clear()
            self.ai_history.clear()
            self.consecutive_apnea_windows = 0
            self.apnea_cooldown = 0
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")

    
    def create_session_folder(self):
        """Create session folder and CSV file"""
        sessions_dir = Path("sessions")
        sessions_dir.mkdir(exist_ok=True)
    
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_folder = sessions_dir / timestamp
        self.session_folder.mkdir(exist_ok=True)
        
        self.csv_file = self.session_folder / "ecg_readings.csv"
        self.csv_file_handle = open(self.csv_file, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_file_handle)
        self.csv_writer.writerow([
            'Timestamp', 'BPM', 'RR_Interval_ms', 'HRV_RMSSD', 'Is_Apnea_Event'
        ])
        print(f"[LOG] Session started: {self.session_folder}")

    def log_reading(self, bpm, rr_interval, hrv_rmssd, is_apnea=False):
        """Log reading to CSV"""
        if self.csv_writer and self.csv_file_handle:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.csv_writer.writerow([
                timestamp, bpm, rr_interval, round(hrv_rmssd, 2), 1 if is_apnea else 0
            ])
            self.csv_file_handle.flush()

    def close_session(self):
        """Close CSV file"""
        if self.csv_file_handle and not self.csv_file_handle.closed:
            self.csv_file_handle.close()
            print(f"[LOG] Session saved to: {self.session_folder}")