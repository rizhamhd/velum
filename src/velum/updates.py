"""User-requested updates from versioned releases in the official repository."""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

REPOSITORY = 'https://github.com/rizhamhd/velum'
LATEST = 'https://api.github.com/repos/rizhamhd/velum/releases/latest'


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+-\d+', value):
        raise ValueError('Unsupported release version')
    return tuple(int(part) for part in re.split(r'[.-]', value))


def read_url(url, limit):
    if url != LATEST and not url.startswith(REPOSITORY + '/releases/download/v'):
        raise ValueError('Updates must come from the official HTTPS repository')
    request = urllib.request.Request(url, headers={'User-Agent': 'Velum-updater',  # noqa: S310 - fixed HTTPS repository
                                                  'Accept': 'application/vnd.github+json' if url == LATEST else '*/*'})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS repository URLs
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError('Release download exceeds its size limit')
    return content


def installed_version():
    result = subprocess.run(['/usr/bin/pacman', '-Q', 'velum-vpn'], capture_output=True,
                            text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('Install Velum first with ./scripts/install.sh')
    fields = result.stdout.split()
    if len(fields) != 2 or fields[0] != 'velum-vpn':
        raise ValueError('Cannot read the installed Velum version')
    version_tuple(fields[1])
    return fields[1]


def release_status():
    current = installed_version()
    data = json.loads(read_url(LATEST, 1024 * 1024))
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('No published update is available')
    tag = data.get('tag_name', '')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('Invalid release tag')
    latest = tag[1:]
    available = version_tuple(latest) > version_tuple(current)
    return {'current': current, 'latest': latest, 'available': available,
            'tag': tag, 'url': f'{REPOSITORY}/releases/tag/{tag}'}


def verified_bundle(status):
    version_tuple(status['latest'])
    if status['tag'] != 'v' + status['latest']:
        raise ValueError('Invalid release tag')
    name = f"velum-{status['latest']}-installer.tar.gz"
    base = f"{REPOSITORY}/releases/download/{status['tag']}"
    checksums = read_url(base + '/SHA256SUMS', 16384).decode('ascii')
    matches = [parts[0] for line in checksums.splitlines()
               if len(parts := line.split()) == 2 and parts[1] == name]
    if len(matches) != 1 or not re.fullmatch(r'[a-fA-F0-9]{64}', matches[0]):
        raise ValueError('Missing or invalid installer checksum')
    bundle = read_url(base + '/' + name, 32 * 1024 * 1024)
    if hashlib.sha256(bundle).hexdigest() != matches[0].lower():
        raise ValueError('Installer checksum mismatch; nothing will be installed')
    return bundle


def unpack_bundle(bundle, directory, version):
    version_tuple(version)
    prefix = f'velum-{version}'
    total = 0
    with tarfile.open(fileobj=io.BytesIO(bundle), mode='r:gz') as archive:
        for index, member in enumerate(archive):
            parts = PurePosixPath(member.name)
            if (parts.is_absolute() or '..' in parts.parts or not parts.parts
                    or parts.parts[0] != prefix or not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe path or special file in release archive')
            total += member.size
            if member.size < 0 or index >= 5000 or total > 128 * 1024 * 1024:
                raise ValueError('Release archive exceeds extraction limits')
            destination = directory.joinpath(*parts.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, destination.open('xb') as target:
                    target.write(source.read())
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)
    project = directory / prefix
    if not (project / 'scripts/install.sh').is_file() or not (project / 'PKGBUILD').is_file():
        raise ValueError('Release is missing its installer or package recipe')
    return project


def update():
    if os.geteuid() == 0:
        raise RuntimeError('Run velum-update as your ordinary user, without sudo')
    status = release_status()
    if not status['available']:
        print(f"Velum {status['current']} is already up to date.")
        return
    print(f"Downloading verified installer for {status['latest']}…", flush=True)
    bundle = verified_bundle(status)
    with tempfile.TemporaryDirectory(prefix='velum-update-') as temporary:
        project = unpack_bundle(bundle, Path(temporary), status['latest'])
        print(f"Update Velum {status['current']} → {status['latest']}.")
        print('Saved profiles are kept. Completing the update will disconnect the VPN and restore normal networking.')
        if input('Install this update? [y/N] ').strip().lower() not in ('y', 'yes'):
            print('Update canceled; nothing was installed.')
            return
        subprocess.run(['/usr/bin/bash', str(project / 'scripts/install.sh')], cwd=project, check=True)
        # Use the newly installed recovery tool after downloads/install complete,
        # so an existing VPN remains available for fetching dependencies.
        subprocess.run(['sudo', '/usr/lib/velum/recover'], check=True)
        subprocess.run(['sudo', '/usr/bin/systemctl', 'start', 'velum.socket'], check=True)
        if installed_version() != status['latest']:
            raise RuntimeError('Installed version does not match the requested release')
    print('Update complete. Close and reopen Velum, then reconnect when ready.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true', help='Print available update information as JSON')
    group.add_argument('--interactive', action='store_true', help='Keep the updater terminal open after completion')
    args = parser.parse_args()
    result = 0
    try:
        if args.check:
            print(json.dumps(release_status()))
        else:
            update()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Update failed: {exc}', file=sys.stderr)
        result = 1
    if args.interactive:
        try:
            input('Press Enter to close this updater…')
        except (EOFError, KeyboardInterrupt):
            pass
    return result


if __name__ == '__main__':
    raise SystemExit(main())
