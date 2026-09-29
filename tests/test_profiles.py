import json
import tempfile
import unittest
from pathlib import Path

from test_vless import BASE

from velum.config.profiles import ProfileStore, migrate


class ProfileTests(unittest.TestCase):
    def test_crud(self):
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            p = store.save(BASE)
            store.save(BASE, 'Renamed', p['id'])
            self.assertEqual(store.list()[0]['name'], 'Renamed')
            copy = store.duplicate(p['id'])
            self.assertNotEqual(copy['id'], p['id'])
            exported = Path(d) / 'export.json'
            store.export(p['id'], exported)
            self.assertEqual(exported.stat().st_mode & 0o777, 0o600)
            store.delete(p['id'])
            self.assertEqual(len(store.list()), 1)
            store.import_file(exported)
            self.assertEqual(len(store.list()), 2)
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            self.assertIn('normalized', json.loads(store.path.read_text())['profiles'][0])

    def test_migration(self):
        self.assertEqual(migrate({'version': 0, 'uris': [BASE]})['version'], 1)
        with self.assertRaises(ValueError):
            migrate({'version': 99})

    def test_import_is_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(Path(d) / 'profiles.json')
            source = Path(d) / 'import.json'
            source.write_text(json.dumps({'version': 1, 'profiles': [
                {'uri': BASE, 'name': 'Valid'}, {'uri': BASE, 'name': ''}]}))
            with self.assertRaises(ValueError):
                store.import_file(source)
            self.assertEqual(store.list(), [])
