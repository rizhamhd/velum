"""Explicit root-only integration; never discovered by ordinary unittest runs."""
import os
import tempfile
from pathlib import Path

from velum.network.firewall import Firewall
from velum.network.system import Runner, Upstream
from velum.network.transaction import Transaction
from velum.network.tunnel import Tunnel


def main():
    if os.geteuid() != 0 or os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net'):
        raise SystemExit('Refusing to run outside an isolated root network namespace')
    runner = Runner()
    runner.run('/usr/bin/ip', 'link', 'set', 'lo', 'up')
    runner.run('/usr/bin/ip', 'link', 'add', 'uplink0', 'type', 'dummy')
    runner.run('/usr/bin/ip', 'addr', 'add', '192.0.2.2/24', 'dev', 'uplink0')
    runner.run('/usr/bin/ip', 'link', 'set', 'uplink0', 'up')
    runner.run('/usr/bin/ip', 'route', 'add', 'default', 'via', '192.0.2.1', 'dev', 'uplink0')
    # An unrelated table must survive the entire transaction.
    runner.run('/usr/bin/nft', 'add', 'table', 'inet', 'unrelated_test')
    with tempfile.TemporaryDirectory(prefix='velum-integration-') as d:
        tx = Transaction(runner, Path(d) / 'network.json')
        guard = Transaction(runner, Path(d) / 'firewall.json')
        tunnel, firewall = Tunnel(runner, tx), Firewall(runner, guard)
        try:
            tunnel.preflight()
            firewall.preflight()
            firewall.configure('192.0.2.20', 443)
            assert firewall.verify()
            print('PASS: nftables creation and rule verification')
            tunnel.prepare(Upstream('uplink0', '192.0.2.1', 'Ethernet'), '192.0.2.20')
            tunnel.start()
            tunnel.wait()
            tunnel.configure_routes()
            assert runner.json('/usr/bin/ip', '-j', 'route', 'get', '8.8.8.8')[0]['dev'] == 'vpn0'
            assert runner.json('/usr/bin/ip', '-j', 'route', 'get', '192.0.2.20', 'mark', '22096')[0]['dev'] == 'uplink0'
            print('PASS: real TUN adapter, policy routes and endpoint bypass')
        finally:
            tunnel.stop()
            tx.rollback()
            guard.rollback()
        assert runner.json('/usr/bin/ip', '-j', 'route', 'get', '8.8.8.8')[0]['dev'] == 'uplink0'
        assert not any(x['ifname'] == 'vpn0' for x in runner.json('/usr/bin/ip', '-j', 'link'))
        tables = runner.json('/usr/bin/nft', '-j', 'list', 'tables')['nftables']
        assert any(x.get('table', {}).get('name') == 'unrelated_test' for x in tables)
        assert not any(x.get('table', {}).get('name') == 'velum_vpn' for x in tables)
        print('PASS: route/TUN/nftables rollback; unrelated table preserved')


if __name__ == '__main__':
    main()
