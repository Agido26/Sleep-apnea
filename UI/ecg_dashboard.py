#  NEW WAY (Connecting through Business Layer)
from Business_Logic.ecg_service import ECGService  # Import Business Layer only
from PyQt6.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget
import pyqtgraph as pg
from collections import deque
class ECGDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Apnea Screening Dashboard")
        self.resize(800, 600)
        
        self.status_label = QLabel("Initializing Connection...")
        self.bpm_label = QLabel("BPM: --")
        self.alert_label = QLabel("Status: Ready")
        
        self.graph_widget = pg.PlotWidget()
        self.graph_widget.setBackground('w')  # White background for clinical look
        self.graph_widget.setTitle("Real-Time Single-Lead ECG", color="b", size="12pt")
        self.graph_widget.showGrid(x=True, y=True)
        self.graph_widget.setYRange(0, 1024)  # Standard 10-bit Arduino ADC range (0-1023)
        
        # Create a red plotting curve
        self.plot_curve = self.graph_widget.plot(pen=pg.mkPen(color='r', width=2))
        
        # Deque for plotting just the last 4 seconds of data (4 * 250Hz = 1000 samples)
        # This keeps the graph moving left-to-right like a hospital monitor
        self.plot_data = deque([0] * 1000, maxlen=1000)
        
        layout = QVBoxLayout()
        layout.addWidget(self.graph_widget)
        layout.addWidget(self.status_label)
        layout.addWidget(self.bpm_label)
        layout.addWidget(self.alert_label)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 1. Instantiate the Business Service (NOT the thread directly)
        self.ecg_service = ECGService(port="COM3", baudrate=115200, sample_rate=250)

        # 2. Connect Business Layer Signals to UI Callbacks
        self.ecg_service.live_sample_ready.connect(self.update_live_graph)
        self.ecg_service.bpm_updated.connect(self.update_bpm)
        self.ecg_service.apnea_warning_triggered.connect(self.update_apnea_status)
        self.ecg_service.sensor_status_changed.connect(self.update_sensor_status)

        # 3. Start monitoring through the Service method
        self.ecg_service.start_monitoring()

    
    def update_live_graph(self, sample_value: int):
        """Called whenever a new filtered ECG sample arrives."""
        self.plot_data.append(sample_value)
        self.plot_curve.setData(list(self.plot_data))

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