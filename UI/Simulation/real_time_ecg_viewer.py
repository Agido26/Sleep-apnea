import sys
import pyqtgraph as pg
from PyQt6 import QtWidgets, QtCore

from Business_Logic.Business_Simulation.Loader import Loader

class RealTimeECGViewer(QtWidgets.QMainWindow):
    def __init__(self, signal, fs):
        super().__init__()
        
        self.signal = signal
        self.fs = fs
        self.current_index = 0
        self.chunk_size = 10  # محاكاة سرعة الأردوينو بجلب 5 قراءات كل تحديث
        
        # إعداد واجهة PyQtGraph
        self.graphWidget = pg.PlotWidget()
        self.setCentralWidget(self.graphWidget)
        self.graphWidget.setBackground('k')  # خلفية سوداء مثل أجهزة المستشفيات
        self.graphWidget.setTitle("Real-Time ECG Signal (Arduino Simulation)", color="w", size="15pt")
        self.graphWidget.setYRange(-2, 3)  # تثبيت محور الفولتية لمنع الاهتزاز
        
        # إعداد نافذة العرض (نعرض 1000 نقطة تعادل 10 ثواني)
        self.x = list(range(1000))  
        self.y = [0] * 1000
        
        # رسم الخط الأولي (أخضر وعريض قليلاً)
        pen = pg.mkPen(color=(0, 255, 0), width=2)
        self.data_line = self.graphWidget.plot(self.x, self.y, pen=pen)
        
        # المؤقت (Timer) هو قلب التحديث الحي
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)  # تحديث الشاشة كل 50 ملي ثانية
        self.timer.timeout.connect(self.update_plot_data)
        self.timer.start()

    def update_plot_data(self):
        # التأكد أن لدينا بيانات باقية للمحاكاة
        if self.current_index + self.chunk_size >= len(self.signal):
            self.timer.stop()
            print("انتهت البيانات التجريبية.")
            return

        # جلب القراءات الجديدة وإزاحة القديمة (Shift)
        new_data = self.signal[self.current_index : self.current_index + self.chunk_size]
        self.y = self.y[self.chunk_size:] + list(new_data)
        
        # تحديث الخط على الشاشة فوراً
        self.data_line.setData(self.x, self.y)
        
        self.current_index += self.chunk_size

def main():
    # 1. جلب البيانات من PhysioNet
    print("جاري تحميل البيانات...")
    loader = Loader()
    signal,fs = loader.load_csv_data('ecg_signal.csv')  # تحميل البيانات من ملف CSV محلي
    # 2. تشغيل الواجهة الرسومية
    app = QtWidgets.QApplication(sys.argv)
    viewer = RealTimeECGViewer(signal, fs)
    viewer.resize(800, 400)
    viewer.show()
    sys.exit(app.exec())
    