import time
from collections import deque
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal

class ECGSerialReader(QThread):
    """Thread 1: ONLY reads serial data and does lightweight EMA smoothing."""
    new_sample_ready = pyqtSignal(int)
    buffer_updated = pyqtSignal(list, list)  # Emits (raw_buffer, smoothed_buffer)
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
        self.samples_since_last_analysis = 0 
        
        # EMA State for UI smoothing
        self.ema_value = 0.0
        self.ema_alpha = 0.3
        self.smoothed_buffer = deque(maxlen=self.buffer_size)
        self.is_leads_off = False

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
                
                # Leads-Off Handling
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
                
                # 2. Send 10s buffer to Thread 2 (Peak Detector)
                self.samples_since_last_analysis += 1
                if self.samples_since_last_analysis >= self.buffer_size:
                    self.samples_since_last_analysis = 0
                    self.buffer_updated.emit(list(self.fifo_buffer), list(self.smoothed_buffer))
                    
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