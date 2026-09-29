import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_vless import BASE

from velum.security.redact import redact
from velum.vpn.engine import Xray


class EngineTests(unittest.TestCase):
    def test_redaction(self):
        self.assertNotIn(BASE, redact(BASE))
        self.assertNotIn('00000000-0000-4000-8000-000000000001', redact(BASE.split('@')[0]))
        self.assertNotIn('secret', redact('token=secret password=secret'))

    @patch('velum.vpn.engine.subprocess.Popen')
    def test_lifecycle(self, popen):
        with tempfile.TemporaryDirectory() as d:
            process = Mock()
            process.poll.return_value = None
            popen.return_value = process
            engine = Xray(Path(d))
            self.assertFalse(engine.status())
            engine.start()
            self.assertTrue(engine.status())
            engine.stop()
            process.terminate.assert_called_once()
            self.assertFalse(engine.status())
