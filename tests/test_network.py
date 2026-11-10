import subprocess
import time
import unittest
from unittest.mock import patch

from velum.network.system import (
    NetworkError,
    interface_kind,
    interface_name,
    parse_default,
    resolve_ipv4,
)


class NetworkTests(unittest.TestCase):
    def test_resolution_of_numeric_endpoint_needs_no_resolver(self):
        with patch('velum.network.system.subprocess.run') as run:
            self.assertEqual(resolve_ipv4('192.0.2.10', 443), '192.0.2.10')
            run.assert_not_called()

    def test_system_resolver_child_returns_ipv4(self):
        self.assertEqual(resolve_ipv4('localhost', 443), '127.0.0.1')

    def test_stalled_resolver_child_is_terminated(self):
        run = subprocess.run

        def blocked_resolver(args, **kwargs):
            return run([args[0], '-I', '-c', 'import time; time.sleep(30)'], **kwargs)

        start = time.monotonic()
        with patch('velum.network.system.subprocess.run', side_effect=blocked_resolver):
            with self.assertRaisesRegex(NetworkError, 'DNS lookup timed out'):
                resolve_ipv4('example.invalid', 443, timeout=0.1)
        self.assertLess(time.monotonic() - start, 5)

    def test_default(self):
        routes = [{'dst': 'default', 'dev': 'vpn0', 'metric': 1},
                  {'dst': 'default', 'dev': 'wlp2s0', 'gateway': '192.0.2.1', 'metric': 600}]
        links = [{'ifname': 'vpn0', 'linkinfo': {'info_kind': 'tun'}},
                 {'ifname': 'wlp2s0', 'link_type': 'ether'}]
        route = parse_default(routes, links)
        self.assertEqual(route.interface, 'wlp2s0')
        self.assertEqual(route.gateway, '192.0.2.1')

    def test_types(self):
        self.assertEqual(interface_kind({'ifname': 'vpn0', 'linkinfo': {'info_kind': 'tun'}}), 'VPN/TUN')
        self.assertEqual(interface_kind({'ifname': 'lo'}), 'Loopback')
        self.assertEqual(interface_kind({'ifname': 'enp3s0', 'link_type': 'ether'}), 'Ethernet')

    def test_missing(self):
        with self.assertRaises(NetworkError):
            parse_default([], [])
        with self.assertRaises(NetworkError):
            interface_name('x;reboot')

    def test_disconnected_interface_cannot_supply_upstream(self):
        routes = [{'dst': 'default', 'dev': 'wlp2s0', 'gateway': '192.0.2.1'}]
        for link in ({'operstate': 'DOWN'}, {'operstate': 'LOWERLAYERDOWN'},
                     {'flags': ['BROADCAST', 'MULTICAST']}):
            with self.subTest(link=link), self.assertRaises(NetworkError):
                parse_default(routes, [{'ifname': 'wlp2s0', 'link_type': 'ether', **link}])
        with self.assertRaises(NetworkError):
            parse_default([{**routes[0], 'flags': ['linkdown']}],
                          [{'ifname': 'wlp2s0', 'link_type': 'ether'}])
