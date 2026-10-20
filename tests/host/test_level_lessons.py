"""docs/level-lessons.md: the survey checks a mistake earned (scripts/level_survey.py `Survey.lessons`) and emit_check's
stale stand-in refusal -- each with its NEGATIVE CONTROL (R9): the mistake put back (the legacy door rule, a lift-less
restart, the pre-fix thvis mirror, a flag turned on ...) must turn the row bad, so a check that checks nothing cannot
pass. Light: the survey runs the model's own functions (seconds a map), no emission.
"""
import dataclasses
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ls():
    return _load("level_survey", "scripts/level_survey.py")


@pytest.fixture(scope="module")
def wad(ls):
    return ls.WadFile.from_path(str(ASSET))


def _survey(ls, wad, m):
    return ls.Survey(wad, m, wad).run()


@pytest.fixture(scope="module")
def e1m1(ls, wad):
    return _survey(ls, wad, "E1M1")


@pytest.fixture(scope="module")
def e1m2(ls, wad):
    return _survey(ls, wad, "E1M2")


def _row(sv, prefix):
    hits = [r for r in sv.rows if r[1].startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


def test_no_lesson_section_errors_on_the_shipped_maps(e1m1, e1m2):
    for sv in (e1m1, e1m2):
        assert not [r for r in sv.rows if r[1].startswith("lesson:")], sv.m      # a guard row = a section raised


# ---- the door clearance (E1M2 playtest: blue door 54 at 12 units, a0af8d4f)
def test_every_shipped_door_opens_past_the_player(e1m1, e1m2):
    for sv in (e1m1, e1m2):
        assert _row(sv, "doors the player can pass")[0] == "OK"


def test_control_the_legacy_neighbour_rule_on_e1m2_traps_door_54(ls, wad, monkeypatch):
    from doomfj import doors
    monkeypatch.setattr(doors, "door_neighbours", lambda secs, lds, sds: doors.neighbours(lds, sds))
    r = _row(_survey(ls, wad, "E1M2"), "doors the player can pass")
    assert r[0] == "WARN" and "(54, 136, 148)" in r[4], r


# ---- back sides without ML_TWOSIDED (the CR of #148: two getNextSector rules)
def test_back_side_flags(e1m1, e1m2):
    assert _row(e1m1, "lines with a back side but no ML_TWOSIDED")[0] == "OK"
    assert _row(e1m2, "lines with a back side but no ML_TWOSIDED")[0] == "OK"


def test_control_a_cleared_two_sided_flag_is_reported(ls, wad):
    from doomfj import gamedata as gd
    sv = ls.Survey(wad, "E1M1", wad)
    i = next(k for k, ld in enumerate(sv.lds) if ld.back not in (0xFFFF, -1) and ld.flags & gd.ML_TWOSIDED)
    sv.lds = list(sv.lds)
    sv.lds[i] = dataclasses.replace(sv.lds[i], flags=sv.lds[i].flags & ~gd.ML_TWOSIDED)
    sv._twosided_flags()
    r = _row(sv, "lines with a back side but no ML_TWOSIDED")
    assert r[0] == "WARN" and str(i) in r[4]


# ---- the legacy door rule is E1M1's flag (the CR of #148; #149: MAP_CONFIG DOOR_NEIGHBOURS, not a fingerprint)
def test_neighbour_rule(e1m1, e1m2):
    assert _row(e1m1, "door neighbour rule")[:3] == ("OK", "door neighbour rule (doors.door_neighbours)",
                                                      "legacy (E1M1, MAP_CONFIG DOOR_NEIGHBOURS)")
    assert _row(e1m2, "door neighbour rule")[:3] == ("OK", "door neighbour rule (doors.door_neighbours)",
                                                      "DOOM's two-sided")


def test_control_another_map_asking_for_the_legacy_rule_is_wrong(ls, wad, monkeypatch):
    from doomfj import config
    sv = ls.Survey(wad, "E1M2", wad)
    monkeypatch.setitem(config.MAP_CONFIG, "E1M2", {**config.MAP_CONFIG["E1M2"], "DOOR_NEIGHBOURS": "legacy"})
    sv._neighbour_rule()
    assert _row(sv, "door neighbour rule")[0] == "WRONG"


def test_control_a_rule_that_ignores_the_flag_is_wrong(ls, wad, monkeypatch):
    from doomfj import doors
    sv = ls.Survey(wad, "E1M2", wad)
    monkeypatch.setattr(doors, "door_neighbours", lambda secs, lds, sds: doors.neighbours(lds, sds))
    sv._neighbour_rule()
    assert _row(sv, "door neighbour rule")[0] == "WRONG"


# ---- NEW GAME restarts the floor groups (#147: fswitch zeroed only with a lift)
def test_shipped_maps_restart_their_floors(e1m1, e1m2):
    assert _row(e1m1, "NEW GAME restarts the floor groups")[0] == "OK"
    assert _row(e1m2, "NEW GAME restarts the floor groups")[0] == "OK"


def test_floor_groups_without_a_lift_restart(ls, wad, monkeypatch):
    """M8 C4 fixed #147 (lesson L36): `restart_lines(nfloor=)` zeroes `fswitch` on a map with no lift too"""
    from doomfj import movers
    monkeypatch.setattr(movers, "lift_states", lambda *a, **k: {})
    sv = ls.Survey(wad, "E1M2", wad)
    sv._restart_floors()
    r = _row(sv, "NEW GAME restarts the floor groups")
    assert r[0] == "OK" and r[2] == "11 groups, 0 lifts", r


def test_control_floor_groups_without_a_lift_are_wrong(ls, wad, monkeypatch):
    """R9: the restart as it was before M8 C4 (no `nfloor`: fswitch zeroed only with a lift) is WRONG again"""
    from doomfj import movers, wall_renderer
    monkeypatch.setattr(movers, "lift_states", lambda *a, **k: {})
    real = wall_renderer.restart_lines
    monkeypatch.setattr(wall_renderer, "restart_lines", lambda *a, **k: real(*a, **{**k, "nfloor": 0}))
    sv = ls.Survey(wad, "E1M2", wad)
    sv._restart_floors()
    r = _row(sv, "NEW GAME restarts the floor groups")
    assert r[0] == "WRONG" and r[2] == "11 groups, 0 lifts", r


# ---- the renderer's per-seg machines (the CR of #146, BLOCKING: lines shut at every state)
def test_shut_gate_is_the_emitters_rule(ls):
    g = ls.Survey.shut_gate
    from doomfj.wall_renderer import seg_shut_gate
    assert all(g(st, d) == seg_shut_gate(st, d) for st, d in (([True, True, False], [3]), ([True] * 4, [2, 2])))
    assert g([False] * 4, [4]) == "never" and g([True] * 4, [4]) == "every"
    assert g([True, False, False], [3]) == (0, 1)           # exactly state 0: the one-op hex.if0 (E1M1's doors)
    assert g([False, True, True], [3]) == (0, 0b110)        # M8 C4: open at state 0, shut later -- a mask gate
    assert g([True, True, False], [3]) == (0, 0b011)        # shut past state 0 (E1M3 515's shape): a mask gate
    assert g([True, True, False, False], [2, 2]) == (0, 1)  # shut exactly while the first machine is at state 0
    assert g([True, False, True, False], [2, 2]) == (1, 1)  # ... the second's (E1M2 line 1199's shape)
    assert g([True, False, False, True], [2, 2]) is None    # both machines decide it: refused


def test_e1m2s_lines_shut_at_every_state_take_the_solid_path(e1m1, e1m2):
    assert _row(e1m1, "dynamic segs the renderer can gate")[0] == "OK"
    assert _row(e1m2, "dynamic segs the renderer can gate")[0] == "OK"
    r = _row(e1m2, "dynamic segs shut at EVERY state")
    assert r[2] == "4" and "[2033, 2050, 2062, 2075]" in r[4]          # the CR of #146's four lines


def test_a_door_beside_a_mover_is_a_pair(ls, wad):
    """M8 C4: a door and a mover on one seg are the renderer's PAIR (E1M3's 519 / 1077) -- no refusal there"""
    sv = ls.Survey(wad, "E1M3", wad)
    assert sv._line_machines(105, 106)[0][0] == 106 and [m for m, _s in sv._line_machines(105, 106)] == [106, 105]
    sv._seg_machines()
    assert _row(sv, "dynamic segs the renderer can gate")[0] == "OK"


def test_control_a_door_beside_two_movers_is_refused(ls, wad, monkeypatch):
    """R9: E1M2's lift 47 (line 1199 to floor 206) made a door too: a door and TWO movers on one seg -- three machines"""
    sv = ls.Survey(wad, "E1M2", wad)
    dst, dsecs, msecs, mcell = sv._machines()
    sv.facts["_machines"] = ({**dst, 47: [0, 1]}, dsecs, msecs, mcell)
    sv._seg_machines()
    r = _row(sv, "dynamic segs the renderer can gate")
    assert r[0] == "REFUSED" and "a door (47) and two movers" in r[4], r


# ---- the openings of lines between dynamic sectors (the CR of #142: the row from the readers' own functions)
def test_e1m2s_dynamic_lines_read_through_one_cell(e1m2):
    assert _row(e1m2, "collision.mover_line_states")[0] == "OK"
    r = _row(e1m2, "monstersight.line_states")
    assert r[0] == "OK" and r[2] == "136 of 136"


def test_control_a_two_cell_opening_is_refused(ls, wad, monkeypatch):
    import doomfj.monstersight as ms
    real = ms.line_states

    def refuse_1199(w, a, b):
        if {a, b} == {47, 206}:                    # E1M2's line 1199: lift 47 / floor 206 (two cells)
            raise AssertionError("a line between two dynamic sectors (47, 206) on two state cells")
        return real(w, a, b)
    monkeypatch.setattr(ms, "line_states", refuse_1199)
    r = _row(_survey(ls, wad, "E1M2"), "monstersight.line_states")
    assert r[0] == "REFUSED" and "1199" in r[4]


# ---- slanted W1 floor lines (#147: two crossing rules)
def test_slanted_floor_lines(e1m1, e1m2):
    assert _row(e1m1, "slanted W1 floor lines")[0] == "OK"
    r = _row(e1m2, "slanted W1 floor lines")
    assert r[0] == "WARN" and "[1972, 1974, 2011]" in r[4]


# ---- the oracle's thvis mirror (the CR of #142, BLOCKING) and the World's sprite art
def test_the_mirror_reads_every_slot(e1m1, e1m2):
    assert _row(e1m1, "the oracle's thvis mirror")[0] == "OK"
    r = _row(e1m2, "the oracle's thvis mirror")
    assert r[0] == "OK" and "1 slot(s) neither pickup nor barrel" in r[4]
    assert _row(e1m2, "World things with sprite art")[0] == "OK"


def test_control_the_pre_fix_mirror_raises_on_e1m2(ls, wad, monkeypatch):
    """the mirror before cd969f2: a slot is a pickup or a barrel -- E1M2's hard-only lamp is neither"""
    from doomfj.monsters import MonsterViews

    def old_vis_state(self, phase):
        ws = phase.world.ws
        pick = {di: i for i, di in enumerate(self.pdi)}
        bar = {di: b for b, di in enumerate(self.bdi)}

        def present(di):
            if di in pick:
                return 1 - ws.pickup_taken[pick[di]]
            return int(bool(ws.bar_state[bar[di]]))
        vals = [present(di) for di in sorted(self.vis_slots, key=self.vis_slots.get)]
        return {"thvis": tuple(vals + [1 - ws.pickup_taken[pick[di]] for di in self.rt_pickups])}
    monkeypatch.setattr(MonsterViews, "vis_state", old_vis_state)
    rows = _survey(ls, wad, "E1M2").rows
    assert any(r[0] == "ERROR" and r[1] == "lesson: the oracle's thvis mirror" and "KeyError" in r[4] for r in rows)


def test_control_a_world_thing_without_art_is_refused(ls, wad, monkeypatch):
    from doomfj.reference_model import ReferenceModel
    real = ReferenceModel.sprite_art
    monkeypatch.setattr(ReferenceModel, "sprite_art",
                        lambda self, sw, ty, cache=None: None if ty == 2012 else real(self, sw, ty, cache))
    r = _row(_survey(ls, wad, "E1M1"), "World things with sprite art")      # 2012: the medikit
    assert r[0] == "REFUSED" and "[2012]" in r[4]


# ---- the per-map feature flags (E1M2's polish: asserts only E1M2 has passed)
def test_feature_flags(e1m1, e1m2):
    for p in ("animated lights", "switch textures", "the MAP page"):
        assert _row(e1m2, p)[:3] == ("OK", _row(e1m2, p)[1], "on")
    r = _row(e1m1, "animated lights")                # off on E1M1: two of its light sectors are doors / movers
    assert r[0] == "WARN" and "when SECTOR_LIGHTS is turned on" in r[4]


def test_control_turning_the_lights_on_for_e1m1_refuses(ls, wad, monkeypatch):
    import doomfj.config as C
    monkeypatch.setitem(C.MAP_CONFIG, "E1M1", dict(C.MAP_CONFIG.get("E1M1", {}), SECTOR_LIGHTS=1))
    sv = ls.Survey(wad, "E1M1", wad)
    sv._feature_flags()
    assert _row(sv, "animated lights")[0] == "REFUSED"


# ---- the plane-pair estimate (E1M2: 376 > 255, found by an emission) and the projection (E1M2's pool and RAM)
def test_plane_pairs_warn_on_a_narrow_config(e1m1, e1m2, ls, wad, monkeypatch):
    assert _row(e1m1, "plane pairs")[0] == "INFO" and _row(e1m2, "plane pairs")[0] == "INFO"
    import doomfj.config as C
    monkeypatch.setitem(C.MAP_CONFIG, "E1M2", dict(C.MAP_CONFIG["E1M2"], PID_NIBBLES=2))     # the control
    sv = ls.Survey(wad, "E1M2", wad)
    sv.render_caps()
    assert _row(sv, "plane pairs")[0] == "WARN"


def test_projection(e1m1, e1m2, ls, wad):
    assert _row(e1m1, "pool demand")[4] == "--spread 2"
    assert _row(e1m2, "pool demand")[4] == "--spread 1"               # E1M2 r3/r4 build at spread 1
    assert _row(e1m2, "assembly peak RAM")[0] == "OK"
    sv = ls.Survey(wad, "E1M7", wad)                                    # 6,947 segs: 1.9x E1M2 -- the control
    sv._projection()
    assert _row(sv, "pool demand")[0] == "WARN" and _row(sv, "assembly peak RAM")[0] == "WARN"


# ---- the matrix hid the filtered World's refusal
def test_control_the_matrix_shows_a_refusing_filtered_world(ls, wad, monkeypatch):
    from doomfj import world as W
    types = dict(ls.gd.THING_TYPES)
    del types[3001]                                   # an unknown type: the survey retries without it ...
    monkeypatch.setattr(ls.gd, "THING_TYPES", types)

    def refuse(self):
        raise AssertionError("leaf lists store mobile index + 1 in a byte")     # ... and that World refuses too
    monkeypatch.setattr(W.World, "_build_level", refuse)
    text = ls.matrix(wad, wad, ["E1M1"])
    assert "REFUSED: World(strict=True) without the unknown thing types | leaf lists store" in text


# ---- emit_check: a stale stand-in is refused (the CR of #142 item 3, #145 F10)
@pytest.fixture(scope="module")
def ec():
    return _load("emit_check", "scripts/emit_check.py")


def test_every_standin_names_its_rows(ec):
    assert set(ec.STANDIN_ROWS) == set(ec.STANDINS)


def test_stale_rule(ec):
    ok = [("OK", "map extent, far LOS (monstersight)")]
    over = [("OVER", "map extent, far LOS (monstersight)")]
    assert ec.stale_standins(["far-los"], ok) == ["far-los"]
    assert ec.stale_standins(["far-los"], over) == []                   # the control: a refusing row keeps it
    assert ec.stale_standins(["barrels-one-skill"], []) == []           # no witness (no World): not judged stale


def test_every_standin_is_stale_on_the_shipped_e1m2(ec, e1m2):
    """E1M2 r3 / r4 build with NO stand-in: each of the six must be refused there"""
    assert ec.stale_standins(sorted(ec.STANDINS), e1m2.rows) == sorted(ec.STANDINS)
