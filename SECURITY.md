# Security policy

This 0.1 development series has not received an independent security audit. Do
not treat test coverage as proof of leak-free behavior across every Linux stack.

Report security issues privately through the published repository's private
vulnerability-reporting channel once enabled. Before publication there is no
public security inbox; contact the repository owner privately. Do not post real
provider credentials in issues.

Threat boundaries: imported URLs and local IPC are untrusted; installed root-owned
code, Polkit, the kernel, Xray, tun2socks, systemd, and root administrators are
trusted. The GUI runs unprivileged. The root service validates input, rejects
arbitrary commands/config files, and executes fixed argument arrays. The initial
implementation retains privileged engine children and requires further review.

Profiles and runtime configs contain credentials in plaintext with restrictive
permissions. They are not a replacement for disk encryption or account security.
The clipboard is intentionally sensitive when explicitly copying a URL. Secrets
are redacted from application logs; raw engine logs are discarded.

TLS certificate verification stays enabled. Profiles may specify one explicit
`verifyPeerCertByName` hostname separately from the SNI. This changes the expected
server identity, so use a hostname supplied by the provider. Empty means the
usual SNI/server identity. `allowInsecure=true` is rejected because the tested
Xray backend removed it; it is never silently translated into another mode.

Kill-switch guarantees are session-scoped and require a non-OFF mode. GUI exit
or crash retains the VPN and its monitoring. Explicit disconnect, orderly service
stop, and explicit recovery restore normal networking. Abrupt helper
failure holds the app's firewall until recovery or reboot. Other privileged tools
can change routes/firewalls outside the application's control.
