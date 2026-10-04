import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from velum import updates


def bundle(extra=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name in ('velum-0.1.0-9/scripts/install.sh', 'velum-0.1.0-9/PKGBUILD'):
            info = tarfile.TarInfo(name)
            info.mode, info.size = 0o755, 4
            archive.addfile(info, io.BytesIO(b'test'))
        if extra:
            archive.addfile(extra)
    return output.getvalue()


class UpdateTests(unittest.TestCase):
    def status(self):
        return {'current': '0.1.0-8', 'latest': '0.1.0-9', 'tag': 'v0.1.0-9', 'available': True}

    def test_release_comparison_never_downgrades_or_accepts_unexpected_tags(self):
        with patch.object(updates, 'installed_version', return_value='0.1.0-9'):
            for tag, expected in (('v0.1.0-8', False), ('v0.1.0-9', False), ('v0.1.0-10', True)):
                with patch.object(updates, 'read_url', return_value=json.dumps({'tag_name': tag}).encode()):
                    self.assertEqual(updates.release_status()['available'], expected)
            for tag in ('../file', 'v0.1.0-9;command', 'v../../something', None):
                with patch.object(updates, 'read_url', return_value=json.dumps({'tag_name': tag}).encode()):
                    with self.assertRaises(ValueError):
                        updates.release_status()

    def test_download_requires_matching_checksum(self):
        data = bundle()
        checksum = hashlib.sha256(data).hexdigest()
        for digest, success in ((checksum, True), ('0' * 64, False)):
            with patch.object(updates, 'read_url', side_effect=[
                f'{digest}  velum-0.1.0-9-installer.tar.gz\n'.encode(), data,
            ]):
                if success:
                    self.assertEqual(updates.verified_bundle(self.status()), data)
                else:
                    with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                        updates.verified_bundle(self.status())

    def test_archive_preserves_installer_and_rejects_traversal_links_and_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            project = updates.unpack_bundle(bundle(), Path(directory), '0.1.0-9')
            self.assertEqual((project / 'scripts/install.sh').read_bytes(), b'test')
            self.assertTrue((project / 'scripts/install.sh').stat().st_mode & 0o111)
        for name, kind in (('velum-0.1.0-9/../../outside', tarfile.REGTYPE),
                           ('/outside', tarfile.REGTYPE),
                           ('velum-0.1.0-9/link', tarfile.SYMTYPE),
                           ('velum-0.1.0-9/device', tarfile.CHRTYPE)):
            member = tarfile.TarInfo(name)
            member.type = kind
            member.linkname = '/etc'
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    updates.unpack_bundle(bundle(member), Path(directory), '0.1.0-9')

    @patch('velum.updates.os.geteuid', return_value=1000)
    def test_cancel_does_not_install_or_disconnect(self, uid):
        with patch.object(updates, 'release_status', return_value=self.status()), \
                patch.object(updates, 'verified_bundle', return_value=bundle()), \
                patch('builtins.input', return_value='n'), patch.object(updates.subprocess, 'run') as run:
            updates.update()
            run.assert_not_called()

    @patch('velum.updates.os.geteuid', return_value=1000)
    def test_install_precedes_recovery_and_failure_does_not_report_success(self, uid):
        with patch.object(updates, 'release_status', return_value=self.status()), \
                patch.object(updates, 'verified_bundle', return_value=bundle()), \
                patch.object(updates, 'installed_version', return_value='0.1.0-9'), \
                patch('builtins.input', return_value='y'), patch.object(updates.subprocess, 'run') as run:
            updates.update()
            calls = [call.args[0] for call in run.call_args_list]
            self.assertTrue(calls[0][1].endswith('/scripts/install.sh'))
            self.assertEqual(calls[1], ['sudo', '/usr/lib/velum/recover'])
            self.assertEqual(calls[2], ['sudo', '/usr/bin/systemctl', 'start', 'velum.socket'])
            run.reset_mock()
            run.side_effect = subprocess.CalledProcessError(1, 'installer')
            with self.assertRaises(subprocess.CalledProcessError):
                updates.update()
            run.assert_called_once()

    def test_root_and_external_sources_are_rejected(self):
        with patch('velum.updates.os.geteuid', return_value=0), patch.object(updates, 'release_status') as status:
            with self.assertRaisesRegex(RuntimeError, 'ordinary user'):
                updates.update()
            status.assert_not_called()
        with self.assertRaises(ValueError):
            updates.read_url('file:///etc/passwd', 100)

    def test_display_version_matches_package_release(self):
        import re

        from velum.version import VERSION

        recipe = (Path(__file__).resolve().parents[1] / 'PKGBUILD').read_text()
        package_version = re.search(r'^pkgver=(.+)$', recipe, re.M)[1]
        release = re.search(r'^pkgrel=(.+)$', recipe, re.M)[1]
        self.assertEqual(VERSION, f'{package_version}-{release}')
