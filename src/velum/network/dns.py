import socket
from pathlib import Path

from velum.network.system import NetworkError
from velum.network.tunnel import TUN


class ResolvedDNS:
    def __init__(self, runner, transaction, resolv_conf=Path('/etc/resolv.conf')):
        self.runner, self.tx = runner, transaction
        self.resolv_conf = resolv_conf

    def preflight(self):
        # NetworkManager may write a regular resolv.conf that points exclusively
        # to resolved. Its effective nameservers matter, not the symlink target.
        servers = []
        for line in self.resolv_conf.read_text().splitlines():
            fields = line.split('#', 1)[0].split(';', 1)[0].split()
            if fields and fields[0] == 'nameserver':
                if len(fields) != 2:
                    raise NetworkError('Invalid nameserver entry in /etc/resolv.conf; no DNS files were changed')
                servers.append(fields[1])
        if servers != ['127.0.0.53']:
            raise NetworkError('Unsupported DNS configuration. All system DNS must use the '
                               'systemd-resolved stub at 127.0.0.53. NetworkManager-managed files '
                               'and stub symlinks are supported. No DNS files were changed.')
        self.runner.run('/usr/bin/resolvectl', 'status')
        try:
            with socket.create_connection(('127.0.0.53', 53), timeout=2):
                pass
        except OSError as exc:
            raise NetworkError('systemd-resolved is available, but its DNS stub at 127.0.0.53:53 '
                               'is not reachable. Check DNSStubListener; no DNS files were changed.') from exc

    def configure(self):
        self.tx.apply(['/usr/bin/resolvectl', 'dns', TUN, '1.1.1.1', '9.9.9.9'],
                      ['/usr/bin/resolvectl', 'revert', TUN])
        self.runner.run('/usr/bin/resolvectl', 'domain', TUN, '~.')
        self.runner.run('/usr/bin/resolvectl', 'default-route', TUN, 'yes')
        self.runner.run('/usr/bin/resolvectl', 'flush-caches')

    def verify(self):
        self.preflight()
        dns = self.runner.run('/usr/bin/resolvectl', 'dns', TUN)
        domains = self.runner.run('/usr/bin/resolvectl', 'domain', TUN)
        return '1.1.1.1' in dns and '9.9.9.9' in dns and '~.' in domains
