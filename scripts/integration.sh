#!/bin/sh
# Explicit opt-in. Networking changes only occur in a disposable namespace.
set -eu
cd "$(dirname "$0")/.."
VELUM_ORIGINAL_NETNS=$(readlink /proc/self/ns/net)
export VELUM_ORIGINAL_NETNS
case "${1:-}" in
  --root-network-namespace)
    test "$(id -u)" -eq 0 || { echo 'Run this mode with sudo.' >&2; exit 2; }
    exec unshare --net --fork env PYTHONPATH="$PWD/src" python tests/integration_network.py
    ;;
  --user-network-namespace)
    exec unshare --user --map-root-user --net --fork env PYTHONPATH="$PWD/src" python tests/integration_network.py
    ;;
  *)
    echo 'Usage: sudo ./scripts/integration.sh --root-network-namespace' >&2
    echo 'Or: ./scripts/integration.sh --user-network-namespace' >&2
    exit 2
    ;;
esac
