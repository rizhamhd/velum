from velum.config.vless import Vless

MARK = 0x5650
SOCKS_PORT = 28673


def generate_config(profile: Vless, server_ip: str | None = None):
    stream = {'network': profile.transport, 'security': profile.security,
              'sockopt': {'mark': MARK}}
    if profile.security == 'tls':
        tls = {'serverName': profile.sni or profile.server,
               'allowInsecure': False}
        if profile.certificate_name:
            tls['verifyPeerCertByName'] = profile.certificate_name
        if profile.alpn:
            tls['alpn'] = list(profile.alpn)
        if profile.fingerprint:
            tls['fingerprint'] = profile.fingerprint
        stream['tlsSettings'] = tls
    if profile.transport == 'ws':
        stream['wsSettings'] = {'path': profile.path}
        if profile.host:
            stream['wsSettings']['host'] = profile.host
    return {'log': {'loglevel': 'warning'},
            'inbounds': [{'tag': 'local-tun', 'listen': '127.0.0.1', 'port': SOCKS_PORT,
                          'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}}],
            'outbounds': [{'tag': 'vpn', 'protocol': 'vless',
                           'settings': {'vnext': [{'address': server_ip or profile.server,
                                                  'port': profile.port,
                                                  'users': [{'id': profile.uuid,
                                                             'encryption': profile.encryption}]}]},
                           'streamSettings': stream}]}
