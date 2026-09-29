#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
printf '%s\n' 'GUI development setup complete. Install the Arch package for privileged networking.'
