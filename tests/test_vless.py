import unittest

from velum.config.vless import ConfigurationError, parse_vless

BASE = 'vless://00000000-0000-4000-8000-000000000001@example.invalid:443'


class ParserTests(unittest.TestCase):
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
                    BASE + '?type=grpc', BASE + '?security=reality', BASE + '?xyz=yes',
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
