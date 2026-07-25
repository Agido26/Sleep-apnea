from UI.Simulation import RealTimeECGViewer
from Business_Logic.Simulation.Loader import DataLoader
if __name__ == "__main__":
   #call the main function from real_time_ecg_viewer.py to start the application screen
   RealTimeECGViewer.launch("ecg_signal.csv")
