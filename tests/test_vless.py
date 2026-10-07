import unittest

from velum.config.vless import ConfigurationError, parse_vless, with_certificate_name

BASE = 'vless://00000000-0000-4000-8000-000000000001@example.invalid:443'


class ParserTests(unittest.TestCase):
    def test_certificate_edit_of_insecure_vless_keeps_sni_and_encoding(self):
        uri = BASE + '?security=tls&%61llowInsecure=true&sni=cover.invalid&type=ws&path=%2fws#My%20VPN'
        updated = with_certificate_name(uri, 'cert.example.invalid')
        self.assertEqual(updated, uri.replace('%61llowInsecure=true', '%61llowInsecure=0')
                         .replace('#', '&verifyPeerCertByName=cert.example.invalid#'))
        self.assertFalse(parse_vless(updated).allow_insecure)
        self.assertEqual(parse_vless(updated).sni, 'cover.invalid')

    def test_certificate_name_is_explicit_and_tls_only(self):
        self.assertEqual(parse_vless(BASE + '?security=tls').certificate_name, '')
        p = parse_vless(BASE + '?security=tls&verifyPeerCertByName=cert.example.invalid')
        self.assertEqual(p.certificate_name, 'cert.example.invalid')
        for query in ('verifyPeerCertByName=example.invalid',
                      'security=tls&verifyPeerCertByName=',
                      'security=tls&verifyPeerCertByName=FromMitM',
                      'security=tls&verifyPeerCertByName=a,b',
                      'security=tls&verifyPeerCertByName=a&verifyPeerCertByName=b',
                      'security=tls&allowInsecure=yes', 'security=tls&allowInsecure='):
            with self.subTest(query=query), self.assertRaises(ConfigurationError):
                parse_vless(BASE + '?' + query)

    def test_certificate_name_preserves_sni_transport_and_url_encoding(self):
        uri = BASE + '?security=tls&type=ws&sni=youtube.com&host=ws.example.invalid&path=%2fa%3Fed%3D2048#My%20VPN'
        updated = with_certificate_name(uri, 'cert.example.invalid')
        self.assertEqual(updated, uri.replace('#', '&verifyPeerCertByName=cert.example.invalid#'))
        self.assertEqual(with_certificate_name(updated, 'cert.example.invalid'), updated)
        self.assertEqual(with_certificate_name(updated, ''), uri)
        self.assertEqual(parse_vless(updated).sni, 'youtube.com')
        self.assertEqual(with_certificate_name(BASE, ''), BASE)
        with self.assertRaises(ConfigurationError):
            with_certificate_name(BASE, 'cert.example.invalid')
        encoded = uri.replace('#', '&%76erifyPeerCertByName=old.example.invalid#')
        self.assertEqual(with_certificate_name(encoded, 'cert.example.invalid'), updated)

    def test_minimal(self):
        p = parse_vless(BASE)
        self.assertEqual((p.server, p.port, p.transport), ('example.invalid', 443, 'tcp'))
        self.assertNotIn(p.uuid, repr(p))

    def test_ws_tls(self):
        uri = BASE + '?type=ws&security=tls&sni=tls.example.invalid&host=ws.example.invalid&path=%2Fsecure&alpn=h2%2Chttp%2F1.1&fp=random#My%20VPN'
        p = parse_vless(uri)
        self.assertEqual(p.path, '/secure')
        self.assertEqual(p.alpn, ('h2', 'http/1.1'))
        self.assertEqual(p.name, 'My VPN')
        self.assertEqual(p.original_uri, uri)

    def test_ipv6(self):
        p = parse_vless(BASE.replace('example.invalid', '[2001:db8::1]'))
        self.assertEqual(p.server, '2001:db8::1')

    def test_invalid(self):
        for uri in ['https://example.invalid', BASE.replace(':443', ':0'),
                    BASE.replace(':443', ':65536'), BASE.replace(':443', ''),
                    BASE.replace('00000000-0000-4000-8000-000000000001', 'bad'),
                    BASE + '?type=kcp', BASE + '?security=reality', BASE + '?xyz=yes',
                    BASE + '?type=ws&type=tcp', BASE + '?path=/a', BASE + '?sni=x',
                    BASE + '?type=ws&path=%0A', BASE + '#%ZZ', BASE + '?fp=random',
                    BASE + '?encryption=auto', BASE + '?type=ws&host=a;touch',
                    BASE + '?type=ws&path=relative', BASE + '?security=tls&alpn=',
                    BASE + '?type', BASE + '#%00']:
            with self.subTest(uri=uri), self.assertRaises(ConfigurationError):
                parse_vless(uri)

    def test_unknown_error(self):
        with self.assertRaisesRegex(ConfigurationError, 'Unsupported VLESS parameter: xyz'):
            parse_vless(BASE + '?xyz=test')

    def test_transport_combinations(self):
        for transport in ('tcp', 'ws'):
            for security in ('none', 'tls'):
                self.assertEqual(parse_vless(BASE + f'?type={transport}&security={security}').security, security)
