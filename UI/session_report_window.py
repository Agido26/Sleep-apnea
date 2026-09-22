"""
Post-session screen (Feature 2).

Page 1 (picker):  view the just-finished session, choose a previous session,
                  or upload a session file.
Page 2 (report):  clinical summary cards + the full apnea-event table.

This window only *displays* SessionData objects - all recording logic lives
in Business_Logic/session_manager.py (SessionRecorder).
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QListWidget, QListWidgetItem,
                             QStackedWidget, QTableWidget, QTableWidgetItem,
                             QFileDialog, QAbstractItemView, QHeaderView,
                             QMessageBox)

from Business_Logic.session_manager import SessionData, SessionRecorder, format_clock


class SessionReportWindow(QMainWindow):
    new_session_requested = pyqtSignal()
    window_closed = pyqtSignal()

    EVENT_COLUMNS = ["#", "Timestamp", "Elapsed", "HRV before (ms)",
                     "HRV at event (ms)", "HRV drop", "BPM before",
                     "BPM after", "Status"]

    def __init__(self, current_session: Optional[SessionData] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clinical Session Report")
        self.resize(1080, 660)
        self.current_session = current_session

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_picker_page())   # index 0
        self.stack.addWidget(self._build_report_page())   # index 1
        self.setCentralWidget(self.stack)
        self._refresh_session_list()

    # ------------------------------------------------------------------
    # Page 1: picker (current / previous / upload)
    # ------------------------------------------------------------------
    def _build_picker_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout()

        title = QLabel("Session saved ✅ — choose what to do next")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        self.view_current_button = QPushButton("📋 View current session report")
        self.view_current_button.setStyleSheet("font-size: 15px; padding: 8px;")
        self.view_current_button.clicked.connect(self._view_current_session)
        if self.current_session is None:
            self.view_current_button.setVisible(False)
        layout.addWidget(self.view_current_button)

        prev_label = QLabel("Or choose a previous session (double-click to open):")
        prev_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(prev_label)

        self.session_list = QListWidget()
        self.session_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.session_list.itemDoubleClicked.connect(self._load_selected_session)
        layout.addWidget(self.session_list)

        upload_button = QPushButton("⬆ Upload session file (.json)...")
        upload_button.setStyleSheet("font-size: 15px; padding: 8px;")
        upload_button.clicked.connect(self._upload_session_file)
        layout.addWidget(upload_button)

        new_session_button = QPushButton("▶ Start New Session")
        new_session_button.setStyleSheet(
            "font-size: 15px; font-weight: bold; padding: 8px; "
            "color: white; background-color: #2e7d32;")
        new_session_button.clicked.connect(self._request_new_session)
        layout.addWidget(new_session_button)

        page.setLayout(layout)
        return page

    # ------------------------------------------------------------------
    # Page 2: clinical report
    # ------------------------------------------------------------------
    def _build_report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout()

        top_row = QHBoxLayout()
        back_button = QPushButton("⬅ Back")
        back_button.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        top_row.addWidget(back_button)
        top_row.addStretch(1)
        new_session_button = QPushButton("▶ Start New Session")
        new_session_button.setStyleSheet(
            "color: white; background-color: #2e7d32; font-weight: bold; padding: 6px 12px;")
        new_session_button.clicked.connect(self._request_new_session)
        top_row.addWidget(new_session_button)
        layout.addLayout(top_row)

        self.report_title = QLabel("Session Report")
        self.report_title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(self.report_title)

        # --- Summary cards ---
        summary_row = QHBoxLayout()
        self.summary_labels = {}
        for key, title, color in [
            ("duration", "Duration", "black"),
            ("events", "Apnea Events", "darkred"),
            ("index", "Apnea Index (events/h)", "darkred"),
            ("bpm", "Average BPM", "blue"),
            ("hrv", "Average HRV (RMSSD)", "purple"),
            ("drop", "Max HRV Drop", "darkorange"),
        ]:
            card = QVBoxLayout()
            t = QLabel(title)
            t.setStyleSheet("font-size: 12px; color: gray;")
            v = QLabel("--")
            v.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {color};")
            card.addWidget(t)
            card.addWidget(v)
            self.summary_labels[key] = v
            summary_row.addLayout(card)
        layout.addLayout(summary_row)

        layout.addWidget(QLabel("Apnea events:"))
        self.events_table = QTableWidget(0, len(self.EVENT_COLUMNS))
        self.events_table.setHorizontalHeaderLabels(self.EVENT_COLUMNS)
        self.events_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.events_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.events_table)

        self.notes_label = QLabel("")
        self.notes_label.setStyleSheet("color: gray;")
        self.notes_label.setWordWrap(True)
        layout.addWidget(self.notes_label)

        page.setLayout(layout)
        return page

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _view_current_session(self):
        if self.current_session is not None:
            self._show_session(self.current_session)

    def _refresh_session_list(self):
        self.session_list.clear()
        for path in SessionRecorder.list_sessions():
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.session_list.addItem(item)

    def _load_selected_session(self, item: QListWidgetItem):
        self._load_from_path(item.data(Qt.ItemDataRole.UserRole))

    def _upload_session_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Upload session file", "", "Session files (*.json)")
        if path:
            self._load_from_path(path)

    def _load_from_path(self, path):
        try:
            session = SessionRecorder.load(path)
        except Exception as e:
            QMessageBox.warning(self, "Invalid session file",
                                f"Could not read:\n{path}\n\n{e}")
            return
        self._show_session(session)

    def _show_session(self, session: SessionData):
        self.report_title.setText(
            f"Session Report — {session.session_id}   |   "
            f"Patient: {session.patient_name or '—'}   |   "
            f"Started: {session.start_time or '—'}")
        self.summary_labels["duration"].setText(format_clock(session.duration_seconds))
        self.summary_labels["events"].setText(str(session.event_count))
        self.summary_labels["index"].setText(f"{session.apnea_index:.2f}")
        self.summary_labels["bpm"].setText(f"{session.average_bpm:.1f}")
        self.summary_labels["hrv"].setText(f"{session.average_hrv_rmssd:.1f} ms")
        max_drop = max((e.drop_percent for e in session.apnea_events), default=0.0)
        self.summary_labels["drop"].setText(f"{max_drop:.1f}%")

        self._fill_events_table(session.apnea_events)
        self.notes_label.setText(
            "Notes: " + " | ".join(session.notes) if session.notes else "Notes: —")
        self.stack.setCurrentIndex(1)

    def _fill_events_table(self, events):
        if not events:
            self.events_table.setRowCount(1)
            empty = QTableWidgetItem("No apnea events were detected during this session.")
            self.events_table.setItem(0, 0, empty)
            self.events_table.setSpan(0, 0, 1, len(self.EVENT_COLUMNS))
            return
        self.events_table.setRowCount(len(events))
        for row, ev in enumerate(events):
            status = "✔ complete" if ev.complete else "post-window pending"
            values = [
                str(ev.event_number),
                ev.timestamp,
                format_clock(ev.elapsed_seconds),
                f"{ev.hrv_baseline_ms:.1f}",
                f"{ev.hrv_at_event_ms:.1f}",
                f"{ev.drop_percent:.1f}%",
                f"{ev.bpm_before:.1f}" if ev.bpm_before is not None else "--",
                f"{ev.bpm_after:.1f}" if ev.bpm_after is not None else "--",
                status,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 5:   # HRV drop column in red
                    item.setForeground(QColor("darkred"))
                self.events_table.setItem(row, col, item)

    def _request_new_session(self):
        self.new_session_requested.emit()
        self.close()

    def closeEvent(self, event):
        self.window_closed.emit()
        super().closeEvent(event)
