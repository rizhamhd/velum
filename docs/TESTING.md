# Test evidence and release gates

## Executed in the development workspace

Environment: CachyOS, Python 3.14.7, PySide6 6.11.2, Xray 26.3.27,
xjasonlyu/tun2socks 2.6.0. No real provider credentials were used.

- Unit/offscreen suite: 45 tests passed in the final unit/offscreen suite.
- Ruff: passed.
- Installed Xray validated generated TCP/none, TCP/TLS, WebSocket/none, and
  WebSocket/TLS configurations using its actual `run -test` command.
- Qt window created/rendered offscreen; profile table and failure-state behavior
  exercised. The screenshot is from the actual disconnected GUI.
- Arch package built with makepkg; systemd units parsed with systemd-analyze.
- Root-mapped user/network namespace integration passed against the real kernel:
  TUN and adapter startup, routing table/rules, marked endpoint bypass, nftables
  creation, all hotspot/kill-switch ruleset syntax variants, and cleanup.
- Unrelated nftables table remained intact after cleanup.
- A second disposable namespace ran a dummy VLESS server and TCP/UDP endpoints.
  Ordinary TCP socket source changed from the direct link to Xray's remote egress;
  UDP echo also traversed VLESS. No SOCKS/interface override was used by probes.
- Previously reachable IPv6 became unreachable under protection.
- Killing the client Xray and removing its catch-all policy rule still left the
  ordinary direct TCP path blocked by the kill switch.
- Namespace teardown and write-ahead rollback completed successfully.

The initial sudo-root attempt could not run because interactive sudo authentication
was required. The equivalent tests succeeded using root-mapped user namespaces
outside the tool sandbox. They did not install the service or mutate host routes.

## Normal development checks

```sh
./scripts/check.sh
python -m compileall -q src
systemd-analyze verify packaging/velum.service packaging/velum.socket
makepkg --force --noconfirm
```

The unit suite never changes host networking. Engine validation is skipped if
Xray is absent; GUI tests are skipped if PySide6 is absent. CI does not install
Xray automatically, so local engine and namespace test evidence remains distinct.

## Explicit namespace integration

```sh
sudo ./scripts/integration.sh --root-network-namespace
# Root only inside disposable namespaces, where the kernel permits this:
./scripts/integration.sh --user-network-namespace
```

The script records the original namespace identity, unshares networking, and
refuses execution if isolation is missing. The suite creates only dummy lab
credentials. It never contacts a paid provider or public internet endpoint.

## Mandatory live release acceptance (NOT YET EXECUTED)

Use a disposable CachyOS/Arch test machine first. Install the package through
pacman, run the GUI as an ordinary active desktop user, and confirm Polkit
allows the authorized user and denies unauthenticated users. Test actual
systemd-resolved/NM behavior and the unit's systemd sandbox.

Record these before connecting:

```sh
ip -4 route show table main
ip -4 rule show
curl -q --noproxy '*' -4 https://api.ipify.org
curl -q --noproxy '*' -4 https://checkip.amazonaws.com
```

Import a legally obtained provider profile through the GUI; never save it in the
checkout. For each supported transport/TLS combination supplied by the provider,
connect and confirm every relevant diagnostic passes. Independently run:

```sh
ip -d link show vpn0
ip -4 route show table 28672
ip -4 route get 1.1.1.1
resolvectl status vpn0
sudo nft list table inet velum_vpn
curl -q --noproxy '*' -4 https://api.ipify.org
curl -q --noproxy '*' -4 https://checkip.amazonaws.com
curl -q --noproxy '*' -6 --max-time 5 https://api64.ipify.org
```

The IPv4 addresses must differ from baseline and agree with the intended provider.
IPv6 must fail in block mode. Capture physical-interface packets while issuing
DNS queries: there must be no ordinary port 53/853 DNS egress. Confirm normal UDP
applications as well as browsers/terminal traffic.

Exercise Wi-Fi loss, new Wi-Fi/gateway, Ethernet insertion/removal, sleep/resume,
engine termination, TUN removal, GUI death, helper SIGKILL/restart, explicit
recovery, and reboot. Compare unrelated routes/firewall/resolver settings before
and after. A non-OFF kill switch must prevent fallback while the session is active.
GUI exit/crash and explicit disconnect intentionally end session protection.

For hotspot acceptance, create a real NM hotspot, enable sharing, connect a phone,
and compare its independently observed public IP with the VPN egress. Confirm
phone DNS and IPv6 protection, then kill the engine: phone traffic must not fall
back. Disable sharing/disconnect and check restoration of forwarding state.

Publish production claims only after these tests pass, packaging/service behavior
is reviewed, and an independent security review has addressed the root service.
