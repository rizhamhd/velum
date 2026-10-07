import base64
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from test_vless import BASE

from velum.config.links import parse_profile, with_certificate_name
from velum.config.profiles import ProfileStore
from velum.config.vless import ConfigurationError
from velum.network.firewall import ruleset
from velum.security.redact import redact
from velum.services.session import Session
from velum.vpn.configuration import MARK, generate_config, generate_engine_config
from velum.vpn.engine import SingBox, Xray, engine_for


def vmess(**options):
    data = {'v': '2', 'add': 'example.invalid', 'port': '443',
            'id': BASE.split('//')[1].split('@')[0], 'aid': '0', 'net': 'ws', 'tls': 'tls'}
    return 'vmess://' + base64.b64encode(json.dumps(data | options).encode()).decode()


SING_BOX = os.environ.get('VELUM_TEST_SING_BOX') or shutil.which('sing-box')
REALITY = ('?type=tcp&security=reality&sni=example.invalid&flow=xtls-rprx-vision'
           '&pbk=jNXHt1yRo0vDuchQlIP6Z0ZvjT3KtzVI-T4E7RoLJS0&sid=0123456789abcdef')


class LinkTests(unittest.TestCase):
    def test_certificate_override_enables_verification_for_all_tls_link_formats(self):
        uris = [BASE + '?security=tls&allowInsecure=true&sni=cover.invalid&type=ws&path=%2fws#My%20VPN',
                vmess(allowInsecure=True, sni='cover.invalid', path='/ws'),
                'trojan://p%40ss%3Aword@example.invalid:443?allowInsecure=1&sni=cover.invalid&type=ws&path=%2fws#My%20VPN']
        for uri in uris:
            with self.subTest(protocol=uri.split(':')[0]):
                original = parse_profile(uri)
                self.assertEqual(with_certificate_name(uri, ''), uri)
                updated = with_certificate_name(uri, ' CERT.EXAMPLE.INVALID ')
                p = parse_profile(updated)
                self.assertFalse(p.allow_insecure)
                self.assertEqual(p.certificate_name, 'cert.example.invalid')
                self.assertEqual((p.uuid, p.password, p.sni, p.path, p.transport),
                                 (original.uuid, original.password, original.sni, original.path, original.transport))
                self.assertIsInstance(engine_for(p, Path('/unused')), Xray)
                self.assertFalse(parse_profile(with_certificate_name(updated, '')).allow_insecure)
                if p.protocol != 'vmess':
                    self.assertIn('path=%2fws#', uri)
                    self.assertIn('path=%2fws&verifyPeerCertByName=', updated)
                    self.assertTrue(updated.endswith('#My%20VPN'))
                with self.assertRaises(ConfigurationError):
                    with_certificate_name(uri, 'frommitm')

    def test_provider_style_link_round_trips_without_changing_settings(self):
        uri = BASE + '?type=tcp&host=example.invalid&security=tls&allowInsecure=1&sni=cover.invalid&fp=chrome&alpn=h2%2Chttp%2F1.1#VPN'
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            item = store.save(uri)
            self.assertEqual(store.list()[0]['uri'], uri)
            export = Path(d) / 'export.json'
            store.export(item['id'], export)
            store.delete(item['id'])
            store.import_file(export)
            p = parse_profile(store.list()[0]['uri'])
            self.assertEqual(p.sni, 'cover.invalid')
            self.assertEqual(p.host, 'example.invalid')
            self.assertEqual(len(p.notices), 2)
            config = generate_engine_config(p)
            outbound = config['outbounds'][0]
            self.assertTrue(outbound['tls']['insecure'])
            self.assertEqual(outbound['tls']['server_name'], p.sni)
            self.assertEqual(outbound['routing_mark'], MARK)
            self.assertNotIn('transport', outbound)
            with self.assertRaises(ConfigurationError):
                generate_config(p)

    def test_transport_generation(self):
        cases = [('type=raw&headerType=http&host=example.invalid&path=/test', 'tcpSettings'),
                 ('type=grpc&serviceName=service&authority=example.invalid&mode=multi', 'grpcSettings'),
                 ('type=httpupgrade&host=example.invalid&path=/test', 'httpupgradeSettings'),
                 ('type=xhttp&host=example.invalid&path=/test&mode=packet-up', 'xhttpSettings')]
        for query, key in cases:
            stream = generate_config(parse_profile(BASE + '?' + query))['outbounds'][0]['streamSettings']
            self.assertIn(key, stream)
        p = parse_profile(BASE + REALITY)
        out = generate_config(p)['outbounds'][0]
        self.assertEqual(out['settings']['vnext'][0]['users'][0]['flow'], 'xtls-rprx-vision')
        self.assertEqual(out['streamSettings']['realitySettings']['publicKey'], p.public_key)

    def test_other_protocol_credentials_and_certificate_edit(self):
        p = parse_profile('trojan://p%40ss%3Aword@example.invalid:443#Trojan')
        self.assertEqual(p.password, 'p@ss:word')
        self.assertEqual(p.security, 'tls')
        self.assertNotIn(p.password, repr(p))
        self.assertEqual(generate_config(p)['outbounds'][0]['settings']['servers'][0]['password'], p.password)
        for uri in (vmess(ps='My VMess', host='cdn.invalid', path='/ws'),
                    'trojan://secret@example.invalid:443?type=grpc&serviceName=service'):
            edited = with_certificate_name(uri, 'cert.invalid')
            self.assertEqual(parse_profile(edited).certificate_name, 'cert.invalid')
            self.assertEqual(parse_profile(with_certificate_name(edited, '')).certificate_name, '')
        credentials = base64.urlsafe_b64encode(b'aes-128-gcm:p@ss:word').decode().rstrip('=')
        p = parse_profile('ss://' + credentials + '@example.invalid:8388#SS')
        legacy = base64.b64encode(b'aes-128-gcm:p@ss:word@example.invalid:8388').decode()
        self.assertEqual(parse_profile('ss://' + legacy).password, p.password)
        self.assertEqual(p.password, 'p@ss:word')
        self.assertEqual(generate_config(p)['outbounds'][0]['protocol'], 'shadowsocks')

    def test_bad_options_and_credentials_do_not_leak(self):
        for uri in (vmess(aid=64), vmess(scy='secret-unknown'), vmess(extra='secret'),
                    vmess(port=True), vmess(tls=[]),
                    'ss://YWVzLTEyOC1nY206cHc@example.invalid:8388?plugin=secret',
                    'trojan://secret@example.invalid:443?flow=xtls-rprx-vision',
                    BASE + '?security=reality&pbk=secret&sni=example.invalid',
                    BASE + REALITY + '&allowInsecure=1',
                    BASE + '?security=tls&allowInsecure=1&verifyPeerCertByName=example.invalid',
                    BASE + '?type=grpc&host=example.invalid',
                    BASE + '?type=ws&serviceName=secret'):
            with self.subTest(uri=uri), self.assertRaises(ConfigurationError) as exc:
                parse_profile(uri)
            self.assertNotIn('secret', str(exc.exception))
        for uri in (vmess(), 'trojan://secret@example.invalid:443', 'ss://secret@example.invalid:443'):
            self.assertNotIn(uri, redact(uri))

    def test_unsupported_backend_combinations_fail_before_network_changes(self):
        with tempfile.TemporaryDirectory() as d:
            runner = Mock()
            session = Session(Path(d), runner=runner)
            for query in ('type=xhttp&security=tls&allowInsecure=1',
                          'type=grpc&mode=multi&security=tls&allowInsecure=1'):
                with self.assertRaises(ConfigurationError):
                    session.validate_request(BASE + '?' + query, {})
            runner.run.assert_not_called()

    def test_tls_diagnostics_never_claim_insecure_identity_is_verified(self):
        with tempfile.TemporaryDirectory() as d:
            session = Session(Path(d), runner=Mock())
            session.profile = parse_profile(BASE + '?security=tls&allowInsecure=1')
            session.verification.run = Mock(return_value=True)
            session.emit = Mock()
            self.assertTrue(session.verify())
            self.assertEqual(session.verification.results[-1].status, 'WARN')
            self.assertIn('not verified', session.verification.results[-1].detail)

    def test_udp_endpoint_exception_is_explicit_and_marked(self):
        self.assertNotIn('udp dport 8388 accept', ruleset('192.0.2.1', 8388))
        self.assertIn(f'meta mark {MARK} ip daddr 192.0.2.1 udp dport 8388 accept',
                      ruleset('192.0.2.1', 8388, endpoint_udp=True))

    @unittest.skipUnless(shutil.which('xray'), 'Xray is not installed')
    def test_installed_xray_accepts_supported_protocols_and_transports(self):
        uris = [BASE + REALITY, vmess(), 'trojan://secret@example.invalid:443',
                'ss://aes-128-gcm:secret@example.invalid:8388']
        for transport in ('tcp', 'ws', 'grpc', 'httpupgrade', 'xhttp'):
            uris.append(BASE + f'?type={transport}&security=tls')
        uris.append(BASE + '?type=tcp&headerType=http&host=example.invalid&path=/http')
        with tempfile.TemporaryDirectory() as d:
            for uri in uris:
                with self.subTest(uri=uri):
                    Xray(Path(d)).validate_config(parse_profile(uri), '192.0.2.1')

    @unittest.skipUnless(SING_BOX, 'sing-box is not installed')
    def test_compatibility_config_passes_real_engine(self):
        uris = [BASE + '?type=' + t + '&security=tls&allowInsecure=1&fp=chrome'
                for t in ('tcp', 'ws', 'grpc', 'httpupgrade')]
        uris += [vmess(allowInsecure=True), 'trojan://secret@example.invalid:443?allowInsecure=1',
                 BASE + '?type=ws&path=%2Fws%3Fed%3D2048&security=tls&allowInsecure=1']
        with tempfile.TemporaryDirectory() as d:
            for uri in uris:
                p = parse_profile(uri)
                self.assertIsInstance(engine_for(p, Path(d)), SingBox)
                SingBox(Path(d), SING_BOX).validate_config(p, '192.0.2.1')


if __name__ == '__main__':
    unittest.main()
