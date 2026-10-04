import json
import shutil

from PySide6.QtCore import QObject, QProcess, Signal


class UpdateCheck(QObject):
    finished = Signal(dict)
    failure = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.finished.connect(self.complete)
        self.process.errorOccurred.connect(self.error)

    def start(self):
        self.process.start('/usr/bin/python', ['-I', '-m', 'velum.updates', '--check'])

    def close(self):
        if self.process.state() != QProcess.NotRunning:
            self.process.blockSignals(True)
            self.process.kill()
            self.process.waitForFinished(1000)

    def complete(self, code, status):
        if code or status != QProcess.NormalExit:
            self.failure.emit('Update check failed. Check internet access or run velum-update --check in a terminal.')
            return
        try:
            data = json.loads(bytes(self.process.readAllStandardOutput()))
            if not isinstance(data, dict) or not all(key in data for key in ('current', 'latest', 'available')):
                raise ValueError('Invalid update response')
            self.finished.emit(data)
        except (ValueError, UnicodeError):
            self.failure.emit('Invalid update response')

    def error(self, error):
        if error == QProcess.FailedToStart:
            self.failure.emit('Cannot start update check. Reinstall the latest Velum package.')


def launch_updater():
    for terminal, flags in (('konsole', ['--separate', '-e']), ('x-terminal-emulator', ['-e']),
                            ('gnome-terminal', ['--']), ('xterm', ['-e'])):
        if binary := shutil.which(terminal):
            started, _pid = QProcess.startDetached(binary, [*flags, '/usr/bin/velum-update', '--interactive'])
            if started:
                return True
    return False
