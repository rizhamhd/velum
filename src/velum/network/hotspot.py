import ipaddress

from velum.network.system import NetworkError, hotspot_interfaces, interface_name
from velum.network.tunnel import TABLE, TUN


class Hotspot:
    def __init__(self, runner, transaction):
        self.runner, self.tx = runner, transaction
        self.interface = ''
        self.subnet = ''

    def preflight(self, interface, upstream):
        interface = interface_name(interface)
        if interface in (upstream.interface, TUN, 'lo'):
            raise NetworkError('The hotspot must be separate from the active upstream interface')
        if interface not in hotspot_interfaces(self.runner):
            raise NetworkError('Choose an active NetworkManager shared/hotspot interface')
        addresses = self.runner.json('/usr/bin/ip', '-j', '-4', 'addr', 'show', 'dev', interface)
        infos = [a for link in addresses for a in link.get('addr_info', []) if a['scope'] == 'global']
        if len(infos) != 1:
            raise NetworkError('Hotspot requires exactly one IPv4 subnet')
        info = infos[0]
        network = ipaddress.IPv4Network(f"{info['local']}/{info['prefixlen']}", strict=False)
        if not network.is_private or network.overlaps(ipaddress.IPv4Network('198.18.0.0/30')):
            raise NetworkError('Unsupported hotspot subnet')
        self.interface, self.subnet = interface, str(network)

    def configure(self):
        self.tx.apply(['/usr/bin/ip', '-4', 'route', 'add', self.subnet, 'dev', self.interface,
                       'table', TABLE, 'proto', '186'],
                      ['/usr/bin/ip', '-4', 'route', 'del', self.subnet, 'dev', self.interface,
                       'table', TABLE, 'proto', '186'])
        # Per-interface forwarding avoids ip_forward's global reset of host sysctls.
        for interface in (self.interface, TUN):
            key = f'net.ipv4.conf.{interface}.forwarding'
            old = self.runner.run('/usr/bin/sysctl', '-n', key).strip()
            if old not in ('0', '1'):
                raise NetworkError('Unexpected forwarding sysctl value')
            if old != '1':
                self.tx.apply(['/usr/bin/sysctl', '-w', key + '=1'],
                              ['/usr/bin/sysctl', '-w', key + '=' + old])

    def verify(self):
        routes = self.runner.json('/usr/bin/ip', '-j', '-4', 'route', 'show', 'table', TABLE)
        route_ok = any(r.get('dst') == self.subnet and r.get('dev') == self.interface for r in routes)
        forwarding = all(self.runner.run('/usr/bin/sysctl', '-n',
                         f'net.ipv4.conf.{interface}.forwarding').strip() == '1'
                         for interface in (self.interface, TUN))
        return route_ok and forwarding and self.interface in hotspot_interfaces(self.runner)
