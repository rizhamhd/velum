"""Root service. The root-owned systemd socket authenticates peers through Polkit."""
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from velum.security.authorization import authorize
from velum.security.redact import redact
from velum.services.session import Session

RUNTIME = Path('/run/velum')


class Controller:
    """One serialized VPN session, independent of authenticated GUI lifetimes."""

    def __init__(self, session):
        self.session = session
        self.peers = {}
        session.notify = self.broadcast

    def add(self, peer):
        peer.settimeout(0.2)
        self.peers[peer] = {'uid': None, 'buffer': b'', 'deadline': time.monotonic() + 10}

    def drop(self, peer):
        self.peers.pop(peer, None)
        peer.close()

    def allowed(self, uid):
        return uid is not None and self.session.owner in (None, uid)

    def send(self, peer, data):
        try:
            peer.sendall((json.dumps(data) + '\n').encode())
        except OSError:
            # A closed/slow GUI must never interrupt network setup or cleanup.
            self.drop(peer)

    def broadcast(self, data):
        for peer, info in list(self.peers.items()):
            if self.allowed(info['uid']):
                self.send(peer, data)

    def request(self, peer, request):
        if not isinstance(request, dict):
            raise ValueError('Expected a JSON object')
        request_id = request.get('request_id')
        if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 64):
            raise ValueError('Invalid request ID')
        info = self.peers[peer]
        if info['uid'] is None:
            info['uid'] = authorize(peer)
        if not self.allowed(info['uid']):
            raise PermissionError('The VPN is controlled by another user')
        session = self.session
        error = ''
        try:
            operation = request.get('operation')
            if operation in ('connect', 'reconnect'):
                uri, settings = request.get('uri'), request.get('settings', {})
                # Validate replacements before disconnecting a working tunnel.
                session.validate_request(uri, settings)
                session.owner = info['uid']
                if operation == 'reconnect':
                    session.disconnect()
                session.connect(uri, settings)
            elif operation == 'disconnect':
                session.disconnect()
            elif operation == 'diagnostics':
                if session.machine.state == 'CONNECTED' and not session.verify():
                    session.machine.lost('Connection diagnostics failed; protection is not verified')
            elif operation != 'status':
                raise ValueError('Unsupported helper operation')
        except Exception as exc:
            error = redact(str(exc))
        finally:
            if session.machine.state == 'DISCONNECTED' and not session.machine.error:
                session.owner = None
        self.send(peer, {**session.status(), 'request_complete': request_id,
                         'error': error or session.machine.error})

    def receive(self, peer):
        try:
            info = self.peers[peer]
            data = peer.recv(65536)
            if not data:
                self.drop(peer)
                return
            info['buffer'] += data
            if len(info['buffer']) > 65536:
                raise ValueError('Request exceeds 64 KiB limit')
            while b'\n' in info['buffer'] and peer in self.peers:
                line, info['buffer'] = info['buffer'].split(b'\n', 1)
                self.request(peer, json.loads(line))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.send(peer, {'state': 'ERROR', 'error': redact(str(exc)), 'control_denied': True})
            self.drop(peer)

    def tick(self):
        for peer, info in list(self.peers.items()):
            if info['uid'] is None and time.monotonic() > info['deadline']:
                self.drop(peer)
        # Monitoring/recovery continues even with no GUI or with busy clients.
        self.session.monitor()


def main():
    if os.geteuid() != 0:
        raise SystemExit('The helper must run through the packaged systemd service')
    os.umask(0o077)
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    if RUNTIME.is_symlink() or RUNTIME.stat().st_uid != 0 or RUNTIME.stat().st_mode & 0o077:
        raise SystemExit('Unsafe runtime directory ownership or permissions')
    session = Session(RUNTIME)
    if sys.argv[1:] == ['--recover']:
        session.disconnect()
        return
    if sys.argv[1:]:
        raise SystemExit('Unknown helper arguments')
    if os.environ.get('LISTEN_PID') != str(os.getpid()) or os.environ.get('LISTEN_FDS') != '1':
        raise SystemExit('Start via velum.socket; direct service launch is unsupported')
    listener = socket.socket(fileno=3)
    listener.setblocking(False)
    controller = Controller(session)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        ready, _, _ = select.select([listener, *controller.peers], [], [], 2)
        for peer in ready:
            if peer is listener:
                connection, _ = listener.accept()
                if len(controller.peers) < 16:
                    controller.add(connection)
                else:
                    connection.close()
            elif peer in controller.peers:
                controller.receive(peer)
        controller.tick()
    # Deliberate service stop is a disconnect. Fatal exits retain journals/rules.
    session.disconnect()


if __name__ == '__main__':
    main()
