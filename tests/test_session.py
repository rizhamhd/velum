import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_vless import BASE

from velum.core.state import State
from velum.security.authorization import authorize
from velum.services.session import Session


class SessionTests(unittest.TestCase):
    def test_unknown_settings(self):
        with tempfile.TemporaryDirectory() as d:
            session = Session(Path(d), runner=Mock())
            for settings in ({'ipv6': 'tunnel'}, {'command': 'reboot'}, {'kill_switch': 'bad'}):
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
