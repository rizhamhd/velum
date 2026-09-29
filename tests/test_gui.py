import os
import tempfile
import unittest
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
try:
    from PySide6.QtWidgets import QApplication

    from velum.gui.window import Window
except ImportError:
    QApplication = None

from test_vless import BASE

from velum.config.profiles import ProfileStore


@unittest.skipUnless(QApplication, 'Qt is not installed')
class GuiTests(unittest.TestCase):
    def test_profiles_and_state(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            store.save(BASE)
            window = Window(store=store)
            self.assertEqual(window.profiles.rowCount(), 1)
            window.update_status({'state': 'VERIFYING', 'checks': []})
            self.assertNotIn('CONNECTED', window.summary.text())
            window.error('helper unavailable')
            self.assertIn('ERROR', window.summary.text())
            window.close()
            app.processEvents()

    def test_tray_notifications_ignore_transient_rechecks(self):
        from unittest.mock import Mock

        from velum.notifications.tray import Tray
        app = QApplication.instance() or QApplication([])
        tray = Tray.__new__(Tray)
        tray.icon, tray.last, tray.last_notice = Mock(), None, None
        tray.update('DISCONNECTED')
        tray.update('CONNECTED')
        tray.update('VERIFYING')
        tray.update('CONNECTED')
        self.assertEqual(tray.icon.showMessage.call_count, 1)
        tray.update('ERROR', 'Tunnel lost')
        tray.update('RECONNECTING')
        tray.update('ERROR', 'Tunnel lost')
        self.assertEqual(tray.icon.showMessage.call_count, 2)
        app.processEvents()
