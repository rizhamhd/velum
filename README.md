# Velum

A Linux desktop client for legally obtained VLESS services. Python / Qt6 frontend,
Xray engine, and a separately authorized Linux networking helper.

**Development release: not yet audited or certified for production use.** Live VPN,
network migration, and hotspot acceptance require testing with your own provider.
No credentials or subscriptions are distributed with this project.

## Architecture

The GUI runs as your user. A fixed, packaged helper is launched through Polkit.
It accepts validated profiles, never shell commands. Full-device routing uses a
TUN adapter backed by Xray. See [architecture](docs/ARCHITECTURE.md) and
[networking](docs/NETWORKING.md).

## Development

`PYTHONPATH=src python -m unittest discover -s tests -v`

`ruff check .`

Installation and operating instructions are expanded alongside implementation.
