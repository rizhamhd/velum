import unittest

from velum.network.system import NetworkError, interface_kind, interface_name, parse_default


class NetworkTests(unittest.TestCase):
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
