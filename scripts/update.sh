#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHONPATH="$PWD/src" exec python -m velum.updates "$@"
