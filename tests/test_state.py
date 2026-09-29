import unittest
from unittest.mock import Mock

from velum.core.state import STEPS, State, StateMachine


class StateTests(unittest.TestCase):
    def test_verified_only(self):
        history = []
        machine = StateMachine(history.append)
        actions = {s: Mock(return_value=True) for s in STEPS}
        machine.connect(actions, Mock())
        self.assertEqual(history, [*STEPS, State.CONNECTED])

    def test_failure_at_every_stage(self):
        for stage in STEPS:
            history, cleanup = [], Mock()
            machine = StateMachine(history.append)
            actions = {s: Mock(return_value=True) for s in STEPS}
            actions[stage].side_effect = RuntimeError('failure')
            with self.assertRaises(RuntimeError):
                machine.connect(actions, cleanup)
            self.assertNotIn(State.CONNECTED, history)
            cleanup.assert_called_once()
            self.assertEqual(machine.state, State.DISCONNECTED)

    def test_engine_alone_is_insufficient(self):
        machine = StateMachine()
        actions = {s: Mock(return_value=True) for s in STEPS}
        actions[State.VERIFYING].return_value = False
        with self.assertRaises(RuntimeError):
            machine.connect(actions, Mock())
        self.assertNotEqual(machine.state, State.CONNECTED)

    def test_loss_holds_network(self):
        machine = StateMachine()
        machine.set(State.CONNECTED)
        machine.lost('Tunnel disappeared')
        self.assertEqual(machine.state, State.ERROR)
