import sys
import os
from PyQt6.QtWidgets import QApplication

# Ensure the root directory is in the Python path for clean module imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from UI.ecg_dashboard import ECGDashboard

def main():
    # High DPI scaling support (optional but makes UI look better on modern screens)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)
    app.setApplicationName("Sleep Apnea Screening System")
    
    main_window = ECGDashboard()
    main_window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()