"""Share-link formats; credentials never appear in validation errors."""
import base64
import binascii
import json
import re
from dataclasses import replace
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from velum.config.vless import (
    ConfigurationError,
    hostname,
    parse_vless,
    replace_certificate_options,
)

DUMMY_ID = '00000000-0000-4000-8000-000000000001'
SS_CIPHERS = ('aes-128-gcm', 'aes-256-gcm', 'chacha20-ietf-poly1305',
              '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm',
              '2022-blake3-chacha20-poly1305')


def decode64(value):
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_',
                                validate=True).decode('utf-8')
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ConfigurationError('Invalid base64 share link') from exc


def checked_text(value, label, limit=4096):
    if not isinstance(value, str) or not value or len(value) > limit or any(
            ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigurationError(f'Invalid {label}')
    return value


def vmess_data(uri):
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ConfigurationError('Duplicate VMess field')
                result[key] = value
            return result
        data = json.loads(decode64(uri[8:]), object_pairs_hook=unique)
    except (ValueError, RecursionError) as exc:
        raise ConfigurationError('Invalid VMess base64 JSON link') from exc
    if not isinstance(data, dict):
        raise ConfigurationError('VMess link must contain a JSON object')
    allowed = {'v', 'ps', 'add', 'port', 'id', 'aid', 'scy', 'net', 'type', 'host',
               'path', 'tls', 'sni', 'alpn', 'fp', 'allowInsecure', 'verifyPeerCertByName'}
    if set(data) - allowed:
        raise ConfigurationError('Unsupported VMess JSON field')
    for key, value in data.items():
        if key not in ('v', 'port', 'aid', 'allowInsecure') and not isinstance(value, str):
            raise ConfigurationError('VMess text fields must be strings')
    if str(data.get('v', '2')) not in ('1', '2'):
        raise ConfigurationError('Unsupported VMess link version')
    return data


def parse_profile(uri):
    if not isinstance(uri, str) or len(uri) > 16384:
        raise ConfigurationError('VPN URL must be text, at most 16 KiB')
    uri = uri.strip()
    checked_text(uri, 'VPN URL', 16384)
    if re.search(r'%(?![0-9a-fA-F]{2})', uri):
        raise ConfigurationError('Invalid percent escape in VPN URL')
    try:
        if uri.startswith('vless://'):
            return parse_vless(uri)
        if uri.startswith('vmess://'):
            data = vmess_data(uri)
            server = hostname(checked_text(data.get('add'), 'VMess server'))
            port = str(data.get('port', ''))
            if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
                raise ConfigurationError('Invalid VMess port')
            uid = checked_text(data.get('id'), 'VMess UUID')
            cipher = data.get('scy', 'auto') or 'auto'
            if cipher not in ('auto', 'aes-128-gcm', 'chacha20-poly1305', 'none', 'zero'):
                raise ConfigurationError('Unsupported VMess cipher')
            if str(data.get('aid', '0')) != '0':
                raise ConfigurationError('Legacy VMess alterId is unsupported; request an AEAD link (aid=0)')
            transport = data.get('net', 'tcp') or 'tcp'
            params = {'type': transport, 'security': data.get('tls') or 'none'}
            for key in ('sni', 'alpn', 'fp', 'allowInsecure', 'verifyPeerCertByName'):
                if key in data and data[key] != '':
                    value = data[key]
                    params[key] = str(value).lower() if isinstance(value, bool) else value
            if transport == 'grpc':
                if data.get('path'):
                    params['serviceName'] = data['path']
                if data.get('host'):
                    params['authority'] = data['host']
                if data.get('type') not in (None, '', 'none', 'gun', 'multi'):
                    raise ConfigurationError('Unsupported VMess gRPC mode')
                params['mode'] = 'multi' if data.get('type') == 'multi' else 'gun'
            else:
                for key in ('host', 'path'):
                    if data.get(key):
                        params[key] = data[key]
                if data.get('type'):
                    params['headerType'] = data['type']
            if any(not isinstance(value, str) for value in params.values()):
                raise ConfigurationError('VMess transport fields must be text')
            name = data.get('ps') or server
            checked_text(name, 'profile name', 200)
            address = f'[{server}]' if ':' in server else server
            p = parse_vless(f'vless://{uid}@{address}:{port}?{urlencode(params)}#{quote(name)}')
            if p.security == 'reality':
                raise ConfigurationError('VMess does not support REALITY')
            return replace(p, original_uri=uri, protocol='vmess', cipher=cipher)
        if uri.startswith('trojan://'):
            parts = urlsplit(uri)
            credentials, sep, address = parts.netloc.rpartition('@')
            if not sep:
                raise ConfigurationError('Trojan requires a password and server')
            password = checked_text(unquote(credentials, errors='strict'), 'Trojan password')
            pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True,
                              encoding='utf-8', errors='strict', max_num_fields=32)
            if not any(k == 'security' for k, _ in pairs):
                pairs.append(('security', 'tls'))
            proxy = urlunsplit(('vless', DUMMY_ID + '@' + address, parts.path,
                               urlencode(pairs), parts.fragment))
            p = parse_vless(proxy)
            if p.flow or 'encryption' in p.parameters:
                raise ConfigurationError('VLESS flow/encryption options do not apply to Trojan')
            return replace(p, original_uri=uri, protocol='trojan', uuid='', password=password)
        if uri.startswith('ss://'):
            # SIP002 userinfo, plus the older base64(method:password@host:port) form.
            body, _, fragment = uri[5:].partition('#')
            if '@' not in body:
                if '?' in body:
                    raise ConfigurationError('Unsupported Shadowsocks link query')
                body = decode64(body)
                credentials, sep, endpoint = body.rpartition('@')
                if not sep:
                    raise ConfigurationError('Invalid Shadowsocks endpoint')
                body = quote(credentials, safe=':') + '@' + endpoint
            parts = urlsplit('ss://' + body)
            credentials, _, endpoint = parts.netloc.rpartition('@')
            if parts.query or parts.path not in ('', '/'):
                raise ConfigurationError('Shadowsocks plugins and extra query options are not supported')
            credentials = unquote(credentials, errors='strict')
            if ':' not in credentials:
                credentials = decode64(credentials)
            cipher, sep, password = credentials.partition(':')
            if not sep or cipher not in SS_CIPHERS:
                raise ConfigurationError('Unsupported Shadowsocks cipher; use AEAD or Shadowsocks 2022')
            checked_text(password, 'Shadowsocks password')
            p = parse_vless(f'vless://{DUMMY_ID}@{endpoint}#{fragment}')
            return replace(p, original_uri=uri, protocol='shadowsocks', uuid='',
                           cipher=cipher, password=password)
    except (ValueError, UnicodeError, TypeError) as exc:
        if isinstance(exc, ConfigurationError):
            raise
        raise ConfigurationError('Invalid VPN share link') from exc
    raise ConfigurationError('Supported links: vless://, vmess://, trojan:// and ss://')


def with_certificate_name(uri, name):
    p = parse_profile(uri)
    name = hostname(name.strip()) if name.strip() else ''
    if p.certificate_name == name:
        return p.original_uri
    if p.security != 'tls':
        raise ConfigurationError('A certificate name requires TLS')
    if p.protocol == 'vmess':
        data = vmess_data(p.original_uri)
        data.pop('verifyPeerCertByName', None)
        if name:
            data['verifyPeerCertByName'] = name
            if 'allowInsecure' in data:
                data['allowInsecure'] = False
        updated = 'vmess://' + base64.b64encode(json.dumps(data).encode()).decode()
    else:
        updated = replace_certificate_options(p.original_uri, name)
    parse_profile(updated)
    return updated
