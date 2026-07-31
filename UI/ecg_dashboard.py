import sys
from PyQt6.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget, QHBoxLayout
from PyQt6.QtCore import Qt
import pyqtgraph as pg  # استيراد مكتبة الرسم السريع
from Business_Logic.ecg_service import ECGService

class ECGDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Apnea Screening Dashboard")
        self.resize(1000, 600)
        
        # --- 1. تصميم الواجهة ---
        main_layout = QVBoxLayout()
        info_layout = QHBoxLayout()

        # إعداد الـ Labels بنصوص كبيرة وواضحة
        self.status_label = QLabel("status: connecting...")
        self.bpm_label = QLabel("BPM: --")
        self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
        self.alert_label = QLabel("Apnea Status: Analyzing...")
        
        # NEW: HRV Label
        self.hrv_label = QLabel("HRV (SDNN): -- ms")
        self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")
        
        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.bpm_label)
        info_layout.addWidget(self.hrv_label)
        info_layout.addWidget(self.alert_label)
        main_layout.addLayout(info_layout)


        # --- 2. Real-Time Graph Setup ---
        self.graph_widget = pg.PlotWidget()
        self.graph_widget.setBackground('w')
        self.graph_widget.setTitle("Real-Time ECG with R-Peak Verification", color="k", size="15pt")
        self.graph_widget.showGrid(x=True, y=True)
        self.graph_widget.setYRange(0, 1023)

       # Layer 1: Continuous ECG Line (Blue)
        pen = pg.mkPen(color='b', width=2)
        self.data_line = self.graph_widget.plot([], [], pen=pen, name="ECG Signal")
        
        # Layer 2: Red Dots on Detected R-Peaks (Scatter Plot)
        self.peak_scatter = self.graph_widget.plot(
            [], [], 
            pen=None, 
            symbol='o', 
            symbolBrush='r', 
            symbolSize=10, 
            name="Detected R-Peaks"
        )


        main_layout.addWidget(self.graph_widget)
        # إعداد نافذة التطبيق
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # بيانات الرسم المؤقتة (لرسم آخر 1000 قراءة فقط لتجنب بطء الشاشة)
        self.plot_data = [512] * 1000 

       # --- 3. Connect Business Layer Signals ---
        self.ecg_service = ECGService(port="COM3", baudrate=115200, sample_rate=250)
        self.ecg_service.live_sample_ready.connect(self.update_live_graph)
        self.ecg_service.bpm_updated.connect(self.update_bpm)
        self.ecg_service.hrv_updated.connect(self.update_hrv)              # Connect HRV
        self.ecg_service.peaks_detected.connect(self.update_peaks_graph)   # Connect Red Dots
        self.ecg_service.apnea_warning_triggered.connect(self.update_apnea_status)
        self.ecg_service.sensor_status_changed.connect(self.update_sensor_status)
        
        # Start the ECG monitoring thread
        self.ecg_service.start_monitoring()

    def update_live_graph(self, value: int):
        """تحديث الرسم البياني بسرعة البرق 250 مرة في الثانية"""
        # إضافة القيمة الجديدة في نهاية المصفوفة وحذف أقدم قيمة
        self.plot_data = self.plot_data[1:]
        self.plot_data.append(value)
        # تحديث الخط على الشاشة
        self.data_line.setData(self.plot_data)

    def update_bpm(self, bpm: int):
        """تحديث نص معدل النبضات"""
        self.bpm_label.setText(f"BPM: {bpm}")
        if bpm < 40 or bpm > 150:
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: red;")
        else:
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: green;")

    def update_apnea_status(self, is_apnea: bool, message: str):
        """تحديث نص إنذار الاختناق التنفسي"""
        self.alert_label.setText(message)
        if is_apnea:
            self.alert_label.setStyleSheet("font-size: 18px; color: red; font-weight: bold;")
        else:
            self.alert_label.setStyleSheet("font-size: 18px; color: green;")

    def update_sensor_status(self, is_ok: bool, message: str):
        """تحديث حالة الاتصال (Leads-Off)"""
        self.status_label.setText(message)
        if not is_ok:
            self.status_label.setStyleSheet("font-size: 16px; color: orange; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("font-size: 16px; color: green;")

    def closeEvent(self, event):
        """إيقاف الاتصال بأمان عند الإغلاق"""
        self.ecg_service.stop_monitoring()
        super().closeEvent(event)