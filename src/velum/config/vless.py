"""Strict VLESS parsing. No unknown option is silently discarded."""
import ipaddress
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qsl, unquote, unquote_plus, urlsplit
from uuid import UUID


class ConfigurationError(ValueError):
    pass


def hostname(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        value = value.encode('idna').decode('ascii')
    except UnicodeError as exc:
        raise ConfigurationError('Invalid hostname') from exc
    if len(value) > 253 or not all(
        re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
        for part in value.rstrip('.').split('.')
    ):
        raise ConfigurationError('Invalid hostname')
    return value.lower()


@dataclass(frozen=True)
class Vless:
    original_uri: str = field(repr=False)
    uuid: str = field(repr=False)
    server: str
    port: int
    name: str
    transport: str = 'tcp'
    security: str = 'none'
    encryption: str = 'none'
    sni: str = ''
    alpn: tuple[str, ...] = ()
    fingerprint: str = ''
    path: str = '/'
    host: str = ''
    parameters: dict[str, str] = field(default_factory=dict, repr=False)
    certificate_name: str = ''

    def normalized(self):
        result = asdict(self)
        result.pop('original_uri')
        return result


def parse_vless(uri: str) -> Vless:
    if not isinstance(uri, str) or len(uri) > 16384:
        raise ConfigurationError('VLESS URL must be text, at most 16 KiB')
    uri = uri.strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in uri):
        raise ConfigurationError('Control characters are not allowed')
    if re.search(r'%(?![0-9a-fA-F]{2})', uri):
        raise ConfigurationError('Invalid percent escape in VLESS URL')
    try:
        parts = urlsplit(uri)
        if parts.scheme != 'vless' or not parts.hostname or not parts.username:
            raise ConfigurationError('Expected vless://UUID@server:port')
        if parts.password is not None or parts.path not in ('', '/'):
            raise ConfigurationError('Unexpected password or URL path')
        uid = str(UUID(parts.username))
        port = parts.port
        if port is None or not 1 <= port <= 65535:
            raise ConfigurationError('Port must be between 1 and 65535')
        server = hostname(parts.hostname)
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict', max_num_fields=32)
        name = unquote(parts.fragment, errors='strict') or server
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ConfigurationError):
            raise
        raise ConfigurationError('Invalid VLESS URL, UUID, port, or query encoding') from exc
    allowed = {'encryption', 'security', 'sni', 'alpn', 'fp', 'type', 'path', 'host',
               'allowInsecure', 'verifyPeerCertByName'}
    query = {}
    for key, value in pairs:
        if key not in allowed:
            # Do not echo arbitrary attacker-controlled secrets as parameter names.
            label = key if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,40}', key) else '[invalid name]'
            raise ConfigurationError(f'Unsupported VLESS parameter: {label}')
        if key in query:
            raise ConfigurationError(f'Duplicate VLESS parameter: {key}')
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ConfigurationError(f'Control character in parameter: {key}')
        query[key] = value
    transport = query.get('type', 'tcp')
    security = query.get('security', 'none')
    if transport not in ('tcp', 'ws'):
        raise ConfigurationError('Unsupported transport: use tcp or ws')
    if security not in ('none', 'tls'):
        raise ConfigurationError('Unsupported security: use none or tls')
    if query.get('encryption', 'none') != 'none':
        raise ConfigurationError('Unsupported VLESS encryption: use none')
    if transport != 'ws' and {'host', 'path'} & query.keys():
        raise ConfigurationError('host and path require WebSocket transport')
    if security != 'tls' and {'sni', 'fp', 'alpn', 'allowInsecure', 'verifyPeerCertByName'} & query.keys():
        raise ConfigurationError('Certificate options, sni, fp and alpn require TLS')
    insecure = query.get('allowInsecure', '0').lower()
    if insecure not in ('0', '1', 'false', 'true'):
        raise ConfigurationError('allowInsecure must be 0, 1, false or true')
    if insecure in ('1', 'true'):
        raise ConfigurationError('This Xray backend no longer supports allowInsecure. '
                                 'Use a provider certificate name (verifyPeerCertByName) while keeping your SNI.')
    certificate_name = hostname(query['verifyPeerCertByName']) if 'verifyPeerCertByName' in query else ''
    if certificate_name == 'frommitm':
        raise ConfigurationError('A literal certificate hostname is required')
    sni = hostname(query['sni']) if query.get('sni') else ''
    host = hostname(query['host']) if query.get('host') else ''
    path = query.get('path', '/')
    if not path.startswith('/') or len(path) > 4096:
        raise ConfigurationError('WebSocket path must begin with / and be at most 4096 characters')
    fp = query.get('fp', '')
    if fp not in ('', 'chrome', 'firefox', 'safari', 'ios', 'android', 'edge', '360', 'qq', 'random', 'randomized'):
        raise ConfigurationError('Unsupported TLS fingerprint')
    alpn = tuple(query['alpn'].split(',')) if 'alpn' in query else ()
    if any(not re.fullmatch(r'[A-Za-z0-9./-]{1,32}', p) for p in alpn):
        raise ConfigurationError('Invalid ALPN value')
    if len(name) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ConfigurationError('Profile name must be printable and at most 200 characters')
    return Vless(uri, uid, server, port, name, transport, security, 'none', sni,
                 alpn, fp, path, host, query, certificate_name=certificate_name)


def with_certificate_name(uri: str, name: str) -> str:
    """Change only this TLS option, preserving the other URL fields and encoding."""
    profile = parse_vless(uri)
    name = hostname(name.strip()) if name.strip() else ''
    if profile.certificate_name == name:
        return profile.original_uri
    if profile.security != 'tls':
        raise ConfigurationError('A certificate name requires TLS')
    body, fragment_sep, fragment = profile.original_uri.partition('#')
    address, _, query = body.partition('?')
    parameters = [part for part in query.split('&')
                  if unquote_plus(part.partition('=')[0]) != 'verifyPeerCertByName']
    if name:
        parameters.append('verifyPeerCertByName=' + name)
    updated = address + '?' + '&'.join(parameters) + fragment_sep + fragment
    parse_vless(updated)
    return updated
