import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from velum.installation import configure_dns

PROJECT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def shell(self, body, installed=(), available=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'commands'
            mock = root / 'pacman'
            mock.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == '-T':
    sys.exit(0 if args[1] in json.loads(os.environ['TEST_INSTALLED']) else 127)
if args[0] == '-Si':
    sys.exit(0 if args[1] in json.loads(os.environ['TEST_AVAILABLE']) else 1)
with Path(os.environ['TEST_LOG']).open('a') as log:
    log.write('pacman ' + ' '.join(args) + '\\n')
''')
            mock.chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'TEST_LOG': str(log), 'TEST_INSTALLED': json.dumps(installed),
                   'TEST_AVAILABLE': json.dumps(available)}
            prelude = '''source scripts/install.sh
sudo() { "$@"; }
install_aur() { printf 'aur %s\n' "$1" >> "$TEST_LOG"; }
'''
            result = subprocess.run(['bash', '-c', prelude + body], cwd=PROJECT,
                                    env=env, text=True, capture_output=True)
            commands = log.read_text().splitlines() if log.exists() else []
            return result, commands

    def test_existing_engines_are_never_reinstalled(self):
        for packages in (('xray', 'tun2socks'), ('xray', 'xray-bin', 'tun2socks-bin')):
            result, commands = self.shell(
                'ensure_engine Xray xray-bin xray xray-bin\n'
                'ensure_engine tun2socks tun2socks-bin tun2socks tun2socks-bin', installed=packages)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(commands, [])
            self.assertIn('Using installed', result.stdout)

    def test_fresh_install_prefers_repositories_and_falls_back_without_aur_helper(self):
        body = ('ensure_engine Xray xray-bin xray xray-bin\n'
                'ensure_engine tun2socks tun2socks-bin tun2socks tun2socks-bin')
        result, commands = self.shell(body, available=('xray',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, ['pacman -S --needed xray', 'aur tun2socks-bin'])
        result, commands = self.shell(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, ['aur xray-bin', 'aur tun2socks-bin'])

    def test_failed_download_stops_before_installing_next_engine(self):
        result, commands = self.shell('install_aur() { return 42; }\n'
                                     'ensure_engine Xray xray-bin xray xray-bin\n'
                                     'ensure_engine tun2socks tun2socks-bin tun2socks tun2socks-bin')
        self.assertEqual(result.returncode, 42)
        self.assertEqual(commands, [])

    def test_package_requires_actual_installed_adapter_provider(self):
        for packages, expected in ((('tun2socks',), 'tun2socks'),
                                   (('tun2socks-bin',), 'tun2socks-bin'), ((), 'tun2socks-bin')):
            result, _ = self.shell('source PKGBUILD\nprintf "%s\\n" "${depends[@]}"', installed=packages)
            self.assertEqual(result.returncode, 0, result.stderr)
            dependencies = result.stdout.splitlines()
            self.assertIn('xray', dependencies)
            self.assertIn(expected, dependencies)

    def test_aur_fallback_builds_without_sudo_or_an_aur_helper(self):
        result, commands = self.shell('''source scripts/install.sh
git() { printf 'clone %s\\n' "$5" >> "$TEST_LOG"; mkdir -p -- "${@: -1}"; }
makepkg() { printf 'build %s\\n' "$*" >> "$TEST_LOG"; }
sudo() { return 99; }
install_aur xray-bin
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, ['clone https://aur.archlinux.org/xray-bin.git',
                                    'build --syncdeps --install --needed'])

    def test_existing_desktop_agent_is_reused(self):
        for agent in ('polkit-kde-agent', 'gnome-shell', 'hyprpolkitagent'):
            result, commands = self.shell('agent_installed', installed=(agent,))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(commands, [])
        result, _ = self.shell('agent_installed')
        self.assertNotEqual(result.returncode, 0)


class DNSSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.resolv = self.root / 'etc/resolv.conf'
        self.dropin = self.root / 'etc/NetworkManager/conf.d/90-velum-resolved.conf'
        self.dropin.parent.mkdir(parents=True)
        self.resolv.write_text('nameserver 192.0.2.53\n')
        self.dropin.write_text('[main]\ndns=default\n')
        stub = self.root / 'run/systemd/resolve/stub-resolv.conf'
        stub.parent.mkdir(parents=True)
        stub.write_text('nameserver 127.0.0.53\n')
        self.runner = Mock()
        self.runner.json.return_value = []
        self.runner.run.side_effect = lambda *args, **kw: (
            'disabled' if 'is-enabled' in args else 'inactive' if 'is-active' in args else '')

    def test_compatible_dns_is_not_changed(self):
        configure_dns(self.root, self.runner, Mock())
        self.runner.run.assert_not_called()
        self.assertEqual(self.resolv.read_text(), 'nameserver 192.0.2.53\n')

    def test_setup_backs_up_files_and_does_not_restart_networkmanager(self):
        verify = Mock(side_effect=[RuntimeError('not ready'), None])
        configure_dns(self.root, self.runner, verify)
        self.assertTrue(self.resolv.is_symlink())
        self.assertEqual(os.readlink(self.resolv), '/run/systemd/resolve/stub-resolv.conf')
        self.assertIn('dns=systemd-resolved', self.dropin.read_text())
        backup = next((self.root / 'var/backups').iterdir())
        self.assertEqual((backup / 'resolv.conf').read_text(), 'nameserver 192.0.2.53\n')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertFalse(any('restart' in call.args for call in self.runner.run.call_args_list))
        self.assertEqual(verify.call_count, 2)

    def test_failed_verification_restores_dns_files_and_resolved_state(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                self.resolv.unlink()
                if symlink:
                    self.resolv.symlink_to('/run/previous/resolv.conf')
                else:
                    self.resolv.write_text('nameserver 192.0.2.53\n')
                verify = Mock(side_effect=RuntimeError('DNS failed'))
                with self.assertRaisesRegex(RuntimeError, 'original DNS setup restored'):
                    configure_dns(self.root, self.runner, verify)
                if symlink:
                    self.assertEqual(os.readlink(self.resolv), '/run/previous/resolv.conf')
                else:
                    self.assertEqual(self.resolv.read_text(), 'nameserver 192.0.2.53\n')
                self.assertEqual(self.dropin.read_text(), '[main]\ndns=default\n')
                self.runner.run.assert_any_call('/usr/bin/systemctl', 'stop', 'systemd-resolved')
                self.runner.run.assert_any_call('/usr/bin/systemctl', 'disable', 'systemd-resolved')

    def test_active_vpn_prevents_dns_migration(self):
        self.runner.json.return_value = [{'ifname': 'vpn0'}]
        with self.assertRaisesRegex(RuntimeError, 'Disconnect Velum'):
            configure_dns(self.root, self.runner, Mock(side_effect=RuntimeError('not ready')))
        self.assertFalse((self.root / 'var/backups').exists())

    def test_failed_setup_removes_new_files_and_keeps_existing_resolved_service(self):
        self.dropin.unlink()
        self.runner.run.side_effect = lambda *args, **kw: (
            'enabled' if 'is-enabled' in args else 'active' if 'is-active' in args else '')
        with self.assertRaisesRegex(RuntimeError, 'original DNS setup restored'):
            configure_dns(self.root, self.runner, Mock(side_effect=RuntimeError('DNS failed')))
        self.assertFalse(self.dropin.exists())
        self.assertEqual(self.resolv.read_text(), 'nameserver 192.0.2.53\n')
        self.assertFalse(any('stop' in call.args or 'disable' in call.args
                             for call in self.runner.run.call_args_list))
