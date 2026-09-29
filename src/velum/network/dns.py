from pathlib import Path

from velum.network.system import NetworkError
from velum.network.tunnel import TUN


class ResolvedDNS:
    def __init__(self, runner, transaction, resolv_conf=Path('/etc/resolv.conf')):
        self.runner, self.tx = runner, transaction
        self.resolv_conf = resolv_conf

    def preflight(self):
        target = str(self.resolv_conf.resolve())
        text = self.resolv_conf.read_text()
        servers = [line.split()[1] for line in text.splitlines()
                   if line.strip().startswith('nameserver ') and len(line.split()) > 1]
        if target != '/run/systemd/resolve/stub-resolv.conf' or servers != ['127.0.0.53']:
            raise NetworkError('Unsupported DNS manager. Enable systemd-resolved and its stub '
                               'resolver (NetworkManager may delegate to resolved). No DNS files were changed.')
        self.runner.run('/usr/bin/resolvectl', 'status')

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
