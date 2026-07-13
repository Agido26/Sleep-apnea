import sys
import numpy as np
from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg
from Business_Logic.Business_Simulation import Loader
from UI.Simulation.real_time_ecg_viewer import RealTimeECGViewer


# 1. جلب البيانات من PhysioNet
print("جاري تحميل البيانات...")
loader= Loader.Loader(record_name='a01', num_samples=5000)
signal,fs = loader.load_data()
# 2. تشغيل الواجهة الرسومية
app = QtWidgets.QApplication(sys.argv)
viewer = RealTimeECGViewer(signal, fs)
viewer.resize(800, 400)
viewer.show()
sys.exit(app.exec())