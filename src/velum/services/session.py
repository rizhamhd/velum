import shutil
import socket
import time
from pathlib import Path

from velum.config.vless import parse_vless
from velum.core.state import State, StateMachine
from velum.diagnostics.verification import IPVerifier, Verification
from velum.network.dns import ResolvedDNS
from velum.network.firewall import Firewall
from velum.network.hotspot import Hotspot
from velum.network.system import NetworkError, Runner, detect_upstream
from velum.network.transaction import Transaction
from velum.network.tunnel import TUN, Tunnel
from velum.vpn.engine import Xray


class Session:
    def __init__(self, directory: Path, notify=lambda data: None, runner=None):
        self.directory = directory
        self.runner = runner or Runner()
        self.notify = notify
        self.tx = Transaction(self.runner, directory / 'network.json')
        self.guard_tx = Transaction(self.runner, directory / 'firewall.json')
        self.engine = Xray(directory)
        self.tunnel = Tunnel(self.runner, self.tx)
        self.dns = ResolvedDNS(self.runner, self.tx)
        self.firewall = Firewall(self.runner, self.guard_tx)
        self.hotspot = Hotspot(self.runner, self.tx)
        self.verification = Verification(self.runner, self.engine, self.tunnel, self.dns, self.firewall)
        self.machine = StateMachine(lambda _: self.emit())
        self.upstream = None
        self.original_ip = ''
        self.latency_ms = None
        self.settings = {}
        self.profile = None
        self.server = ''
        self.last_verify = 0
        self.last_tick = time.time()
        self.retry_at = 0
        self.retries = 0
        self.owner = None
        if self.tx.undo or self.guard_tx.undo:
            self.machine.state = State.ERROR
            self.machine.error = ('A previous helper session ended unexpectedly. Existing protection is retained. '
                                  'Disconnect to recover its owned resources before connecting.')

    def status(self):
        return {'state': str(self.machine.state), 'error': self.machine.error,
                'upstream': f'{self.upstream.kind} ({self.upstream.interface})' if self.upstream else '—',
                'original_ip': self.original_ip, 'vpn_ip': self.verification.vpn_ip,
                'tunnel': TUN if self.tunnel.status() else '—', 'latency_ms': self.latency_ms,
                'hotspot': 'Enabled; phone egress needs verification' if self.hotspot.interface and self.machine.state == State.CONNECTED else 'NOT ENABLED',
                'checks': self.verification.report()}

    def emit(self):
        self.notify(self.status())

    def validate_settings(self, settings):
        if not isinstance(settings, dict) or set(settings) - {'kill_switch', 'ipv6', 'expect_change', 'hotspot'}:
            raise ValueError('Unknown or invalid connection settings')
        if settings.get('ipv6', 'block') != 'block':
            raise ValueError('Native IPv6 tunneling is not supported; select temporary IPv6 blocking')
        if settings.get('kill_switch', 'VPN only') not in ('OFF', 'VPN only', 'VPN + hotspot'):
            raise ValueError('Invalid kill switch mode')
        if not isinstance(settings.get('expect_change', True), bool):
            raise ValueError('Invalid IP-change setting')
        if not isinstance(settings.get('hotspot', ''), str):
            raise ValueError('Invalid hotspot interface')

    def connect(self, uri, settings):
        if self.machine.state != State.DISCONNECTED:
            raise RuntimeError('Disconnect or recover the previous session first')
        self.validate_settings(settings)
        self.profile = parse_vless(uri)
        self.settings = settings
        self.retries = 0
        actions = {
            State.VALIDATING: self.validate,
            State.PREPARING_NETWORK: self.prepare,
            State.STARTING_CORE: self.start,
            State.WAITING_FOR_TUN: self.tunnel.wait,
            State.CONFIGURING_ROUTES: self.routes,
            State.CONFIGURING_DNS: self.dns.configure,
            State.VERIFYING: self.verify,
        }
        self.machine.connect(actions, self.cleanup)
        self.emit()

    def validate(self):
        for binary in ('xray', 'tun2socks', 'ip', 'nft', 'resolvectl', 'curl', 'sysctl'):
            if not shutil.which(binary, path='/usr/bin:/usr/sbin'):
                raise NetworkError(f'Required program is missing: {binary}. See installation instructions.')
        self.engine.validate_config(self.profile)
        self.upstream = detect_upstream(self.runner)
        self.tunnel.preflight()
        self.firewall.preflight()
        self.dns.preflight()
        if self.settings.get('hotspot'):
            self.hotspot.preflight(self.settings['hotspot'], self.upstream)
        records = socket.getaddrinfo(self.profile.server, self.profile.port, socket.AF_INET, socket.SOCK_STREAM)
        self.server = records[0][4][0]
        start = time.monotonic()
        with socket.create_connection((self.server, self.profile.port), timeout=5):
            self.latency_ms = round((time.monotonic() - start) * 1000)
        self.engine.validate_config(self.profile, self.server)
        self.original_ip = IPVerifier(self.runner).observe()

    def prepare(self):
        self.firewall.configure(self.server, self.profile.port,
                                self.settings.get('kill_switch', 'VPN only'),
                                self.settings.get('hotspot', ''))
        self.tunnel.prepare(self.upstream, self.server)

    def start(self):
        self.engine.start()
        self.tunnel.start()

    def routes(self):
        if self.hotspot.interface:
            self.hotspot.configure()
        self.tunnel.configure_routes()

    def verify(self):
        self.last_verify = time.time()
        result = self.verification.run(self.original_ip, self.settings.get('expect_change', True),
                                       bool(self.hotspot.interface))
        self.emit()
        return result

    def cleanup_network(self):
        self.tunnel.stop()
        self.engine.stop()
        self.tx.rollback()

    def cleanup(self):
        self.cleanup_network()
        # Leave the guard in place if network rollback could not complete.
        self.guard_tx.rollback()
        self.hotspot.interface = ''
        self.verification.vpn_ip = ''
        self.profile = None

    def disconnect(self):
        self.machine.disconnect(self.cleanup)
        self.machine.error = ''
        self.emit()

    def recover_connection(self):
        """Retain firewall while recreating routes against the new physical upstream."""
        if not self.profile:
            return
        self.machine.set(State.RECONNECTING)
        try:
            upstream = detect_upstream(self.runner)
            self.cleanup_network()
            self.tunnel.preflight()
            self.upstream = upstream
            if self.hotspot.interface:
                self.hotspot.preflight(self.hotspot.interface, upstream)
            self.engine.validate_config(self.profile, self.server)
            self.tunnel.prepare(upstream, self.server)
            self.start()
            self.tunnel.wait()
            self.routes()
            self.dns.configure()
            self.machine.set(State.VERIFYING)
            if not self.verify():
                raise NetworkError('Tunnel recovery failed routing or egress verification')
            self.machine.error = ''
            self.machine.set(State.CONNECTED)
            self.retries = 0
        except Exception:
            self.retries += 1
            self.retry_at = time.time() + min(60, 5 * 2 ** self.retries)
            self.machine.lost('VPN tunnel lost; protection retained. Automatic reconnect will retry.')

    def monitor(self):
        now = time.time()
        resumed = now - self.last_tick > 15
        self.last_tick = now
        if self.machine.state == State.ERROR and self.profile:
            if now >= self.retry_at:
                self.recover_connection()
            return
        if self.machine.state != State.CONNECTED:
            return
        try:
            if (not self.engine.status() or not self.tunnel.status()
                    or detect_upstream(self.runner) != self.upstream):
                raise NetworkError('VPN process or upstream changed')
            if resumed or now - self.last_verify > 60:
                self.machine.set(State.VERIFYING)
                if not self.verify():
                    raise NetworkError('Periodic routing verification failed')
                self.machine.set(State.CONNECTED)
        except Exception:
            self.machine.lost('VPN tunnel lost; kill-switch rules remain active when enabled.')
            self.retry_at = now + 2
