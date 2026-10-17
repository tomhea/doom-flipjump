"""M8 (docs/level-pipeline.md 7): the game tier's EMISSION for a map, asserts ON -- every Python refusal in minutes,
before any 1-2 hour assembly. Prints the parts' sizes on success, the first refusal on failure.

    python scripts/emit_check.py E1M2                                 # what refuses today
    python scripts/emit_check.py E1M2 --standin far-los ...            # past the named refusals, for a SIZE measurement

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


# M8 F4 RETIRED "gives" (lootcode.give_lines: the yellow / red cards, the soulsphere, the computer map), F7 RETIRED
# "exit-bar-stale" (wall_renderer.p5_tic_lines(bar_always=): the bar runs after the lvdone guard where the exit frame
# can move it), F2 RETIRED "slanted-doors" (doorcode: a slanted door's contact by its own lines) and M8 L5 RETIRED
# "soundblock-ignored" (noisecode floods with ML_SOUNDBLOCK: tests/fj/test_noise_block_fj.py)
STANDINS = {"decor-every-skill": _decor_every_skill,
            "stats-digits": _stats_digits, "far-los": _far_los, "barrels-one-skill": _barrels_one_skill,
            "barrel-chains-static": _barrel_chains_static,
            "pickup-static-z": _pickup_static_z,
            "attacker-7bit": _attacker_7bit}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("map")
    ap.add_argument("--tier", default="game")
    ap.add_argument("--standin", nargs="*", default=[], choices=sorted(STANDINS))
    ap.add_argument("--json", help="write the parts' sizes here")
    ap.add_argument("--map-config", nargs="*", default=[], metavar="KEY=VAL",
                    help="override the map's config.MAP_CONFIG widths (e.g. PID_NIBBLES=3 on E1M1: E1M2's wide layout "
                         "built on a map whose gates need no stand-in) -- a MEASUREMENT build, never the shipped one")
    ap.add_argument("--then", nargs="*", metavar="SCRIPT ARGS",
                    help="LAST on the line: after applying the stand-ins, run SCRIPT (e.g. scratchpad/12m/build_labeled.py) "
                         "in THIS process with every argument after it, `--` included -- a blocked build's PREFLIGHT for a "
                         "map whose features are not all built yet")
    ap.add_argument("--assemble", metavar="OUT_FJM",
                    help="build the tier into OUT_FJM (build_wall_renderer: emit + the plain one-pass assembly, asserts "
                         "ON) and print its size metrics -- a SIZE measurement when any stand-in is on")
    argv, then = sys.argv[1:], None
    if "--then" in argv:                    # everything after it is the script's, `--` included (argparse would eat it)
        k = argv.index("--then")
        argv, then = argv[:k], argv[k + 1:]
        assert then, "--then needs a script"
    a = ap.parse_args(argv)
    a.then = then
    if a.map_config:                        # before anything reads config.MAP_CONFIG
        import doomfj.config as _config
        over = {k: int(v) for k, v in (kv.split("=", 1) for kv in a.map_config)}
        _config.MAP_CONFIG[a.map.upper()] = dict(_config.MAP_CONFIG.get(a.map.upper(), {}), **over)
        print("MAP_CONFIG[%s] = %s" % (a.map.upper(), _config.MAP_CONFIG[a.map.upper()]), flush=True)
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
    if a.then:
        import runpy
        script, *rest = a.then
        sys.argv = [script] + rest
        sys.path.insert(0, str((ROOT / script).parent))
        print("THEN %s %s" % (script, " ".join(rest)), flush=True)
        runpy.run_path(str(ROOT / script), run_name="__main__")
        print("THEN done in %.0f s" % (time.time() - t), flush=True)
        return
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
    hot_block_check(parts)
    if a.tier in ONE_PASS_RESET_TIERS:
        reset_check(parts, mw, a.map, cfg, a.tier)


HOT_WINDOW_OPS = 1 << 14        # frame.arm5's window: 16^5 bits = 16,384 ops (2^20 / 64)


def hot_block_check(parts):
    """the hot data block (pclm .. wrej) counted from the emitted TEXT -- `;v * dw` one op, `hex.vec n` n ops (w/4 = 8)
    -- against frame.arm5's 16^5-bit window; `pad 16384` anchors pclm on a window base, so it fits iff it is <= 16,384
    ops (build.hot_window_violation is the build's own refusal, from the labels; this is the same fact before any
    assembly: E1M2's first fast build learned it after 97 minutes). Exact on E1M2 b3: 15,376 ops, as its labels."""
    import re
    text = (dict(parts) if not isinstance(parts, dict) else parts).get("tables", "")
    lines = text.split(chr(10))
    try:
        s = next(i for i, ln in enumerate(lines) if ln.startswith("pclm:"))
        e = next(i for i, ln in enumerate(lines) if ln.startswith("wrej:"))
    except StopIteration:
        print("HOT BLOCK: no pclm / wrej in this tier's tables part", flush=True)
        return
    ops, unknown = 0, []
    for ln in lines[s:e]:
        t = re.sub(r"^[A-Za-z_][\w.]*:\s*", "", ln.strip())
        if not t or t.startswith("//"):
            continue
        if t.startswith(";"):
            ops += 1
            continue
        m = re.match(r"hex\.vec\s+(\d+|w/4)", t)
        if m:
            ops += 8 if m.group(1) == "w/4" else int(m.group(1))
            continue
        unknown.append(t)
    print("HOT BLOCK: %s ops of the %s-op window (%s ops of headroom)%s"
          % (format(ops, ","), format(HOT_WINDOW_OPS, ","), format(HOT_WINDOW_OPS - ops, ","),
             "" if not unknown else "; %d lines not counted: %s" % (len(unknown), unknown[:3])), flush=True)
    assert not unknown, "the hot block has lines this count does not know -- extend hot_block_check"
    assert ops <= HOT_WINDOW_OPS, ("the hot data block is %d ops past frame.arm5's window: every narrow pointer would go "
                                   "wild (shrink it: docs/handoff-e1m2.md 9)" % (ops - HOT_WINDOW_OPS))


def reset_check(parts, mw, mapname, cfg, tier):
    """the one-pass reset's refusals (a persisted name the registry lacks, or the program does not declare; a
    registered cell undeclared) WITHOUT an assembly: the parts written to a temporary directory and the reset composed
    over them -- the same calls, in the same order, as `build.build_wall_renderer`'s one-pass block (keep the two in
    step: a refusal found here is one the build would hit 7 minutes in; E1M2's `mc_don` registry miss, 2026-10-17)"""
    import tempfile
    from doomfj import selfreset
    from doomfj.build import STANDALONE_RESTORE_SET, DEFAULT_RESTORE_SET, _map_persist, persist_labels
    from doomfj.mapcompiler import bake_bsp
    from doomfj.wall_renderer import tier_flags, write_program_files
    t = tier_flags(tier)
    standalone, moving_things, doors = t["standalone"], t["moving_things"], t["doors"]
    restore_set = STANDALONE_RESTORE_SET if standalone else DEFAULT_RESTORE_SET
    with tempfile.TemporaryDirectory() as tmp:
        prog = write_program_files(parts, Path(tmp), mapname)
        extra = _map_persist(mw, mapname, standalone and moving_things)
        persist = persist_labels(standalone=standalone, doors=doors, moving_things=moving_things, extra=extra)
        nss = len(bake_bsp(mw, mapname).subsectors)
        names = selfreset.registered_reset_names(restore_set, cfg, standalone, mapname) | set(extra)
        _part, n_nib, n_byte, _plan = selfreset.emit_reset_part_by_label(
            Path(tmp), prog, names, cfg.VIEW_W, nss, mapname, persist=persist, pid_bytes=cfg.PID_BYTES,
            ss_ratio=cfg.SSHEAD_RATIO)
    print("RESET composed: %d nibble cells, %d byte cells, %d persisted names (the map's own: %s)"
          % (n_nib, n_byte, len(persist), list(extra) or "none"), flush=True)


ONE_PASS_RESET_TIERS = ("game",)        # build.ONE_PASS_TIERS' standalone member (the shipped one)


if __name__ == "__main__":
    main()
