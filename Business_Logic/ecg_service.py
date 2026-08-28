from PyQt6.QtCore import QObject, pyqtSignal
from Data.ecg_serial.ecg_serial_receiver import ECGSerialReader

class ECGService(QObject):
    """
    Business Logic Layer (Router):
    Receives processed results from the background thread and routes them to the UI.
    """
    # Signals to UI
    live_sample_ready = pyqtSignal(int)
    bpm_updated = pyqtSignal(int)
    hrv_updated = pyqtSignal(float)
    peaks_detected = pyqtSignal(list, list)
    apnea_warning_triggered = pyqtSignal(bool, str)
    sensor_status_changed = pyqtSignal(bool, str)

    def __init__(self, port="COM3", baudrate=115200, sample_rate=250):
        super().__init__()
        self.sample_rate = sample_rate
        
        # Initialize Background Reader
        self.reader = ECGSerialReader(port=port, baudrate=baudrate, sample_rate=self.sample_rate)
        
        # Wire Background Thread signals directly to UI signals
        self.reader.new_sample_ready.connect(self.live_sample_ready.emit)
        self.reader.analysis_results.connect(self._handle_analysis_results)
        self.reader.leads_off_detected.connect(self._handle_leads_off)
        self.reader.connection_error.connect(self._handle_connection_error)

    def start_monitoring(self):
        self.reader.start()

    def stop_monitoring(self):
        self.reader.stop()

    def _handle_analysis_results(self, bpm: int, hrv: float, x_peaks: list, y_peaks: list):
        """Receives pre-calculated data from background thread and emits to UI."""
        self.bpm_updated.emit(bpm)
        self.hrv_updated.emit(hrv)
        self.peaks_detected.emit(x_peaks, y_peaks)
        
        # TODO: Future Apnea Logic (Pathway A & B) will go here!

    def _handle_leads_off(self, is_off: bool):
        if is_off:
            self.sensor_status_changed.emit(False, "Electrode Disconnected!")
        else:
            self.sensor_status_changed.emit(True, "Sensor Connected Normally")

    def _handle_connection_error(self, error_msg: str):
        self.sensor_status_changed.emit(False, f"Error: {error_msg}")