#!/bin/sh
# Root opt-in; all networking changes occur in a disposable network namespace.
set -eu
cd "$(dirname "$0")/.."
if [ "${1:-}" != '--root-network-namespace' ] || [ "$(id -u)" -ne 0 ]; then
  printf '%s\n' 'Usage: sudo ./scripts/integration.sh --root-network-namespace' >&2
  exit 2
fi
exec unshare --net --fork env PYTHONPATH="$PWD/src" python tests/integration_network.py
