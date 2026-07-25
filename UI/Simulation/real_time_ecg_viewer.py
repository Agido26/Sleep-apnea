import pyqtgraph as pg
from PyQt6 import QtWidgets, QtCore

# استيراد جالب البيانات والمعالج الرياضي من هيكليتك
from Business_Logic.Simulation.Loader import DataLoader
from Business_Logic.Simulation.Processor import ECGProcessor

class RealTimeECGViewer(QtWidgets.QMainWindow):
    def __init__(self, path="ecg_signal.csv"):
        super().__init__()
        self.signal, self.fs = DataLoader.load_csv_data(file_path=path)  
        self.current_index = 0
        self.chunk_size = 10  
        
        # --- إعداد الهيكل الرئيسي للنافذة (Layout) ---
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        layout = QtWidgets.QVBoxLayout(main_widget)
        
        # 1. إضافة شاشة رقمية لعرض الـ BPM
        self.bpm_label = QtWidgets.QLabel("Heart Rate (BPM): --")
        self.bpm_label.setStyleSheet("font-size: 20pt; color: #00FF00; font-weight: bold; background-color: black; qproperty-alignment: AlignCenter;")
        layout.addWidget(self.bpm_label)
        
        # 2. إعداد واجهة الرسم البياني
        self.graphWidget = pg.PlotWidget()
        layout.addWidget(self.graphWidget)
        self.graphWidget.setBackground('k')
        self.graphWidget.setTitle("Real-Time ECG Signal & Peak Detection", color="w", size="15pt")
        self.graphWidget.setYRange(-2, 3)
        
        self.x = list(range(1000))  
        self.y = [0] * 1000
        
        pen = pg.mkPen(color=(0, 255, 0), width=2)
        self.data_line = self.graphWidget.plot(self.x, self.y, pen=pen)
        
        # 3. تجهيز النقاط الحمراء التي ستظهر فوق القمم
        self.peaks_scatter = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(255, 0, 0))
        self.graphWidget.addItem(self.peaks_scatter)
        
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.update_plot_data)
        self.timer.start()

    def update_plot_data(self):
        if self.current_index + self.chunk_size >= len(self.signal):
            self.timer.stop()
            print("انتهت البيانات التجريبية.")
            return

        # تحديث بيانات الرسم
        new_data = self.signal[self.current_index : self.current_index + self.chunk_size]
        self.y = self.y[self.chunk_size:] + list(new_data)
        self.data_line.setData(self.x, self.y)
        
        # --- استدعاء Business Logic لحساب القمم ---
        # نرسل نافذة البيانات الحالية ومعدل التردد
        peaks, bpm = ECGProcessor.calculate_peaks_and_bpm(self.y, self.fs)
        
        # رسم النقاط الحمراء إذا تم اكتشاف قمم
        if len(peaks) > 0:
            self.peaks_scatter.setData(peaks, [self.y[p] for p in peaks])
            # تحديث شاشة الـ BPM إذا تم حسابه بنجاح
            if bpm > 0:
                self.bpm_label.setText(f"Heart Rate (BPM): {int(bpm)}")
        else:
            self.peaks_scatter.clear()
            
        self.current_index += self.chunk_size

    @staticmethod
    def launch(path="ecg_signal.csv"):
        import sys
        app = QtWidgets.QApplication(sys.argv)
        viewer = RealTimeECGViewer(path)
        viewer.resize(800, 500)
        viewer.show()
        sys.exit(app.exec())