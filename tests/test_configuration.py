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
    def test_certificate_name_keeps_original_sni_when_endpoint_is_pinned(self):
        p = parse_vless(BASE + '?security=tls&type=ws&sni=youtube.com'
                        '&host=ws.example.invalid&verifyPeerCertByName=cert.example.invalid')
        stream = generate_config(p, '192.0.2.1')['outbounds'][0]['streamSettings']
        self.assertEqual(stream['tlsSettings']['serverName'], 'youtube.com')
        self.assertIs(stream['tlsSettings']['allowInsecure'], False)
        self.assertEqual(stream['tlsSettings']['verifyPeerCertByName'], 'cert.example.invalid')
        self.assertEqual(stream['wsSettings']['host'], 'ws.example.invalid')

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
                for security in ('none', 'tls', 'tls&verifyPeerCertByName=cert.example.invalid'):
                    path = Path(d) / 'config.json'
                    path.write_text(json.dumps(generate_config(parse_vless(
                        BASE + f'?type={transport}&security={security}'))))
                    result = subprocess.run(['xray', 'run', '-test', '-config', str(path)],
                                            capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode())
