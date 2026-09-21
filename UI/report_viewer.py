from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem, 
                             QHBoxLayout, QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import csv

class ReportViewer(QMainWindow):
    def __init__(self, report_data):
        super().__init__()
        self.report_data = report_data
        self.setWindowTitle("Sleep Apnea Screening - Session Report")
        self.resize(900, 700)
        
        self.init_ui()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Header
        title = QLabel("SESSION ANALYSIS REPORT")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # File info
        file_label = QLabel(f"File: {self.report_data['file_path']}")
        file_label.setFont(QFont("Arial", 10))
        file_label.setStyleSheet("color: #666;")
        layout.addWidget(file_label)
        
        # Summary Box
        summary_layout = QHBoxLayout()
        
        self._add_summary_box(summary_layout, "Session Duration", 
                             self.report_data['duration'], "#2196F3")
        self._add_summary_box(summary_layout, "Total Apnea Events", 
                             str(self.report_data['total_events']), "#f44336")
        self._add_summary_box(summary_layout, "Avg Heart Rate", 
                             f"{self.report_data['avg_bpm']} BPM", "#4CAF50")
        self._add_summary_box(summary_layout, "Avg HRV", 
                             f"{self.report_data['avg_hrv']} ms", "#9C27B0")
        
        layout.addLayout(summary_layout)
        
        # Events Table
        table_label = QLabel("Detected Apnea Events Timeline:")
        table_label.setFont(QFont("Arial", 14, QFont.Bold))
        layout.addWidget(table_label)
        
        if self.report_data['events']:
            self.table = QTableWidget()
            self.table.setColumnCount(3)
            self.table.setHorizontalHeaderLabels(["Time", "BPM", "HRV (RMSSD)"])
            self.table.horizontalHeader().setStretchLastSection(True)
            
            events = self.report_data['events']
            self.table.setRowCount(len(events))
            
            for i, event in enumerate(events):
                self.table.setItem(i, 0, QTableWidgetItem(event['timestamp']))
                self.table.setItem(i, 1, QTableWidgetItem(event['bpm']))
                self.table.setItem(i, 2, QTableWidgetItem(event['hrv']))
            
            layout.addWidget(self.table)
        else:
            no_events_label = QLabel("✓ No apnea events detected during this session.")
            no_events_label.setFont(QFont("Arial", 14))
            no_events_label.setStyleSheet("color: green; padding: 20px;")
            no_events_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(no_events_label)
        
        # Recommendation
        recommendation = self._get_recommendation()
        rec_box = QLabel(f"Clinical Recommendation:\n{recommendation}")
        rec_box.setFont(QFont("Arial", 12))
        rec_box.setStyleSheet("background-color: #e8f4f8; padding: 15px; border-radius: 5px; border-left: 5px solid #2196F3;")
        rec_box.setWordWrap(True)
        layout.addWidget(rec_box)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        export_btn = QPushButton("Export Report as CSV")
        export_btn.clicked.connect(self.export_report)
        export_btn.setStyleSheet("padding: 10px; background-color: #4CAF50; color: white; font-size: 14px;")
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("padding: 10px; background-color: #f44336; color: white; font-size: 14px;")
        
        btn_layout.addWidget(export_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
    
    def _add_summary_box(self, layout, title, value, color):
        box = QWidget()
        box.setStyleSheet(f"background-color: {color}; color: white; border-radius: 10px; padding: 15px;")
        box_layout = QVBoxLayout(box)
        box_layout.setAlignment(Qt.AlignCenter)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("Arial", 10))
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: white;")
        
        value_label = QLabel(value)
        value_label.setFont(QFont("Arial", 18, QFont.Bold))
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("color: white;")
        
        box_layout.addWidget(title_label)
        box_layout.addWidget(value_label)
        layout.addWidget(box)
    
    def _get_recommendation(self):
        total_events = self.report_data['total_events']
        
        if total_events == 0:
            return "No apnea events detected during this session. Patient shows normal HRV patterns. No immediate action required."
        elif total_events < 5:
            return f"Low number of events ({total_events}) detected. Monitor symptoms and consider follow-up if patient experiences daytime fatigue or snoring."
        elif total_events < 15:
            return f"Moderate number of events ({total_events}) detected. Recommend clinical evaluation and possible sleep study (PSG) for definitive diagnosis."
        else:
            return f"HIGH number of events ({total_events}) detected. STRONGLY recommend immediate referral for comprehensive Polysomnography (PSG) evaluation at hospital."
    
    def export_report(self):
        """Export report to CSV"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", "", "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["SLEEP APNEA SCREENING REPORT"])
                    writer.writerow(["Session Duration", self.report_data['duration']])
                    writer.writerow(["Total Events", self.report_data['total_events']])
                    writer.writerow(["Average BPM", self.report_data['avg_bpm']])
                    writer.writerow(["Average HRV", self.report_data['avg_hrv']])
                    writer.writerow([])
                    writer.writerow(["Event Timeline"])
                    writer.writerow(["Timestamp", "BPM", "HRV (RMSSD)"])
                    
                    for event in self.report_data['events']:
                        writer.writerow([
                            event['timestamp'],
                            event['bpm'],
                            event['hrv']
                        ])
                
                QMessageBox.information(self, "Success", f"Report exported to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export report:\n{str(e)}")