import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = (PROJECT / 'install.sh').read_text()
PYTHON = SCRIPT.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
BOOTSTRAP = {'__name__': 'bootstrap_test'}
exec(compile(PYTHON, 'install.sh:embedded-python', 'exec'), BOOTSTRAP)  # noqa: S102 - trusted repository code


def bundle(extra=None, missing=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for filename in ('scripts/install.sh', 'scripts/update.sh', 'PKGBUILD'):
            if missing and filename == 'scripts/install.sh':
                continue
            info = tarfile.TarInfo('velum-0.1.0-11/' + filename)
            info.mode, info.size = 0o755, 5
            archive.addfile(info, io.BytesIO(b'exit\n'))
        if extra:
            archive.addfile(extra)
    return output.getvalue()


class BootstrapDownloadTests(unittest.TestCase):
    def prepare(self, directory, data=None, checksums=None, release=None):
        data = bundle() if data is None else data
        checksums = (hashlib.sha256(data).hexdigest() + '  velum-0.1.0-11-installer.tar.gz\n'
                     if checksums is None else checksums)
        reader = Mock(side_effect=[json.dumps(release or {'tag_name': 'v0.1.0-11'}).encode(),
                                   checksums.encode(), data])
        with patch.dict(BOOTSTRAP, read_url=reader):
            project = BOOTSTRAP['download_release'](Path(directory))
        return project, reader

    def test_pins_release_and_extracts_only_verified_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            project, reader = self.prepare(directory)
            self.assertEqual((project / 'scripts/install.sh').read_bytes(), b'exit\n')
            self.assertEqual((project / 'scripts/install.sh').stat().st_mode & 0o777, 0o755)
            self.assertEqual(reader.call_args_list[1].args[0],
                             'https://github.com/rizhamhd/velum/releases/download/v0.1.0-11/SHA256SUMS')
            self.assertIn('/v0.1.0-11/velum-0.1.0-11-installer.tar.gz', reader.call_args.args[0])

    def test_missing_duplicate_and_wrong_checksums_stop_before_extraction(self):
        for checksums in ('', 'invalid  velum-0.1.0-11-installer.tar.gz',
                          '0' * 64 + '  velum-0.1.0-11-installer.tar.gz\n',
                          ('0' * 64 + '  velum-0.1.0-11-installer.tar.gz\n') * 2):
            with self.subTest(checksums=checksums), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    self.prepare(d, checksums=checksums)
                self.assertEqual(list(Path(d).iterdir()), [])

    def test_invalid_release_metadata(self):
        for release in ({'tag_name': 'v../../escape'}, {'tag_name': None},
                        {'tag_name': 'v0.1.0-11', 'draft': True},
                        {'tag_name': 'v0.1.0-11', 'prerelease': True}, ['v0.1.0-11']):
            with self.subTest(release=release), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    self.prepare(d, release=release)

    def test_unsafe_archives_and_missing_installer_are_rejected(self):
        for name, kind in (('../escape', tarfile.REGTYPE), ('/escape', tarfile.REGTYPE),
                           ('wrong-prefix/file', tarfile.REGTYPE),
                           ('velum-0.1.0-11/link', tarfile.SYMTYPE),
                           ('velum-0.1.0-11/hardlink', tarfile.LNKTYPE),
                           ('velum-0.1.0-11/device', tarfile.CHRTYPE)):
            member = tarfile.TarInfo(name)
            member.type, member.linkname = kind, '/etc'
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    self.prepare(d, data=bundle(member))
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(ValueError, 'missing'):
            self.prepare(d, data=bundle(missing=True))

    def test_download_limits_and_network_errors_propagate(self):
        reader = BOOTSTRAP['read_url']
        with self.assertRaisesRegex(ValueError, 'official'):
            reader('file:///etc/passwd', 100)
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'12345')):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                reader(BOOTSTRAP['LATEST'], 4)
        with patch('urllib.request.urlopen', side_effect=OSError('offline')):
            with self.assertRaisesRegex(OSError, 'offline'):
                reader(BOOTSTRAP['LATEST'], 100)


@unittest.skipIf(os.geteuid() == 0, 'Installer intentionally refuses root')
class BootstrapShellTests(unittest.TestCase):
    def shell(self, args='', installed=False, updater=False, download_ok=True, arch=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tmp').mkdir()
            if arch:
                (root / 'arch-release').touch()
            script = root / 'bootstrap.sh'
            script.write_text(SCRIPT.replace('/etc/arch-release', str(root / 'arch-release'))
                              .replace('/usr/bin/velum-update', str(root / 'velum-update')))
            if updater:
                (root / 'velum-update').write_text('#!/bin/sh\necho UPDATE_STARTED\nexit 17\n')
                (root / 'velum-update').chmod(0o755)
            project = root / 'release'
            (project / 'scripts').mkdir(parents=True)
            (project / 'scripts/install.sh').write_text('read -r answer\necho "FRESH_INSTALL:$answer"\n')
            (project / 'scripts/update.sh').write_text('echo LEGACY_UPDATE\n')
            prelude = '''source "$BOOTSTRAP_SCRIPT"
pacman() { return "$MOCK_INSTALLED"; }
sudo() { echo UNEXPECTED_SUDO; return 99; }
download_release() {
    printf '%s\\n' partial > "$1/partial"
    if [[ $MOCK_DOWNLOAD != 0 ]]; then return 42; fi
    printf '%s\\n' "$MOCK_PROJECT"
}
bootstrap_main '''
            env = {**os.environ, 'BOOTSTRAP_SCRIPT': str(script), 'TMPDIR': str(root / 'tmp'),
                   'MOCK_INSTALLED': '0' if installed else '1', 'MOCK_PROJECT': str(project),
                   'MOCK_DOWNLOAD': '0' if download_ok else '1'}
            result = subprocess.run(['bash', '-c', prelude + args], input='yes\n',
                                    text=True, capture_output=True, env=env)
            self.assertEqual(list((root / 'tmp').iterdir()), [], 'Temporary download files leaked')
            self.assertNotIn('UNEXPECTED_SUDO', result.stdout)
            return result

    def test_fresh_install_preserves_interactive_input(self):
        result = self.shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('FRESH_INSTALL:yes', result.stdout)

    def test_existing_installs_use_updater_and_preserve_failures(self):
        result = self.shell(installed=True, updater=True)
        self.assertEqual(result.returncode, 17)
        self.assertIn('UPDATE_STARTED', result.stdout)
        self.assertNotIn('FRESH_INSTALL', result.stdout)
        result = self.shell(installed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LEGACY_UPDATE', result.stdout)

    def test_check_mode_does_not_install_or_update(self):
        result = self.shell('--check', installed=True, updater=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No packages or system settings changed', result.stdout)
        self.assertNotIn('UPDATE_STARTED', result.stdout)
        self.assertNotIn('FRESH_INSTALL', result.stdout)

    def test_failed_download_and_unsupported_system_never_install(self):
        for result in (self.shell(download_ok=False), self.shell(arch=False),
                       self.shell('--unknown'), self.shell('--check extra')):
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('FRESH_INSTALL', result.stdout)
            self.assertNotIn('UPDATE_STARTED', result.stdout)
