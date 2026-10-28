#!/usr/bin/env bash
set -euo pipefail
# M0 toolchain smoke build.
PYTHONIOENCODING=utf-8 python -m doomfj.build
