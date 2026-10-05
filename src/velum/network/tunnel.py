import ipaddress
import subprocess
import time

from velum.network.system import NetworkError
from velum.vpn.configuration import MARK, SOCKS_PORT

TABLE = '28672'
RULE = '11000'
BYPASS = '10999'
ENDPOINT = '10998'
TUN = 'vpn0'


class Tunnel:
    def __init__(self, runner, transaction):
        self.runner = runner
        self.tx = transaction
        self.process = None

    def preflight(self):
        links = self.runner.json('/usr/bin/ip', '-j', 'link', 'show')
        if any(p['ifname'] == TUN for p in links):
            raise NetworkError('vpn0 already exists; refusing to change an unowned interface')
        rules = self.runner.json('/usr/bin/ip', '-j', '-4', 'rule', 'show')
        if any(str(p.get('priority')) in (RULE, BYPASS, ENDPOINT) for p in rules):
            raise NetworkError('Reserved routing priorities are already in use')
        # Refuse custom policy routing: VPN coexistence requires an explicit adapter.
        if any(p.get('priority') not in (0, 32766, 32767) for p in rules):
            raise NetworkError('Existing policy routing is unsupported; disconnect other VPNs first')
        routes = self.runner.run('/usr/bin/ip', '-4', 'route', 'show', 'table', TABLE, check=False)
        if routes.strip():
            raise NetworkError('Reserved VPN routing table is already in use')

    def prepare(self, upstream, server):
        server = str(ipaddress.IPv4Address(server))
        # A dedicated endpoint route is installed before traffic is redirected.
        existing = self.runner.json('/usr/bin/ip', '-j', '-4', 'route', 'show', 'exact', server + '/32')
        if existing:
            raise NetworkError('Provider already has a host route; refusing to replace it')
        route = ['/usr/bin/ip', '-4', 'route', 'add', server + '/32']
        if upstream.gateway:
            route += ['via', upstream.gateway]
        route += ['dev', upstream.interface, 'proto', '186']
        self.tx.apply(route, ['/usr/bin/ip', '-4', 'route', 'del', server + '/32',
                              'dev', upstream.interface, 'proto', '186'])
        self.tx.apply(['/usr/bin/ip', '-4', 'rule', 'add', 'priority', ENDPOINT,
                       'to', server + '/32', 'lookup', 'main'],
                      ['/usr/bin/ip', '-4', 'rule', 'del', 'priority', ENDPOINT,
                       'to', server + '/32', 'lookup', 'main'])
        self.tx.apply(['/usr/bin/ip', 'tuntap', 'add', 'dev', TUN, 'mode', 'tun'],
                      ['/usr/bin/ip', 'link', 'del', 'dev', TUN])
        self.runner.run('/usr/bin/ip', 'addr', 'add', '198.18.0.1/30', 'dev', TUN)
        self.runner.run('/usr/bin/ip', 'link', 'set', 'dev', TUN, 'mtu', '1500', 'up')

    def start(self):
        self.process = subprocess.Popen(['/usr/bin/tun2socks', '-device', 'tun://' + TUN,
                                         '-proxy', f'socks5://127.0.0.1:{SOCKS_PORT}',
                                         '-loglevel', 'silent'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait(self):
        for _ in range(30):
            if not self.status():
                raise NetworkError('TUN adapter stopped before the tunnel became usable')
            links = self.runner.json('/usr/bin/ip', '-j', 'link', 'show', 'dev', TUN)
            if links and 'UP' in links[0].get('flags', []):
                return
            time.sleep(0.1)
        raise NetworkError('VPN engine started, but vpn0 is not ready. The VPN is not active.')

    def configure_routes(self):
        operations = [
            (['route', 'add', 'default', 'dev', TUN, 'table', TABLE, 'proto', '186'],
             ['route', 'del', 'default', 'dev', TUN, 'table', TABLE, 'proto', '186']),
            (['rule', 'add', 'priority', BYPASS, 'fwmark', str(MARK), 'lookup', 'main'],
             ['rule', 'del', 'priority', BYPASS, 'fwmark', str(MARK), 'lookup', 'main']),
            (['rule', 'add', 'priority', RULE, 'lookup', TABLE],
             ['rule', 'del', 'priority', RULE, 'lookup', TABLE]),
        ]
        for forward, reverse in operations:
            self.tx.apply(['/usr/bin/ip', '-4', *forward], ['/usr/bin/ip', '-4', *reverse])

    def status(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
