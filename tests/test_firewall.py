import unittest

from velum.network.firewall import fingerprint, ruleset


class FirewallTests(unittest.TestCase):
    def test_isolated_and_fail_closed(self):
        text = ruleset('192.0.2.1', 443)
        self.assertNotIn('flush ruleset', text)
        self.assertIn('meta nfproto ipv6 drop', text)
        self.assertIn('meta mark', text)
        self.assertNotIn('ct state established', text)
        self.assertIn('dport { 53, 853 } drop', text)

    def test_off_keeps_leak_protection(self):
        text = ruleset('192.0.2.1', 443, 'OFF')
        self.assertIn('meta nfproto ipv6 drop', text)
        self.assertNotIn('meta mark', text)

    def test_injection_rejected(self):
        with self.assertRaises(ValueError):
            ruleset('1.1.1.1; flush ruleset', 443)
        with self.assertRaises(RuntimeError):
            ruleset('192.0.2.1', 443, hotspot='x";drop')

    def test_fingerprint(self):
        self.assertEqual(fingerprint({'handle': 1, 'rule': 'a'}),
                         fingerprint({'handle': 9, 'rule': 'a'}))
        self.assertNotEqual(fingerprint({'rule': 'a'}), fingerprint({'rule': 'b'}))
