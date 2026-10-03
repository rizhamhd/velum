from PySide6.QtCore import QObject, QProcess, Signal


class EmergencyStop(QObject):
    finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.running = False
        self.process.finished.connect(self.complete)
        self.process.errorOccurred.connect(self.process_error)

    def start(self):
        if self.running:
            return
        self.running = True
        self.process.start('/usr/bin/pkexec', ['/usr/lib/velum/emergency-stop'])

    def complete(self, code, status):
        if not self.running:
            return
        self.running = False
        success = status == QProcess.NormalExit and code == 0
        if code in (126, 127):
            message = 'Administrator authorization was canceled or denied. The VPN may still be running.'
        else:
            message = ('Emergency stop failed. VPN/network state is unknown. '
                       'Run sudo /usr/lib/velum/recover in a terminal, then sudo systemctl start velum.socket.')
        self.finished.emit(success, '' if success else message)

    def process_error(self, error):
        if self.running and error == QProcess.FailedToStart:
            self.running = False
            self.finished.emit(False, 'Cannot start emergency recovery. Install the updated Velum package '
                               'and Polkit, or run sudo /usr/lib/velum/recover in a terminal.')
