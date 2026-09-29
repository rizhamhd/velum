import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from velum.network.transaction import Transaction
from velum.network.tunnel import Tunnel


class TransactionTests(unittest.TestCase):
    def test_reverse_order_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            runner = Mock()
            path = Path(d) / 'journal.json'
            tx = Transaction(runner, path)
            tx.apply(['add', 'a'], ['delete', 'a'])
            tx.apply(['add', 'b'], ['delete', 'b'])
            Transaction(runner, path).rollback()
            self.assertEqual(runner.run.call_args_list[-2].args, ('delete', 'b'))
            self.assertFalse(path.exists())

    def test_failed_cleanup_retains_journal(self):
        with tempfile.TemporaryDirectory() as d:
            runner = Mock()
            path = Path(d) / 'journal.json'
            tx = Transaction(runner, path)
            tx.apply(['add'], ['delete'])
            runner.run.side_effect = RuntimeError()
            with self.assertRaises(RuntimeError):
                tx.rollback()
            self.assertTrue(path.exists())

    def test_route_order(self):
        runner, tx = Mock(), Mock()
        Tunnel(runner, tx).configure_routes()
        commands = [call.args[0] for call in tx.apply.call_args_list]
        self.assertIn('fwmark', commands[1])
        self.assertEqual(commands[-1][-1], '28672')
        self.assertFalse(any('replace' in cmd for cmd in commands))
