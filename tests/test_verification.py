import unittest
from unittest.mock import Mock, patch

from velum.diagnostics.verification import IPVerifier, Verification


class VerificationTests(unittest.TestCase):
    def test_fallback_and_no_proxy(self):
        runner = Mock()
        runner.run.side_effect = [RuntimeError(), '8.8.8.8', '8.8.8.8']
        self.assertEqual(IPVerifier(runner).observe(), '8.8.8.8')
        for call in runner.run.call_args_list:
            self.assertIn('--noproxy', call.args)
            self.assertNotIn('--interface', call.args)

    def test_disagreement(self):
        runner = Mock()
        runner.run.side_effect = ['1.1.1.1', '8.8.8.8', '9.9.9.9']
        with self.assertRaises(RuntimeError):
            IPVerifier(runner).observe()

    @patch('velum.diagnostics.verification.socket.getaddrinfo', return_value=[1])
    @patch('velum.diagnostics.verification.IPVerifier.observe', return_value='8.8.8.8')
    def test_unchanged_egress_fails(self, observe, dns):
        runner = Mock()
        runner.json.return_value = [{'dev': 'vpn0'}]
        v = Verification(runner, Mock(), Mock(), Mock(), Mock())
        v.policy_valid = Mock(return_value=True)
        self.assertFalse(v.run('8.8.8.8'))
        self.assertTrue(v.run('1.1.1.1'))

    @patch('velum.diagnostics.verification.socket.getaddrinfo', return_value=[1])
    @patch('velum.diagnostics.verification.IPVerifier.observe', return_value='8.8.8.8')
    def test_no_baseline_still_requires_tunnel_and_https_checks(self, observe, dns):
        runner = Mock()
        runner.json.return_value = [{'dev': 'vpn0'}]
        v = Verification(runner, Mock(), Mock(), Mock(), Mock())
        v.policy_valid = Mock(return_value=True)
        self.assertTrue(v.run('', expect_change=False))
        observe.assert_called_once_with()
        self.assertEqual(v.vpn_ip, '8.8.8.8')
        observe.side_effect = RuntimeError('No tunnel internet access')
        self.assertFalse(v.run('', expect_change=False))
        observe.reset_mock()
        runner.json.return_value = [{'dev': 'eth0'}]
        self.assertFalse(v.run('', expect_change=False))
        observe.assert_not_called()

    @patch('velum.diagnostics.verification.socket.getaddrinfo', return_value=[1])
    def test_wrong_route_fails(self, dns):
        runner = Mock()
        runner.json.return_value = [{'dev': 'wlp2s0'}]
        v = Verification(runner, Mock(), Mock(), Mock(), Mock())
        self.assertFalse(v.run('1.1.1.1'))
        self.assertTrue(any('not being routed' in c.detail for c in v.results))

    def test_policy_rejects_extra_rule(self):
        runner = Mock()
        routes = [{'dst': 'default', 'dev': 'vpn0'}]
        rules = [{'priority': priority, 'table': 28672 if priority == 11000 else 254}
                 for priority in (0, 10998, 10999, 11000, 32766, 32767)]
        runner.json.side_effect = [routes, rules]
        v = Verification(runner, Mock(), Mock(), Mock(), Mock())
        self.assertTrue(v.policy_valid())
        runner.json.side_effect = [routes, rules + [{'priority': 11000, 'table': 254}]]
        self.assertFalse(v.policy_valid())
