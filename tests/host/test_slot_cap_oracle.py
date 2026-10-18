"""M8 F1.4 (docs/f1-big-map-widths.md section 1, option B) -- THE SLOT CAP's model rules, in the oracle.

reference_model.render_wall_frame counts `n_slots` (the fj's `gps_nslot`) where the fj increments it -- past every
reject -- and turns a thing away once the frame has handed out `SPR_SLOT_CAP` ids (config.MAP_CONFIG: E1M2 255; 0 =
none, E1M1's), tested before the count budgets as frame.thing_record_body tests it. tests/fj/test_slot_cap_fj.py runs
the fj against this oracle's `slot_trace`; this file holds the oracle's own rules:

  * a cap no frame reaches draws exactly the uncapped picture; one it reaches draws less, and only the walk's tail;
  * the AIM rule: a capped monster with a seen flag is still aimed (the fj's seen probe projects it through the aim
    hook -- DOOM's hitscan never depends on the vissprite cap), every other capped thing is not;
  * the map's cap reaches every oracle a gate builds: MAP_CONFIG over the model's own Config.

R9: each of MUTANTS -- one real edit of reference_model.py, run on a copy of src/ -- must fail this file.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from doomfj.config import GAME_CFG, MAP_CONFIG
from doomfj.reference_model import GAME_RENDER_KW, ReferenceModel, build_scene, spawn_state
from doomfj.wad import Thing, WadFile

ROOT = Path(__file__).resolve().parents[2]
_KINDS = [3004, 9, 3001, 3002, 58, 2001, 2007, 2028, 2011, 2012, 2014, 2015, 2018, 2019, 2035]
ROOM = tuple((40 + (i % 10) * 18, 150 + (i // 10) * 30, _KINDS[i % len(_KINDS)]) for i in range(30))
# the aim rule's room: four lamps beside the line of fire take ids 1..4, then a zombieman and, behind him, a barrel
# on the line (the aim window's columns) -- both turned away by a cap of 4
AIM_ROOM = ((92, 175, 2028), (164, 175, 2028), (100, 185, 2028), (156, 185, 2028), (128, 215, 3004), (128, 240, 2035))
_RIGS = {}


def rig(room):
    if room not in _RIGS:
        mw = WadFile.from_path(ROOT / "tests/fixtures/square_room.wad")
        base = mw.things
        mw.things = lambda name, base=base: base(name) + [Thing(x, y, 0, t, 7) for x, y, t in room]
        _RIGS[room] = dict(mw=mw, sw=WadFile.from_path(ROOT / "assets/freedoom1.wad"),
                           scene=build_scene(mw, WadFile.from_path(ROOT / "tests/fixtures/freedoom_assets.wad"),
                                             "MAP01"))
    return _RIGS[room]


def render(cap, *, seen=True, aim_things=None, mapname="MAP01", room=ROOM):
    r = rig(room)
    rm = ReferenceModel(replace(GAME_CFG, SPR_SLOT_CAP=cap))
    trace, aim_out = [], None
    kw = {}
    if aim_things is not None:
        lo, hi = rm.aim_window_cols()
        aim_out = [0] * (hi - lo + 1)
        kw = dict(aim_things=aim_things, aim_out=aim_out)
    st = spawn_state(r["mw"], "MAP01")
    frame = rm.render_wall_frame(replace(st, level=mapname), r["scene"], sprite_wad=r["sw"],
                                 seen_out=set() if seen else None, slot_trace=trace, **kw, **GAME_RENDER_KW)
    return bytes(frame), trace, aim_out


def test_the_slots_are_counted_at_the_increment_and_capped():
    _f0, free, _ = render(0)
    _f4, capped, _ = render(4)
    ids = [h for *_x, h in free if isinstance(h, int)]
    assert ids == list(range(1, len(ids) + 1)) and len(ids) > 5, "one id per thing past every reject, in walk order"
    # the capped walk: the same outcomes up to the 4th id, then every thing that would have reached the budget test
    # is turned away -- including the ones the projection or the off-view test would have rejected (tested after)
    k = next(n for n, e in enumerate(free) if e[3] == 4)
    assert capped[:k + 1] == free[:k + 1]
    assert all(e[3] == "C" for e in capped[k + 1:]) and len(capped) == len(free)


def test_a_cap_no_frame_reaches_draws_the_uncapped_picture():
    f0, free, _ = render(0)
    n = max(h for *_x, h in free if isinstance(h, int))
    assert render(n)[0] == f0                      # the cap reached exactly at the last id: nothing turned away
    assert render(255)[0] == f0
    assert render(4)[0] != f0                      # R9: a cap the frame reaches turns drawn things away


def test_a_capped_monster_with_a_seen_flag_is_still_aimed():
    """the fj's capped monster takes the seen probe, whose projection runs the aim hook; a capped thing without that
    path (scenery -- here the barrel -- or any thing in a body without the seen rule) records no aim. Each case aims
    ONE capped thing, so nothing nearer hides what the rule decides"""
    _f, trace, _ = render(4, room=AIM_ROOM)
    assert [h for *_x, h in trace] == [1, 2, 3, 4, "C", "C"], trace
    assert [(d, a, e) for d, a, e, _h in trace][4:] == [(4, True, False), (5, False, True)]
    for d, seen, kept in ((4, True, True), (4, False, False), (5, True, False), (5, False, False)):
        aim = {d: (d + 1, 20)}
        _f, _t, uncapped = render(0, seen=seen, aim_things=aim, room=AIM_ROOM)
        assert set(uncapped) == {d + 1}, "the thing fills the aim window uncapped"
        _f, _t, got = render(4, seen=seen, aim_things=aim, room=AIM_ROOM)
        assert got == (uncapped if kept else [0] * len(got)), (d, seen, got)


def test_the_map_cap_reaches_the_oracle():
    """MAP_CONFIG's cap applies whatever Config the model was built with (a gate's ReferenceModel(GAME_CFG)) -- shown
    on this room with a temporary entry for its map name, and gone with it"""
    f0 = render(0)[0]
    MAP_CONFIG["MAP01"] = {"SPR_SLOT_CAP": 4}
    try:
        assert render(0)[0] == render(4)[0] != f0
    finally:
        del MAP_CONFIG["MAP01"]
    assert render(0)[0] == f0


MUTANTS = [
    ("the aim ignores the cap", "and not (slot_capped and not (seen_out is not None and mon))\n", "\n"),
    ("the aim drops every capped thing", "and not (slot_capped and not (seen_out is not None and mon))\n",
     "and not slot_capped\n"),
    ("the slot counted before the projection's reject", "                    if act:\n                        n_mon += 1\n",
     "                    n_slots += 1\n                    if act:\n                        n_mon += 1\n"),
    ("the cap one late", "slot_capped = bool(slot_cap) and n_slots >= slot_cap",
     "slot_capped = bool(slot_cap) and n_slots > slot_cap"),
    ("the map's cap not read", "slot_cap = map_cfg(self.cfg, scene.mapname).SPR_SLOT_CAP", "slot_cap = self.cfg.SPR_SLOT_CAP"),
]


@pytest.mark.parametrize("label, old, new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutant_of_the_oracle_fails_this_file(label, old, new):
    with tempfile.TemporaryDirectory() as t:
        shutil.copytree(ROOT / "src", Path(t) / "src")
        p = Path(t) / "src/doomfj/reference_model.py"
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, "the mutant's text is not in reference_model.py: %s" % label
        p.write_text(text.replace(old, new), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "not mutant",
                            str(Path(__file__).resolve())], capture_output=True, text=True, cwd=ROOT, timeout=600,
                           # the CI shard (PYTEST_SHARD) would deselect the inner run: 0 tests, rc 5 -- it is the WHOLE file
                           env={k: v for k, v in dict(os.environ, PYTHONPATH=str(Path(t) / "src")).items()
                                if k != "PYTEST_SHARD"})
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
    assert r.returncode == 1 and " failed" in tail and "error" not in tail, (label, tail)
