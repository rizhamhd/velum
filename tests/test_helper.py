import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_vless import BASE

from velum.core.state import State
from velum.services.helper import Controller
from velum.services.session import Session


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.session = Session(Path(self.directory.name), runner=Mock())
        self.session.tunnel.status = Mock(return_value=True)
        self.controller = Controller(self.session)

    def peer(self, uid=1000):
        peer = Mock()
        self.controller.add(peer)
        self.controller.peers[peer]['uid'] = uid
        return peer

    def response(self, peer):
        return json.loads(peer.sendall.call_args.args[0])

    def test_gui_eof_keeps_tunnel_and_monitor_running(self):
        self.session.machine.state = State.CONNECTED
        self.session.owner = 1000
        self.session.disconnect = Mock()
        self.session.monitor = Mock()
        peer = self.peer()
        peer.recv.return_value = b''
        self.controller.receive(peer)
        self.controller.tick()
        self.assertFalse(self.controller.peers)
        self.session.disconnect.assert_not_called()
        self.session.monitor.assert_called_once()
        self.assertEqual(self.session.machine.state, State.CONNECTED)

    def test_closed_gui_during_setup_does_not_fail_connection(self):
        peer = self.peer()
        peer.sendall.side_effect = BrokenPipeError()
        self.session.validate = Mock()
        self.session.prepare = Mock()
        self.session.start = Mock()
        self.session.tunnel.wait = Mock()
        self.session.routes = Mock()
        self.session.dns.configure = Mock()
        self.session.verify = Mock(return_value=True)
        self.session.cleanup = Mock()
        self.controller.request(peer, {'operation': 'connect', 'uri': BASE})
        self.assertEqual(self.session.machine.state, State.CONNECTED)
        self.session.cleanup.assert_not_called()
        self.assertFalse(self.controller.peers)

    @patch('velum.services.helper.authorize', return_value=1000)
    def test_reopen_authenticates_and_recovers_status_then_disconnects(self, authorize):
        self.session.owner = 1000
        self.session.machine.state = State.CONNECTED
        peer = self.peer(uid=None)
        self.controller.request(peer, {'operation': 'status', 'request_id': 'reopen'})
        authorize.assert_called_once_with(peer)
        self.assertEqual(self.response(peer)['state'], 'CONNECTED')
        self.assertEqual(self.response(peer)['request_complete'], 'reopen')
        self.session.cleanup = Mock()
        self.controller.request(peer, {'operation': 'disconnect', 'request_id': 'stop'})
        self.session.cleanup.assert_called_once()
        self.assertEqual(self.response(peer)['state'], 'DISCONNECTED')
        self.assertIsNone(self.session.owner)

    def test_other_user_cannot_inspect_or_disconnect_owned_session(self):
        self.session.owner = 1000
        self.session.disconnect = Mock()
        peer = self.peer(uid=1001)
        self.controller.broadcast({'state': 'CONNECTED'})
        peer.sendall.assert_not_called()
        for operation in ('status', 'disconnect', 'connect', 'reconnect'):
            with self.assertRaises(PermissionError):
                self.controller.request(peer, {'operation': operation})
        self.session.disconnect.assert_not_called()

    def test_invalid_reconnect_keeps_existing_connection(self):
        self.session.machine.state = State.CONNECTED
        self.session.disconnect = Mock()
        peer = self.peer()
        for uri, settings in [('bad', {}), (BASE, {'ipv6': 'tunnel'})]:
            self.controller.request(peer, {'operation': 'reconnect', 'uri': uri,
                                           'settings': settings, 'request_id': 'retry'})
            self.assertEqual(self.response(peer)['state'], 'CONNECTED')
            self.assertTrue(self.response(peer)['error'])
            self.assertEqual(self.response(peer)['request_complete'], 'retry')
        self.session.disconnect.assert_not_called()

    def test_multiple_windows_receive_status_and_completion_only_goes_to_requester(self):
        first, second = self.peer(), self.peer()
        self.session.cleanup = Mock()
        self.controller.request(first, {'operation': 'disconnect', 'request_id': 'stop'})
        self.assertEqual(self.response(first)['request_complete'], 'stop')
        self.assertEqual(self.response(second)['state'], 'DISCONNECTED')
        self.assertNotIn('request_complete', self.response(second))

    def test_idle_unauthorized_peer_does_not_block_monitor(self):
        peer = self.peer(uid=None)
        self.controller.peers[peer]['deadline'] = 0
        self.session.monitor = Mock()
        self.controller.tick()
        peer.close.assert_called_once()
        self.session.monitor.assert_called_once()

    @patch('velum.services.helper.authorize', return_value=1000)
    def test_real_socket_close_and_reopen_preserve_session(self, authorize):
        self.session.machine.state = State.CONNECTED
        self.session.owner = 1000
        self.session.monitor = Mock()
        server, gui = socket.socketpair()
        self.addCleanup(server.close)
        self.controller.add(server)
        gui.close()
        self.controller.receive(server)
        self.controller.tick()
        server, gui = socket.socketpair()
        self.addCleanup(server.close)
        self.addCleanup(gui.close)
        gui.settimeout(1)
        self.controller.add(server)
        gui.sendall(b'{"operation":"status","request_id":"open"}\n')
        self.controller.receive(server)
        result = json.loads(gui.recv(65536))
        self.assertEqual(result['state'], 'CONNECTED')
        self.assertEqual(result['request_complete'], 'open')
        authorize.assert_called_once_with(server)
