# Architecture

## Boundaries

`config/` parses VLESS and persists versioned profiles. Original URI and normalized
fields are both stored; the privileged service reparses the URI rather than
trusting saved normalized fields. `vpn/` generates Xray JSON and owns process
lifecycle. `network/` detects the upstream and manages transactions, TUN, DNS,
firewall, and sharing. `core/` implements the state machine. `diagnostics/` observes
ordinary routing and HTTPS egress. `gui/` and `notifications/` contain Qt views.
`security/` provides private writes, redaction, structured logs, and Polkit checks.
`services/` is the IPC/session orchestration boundary.

## IPC and privilege separation

The root-owned systemd socket `/run/velum.sock` is accessible to local users.
Socket access does not grant networking authority. On the first request, the
service obtains Linux SO_PEERCRED and checks `org.velum.manage` through Polkit,
including the peer PID, start time, and UID. Policy defaults require an active
local administrator authentication. The service owns the VPN session independently
of GUI connections; EOF only detaches a GUI. Unauthorized/idle connections cannot
change networking. The session's initiating UID controls it until explicit
disconnect; reopening a GUI requires authorization again.

Requests are newline-delimited JSON, limited to 64 KiB, with a fixed operation
set: connect, disconnect, reconnect, diagnostics, status. Profile fields are
strictly validated. Executable paths and command arguments are constructed by
trusted code. One session and up to sixteen control connections are supported.
Requests are serialized on the service thread. Only authorized peers belonging to
the owning UID receive session updates or control the active VPN. Closed or slow
peers are detached without propagating socket errors into network operations.
Request completion IDs keep GUI buttons locked across intermediate reconnect
states. Monitoring also runs when there are no GUI connections.

The service runs `/usr/bin/python -I -m velum.services.helper` from installed,
root-owned site-packages. Python user-site and checkout imports are disabled.
The systemd unit restricts capabilities, writable paths, address families, and
privilege escalation. Xray and tun2socks are currently privileged children; further
privilege reduction is a release-review target, not a claimed implementation.

## Connection sequence

DISCONNECTED → VALIDATING → PREPARING_NETWORK → STARTING_CORE → WAITING_FOR_TUN
→ CONFIGURING_ROUTES → CONFIGURING_DNS → VERIFYING → CONNECTED.

Validation includes Xray's own configuration test, prerequisites, collision checks,
resolver compatibility, provider resolution/reachability, and baseline public IP.
Failures enter ERROR/CLEANUP and only reach DISCONNECTED after successful rollback.
Disconnect enters STOPPING/RESTORING_NETWORK. Active tunnel failure retains the
firewall and moves through ERROR/RECONNECTING/VERIFYING.

The root service serializes operations. Qt uses asynchronous QLocalSocket I/O;
network validation never executes on the GUI thread. Monitoring checks local
state roughly every two seconds while idle, and rechecks HTTPS egress every minute
and after a detected resume interval. An upstream change triggers reconstruction
against the new default while retaining firewall protection. Reconnection uses
cached provider IPv4; explicit reconnect refreshes provider DNS.

## Engine choice

Xray's newer documentation describes a native TUN inbound, but support depends
on the installed core version. This release uses the tested xjasonlyu/tun2socks
adapter and loopback Xray SOCKS inbound, with explicit Linux routing ownership.
The adapter carries both TCP and UDP. There is no direct/freedom fallback in the
client configuration. The engine Protocol permits a later sing-box backend.

References: [Xray inbound documentation](https://xtls.github.io/en/config/inbound.html),
[tun2socks usage](https://github.com/xjasonlyu/tun2socks/wiki/Examples),
[systemd sockets](https://www.freedesktop.org/software/systemd/man/latest/systemd.socket.html).

## Persistence and recovery

Profile JSON is atomically replaced with mode 0600 and directory/file fsync. A
file lock serializes writers. v0 URI-list databases migrate to v1 records. Runtime
credentials and write-ahead rollback journals are under root-owned mode-0700
`/run/velum`; no profiles are committed to Git. The firewall journal is separate
from network rollback so retries can retain protection. See NETWORKING.md for
failure semantics and the operational limits of rollback.
