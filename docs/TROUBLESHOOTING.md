# Troubleshooting

## Stuck operations or an unresponsive helper

Use **Kill VPN & Quit** in the window or tray and approve administrator
authorization. Recovery runs separately from the helper and remains available
while Connect/Reconnect is pending. It stops the VPN and restores ordinary
networking before closing the GUI. If the whole GUI is frozen, use:

```sh
pkexec /usr/lib/velum/emergency-stop
```

If recovery reports failure, follow the journal recovery instructions below.
Do not assume protection or successful cleanup from a failed emergency stop.

## Installation fails with 404 or PKGBUILD does not exist

A pacman `.pkg.tar.zst.sig` download returning **404** means the requested file
is missing from that mirror. Refresh the package databases with a full upgrade:

```sh
sudo pacman -Syu
```

On CachyOS, if the mirror still returns 404, rerate mirrors and refresh again:

```sh
sudo cachyos-rate-mirrors && sudo pacman -Syyu
```

Then rerun `./scripts/install.sh`. Keep signature checking
enabled; a missing signature file is a download problem, not a reason to disable
verification. See the [CachyOS FAQ](https://wiki.cachyos.org/cachyos_basic/faq/#error-404-not-found)
and [Arch pacman troubleshooting](https://wiki.archlinux.org/title/Pacman#Troubleshooting).

`ERROR: PKGBUILD does not exist` means `makepkg` is running in the wrong directory
or the repository has not been cloned. For a fresh checkout:

```sh
git clone https://github.com/rizhamhd/velum.git && cd velum
./scripts/install.sh
```

If the repository is already on disk, enter its existing directory instead of
cloning again. The installer prepares dependencies and engines before building.

`Unit velum.socket does not exist` and `Unknown command: velum` are expected when
the package was never installed. After `makepkg -si` succeeds:

```sh
sudo systemctl enable --now velum.socket && velum
```

## Service or authorization unavailable

```sh
systemctl status velum.socket velum.service
journalctl -u velum.service -b --no-pager
pkaction --action-id org.velum.manage --verbose
```

Install the package and enable `velum.socket`. On KDE ensure a Polkit agent is
running. Do not run the GUI as root or loosen the Polkit policy. The user who
started the VPN owns it; that user can reopen Velum to inspect or disconnect it.
Closing the GUI keeps the VPN running. Helper code comes from the installed
package, not the development checkout.

## Xray started but routing failed

```sh
ip -d link show vpn0
ip -4 rule show
ip -4 route show table 28672
ip -4 route get 1.1.1.1
ip -4 route show table main
sudo nft list table inet velum_vpn
```

Expected: vpn0 UP, table 28672 default via vpn0, priorities 10998/10999/11000.
The physical default remaining in main is intentional. A rule/table collision or
another policy VPN is rejected. Do not delete another application's resources.

For the pinned provider IPv4, substitute its address locally (not credentials):

```sh
ip -4 route get PROVIDER_IPV4 mark 0x5650
```

It should use the physical upstream. A provider host-route collision is rejected
instead of overwritten. Automatic recovery uses the pinned IP; explicitly
reconnect if the provider changed DNS.

## DNS configuration failed

```sh
readlink -f /etc/resolv.conf
resolvectl status
resolvectl status vpn0
resolvectl query example.com
nmcli general status
```

Both regular NetworkManager-generated files and symlinks are supported when
127.0.0.53 is the sole nameserver and the resolved stub is reachable. External
resolvers, mixed resolver lists, and unreachable stub listeners are refused.
The installer offers backed-up NetworkManager/resolved setup after confirmation.
For other network managers, configure resolved according to distro documentation.
The running VPN never migrates the resolver automatically. Do not replace
resolv.conf merely to silence an error.

## TLS or connectivity fails

For an app-specific data package, turn off **Require public IP to change** in
Settings before connecting. Version 0.1.0-5 remembers this choice across restarts;
earlier versions reset it to on whenever the GUI opened. Otherwise Velum contacts public-IP services directly
before starting the tunnel; this can consume regular data or prevent startup if
general internet access is unavailable. With the setting off, public-IP requests
run only after tunnel protection checks pass. Endpoint DNS and TCP setup still
use the physical connection. The original IP is not measured in this mode, so
only the post-connect egress is verified, without a before/after comparison.
An installed helper from before this fix still performs the direct check even
with the setting off; rebuild and reinstall the package when updating source.

Use the exact provider profile that works in your other client. Changing SNI to
the VPN server's hostname changes the TLS handshake and may affect how the ISP
classifies the connection. A successful connection, changed public IP, or passing
diagnostics cannot establish which data allowance was charged; compare the ISP's
usage counters. Velum does not read those counters.

Check provider address/port, SNI, validity of the subscription, ALPN, system clock,
and whether the provider supports the imported transport. VLESS supports TCP,
WebSocket, gRPC, HTTPUpgrade, XHTTP, REALITY and Vision. Unknown options still
produce errors. Old `allowInsecure=true` links need the installed sing-box
compatibility engine; verification is disabled and labeled in the UI.
When a provider uses a different SNI from its certificate,
set **Edit → Verify certificate for** to the provider's certificate hostname.
This emits `verifyPeerCertByName` while preserving the original SNI and still
validating the certificate chain and configured name. Obtain the expected name
from your provider; do not use an arbitrary hostname. Leaving the field blank
restores normal SNI/server verification. Raw Xray output is suppressed to avoid logging credentials; the GUI
cannot always distinguish a remote TLS failure from a dropped transport.

From a development checkout, check the saved profile's certificate without
changing host routing (find its ID using the live-test guide in TESTING.md):

```sh
PYTHONPATH=src python scripts/live-test.py --profile-id PROFILE_ID --tls-only
```

This is a standard TLS probe, not a full Xray/uTLS or provider authentication
test, and does not support a separate certificate hostname (it refuses that mode
explicitly). A hostname mismatch means the certificate does not cover the configured
SNI. Confirm both the required SNI and certificate hostname with your provider;
keep the original URL and use a separate profile for changes. A passing certificate check alone does not prove
that the VPN account or transport works.

```sh
timedatectl status
xray version
tun2socks -version
curl -q --noproxy '*' -4 --max-time 10 https://api.ipify.org
curl -q --noproxy '*' -4 --max-time 10 https://checkip.amazonaws.com
```

Two HTTPS observations must agree. If services are unavailable or a provider uses
rotating egress per destination, verification can fail conservatively. Do not
claim CONNECTED by bypassing these checks. Before/after equality fails by default.

## IPv6

```sh
sudo nft list table inet velum_vpn
curl -q --noproxy '*' -6 --max-time 5 https://api64.ipify.org
```

The IPv6 request should fail while connected. IPv6-only provider endpoints cannot
connect in this release. The app does not permanently disable IPv6 via sysctl.

## Hotspot clients cannot reach the VPN

```sh
nmcli -f NAME,UUID,TYPE,DEVICE connection show --active
ip -4 route show table 28672
sudo nft list table inet velum_vpn
sysctl net.ipv4.conf.vpn0.forwarding
```

Also inspect `net.ipv4.conf.HOTSPOT_INTERFACE.forwarding` using the actual interface.
Verify the NM connection uses `ipv4.method=shared`, the interface differs from the
upstream, and the phone has a valid IPv4 lease. Third-party forward-chain drops can
block sharing. Velum does not override these rules. Compare the phone's public IP
with the laptop's VPN IP; laptop diagnostics alone do not certify a phone.

## Stale resources / failed cleanup

First try **Disconnect**. If necessary, explicitly restore normal networking:

```sh
sudo /usr/lib/velum/recover
sudo systemctl start velum.socket
```

The recovery wrapper stops the service before replaying only its root-owned
journals. A failed cleanup leaves the firewall rather than reporting success.
Do not `nft flush ruleset`, replace defaults, remove another VPN's interface, or
manually delete journals. A reboot clears transient Velum kernel state; it should
not be needed for ordinary disconnects.

## Reporting a bug

Attach copied diagnostics and sanitized structured logs, core versions, resolver
manager, and distro/kernel version. Remove personal public IPs if desired. Never
paste a real VLESS link, UUID, exported profile, or runtime xray.json in a public
issue. Include whether the isolated integration suite passes and which live
acceptance step failed.
