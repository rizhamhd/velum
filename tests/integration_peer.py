"""Private lab peer, launched only by the explicit namespace integration suite."""
import http.server
import json
import signal
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

from velum.network.system import Runner


class HTTP(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.client_address[0].encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class UDP(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        sock.sendto(self.client_address[0].encode() + b':' + data, self.client_address)


class HTTP6(http.server.HTTPServer):
    address_family = socket.AF_INET6


def main():
    directory = Path(sys.argv[1])
    print('NAMESPACE_READY', flush=True)
    if sys.stdin.readline().strip() != 'CONFIGURE':
        return
    runner = Runner()
    for command in [
        ('link', 'set', 'lo', 'up'), ('addr', 'add', '192.0.2.1/24', 'dev', 'peer0'),
        ('addr', 'add', '192.0.2.20/32', 'dev', 'peer0'),
        ('addr', 'add', '2001:db8:1::1/64', 'dev', 'peer0', 'nodad'),
        ('addr', 'add', '198.51.100.42/32', 'dev', 'lo'), ('link', 'set', 'peer0', 'up'),
    ]:
        runner.run('/usr/bin/ip', *command)
    config = {'log': {'loglevel': 'none'}, 'inbounds': [{
        'listen': '192.0.2.20', 'port': 24443, 'protocol': 'vless',
        'settings': {'clients': [{'id': '00000000-0000-4000-8000-000000000001'}], 'decryption': 'none'}}],
        'outbounds': [{'protocol': 'freedom'}]}
    path = directory / 'lab-server.json'
    path.write_text(json.dumps(config))
    servers = [http.server.HTTPServer(('198.51.100.42', 18080), HTTP),
               socketserver.UDPServer(('198.51.100.42', 18081), UDP),
               HTTP6(('2001:db8:1::1', 18082), HTTP)]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    process = subprocess.Popen(['/usr/bin/xray', 'run', '-config', str(path)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(_signum, _frame):
        raise SystemExit()

    signal.signal(signal.SIGTERM, stop)
    try:
        print('SERVICES_READY', flush=True)
        sys.stdin.read()
    finally:
        process.terminate()
        process.wait(timeout=5)
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
