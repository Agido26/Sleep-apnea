from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem, 
                             QHBoxLayout, QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import csv
from pathlib import Path

class ReportWindow(QMainWindow):
    def __init__(self, report_data):
        super().__init__()
        self.report_data = report_data
        self.setWindowTitle("Sleep Apnea Screening - Clinical Report")
        self.resize(900, 700)
        
        self.init_ui()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Header
        title = QLabel("SLEEP APNEA SCREENING REPORT")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Session Info
        info_layout = QHBoxLayout()
        
        duration_label = QLabel(f"Session Duration: {self.report_data['duration']}")
        duration_label.setFont(QFont("Arial", 12))
        
        events_label = QLabel(f"Total Apnea Events: {self.report_data['total_events']}")
        events_label.setFont(QFont("Arial", 12, QFont.Bold))
        events_label.setStyleSheet("color: darkred;")
        
        info_layout.addWidget(duration_label)
        info_layout.addWidget(events_label)
        layout.addLayout(info_layout)
        
        # Pattern Analysis
        pattern_box = QLabel(f"Event Pattern Analysis:\n{self.report_data['pattern']}")
        pattern_box.setFont(QFont("Arial", 11))
        pattern_box.setStyleSheet("background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        pattern_box.setWordWrap(True)
        layout.addWidget(pattern_box)
        
        # Events Timeline Table
        table_label = QLabel("Detailed Event Timeline:")
        table_label.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(table_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Event #", "Time", "Time From Start", "HRV Before", "HRV During"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        
        # Populate table
        events = self.report_data['events_timeline']
        self.table.setRowCount(len(events))
        
        for i, event in enumerate(events):
            self.table.setItem(i, 0, QTableWidgetItem(event['Event_Number']))
            self.table.setItem(i, 1, QTableWidgetItem(event['Timestamp']))
            self.table.setItem(i, 2, QTableWidgetItem(event['Time_From_Start']))
            self.table.setItem(i, 3, QTableWidgetItem(event['HRV_Before']))
            self.table.setItem(i, 4, QTableWidgetItem(event['HRV_During']))
        
        layout.addWidget(self.table)
        
        # Recommendation based on pattern
        recommendation = self._get_recommendation()
        rec_box = QLabel(f"Clinical Recommendation:\n{recommendation}")
        rec_box.setFont(QFont("Arial", 12))
        rec_box.setStyleSheet("background-color: #e8f4f8; padding: 15px; border-radius: 5px; border-left: 5px solid #2196F3;")
        rec_box.setWordWrap(True)
        layout.addWidget(rec_box)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        save_btn = QPushButton("Save Report as CSV")
        save_btn.clicked.connect(self.save_report)
        save_btn.setStyleSheet("padding: 10px; background-color: #4CAF50; color: white; font-size: 14px;")
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("padding: 10px; background-color: #f44336; color: white; font-size: 14px;")
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
    
    def _get_recommendation(self):
        """Generate clinical recommendation based on events and pattern"""
        total_events = self.report_data['total_events']
        pattern = self.report_data['pattern']
        
        if total_events == 0:
            return "No apnea events detected during this session. Patient shows normal HRV patterns."
        
        if "CLUSTERED" in pattern:
            return (f"⚠️ HIGH PRIORITY: {total_events} apnea events detected with CLUSTERED pattern.\n"
                    f"This suggests possible true sleep apnea. STRONGLY recommend full Polysomnography (PSG) "
                    f"evaluation at hospital for definitive diagnosis.")
        elif "MODERATE" in pattern:
            return (f"⚠️ MODERATE CONCERN: {total_events} apnea events detected.\n"
                    f"Events are moderately scattered. Recommend follow-up monitoring or "
                    f"consider PSG if patient has symptoms (snoring, daytime fatigue).")
        else:
            return (f"ℹ️ LOW CONCERN: {total_events} isolated apnea events detected.\n"
                    f"Events are scattered and may be positional or normal variation. "
                    f"Monitor symptoms; PSG only if clinical symptoms present.")
    
    def save_report(self):
        """Save report to CSV file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Report", "", "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["SLEEP APNEA SCREENING REPORT"])
                    writer.writerow(["Session Duration", self.report_data['duration']])
                    writer.writerow(["Total Events", self.report_data['total_events']])
                    writer.writerow(["Pattern Analysis", self.report_data['pattern']])
                    writer.writerow([])
                    writer.writerow(["Event Timeline"])
                    writer.writerow(["Event #", "Timestamp", "Time From Start", "HRV Before", "HRV During"])
                    
                    for event in self.report_data['events_timeline']:
                        writer.writerow([
                            event['Event_Number'],
                            event['Timestamp'],
                            event['Time_From_Start'],
                            event['HRV_Before'],
                            event['HRV_During']
                        ])
                
                QMessageBox.information(self, "Success", f"Report saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save report:\n{str(e)}")