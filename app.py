import sys
from PyQt6.QtWidgets import QApplication
from UI.ecg_dashboard import ECGDashboard

def main():

    app = QApplication(sys.argv)
    app.setApplicationName("Sleep Apnea Screening System")

    main_window = ECGDashboard()
    main_window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()