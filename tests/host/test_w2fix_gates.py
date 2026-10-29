"""M8 w2fix: the E1M8 / E1M9 / E1M5 gate findings, host side.

  * E1M8 fight F9l ("nukage's rim"): the pose (840, 200) overlapped the firestick at (864, 224) -- no move stands the
    player there, and there the fj's floor test (the player's cells WITH the static blockers: a refused box reads the
    seed floor) and the model's (`_on_sector_floor`, the lines alone) disagree. `fight_gate.poses_in_sector` skips a
    pose a static blocker overlaps when it reads the floor; control: the old candidate list still holds (840, 200).
  * fight / die counters: a map whose monsters never drop owes no drop counter (`fight_gate.map_cannot`: E1M8's four
    Barons); control: E1M1 owes them. The blood (`fx_spawns`) is I1's and C2's (OWNS); control: one of them runs.
  * a ONE-door map's `dstate` reads as an int (probe.read_cells): gamespeed_trail / b0 / b0_scenarios compare a tuple
    (`door_reading`, `_doors_tuple`); control: the int itself fails the trail's door index.
  * E1M9 fight F1 (aim_sid all 0 where the model has 252): the GR line's record sat after PASS 1, which never writes
    `drawn`; `wall_renderer.solid_seg_call_lines` puts it after pass 2; a seg without a GR line emits no record.
  * the survey lists the closing doors whose pass state is their top (E1M5's 12); E1M2 has none; E1M1's door 84 is one
    and keeps the old step (config.DOOR_TOP_STEP_LEGACY), so E1M1's emission is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", ROOT / "scratchpad" / "gp", ROOT / "scripts"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))


def _wad(m):
    from doomfj.wad import WadFile
    return WadFile.from_path(ROOT / "tests" / "fixtures" / ("freedoom_%s.wad" % m.lower()))


def test_a_map_whose_monsters_never_drop_owes_no_drop_counter():
    import fight_gate as FG
    assert FG.map_cannot(_wad("E1M8").things("E1M8")) == {"pickup_drops", "drop_frames"}   # four Barons
    assert FG.map_cannot(_wad("E1M1").things("E1M1")) == set()            # control: zombiemen drop clips


def test_the_blood_is_owned_by_i1_and_c2():
    import fight_gate as FG
    tags = ["F1", "I1", "C2"]
    assert FG.unowed(("fx_spawns",), tags, {"I1", "C2"}) == ["fx_spawns"]
    assert FG.unowed(("fx_spawns",), tags, {"I1"}) == []                  # control: C2 runs -> owed


def test_a_one_door_reading_is_a_tuple():
    import gamespeed_trail as GT
    import b0
    import b0_scenarios
    assert GT.door_reading(3) == (3,) and GT.door_reading((1, 2)) == (1, 2)
    assert b0._doors_tuple(0) == (0,) and b0_scenarios._doors_tuple((0, 4)) == (0, 4)
    pose = (1 << 16, 2 << 16, 0)
    trail = [pose + (GT.door_reading(0), 0)]
    v = GT.verdicts({0: (trail, 1)}, [[pose + ((0,),)]], [[pose + (None,)]], [[pose + ((1,),)]], [1])
    assert v[3] is True and v[2] == [0]
    with pytest.raises(TypeError):                                      # control: the raw int reading
        GT.verdicts({0: ([pose + (0, 0)], 1)}, [[pose + ((0,),)]], [[pose + (None,)]], [[pose + ((1,),)]], [1])


def test_the_shot_record_follows_pass_2():
    from doomfj import wall_renderer as wr
    from doomfj.scrollcode import PASS2_CALL
    rc = ["    stl.fcall seg7_render_consts, xb_ret"]
    out = wr.solid_seg_call_lines(7, 3, rc, [PASS2_CALL], 2)
    rec = out.index("    stl.fcall shot_rec, shr_ret")
    assert out.index(PASS2_CALL) < rec < len(out) - 1 - out[::-1].index(rc[0])      # pass 2, the record, the CLEAR
    assert max(i for i, ln in enumerate(out) if "shr_pre" in ln) < out.index("    stl.fcall seg_pass1_leaf, seg_ret")
    plain = wr.solid_seg_call_lines(7, 3, rc, [PASS2_CALL])
    assert not [ln for ln in plain if "shr" in ln or "shot_rec" in ln]
    assert plain == ["    stl.fcall seg7_geom_consts, xb_ret", "    stl.fcall seg_pass1_leaf, seg_ret",
                     "    hex.if0 1, proceed, ss3_seg7_unseen", *rc, PASS2_CALL, *rc, "  ss3_seg7_unseen:",
                     "    stl.fcall seg7_geom_consts, xb_ret"]                # the text every non-GR seg emitted


def test_the_survey_lists_top_pass_doors():
    from level_survey import top_pass_doors
    w5 = _wad("E1M5")
    assert 12 in top_pass_doors(w5.sectors("E1M5"), w5.linedefs("E1M5"), w5.sidedefs("E1M5"))
    w2 = _wad("E1M2")
    assert top_pass_doors(w2.sectors("E1M2"), w2.linedefs("E1M2"), w2.sidedefs("E1M2")) == []   # its text unchanged
    w1 = _wad("E1M1")                           # E1M1's door 84 is one: it keeps the old step (its emission identical)
    assert top_pass_doors(w1.sectors("E1M1"), w1.linedefs("E1M1"), w1.sidedefs("E1M1")) == [84]
    from doomfj.config import DOOR_TOP_STEP_LEGACY
    assert DOOR_TOP_STEP_LEGACY == {"E1M1"}


def test_the_rim_pose_skips_a_static_blocker(monkeypatch):
    import gate_targets as GT
    import fight_gate as FG
    ctx = GT.Ctx("E1M8")
    w, d = ctx.w, ctx.dsim
    assert not FG.statics_clear(w, 840 << 16, 200 << 16)               # the firestick at (864, 224)
    assert FG.statics_clear(w, 840 << 16, 256 << 16)
    got = FG.poses_in_sector(d, w, 10, step=8, ledge=True)[:12]
    assert got and all(FG.statics_clear(w, p[0], p[1]) for p in got)
    monkeypatch.setattr(FG, "statics_clear", lambda *a: True)          # control: the old list
    assert (840 << 16, 200 << 16) == FG.poses_in_sector(d, w, 10, step=8, ledge=True)[0][:2]
