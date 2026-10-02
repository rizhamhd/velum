import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
try:
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete

    from velum.services.client import Client
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication, 'Qt is not installed')
class ClientTests(unittest.TestCase):
    def test_destroying_connected_client_does_not_emit_from_deleted_object(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            server = QLocalServer()
            self.assertTrue(server.listen(str(Path(directory) / 'control.sock')), server.errorString())
            self.addCleanup(server.close)
            client = Client()
            client.socket.connectToServer(server.fullServerName())
            self.assertTrue(client.socket.waitForConnected(1000))
            server.waitForNewConnection(1000)
            peer = server.nextPendingConnection()
            self.assertIsNotNone(peer)
            with patch('sys.excepthook') as errors:
                delete(client)
                app.processEvents()
                errors.assert_not_called()
            peer.close()

    def test_intentional_close_is_silent_and_clears_pending_state(self):
        app = QApplication.instance() or QApplication([])
        client = Client()
        failure = Mock()
        client.failure.connect(failure)
        client.buffer = b'partial response'
        client.pending = [{'operation': 'connect'}]
        client.close()
        app.processEvents()
        failure.assert_not_called()
        self.assertEqual(client.buffer, b'')
        self.assertEqual(client.pending, [])
