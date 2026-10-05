#!/usr/bin/env python3
"""Explicit live acceptance using a private saved profile and the actual Qt client.

Run with PYTHONPATH=src. This contacts the provider and temporarily changes host
networking through the installed, Polkit-authorized helper. Never run as root.
The report contains check outcomes, not profile URLs, credentials or IP addresses.
"""
import argparse
import ipaddress
import json
import os
import secrets
import signal
import socket
import ssl
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from velum.config.links import parse_profile
from velum.config.profiles import ProfileStore
from velum.security.files import private_write
from velum.security.redact import redact


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True,
                          timeout=30, env={'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C'}).stdout


def snapshot():
    return {
        'rules': json.loads(command('/usr/bin/ip', '-j', '-4', 'rule', 'show')),
        'routes': json.loads(command('/usr/bin/ip', '-j', '-4', 'route', 'show', 'table', 'main')),
        'resolver': Path('/etc/resolv.conf').read_text(),
        'dns': command('/usr/bin/resolvectl', 'dns'),
        'domains': command('/usr/bin/resolvectl', 'domain'),
    }


def public_ip():
    values = []
    issues = []
    for url in ('https://api.ipify.org', 'https://checkip.amazonaws.com',
                'https://ipv4.icanhazip.com'):
        try:
            value = command('/usr/bin/curl', '-q', '--fail', '--silent', '--show-error',
                            '--noproxy', '*', '--proto', '=https', '-4', '--max-time', '10',
                            '--connect-timeout', '4', '--max-filesize', '128', url).strip()
            if ipaddress.IPv4Address(value).is_global:
                values.append(value)
                if values.count(value) >= 2:
                    return value
            else:
                issues.append('non-public response')
        except subprocess.CalledProcessError as exc:
            issues.append('curl exit ' + str(exc.returncode))
        except (subprocess.SubprocessError, ValueError):
            issues.append('invalid or timed-out response')
            continue
    if len(values) > 1 and len(set(values)) > 1:
        issues.append('valid providers disagree')
    raise RuntimeError('Independent HTTPS probes could not agree on public IPv4: '
                       + ', '.join(issues))


def udp_dns():
    identifier = secrets.randbits(16)
    question = b'\x07example\x03com\x00\x00\x01\x00\x01'
    query = struct.pack('!6H', identifier, 0x0100, 1, 0, 0, 0) + question
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
        stream.settimeout(8)
        stream.connect(('1.1.1.1', 53))
        stream.send(query)
        response = stream.recv(4096)
    rid, flags, questions, answers, _, _ = struct.unpack('!6H', response[:12])
    if (rid != identifier or not flags & 0x8000 or flags & 0x020F
            or questions != 1 or not answers or response[12:12 + len(question)] != question):
        raise RuntimeError('Ordinary UDP DNS probe returned an invalid answer')


def ipv6_reachable():
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as stream:
            stream.settimeout(3)
            stream.connect(('2606:4700:4700::1111', 443))
        return True
    except OSError:
        return False


