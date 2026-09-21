import csv
import os
from datetime import datetime
from pathlib import Path

class SessionDataLogger:
    """Handles all data logging and session management"""
    
    def __init__(self):
        self.session_folder = None
        self.ecg_file = None
        self.events_file = None
        self.ecg_writer = None
        self.events_writer = None
        self.ecg_csv_file = None  # Keep file handle open
        self.events_csv_file = None
        self.session_start_time = None
        
    def create_session(self):
        """Create a new session folder and CSV files"""
        self.session_start_time = datetime.now()
        timestamp = self.session_start_time.strftime("%Y-%m-%d_%H-%M-%S")
        
        sessions_dir = Path("sessions")
        sessions_dir.mkdir(exist_ok=True)
        
        self.session_folder = sessions_dir / timestamp
        self.session_folder.mkdir(exist_ok=True)
        
        # Create ECG data CSV
        self.ecg_file = self.session_folder / "ecg_readings.csv"
        self.ecg_csv_file = open(self.ecg_file, 'w', newline='')
        self.ecg_writer = csv.writer(self.ecg_csv_file)
        self.ecg_writer.writerow([
            'Timestamp', 'BPM', 'RR_Interval_ms', 'HRV_RMSSD', 'Is_Apnea_Event'
        ])
        
        # Create Apnea Events CSV
        self.events_file = self.session_folder / "apnea_events.csv"
        self.events_csv_file = open(self.events_file, 'w', newline='')
        self.events_writer = csv.writer(self.events_csv_file)
        self.events_writer.writerow([
            'Event_Number', 'Timestamp', 'Time_From_Start',
            'HRV_Before', 'HRV_During', 'Duration_Estimated'
        ])
        
        print(f"[LOG] Session created: {self.session_folder}")
        return self.session_folder
    
    def log_reading(self, bpm, rr_interval, hrv_rmssd, is_apnea=False):
        """Log a single reading to CSV"""
        if self.ecg_writer is None or self.ecg_csv_file.closed:
            return
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ecg_writer.writerow([
            timestamp, bpm, rr_interval, round(hrv_rmssd, 2), 1 if is_apnea else 0
        ])
        self.ecg_csv_file.flush()  # Ensure data is written immediately
    
    def log_apnea_event(self, event_number, hrv_before, hrv_during):
        """Log an apnea event with timestamp"""
        if self.events_writer is None or self.events_csv_file.closed:
            return
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        time_from_start = (datetime.now() - self.session_start_time).total_seconds()
        
        self.events_writer.writerow([
            event_number, timestamp, f"{time_from_start:.1f} sec",
            round(hrv_before, 2), round(hrv_during, 2), "~15 sec"
        ])
        self.events_csv_file.flush()
    
    def close_files(self):
        """Close CSV files properly"""
        if self.ecg_csv_file and not self.ecg_csv_file.closed:
            self.ecg_csv_file.close()
        if self.events_csv_file and not self.events_csv_file.closed:
            self.events_csv_file.close()
    
    def get_session_summary(self):
        """Read back the CSV to generate summary statistics"""
        if not self.events_file or not self.events_file.exists():
            return None
        
        events = []
        with open(self.events_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                events.append(row)
        
        if self.session_start_time:
            duration = (datetime.now() - self.session_start_time).total_seconds()
        else:
            duration = 0
        
        return {
            'total_events': len(events),
            'duration_seconds': duration,
            'duration_formatted': f"{int(duration // 60)} min {int(duration % 60)} sec",
            'events': events,
            'session_folder': str(self.session_folder)
        }