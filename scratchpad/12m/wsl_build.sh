#!/usr/bin/env bash
# Build the flipjump native engine inside WSL and report what THP granted.
#
# The point of running here is that Linux gives huge pages to any user via
# madvise(MADV_HUGEPAGE) -- no privilege, unlike Windows' SeLockMemoryPrivilege. The engine's
# fj_alloc_flat asks for them; this script builds it and the companion wsl_speed.py measures
# whether the kernel actually granted them (AnonHugePages in /proc/self/smaps).
set -euo pipefail

SRC=/mnt/c/Users/tomhe/Documents/flipjump-151
DST=$HOME/fj/flipjump-151

echo "--- syncing engine source into the WSL filesystem (building on /mnt/c is slow) ---"
mkdir -p "$HOME/fj"
rm -rf "$DST"
mkdir -p "$DST/flipjump/interpreter"
# copy only what the build needs; the repo has large test/program trees
cp -r "$SRC/flipjump" "$DST/" 2>/dev/null || true
cp "$SRC/setup.py" "$SRC/pyproject.toml" "$DST/" 2>/dev/null || true
cd "$DST"
rm -rf build ./*.egg-info
find . -name '*.pyd' -delete 2>/dev/null || true
find . -name '*.so' -delete 2>/dev/null || true

echo "--- python/gcc ---"
python3 -VV | head -1
gcc --version | head -1

echo "--- building _fjcore ---"
python3 setup.py build_ext --inplace 2>&1 | tail -8

echo "--- result ---"
ls -l flipjump/interpreter/_fjcore*.so 2>/dev/null || echo "NO .so BUILT"
python3 - <<'PY'
import sys
sys.path.insert(0, '.')
try:
    from flipjump.interpreter import _fjcore
    print("native engine imports OK")
    from flipjump import is_native_engine_active
    print("is_native_engine_active:", is_native_engine_active())
except Exception as e:
    print("IMPORT FAILED:", e)
PY
