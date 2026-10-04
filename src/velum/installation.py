"""Installer checks and explicitly requested NetworkManager DNS setup."""
import argparse
import fcntl
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from velum.network.dns import ResolvedDNS
from velum.network.system import Runner


def check_engines():
    runner = Runner()
    xray = runner.run('/usr/bin/xray', 'version')
    if not xray.startswith('Xray '):
        raise RuntimeError('/usr/bin/xray is not the supported Xray engine')
    # tun2socks prints its version on stderr in some builds.
    result = subprocess.run(['/usr/bin/tun2socks', '-version'], capture_output=True,
                            text=True, check=True, timeout=10)
    if 'tun2socks' not in (result.stdout + result.stderr).lower():
        raise RuntimeError('Install xjasonlyu/tun2socks, not badvpn-tun2socks')
    help_result = subprocess.run(['/usr/bin/tun2socks', '-help'], capture_output=True,
                                 text=True, timeout=10)
    help_text = help_result.stdout + help_result.stderr
    if not all(option in help_text for option in ('-device', '-proxy', '-loglevel')):
        raise RuntimeError('Installed tun2socks does not support the required adapter options')
    print('Xray and tun2socks are installed at the required paths.')


def check_dns(path=Path('/etc/resolv.conf'), runner=None):
    ResolvedDNS(runner or Runner(), None, path).preflight()


def configure_dns(root=Path('/'), runner=None, verify=None):
    """Back up DNS files and restore them on a failed setup; never bounce links."""
    runner = runner or Runner()
    resolv = root / 'etc/resolv.conf'
    dropin = root / 'etc/NetworkManager/conf.d/90-velum-resolved.conf'
    if verify is None:
        def verify():
            check_dns(resolv, runner)
            runner.run('/usr/bin/getent', 'ahostsv4', 'archlinux.org')
    try:
        verify()
        print('DNS is already compatible; no changes needed.')
        return
    except Exception:
        print('Preparing requested DNS setup.')
    runner.run('/usr/bin/systemctl', 'is-active', '--quiet', 'NetworkManager')
    links = runner.json('/usr/bin/ip', '-j', 'link', 'show')
    if any(link['ifname'] == 'vpn0' for link in links):
        raise RuntimeError('Disconnect Velum before changing system DNS setup')
    active = runner.run('/usr/bin/systemctl', 'is-active', 'systemd-resolved', check=False).strip()
    enabled = runner.run('/usr/bin/systemctl', 'is-enabled', 'systemd-resolved', check=False).strip()
    if enabled not in ('enabled', 'disabled'):
        raise RuntimeError('Resolved has a custom/masked enablement state; configure DNS manually')
    backup_parent = root / 'var/backups'
    backup_parent.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='velum-dns-', dir=backup_parent))
    originals = []
    for path, name in ((resolv, 'resolv.conf'), (dropin, '90-velum-resolved.conf')):
        exists = path.exists() or path.is_symlink()
        if exists:
            shutil.copy2(path, backup / name, follow_symlinks=False)
        originals.append((path, backup / name if exists else None))
    print(f'DNS backup: {backup}')
    try:
        runner.run('/usr/bin/systemctl', 'enable', '--now', 'systemd-resolved')
        stub = root / 'run/systemd/resolve/stub-resolv.conf'
        if not stub.is_file():
            raise RuntimeError('systemd-resolved did not create its DNS stub file')
        dropin.parent.mkdir(parents=True, exist_ok=True)
        # Replacing files avoids following a pre-existing symlink in conf.d.
        replace_file(dropin, '[main]\ndns=systemd-resolved\nrc-manager=unmanaged\n')
        fd, temporary_name = tempfile.mkstemp(prefix='.velum-resolv-', dir=resolv.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            temporary.unlink()
            temporary.symlink_to('/run/systemd/resolve/stub-resolv.conf')
            os.replace(temporary, resolv)
        finally:
            temporary.unlink(missing_ok=True)
        runner.run('/usr/bin/nmcli', 'general', 'reload', 'conf', 'dns-full')
        verify()
    except Exception as exc:
        failures = []
        # Restore NM settings first; restore resolv.conf after NM's reload since
        # the previous DNS plugin may rewrite it during that reload.
        for path, saved in reversed(originals):
            try:
                path.unlink(missing_ok=True)
                if saved is not None:
                    shutil.copy2(saved, path, follow_symlinks=False)
                if path == dropin:
                    runner.run('/usr/bin/nmcli', 'general', 'reload', 'conf', 'dns-full')
            except Exception:
                failures.append(str(path))
        for restore, required in (('stop', active != 'active'), ('disable', enabled != 'enabled')):
            if required:
                try:
                    runner.run('/usr/bin/systemctl', restore, 'systemd-resolved')
                except Exception:
                    failures.append('systemd-resolved ' + restore)
        message = 'DNS setup failed; ' + ('rollback incomplete' if failures else 'original DNS setup restored')
        raise RuntimeError(f'{message}. Backup: {backup}') from exc
    print('NetworkManager and systemd-resolved DNS checks passed.')


def replace_file(path, text):
    fd, temporary = tempfile.mkstemp(prefix='.velum-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check-engines', action='store_true')
    group.add_argument('--check-dns', action='store_true')
    group.add_argument('--configure-dns', action='store_true')
    args = parser.parse_args()
    try:
        if args.check_engines:
            check_engines()
        elif args.check_dns:
            check_dns()
        else:
            if os.geteuid() != 0:
                raise RuntimeError('DNS setup requires administrator access')
            fd = os.open('/run/velum-dns-setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                configure_dns()
            finally:
                os.close(fd)
    except Exception as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
