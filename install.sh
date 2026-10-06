#!/usr/bin/env bash
# Standalone release bootstrap; published as the velum-install.sh release asset.
set -euo pipefail

download_release() {
    python3 - "$1" <<'PY'
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

REPOSITORY = 'https://github.com/rizhamhd/velum'
LATEST = 'https://api.github.com/repos/rizhamhd/velum/releases/latest'


def read_url(url, limit):
    if url != LATEST and not url.startswith(REPOSITORY + '/releases/download/v'):
        raise ValueError('Downloads must come from the official Velum repository')
    request = urllib.request.Request(url, headers={'User-Agent': 'Velum-installer'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Release download exceeds its size limit')
    return data


def download_release(directory):
    release = json.loads(read_url(LATEST, 1024 * 1024))
    if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
        raise ValueError('No published stable release is available')
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not re.fullmatch(r'v\d+\.\d+\.\d+-\d+', tag):
        raise ValueError('Invalid release version')
    version = tag[1:]
    name = f'velum-{version}-installer.tar.gz'
    base = f'{REPOSITORY}/releases/download/{tag}'
    print(f'Latest Velum: {version}. Downloading and verifying installer…', file=sys.stderr)
    checksums = read_url(base + '/SHA256SUMS', 16384).decode('ascii')
    matches = [parts[0] for line in checksums.splitlines()
               if len(parts := line.split()) == 2 and parts[1] == name]
    if len(matches) != 1 or not re.fullmatch(r'[a-fA-F0-9]{64}', matches[0]):
        raise ValueError('Missing or invalid installer checksum')
    data = read_url(base + '/' + name, 32 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != matches[0].lower():
        raise ValueError('Installer checksum mismatch; nothing was installed')
    prefix = f'velum-{version}'
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
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
    for required in ('scripts/install.sh', 'scripts/update.sh', 'PKGBUILD'):
        if not (project / required).is_file():
            raise ValueError('Release is missing its installer or update files')
    return project


if __name__ == '__main__':
    try:
        print(download_release(Path(sys.argv[1])))
    except Exception as exc:
        print(f'Cannot prepare Velum: {exc}', file=sys.stderr)
        sys.exit(1)
PY
}

bootstrap_main() (
    local mode=install bootstrap_dir project
    if (( $# > 1 )); then
        printf 'Usage: bash velum-install.sh [--check | --help]\n' >&2
        return 2
    fi
    case "${1:-}" in
        '') ;;
        --check) mode=check ;;
        --help|-h)
            printf 'Usage: bash velum-install.sh [--check | --help]\n'
            printf 'Install the latest Velum on CachyOS/Arch, or update an existing installation.\n'
            printf 'Run as your ordinary user. --check only downloads and verifies the installer.\n'
            return ;;
        *) printf 'Unknown option. Use --help for usage.\n' >&2; return 2 ;;
    esac
    if (( EUID == 0 )); then
        printf 'Run as your ordinary desktop user, without sudo.\n' >&2
        return 1
    fi
    if [[ ! -f /etc/arch-release ]] || ! command -v pacman >/dev/null; then
        printf 'Velum supports CachyOS and Arch Linux.\n' >&2
        return 1
    fi
    if [[ $mode == install && -x /usr/bin/velum-update ]]; then
        printf 'Velum is already installed. Checking for updates…\n'
        /usr/bin/velum-update
        return
    fi
    if ! command -v python3 >/dev/null; then
        if [[ $mode == check ]]; then
            printf 'Python is required for this check; nothing was installed.\n' >&2
            return 1
        fi
        printf 'Installing Python to verify and prepare the release…\n'
        sudo pacman -Syu --needed python
    fi
    bootstrap_dir=$(mktemp -d -t velum-install.XXXXXXXX)
    trap 'rm -rf -- "$bootstrap_dir"' EXIT
    project=$(download_release "$bootstrap_dir")
    if [[ $mode == check ]]; then
        printf 'Installer checksum and archive verified. No packages or system settings changed.\n'
    elif pacman -Q velum-vpn >/dev/null 2>&1; then
        bash "$project/scripts/update.sh"
    else
        printf 'Starting setup. Follow the package and DNS prompts in this terminal.\n'
        bash "$project/scripts/install.sh"
    fi
)

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then bootstrap_main "$@"; fi
