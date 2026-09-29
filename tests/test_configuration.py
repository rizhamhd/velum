import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_vless import BASE

from velum.config.vless import parse_vless
from velum.vpn.configuration import generate_config


class ConfigurationTests(unittest.TestCase):
    def test_tls(self):
        p = parse_vless(BASE + '?security=tls&type=ws&host=example.invalid&path=%2Fx')
        config = generate_config(p, '192.0.2.1')
        outbound = config['outbounds'][0]
        self.assertEqual(outbound['settings']['vnext'][0]['address'], '192.0.2.1')
        self.assertEqual(outbound['streamSettings']['tlsSettings']['serverName'], 'example.invalid')
        self.assertFalse(outbound['streamSettings']['tlsSettings']['allowInsecure'])
        self.assertEqual(outbound['streamSettings']['wsSettings']['path'], '/x')
        self.assertEqual(len(config['outbounds']), 1)

    @unittest.skipUnless(shutil.which('xray'), 'Xray is not installed')
    def test_actual_xray_validation(self):
        with tempfile.TemporaryDirectory() as d:
            for transport in ('tcp', 'ws'):
                for security in ('none', 'tls'):
                    path = Path(d) / 'config.json'
                    path.write_text(json.dumps(generate_config(parse_vless(
                        BASE + f'?type={transport}&security={security}'))))
                    result = subprocess.run(['xray', 'run', '-test', '-config', str(path)],
                                            capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
