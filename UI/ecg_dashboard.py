import sys
from collections import deque
from PyQt6.QtWidgets import (QMainWindow, QApplication, QLabel, QVBoxLayout,
                             QWidget, QHBoxLayout, QPushButton, QCheckBox,
                             QMessageBox)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg

from Business_Logic.ecg_service import ECGService
from Business_Logic.session_manager import SessionRecorder, format_clock
from Business_Logic.voice_alerter import VoiceAlerter
from UI.session_report_window import SessionReportWindow


class ECGDashboard(QMainWindow):
    """
    Live ECG monitoring screen.

    Clean-code split of responsibilities:
      - this class           -> real-time widgets only (graph, labels, buttons)
      - ECGService           -> signal processing + apnea state machine
      - SessionRecorder      -> clinical session record (Feature 1)
      - VoiceAlerter         -> spoken warnings on apnea events (Feature 3)
      - SessionReportWindow  -> post-session report / browser (Feature 2)
    """

    RED_BUTTON = ("font-size: 15px; font-weight: bold; color: white; "
                  "background-color: #b22222; padding: 6px 14px;")
    GREEN_BUTTON = ("font-size: 15px; font-weight: bold; color: white; "
                    "background-color: #2e7d32; padding: 6px 14px;")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Apnea Screening Dashboard")
        self.resize(1200, 650)
        self.report_window = None

        main_layout = QVBoxLayout()
        info_layout = QHBoxLayout()

        # --- Labels ---
        self.status_label = QLabel("Status: Connecting...")
        self.bpm_label = QLabel("BPM: --")
        self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
        self.rr_label = QLabel("RR: -- ms")
        self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkorange;")
        self.hrv_label = QLabel("HRV (RMSSD): -- ms")
        self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")

        self.apnea_status_label = QLabel("Apnea Status: Normal")
        self.apnea_status_label.setStyleSheet("font-size: 22px; font-weight: bold; color: green;")
        self.apnea_count_label = QLabel("Events Detected: 0")
        self.apnea_count_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkred;")

        # --- Session recording indicator ---
        self.session_timer_label = QLabel("● SESSION 00:00:00")
        self.session_timer_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: darkred;")

        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.bpm_label)
        info_layout.addWidget(self.rr_label)
        info_layout.addWidget(self.hrv_label)
        info_layout.addWidget(self.apnea_status_label)
        info_layout.addWidget(self.apnea_count_label)
        info_layout.addWidget(self.session_timer_label)
        main_layout.addLayout(info_layout)

        # --- Controls row ---
        controls_layout = QHBoxLayout()
        self.stop_start_button = QPushButton("⏹ Stop Session & Open Report")
        self.stop_start_button.setStyleSheet(self.RED_BUTTON)
        self.stop_start_button.clicked.connect(self._on_stop_start_clicked)

        self.voice_checkbox = QCheckBox("🔊 Voice alert on apnea")
        self.voice_checkbox.setChecked(True)
        self.voice_checkbox.toggled.connect(
            lambda checked: self.voice_alerter.set_enabled(checked))

        controls_layout.addWidget(self.stop_start_button)
        controls_layout.addWidget(self.voice_checkbox)
        controls_layout.addStretch(1)
        main_layout.addLayout(controls_layout)

        # --- GRAPH: ECG Only ---
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

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.plot_data = deque([512] * 1000, maxlen=1000)
        self.current_peaks = []

        # --- Feature objects (one class per feature) ---
        self.ecg_service = ECGService(port="COM4", baudrate=115200, sample_rate=250)
        self.session_recorder = SessionRecorder()   # Feature 1
        self.voice_alerter = VoiceAlerter(enabled=True)  # Feature 3
        self.session_recorder.start()               # session begins at app start

        # --- Service -> UI ---
        self.ecg_service.live_chunk_ready.connect(self.store_live_chunk)
        self.ecg_service.bpm_updated.connect(self.update_bpm)
        self.ecg_service.rr_updated.connect(self.update_rr)
        self.ecg_service.hrv_updated.connect(self.update_hrv)
        self.ecg_service.peaks_detected.connect(self.update_peaks_graph)
        self.ecg_service.apnea_warning_triggered.connect(self.update_apnea_status)
        self.ecg_service.apnea_event_count_updated.connect(self.update_apnea_count)
        self.ecg_service.sensor_status_changed.connect(self.update_sensor_status)

        # --- Service -> SessionRecorder ---
        self.ecg_service.bpm_updated.connect(self.session_recorder.on_bpm)
        self.ecg_service.hrv_updated.connect(self.session_recorder.on_hrv)
        self.ecg_service.apnea_event_occurred.connect(self.session_recorder.on_apnea_event)
        self.ecg_service.sensor_status_changed.connect(self.session_recorder.on_sensor_status)

        # --- Apnea -> voice alert ---
        self.ecg_service.apnea_event_occurred.connect(self._on_apnea_event_alert)

        self.timer = QTimer()
        self.timer.timeout.connect(self.draw_graph)
        self.timer.start(33)

        self.session_clock = QTimer()
        self.session_clock.timeout.connect(self._update_session_clock)
        self.session_clock.start(1000)

        self.ecg_service.start_monitoring()

    # ------------------------------------------------------------------
    # Graph
    # ------------------------------------------------------------------
    def store_live_chunk(self, chunk: list):
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

    # ------------------------------------------------------------------
    # Vital labels
    # ------------------------------------------------------------------
    def update_sensor_status(self, is_ok: bool, message: str):
        self.status_label.setText(message)
        if not is_ok:
            self.status_label.setStyleSheet("font-size: 16px; color: red; font-weight: bold;")
            self.peak_scatter.setData([], [])
            self.current_peaks = []
            self.bpm_label.setText("BPM: --")
            self.rr_label.setText("RR: -- ms")
            self.hrv_label.setText("HRV (RMSSD): -- ms")
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: gray;")
            self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: gray;")
            self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: gray;")
        else:
            self.status_label.setStyleSheet("font-size: 16px; color: green; font-weight: bold;")
            self.bpm_label.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
            self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkorange;")
            self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")

    def update_bpm(self, bpm: int):
        self.bpm_label.setText(f"BPM: {bpm}")
        color = "green" if 40 <= bpm <= 150 else "red"
        self.bpm_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")

    def update_rr(self, rr_intervals_ms: list):
        if rr_intervals_ms:
            latest_rr = rr_intervals_ms[-1]
            self.rr_label.setText(f"RR: {latest_rr:.0f} ms")
            self.rr_label.setStyleSheet("font-size: 24px; font-weight: bold; color: darkorange;")

    def update_hrv(self, hrv_value: float):
        self.hrv_label.setText(f"HRV (RMSSD): {hrv_value:.1f} ms")
        self.hrv_label.setStyleSheet("font-size: 22px; font-weight: bold; color: purple;")

    def update_peaks_graph(self, x_peaks: list, y_peaks: list):
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
        self.apnea_status_label.setText(f"Apnea Status: {message}")
        if is_apnea:
            self.apnea_status_label.setStyleSheet("font-size: 22px; font-weight: bold; color: red;")
        else:
            self.apnea_status_label.setStyleSheet("font-size: 22px; font-weight: bold; color: green;")

    def update_apnea_count(self, count: int):
        self.apnea_count_label.setText(f"Events Detected: {count}")
        self.apnea_count_label.setStyleSheet("font-size: 24px; font-weight: bold; color: red;")
        QTimer.singleShot(1000, lambda: self.apnea_count_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: darkred;"))

    # ------------------------------------------------------------------
    # Feature hooks
    # ------------------------------------------------------------------
    def _update_session_clock(self):
        seconds = int(self.session_recorder.elapsed_seconds())
        self.session_timer_label.setText(f"● SESSION {format_clock(seconds)}")

    def _on_apnea_event_alert(self, details: dict):
        self.voice_alerter.alert_apnea(details.get("event_count", 0))

    def _on_stop_start_clicked(self):
        if self.session_recorder.is_active():
            self._stop_session()
        else:
            self._start_new_session()

    def _stop_session(self):
        """Feature 2: stop recording, save JSON, open the report window."""
        reply = QMessageBox.question(
            self, "Stop Session",
            "Stop the current session and open the clinical report?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.session_clock.stop()
        self.timer.stop()
        self.ecg_service.stop_monitoring()
        session = self.session_recorder.stop()   # saves JSON automatically
        self.voice_alerter.speak(
            f"Session finished. {session.event_count} apnea events were detected.")
        self.session_timer_label.setText("■ SESSION SAVED")
        self.stop_start_button.setText("▶ Start New Session")
        self.stop_start_button.setStyleSheet(self.GREEN_BUTTON)
        self.report_window = SessionReportWindow(current_session=session)
        self.report_window.new_session_requested.connect(self._start_new_session)
        self.report_window.window_closed.connect(self.show)
        self.report_window.show()
        self.hide()

    def _start_new_session(self):
        self.session_recorder.start()
        self.ecg_service.start_monitoring()
        self.timer.start(33)
        self.session_clock.start(1000)
        self.plot_data = deque([512] * 1000, maxlen=1000)
        self.current_peaks = []
        self.bpm_label.setText("BPM: --")
        self.rr_label.setText("RR: -- ms")
        self.hrv_label.setText("HRV (RMSSD): -- ms")
        self.apnea_status_label.setText("Apnea Status: Normal")
        self.apnea_status_label.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: green;")
        self.apnea_count_label.setText("Events Detected: 0")
        self.status_label.setText("Status: Connecting...")
        self.stop_start_button.setText("⏹ Stop Session & Open Report")
        self.stop_start_button.setStyleSheet(self.RED_BUTTON)
        self.show()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        # Never lose data: save the session even if it wasn't stopped explicitly
        if self.session_recorder.is_active():
            self.session_recorder.stop()
        self.ecg_service.stop_monitoring()
        self.voice_alerter.shutdown()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = ECGDashboard()
    dashboard.show()
    sys.exit(app.exec())
