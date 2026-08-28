import time
from collections import deque
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

class ECGSerialReader(QThread):
    """
    Background QThread: Handles Serial Reading, EMA Smoothing, AND Heavy Signal Processing.
    This ensures the Main UI Thread is NEVER blocked by math operations.
    """
    # Signals
    new_sample_ready = pyqtSignal(int)             # Smoothed value for UI plotting
    analysis_results = pyqtSignal(int, float, list, list) # (BPM, HRV, x_peaks, y_peaks)
    leads_off_detected = pyqtSignal(bool)
    connection_error = pyqtSignal(str)

    def __init__(self, port="COM3", baudrate=115200, sample_rate=250, window_seconds=10):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.is_running = False
        self.serial_conn = None
        
        self.buffer_size = self.sample_rate * self.window_seconds
        self.fifo_buffer = deque(maxlen=self.buffer_size)
        
        # EMA State for UI smoothing
        self.ema_value = 0.0
        self.ema_alpha = 0.3
        self.smoothed_buffer = deque(maxlen=self.buffer_size)

    def _butter_bandpass_filter(self, data, lowcut=0.5, highcut=40.0, fs=250.0, order=3):
        nyquist = 0.5 * fs
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        return filtfilt(b, a, data)

    def _analyze_window(self):
        """Executes in background thread. Calculates BPM, HRV, and maps peaks for UI."""
        raw_data = np.array(list(self.fifo_buffer))
        smoothed_data = np.array(list(self.smoothed_buffer))
        
        # 1. Filter & Find Peaks
        filtered_data = self._butter_bandpass_filter(raw_data)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)
        
        if len(peaks) > 1:
            # BPM & HRV
            r_r_intervals = np.diff(peaks) / self.sample_rate
            real_bpm = int(60 / np.mean(r_r_intervals))
            hrv_sdnn = float(np.std(r_r_intervals * 1000.0))
            
            # Map peaks to UI Window (UI shows last 1000 samples, buffer is 2500)
            ui_window_size = 1000 
            offset = len(raw_data) - ui_window_size 
            
            x_indices = []
            y_values = []
            for p in peaks:
                if p >= offset:
                    x_indices.append(int(p - offset))
                    y_values.append(int(smoothed_data[p])) # Use smoothed Y so dot aligns with blue line
            
            # Emit results to UI
            self.analysis_results.emit(real_bpm, hrv_sdnn, x_indices, y_values)
        else:
            self.analysis_results.emit(0, 0.0, [], [])

    def run(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)
            self.serial_conn.reset_input_buffer()
            self.is_running = True
        except Exception as e:
            self.connection_error.emit(f"Failed to connect: {str(e)}")
            return

        while self.is_running and self.serial_conn.is_open:
            try:
                raw_line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if not raw_line:
                    continue
                
                value = int(raw_line)
                
                # Leads-off check
                if value == -1 or value == 1023:
                    self.leads_off_detected.emit(True)
                    value = 512
                else:
                    self.leads_off_detected.emit(False)
                
                # 1. EMA Smoothing for UI
                if self.ema_value == 0.0:
                    self.ema_value = float(value)
                else:
                    self.ema_value = (self.ema_alpha * value) + ((1 - self.ema_alpha) * self.ema_value)
                
                smoothed_int = int(self.ema_value)
                self.smoothed_buffer.append(smoothed_int)
                self.fifo_buffer.append(value)
                
                # Send to UI for immediate plotting
                self.new_sample_ready.emit(smoothed_int)
                
                # 2. Trigger Heavy Analysis when buffer is full (Every 10s)
                if len(self.fifo_buffer) == self.buffer_size:
                    self._analyze_window()
                    
            except ValueError:
                continue
            except Exception as e:
                self.connection_error.emit(f"Serial error: {str(e)}")
                break
                
        self.close_connection()

    def stop(self):
        self.is_running = False
        self.wait()

    def close_connection(self):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

    @staticmethod
    def get_available_ports():
        return [port.device for port in serial.tools.list_ports.comports()]