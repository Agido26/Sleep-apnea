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
        self.resize(1000, 800) # زيادة الارتفاع قليلاً لاستيعاب رسم التنفس

        main_layout = QVBoxLayout()
        info_layout = QHBoxLayout()

        # --- Labels ---
        self.status_label = QLabel("Status: Connecting...")
        
        self.bpm_label = QLabel("BPM: --")
        self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
        
        self.rr_label = QLabel("RR: -- ms")
        self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkorange;")
        
        self.resp_label = QLabel("Resp: -- BrPM")
        self.resp_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkgreen;")
        
        self.hrv_label = QLabel("HRV (RMSSD): -- ms") # تم تغيير SDNN إلى RMSSD
        self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")
        
        self.alert_label = QLabel("Apnea Status: Analyzing...")

        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.bpm_label)
        info_layout.addWidget(self.rr_label)
        info_layout.addWidget(self.resp_label)
        info_layout.addWidget(self.hrv_label)
        info_layout.addWidget(self.alert_label)
        main_layout.addLayout(info_layout)

        # --- GRAPH 1: Real-Time ECG ---
        self.ecg_graph = pg.PlotWidget()
        self.ecg_graph.setBackground('w')
        self.ecg_graph.setTitle("Real-Time ECG with R-Peaks", color="k", size="15pt")
        self.ecg_graph.showGrid(x=True, y=True)
        self.ecg_graph.setYRange(0, 1023)
        
        pen_ecg = pg.mkPen(color='b', width=2)
        self.ecg_line = self.ecg_graph.plot([], [], pen=pen_ecg, name="ECG Signal")
        self.peak_scatter = self.ecg_graph.plot([], [], pen=None, symbol='o', 
                                                symbolBrush='r', symbolSize=10, name="R-Peaks")
        main_layout.addWidget(self.ecg_graph)

        # --- GRAPH 2: EDR (Respiration) - جديد ---
        self.edr_graph = pg.PlotWidget()
        self.edr_graph.setBackground('w')
        self.edr_graph.setTitle("ECG-Derived Respiration (EDR) - Last 30 Seconds", color="k", size="15pt")
        self.edr_graph.showGrid(x=True, y=True)
        self.edr_graph.setLabel('bottom', 'Time', units='s')
        self.edr_graph.setLabel('left', 'Amplitude')
        
        pen_edr = pg.mkPen(color='g', width=2)
        self.edr_line = self.edr_graph.plot([], [], pen=pen_edr, name="Respiratory Signal")
        self.breath_scatter = self.edr_graph.plot([], [], pen=None, symbol='o', 
                                                  symbolBrush='y', symbolSize=12, name="Breath Peaks")
        main_layout.addWidget(self.edr_graph)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.plot_data = deque([512] * 1000, maxlen=1000)
        self.current_peaks = [] 

        # --- Backend Service ---
        self.ecg_service = ECGService(port="COM4", baudrate=115200, sample_rate=250)
        
        # 🔴 التعديل الأهم: ربط الإشارات الجديدة (Chunk بدلاً من Sample)
        self.ecg_service.live_chunk_ready.connect(self.store_live_chunk)
        self.ecg_service.bpm_updated.connect(self.update_bpm)
        self.ecg_service.rr_updated.connect(self.update_rr)           # جديد
        self.ecg_service.brpm_updated.connect(self.update_resp)       # جديد
        self.ecg_service.hrv_updated.connect(self.update_hrv)
        self.ecg_service.peaks_detected.connect(self.update_peaks_graph)
        self.ecg_service.edr_graph_updated.connect(self.update_edr_graph) # جديد
        self.ecg_service.apnea_warning_triggered.connect(self.update_apnea_status)
        self.ecg_service.sensor_status_changed.connect(self.update_sensor_status)

        self.timer = QTimer()
        self.timer.timeout.connect(self.draw_graph)
        self.timer.start(33) 

        self.ecg_service.start_monitoring()

    # 🔴 التعديل: استقبال الحزمة (Chunk) بدلاً من العينة الواحدة
    def store_live_chunk(self, chunk: list):
        """إضافة الحزمة دفعة واحدة وتزحيح مواقع الـ Peaks بمقدار طول الحزمة"""
        chunk_len = len(chunk)
        self.plot_data.extend(chunk)
        
        # --- THE MAGIC FIX: Scroll existing peaks to the left by chunk length ---
        for peak in self.current_peaks:
            peak[0] -= chunk_len
            
        # Remove peaks that have scrolled off the left side of the screen
        self.current_peaks = [p for p in self.current_peaks if p[0] >= 0]

    def draw_graph(self):
        self.ecg_line.setData(list(self.plot_data))
        
        if self.current_peaks:
            x_peaks = [p[0] for p in self.current_peaks]
            y_peaks = [p[1] for p in self.current_peaks]
            self.peak_scatter.setData(x_peaks, y_peaks)
        else:
            self.peak_scatter.setData([], [])

    def update_edr_graph(self, t_data, edr_data, breath_x, breath_y):
        """رسم إشارة التنفس المستخرجة من الـ ECG"""
        self.edr_line.setData(t_data, edr_data)
        self.breath_scatter.setData(breath_x, breath_y)

    def update_sensor_status(self, is_ok: bool, message: str):
        self.status_label.setText(message)
        if not is_ok:
            self.status_label.setStyleSheet("font-size: 16px; color: red; font-weight: bold;")
            self.peak_scatter.setData([], [])   
            self.current_peaks = []
            self.bpm_label.setText("BPM: --")
            self.rr_label.setText("RR: -- ms")
            self.resp_label.setText("Resp: -- BrPM")
            self.hrv_label.setText("HRV (RMSSD): -- ms")
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: gray;")
            self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: gray;")
            self.resp_label.setStyleSheet("font-size: 24px; font-weight: bold; color: gray;")
            self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: gray;")
        else:
            self.status_label.setStyleSheet("font-size: 16px; color: green; font-weight: bold;")
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
            self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkorange;")
            self.resp_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkgreen;")
            self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")

    def update_bpm(self, bpm: int):
        self.bpm_label.setText(f"BPM: {bpm}")
        color = "green" if 40 <= bpm <= 150 else "red"
        self.bpm_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")

    def update_rr(self, rr_intervals_ms: list):
        """عرض آخر فترة RR محسوبة"""
        if rr_intervals_ms:
            latest_rr = rr_intervals_ms[-1]
            self.rr_label.setText(f"RR: {latest_rr:.0f} ms")

    def update_resp(self, brpm: float):
        """عرض معدل التنفس (BrPM)"""
        if brpm > 0:
            self.resp_label.setText(f"Resp: {brpm:.1f} BrPM")
        else:
            self.resp_label.setText("Resp: -- BrPM")

    def update_hrv(self, hrv_value: float):
        """عرض الـ HRV (الآن هي RMSSD وليست SDNN)"""
        self.hrv_label.setText(f"HRV (RMSSD): {hrv_value:.1f} ms")

    def update_peaks_graph(self, x_peaks: list, y_peaks: list):
        for new_x, new_y in zip(x_peaks, y_peaks):
            is_duplicate = False
            for i, existing_peak in enumerate(self.current_peaks):
                if abs(existing_peak[0] - new_x) < 30:
                    self.current_peaks[i] = [new_x, new_y]
                    is_duplicate = True
                    break
            if not is_duplicate:
                self.current_peaks.append([new_x, new_y])

    def update_apnea_status(self, is_apnea: bool, message: str):
        self.alert_label.setText(message)
        color = "red" if is_apnea else "green"
        self.alert_label.setStyleSheet(f"font-size: 18px; color: {color}; font-weight: bold;")

    def closeEvent(self, event):
        self.ecg_service.stop_monitoring()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = ECGDashboard()
    dashboard.show()
    sys.exit(app.exec())