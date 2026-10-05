#!/usr/bin/env bash
# First-time CachyOS/Arch installation. Package builds always run as the user.
set -euo pipefail

installed() { pacman -T "$1" >/dev/null 2>&1; }

install_aur() (
    local package=$1 build_dir
    build_dir=$(mktemp -d -t velum-build.XXXXXXXX)
    trap 'rm -rf -- "$build_dir"' EXIT
    printf 'Installing %s from the AUR (built as your ordinary user).\n' "$package"
    git clone --depth 1 -- "https://aur.archlinux.org/$package.git" "$build_dir/$package"
    cd "$build_dir/$package"
    makepkg --syncdeps --install --needed
)

ensure_engine() {
    local label=$1 fallback=$2 candidate
    shift 2
    for candidate in "$@"; do
        if installed "$candidate"; then
            printf 'Using installed %s package: %s\n' "$label" "$candidate"
            return
        fi
    done
    for candidate in "$@"; do
        if pacman -Si "$candidate" >/dev/null 2>&1; then
            sudo pacman -S --needed "$candidate"
            return
        fi
    done
    install_aur "$fallback"
}

agent_installed() {
    local agent
    for agent in polkit-kde-agent polkit-gnome lxqt-policykit mate-polkit \
                 hyprpolkitagent cosmic-polkit gnome-shell; do
        if installed "$agent"; then return 0; fi
    done
    return 1
}

configure_dns() {
    if /usr/bin/python -I -m velum.installation --check-dns; then
        sudo systemctl enable --now systemd-resolved
        return
    fi
    printf '\nVelum needs the systemd-resolved DNS stub.\n'
    printf 'Configure NetworkManager/resolved now? DNS files will be backed up; failed setup is rolled back. [Y/n] '
    local answer
    read -r answer || { printf '\nDNS setup needs an interactive terminal.\n' >&2; return 1; }
    case "$answer" in
        ''|y|Y|yes|YES) sudo /usr/bin/python -I -m velum.installation --configure-dns ;;
        *) printf 'Packages installed, but DNS setup is incomplete. See README: DNS prerequisite.\n' >&2; return 1 ;;
    esac
}

main() {
    if (( EUID == 0 )); then
        printf 'Run ./scripts/install.sh as your ordinary user, without sudo.\n' >&2
        return 1
    fi
    if (( $# != 0 )) || [[ ! -f /etc/arch-release ]] || ! command -v pacman >/dev/null; then
        printf 'This installer takes no arguments and supports CachyOS/Arch Linux.\n' >&2
        return 1
    fi
    local project agent_added=false
    project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
    cd "$project"
    local dependencies=(git base-devel python pyside6 python-build python-installer
        python-setuptools ruff iproute2 nftables systemd polkit curl procps-ng
        networkmanager unzip)
    if ! agent_installed; then
        dependencies+=(polkit-kde-agent)
        agent_added=true
    fi
    printf 'Updating Arch packages and installing missing dependencies (up-to-date packages are skipped).\n'
    sudo pacman -Syu --needed "${dependencies[@]}"
    ensure_engine Xray xray-bin xray xray-bin
    ensure_engine sing-box sing-box-bin sing-box sing-box-bin
    ensure_engine tun2socks tun2socks-bin tun2socks tun2socks-bin
    PYTHONPATH="$project/src" /usr/bin/python -m velum.installation --check-engines
    makepkg --force --syncdeps --install --needed
    configure_dns
    sudo systemctl enable --now velum.socket
    systemctl is-active --quiet velum.socket
    if $agent_added; then
        systemctl --user daemon-reload
        if ! systemctl --user start plasma-polkit-agent.service; then
            printf 'Log out and back in to start the newly installed desktop authorization agent.\n'
        fi
    fi
    printf '\nVelum installed. Open Velum from your app menu (or run velum), then import your VPN link.\n'
    printf 'When upgrading a running Velum, disconnect, run sudo systemctl restart velum.service, and reopen it.\n'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
