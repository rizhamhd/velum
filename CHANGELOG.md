# Changelog

## 0.1.0-6 — Keep VPN running when the GUI closes

- Keep the service session, monitoring, and recovery alive after GUI exit/crash.
  Authenticated windows from the owning user can reopen and control the session.
- Synchronize status, active profile, and connection settings on GUI startup.
  Lock conflicting controls until the helper acknowledges operation completion.
- Validate reconnect input before disconnecting; isolate broken GUI sockets from
  network operations and fix the deleted Qt signal callback on window teardown.
- Pass 74 unit/offscreen/local-socket tests, Ruff, and isolated real-kernel
  TCP/UDP, IPv6 blocking, kill-switch and rollback checks. Persistence tests mock
  networking; installed live close/reopen acceptance remains to be performed.

## 0.1.0-5 — Remember pre-VPN check preference

- Persist the public-IP-change checkbox across app restarts in private settings.
- Explain that a failed pre-VPN public-IP check happened before tunnel startup,
  and direct restricted-package users to the relevant setting.
- Cover reopening the GUI, the setting sent to the service, malformed stored
  preferences, and failure context; all 62 unit tests and Ruff pass.

## 0.1.0-4 — Separate certificate hostname

- Add a per-profile certificate hostname in the editor and VLESS URL using
  `verifyPeerCertByName`, preserving SNI and transport fields while validating TLS.
- Show the certificate hostname in the profile table and distinguish it in TLS
  diagnostics. Reject removed `allowInsecure=true` with an actionable error.
- Validate import/export, editing, strict parsing, original-SNI preservation, and
  actual Xray configuration acceptance. A live provider probe with original
  YouTube SNI and a separate certificate hostname passed two proxied HTTPS checks;
  ISP package billing and full-device routing were not tested in that probe.

## Unreleased — live acceptance tooling

- Respect disabling the public-IP-change check: skip pre-tunnel public-IP
  requests on restricted data connections while retaining tunnel verification.
  Explain regular-data use and package-billing limits in Settings and docs.
- Add explicit live Qt/client acceptance using private saved profiles: independent
  HTTPS egress, UDP DNS, IPv6 probe, diagnostics, periodic verification, reconnect,
  and route/DNS/public-IP restoration checks with private outcome reports.
- Add certificate-only troubleshooting without changing network routes.
- Cover engine loss, periodic-check failure, upstream recovery, and retry backoff
  in regression tests, including preservation of firewall protection.

## 0.1.0-2 — DNS compatibility fix

- Accept NetworkManager-generated regular resolv.conf files pointing exclusively
  to the running systemd-resolved stub. Keep external/mixed resolver rejection.
- Add regression coverage for regular files, symlinks, and unreachable stubs.

## 0.1.0 — Unreleased

- Add strict VLESS TCP/WebSocket and TLS parsing with original-URI preservation.
- Add atomic private profile CRUD, migration, imports, and exports.
- Add Xray configuration validation and process management.
- Add Qt GUI, system tray, diagnostics, notifications, and structured redacted logs.
- Add Polkit/systemd service, full-device TUN routing, endpoint bypass, DNS and IPv6
  protection, optional kill switch, and existing NetworkManager hotspot sharing.
- Add journaled rollback, stale-session recovery, and supervised reconnect.
- Add Arch package, unit tests, and isolated real Xray TCP/UDP packet tests.
- Production release remains gated on live acceptance and independent review.
