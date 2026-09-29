#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
  printf '%s\n' 'Run with sudo to uninstall the system package.' >&2
  exit 1
fi
/usr/lib/velum/recover
systemctl disable velum.socket
pacman -R velum-vpn
printf '%s\n' 'Private profiles remain in your user configuration directory.'
