import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalSocket


class Client(QObject):
    received = Signal(dict)
    failure = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.socket = QLocalSocket(self)
        self.buffer = b''
        self.pending = []
        self.socket.connected.connect(self.flush)
        self.socket.readyRead.connect(self.read)
        self.socket.errorOccurred.connect(self.socket_error)
        self.socket.disconnected.connect(lambda: self.failure.emit(
            'Backend connection lost. Protection is unknown; inspect diagnostics before using the network.'))

    def socket_error(self, _):
        self.pending.clear()
        self.failure.emit("Privileged service unavailable. Install the package and enable velum.socket.")

    def send(self, operation, **data):
        self.pending.append({'operation': operation, **data})
        if self.socket.state() == QLocalSocket.ConnectedState:
            self.flush()
        elif self.socket.state() == QLocalSocket.UnconnectedState:
            self.socket.connectToServer('/run/velum.sock')

    def flush(self):
        while self.pending:
            self.socket.write((json.dumps(self.pending.pop(0)) + '\n').encode())

    def read(self):
        self.buffer += bytes(self.socket.readAll())
        if len(self.buffer) > 1024 * 1024:
            self.socket.abort()
            return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                self.received.emit(json.loads(line))
            except (ValueError, UnicodeError):
                self.failure.emit('Invalid response from privileged helper')
