# Contributing

Use Python 3.11+ and the dependencies in pyproject.toml. Run `scripts/check.sh`
before proposing changes. Keep parsing, GUI, engine, and privileged networking
separate. New parameters need validation and generation tests; never silently
ignore unsupported imported options.

Normal tests must mock privileged operations. Use `scripts/integration.sh` only
with its explicit namespace option. Do not test new routing code on a contributor's
host default route. New mutations need write-ahead rollback, ownership checks,
failure-injection tests, and documentation of kill-switch behavior.

Never commit real credentials, profile exports, runtime journals, or screenshots
of provider secrets. Use reserved documentation IPs/domains and dummy UUIDs.
Describe which checks actually ran, not just which checks exist. Changes affecting
protection require namespace packet tests and the relevant live release gates in
docs/TESTING.md before production release.

The repository currently has no configured upstream or release-signing identity.
Before publishing, configure the actual repository URL, security contact/private
reporting, and signed release process; do not invent maintainer identities.
