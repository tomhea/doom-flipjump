#!/usr/bin/env bash
# MUST exit non-zero on any failing test (CR-ist R1 relies on this)
set -euo pipefail
PYTHONIOENCODING=utf-8 python -m pytest -q "$@"
