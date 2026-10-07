# Security policy

This 0.1 development series has not received an independent security audit. Do
not treat test coverage as proof of leak-free behavior across every Linux stack.

Report security issues privately through the published repository's private
vulnerability-reporting channel once enabled. Before publication there is no
public security inbox; contact the repository owner privately. Do not post real
provider credentials in issues.

Threat boundaries: imported URLs and local IPC are untrusted; installed root-owned
code, Polkit, the kernel, Xray, sing-box, tun2socks, systemd, and root administrators are
trusted. The GUI runs unprivileged. The root service validates input, rejects
arbitrary commands/config files, and executes fixed argument arrays. The initial
implementation retains privileged engine children and requires further review.

Profiles and runtime configs contain credentials in plaintext with restrictive
permissions. They are not a replacement for disk encryption or account security.
The clipboard is intentionally sensitive when explicitly copying a URL. Secrets
are redacted from application logs; raw engine logs are discarded.

TLS certificate verification is enabled by default. Profiles may specify one explicit
`verifyPeerCertByName` hostname separately from the SNI. This changes the expected
server identity, so use a hostname supplied by the provider. Empty means the
usual SNI/server identity. A link explicitly requesting `allowInsecure=true`
selects the installed sing-box compatibility engine and disables verification.
The editor, profile table and diagnostics display this; successful egress does
not mark the server identity as verified. The imported URI is preserved unless edited. Entering a certificate hostname
in the editor explicitly enables verification on save and preserves the SNI;
the editor previews this change. Leaving an insecure profile’s name field blank
keeps its existing verification setting.
Plain TCP may retain an unused host field, with a visible notice.
Shadowsocks additionally permits marked UDP only to its pinned provider IP/port;
other protocols keep the TCP-only endpoint exception.

Kill-switch guarantees are session-scoped and require a non-OFF mode. GUI exit
or crash retains the VPN and its monitoring. Explicit disconnect, orderly service
stop, and explicit recovery restore normal networking. Abrupt helper
failure holds the app's firewall until recovery or reboot. Other privileged tools
can change routes/firewalls outside the application's control.

Emergency stop uses pkexec and the installed root-owned
`/usr/lib/velum/emergency-stop` entry point, with administrator authorization.
It accepts no options or caller-provided commands. It stops only the Velum units
and service processes before replaying existing recovery journals. Recovery
failure leaves the socket stopped and journals available; the GUI stays open.

The first-time installer is an explicit package installation operation. It uses
the configured Arch repositories and, when necessary, the community-maintained
xray-bin/tun2socks-bin AUR recipes. Builds run without root; package signatures
and source checksum checks are not disabled. The GUI/helper do not fetch engines.
Guided DNS setup requires a separate installer confirmation and administrator
access. It uses installed code, backs up DNS files, and rolls back failed checks.

Update checks contact this repository's public GitHub release API only on user
request. The updater uses HTTPS downloads, checks the published SHA-256, refuses
unsafe archive entries, and runs source builds as the ordinary user. Checksums
detect corruption; they are not independent release signatures. Release/package
artifacts are unsigned and require trust in this repository and its maintainers.
Installation requires user confirmation and normal administrator authorization.

The standalone `velum-install.sh` release asset bootstraps first-time installs
from the same official GitHub release API. It checks the source archive SHA-256,
rejects unsafe archive paths/links/devices, and extracts to a private temporary
directory before running the ordinary installer. Its initial HTTPS download
requires trust in the release publisher; checksums do not establish an independent
signature. Existing installations use the updater. `--check` downloads and verifies
only and does not install missing dependencies or change system settings.
