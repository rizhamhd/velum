# Test evidence and release gates

## Release updater (2026-10-04)

Updater coverage includes version ordering/no downgrades, invalid release tags,
checksum mismatches, archive path traversal/symlink/device rejection, canceled
updates, installation failure, recovery ordering, and GUI update controls.
Installer and privileged recovery subprocesses are mocked; the tests do not
upgrade the host or disconnect an existing VPN.

## Dependency installer (2026-10-04)

Installer tests simulate package-manager responses for installed engines,
repository packages, missing AUR engines, desktop agents, and failed downloads.
The AUR build path is exercised with mocked git/makepkg commands. DNS migration
uses temporary filesystem trees and mocked system commands, covering backups,
regular files/symlinks, failed verification, and restoration of service state.
The local engine check also ran against the installed Xray and tun2socks.

A full first-time install on a clean Arch/CachyOS VM, real AUR downloads, and live
DNS migration remain acceptance checks. Tests do not perform a system upgrade or
change the development machine's DNS configuration.

## Persistent service session (2026-10-02)

The 0.1.0-6 source passed 74 tests and Ruff. Coverage includes GUI socket EOF,
broken pipes during setup, monitoring without a GUI, reopening over a real local
socket, authorization and UID ownership, explicit disconnect, invalid reconnect
input, button locking through intermediate states, restored profile/settings,
and destruction of a connected Qt client. These lifecycle tests mock networking.
Socket tests require an environment permitting local Unix sockets.

The isolated namespace suite also passed real Xray/VLESS TCP/UDP egress, IPv6
blocking, kill-switch protection after engine/routing loss, and rollback retaining
unrelated firewall state. This is not installed live GUI-close acceptance. Before
claiming that gate, connect a private profile, close all GUI windows, verify
ordinary egress and periodic monitoring, reopen, reconnect, and explicitly disconnect.

## Airtel profile with pre-VPN checks disabled (2026-09-30)

After restarting the installed 0.1.0-5 service, the saved YouTube-SNI profile with
a separate certificate hostname passed full-device live acceptance using
`scripts/live-test.py --restricted-data --cycles 1 --hold-seconds 0` plus the
private profile ID and explicit network-change option. Direct public-IP probes
before connection and after disconnect were skipped for the restricted package.

The [sanitized report](test-results/live-airtel-restricted-2026-09-30.json) records
successful connection, independent non-root HTTPS egress matching the helper,
ordinary UDP DNS, IPv6 blocking, repeated diagnostics, and restoration of routes
and DNS after disconnect. This run did not measure a before/after IP change,
long-term stability, hotspot traffic, or ISP allowance accounting.

Earlier attempts failed during tunnel verification, independent HTTPS egress
checking, and waiting for the helper. The final successful run demonstrates
current connectivity; it does not establish the cause of every earlier failure.

## Separate certificate hostname (2026-09-30)

The 0.1.0-4 source passed 60 unit tests and Ruff, including real Xray 26.3.27
configuration validation for TCP/WebSocket with a separate certificate hostname.
Regression coverage includes unchanged SNI/path encoding, strict option parsing,
GUI edit/save/import/export, and TLS diagnostics retaining failed connection status.

A temporary unprivileged Xray SOCKS probe used the original private YouTube-SNI
profile plus the certificate hostname from its previously verified counterpart.
Both independent HTTPS egress services succeeded and agreed through that proxy.
No host routes were changed. This confirms provider transport compatibility;
it does not establish full-device routing or Airtel data-allowance accounting.

## Executed in the development workspace

Environment: CachyOS, Python 3.14.7, PySide6 6.11.2, Xray 26.3.27,
xjasonlyu/tun2socks 2.6.0. Automated namespace tests use dummy credentials. A subsequent authorized live
WebSocket/TLS provider test used a private profile outside the checkout.

- Unit/offscreen suite: 53 tests passed, including recovery/backoff and protection
  retention after engine loss or failed periodic verification.
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

## Authorized live smoke test (2026-09-29)

The installed 0.1.0-2 package passed Polkit authorization and setup against the
machine's actual NetworkManager-generated regular resolv.conf and resolved stub.
The supplied profile initially failed TLS certificate-name validation; a separate
profile with SNI matching the server certificate passed without allowInsecure.
The original private profile was preserved. No provider credentials are in Git.

The full-device session reached CONNECTED with all applicable diagnostics passing:
Xray, TUN, routing policy, DNS protection/resolution, IPv6 protection, HTTPS
connectivity, and changed IPv4 egress. An independent ordinary non-root process
confirmed its public address changed and matched the helper's VPN egress. The
test explicitly disconnected afterward and completed rollback. This is one
WebSocket/TLS profile, not certification of every provider or network environment.
Hotspot sharing was disabled during this test.

