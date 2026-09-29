#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHONPATH=src python -m unittest discover -s tests -v
ruff check .
