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
    def test_import_legacy_link_and_keep_invalid_dialog_open(self):
        from PySide6.QtWidgets import QDialog

        app = QApplication.instance() or QApplication([])
        dialog = ProfileDialog(None)
        dialog.uri.setText(BASE + '?type=tcp&host=example.invalid&security=tls&allowInsecure=1')
        self.assertFalse(dialog.certificate_name.isEnabled())
        self.assertIn('verification is disabled', dialog.tls_notice.text())
        uri = dialog.profile_uri()
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            store.save(uri)
            window = Window(store=store)
            self.assertEqual(window.profiles.item(0, 7).text(), 'Verification disabled')
            window.close()
        dialog = ProfileDialog(None)
        dialog.uri.setText('trojan://secret@example.invalid:443?unsupported=secret')
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertIn('Unsupported', dialog.tls_notice.text())
        self.assertNotIn('secret', dialog.tls_notice.text())
        dialog.close()
        app.processEvents()

    def test_update_buttons_show_versions_and_launch_only_on_click(self):
        from unittest.mock import Mock, patch

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            window = Window(store=ProfileStore(Path(d) / 'profiles.json'), client=Mock())
            self.assertFalse(window.install_update_button.isEnabled())
            with patch.object(window.update_check, 'start') as start:
                window.check_update_button.click()
                start.assert_called_once()
                self.assertFalse(window.check_update_button.isEnabled())
            window.update_available({'current': '0.1.0-9', 'latest': '0.1.0-10', 'available': True})
            self.assertIn('0.1.0-10', window.update_label.text())
            self.assertTrue(window.install_update_button.isEnabled())
            with patch('velum.gui.window.launch_updater', return_value=True) as launch:
                launch.assert_not_called()
                window.install_update_button.click()
                launch.assert_called_once()
            window.update_failed('Offline')
            self.assertTrue(window.check_update_button.isEnabled())
            self.assertFalse(window.install_update_button.isEnabled())
            window.close()
            app.processEvents()

    def test_emergency_is_available_while_busy_and_ignores_stale_status(self):
        from unittest.mock import Mock, patch

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            client = Mock()
            window = Window(store=ProfileStore(Path(d) / 'profiles.json'), client=client)
            window.pending_request = 'connecting'
            window.update_status({'state': 'VERIFYING'})
            self.assertTrue(window.kill_button.isEnabled())
            with patch.object(window.emergency, 'start') as start:
                window.kill_button.click()
                window.kill_vpn()
                start.assert_called_once()
            client.close.assert_called_once()
            window.update_status({'state': 'CONNECTED', 'request_complete': 'connecting'})
            self.assertIn('Stopping VPN', window.summary.text())
            self.assertFalse(window.kill_button.isEnabled())
            window.refresh_status()
            client.send.assert_not_called()
            event = Mock()
            window.closeEvent(event)
            event.ignore.assert_called_once()
            window.emergency_finished(False, 'Authorization denied; VPN may still be running.')
            self.assertTrue(window.kill_button.isEnabled())
            self.assertIn('Authorization denied', window.summary.text())
            self.assertTrue(window.isVisible())
            window.refresh_status()
            self.assertEqual(client.send.call_args.args[0], 'status')
            window.close()
            app.processEvents()

    def test_emergency_quits_only_after_confirmed_recovery(self):
        from unittest.mock import Mock, patch

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            window = Window(store=ProfileStore(Path(d) / 'profiles.json'), client=Mock())
            with patch.object(window.emergency, 'start'), patch('velum.gui.window.QApplication.quit') as quit_app:
                window.kill_vpn()
                quit_app.assert_not_called()
                window.emergency_finished(True, '')
                quit_app.assert_called_once()
            app.processEvents()

    def test_buttons_wait_for_completion_and_close_does_not_disconnect(self):
        from unittest.mock import Mock

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            store.save(BASE)
            client = Mock()
            window = Window(store=store, client=client)
            self.assertFalse(window.control_buttons['Connect'].isEnabled())
            window.refresh_status()
            window.update_status({'state': 'CONNECTED', 'request_complete': window.pending_request})
            self.assertFalse(window.control_buttons['Connect'].isEnabled())
            self.assertTrue(window.control_buttons['Disconnect'].isEnabled())
            window.control_buttons['Reconnect'].click()
            self.assertFalse(window.control_buttons['Run Full Test'].isEnabled())
            request_id = window.pending_request
            count = client.send.call_count
            window.reconnect()
            window.connect_vpn()
            window.disconnect_vpn()
            self.assertEqual(client.send.call_count, count)
            # Intermediate DISCONNECTED belongs to reconnect, not its completion.
            window.update_status({'state': 'DISCONNECTED'})
            self.assertFalse(window.control_buttons['Connect'].isEnabled())
            window.update_status({'state': 'CONNECTED', 'request_complete': request_id})
            self.assertTrue(window.control_buttons['Reconnect'].isEnabled())
            window.control_buttons['Disconnect'].click()
            self.assertEqual(client.send.call_args.args[0], 'disconnect')
            window.update_status({'state': 'DISCONNECTED', 'request_complete': window.pending_request})
            self.assertTrue(window.control_buttons['Connect'].isEnabled())
            count = client.send.call_count
            window.close()
            self.assertEqual(client.send.call_count, count)
            client.close.assert_called_once()
            app.processEvents()

    def test_reopen_restores_active_profile_and_connection_settings(self):
        from hashlib import sha256
        from unittest.mock import Mock

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            store.save(BASE)
            active = store.save(BASE + '?security=tls')
            window = Window(store=store, client=Mock())
            window.refresh_status()
            window.update_status({'state': 'CONNECTED', 'request_complete': window.pending_request,
                                  'profile_key': sha256(active['uri'].encode()).hexdigest(),
                                  'settings': {'expect_change': False, 'kill_switch': 'VPN + hotspot',
                                               'hotspot': 'wlan1'}})
            self.assertEqual(window.selected()['id'], active['id'])
            self.assertFalse(window.expect_change.isChecked())
            self.assertEqual(window.kill.currentText(), 'VPN + hotspot')
            self.assertTrue(window.share.isChecked())
            self.assertEqual(window.hotspot_interface.text(), 'wlan1')
            window.error('Lost helper connection')
            self.assertFalse(window.control_buttons['Connect'].isEnabled())
            window.diagnose()
            self.assertEqual(window.client.send.call_args.args[0], 'status')
            window.close()
            app.processEvents()

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
            reopened.update_status({'state': 'DISCONNECTED'})
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