## Live GUI acceptance rerun (2026-09-30)

The actual Qt window/client and installed 0.1.0-2 helper passed a complete rerun
using the same private WebSocket/TLS profile with corrected SNI. The original
profile still fails a separate standard TLS probe with a certificate hostname
mismatch. Neither saved profile was changed and TLS verification stayed enabled.

The [sanitized final report](test-results/live-2026-09-30.json) records 27 passing
checks and zero failures:

- Connect and explicit reconnect both reached CONNECTED with all applicable
  helper diagnostics passing, including TLS and changed IPv4 egress.
- Independent ordinary non-root HTTPS traffic agreed with the helper's VPN IP.
- Ordinary UDP DNS requests succeeded through protected routing.
- The connection stayed healthy for 90 seconds, including automatic verification.
- Explicit disconnect restored the original main routes, policy rules,
  resolv.conf contents, resolved DNS/domain settings, and public IPv4.
- IPv6 probes failed while connected. The physical uplink had no baseline IPv6
  reachability, so the isolated namespace test remains the evidence of IPv6 blocking.

Two earlier runs prompted acceptance-harness improvements: extra diagnostics reset
the periodic timer, and an immediate restoration comparison differed from baseline.
The final harness disables manual window controls
and waits at most 10 seconds for exact restoration, reporting mismatching
components if it does not settle. It does not waive failed network checks.

The isolated real-kernel TCP/UDP, IPv6, kill-switch, and rollback suite was also
rerun successfully. The local 53-test suite, Ruff, Python compilation, and systemd
unit verification passed. Physical hotspot, suspend/hotplug, and independent
security review remain release gates.

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

## Repeatable live GUI acceptance

The live test uses the actual Qt window/client and the installed Polkit helper.
Close other Velum windows first. Run as your ordinary desktop user. The test
temporarily routes the machine through the selected saved VPN, then disconnects
and compares routes, policy rules, DNS configuration, and public IPv4 with their
original values. The original profile is never edited.

List profile IDs without exposing their URLs or credentials:

```sh
PYTHONPATH=src python - <<'PY'
import os
from pathlib import Path
from velum.config.profiles import ProfileStore
config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'velum'
for profile in ProfileStore(config / 'profiles.json').list():
    print(profile['id'], profile['name'])
PY
```

Substitute the chosen ID for `PROFILE_ID`:

```sh
PYTHONPATH=src python scripts/live-test.py --profile-id PROFILE_ID \
  --allow-network-changes --cycles 2 --hold-seconds 90 \
  --report /tmp/velum-live-acceptance.json --visible
```

The test checks changed egress with independent ordinary non-root HTTPS probes,
a UDP DNS query, an IPv6 connection attempt, explicit diagnostics, periodic
verification, and reconnect. The visible window's controls are temporarily disabled
to prevent manual actions from changing the automated test sequence. Omit
`--visible` to render Qt offscreen. Reports contain outcomes without profile URLs,
credentials, or public IP addresses, and are written with mode 0600.
Network restoration allows up to 10 seconds for asynchronous link-removal updates;
a remaining mismatch identifies the affected component and fails the test.

An IPv6 connection failure on an IPv4-only uplink is not by itself proof of IPv6
protection. The isolated dataplane test separately establishes IPv6 reachability
before confirming that protection blocks it. Live tests do not replace packet
capture for DNS leak checks or physical hotspot and suspend/hotplug acceptance.

If a live check fails, the test attempts an explicit disconnect and checks network
restoration before returning a nonzero exit status. A cleanup failure is reported
separately and needs inspection using the recovery guide.

## Explicit namespace integration

```sh
sudo ./scripts/integration.sh --root-network-namespace
# Root only inside disposable namespaces, where the kernel permits this:
./scripts/integration.sh --user-network-namespace
```

The script records the original namespace identity, unshares networking, and
refuses execution if isolation is missing. The suite creates only dummy lab
credentials. It never contacts a paid provider or public internet endpoint.

## Remaining live release acceptance

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
GUI exit/crash must retain the session and monitoring; reopen the GUI and check
that its status matches the service. Explicit disconnect ends session protection.

For hotspot acceptance, create a real NM hotspot, enable sharing, connect a phone,
and compare its independently observed public IP with the VPN egress. Confirm
phone DNS and IPv6 protection, then kill the engine: phone traffic must not fall
back. Disable sharing/disconnect and check restoration of forwarding state.

Publish production claims only after these tests pass, packaging/service behavior
is reviewed, and an independent security review has addressed the root service.
