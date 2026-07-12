import sys
import numpy as np
from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg
from Data.data_loader import load_physionet_data
from UI.Simulation.real_time_ecg_viewer import RealTimeECGViewer


# 1. جلب البيانات من PhysioNet
print("جاري تحميل البيانات...")
ecg_signal, fs = load_physionet_data(record_name='a01', num_samples=5000)

# 2. تشغيل الواجهة الرسومية
app = QtWidgets.QApplication(sys.argv)
viewer = RealTimeECGViewer(ecg_signal, fs)
viewer.resize(800, 400)
viewer.show()
sys.exit(app.exec())