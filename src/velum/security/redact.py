import re

_UUID = re.compile(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b')
_URI = re.compile(r'vless://[^\s\"\'<>]+', re.I)
_SECRET = re.compile(r'(?i)([\"\']?(?:password|token|privateKey|authorization|uuid|id)[\"\']?\s*[:=]\s*)[^,\s}]+')


def redact(text):
    text = _URI.sub('[VLESS URL redacted]', str(text))
    text = _UUID.sub('[UUID redacted]', text)
    return _SECRET.sub(r'\1[redacted]', text)
