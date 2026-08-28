import sys
from collections import deque
from PyQt6.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg
from Business_Logic.ecg_service import ECGService

class ECGDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Apnea Screening Dashboard")
        self.resize(1000, 600)

        main_layout = QVBoxLayout()
        info_layout = QHBoxLayout()

        self.status_label = QLabel("Status: Connecting...")
        self.bpm_label = QLabel("BPM: --")
        self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
        self.alert_label = QLabel("Apnea Status: Analyzing...")
        self.hrv_label = QLabel("HRV (SDNN): -- ms")
        self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")

        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.bpm_label)
        info_layout.addWidget(self.hrv_label)
        info_layout.addWidget(self.alert_label)
        main_layout.addLayout(info_layout)

        self.graph_widget = pg.PlotWidget()
        self.graph_widget.setBackground('w')
        self.graph_widget.setTitle("Real-Time ECG with R-Peaks", color="k", size="15pt")
        self.graph_widget.showGrid(x=True, y=True)
        self.graph_widget.setYRange(0, 1023)

        pen = pg.mkPen(color='b', width=2)
        self.data_line = self.graph_widget.plot([], [], pen=pen, name="ECG Signal")

        self.peak_scatter = self.graph_widget.plot([], [], pen=None, symbol='o', 
                                                   symbolBrush='r', symbolSize=10, name="R-Peaks")
        main_layout.addWidget(self.graph_widget)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.plot_data = deque([512] * 1000, maxlen=1000)

        self.ecg_service = ECGService(port="COM4", baudrate=115200, sample_rate=250)
        self.ecg_service.live_sample_ready.connect(self.store_live_sample)
        self.ecg_service.bpm_updated.connect(self.update_bpm)
        self.ecg_service.hrv_updated.connect(self.update_hrv)
        self.ecg_service.peaks_detected.connect(self.update_peaks_graph)
        self.ecg_service.apnea_warning_triggered.connect(self.update_apnea_status)
        self.ecg_service.sensor_status_changed.connect(self.update_sensor_status)

        self.timer = QTimer()
        self.timer.timeout.connect(self.draw_graph)
        self.timer.start(33) 

        self.ecg_service.start_monitoring()

    def store_live_sample(self, value: int):
        self.plot_data.append(value)

    def draw_graph(self):
        self.data_line.setData(list(self.plot_data))

    def update_sensor_status(self, is_ok: bool, message: str):
        self.status_label.setText(message)
        
        if not is_ok:
            # 1. Show Red Warning
            self.status_label.setStyleSheet("font-size: 16px; color: red; font-weight: bold;")
            
            # 2. [FIX] DO NOT clear the plot_data! 
            # Let the real ECG waveform naturally scroll to the left and disappear over time.
            # The background thread is now feeding '512' (flatline), so the new incoming 
            # data will just draw a flat line, while the old data fades out naturally.
            
            # 3. Clear the Red Dots (Because there are no heartbeats right now, 
            # keeping old dots would be misleading to the doctor)
            self.peak_scatter.setData([], [])   
            
            # 4. Gray out the metrics so the user knows they are currently invalid
            self.bpm_label.setText("BPM: -- (No Signal)")
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: gray;")
            self.hrv_label.setText("HRV (SDNN): -- ms")
            self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: gray;")
            
        else:
            # Sensor is reconnected
            self.status_label.setStyleSheet("font-size: 16px; color: green; font-weight: bold;")
            # Restore normal colors when signal returns
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
            self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")
    def update_bpm(self, bpm: int):
        self.bpm_label.setText(f"BPM: {bpm}")
        color = "green" if 40 <= bpm <= 150 else "red"
        self.bpm_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")

    def update_hrv(self, hrv_value: float):
        self.hrv_label.setText(f"HRV (SDNN): {hrv_value:.1f} ms")

    def update_peaks_graph(self, x_peaks: list, y_peaks: list):
        self.peak_scatter.setData(x_peaks, y_peaks)

    def update_apnea_status(self, is_apnea: bool, message: str):
        self.alert_label.setText(message)
        color = "red" if is_apnea else "green"
        self.alert_label.setStyleSheet(f"font-size: 18px; color: {color}; font-weight: bold;")

    def closeEvent(self, event):
        self.ecg_service.stop_monitoring()
        super().closeEvent(event)

