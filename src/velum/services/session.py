import ipaddress
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
from velum.security.logging import event
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
        self.preflight_checks = []
        self.engine_version = ''
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
                'checks': self.preflight_checks + self.verification.report(),
                'engine_version': self.engine_version}

    def emit(self):
        print(event("ERROR" if self.machine.error else "INFO", self.machine.error or str(self.machine.state)), flush=True)
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
        profile = parse_vless(uri)
        try:
            address = ipaddress.ip_address(profile.server)
        except ValueError:
            address = None
        if address and address.version == 6:
            raise ValueError('IPv6-only provider endpoints are unsupported; choose an IPv4-capable endpoint')
        self.profile = profile
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
        self.preflight_checks = []
        self.original_ip = ''
        for binary in ('xray', 'tun2socks', 'ip', 'nft', 'resolvectl', 'curl', 'sysctl'):
            if not shutil.which(binary, path='/usr/bin:/usr/sbin'):
                raise NetworkError(f'Required program is missing: {binary}. See installation instructions.')
        self.engine.validate_config(self.profile)
        self.engine_version = self.engine.version()
        self.preflight_checks.append({'name': 'VLESS configuration', 'status': 'PASS',
                                      'detail': 'Strict parser and installed Xray validation passed'})
        self.upstream = detect_upstream(self.runner)
        self.tunnel.preflight()
        self.firewall.preflight()
        self.dns.preflight()
        if self.settings.get('hotspot'):
            self.hotspot.preflight(self.settings['hotspot'], self.upstream)
        try:
            records = socket.getaddrinfo(self.profile.server, self.profile.port, socket.AF_INET, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise NetworkError('Provider DNS resolution failed; this release needs an IPv4-capable endpoint') from exc
        self.server = records[0][4][0]
        self.preflight_checks.append({'name': 'Server DNS resolution', 'status': 'PASS',
                                      'detail': 'Provider endpoint resolved to IPv4'})
        start = time.monotonic()
        with socket.create_connection((self.server, self.profile.port), timeout=5):
            self.latency_ms = round((time.monotonic() - start) * 1000)
        self.preflight_checks.append({'name': 'Server reachability', 'status': 'PASS',
                                      'detail': f'TCP connection established in {self.latency_ms} ms'})
        self.preflight_checks.append({'name': 'Default route', 'status': 'PASS',
                                      'detail': 'Physical upstream preserved: ' + self.upstream.interface})
        self.engine.validate_config(self.profile, self.server)
        if self.settings.get('expect_change', True):
            try:
                self.original_ip = IPVerifier(self.runner).observe()
            except RuntimeError as exc:
                raise NetworkError('Pre-VPN public-IP check failed before the tunnel started. '
                                   'For an app-specific data package, turn off Settings → '
                                   'Require public IP to change, then connect again. '
                                   'Tunnel connectivity checks will still run.') from exc
            self.preflight_checks.append({'name': 'Pre-VPN public IP', 'status': 'PASS',
                                          'detail': 'Public IP checked over the physical connection'})
        else:
            self.preflight_checks.append({'name': 'Pre-VPN public IP', 'status': 'NOT ENABLED',
                                          'detail': 'Skipped; public IP will be checked only through the tunnel'})

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
                                       self.hotspot if self.hotspot.interface else None)
        if self.profile and self.profile.security == 'tls':
            from velum.diagnostics.verification import Check
            detail = ('Certificate verification uses the configured certificate name; original SNI preserved'
                      if self.profile.certificate_name else
                      'Certificate verification is enforced by Xray; successful tunnel egress required')
            self.verification.results.append(Check('TLS', 'PASS' if result else 'FAIL', detail))
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
            self.retries = min(self.retries + 1, 6)
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
            if not self.firewall.verify() or not self.dns.verify():
                raise NetworkError('DNS or firewall protection changed')
            if self.runner.json('/usr/bin/ip', '-j', '-4', 'route', 'get', '1.1.1.1')[0].get('dev') != TUN:
                raise NetworkError('System routing no longer uses the tunnel')
            if resumed or now - self.last_verify > 60:
                self.machine.set(State.VERIFYING)
                if not self.verify():
                    raise NetworkError('Periodic routing verification failed')
                self.machine.set(State.CONNECTED)
        except Exception:
            self.machine.lost('VPN tunnel lost; kill-switch rules remain active when enabled.')
            self.retry_at = now + 2
