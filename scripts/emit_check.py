"""M8 (docs/level-pipeline.md 7): the game tier's EMISSION for a map, asserts ON -- every Python refusal in minutes,
before any 1-2 hour assembly. Prints the parts' sizes on success, the first refusal on failure.

    python scripts/emit_check.py E1M2                                 # what refuses today
    python scripts/emit_check.py E1M2 --standin gives far-los ...      # past the named refusals, for a SIZE measurement

A STAND-IN is a named, opt-in substitute for a feature that is not built yet: it supplies the missing piece AS CODE (a
give routine of the same size, a decoration present on every skill ...), never by switching asserts off -- E1M2's
first size measurement ran under `python -O`, and the guard it skipped surfaced 98 minutes later as an undefined label.
A program emitted with any stand-in is a SIZE measurement: its pixels are not certified, and the output says which
stand-ins it used. Every stand-in names the feature rung that removes it.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _gives():
    """F4: yellow / red cards as the blue card's routine, the soulsphere as the stimpack's, the computer map as the
    health bonus's -- give routines of about their size, renamed to the kind's labels"""
    import re
    import doomfj.lootcode as lc
    orig = lc.give_lines

    def give(kind, *a, **k):
        stand = {13: 5, 6: 5, 2013: 2011, 2026: 2014}.get(kind, kind)
        out = orig(stand, *a, **k)
        if stand == kind:
            return out
        return [re.sub(r"(?<!\w)give_%d(?!\d)" % stand, "give_%d" % kind, x) for x in out]
    lc.give_lines = give


def _slanted_doors():
    """F2: a door with slanted sides contacts as its bounding rectangle (doorcode's 'd' lines)"""
    from doomfj import doorcode
    orig = doorcode.door_contact_lines

    def dcl(tag, geo, *a, **k):
        area, lines = geo
        if area[0] == "poly":
            xs = [p for e in area[1] for p in (e[0], e[2])]
            ys = [p for e in area[1] for p in (e[1], e[3])]
            area = (min(xs), min(ys), max(xs), max(ys))
        return orig(tag, (area, [ln for ln in lines if ln[0] != "d"]), *a, **k)
    doorcode.door_contact_lines = dcl


def _decor_every_skill():
    """F1: a solid decoration some skill lacks is treated as present on every skill (no mc_don flag)"""
    import doomfj.monstermove as mm
    orig = mm.static_blockers

    def sb(w):
        things, var = orig(w)
        return [(x, y, r, None if (isinstance(f, str) and f.startswith("mc_don")) else f) for x, y, r, f in things], []
    mm.static_blockers = sb


def _stats_digits():
    """F1: LEVEL COMPLETE's two-digit counters (kills > 99): the digit check skipped, every other check kept"""
    from doomfj import gamedata as gd
    import doomfj.statcode as sc

    def check(w):
        assert all(gd.THING_TYPES[t.type].flags & gd.MF_COUNTKILL for t in w.mon_things)
        assert len(w.secret_sectors) <= 9
    sc.check_world = check
    orig = sc._digit_set_lines
    sc._digit_set_lines = lambda slot, value, *a, **k: orig(slot, value % 100, *a, **k)   # the totals shown mod 100


def _far_los():
    """F1: a map wider than the far line of sight's 32 x 127 units -- the walk kept at 32 pieces (more breaks its 6-nibble
    step) and the extent clamped to it: the code's size, not its reach"""
    import doomfj.monstersight as ms
    orig = ms.far_margin

    def fm(w):
        vs = w.cmap.vertexes
        ext = max(max(v[0] for v in vs) - min(v[0] for v in vs), max(v[1] for v in vs) - min(v[1] for v in vs)) + 1
        return orig(w) if ext <= ms.FAR_PIECES * ms.PIECE else ms.FAR_PIECES * ms.PIECE
    ms.far_margin = fm


def _slot_ids():
    """F1: more than 255 drawable things -- the slot-id check skipped (ids wrap: size right, pixels not)"""
    import doomfj.wall_renderer as wr
    wr.check_slot_ids = lambda n: None


def _soundblock_ignored():
    """F3: the fj noise flood without ML_SOUNDBLOCK -- the block edges read as ordinary edges (the flood's size, not its
    rule: the model keeps them)"""
    import doomfj.noisecode as nc
    for name in [n for n in dir(nc) if callable(getattr(nc, n)) and not n.startswith("_")]:
        fn = getattr(nc, name)
        if getattr(fn, "__module__", "") != nc.__name__:
            continue

        def wrap(*a, _fn=fn, **k):
            w = next((x for x in a if hasattr(x, "_sound_block_static_edges")), None)
            if w is None:
                return _fn(*a, **k)
            saved = (w._sound_block_door_edges, w._sound_block_static_edges)
            w._sound_block_door_edges, w._sound_block_static_edges = [], []
            try:
                return _fn(*a, **k)
            finally:
                w._sound_block_door_edges, w._sound_block_static_edges = saved
        setattr(nc, name, wrap)


def _barrels_one_skill():
    """F1: barrels that differ by skill -- every skill's level start read as the hard skill's (NEW GAME's lines per
    skill are F1's)"""
    from doomfj import gamedata as gd
    import doomfj.barrelcode as bc
    orig = bc.level_start_values
    bc.level_start_values = lambda w, sk, *a, **k: orig(w, gd.SK_HARD, *a, **k)


def _barrel_chains_static():
    """F1: a barrel chain whose trace a dynamic line touches (the chain's LOS is asserted static) -- the pair dropped
    (read as blocked): the chain table's size, not its rule"""
    import doomfj.barrelcode as bc
    from doomfj.combat import BARREL_R, BOMB_DAMAGE
    from doomfj.monstersight import sight_segments
    from doomfj.world import segments_touch

    def chains(w):
        segs = sight_segments(w)
        out = {}
        for b, t in enumerate(w.barrel_things):
            out[b] = []
            for c, tc in enumerate(w.barrel_things):
                d = max(0, max(abs(tc.x - t.x), abs(tc.y - t.y)) - BARREL_R)
                if c == b or d >= BOMB_DAMAGE:
                    continue
                if not any(segments_touch((tc.x, tc.y), (t.x, t.y), s["a"], s["b"]) for s in segs):
                    out[b].append((c, BOMB_DAMAGE - d))
        return out
    bc.chain_pairs = chains


def _pickup_static_z():
    """F1: a pickup standing in a door or mover sector (E1M2's blue card on floor-switch sector 45) -- read at its
    sector's stored floor: the pickup code's size, not its z on a moved floor"""
    import doomfj.lootcode as lc
    orig = lc.pickup_lines

    def pl(w, *a, **k):
        secs = {w.leaf_sector[w.rm.point_in_subsector(w.cmap, t.x, t.y)] for t in w.pickup_things}
        saved = (w.door_order, w.mover_order)
        w.door_order = [s for s in saved[0] if s not in secs]
        w.mover_order = [s for s in saved[1] if s not in secs]
        try:
            return orig(w, *a, **k)
        finally:
            w.door_order, w.mover_order = saved
    lc.pickup_lines = pl


def _attacker_7bit():
    """F1: more than 126 monster slots against the 7-bit attacker ids (p_atk / aim_sid in world's schema) -- the death
    turn's dispatch over the first 126 slots: the code's size (two levels of 16), not the far killers' faces"""
    import doomfj.hurtcode as hc
    orig = hc.turn_lines
    hc.turn_lines = lambda slot_rows, *a, **k: orig(list(slot_rows)[:0x7E], *a, **k)


def _exit_bar_stale():
    """F7: a health / armor pickup within a frame of the exit box (issue #123 item 4: the bar stale on the exit frame)
    -- a CHECK with no code behind it, skipped: the program is unchanged, the exit frame's bar may be one frame old"""
    import doomfj.wall_renderer as wr
    wr.assert_exit_frame_bar = lambda *a, **k: None


STANDINS = {"soundblock-ignored": _soundblock_ignored, "gives": _gives, "slanted-doors": _slanted_doors, "decor-every-skill": _decor_every_skill,
            "stats-digits": _stats_digits, "far-los": _far_los, "slot-ids": _slot_ids, "barrels-one-skill": _barrels_one_skill,
            "barrel-chains-static": _barrel_chains_static,
            "pickup-static-z": _pickup_static_z,
            "attacker-7bit": _attacker_7bit,
            "exit-bar-stale": _exit_bar_stale}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("map")
    ap.add_argument("--tier", default="game")
    ap.add_argument("--standin", nargs="*", default=[], choices=sorted(STANDINS))
    ap.add_argument("--json", help="write the parts' sizes here")
    ap.add_argument("--assemble", metavar="OUT_FJM",
                    help="build the tier into OUT_FJM (build_wall_renderer: emit + the plain one-pass assembly, asserts "
                         "ON) and print its size metrics -- a SIZE measurement when any stand-in is on")
    a = ap.parse_args()
    for s in [s for s in STANDINS if s in a.standin]:     # registry order: modules that bind names at import last
        STANDINS[s]()
    from doomfj.config import Config, map_cfg
    from doomfj.mapprofile import profile
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import emit_wall_renderer, tier_cfg
    mw = WadFile.from_path(str(ROOT / profile(a.map).wad))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    cfg = tier_cfg(map_cfg(Config(), a.map), a.tier)
    print("emit_check %s tier %s stand-ins %s (asserts %s)" % (a.map, a.tier, a.standin or "none",
                                                               "ON" if __debug__ else "OFF -- refused"), flush=True)
    assert __debug__, "emit_check runs with asserts ON (no python -O): a skipped guard costs an assembly"
    t = time.time()
    if a.assemble:
        from doomfj.build import build_wall_renderer
        met = build_wall_renderer(a.assemble, wad_path=str(ROOT / profile(a.map).wad), mapname=a.map, tier=a.tier)
        print("BUILT in %.0f s" % (time.time() - t), flush=True)
        flat = {k: v for k, v in met.items() if not isinstance(v, (dict, list))}
        print(json.dumps(flat, indent=1, default=str), flush=True)
        if a.json:
            Path(a.json).write_text(json.dumps({"map": a.map, "standins": a.standin, "metrics": flat}, indent=1,
                                               default=str))
        return
    parts = emit_wall_renderer(mw, a.map, cfg, sprite_wad=art, tier=a.tier, return_parts=True)
    items = parts.items() if isinstance(parts, dict) else parts
    res = {k: {"chars": len(v), "lines": v.count("\n") + 1} for k, v in items}
    print("EMITTED in %.0f s: %s" % (time.time() - t, {k: v["chars"] for k, v in res.items()}), flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps({"map": a.map, "standins": a.standin, "parts": res}, indent=1))


if __name__ == "__main__":
    main()
