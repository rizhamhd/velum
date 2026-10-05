import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from velum.config.links import parse_profile
from velum.config.vless import ConfigurationError
from velum.security.files import private_write
from velum.vpn.configuration import generate_engine_config


def migrate(data):
    if data.get('version') == 1:
        return data
    if data.get('version') == 0:
        return {'version': 1, 'profiles': [
            {'id': str(uuid4()), 'name': parse_profile(uri).name, 'uri': uri,
             'normalized': parse_profile(uri).normalized()} for uri in data['uris']]}
    raise ConfigurationError('Unsupported profile database version')


def profile_record(uri, name=None, profile_id=None):
    parsed = parse_profile(uri)
    generate_engine_config(parsed)
    if name is not None and not isinstance(name, str):
        raise ConfigurationError('Profile name must be text')
    name = parsed.name if name is None else name.strip()
    if not name or len(name) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ConfigurationError('Name must contain 1–200 printable characters')
    return {'id': profile_id or str(uuid4()), 'name': name, 'uri': uri,
            'normalized': parsed.normalized()}


class ProfileStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def locked(self):
        fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def list(self):
        if not self.path.exists():
            return []
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            data = migrate(json.load(stream))
        for item in data['profiles']:
            parse_profile(item['uri'])
        return data['profiles']

    def save(self, uri, name=None, profile_id=None):
        record = profile_record(uri, name, profile_id)
        with self.locked():
            records = self.list()
            if profile_id and not any(p['id'] == profile_id for p in records):
                raise ConfigurationError('Profile no longer exists')
            records = [p for p in records if p['id'] != record['id']] + [record]
            private_write(self.path, {'version': 1, 'profiles': records})
        return record

    def delete(self, profile_id):
        with self.locked():
            private_write(self.path, {'version': 1, 'profiles': [
                p for p in self.list() if p['id'] != profile_id]})

    def duplicate(self, profile_id):
        item = next(p for p in self.list() if p['id'] == profile_id)
        return self.save(item['uri'], item['name'][:193] + ' (copy)')

    def export(self, profile_id, path):
        item = next(p for p in self.list() if p['id'] == profile_id)
        private_write(Path(path), {'version': 1, 'profiles': [item]})

    def import_file(self, path):
        if Path(path).stat().st_size > 1024 * 1024:
            raise ConfigurationError('Profile import exceeds the 1 MiB size limit')
        data = migrate(json.loads(Path(path).read_text()))
        records = [profile_record(item['uri'], item.get('name')) for item in data['profiles']]
        with self.locked():
            private_write(self.path, {'version': 1, 'profiles': self.list() + records})
        return records
