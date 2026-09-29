import unittest
from unittest.mock import Mock

from velum.network.firewall import ruleset
from velum.network.hotspot import Hotspot
from velum.network.system import Upstream


class HotspotTests(unittest.TestCase):
    def test_same_upstream_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'separate'):
            Hotspot(Mock(), Mock()).preflight('wlp2s0', Upstream('wlp2s0', None, 'Wi-Fi'))

    def test_forward_dns_nat(self):
        text = ruleset('192.0.2.1', 443, 'VPN + hotspot', 'wlp3s0')
        self.assertIn('iifname "wlp3s0" oifname "vpn0" masquerade', text)
        self.assertIn('iifname "wlp3s0" udp dport 53 dnat ip to 1.1.1.1', text)
        self.assertIn('iifname "wlp3s0" drop', text)

    def test_restore_forwarding(self):
        runner, tx = Mock(), Mock()
        runner.run.return_value = '0\n'
        hotspot = Hotspot(runner, tx)
        hotspot.interface, hotspot.subnet = 'wlp3s0', '10.42.0.0/24'
        hotspot.configure()
        self.assertEqual(tx.apply.call_count, 3)
        self.assertTrue(tx.apply.call_args.args[1][-1].endswith('=0'))
