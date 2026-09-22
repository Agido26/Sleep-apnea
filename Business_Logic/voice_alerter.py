"""
Voice alert for apnea events (Feature 3).

Clean-code notes:
  - The pyttsx3 engine is created and used ONLY on a background thread,
    so text-to-speech never freezes the GUI.
  - If pyttsx3 is not installed (or fails at runtime), the alerter falls
    back to a system beep, so the app always makes some sound.
  - The UI only calls: alert_apnea(), speak(), set_enabled(), shutdown().
"""
import queue
import threading


class VoiceAlerter:
    """Small speak-queue wrapper around pyttsx3 (with beep fallback)."""

    def __init__(self, enabled: bool = True, rate: int = 165, volume: float = 1.0):
        self._enabled = enabled
        self._rate = rate
        self._volume = volume
        self._queue = queue.Queue()
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    # ---------------- public API ----------------
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def alert_apnea(self, event_number: int) -> None:
        self.speak(f"Warning. Apnea event detected. Event number {event_number}.")

    def speak(self, text: str) -> None:
        if self._enabled:
            self._queue.put(text)

    def shutdown(self) -> None:
        self._running = False

    # ---------------- internals ----------------
    def _worker_loop(self) -> None:
        engine = self._init_engine()
        while self._running:
            try:
                text = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if engine is not None:
                try:
                    engine.say(text)
                    engine.runAndWait()
                    continue
                except Exception:
                    engine = None   # TTS died -> fall back to beeps
            self._beep()

    def _init_engine(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)
            return engine
        except Exception:
            return None

    @staticmethod
    def _beep() -> None:
        try:
            import winsound
            winsound.Beep(1000, 600)
        except Exception:
            try:
                print("\a", end="", flush=True)
            except Exception:
                pass
