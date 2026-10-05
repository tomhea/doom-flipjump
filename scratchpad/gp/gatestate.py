"""M7 P1.5 -- the game-tier gates' STATE check (scratchpad/m2_std_gate.py, scratchpad/m3_gate.py).

Kill criterion 3 of P1.5 (docs/gp-ledger.md) asks both gates to be byte- AND state-exact, and both
compared pixels only: a NEW GAME that forgot a cell the frame cannot show -- a door's timer, a
screen or a highlight while the world is up -- passed them. So each gate now runs its binary ONCE
through the same PcIO composition (`probe.GameBinary.run`, what b0_scenarios drives) with a
`probe.Probe` that reads the persisted world cells at every present, and holds every frame's
reading against the oracle's state after that frame: the view, `mode`, `menu_scr`, `menu_sel`, and
every door's state, direction, sub-step and timer.

    frames, ops, reads = run_reading_state(fjm, labels, events, n_frames, ndoors)
    bad = diff(reads[f], oracle_state(x, y, angle, mode, scr, sel, doors))
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import probe as P                                                          # noqa: E402
from doomfj.fixedpoint import _signed                                      # noqa: E402

STATE_NAMES = ("viewx", "viewy", "viewangle", "mode", "menu_scr", "menu_sel",
               "dstate", "ddir", "dsub", "dwait",
               "dreq", "pcard", "wfired",        # M7 P2a.1: doors.DoorPhase's (req, card, fired)
               "lvdone", "pusedn",               # M7 P2a.2: the exit's
               "lstate", "ldir", "lsub", "lwait", "lreq", "fswitch",   # M7 P2b: movers.MoverPhase's
               "mon_state", "mon_tics", "mon_facing", "mon_active",   # M7 P3.1: monsters.MonsterPhase's
               "mon_target", "mon_reaction", "mon_threshold", "mon_movedir", "sched_cursor", "thseen",  # P3.2a
               "mon_movecount", "mon_rng", "mon_floorz", "msec", "thpos_rt", "thss_rt",   # P3.2b
               "mon_justattacked",                                                       # P3.2c
               "wp_rdy", "wp_pend", "wp_st", "wp_tics", "wp_sy", "fl_st", "fl_tics", "wp_rf", "wp_ad", "am_clip", "am_shell", "wp_own", "rng_pl", "wp_frm", "fl_frm", "aim_sid",   # P4.1: the weapon; P4.2a: the window
               "mon_health", "mon_shootable", "mon_solid", "mon_justhit",   # P4.2a: the damage
               "mon_ambush", "snd_alert",                                           # P4.2b: the noise
               "p_hp", "p_ar", "p_at", "p_dc", "p_dead",                            # P5: hurtcode's player cells
               "pj_act", "pj_x", "pj_y", "pj_mx", "pj_my", "pj_st", "pj_ti",        # P5: the fireball pool
               "fx_act", "fx_x", "fx_y", "fx_st", "fx_ti", "rng_fx",                # P5: the blood pool, rng_fx
               # P6 / P7 (docs/gp-p67-interface.md 4.5): the loot, the barrels, the drops, the game's cells, thvis
               "p_bc", "p_str", "p_bp", "am_misl", "am_cell", "mdrop", "dr_live",
               "bar_st", "bar_ti", "bar_hp", "bar_solid", "rng_wd", "lvtime", "g_rs", "g_skill", "thvis",
               "p_atk", "pj_src")                                                   # P7: the killer, the shooters


def run_reading_state(fjm, labels, events, frames: int, ndoors: int, nwalk: int = 1, nlift: int = 2,
                      nmon: int = 0, nrt: int = 0, palettes_out: list | None = None, nthvis: int = 0):
    """-> (the presented frames' pixel indices, the exact op total, [the STATE_NAMES cells read at
    each present]). `labels` is the build's own label table (build_labeled.py writes it).
    M7 P5: `palettes_out`, when given, receives the palette each present showed (probe.RunResult.palettes:
    sha1[:12] of its bytes -- `probe.Oracle.palette_sha` is the oracle's side).
    M7 P6: `nthvis` -- the `thvis` slots to read (probe.Oracle.nthvis: a player who loots), 0 reads none"""
    cells = {n: c for n, c in P.game_cells(ndoors, nwalk, nlift, nmon, nrt, nthvis).items() if n in STATE_NAMES}
    # M7 P3.1: a gate that does not pass `nmon` asks for no monster cells (a binary before P3.1)
    missing = sorted(set(STATE_NAMES) - set(cells) - (set() if nmon else MONSTER_NAMES)
                     - (set() if nthvis else {"thvis"}))
    assert not missing, "probe.game_cells lost %s -- the state check would skip them" % missing
    table = P.LabelTable.load(labels, {c.label for c in cells.values()})
    gb = P.GameBinary(fjm)
    probe = P.Probe(cells, table, gb.width)
    # a binary before M7 P1.5 has no menu_scr / menu_sel (probe.OPTIONAL_LABELS): the probe drops
    # them, and `diff` then reports them missing on every frame -- such a binary fails this check
    kept = [n for n in STATE_NAMES if n in probe.cells]
    reads = []
    probe.on_present(lambda pr, f: reads.append(pr.read_cells(kept)))
    r = gb.run(frames, events, probe)
    if palettes_out is not None:
        palettes_out.extend(r.palettes)
    return r.frames, r.ops, reads


MONSTER_NAMES = {"mon_state", "mon_tics", "mon_facing", "mon_active",
                 "mon_target", "mon_reaction", "mon_threshold", "mon_movedir", "sched_cursor", "thseen",
                 "mon_movecount", "mon_rng", "mon_floorz", "msec", "thpos_rt", "thss_rt", "mon_justattacked",
                 "mon_health", "mon_shootable", "mon_solid", "mon_justhit", "mon_ambush", "snd_alert"}


def oracle_state(x, y, angle, mode, scr, sel, doors, phase=None, order=None, exit_=None,
                 movers=None, mover_order=None, monsters=None) -> dict:
    """the oracle's state after a frame, in the cells' own units: the view as signed 16.16, the
    angle's 32 bits, and each door cell a tuple in door order (`doors`: the per-door
    (state, direction, sub-step, timer) tuples, sorted by sector as the binary numbers them).
    M7 P2a.1: `phase` = a doors.DoorPhase state (its req, card and fired), `order` its door order.
    M7 P2a.2: `exit_` = (lvdone, pusedn). M7 P2b: `movers` = a movers.MoverPhase state (its lifts,
    requests and switch), `mover_order` its lift order"""
    doors = list(doors)
    extra = {}
    if phase is not None:
        _ds, fired, req, card = phase
        extra = {"dreq": tuple(int(si in req) for si in order), "pcard": card,
                 "wfired": P.wfired_value(fired)}
    if exit_ is not None:
        extra.update({"lvdone": exit_[0], "pusedn": exit_[1]})
    if movers is not None:
        lifts, req, sw = movers
        extra.update({"lstate": tuple(t[0] for t in lifts), "ldir": tuple(t[1] for t in lifts),
                      "lsub": tuple(t[2] for t in lifts), "lwait": tuple(t[3] for t in lifts),
                      "lreq": tuple(int(si in req) for si in mover_order), "fswitch": sw})
    if monsters is not None:                    # M7 P3.1: a monsters.MonsterPhase's state()
        extra.update(monsters)
    return {**extra, "viewx": _signed(x, 32), "viewy": _signed(y, 32), "viewangle": angle & 0xFFFFFFFF,
            "mode": mode, "menu_scr": scr, "menu_sel": sel,
            "dstate": tuple(d[0] for d in doors), "ddir": tuple(d[1] for d in doors),
            "dsub": tuple(d[2] for d in doors), "dwait": tuple(d[3] for d in doors)}


def diff(got, want: dict) -> dict:
    """{cell: (the binary's value, the oracle's)} for every cell that disagrees; a missing reading
    (the binary presented fewer frames) disagrees in every cell"""
    got = got or {}
    return {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}


def palette_diff(palettes: list, f: int, wad, index: int) -> dict:
    """M7 P5: {"palette": (the present's, the oracle's)} when present `f` did not show `wad`'s PLAYPAL[index] -- `wad`
    the ASSET wad (freedoom1.wad: 14 palettes; the fixture map wad has palette 0 only, the same bytes)
    (`run_reading_state(palettes_out=)`; the oracle's index is combat.palette_index on a world frame, 0 on a menu
    frame) -- {} when it did. A present the run never made disagrees."""
    want = P.palette_sha(wad, index)
    got = palettes[f] if f < len(palettes) else None
    return {} if got == want else {"palette": (got, "%s (PLAYPAL %d)" % (want, index))}


def show(bad: dict, limit: int = 4) -> str:
    """one line: the first `limit` disagreeing cells, and for a door cell only the doors that differ"""
    parts = []
    for k, (g, w) in list(bad.items())[:limit]:
        if isinstance(w, tuple) and isinstance(g, tuple) and len(g) == len(w):
            parts.append("%s[%s]" % (k, ", ".join("door %d: fj %s, oracle %s" % (i, a, b)
                                                  for i, (a, b) in enumerate(zip(g, w)) if a != b)))
        else:
            parts.append("%s: fj %s, oracle %s" % (k, g, w))
    return "; ".join(parts) + (" (+%d more)" % (len(bad) - limit) if len(bad) > limit else "")
