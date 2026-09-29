"""Exercise unmodified application sockets through real VLESS in isolated namespaces."""
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from velum.config.vless import parse_vless
from velum.network.firewall import Firewall
from velum.network.system import Runner, Upstream
from velum.network.transaction import Transaction
from velum.network.tunnel import Tunnel
from velum.vpn.engine import Xray


def http_source(address='198.51.100.42', port=18080):
    with socket.create_connection((address, port), timeout=3) as stream:
        stream.settimeout(3)
        stream.sendall(b'GET / HTTP/1.0\r\nHost: lab.invalid\r\n\r\n')
        data = b''
        while chunk := stream.recv(4096):
            data += chunk
        return data.split(b'\r\n\r\n', 1)[1].decode()


def assert_blocked(address, port):
    try:
        with socket.create_connection((address, port), timeout=2):
            raise AssertionError('Traffic bypassed the protection firewall')
    except (TimeoutError, ConnectionError, OSError):
        return


def main():
    runner = Runner()
    runner.run('/usr/bin/ip', 'link', 'del', 'uplink0')
    with tempfile.TemporaryDirectory(prefix='velum-dataplane-') as d:
        directory = Path(d)
        peer = subprocess.Popen(['unshare', '--net', 'python', 'tests/integration_peer.py', d],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        engine = Xray(directory)
        tx = Transaction(runner, directory / 'network.json')
        guard = Transaction(runner, directory / 'firewall.json')
        tunnel, firewall = Tunnel(runner, tx), Firewall(runner, guard)
        try:
            assert peer.stdout.readline().strip() == 'NAMESPACE_READY'
            runner.run('/usr/bin/ip', 'link', 'add', 'uplink0', 'type', 'veth', 'peer', 'name', 'peer0')
            runner.run('/usr/bin/ip', 'link', 'set', 'peer0', 'netns', str(peer.pid))
            runner.run('/usr/bin/ip', 'addr', 'add', '192.0.2.2/24', 'dev', 'uplink0')
            runner.run('/usr/bin/ip', 'addr', 'add', '2001:db8:1::2/64', 'dev', 'uplink0', 'nodad')
            runner.run('/usr/bin/ip', 'link', 'set', 'uplink0', 'up')
            runner.run('/usr/bin/ip', 'route', 'add', 'default', 'via', '192.0.2.1', 'dev', 'uplink0')
            peer.stdin.write('CONFIGURE\n')
            peer.stdin.flush()
            assert peer.stdout.readline().strip() == 'SERVICES_READY'
            assert http_source() == '192.0.2.2'
            assert http_source('2001:db8:1::1', 18082) == '2001:db8:1::2'
            profile = parse_vless('vless://00000000-0000-4000-8000-000000000001@192.0.2.20:24443')
            engine.validate_config(profile, '192.0.2.20')
            firewall.configure('192.0.2.20', 24443)
            tunnel.prepare(Upstream('uplink0', '192.0.2.1', 'Ethernet'), '192.0.2.20')
            engine.start()
            tunnel.start()
            tunnel.wait()
            tunnel.configure_routes()
            deadline = time.monotonic() + 10
            while True:
                try:
                    assert http_source() == '198.51.100.42'
                    break
                except (OSError, IndexError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)
            print('PASS: ordinary TCP socket egress changed through real Xray/VLESS', flush=True)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.settimeout(5)
                udp.sendto(b'tunnel-test', ('198.51.100.42', 18081))
                assert udp.recv(1024) == b'198.51.100.42:tunnel-test'
            print('PASS: ordinary UDP socket traverses real TUN/VLESS', flush=True)
            assert_blocked('2001:db8:1::1', 18082)
            print('PASS: previously reachable IPv6 is blocked during connection', flush=True)
            engine.stop()
            runner.run('/usr/bin/ip', '-4', 'rule', 'del', 'priority', '11000')
            assert_blocked('198.51.100.42', 18080)
            print('PASS: kill switch blocks fallback after engine death and route loss', flush=True)
        finally:
            tunnel.stop()
            engine.stop()
            tx.rollback()
            guard.rollback()
            peer.terminate()
            peer.wait(timeout=10)
        assert not any(link['ifname'] == 'uplink0' for link in runner.json('/usr/bin/ip', '-j', 'link'))
        print('PASS: dataplane namespace resources automatically removed', flush=True)
