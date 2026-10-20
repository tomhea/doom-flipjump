"""M8 (docs/episode-plan.md G15): every E1 map has its committed fixture wad, and each is exactly what
`tests/fixtures/make_e1m1_wad.py <map>` makes from the dev Freedoom wad -- so CI and the gates read the map the
pipeline was built on, and a stale or hand-edited fixture is caught.

The reproduction needs `assets/freedoom1.wad` (gitignored; `bash scripts/fetch_freedoom.sh`): skipped without it.
The negative control (R9) flips one byte of a fixture's bytes and requires the comparison to reject it.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
SRC = ROOT / "assets" / "freedoom1.wad"
MAPS = ["E1M%d" % k for k in range(1, 10)]


def _maker():
    spec = importlib.util.spec_from_file_location("make_e1m1_wad", FIX / "make_e1m1_wad.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _same(a: bytes, b: bytes) -> bool:
    return hashlib.sha256(a).digest() == hashlib.sha256(b).digest()


@pytest.mark.parametrize("m", MAPS)
def test_fixture_present_and_names_its_map(m):
    from doomfj.wad import WadFile
    p = FIX / ("freedoom_%s.wad" % m.lower())
    assert p.exists(), "%s missing: python tests/fixtures/make_e1m1_wad.py %s" % (p.name, m)
    w = WadFile.from_path(str(p))
    assert w.linedefs(m) and w.sectors(m) and w.things(m), m


@pytest.mark.skipif(not SRC.exists(), reason="assets/freedoom1.wad absent (scripts/fetch_freedoom.sh)")
@pytest.mark.parametrize("m", MAPS)
def test_fixture_is_the_makers_output(m):
    want = _maker().build_e1m1_wad(SRC, MAP=m)
    got = (FIX / ("freedoom_%s.wad" % m.lower())).read_bytes()
    assert _same(got, want), "%s differs from make_e1m1_wad.py %s's output: regenerate it" % (m, m)


@pytest.mark.skipif(not SRC.exists(), reason="assets/freedoom1.wad absent (scripts/fetch_freedoom.sh)")
def test_control_a_flipped_byte_is_rejected():
    want = _maker().build_e1m1_wad(SRC, MAP="E1M5")
    bad = bytearray(want)
    bad[len(bad) // 2] ^= 1
    assert _same(bytes(want), want) and not _same(bytes(bad), want)
