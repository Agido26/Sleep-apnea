from PyQt6.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget
from Business_Logic.ecg_service import ECGService
import sys

class ECGDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Apnea Screening Dashboard")
        self.resize(800, 600)
        
        # Simple layout for demonstration
        self.status_label = QLabel("Connecting to sensor...")
        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 1. Initialize Background Reader Thread
        # Note: Change 'COM3' to '/dev/ttyUSB0' or '/dev/ttyACM0' if on Linux/macOS
        self.ecg_thread = ECGService(port="COM3", baudrate=115200, sample_rate=250)
        
        # 2. Connect Signals to processing callbacks
        self.ecg_thread.new_sample_received.connect(self.update_live_graph)
        self.ecg_thread.buffer_updated.connect(self.process_moving_window)
        self.ecg_thread.leads_off_detected.connect(self.handle_leads_off)
        self.ecg_thread.connection_error.connect(self.handle_error)
        
        # 3. Start reading in background
        self.ecg_thread.start()

    def update_live_graph(self, value):
        """Called 250 times per second: update your real-time ECG chart here."""
        # e.g., self.graph_widget.append_point(value)
        pass

    def process_moving_window(self, buffer_data):
        """
        Called when a 10-second window is ready.
        Pass buffer_data to your deterministic Peak Detection & HRV apnea algorithm here!
        """
        self.status_label.setText(f"Processing 10s Window ({len(buffer_data)} samples)...")
        # e.g., r_peaks = detect_r_peaks(buffer_data, sample_rate=250)
        #       estimate_apnea(r_peaks)

    def handle_leads_off(self, is_off):
        if is_off:
            self.status_label.setText("WARNING: Electrode Disconnected (Leads-Off)!")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: green;")

    def handle_error(self, message):
        self.status_label.setText(f"Error: {message}")

    def closeEvent(self, event):
        """Ensure clean shutdown of serial port when closing the app."""
        self.ecg_thread.stop()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ECGDashboard()
    window.show()
    sys.exit(app.exec())