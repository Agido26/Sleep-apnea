import time
from collections import deque
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal
import numpy as np
from scipy.signal import find_peaks, butter, filtfilt

class ECGSerialReader(QThread):
    new_sample_ready = pyqtSignal(int)
    buffer_updated = pyqtSignal(list, list)  # EMITS (raw_buffer, smoothed_buffer) - THIS WAS MISSING!
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
        
        # 1. Keep buffer at 10 seconds (2500 samples) for accurate HRV math
        self.buffer_size = self.sample_rate * self.window_seconds 
        self.fifo_buffer = deque(maxlen=self.buffer_size)
        
        # Trigger analysis every 1 SECOND (250 samples) for instant peak detection
        self.analysis_trigger = self.sample_rate * 1 
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
        """Executes in background thread every 1 second."""
        if len(self.fifo_buffer) < 50: 
            return  # Not enough data
        
        # Emit the buffer to the Peak Detector Thread
        self.buffer_updated.emit(list(self.fifo_buffer), list(self.smoothed_buffer))

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
                
                # Strict Leads-Off Handling
                if value == -1 or value == 1023:
                    if not self.is_leads_off:
                        self.is_leads_off = True
                        self.leads_off_detected.emit(True)
                        self.fifo_buffer.clear() 
                        self.smoothed_buffer.clear()
                        self.samples_since_last_analysis = 0
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
                
                # 2. Trigger Analysis exactly every 1 second
                self.samples_since_last_analysis += 1
                if self.samples_since_last_analysis >= self.analysis_trigger:
                    self.samples_since_last_analysis = 0 
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