import time
from collections import deque
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

class ECGSerialReader(QThread):
    new_sample_ready = pyqtSignal(int)             
    analysis_results = pyqtSignal(int, float, list, list) 
    leads_off_detected = pyqtSignal(bool)
    connection_error = pyqtSignal(str)

    def __init__(self, port="COM4", baudrate=115200, sample_rate=250, window_seconds=10):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.is_running = False
        self.serial_conn = None
        
        self.buffer_size = self.sample_rate * self.window_seconds
        self.fifo_buffer = deque(maxlen=self.buffer_size)
        
        # --- FIX 1: Proper counter for 10-second intervals ---
        self.samples_since_last_analysis = 0 
        
        # EMA State for UI smoothing
        self.ema_value = 0.0
        self.ema_alpha = 0.3
        self.smoothed_buffer = deque(maxlen=self.buffer_size)
        self.is_leads_off = False

    def _butter_bandpass_filter(self, data, lowcut=0.5, highcut=40.0, fs=250.0, order=3):
        nyquist = 0.5 * fs
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        return filtfilt(b, a, data)

    def _analyze_window(self):
        """Executes in background thread exactly once every 10 seconds."""
        if len(self.fifo_buffer) < 50: # Not enough data to analyze
            self.analysis_results.emit(0, 0.0, [], [])
            return

        raw_data = np.array(list(self.fifo_buffer))
        smoothed_data = np.array(list(self.smoothed_buffer))
        
        filtered_data = self._butter_bandpass_filter(raw_data)
        threshold = np.mean(filtered_data) + 1.2 * np.std(filtered_data)
        min_distance = int(self.sample_rate * 0.4)
        peaks, _ = find_peaks(filtered_data, height=threshold, distance=min_distance)
        
        if len(peaks) > 1:
            r_r_intervals = np.diff(peaks) / self.sample_rate
            real_bpm = int(60 / np.mean(r_r_intervals))
            hrv_sdnn = float(np.std(r_r_intervals * 1000.0))
            
            ui_window_size = 1000 
            offset = len(raw_data) - ui_window_size 
            
            x_indices = [int(p - offset) for p in peaks if p >= offset]
            y_values = [int(smoothed_data[p]) for p in peaks if p >= offset]
            
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
                
                # --- FIX 2: Strict Leads-Off Handling ---
                if value == -1 or value == 1023:
                    if not self.is_leads_off:
                        self.is_leads_off = True
                        self.leads_off_detected.emit(True)
                        # Clear buffers immediately so we don't analyze flatline garbage
                        self.fifo_buffer.clear() 
                        self.samples_since_last_analysis = 0
                    
                    # Send 512 to UI to draw a flatline, but DO NOT add to analysis buffer
                    self.new_sample_ready.emit(512)
                    continue 
                else:
                    if self.is_leads_off:
                        self.is_leads_off = False
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
                
                # --- FIX 3: Trigger Analysis exactly every 10 seconds ---
                self.samples_since_last_analysis += 1
                if self.samples_since_last_analysis >= self.buffer_size:
                    self.samples_since_last_analysis = 0 # Reset counter
                    self._analyze_window()
                    
            except ValueError:
                continue
            except serial.SerialException:
                self.connection_error.emit("USB Disconnected!")
                break
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