"""Validated VLESS links and shared transport options."""
import base64
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
    allow_insecure: bool = False
    header_type: str = 'none'
    service_name: str = ''
    authority: str = ''
    mode: str = ''
    flow: str = ''
    public_key: str = field(default='', repr=False)
    short_id: str = field(default='', repr=False)
    spider_x: str = '/'
    protocol: str = 'vless'
    password: str = field(default='', repr=False)
    cipher: str = ''
    alter_id: int = 0

    @property
    def notices(self):
        notices = []
        if self.transport == 'tcp' and self.header_type == 'none' and self.host:
            notices.append('Host is retained in the link but unused by plain TCP.')
        if self.allow_insecure:
            notices.append('Certificate verification is disabled by this link (allowInsecure).')
        return notices

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
               'allowInsecure', 'verifyPeerCertByName', 'headerType', 'serviceName',
               'authority', 'mode', 'flow', 'pbk', 'sid', 'spx'}
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
    transport = {'raw': 'tcp', 'websocket': 'ws', 'splithttp': 'xhttp'}.get(transport, transport)
    security = query.get('security', 'none')
    if transport not in ('tcp', 'ws', 'grpc', 'httpupgrade', 'xhttp'):
        raise ConfigurationError('Unsupported transport: use tcp, ws, grpc, httpupgrade or xhttp')
    if security not in ('none', 'tls', 'reality'):
        raise ConfigurationError('Unsupported security: use none, tls or reality')
    if query.get('encryption', 'none') != 'none':
        raise ConfigurationError('Unsupported VLESS encryption: use none')
    header = query.get('headerType', 'none')
    if header not in ('none', 'http') or (header != 'none' and transport != 'tcp'):
        raise ConfigurationError('HTTP headerType requires TCP transport')
    if transport == 'grpc' and {'host', 'path'} & query.keys():
        raise ConfigurationError('gRPC uses serviceName and authority, not host or path')
    if transport == 'tcp' and header == 'none' and query.get('path', '/') not in ('', '/'):
        raise ConfigurationError('A TCP path requires headerType=http')
    if security == 'none' and {'sni', 'fp', 'alpn', 'allowInsecure', 'verifyPeerCertByName'} & query.keys():
        raise ConfigurationError('Certificate options, sni, fp and alpn require TLS or REALITY')
    if security == 'reality' and {'alpn', 'allowInsecure', 'verifyPeerCertByName'} & query.keys():
        raise ConfigurationError('TLS certificate options and ALPN are not supported with REALITY')
    insecure = query.get('allowInsecure', '0').lower()
    if insecure not in ('0', '1', 'false', 'true'):
        raise ConfigurationError('allowInsecure must be 0, 1, false or true')
    allow_insecure = insecure in ('1', 'true')
    certificate_name = hostname(query['verifyPeerCertByName']) if 'verifyPeerCertByName' in query else ''
    if certificate_name == 'frommitm':
        raise ConfigurationError('A literal certificate hostname is required')
    if allow_insecure and certificate_name:
        raise ConfigurationError('Remove allowInsecure to use a verified certificate name')
    sni = hostname(query['sni']) if query.get('sni') else ''
    host = hostname(query['host']) if query.get('host') else ''
    path = query.get('path') or '/'
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
    service = query.get('serviceName', '')
    authority = hostname(query['authority']) if query.get('authority') else ''
    if transport != 'grpc' and {'serviceName', 'authority'} & query.keys():
        raise ConfigurationError('serviceName and authority require gRPC')
    if len(service) > 256 or (service and not re.fullmatch(r'[A-Za-z0-9_./-]+', service)):
        raise ConfigurationError('Invalid gRPC serviceName')
    mode = query.get('mode', '')
    if 'mode' in query and (transport not in ('grpc', 'xhttp') or
                           mode not in (('gun', 'multi') if transport == 'grpc' else
                                        ('auto', 'packet-up', 'stream-up', 'stream-one'))):
        raise ConfigurationError('Invalid transport mode')
    flow = query.get('flow', '')
    if flow not in ('', 'xtls-rprx-vision', 'xtls-rprx-vision-udp443') or (flow and
            (transport != 'tcp' or security not in ('tls', 'reality') or header != 'none')):
        raise ConfigurationError('Vision flow requires plain TCP with TLS or REALITY')
    public_key, short_id, spider_x = query.get('pbk', ''), query.get('sid', ''), query.get('spx', '/')
    if security != 'reality' and {'pbk', 'sid', 'spx'} & query.keys():
        raise ConfigurationError('pbk, sid and spx require REALITY')
    if security == 'reality':
        if transport not in ('tcp', 'grpc', 'xhttp') or header != 'none':
            raise ConfigurationError('REALITY requires plain TCP, gRPC or XHTTP')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', public_key) or len(base64.urlsafe_b64decode(public_key + '=')) != 32:
            raise ConfigurationError('REALITY requires a 32-byte base64url public key (pbk)')
        if not re.fullmatch(r'(?:[0-9a-fA-F]{2}){0,8}', short_id):
            raise ConfigurationError('REALITY sid must be even-length hex, up to 16 characters')
        if not sni or not spider_x.startswith('/') or len(spider_x) > 4096:
            raise ConfigurationError('REALITY requires an SNI and a valid spx path')
        fp = fp or 'chrome'
    return Vless(uri, uid, server, port, name, transport, security, 'none', sni,
                 alpn, fp, path, host, query, certificate_name=certificate_name,
                 allow_insecure=allow_insecure, header_type=header, service_name=service,
                 authority=authority, mode=mode, flow=flow, public_key=public_key,
                 short_id=short_id, spider_x=spider_x)


def with_certificate_name(uri: str, name: str) -> str:
    """Set the expected TLS identity, enabling verification when a name is supplied."""
    profile = parse_vless(uri)
    name = hostname(name.strip()) if name.strip() else ''
    if profile.certificate_name == name:
        return profile.original_uri
    if profile.security != 'tls':
        raise ConfigurationError('A certificate name requires TLS')
    updated = replace_certificate_options(profile.original_uri, name)
    parse_vless(updated)
    return updated


def replace_certificate_options(uri: str, name: str) -> str:
    """Rewrite TLS options on an already validated URL without re-encoding other fields."""
    body, fragment_sep, fragment = uri.partition('#')
    address, _, query = body.partition('?')
    parameters = []
    for part in query.split('&'):
        key = unquote_plus(part.partition('=')[0])
        if key == 'verifyPeerCertByName':
            continue
        if key == 'allowInsecure' and name:
            part = part.partition('=')[0] + '=0'
        if part:
            parameters.append(part)
    if name:
        parameters.append('verifyPeerCertByName=' + name)
    return address + ('?' + '&'.join(parameters) if parameters else '') + fragment_sep + fragment
