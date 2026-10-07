"""M7 P8a package C: the compositor rules' EMITTED footprint, proven against the frozen "full" text.

The game tier is emitted ONCE with the compositor rule forced on (`world.compositor_d3` patched to True and
GAME_RENDER_KW's two D3 keys flipped with it; the modes stay "full" / "full", so no other P8a hook is emitted) and
every part is compared with scratchpad/cr/emit_baseline.json's
`standalone` hashes (the "full" game tier, blocked51's text) after removing EXACTLY the D3 lines:

  * the baked barrels' xor_by blocks:     `    hex.xor_by 1, sp_ex, 1`           (every state of every baked barrel)
  * the runtime barrels' row selects:     `    hex.set 1, sp_ex, 1`
  * the D3 cells (monstercode.D3_DECLS):  `td_rk: hex.vec 2`, `sp_ex: hex.vec 1`
  * the depth walk's call:                `sim.thing_pass_depth ..., sp_lt_hi, <rank0>, 1` -> `..., sp_lt_hi`
  * the record bodies' scenery count:     `frame.thing_record_body ..., 1, <3|0x100>, 255, ...` -> `..., 1, 3, 255, ...`

Every part must then be SAME -- so the rule adds those lines and nothing else -- and each kind must occur the number of
times the map says (20 baked barrels x 7 states, the runtime barrels, 3 record bodies, 1 walk, the 2 cells).

R9 (`--selftest`, on the same emission): the comparison with ONE transform left out must fail (each in turn), so a
stripping that hides a difference is caught. Heavy: one game-tier emission (~7 min, several GB) -- run it solo.

    python scratchpad/gp/p8_d3_emit_check.py [--selftest]
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

BASELINE = ROOT / "scratchpad/cr/emit_baseline.json"


def emit_d3():
    from doomfj import world
    from doomfj.config import Config
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE, emit_wall_renderer
    assert (MONSTER_MODE, PLAYER_MODE) == ("full", "full"), "the check forces D3 alone on top of the 'full' tier"
    from doomfj.reference_model import D3_RENDER_KW, GAME_RENDER_KW
    saved, kw_saved = world.compositor_d3, dict(GAME_RENDER_KW)
    world.compositor_d3 = lambda pm: True
    GAME_RENDER_KW.update(D3_RENDER_KW)       # the oracle's keys flipped with it (the emitter asserts they agree)
    try:
        mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
        aw = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
        parts = emit_wall_renderer(mw, "E1M1", Config(), asset_wad=aw, sprite_wad=aw, return_parts=True, tier="game")
    finally:
        world.compositor_d3 = saved
        GAME_RENDER_KW.clear()
        GAME_RENDER_KW.update(kw_saved)
    return [(n, "\n".join(ls) if isinstance(ls, list) else ls) for n, ls in parts]


def rank0_of(text):
    m = re.search(r"^sim\.thing_pass_depth .*, sp_lt_hi, (\d+), 1$", text, re.M)
    return int(m.group(1)) if m else None


def transforms():
    from doomfj.reference_model import DEG_SOFT_SCENERY
    from doomfj.wall_renderer import D3B_SOFT_FLAG
    d3s = DEG_SOFT_SCENERY | D3B_SOFT_FLAG
    rec = re.compile(r"^(frame\.thing_record_body (?:[^,]*, ){13})%d, " % d3s, re.M)   # dsofts: the 14th argument
    return {
        "xor_by sp_ex": (re.compile(r"^    hex\.xor_by 1, sp_ex, 1\n", re.M), ""),
        "select sp_ex": (re.compile(r"^    hex\.set 1, sp_ex, 1\n", re.M), ""),
        "D3 cells": (re.compile(r"^(td_rk: hex\.vec 2|sp_ex: hex\.vec 1)\n", re.M), ""),
        "walk rank0": (re.compile(r"^(sim\.thing_pass_depth .*, sp_lt_hi), \d+, 1$", re.M), r"\1"),
        "record dsofts": (rec, r"\g<1>%d, " % DEG_SOFT_SCENERY),
    }


def strip(text, skip=None):
    counts = {}
    for name, (rx, rep) in transforms().items():
        if name == skip:
            continue
        text, n = rx.subn(rep, text)
        counts[name] = n
    return text, counts


def compare(parts, want, skip=None):
    same, counts = {}, {}
    for pname, text in parts:
        t, c = strip(text, skip)
        for k, v in c.items():
            counts[k] = counts.get(k, 0) + v
        same[pname] = hashlib.sha256(t.encode()).hexdigest() == want[pname][0]
    return same, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="R9: each transform left out must make the check FAIL")
    a = ap.parse_args()
    want = json.loads(BASELINE.read_text(encoding="utf-8"))["configs"]["standalone"]
    t = time.perf_counter()
    parts = emit_d3()
    print("emitted the game tier with D3 forced on: %.0f s" % (time.perf_counter() - t), flush=True)
    same, counts = compare(parts, want)
    rank0 = [r for r in (rank0_of(x) for _n, x in parts) if r is not None]
    for pname, ok in same.items():
        print("  %-16s %s" % (pname, "SAME" if ok else "!! DIFFERS"))
    print("  the D3 lines removed: %s; the walk's rank0 %s" % (counts, rank0))
    from doomfj.world import FIREBALL_POOL
    ok = all(same.values()) and counts["walk rank0"] == 1 and counts["record dsofts"] == 3 and counts["D3 cells"] == 2
    ok &= counts["xor_by sp_ex"] > 0 and counts["xor_by sp_ex"] % 7 == 0 and counts["select sp_ex"] >= 1
    ok &= len(rank0) == 1 and rank0[0] > FIREBALL_POOL
    print("D3 EMISSION: %s" % ("ONLY THE D3 LINES (every part SAME once they are removed)" if ok else "!! FAIL"))
    if a.selftest:
        ctl = True
        for name in transforms():
            s_, _c = compare(parts, want, skip=name)
            caught = not all(s_.values())
            ctl &= caught
            print("  control: %-14s left in -> %s" % (name, "CAUGHT (a part differs)" if caught else "!! NOT CAUGHT"))
        print("SELFTEST: %s" % ("PASS" if ctl else "!! FAIL"))
        ok &= ctl
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
