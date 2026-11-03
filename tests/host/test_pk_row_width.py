"""M8 l12fix (E1M5): the pickup's drop row register `pk_t` is as wide as the rows the EMITTER sets it to.

`lootcode.pickup_lines` sets `pk_t` to dropper k's runtime row and `pk_drop` moves it into the row offset; on a
wide-list map those rows pass 255 (E1M5: 275), and at 2 nibbles `hex.set 2, pk_t, 275` silently kept 0x13 (m2_std_gate
parted at frame 94). This holds the emitted text to `lootcode.pk_row_nibbles`, on E1M1's real World and pickup slots:

  * the E1M1 rows (all < 256): pk_t 2 nibbles, the declaration `pk_t: hex.vec 2`, every set and the move at 2 --
    the text E1M1 / E1M2 always had;
  * the same World with its drops placed at rows 250 .. 250 + k (past 255): every `hex.set n, pk_t, v` has
    v < 16**n, the declaration (loot_parts' pk_row_nibbles of drop_rows) and the move are 3.

CONTROL (R9): pk_row_nibbles forced to 2 on the wide rows -- a set truncates, and the scan names it.
tests/fj/test_pk_drop_wide_rows_fj.py RUNS pk_drop at rows past 255.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"


@pytest.fixture(scope="module")
def world():
    if not ART.exists():
        pytest.skip("needs assets/freedoom1.wad (the sprite art)")
    from doomfj import lootcode as L
    from doomfj.config import Config
    from doomfj.reference_model import ReferenceModel
    from doomfj.wad import WadFile
    from doomfj.world import World
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ART))
    w = World(mw, "E1M1")
    rm = ReferenceModel(Config())
    slots = L.pickup_slots(w, rm, mw, "E1M1", art)
    assert L.droppers(w), "E1M1 has droppers"
    return w, slots


def _emit(world, drop_rt):
    from doomfj import lootcode as L
    w, slots = world
    mon_rt = list(range(len(w.mon_things)))
    lines = L.pickup_lines(w, slots, mon_rt, drop_rt=drop_rt)
    nib = L.pk_row_nibbles(L.drop_rows(w, mon_rt, drop_rt))
    decl = [d for d in L.loot_decls({c: 0 for c, *_ in L.CELLS}, nib) if d.startswith("pk_t:")]
    return lines, decl


def _scan(lines):
    """-> (the widths pk_t is set / moved at, the truncated sets)"""
    widths, bad = set(), []
    for ln in lines:
        m = re.search(r"hex\.set (\d+), pk_t, (\d+)", ln)
        if m:
            n, v = int(m.group(1)), int(m.group(2))
            widths.add(n)
            if v >= 16 ** n:
                bad.append(ln.strip())
        m = re.search(r"hex\.mov (\d+), pk_off, pk_t", ln)
        if m:
            widths.add(int(m.group(1)))
    return widths, bad


def test_e1m1_rows_keep_the_two_nibble_text(world):
    lines, decl = _emit(world, None)
    assert _scan(lines) == ({2}, []) and decl == ["pk_t: hex.vec 2"]


def test_rows_past_255_widen_pk_t(world):
    w, _s = world
    rows = [250 + k * 3 for k in range(len(__import__("doomfj.lootcode", fromlist=["x"]).droppers(w)))]
    assert max(rows) > 255
    lines, decl = _emit(world, rows)
    assert _scan(lines) == ({3}, []) and decl == ["pk_t: hex.vec 3"]


def test_control_a_two_nibble_pk_t_truncates(world, monkeypatch):
    from doomfj import lootcode as L
    w, _s = world
    rows = [250 + k * 3 for k in range(len(L.droppers(w)))]
    monkeypatch.setattr(L, "pk_row_nibbles", lambda rows: 2)
    widths, bad = _scan(_emit(world, rows)[0])
    assert widths == {2} and bad, "the scan must name the truncated sets"
