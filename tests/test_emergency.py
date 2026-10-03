import subprocess
import unittest
from unittest.mock import Mock, patch

from velum.services.emergency import main, stop_and_recover


class EmergencyTests(unittest.TestCase):
    def test_force_stop_is_scoped_and_recovery_precedes_socket_restart(self):
        run = Mock()
        stop_and_recover(run)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands, [
            ['/usr/bin/systemctl', 'stop', '--no-block', 'velum.socket', 'velum.service'],
            ['/usr/bin/systemctl', 'kill', '--kill-whom=all', '--signal=SIGKILL', 'velum.service'],
            ['/usr/bin/systemctl', 'stop', 'velum.socket', 'velum.service'],
            ['/usr/bin/python', '-I', '-m', 'velum.services.helper', '--recover'],
            ['/usr/bin/systemctl', 'start', 'velum.socket'],
        ])
        self.assertFalse(run.call_args_list[1].kwargs['check'])
        self.assertTrue(run.call_args_list[2].kwargs['check'])

    def test_stop_or_recovery_failure_never_restarts_socket(self):
        for stage in (0, 2, 3):
            for error in (subprocess.CalledProcessError(1, 'test'), subprocess.TimeoutExpired('test', 20)):
                with self.subTest(stage=stage, error=error):
                    run = Mock(side_effect=[None] * stage + [error])
                    with self.assertRaises(subprocess.SubprocessError):
                        stop_and_recover(run)
                    self.assertEqual(run.call_count, stage + 1)
                    self.assertNotIn('start', run.call_args.args[0])

    @patch('velum.services.emergency.stop_and_recover')
    def test_unprivileged_or_extra_arguments_cannot_recover(self, recover):
        for uid, argv in ((1000, ['emergency']), (0, ['emergency', '--arbitrary'])):
            with patch('velum.services.emergency.os.geteuid', return_value=uid), patch('sys.argv', argv):
                self.assertEqual(main(), 1)
        recover.assert_not_called()
