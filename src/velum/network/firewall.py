import hashlib
import ipaddress
import json

from velum.network.system import NetworkError, interface_name
from velum.vpn.configuration import MARK

NFT_TABLE = 'velum_vpn'


def ruleset(server, port, kill_switch='VPN only', hotspot=''):
    server = str(ipaddress.IPv4Address(server))
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Invalid server port')
    if kill_switch not in ('OFF', 'VPN only', 'VPN + hotspot'):
        raise ValueError('Invalid kill switch mode')
    if hotspot:
        hotspot = interface_name(hotspot)
    lines = [f'table inet {NFT_TABLE} {{',
             'chain output { type filter hook output priority -50; policy accept;',
             'oifname "lo" accept',
             'meta nfproto ipv6 drop',
             'oifname "vpn0" accept',
             'meta l4proto { tcp, udp } th dport { 53, 853 } drop']
    if hotspot:
        # Permit DHCP replies from the laptop's existing NM hotspot service.
        lines += [f'oifname "{hotspot}" udp sport 67 udp dport 68 accept']
    if kill_switch != 'OFF':
        lines += [f'meta mark {MARK} ip daddr {server} tcp dport {port} accept',
                  'udp sport 68 udp dport 67 accept', 'drop']
    lines += ['}', 'chain forward { type filter hook forward priority -50; policy accept;',
              'meta nfproto ipv6 drop']
    if hotspot:
        lines += [f'iifname "{hotspot}" oifname "vpn0" accept',
                  f'iifname "vpn0" oifname "{hotspot}" ct state established,related accept',
                  # Sharing is always fail-closed even if the desktop kill switch is off.
                  f'iifname "{hotspot}" drop', f'oifname "{hotspot}" drop']
    lines += ['oifname "vpn0" drop', '}',
              'chain dns_output { type nat hook output priority -101; policy accept;',
              'ip daddr != 127.0.0.0/8 udp dport 53 dnat ip to 1.1.1.1',
              'ip daddr != 127.0.0.0/8 tcp dport 53 dnat ip to 1.1.1.1', '}']
    if hotspot:
        lines += ['chain dns_hotspot { type nat hook prerouting priority -101; policy accept;',
                  f'iifname "{hotspot}" udp dport 53 dnat ip to 1.1.1.1',
                  f'iifname "{hotspot}" tcp dport 53 dnat ip to 1.1.1.1', '}',
                  'chain nat_hotspot { type nat hook postrouting priority 99; policy accept;',
                  f'iifname "{hotspot}" oifname "vpn0" masquerade', '}']
    lines += ['}']
    return '\n'.join(lines) + '\n'


def fingerprint(data):
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if k not in ('handle', 'metainfo', 'packets', 'bytes')}
        if isinstance(value, list):
            return [clean(v) for v in value if not (isinstance(v, dict) and 'metainfo' in v)]
        return value
    return hashlib.sha256(json.dumps(clean(data), sort_keys=True).encode()).hexdigest()


class Firewall:
    def __init__(self, runner, transaction):
        self.runner, self.tx = runner, transaction
        self.expected = None

    def preflight(self):
        data = self.runner.json('/usr/bin/nft', '-j', 'list', 'tables')
        if any(v.get('table', {}).get('name') == NFT_TABLE for v in data['nftables']):
            raise NetworkError('Velum nftables table already exists; recover the stale session first')

    def configure(self, server, port, kill_switch='VPN only', hotspot=''):
        content = ruleset(server, port, kill_switch, hotspot)
        self.runner.run('/usr/bin/nft', '--check', '-f', '-', input=content)
        self.tx.apply(['/usr/bin/nft', '-f', '-'],
                      ['/usr/bin/nft', 'delete', 'table', 'inet', NFT_TABLE], input=content)
        self.expected = fingerprint(self.runner.json('/usr/bin/nft', '-j', 'list', 'table', 'inet', NFT_TABLE))

    def verify(self):
        return self.expected is not None and self.expected == fingerprint(
            self.runner.json('/usr/bin/nft', '-j', 'list', 'table', 'inet', NFT_TABLE))
