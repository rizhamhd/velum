import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from velum.network.dns import ResolvedDNS


class DNSTests(unittest.TestCase):
    def test_foreign_resolver_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'resolv.conf'
            path.write_text('nameserver 192.0.2.1\n')
            dns = ResolvedDNS(Mock(), Mock(), path)
            with self.assertRaisesRegex(RuntimeError, 'Unsupported DNS manager'):
                dns.preflight()
            self.assertEqual(path.read_text(), 'nameserver 192.0.2.1\n')

    def test_link_only_changes(self):
        runner, tx = Mock(), Mock()
        ResolvedDNS(runner, tx).configure()
        self.assertIn('vpn0', tx.apply.call_args.args[0])
        self.assertEqual(tx.apply.call_args.args[1], ['/usr/bin/resolvectl', 'revert', 'vpn0'])
