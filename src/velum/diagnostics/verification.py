import ipaddress
import socket
from dataclasses import asdict, dataclass

from velum.network.tunnel import TUN


@dataclass(frozen=True)
class IPProvider:
    name: str
    url: str


PROVIDERS = (IPProvider('ipify', 'https://api.ipify.org'),
             IPProvider('AWS', 'https://checkip.amazonaws.com'),
             IPProvider('icanhazip', 'https://ipv4.icanhazip.com'))


class IPVerifier:
    """Ordinary unmarked routing, no proxy environment and no interface binding."""
    def __init__(self, runner, providers=PROVIDERS):
        self.runner = runner
        self.providers = providers

    def observe(self):
        observations = []
        for provider in self.providers:
            try:
                value = self.runner.run('/usr/bin/curl', '-q', '--fail', '--silent',
                                        '--show-error', '--noproxy', '*', '--proto', '=https',
                                        '--connect-timeout', '4', '--max-time', '8', '-4',
                                        '--max-filesize', '128', provider.url).strip()
                address = ipaddress.IPv4Address(value)
                if not address.is_global:
                    raise ValueError('Non-public IP response')
                observations.append(str(address))
            except Exception:  # noqa: S112 - provider failures are aggregated below
                continue
            if len(observations) >= 2 and observations[-1] == observations[-2]:
                return observations[-1]
        raise RuntimeError('Could not confirm public IPv4 with two independent HTTPS services')


@dataclass
class Check:
    name: str
    status: str
    detail: str


class Verification:
    def __init__(self, runner, engine, tunnel, dns, firewall):
        self.runner, self.engine, self.tunnel = runner, engine, tunnel
        self.dns, self.firewall = dns, firewall
        self.results = []
        self.vpn_ip = ''

    def run(self, original_ip, expect_change=True, hotspot=False):
        self.results = []

        def check(name, test, detail):
            try:
                success = bool(test())
            except Exception:  # noqa: S112 - provider failures are aggregated below
                success = False
            self.results.append(Check(name, 'PASS' if success else 'FAIL', detail))
            return success

        check('Xray core', self.engine.status, 'Xray process is alive')
        check('TUN interface', lambda: self.tunnel.status() and bool(self.runner.json(
            '/usr/bin/ip', '-j', 'link', 'show', 'dev', TUN)), 'vpn0 and adapter exist')
        route_ok = check('VPN route', lambda: all(self.runner.json(
            '/usr/bin/ip', '-j', '-4', 'route', 'get', target)[0].get('dev') == TUN
            for target in ('1.1.1.1', '9.9.9.9', '8.8.8.8')),
            'Ordinary unmarked application route lookup must use vpn0')
        check('DNS protection', self.dns.verify, 'Resolved stub and tunnel DNS domain are active')
        check('IPv6 protection', self.firewall.verify, 'Owned firewall matches installed protection rules')
        check('DNS resolution', lambda: bool(socket.getaddrinfo('api.ipify.org', 443, socket.AF_INET)),
              'System resolver can resolve an external hostname')
        if all(c.status == 'PASS' for c in self.results):
            try:
                self.vpn_ip = IPVerifier(self.runner).observe()
                self.results.append(Check('Internet connectivity', 'PASS', 'Two HTTPS services agree'))
                changed = not expect_change or self.vpn_ip != original_ip
                self.results.append(Check('IPv4 egress', 'PASS' if changed else 'FAIL',
                                          'Egress address ' + self.vpn_ip))
            except Exception as exc:
                self.results.append(Check('Internet connectivity', 'FAIL', str(exc)))
        else:
            self.results.append(Check('IPv4 egress', 'FAIL', 'Preconditions failed; protection not verified'))
        if not route_ok:
            self.results.append(Check('Routing safety', 'FAIL',
                'VPN engine is running, but traffic is not being routed through the tunnel.'))
        self.results.append(Check('Hotspot forwarding', 'PASS' if hotspot and self.firewall.verify()
                                  else 'NOT ENABLED',
                                  'Laptop rules only; verify phone egress separately' if hotspot else 'Disabled'))
        return all(c.status in ('PASS', 'NOT ENABLED') for c in self.results)

    def report(self):
        return [asdict(c) for c in self.results]