def tls_probe(uri):
    profile = parse_profile(uri)
    if profile.security != 'tls':
        raise RuntimeError('Selected profile does not use TLS')
    if profile.certificate_name:
        raise RuntimeError('This standard TLS probe cannot separate SNI from the certificate name; '
                           'use the Xray connection diagnostics for this profile')
    address = socket.getaddrinfo(profile.server, profile.port, socket.AF_INET,
                                 socket.SOCK_STREAM)[0][4]
    context = ssl.create_default_context()
    if profile.alpn:
        context.set_alpn_protocols(list(profile.alpn))
    with socket.create_connection(address, timeout=8) as stream:
        with context.wrap_socket(stream, server_hostname=profile.sni or profile.server):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-id', required=True, help='ID in the private profile store')
    parser.add_argument('--allow-network-changes', action='store_true')
    parser.add_argument('--tls-only', action='store_true', help='Check certificate without connecting VPN')
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--hold-seconds', type=int, default=75)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--visible', action='store_true', help='Show the tested Qt window')
    parser.add_argument('--restricted-data', action='store_true',
                        help='Skip direct public-IP checks before and after VPN connection')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as your ordinary desktop user, never with sudo')
    if not 1 <= args.cycles <= 5 or not 0 <= args.hold_seconds <= 600:
        parser.error('Use 1–5 cycles and 0–600 hold seconds')
    if not args.tls_only and not args.allow_network_changes:
        parser.error('Live testing requires --allow-network-changes')
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'velum'
    store = ProfileStore(config / 'profiles.json')
    records = store.list()
    selected = next((item for item in records if item['id'] == args.profile_id), None)
    if selected is None:
        parser.error('No saved profile has that ID')
    if args.tls_only:
        tls_probe(selected['uri'])
        print('PASS: certificate is trusted and matches the configured TLS server name', flush=True)
        return

    if not args.visible:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication

    from velum.gui.window import Window

    app = QApplication.instance() or QApplication([])
    window = Window(store=store)
    if args.restricted_data:
        window.expect_change.setChecked(False)
    window.profiles.selectRow(next(i for i, item in enumerate(window.records)
                                   if item['id'] == args.profile_id))
    if args.visible:
        window.show()
    # Programmatic actions still work. Manual diagnostic clicks would reset the
    # helper's verification timer and invalidate the watchdog acceptance check.
    window.setEnabled(False)
    messages, failures, outcomes = [], [], []
    window.client.received.connect(messages.append)
    window.client.failure.connect(failures.append)
    last_state = None

    def record(name, detail=''):
        outcomes.append({'check': name, 'status': 'PASS', 'detail': detail})
        print('PASS: ' + name + (': ' + detail if detail else ''), flush=True)

    def pump(seconds=0.3):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(0.02)

    def wait(start, predicate, timeout=150, allow_errors=False):
        nonlocal last_state
        until = time.monotonic() + timeout
        cursor = start
        while time.monotonic() < until:
            pump(0.05)
            if failures:
                raise RuntimeError(failures[-1])
            for message in messages[cursor:]:
                cursor += 1
                state = message.get('state')
                if state != last_state:
                    print('STATE: ' + str(state), flush=True)
                    last_state = state
                if message.get('error') and not allow_errors:
                    failed = [c['name'] for c in message.get('checks', [])
                              if c['status'] == 'FAIL']
                    detail = '; failed checks: ' + ', '.join(failed) if failed else ''
                    raise RuntimeError(message['error'] + detail)
                if predicate(message):
                    return message
        raise TimeoutError('Timed out waiting for the installed helper')

    def operation(action, predicate, **kwargs):
        pump()
        start = len(messages)
        action()
        return wait(start, predicate, **kwargs)

    def connected(message):
        return message.get('state') == 'CONNECTED'

    def disconnected(message):
        return message.get('state') == 'DISCONNECTED'

    def verify_connected(message, baseline):
        checks = message.get('checks', [])
        if not checks or any(c['status'] not in ('PASS', 'NOT ENABLED') for c in checks):
            raise RuntimeError('Helper diagnostics contain a failed check')
        if 'CONNECTED' not in window.summary.text() or window.last_status != 'CONNECTED':
            raise RuntimeError('GUI did not display the verified connection')
        egress = public_ip()
        if egress != message.get('vpn_ip') or (baseline is not None and egress == baseline):
            raise RuntimeError('Ordinary non-root HTTPS traffic did not match the expected VPN egress')
        record('Independent non-root HTTPS egress matches helper'
               + (' and differs from baseline' if baseline is not None else ''))
        udp_dns()
        record('Ordinary UDP DNS query succeeds through protected routing')
        if ipv6_reachable():
            raise RuntimeError('IPv6 traffic escaped during the protected session')
        record('IPv6 outbound connection is blocked')
        record('GUI and helper checks agree', ', '.join(c['name'] for c in checks if c['status'] == 'PASS'))

    def wait_restored(baseline):
        # Resolved/NetworkManager consume link-removal events asynchronously.
        # Report the mismatching component instead of a generic cleanup failure.
        deadline = time.monotonic() + 10
        differences = []
        while time.monotonic() < deadline:
            current = snapshot()
            differences = [key for key in baseline if baseline[key] != current[key]]
            if not differences:
                return
            pump(0.25)
        raise RuntimeError('Network restoration differs from baseline: ' + ', '.join(differences))

    print('Preparing network snapshot', flush=True)
    baseline_network = snapshot()
    baseline_ip = None if args.restricted_data else public_ip()
    baseline_ipv6 = ipv6_reachable()
    owned = False
    error = None

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        print('Waiting for installed helper and desktop authorization', flush=True)
        initial = operation(lambda: window.client.send('status'), lambda m: 'state' in m)
        if not disconnected(initial):
            raise RuntimeError('Existing helper session needs manual inspection before live testing')
        owned = True
        for cycle in range(args.cycles):
            result = operation(window.connect_vpn if cycle == 0 else window.reconnect, connected)
            record(f'Connection cycle {cycle + 1} reached CONNECTED')
            verify_connected(result, baseline_ip)
            result = operation(window.diagnose, connected)
            verify_connected(result, baseline_ip)
            record(f'Explicit diagnostics passed for cycle {cycle + 1}')
            if cycle == 0 and args.hold_seconds:
                start = len(messages)
                deadline = time.monotonic() + args.hold_seconds
                while time.monotonic() < deadline:
                    pump(0.25)
                    if failures or any(m.get('error') for m in messages[start:]):
                        raise RuntimeError('Connection failed during the stability interval')
                if args.hold_seconds >= 70 and not any(m.get('state') == 'VERIFYING' for m in messages[start:]):
                    raise RuntimeError('Periodic verification did not run during the stability interval')
                result = operation(window.diagnose, connected)
                verify_connected(result, baseline_ip)
                record('Connection remained healthy during stability interval', f'{args.hold_seconds} seconds')
        operation(window.disconnect_vpn, disconnected, allow_errors=True)
        record('Explicit disconnect completed')
        wait_restored(baseline_network)
        if baseline_ip is not None and public_ip() != baseline_ip:
            raise RuntimeError('Original public IP was not restored')
        if baseline_ipv6 and not ipv6_reachable():
            raise RuntimeError('Previously available IPv6 did not return after disconnect')
        record('Original routes and DNS settings restored'
               + ('; public IPv4 restored' if baseline_ip is not None else ''))
        owned = False
    except (Exception, KeyboardInterrupt) as exc:
        error = 'Live test interrupted' if isinstance(exc, KeyboardInterrupt) else redact(str(exc))
        outcomes.append({'check': 'Live acceptance', 'status': 'FAIL', 'detail': error})
    finally:
        if owned:
            try:
                failures.clear()
                operation(window.disconnect_vpn, disconnected, allow_errors=True)
                record('Cleanup disconnect completed')
                wait_restored(baseline_network)
                if baseline_ip is not None and public_ip() != baseline_ip:
                    raise RuntimeError('Post-failure network restoration differs from baseline')
                record('Network restored after failed test')
            except Exception as exc:
                cleanup_error = 'Cleanup requires inspection: ' + redact(str(exc))
                outcomes.append({'check': 'Cleanup', 'status': 'FAIL', 'detail': cleanup_error})
                error = (error + '; ' if error else '') + cleanup_error
        window.client.socket.disconnectFromServer()
        window.close()
        if args.report:
            private_write(args.report, {'passed': error is None,
                                       'checked_at': datetime.now(UTC).isoformat(), 'cycles': args.cycles,
                                       'hold_seconds': args.hold_seconds,
                                       'baseline_public_ip_checked': baseline_ip is not None,
                                       'baseline_ipv6_reachable': baseline_ipv6,
                                       'checks': outcomes})
    if error:
        raise RuntimeError(error)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FAIL: ' + redact(str(exc)), file=sys.stderr, flush=True)
        sys.exit(1)
