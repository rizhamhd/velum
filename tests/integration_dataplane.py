"""Exercise unmodified application sockets through real VLESS in isolated namespaces."""
import base64
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from integration_peer import LAB_ID, LAB_PASSWORD

from velum.config.links import parse_profile
from velum.network.firewall import Firewall
from velum.network.system import Runner, Upstream
from velum.network.transaction import Transaction
from velum.network.tunnel import Tunnel
from velum.vpn.engine import SingBox, engine_for


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


def main(kind='vless'):
    runner = Runner()
    runner.run('/usr/bin/ip', 'link', 'del', 'uplink0', check=False)
    with tempfile.TemporaryDirectory(prefix='velum-dataplane-') as d:
        directory = Path(d)
        peer = subprocess.Popen(['unshare', '--net', 'python', 'tests/integration_peer.py', d, kind],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        uri = f'vless://{LAB_ID}@192.0.2.20:24443'
        if kind == 'vmess':
            uri = 'vmess://' + base64.b64encode(json.dumps({'add': '192.0.2.20', 'port': 24443,
                       'id': LAB_ID, 'net': 'tcp', 'scy': 'auto'}).encode()).decode()
        elif kind == 'shadowsocks':
            uri = f'ss://aes-128-gcm:{LAB_PASSWORD}@192.0.2.20:24443'
        elif kind == 'trojan':
            uri = f'trojan://{LAB_PASSWORD}@192.0.2.20:24443?allowInsecure=1&sni=lab.invalid'
        elif kind == 'vless-insecure':
            uri += '?type=tcp&host=lab.invalid&security=tls&allowInsecure=1&sni=lab.invalid&fp=chrome'
        profile = parse_profile(uri)
        engine = engine_for(profile, directory)
        if isinstance(engine, SingBox) and os.environ.get('VELUM_TEST_SING_BOX'):
            engine.binary = os.environ['VELUM_TEST_SING_BOX']
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
            engine.validate_config(profile, '192.0.2.20')
            firewall.configure('192.0.2.20', 24443, endpoint_udp=kind == 'shadowsocks')
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
            print(f'PASS: ordinary TCP socket egress through {engine.name}/{kind}', flush=True)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.settimeout(5)
                udp.sendto(b'tunnel-test', ('198.51.100.42', 18081))
                assert udp.recv(1024) == b'198.51.100.42:tunnel-test'
            print(f'PASS: ordinary UDP socket traverses real TUN/{kind}', flush=True)
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
