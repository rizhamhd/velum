# Changelog

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
