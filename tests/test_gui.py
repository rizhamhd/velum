import os
import tempfile
import unittest
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
try:
    from PySide6.QtWidgets import QApplication

    from velum.gui.window import ProfileDialog, Window
except ImportError:
    QApplication = None

from test_vless import BASE

from velum.config.profiles import ProfileStore


@unittest.skipUnless(QApplication, 'Qt is not installed')
class GuiTests(unittest.TestCase):
    def test_public_ip_preference_survives_reopen_and_reaches_helper(self):
        from unittest.mock import Mock

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            store.save(BASE)
            first = Window(store=store, client=Mock())
            self.assertTrue(first.expect_change.isChecked())
            first.expect_change.setChecked(False)
            self.assertEqual(first.preferences_path.stat().st_mode & 0o777, 0o600)
            first.close()
            client = Mock()
            reopened = Window(store=store, client=client)
            self.assertFalse(reopened.expect_change.isChecked())
            reopened.connect_vpn()
            self.assertIs(client.send.call_args.kwargs['settings']['expect_change'], False)
            reopened.expect_change.setChecked(True)
            reopened.close()
            restored = Window(store=store, client=Mock())
            self.assertTrue(restored.expect_change.isChecked())
            restored.close()
            app.processEvents()

    def test_invalid_saved_public_ip_preference_is_reported(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            (Path(d) / 'settings.json').write_text('{"version":1,"expect_change":"false"}')
            window = Window(store=store)
            self.assertTrue(window.expect_change.isChecked())
            self.assertIn('Cannot read saved settings', window.summary.text())
            window.close()
            app.processEvents()

    def test_certificate_name_edit_save_reload_and_export(self):
        from velum.config.vless import parse_vless

        app = QApplication.instance() or QApplication([])
        uri = BASE + '?security=tls&type=ws&sni=youtube.com'
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            saved = store.save(uri)
            dialog = ProfileDialog(None, saved)
            self.assertEqual(dialog.certificate_name.text(), '')
            dialog.certificate_name.setText('cert.example.invalid')
            saved = store.save(dialog.profile_uri(), saved['name'], saved['id'])
            dialog.close()
            exported = Path(d) / 'export.json'
            store.export(saved['id'], exported)
            store.delete(saved['id'])
            store.import_file(exported)
            saved = store.list()[0]
            dialog = ProfileDialog(None, saved)
            self.assertEqual(dialog.certificate_name.text(), 'cert.example.invalid')
            self.assertEqual(parse_vless(dialog.profile_uri()).sni, 'youtube.com')
            window = Window(store=store)
            self.assertEqual(window.profiles.item(0, 7).text(), 'cert.example.invalid')
            window.close()
            dialog.uri.setText(BASE)
            self.assertFalse(dialog.certificate_name.isEnabled())
            self.assertEqual(dialog.certificate_name.text(), '')
            self.assertEqual(dialog.profile_uri(), BASE)
            dialog.close()
            app.processEvents()

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
