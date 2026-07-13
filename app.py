import sys
import matplotlib.pyplot as plt
import numpy as np
from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg
from Business_Logic.Business_Simulation import Loader
from UI.Simulation import real_time_ecg_viewer
from UI.Simulation.real_time_ecg_viewer import RealTimeECGViewer
import pandas as pd
if __name__ == "__main__":
   #call the main function from real_time_ecg_viewer.py to start the application screen
    real_time_ecg_viewer.main()