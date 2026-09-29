# Local-checkout package. Build from the repository root with makepkg -si.
pkgname=velum-vpn
pkgver=0.1.0
pkgrel=1
pkgdesc='Qt VLESS client with privilege-separated full-device routing'
arch=('any')
license=('MIT')
depends=('python' 'pyside6' 'iproute2' 'nftables' 'systemd' 'polkit' 'curl' 'procps-ng')
makedepends=('python-build' 'python-installer' 'python-setuptools')
checkdepends=('ruff')
optdepends=('xray: required VPN engine (xray-bin also works)'
            'tun2socks: required xjasonlyu TUN adapter (tun2socks-bin also works)'
            'networkmanager: hotspot connection detection'
            'polkit-kde-agent: KDE authentication dialog')
source=()
sha256sums=()

build() {
  cd "$startdir"
  python -m build --wheel --no-isolation
}

check() {
  cd "$startdir"
  ./scripts/check.sh
}

package() {
  cd "$startdir"
  python -m installer --destdir="$pkgdir" "dist/velum_vpn-$pkgver-py3-none-any.whl"
  install -Dm644 packaging/velum.service "$pkgdir/usr/lib/systemd/system/velum.service"
  install -Dm644 packaging/velum.socket "$pkgdir/usr/lib/systemd/system/velum.socket"
  install -Dm644 packaging/org.velum.policy "$pkgdir/usr/share/polkit-1/actions/org.velum.policy"
  install -Dm644 packaging/org.velum.Velum.desktop "$pkgdir/usr/share/applications/org.velum.Velum.desktop"
  install -Dm644 assets/org.velum.Velum.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/org.velum.Velum.svg"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm755 scripts/recover.sh "$pkgdir/usr/lib/velum/recover"
}
