#  NEW WAY (Connecting through Business Layer)
from Business_Logic.ecg_service import ECGService  # Import Business Layer only
from PyQt6.QtWidgets import QMainWindow
class ECGDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        # ... setup your UI widgets here ...

        # 1. Instantiate the Business Service (NOT the thread directly)
        self.ecg_service = ECGService(port="COM3", baudrate=115200, sample_rate=250)

        # 2. Connect Business Layer Signals to UI Callbacks
        self.ecg_service.live_sample_ready.connect(self.update_live_graph)
        self.ecg_service.bpm_updated.connect(self.update_bpm)
        self.ecg_service.apnea_warning_triggered.connect(self.update_apnea_status)
        self.ecg_service.sensor_status_changed.connect(self.update_sensor_status)

        # 3. Start monitoring through the Service method
        self.ecg_service.start_monitoring()

    def update_live_graph(self, value: int):
        """Called whenever a new filtered ECG sample arrives."""
        # Update your PyQtGraph / Chart here
        pass

    def update_bpm(self, bpm: int):
        """Called when a 10s window is processed and BPM is calculated."""
        # e.g., self.bpm_label.setText(f"BPM: {bpm}")
        pass

    def update_apnea_status(self, is_apnea: bool, message: str):
        """Called when an apnea event pattern is detected or cleared."""
        # e.g., self.status_label.setText(message)
        pass

    def update_sensor_status(self, is_ok: bool, message: str):
        """Handles connection status and Leads-Off disconnect warnings."""
        # e.g., self.connection_label.setText(message)
        pass

    def closeEvent(self, event):
        """Stop the service cleanly when closing the application window."""
        self.ecg_service.stop_monitoring()
        super().closeEvent(event)