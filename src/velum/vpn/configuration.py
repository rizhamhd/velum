from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from velum.config.vless import ConfigurationError, Vless

MARK = 0x5650
SOCKS_PORT = 28673


def generate_config(profile: Vless, server_ip: str | None = None):
    if profile.allow_insecure:
        raise ConfigurationError('This profile requires sing-box; export its engine configuration instead')
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
    elif profile.security == 'reality':
        stream['realitySettings'] = {'serverName': profile.sni, 'fingerprint': profile.fingerprint,
                                     'publicKey': profile.public_key, 'shortId': profile.short_id,
                                     'spiderX': profile.spider_x}
    if profile.transport == 'ws':
        stream['wsSettings'] = {'path': profile.path}
        if profile.host:
            stream['wsSettings']['host'] = profile.host
    elif profile.transport == 'tcp' and profile.header_type == 'http':
        request = {'path': [profile.path]}
        if profile.host:
            request['headers'] = {'Host': [profile.host]}
        stream['tcpSettings'] = {'header': {'type': 'http', 'request': request}}
    elif profile.transport == 'grpc':
        stream['grpcSettings'] = {'serviceName': profile.service_name,
                                   'multiMode': profile.mode == 'multi'}
        if profile.authority:
            stream['grpcSettings']['authority'] = profile.authority
    elif profile.transport in ('httpupgrade', 'xhttp'):
        settings = {'host': profile.host, 'path': profile.path}
        if profile.transport == 'xhttp':
            settings['mode'] = profile.mode or 'auto'
        stream[profile.transport + 'Settings'] = settings
    if profile.protocol in ('vless', 'vmess'):
        user = {'id': profile.uuid}
        if profile.protocol == 'vless':
            user['encryption'] = profile.encryption
            if profile.flow:
                user['flow'] = profile.flow
        else:
            user.update(security=profile.cipher, alterId=profile.alter_id)
        settings = {'vnext': [{'address': server_ip or profile.server,
                              'port': profile.port, 'users': [user]}]}
    else:
        server = {'address': server_ip or profile.server, 'port': profile.port,
                  'password': profile.password}
        if profile.protocol == 'shadowsocks':
            server['method'] = profile.cipher
        settings = {'servers': [server]}
    return {'log': {'loglevel': 'warning'},
            'inbounds': [{'tag': 'local-tun', 'listen': '127.0.0.1', 'port': SOCKS_PORT,
                          'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}}],
            'outbounds': [{'tag': 'vpn', 'protocol': profile.protocol,
                           'settings': settings,
                           'streamSettings': stream}]}


def generate_sing_box_config(profile: Vless, server_ip: str | None = None):
    if profile.security != 'tls' or not profile.allow_insecure:
        raise ConfigurationError('The compatibility engine is only used for explicit allowInsecure TLS links')
    if profile.transport not in ('tcp', 'ws', 'grpc', 'httpupgrade') or profile.header_type != 'none':
        raise ConfigurationError('allowInsecure supports plain TCP, WebSocket, gRPC and HTTPUpgrade; '
                                 'use verified TLS for XHTTP or TCP HTTP headers')
    if profile.authority or profile.mode == 'multi' or profile.flow.endswith('-udp443'):
        raise ConfigurationError('The compatibility engine does not support gRPC authority/multi or udp443 flow')
    if profile.fingerprint not in ('', 'chrome', 'firefox', 'safari', 'ios', 'android', 'edge',
                                    '360', 'qq', 'random', 'randomized'):
        raise ConfigurationError('Unsupported compatibility fingerprint')
    tls = {'enabled': True, 'server_name': profile.sni or profile.server, 'insecure': True}
    if profile.alpn:
        tls['alpn'] = list(profile.alpn)
    if profile.fingerprint:
        tls['utls'] = {'enabled': True, 'fingerprint': profile.fingerprint}
    outbound = {'type': profile.protocol, 'tag': 'vpn', 'server': server_ip or profile.server,
                'server_port': profile.port, 'routing_mark': MARK, 'tls': tls}
    if profile.protocol in ('vless', 'vmess'):
        outbound['uuid'] = profile.uuid
        if profile.protocol == 'vmess':
            if profile.cipher == 'zero':
                raise ConfigurationError('VMess zero cipher requires verified TLS with Xray')
            outbound.update(security=profile.cipher, alter_id=profile.alter_id)
        elif profile.flow:
            outbound['flow'] = profile.flow
    else:
        outbound['password'] = profile.password
    if profile.transport in ('ws', 'httpupgrade'):
        transport = {'type': profile.transport, 'path': profile.path}
        if profile.host:
            if profile.transport == 'ws':
                transport['headers'] = {'Host': profile.host}
            else:
                transport['host'] = profile.host
        # Translate Xray's WebSocket early-data URL convention explicitly.
        path = urlsplit(profile.path)
        pairs = parse_qsl(path.query, keep_blank_values=True)
        early = [v for k, v in pairs if k == 'ed']
        if early:
            if profile.transport != 'ws' or len(early) != 1 or not early[0].isdigit() or not 0 <= int(early[0]) <= 65535:
                raise ConfigurationError('Unsupported early-data setting')
            transport.update(max_early_data=int(early[0]), early_data_header_name='Sec-WebSocket-Protocol')
            transport['path'] = urlunsplit(path._replace(query=urlencode([(k, v) for k, v in pairs if k != 'ed'])))
        outbound['transport'] = transport
    elif profile.transport == 'grpc':
        outbound['transport'] = {'type': 'grpc', 'service_name': profile.service_name}
    return {'log': {'level': 'warn', 'disabled': True},
            'inbounds': [{'type': 'socks', 'tag': 'local-tun', 'listen': '127.0.0.1',
                          'listen_port': SOCKS_PORT}],
            'outbounds': [outbound], 'route': {'final': 'vpn'}}


def generate_engine_config(profile, server_ip=None):
    return (generate_sing_box_config if profile.allow_insecure else generate_config)(profile, server_ip)
