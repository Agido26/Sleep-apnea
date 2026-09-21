import sys
from collections import deque
from PyQt6.QtWidgets import QMainWindow, QApplication, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QPushButton, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg
from Business_Logic.ecg_service import ECGService
from UI.report_viewer import ReportViewer

class ECGDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Apnea Screening Dashboard")
        self.resize(1000, 700)

        main_layout = QVBoxLayout()
        info_layout = QHBoxLayout()

        # --- Top Labels ---
        self.status_label = QLabel("Status: Recording...")
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: green;")
        
        self.bpm_label = QLabel("BPM: --")
        self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
        
        self.rr_label = QLabel("RR: -- ms")
        self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkorange;")
        
        self.hrv_label = QLabel("HRV (RMSSD): -- ms")
        self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")
        
        # --- Apnea Detection Labels ---
        self.apnea_status_label = QLabel("Apnea Status: Normal")
        self.apnea_status_label.setStyleSheet("font-size: 22px; font-weight: bold; color: green;")
        
        self.apnea_count_label = QLabel("Events Detected: 0")
        self.apnea_count_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkred;")

        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.bpm_label)
        info_layout.addWidget(self.rr_label)
        info_layout.addWidget(self.hrv_label)
        info_layout.addWidget(self.apnea_status_label)
        info_layout.addWidget(self.apnea_count_label)
        main_layout.addLayout(info_layout)

        # --- GRAPH: ECG ---
        self.ecg_graph = pg.PlotWidget()
        self.ecg_graph.setBackground('w')
        self.ecg_graph.setTitle("Real-Time ECG with R-Peaks", color="k", size="15pt")
        self.ecg_graph.showGrid(x=True, y=True)
        self.ecg_graph.setYRange(0, 1023)

        pen_ecg = pg.mkPen(color='b', width=2)
        self.ecg_line = self.ecg_graph.plot([], [], pen=pen_ecg, name="ECG Signal")
        self.peak_scatter = self.ecg_graph.plot([], [], pen=None, symbol='o', 
                                                symbolBrush='r', symbolSize=10, name="R-Peaks")
        main_layout.addWidget(self.ecg_graph)

        # --- End Session Button ---
        self.end_session_btn = QPushButton("⏹️ End Session & Generate Report")
        self.end_session_btn.setStyleSheet("""
            font-size: 20px; 
            font-weight: bold; 
            padding: 15px; 
            background-color: #f44336; 
            color: white; 
            border-radius: 5px;
        """)
        self.end_session_btn.clicked.connect(self.end_session_and_show_report)
        main_layout.addWidget(self.end_session_btn)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.plot_data = deque([512] * 1000, maxlen=1000)
        self.current_peaks = [] 
        self.session_active = True  # Track if session is active

        self.ecg_service = ECGService(port="COM4", baudrate=115200, sample_rate=250)
        
        # Connections
        self.ecg_service.live_chunk_ready.connect(self.store_live_chunk)
        self.ecg_service.bpm_updated.connect(self.update_bpm)
        self.ecg_service.rr_updated.connect(self.update_rr)
        self.ecg_service.hrv_updated.connect(self.update_hrv)
        self.ecg_service.peaks_detected.connect(self.update_peaks_graph)
        self.ecg_service.apnea_warning_triggered.connect(self.update_apnea_status)
        self.ecg_service.apnea_event_count_updated.connect(self.update_apnea_count)
        self.ecg_service.sensor_status_changed.connect(self.update_sensor_status)

        self.timer = QTimer()
        self.timer.timeout.connect(self.draw_graph)
        self.timer.start(33) 

        self.ecg_service.start_monitoring()

    def store_live_chunk(self, chunk: list):
        """Only store data if session is still active"""
        if not self.session_active:
            return
            
        chunk_len = len(chunk)
        self.plot_data.extend(chunk)
        for peak in self.current_peaks:
            peak[0] -= chunk_len
        self.current_peaks = [p for p in self.current_peaks if p[0] >= 0]

    def draw_graph(self):
        self.ecg_line.setData(list(self.plot_data))
        if self.current_peaks:
            x_peaks = [p[0] for p in self.current_peaks]
            y_peaks = [p[1] for p in self.current_peaks]
            self.peak_scatter.setData(x_peaks, y_peaks)
        else:
            self.peak_scatter.setData([], [])

    def end_session_and_show_report(self):
        """Stop session and open file upload dialog"""
        if not self.session_active:
            QMessageBox.warning(self, "Session Already Ended", 
                              "This session has already ended. Please restart the application for a new session.")
            return
        
        # Confirm end session
        reply = QMessageBox.question(self, 'End Session?', 
                            'Are you sure you want to end this session?\n\nNo more data will be recorded after this.',
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                            QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.No:
            return
        
        # 1. Stop the session
        self.session_active = False
        self.ecg_service.stop_monitoring()
        
        # 2. Update UI to show session ended
        self.status_label.setText("Status: Session Ended")
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: orange;")
        self.end_session_btn.setEnabled(False)
        self.end_session_btn.setText("Session Ended")
        self.end_session_btn.setStyleSheet("""
            font-size: 20px; 
            font-weight: bold; 
            padding: 15px; 
            background-color: #9e9e9e; 
            color: white; 
            border-radius: 5px;
        """)
        
        # 3. Open file upload dialog
        self.open_file_upload_dialog()

    def open_file_upload_dialog(self):
        """Open dialog to select session CSV file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Session File",
            "sessions/",  # Default directory
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            # User selected a file, show report
            self.show_report_from_file(file_path)
        else:
            # User cancelled, restart monitoring
            QMessageBox.information(self, "Report Cancelled", 
                                  "Session has ended but no file was selected.\nYou can restart the application for a new session.")

    def show_report_from_file(self, file_path):
        """Load CSV file and display report"""
        try:
            import csv
            from datetime import datetime
            
            # Read CSV file
            events = []
            total_duration = 0
            bpm_readings = []
            hrv_readings = []
            
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('Is_Apnea_Event') == '1':
                        events.append({
                            'timestamp': row.get('Timestamp', ''),
                            'bpm': row.get('BPM', '0'),
                            'hrv': row.get('HRV_RMSSD', '0')
                        })
                    
                    if row.get('BPM'):
                        bpm_readings.append(float(row['BPM']))
                    if row.get('HRV_RMSSD'):
                        hrv_readings.append(float(row['HRV_RMSSD']))
            
            # Calculate statistics
            total_events = len(events)
            avg_bpm = sum(bpm_readings) / len(bpm_readings) if bpm_readings else 0
            avg_hrv = sum(hrv_readings) / len(hrv_readings) if hrv_readings else 0
            
            # Calculate duration (approximate from number of rows)
            total_rows = len(bpm_readings)
            total_duration_sec = total_rows / 250  # 250 Hz sampling
            total_duration_min = total_duration_sec / 60
            
            # Prepare report data
            report_data = {
                'file_path': file_path,
                'total_events': total_events,
                'duration': f"{int(total_duration_min)} min {int(total_duration_sec % 60)} sec",
                'avg_bpm': round(avg_bpm, 1),
                'avg_hrv': round(avg_hrv, 1),
                'events': events
            }
            
            # Show report window
            self.report_viewer = ReportViewer(report_data)
            self.report_viewer.show()
            
        except Exception as e:
            QMessageBox.critical(self, "Error Loading File", 
                               f"Failed to load session file:\n{str(e)}")

    def update_sensor_status(self, is_ok: bool, message: str):
        if not self.session_active:
            return
        self.status_label.setText(message)
        if not is_ok:
            self.status_label.setStyleSheet("font-size: 16px; color: red; font-weight: bold;")
            self.peak_scatter.setData([], [])   
            self.current_peaks = []
        else:
            self.status_label.setStyleSheet("font-size: 16px; color: green; font-weight: bold;")

    def update_bpm(self, bpm: int):
        if not self.session_active:
            return
        self.bpm_label.setText(f"BPM: {bpm}")
        color = "green" if 40 <= bpm <= 150 else "red"
        self.bpm_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")

    def update_rr(self, rr_intervals_ms: list):
        if not self.session_active:
            return
        if rr_intervals_ms:
            latest_rr = rr_intervals_ms[-1]
            self.rr_label.setText(f"RR: {latest_rr:.0f} ms")
            self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkorange;")

    def update_hrv(self, hrv_value: float):
        if not self.session_active:
            return
        self.hrv_label.setText(f"HRV (RMSSD): {hrv_value:.1f} ms")
        self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")

    def update_peaks_graph(self, x_peaks: list, y_peaks: list):
        if not self.session_active:
            return
        for new_x, new_y in zip(x_peaks, y_peaks):
            is_duplicate = False
            for i, existing_peak in enumerate(self.current_peaks):
                if abs(existing_peak[0] - new_x) < 30:
                    self.current_peaks[i] = [new_x, new_y]
                    is_duplicate = True
                    break
            if not is_duplicate:
                self.current_peaks.append([new_x, new_y])

    def update_apnea_status(self, is_apnea: bool, message: str):
        if not self.session_active:
            return
        self.apnea_status_label.setText(f"Apnea Status: {message}")
        if is_apnea:
            self.apnea_status_label.setStyleSheet("font-size: 22px; font-weight: bold; color: red;")
        else:
            self.apnea_status_label.setStyleSheet("font-size: 22px; font-weight: bold; color: green;")

    def update_apnea_count(self, count: int):
        if not self.session_active:
            return
        self.apnea_count_label.setText(f"Events Detected: {count}")
        # Flash effect
        self.apnea_count_label.setStyleSheet("font-size: 24px; font-weight: bold; color: red;")
        QTimer.singleShot(1000, lambda: self.apnea_count_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkred;"))

    def closeEvent(self, event):
        if self.session_active:
            reply = QMessageBox.question(self, 'Active Session', 
                                       'Session is still active. Are you sure you want to exit?',
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
        self.ecg_service.stop_monitoring()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = ECGDashboard()
    dashboard.show()
    sys.exit(app.exec())