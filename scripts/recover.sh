#!/bin/sh
# Explicit root-only recovery stops the supervisor before replaying its journal.
set -eu
if [ "$(id -u)" -ne 0 ]; then
  printf '%s\n' 'Run with sudo to recover Velum-owned networking.' >&2
  exit 1
fi
systemctl stop velum.socket velum.service
exec /usr/bin/python -I -m velum.services.helper --recover
