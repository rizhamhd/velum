import ipaddress
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class NetworkError(RuntimeError):
    pass


def resolve_ipv4(host, port, timeout=8):
    """Bound libc/NSS resolution in a disposable process, including on a dead tunnel."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if address.version != 4:
            raise NetworkError('An IPv4-capable endpoint is required')
        return str(address)
    try:
        result = subprocess.run(
            ['/usr/bin/python', '-I', '-c',
             'import socket,sys; print(socket.getaddrinfo(sys.argv[1], int(sys.argv[2]), '
             'socket.AF_INET, socket.SOCK_STREAM)[0][4][0])', host, str(port)],
            capture_output=True, text=True, check=True, timeout=timeout,
            env={'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C'})
        return str(ipaddress.IPv4Address(result.stdout.strip()))
    except subprocess.TimeoutExpired as exc:
        raise NetworkError(f'DNS lookup timed out after {timeout} seconds; '
                           'the connection is not providing working DNS') from exc
    except (subprocess.SubprocessError, ValueError) as exc:
        raise NetworkError('DNS lookup failed; no IPv4 address was returned') from exc


class Runner:
    def run(self, *args, input=None, check=True):
        result = subprocess.run(list(args), input=input, text=True, capture_output=True,
                                timeout=20, env={'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C'})
        if check and result.returncode:
            # Never print command arguments (may include provider information).
            raise NetworkError(f'{Path(args[0]).name} operation failed: {result.stderr[:500]}')
        return result.stdout

    def json(self, *args):
        return json.loads(self.run(*args))


@dataclass(frozen=True)
class Upstream:
    interface: str
    gateway: str | None
    kind: str


def interface_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', name):
        raise NetworkError('Invalid network interface name')
    return name


def interface_kind(link, sysroot=Path('/sys/class/net')):
    name = link['ifname']
    kind = link.get('linkinfo', {}).get('info_kind', '')
    if name == 'lo' or link.get('link_type') == 'loopback':
        return 'Loopback'
    if kind in ('tun', 'wireguard', 'tap') or (sysroot / name / 'tun_flags').exists():
        return 'VPN/TUN'
    if (sysroot / name / 'wireless').exists():
        return 'Wi-Fi'
    if kind in ('bridge', 'veth', 'dummy'):
        return 'Virtual'
    return 'Ethernet' if link.get('link_type') == 'ether' else 'Unknown'


def parse_default(routes, links):
    candidates = sorted((r for r in routes if r.get('dst') == 'default'
                         and 'dev' in r and r.get('type', 'unicast') == 'unicast'),
                        key=lambda r: r.get('metric', 0))
    for route in candidates:
        link = next((p for p in links if p['ifname'] == route['dev']), {})
        if not link:
            continue
        if (link.get('operstate') in ('DOWN', 'LOWERLAYERDOWN', 'NOTPRESENT')
                or ('flags' in link and 'UP' not in link['flags'])
                or 'linkdown' in route.get('flags', [])):
            continue
        kind = interface_kind(link)
        if kind in ('VPN/TUN', 'Loopback'):
            continue
        return Upstream(interface_name(route['dev']), route.get('gateway'), kind)
    raise NetworkError('No supported physical IPv4 default route is available')


def detect_upstream(runner):
    upstream = parse_default(runner.json('/usr/bin/ip', '-j', '-4', 'route', 'show', 'table', 'main'),
                             runner.json('/usr/bin/ip', '-j', '-d', 'link', 'show'))
    return upstream


def hotspot_interfaces(runner):
    """Detect NM shared connections; never create/disconnect the user's Wi-Fi."""
    result = []
    connections = runner.run('/usr/bin/nmcli', '-t', '-f', 'UUID', 'connection', 'show', '--active', check=False)
    for uid in connections.splitlines():
        if not re.fullmatch(r'[0-9a-f-]{36}', uid):
            continue
        method = runner.run('/usr/bin/nmcli', '-g', 'ipv4.method', 'connection', 'show', uid, check=False).strip()
        if method == 'shared':
            devices = runner.run('/usr/bin/nmcli', '-g', 'GENERAL.DEVICES', 'connection', 'show', uid).strip()
            result.extend(interface_name(d) for d in devices.split(',') if d)
    return result
