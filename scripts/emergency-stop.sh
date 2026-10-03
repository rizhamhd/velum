#!/bin/sh
# pkexec runs only this installed, root-owned entry point.
exec /usr/bin/python -I -m velum.services.emergency "$@"
