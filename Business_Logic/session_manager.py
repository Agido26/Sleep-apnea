"""
Clinical session recording for the ECG Apnea Screening app.

Clean-code split:
  - ApneaEvent   : plain data model for ONE apnea event (JSON-serialisable)
  - SessionData  : plain data model for the WHOLE session
  - SessionRecorder: QObject that only LISTENS to ECGService signals and
                     builds the session record. No UI code, no serial code.

The recorder never talks to the serial port and never draws widgets - it
only reacts to signals, which keeps every feature in its own class.
"""
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "sessions"

PRE_EVENT_WINDOW_SEC = 15    # BPM averaged over this window BEFORE an event
POST_EVENT_WINDOW_SEC = 15   # BPM averaged over this window AFTER an event


def now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def format_clock(seconds: float) -> str:
    """1234 -> '00:20:34' (used by the UI for durations)."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ApneaEvent:
    """Everything a doctor wants to know about one detected apnea event."""
    event_number: int
    timestamp: str                 # wall-clock time, e.g. 2026-09-22T17:31:05
    elapsed_seconds: float         # time since session start
    hrv_baseline_ms: float         # normal HRV BEFORE the event
    hrv_at_event_ms: float         # HRV at the moment of detection
    drop_ratio: float              # hrv_at_event / hrv_baseline
    bpm_before: Optional[float] = None
    bpm_after: Optional[float] = None
    complete: bool = False         # True once the post-event BPM window closed

    @property
    def drop_percent(self) -> float:
        return round((1.0 - self.drop_ratio) * 100.0, 1)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["drop_percent"] = self.drop_percent
        return d


@dataclass
class SessionData:
    """The full clinical record of one monitoring session."""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = field(default_factory=now_str)
    patient_name: str = ""
    sample_rate: int = 250
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0
    average_bpm: float = 0.0
    average_hrv_rmssd: float = 0.0
    apnea_events: List[ApneaEvent] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)   # sensor markers etc.

    @property
    def event_count(self) -> int:
        return len(self.apnea_events)

    @property
    def apnea_index(self) -> float:
        """Apnea events per hour (same idea as the clinical AHI)."""
        if self.duration_seconds <= 0:
            return 0.0
        return round(self.event_count / (self.duration_seconds / 3600.0), 2)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["event_count"] = self.event_count
        d["apnea_index"] = self.apnea_index
        return d

    @staticmethod
    def from_dict(data: Dict) -> "SessionData":
        event_fields = set(ApneaEvent.__dataclass_fields__)
        events = [ApneaEvent(**{k: v for k, v in e.items() if k in event_fields})
                  for e in data.get("apnea_events", [])]
        session_fields = set(SessionData.__dataclass_fields__) - {"apnea_events"}
        base = {k: v for k, v in data.items() if k in session_fields}
        base["apnea_events"] = events
        return SessionData(**base)


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------
class SessionRecorder(QObject):
    """
    Builds the session record live, purely from ECGService signals:
      bpm_updated             -> on_bpm()
      hrv_updated             -> on_hrv()
      apnea_event_occurred    -> on_apnea_event()
      sensor_status_changed   -> on_sensor_status()
    """

    event_recorded = pyqtSignal(object)    # ApneaEvent (for live UI updates)
    session_saved = pyqtSignal(str)        # path of the saved JSON file

    def __init__(self, sessions_dir: Path = SESSIONS_DIR, parent=None):
        super().__init__(parent)
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.session = SessionData()
        self._bpm_samples: deque = deque()   # (monotonic_time, bpm)
        self._hrv_samples: deque = deque()   # (monotonic_time, rmssd)
        self._start_monotonic: Optional[float] = None
        self._active = False
        self._post_event: Optional[dict] = None
        self._last_note = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, patient_name: str = "") -> None:
        """Begin a new session (called automatically when the app starts)."""
        self.session = SessionData(patient_name=patient_name, start_time=now_str())
        self._bpm_samples.clear()
        self._hrv_samples.clear()
        self._post_event = None
        self._last_note = ""
        self._start_monotonic = time.monotonic()
        self._active = True

    def stop(self) -> SessionData:
        """Finish the session, compute averages, save JSON, return the record."""
        self._active = False
        self._finalize_post_event()
        self.session.end_time = now_str()
        if self._start_monotonic is not None:
            self.session.duration_seconds = round(
                time.monotonic() - self._start_monotonic, 1)
        if self._bpm_samples:
            self.session.average_bpm = round(
                sum(b for _, b in self._bpm_samples) / len(self._bpm_samples), 1)
        if self._hrv_samples:
            self.session.average_hrv_rmssd = round(
                sum(h for _, h in self._hrv_samples) / len(self._hrv_samples), 1)
        self.save()
        return self.session

    def is_active(self) -> bool:
        return self._active

    def elapsed_seconds(self) -> float:
        if not self._active or self._start_monotonic is None:
            return 0.0
        return time.monotonic() - self._start_monotonic

    # ------------------------------------------------------------------
    # Slots - connected to ECGService signals
    # ------------------------------------------------------------------
    def on_bpm(self, bpm: int) -> None:
        if not self._active or bpm <= 0:
            return
        now = time.monotonic()
        self._bpm_samples.append((now, bpm))
        self._update_post_event_window(now, bpm)

    def on_hrv(self, hrv: float) -> None:
        if not self._active or hrv <= 0:
            return
        self._hrv_samples.append((time.monotonic(), hrv))

    def on_apnea_event(self, details: dict) -> None:
        """Called when ECGService confirms an apnea event."""
        if not self._active:
            return
        self._finalize_post_event()   # close the previous event's post-window
        now = time.monotonic()
        bpm_before = self._avg_bpm_between(now - PRE_EVENT_WINDOW_SEC, now)
        event = ApneaEvent(
            event_number=len(self.session.apnea_events) + 1,
            timestamp=details.get("timestamp", now_str()),
            elapsed_seconds=round(now - self._start_monotonic, 1),
            hrv_baseline_ms=round(details.get("baseline_rmssd", 0.0), 1),
            hrv_at_event_ms=round(details.get("rmssd_at_event", 0.0), 1),
            drop_ratio=round(details.get("drop_ratio", 0.0), 3),
            bpm_before=bpm_before,
        )
        self.session.apnea_events.append(event)
        self._post_event = {
            "event": event,
            "deadline": now + POST_EVENT_WINDOW_SEC,
            "samples": [],
        }
        self.event_recorded.emit(event)

    def on_sensor_status(self, is_ok: bool, message: str) -> None:
        """Log sensor connect/disconnect markers (explains gaps to a doctor)."""
        if not self._active or message == self._last_note:
            return
        self._last_note = message
        state = "OK" if is_ok else "PROBLEM"
        self.session.notes.append(f"[{now_str()}] {state}: {message}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self) -> Path:
        fname = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = self.sessions_dir / fname
        path.write_text(json.dumps(self.session.to_dict(), indent=2),
                        encoding="utf-8")
        self.session_saved.emit(str(path))
        return path

    @staticmethod
    def list_sessions(sessions_dir: Path = SESSIONS_DIR) -> List[Path]:
        d = Path(sessions_dir)
        if not d.exists():
            return []
        return sorted(d.glob("*.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    @staticmethod
    def load(path) -> SessionData:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return SessionData.from_dict(data)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _avg_bpm_between(self, t_from: float, t_to: float) -> Optional[float]:
        vals = [b for t, b in self._bpm_samples if t_from <= t <= t_to]
        if not vals:                       # very early event -> use what we have
            vals = [b for _, b in self._bpm_samples]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    def _update_post_event_window(self, now: float, bpm: int) -> None:
        """Collect BPM samples for the 15 s AFTER an event."""
        pe = self._post_event
        if pe is None:
            return
        if now <= pe["deadline"]:
            pe["samples"].append(bpm)
        else:
            self._finalize_post_event()

    def _finalize_post_event(self) -> None:
        pe = self._post_event
        if pe is None:
            return
        event = pe["event"]
        if pe["samples"]:
            event.bpm_after = round(sum(pe["samples"]) / len(pe["samples"]), 1)
            event.complete = True
        self._post_event = None
