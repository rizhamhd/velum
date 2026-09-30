import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_vless import BASE

from velum.config.vless import parse_vless
from velum.core.state import State
from velum.network.system import Upstream
from velum.security.authorization import authorize
from velum.services.session import Session


class SessionTests(unittest.TestCase):
    def test_certificate_name_does_not_hide_failed_connection(self):
        for custom_name in ('', '&verifyPeerCertByName=cert.example.invalid'):
            for connected in (False, True):
                with self.subTest(custom_name=custom_name, connected=connected), tempfile.TemporaryDirectory() as d:
                    session = Session(Path(d), runner=Mock())
                    session.profile = parse_vless(BASE + '?security=tls' + custom_name)
                    session.verification.run = Mock(return_value=connected)
                    session.emit = Mock()
                    self.assertIs(session.verify(), connected)
                    check = session.verification.results[-1]
                    self.assertEqual(check.name, 'TLS')
                    self.assertEqual(check.status, 'PASS' if connected else 'FAIL')
                    if custom_name:
                        self.assertIn('original SNI preserved', check.detail)

    @patch('velum.services.session.shutil.which', return_value='/usr/bin/tool')
    @patch('velum.services.session.socket.create_connection')
    @patch('velum.services.session.socket.getaddrinfo',
           return_value=[(None, None, None, None, ('192.0.2.10', 443))])
    @patch('velum.services.session.detect_upstream')
    @patch('velum.services.session.IPVerifier.observe', return_value='8.8.8.8')
    def test_pre_vpn_ip_requests_only_when_comparison_enabled(
            self, observe, upstream, resolve, connection, which):
        from unittest.mock import MagicMock

        connection.return_value = MagicMock()
        upstream.return_value = Upstream('eth0', '192.0.2.1', 'Ethernet')
        for settings in ({}, {'expect_change': True}, {'expect_change': False}):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as d:
                observe.reset_mock()
                observe.side_effect = None
                session = self.connected_session(d)
                session.profile = parse_vless(BASE)
                session.settings = settings
                session.original_ip = '9.9.9.9'
                session.validate()
                if settings.get('expect_change', True):
                    observe.assert_called_once_with()
                    self.assertEqual(session.original_ip, '8.8.8.8')
                    observe.side_effect = RuntimeError('Could not confirm public IPv4')
                    with self.assertRaisesRegex(RuntimeError, 'Pre-VPN public-IP check failed'):
                        session.validate()
                    self.assertEqual(session.original_ip, '')
                else:
                    observe.assert_not_called()
                    self.assertEqual(session.original_ip, '')
                    self.assertTrue(any(c['name'] == 'Pre-VPN public IP'
                                        and c['status'] == 'NOT ENABLED'
                                        for c in session.preflight_checks))

    def connected_session(self, directory):
        session = Session(Path(directory), runner=Mock())
        session.machine.notify = Mock()
        session.machine.state = State.CONNECTED
        session.profile = Mock()
        session.upstream = Upstream('eth0', '192.0.2.1', 'Ethernet')
        session.engine = Mock()
        session.tunnel = Mock()
        session.dns = Mock()
        session.firewall = Mock()
        session.runner.json.return_value = [{'dev': 'vpn0'}]
        return session

    @patch('velum.services.session.detect_upstream')
    def test_engine_failure_retains_guard_and_schedules_recovery(self, upstream):
        with tempfile.TemporaryDirectory() as d:
            session = self.connected_session(d)
            session.engine.status.return_value = False
            session.guard_tx.rollback = Mock()
            session.cleanup_network = Mock()
            with patch('velum.services.session.time.time', return_value=100):
                session.monitor()
            self.assertEqual(session.machine.state, State.ERROR)
            self.assertEqual(session.retry_at, 102)
            session.guard_tx.rollback.assert_not_called()
            session.cleanup_network.assert_not_called()
            session.engine.stop.assert_not_called()

    @patch('velum.services.session.detect_upstream')
    def test_periodic_verification_failure_retains_protection(self, upstream):
        with tempfile.TemporaryDirectory() as d:
            session = self.connected_session(d)
            upstream.return_value = session.upstream
            session.last_tick = 99
            session.last_verify = 1
            session.verify = Mock(return_value=False)
            session.guard_tx.rollback = Mock()
            with patch('velum.services.session.time.time', return_value=100):
                session.monitor()
            session.verify.assert_called_once()
            self.assertEqual(session.machine.state, State.ERROR)
            session.guard_tx.rollback.assert_not_called()

    @patch('velum.services.session.detect_upstream')
    def test_recovery_uses_new_upstream_and_verifies_before_connected(self, upstream):
        with tempfile.TemporaryDirectory() as d:
            session = self.connected_session(d)
            new_upstream = Upstream('wlan0', '192.0.2.254', 'Wi-Fi')
            upstream.return_value = new_upstream
            session.machine.state = State.ERROR
            session.server = '198.51.100.8'
            session.cleanup_network = Mock()
            session.guard_tx.rollback = Mock()
            session.hotspot.interface = ''
            states = []
            session.machine.notify = states.append
            session.verify = Mock(return_value=True)
            session.recover_connection()
            self.assertEqual(session.upstream, new_upstream)
            session.tunnel.prepare.assert_called_once_with(new_upstream, session.server)
            session.verify.assert_called_once()
            self.assertEqual(states, [State.RECONNECTING, State.VERIFYING, State.CONNECTED])
            session.guard_tx.rollback.assert_not_called()

    @patch('velum.services.session.detect_upstream')
    def test_failed_recovery_waits_for_backoff_and_keeps_guard(self, upstream):
        with tempfile.TemporaryDirectory() as d:
            session = self.connected_session(d)
            upstream.side_effect = RuntimeError('Upstream temporarily unavailable')
            session.machine.state = State.ERROR
            session.retry_at = 0
            session.guard_tx.rollback = Mock()
            with patch('velum.services.session.time.time', return_value=100):
                session.monitor()
                self.assertEqual(session.retry_at, 110)
                session.monitor()
            upstream.assert_called_once()
            self.assertEqual(session.machine.state, State.ERROR)
            self.assertIsNotNone(session.profile)
            session.guard_tx.rollback.assert_not_called()

    def test_unknown_settings(self):
        with tempfile.TemporaryDirectory() as d:
            session = Session(Path(d), runner=Mock())
            for settings in ({'ipv6': 'tunnel'}, {'command': 'reboot'}, {'kill_switch': 'bad'},
                             {'expect_change': 'false'}):
                with self.assertRaises(ValueError):
                    session.connect(BASE, settings)
            self.assertEqual(session.machine.state, State.DISCONNECTED)

    def test_active_session_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            session = Session(Path(d), runner=Mock())
            session.machine.state = State.CONNECTED
            with self.assertRaises(RuntimeError):
                session.connect(BASE, {})
            self.assertIsNone(session.profile)

    def test_firewall_preserved_on_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as d:
            session = Session(Path(d), runner=Mock())
            session.cleanup_network = Mock(side_effect=RuntimeError())
            session.guard_tx.rollback = Mock()
            with self.assertRaises(RuntimeError):
                session.cleanup()
            session.guard_tx.rollback.assert_not_called()

    @patch('velum.security.authorization.peer_identity', return_value=(123, 1000, '456'))
    @patch('velum.security.authorization.subprocess.run')
    def test_polkit_includes_process_start_and_uid(self, run, identity):
        run.return_value.returncode = 0
        self.assertEqual(authorize(Mock()), 1000)
        self.assertIn('123,456,1000', run.call_args.args[0])
        run.return_value.returncode = 1
        with self.assertRaises(PermissionError):
            authorize(Mock())

    def test_ipv6_endpoint_rejected_before_mutations(self):
        with tempfile.TemporaryDirectory() as d:
            runner = Mock()
            session = Session(Path(d), runner=runner)
            with self.assertRaisesRegex(ValueError, 'IPv6-only'):
                session.connect(BASE.replace('example.invalid', '[2001:db8::1]'), {})
            runner.run.assert_not_called()
