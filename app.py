import sys
from PyQt6.QtWidgets import QApplication
from UI.ecg_dashboard import ECGDashboard

def main():
    """
    Main entry point of the application.
    Initializes the Qt Application context, loads the UI layer,
    and manages the application execution loop.
    """
    # 1. Initialize the QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Sleep Apnea Screening System")

    # 2. Instantiate the UI Layer (ECGDashboard)
    # The ECGDashboard internally instantiates the ECGService (Business Layer),
    # maintaining the strict 3-layer architecture.
    main_window = ECGDashboard()
    main_window.show()

    # 3. Start the Qt Event Loop and exit cleanly when closed
    sys.exit(app.exec())

if __name__ == "__main__":
    main()