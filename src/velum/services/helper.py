"""Root service. The root-owned systemd socket authenticates peers through Polkit."""
import json
import os
import select
import signal
import socket
import sys
import time
from pathlib import Path

from velum.security.authorization import authorize
from velum.security.redact import redact
from velum.services.session import Session

RUNTIME = Path('/run/velum')


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
    listener.settimeout(2)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            continue
        authorized = False
        authentication_deadline = time.monotonic() + 10
        buffer = b''
        connection.settimeout(10)

        def send(data, peer=connection):
            peer.sendall((json.dumps(data) + '\n').encode())

        session.notify = send
        try:
            while not stopping:
                if not authorized and time.monotonic() > authentication_deadline:
                    break
                ready, _, _ = select.select([connection], [], [], 2)
                if not ready:
                    if not authorized:
                        break
                    session.monitor()
                    continue
                data = connection.recv(65536)
                if not data:
                    break
                buffer += data
                if len(buffer) > 65536:
                    raise ValueError('Request exceeds 64 KiB limit')
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError('Expected a JSON object')
                    if not authorized:
                        authorize(connection)
                        authorized = True
                    operation = request.get('operation')
                    try:
                        if operation in ('connect', 'reconnect'):
                            if operation == 'reconnect':
                                session.disconnect()
                            session.connect(request['uri'], request.get('settings', {}))
                        elif operation == 'disconnect':
                            session.disconnect()
                        elif operation == 'diagnostics':
                            if session.machine.state == 'CONNECTED':
                                if not session.verify():
                                    session.machine.lost('Connection diagnostics failed; protection is not verified')
                            session.emit()
                        elif operation == 'status':
                            session.emit()
                        else:
                            raise ValueError('Unsupported helper operation')
                    except Exception as exc:
                        send({**session.status(), 'error': redact(str(exc))})
        except (OSError, ValueError, PermissionError) as exc:
            try:
                send({'state': 'ERROR', 'error': redact(str(exc))})
            except OSError:
                pass
        finally:
            session.notify = lambda _: None
            connection.close()
            if authorized:
                try:
                    session.disconnect()
                except Exception:
                    # Keep the journal and firewall for the next authorized recovery.
                    print('Velum cleanup incomplete; recovery journal retained', file=sys.stderr)
    # Deliberate service stop is a disconnect. Fatal exits retain journals/rules.
    session.disconnect()


if __name__ == '__main__':
    main()
