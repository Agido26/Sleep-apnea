import sys
import time
from collections import deque
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal

class ECGSerialReader(QThread):
    """
    Background QThread to read continuous ECG data from Arduino via USB Serial.
    Prevents UI freezing and maintains a real-time FIFO circular buffer.
    """
    # PyQt Signals to send data back to the UI/Processing pipeline safely
    new_sample_received = pyqtSignal(int)          # Emits single raw ECG value
    buffer_updated = pyqtSignal(list)              # Emits full moving-window buffer
    leads_off_detected = pyqtSignal(bool)          # Emits True if electrode is disconnected
    connection_error = pyqtSignal(str)             # Emits error messages

    def __init__(self, port="COM3", baudrate=115200, sample_rate=250, window_seconds=10):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.is_running = False
        self.serial_conn = None
        
        # FIFO Circular Buffer: Holds exactly 10 seconds of data (250 Hz * 10s = 2500 samples)
        self.buffer_size = self.sample_rate * self.window_seconds
        self.fifo_buffer = deque(maxlen=self.buffer_size)

    def run(self):
        """
        Main thread loop: Opens serial port and reads incoming lines at 250Hz.
        """
        # --- 1. DEBUG: Show available ports before connecting ---
        available_ports = self.get_available_ports()
        print(f"[DEBUG] Available USB/COM Ports on laptop: {available_ports}")

        try:
            print(f"[INFO] Attempting connection to Arduino on {self.port} at {self.baudrate} baud...")
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)  # Allow Arduino microcontroller to reset after serial connection
            self.serial_conn.reset_input_buffer()
            self.is_running = True
            print(f"[SUCCESS] Connected to {self.port}! Listening for live ECG data...")
        except Exception as e:
            error_msg = f"Failed to connect to {self.port}: {str(e)}"
            print(f"\n[CRITICAL ERROR] {error_msg}")
            print("[TIP] 1. Is the Arduino IDE Serial Monitor open? If yes, CLOSE IT!")
            print("[TIP] 2. Is your Arduino plugged into COM3, or a different COM port?\n")
            self.connection_error.emit(error_msg)
            return

        sample_counter = 0

        while self.is_running and self.serial_conn.is_open:
            try:
                # Read line from Arduino, decode ASCII, and strip whitespace
                raw_line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                
                if not raw_line:
                    continue
                
                # --- 2. DEBUG: Parse integer value with error detection ---
                value = int(raw_line)
                
                # Print live data to the terminal so you can verify it before the UI
                sample_counter += 1
                print(f"[LIVE SERIAL - {self.port}] Sample #{sample_counter} | Raw Value: {value}")
                
                # Check for Leads-Off indicator (-1 sent by Arduino)
                if value == -1:
                    print("[WARNING] Arduino sent '-1': Leads-Off (Electrode disconnected) detected!")
                    self.leads_off_detected.emit(True)
                    continue
                else:
                    self.leads_off_detected.emit(False)

                # Append to FIFO Circular Buffer (automatically discards oldest sample when full)
                self.fifo_buffer.append(value)
                
                # Emit signals for live plotting and moving-window analysis
                self.new_sample_received.emit(value)
                
                # Emit full buffer copy when it is full (for peak detection & apnea estimation)
                if len(self.fifo_buffer) == self.buffer_size:
                    print(f"[BUFFER FULL] 10-second window ({self.buffer_size} samples) ready for ECG analysis!")
                    self.buffer_updated.emit(list(self.fifo_buffer))

            except ValueError:
                # --- 3. DEBUG: Catch when Arduino sends text instead of numbers ---
                print(f"[PARSE ERROR] Received non-integer data from Arduino: '{raw_line}'")
                print("[TIP] Ensure your Arduino sketch uses 'Serial.println(val)' without extra text letters!")
                continue
            except Exception as e:
                print(f"[SERIAL ERROR] Connection dropped: {str(e)}")
                self.connection_error.emit(f"Serial read error: {str(e)}")
                break

        self.close_connection()

    def stop(self):
        """Stops the thread safely."""
        self.is_running = False
        self.wait()

    def close_connection(self):
        """Closes the serial port cleanly."""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print("[INFO] Serial connection closed safely.")

    @staticmethod
    def get_available_ports():
        """Utility method to scan and list all available USB/Serial COM ports."""
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]