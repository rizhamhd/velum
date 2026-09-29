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
        self.assertFalse(v.run('8.8.8.8'))
        self.assertTrue(v.run('1.1.1.1'))

    @patch('velum.diagnostics.verification.socket.getaddrinfo', return_value=[1])
    def test_wrong_route_fails(self, dns):
        runner = Mock()
        runner.json.return_value = [{'dev': 'wlp2s0'}]
        v = Verification(runner, Mock(), Mock(), Mock(), Mock())
        self.assertFalse(v.run('1.1.1.1'))
        self.assertTrue(any('not being routed' in c.detail for c in v.results))
