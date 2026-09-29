# Networking and resource ownership

## Initial supported environment

Linux with TUN, iproute2 JSON support, nftables inet/NAT, systemd, Polkit,
systemd-resolved stub, Xray, and xjasonlyu/tun2socks. An IPv4 physical default
route is required. Existing custom IPv4 policy routing is refused. No physical
interface names are assumed: the lowest-metric usable `main` default supplies
the gateway/device. Wi-Fi is identified by sysfs; TUN/loopback/virtual links have
separate classifications. NetworkManager `ipv4.method=shared` identifies sharing.

## IPv4 routing

Owned resources:

| Resource | Value |
| --- | --- |
| Tunnel | vpn0, 198.18.0.1/30, MTU 1500 |
| Table | 28672 |
| Endpoint rule | priority 10998, destination provider /32 → main |
| Engine bypass | priority 10999, fwmark 0x5650 → main |
| Ordinary traffic | priority 11000 → table 28672 |
| Route protocol | 186 |
| Internal SOCKS | 127.0.0.1:28673 |
| Firewall | inet velum_vpn |

A provider /32 route through the original gateway/device is added before the
policy route. The destination rule also gives reverse-path filtering a correct
physical reverse route for provider packets. Xray marks its provider sockets;
ordinary sockets remain unmarked. Local table priority 0 preserves loopback,
including the internal SOCKS connection. `main` defaults are never replaced.

Existing interfaces, priorities, tables, or endpoint host routes that collide are
refused. Owned resources use `add`, not `replace`. Unrelated rules/tables are not
flushed. Native IPv6 routes remain unchanged; IPv6 output/forwarding is blocked
while the session firewall exists. IPv6 loopback remains available.

## DNS

Only the systemd-resolved stub at 127.0.0.53 is accepted. VPN link DNS uses
1.1.1.1 and 9.9.9.9 and routing domain `~.`. Other link settings remain intact.
Outgoing non-loopback port-53 traffic is intercepted to 1.1.1.1, which routes
through the tunnel. Physical port 53/853 egress is blocked. DNS transport is
carried through VLESS; encryption depends on whether the imported service uses
TLS. This is leak prevention, not a claim of end-to-end DoH/DoT.

Rollback reverts the VPN link only. It does not rewrite resolv.conf or reset
NetworkManager's connection. Resolved caches are flushed on setup. Existing DNS
managers and hostname-resolution NSS configurations need live deployment testing.

## Firewall and sharing

The inet table has separate output, forward, DNS NAT, and (when enabled) hotspot
NAT chains. No blanket established-connection exception permits old physical
connections to bypass the desktop kill switch. Reconnect exceptions are limited
to marked TCP to the pinned provider and DHCP. LAN bypass is currently unavailable.

With an existing NM shared interface, its subnet gets a return route in table
28672. Per-interface IPv4 forwarding is enabled for that interface and vpn0,
recording previous values. This avoids the kernel's global ip_forward setting
resetting other host/router sysctls. DNS from hotspot clients is intercepted before
NetworkManager's usual NAT priority. Hotspot egress is allowed only toward vpn0,
with masquerade; replies are limited to established/related forwarding. IPv6
forwarding is blocked. Existing third-party firewall drops remain authoritative.

A phone egress test is mandatory before claiming hotspot acceptance. Laptop-side
checks cannot prove that a particular phone is using the intended network.

## Failure semantics

| Event | Behavior |
| --- | --- |
| Config/preflight failure | No routes changed; credentials cleaned |
| Setup/verification failure | Rollback; error shown; normal networking restored |
| Xray/tun2socks dies | Non-OFF kill switch remains; retry and reverify |
| Wi-Fi/gateway changes | Detect, hold firewall, recreate network transaction |
| Resume | Detected by monitor interval; full verification before CONNECTED |
| GUI exits/crashes | Socket EOF triggers disconnect and restores networking |
| Explicit disconnect | Stop children, restore network, remove guard last |
| Abrupt helper death | systemd kills children; journals and firewall retained |
| Helper restart with journals | ERROR; authenticated disconnect/recovery required |
| Reboot | Runtime journals/kernel routes/nftables disappear; normal boot networking |

OFF explicitly permits IPv4 fallback. A kill switch is scoped to the VPN session,
not a permanent boot-time firewall. GUI crash recovery restores normal networking
by design. Applications must not assume protection after the GUI/service exits.

Rollback operations are recorded before mutations. Missing already-removed
resources are treated idempotently; genuine cleanup failures retain the journal
and guard. Only the service's root-owned journals are replayed. Do not persist the
Velum nftables table in `/etc/nftables.conf`; that would defeat reboot cleanup.
Privileged third-party tools can alter networking outside these guarantees.
