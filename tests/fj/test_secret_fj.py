"""P10 (doomfj.statcode): THE SECRETS on the real flipjump engine -- `sc_go`, the very text the emitter splices into the
tic's `pre` (the per-secret box filter, `ptloc_walk`, `lfsec`, `ms_seed_leaf`, the player's collision cells WITH the
static blockers) -- against the model's own `combat._special_sector`, record by record in ONE image.

Each record stands the player somewhere he CAN be: inside the polygon of the sector the BSP places him in (no point
in the void behind a wall -- the BSP assigns those a sector too, outside its lines' bounds, and only there is the box
filter not exact) and where the model's check_position takes his box -- deep in one of E1M1's four secret sectors (52, 86, 128, 132), on their edges
where the box reaches another floor ("falling, not all the way down yet": not counted), inside a secret's box but
outside the sector, or far away -- with some secrets already found (`st_secm` / `st_secn` poked to a random
subset), and the doors and lifts in random states (secret 128 lies beside lift 129). `leveltime` is 1 in the model, so
its damaging-floor branch never fires: the records compare the secrets alone. After every record: `st_secn`,
`st_secm`.

R9 (MUTANTS), each must part: the floor test gone, the found bits not read (a found secret counted again: both of
its checks, the box loop's and the walk loop's -- they back each other up), a secret's box cut short, the count not
kept.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import lootcode as L
from doomfj import monstermove as MM
from doomfj import statcode as SC
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, cell_lists, collision_cells_fj,
                              generate_point_location_fj, line_rows, mover_line_openings, point_location_decls)
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.reference_model import PLAYER_RADIUS
from doomfj.world import TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 260
M32 = 0xFFFFFFFF


def _world():
    return World(skill=gd.SK_HARD, monsters="idle", player="full")


def _statics_clear(w, x16, y16) -> bool:
    """no static blocker overlaps the player's box (the invariant the move keeps)"""
    for b, t in enumerate(w.barrel_things):
        if w.ws.bar_solid[b] and abs((t.x << 16) - x16) < 26 << 16 and abs((t.y << 16) - y16) < 26 << 16:
            return False
    for t in w._decor_now:
        bd = (w.decor_radius[t.type] + 16) << 16
        if abs((t.x << 16) - x16) < bd and abs((t.y << 16) - y16) < bd:
            return False
    return True


def _records(w):
    rnd = random.Random(0x5EC)
    secrets = list(w.secret_sectors)
    boxes = [SC.sector_box(w, s) for s in secrets]
    xs = [v[0] for v in w.cmap.vertexes]
    ys = [v[1] for v in w.cmap.vertexes]
    out = []
    while len(out) < N:
        kind = rnd.choice(("in", "in", "in", "edge", "box", "out"))
        k = rnd.randrange(len(secrets))
        x0, x1, y0, y1 = boxes[k]
        if kind in ("in", "box"):
            x, y = rnd.randint(x0, x1), rnd.randint(y0, y1)
        elif kind == "edge":                              # within the player's radius of the box's border
            x = rnd.choice((rnd.randint(x0 - 20, x0 + 20), rnd.randint(x1 - 20, x1 + 20), rnd.randint(x0, x1)))
            y = rnd.choice((rnd.randint(y0 - 20, y0 + 20), rnd.randint(y1 - 20, y1 + 20), rnd.randint(y0, y1)))
        else:
            x, y = rnd.randint(min(xs), max(xs)), rnd.randint(min(ys), max(ys))
        x16 = (x << 16) + rnd.choice((0, 0, 0x8000, 0xFFFF))
        y16 = (y << 16) + rnd.choice((0, 0, 0x4000))
        sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, x16 >> 16, y16 >> 16)]
        if kind == "in" and sec != secrets[k]:
            continue
        if not _statics_clear(w, x16, y16):
            continue
        found = [int(rnd.random() < 0.25) for _ in secrets]
        rec = {"pos": (x16, y16), "found": found,
               "doors": [rnd.choice((0, rnd.randrange(w.door_nstates[si]))) for si in w.door_order],
               "lifts": [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]}
        _apply(w, rec)
        if not (_inside_sector(w, sec, x16 / 65536, y16 / 65536) and w.rm.check_position(w.scene_c, x16, y16)[0]):
            continue                                     # no player is there (the void behind a wall, or in a wall)
        out.append(rec)
    return out


def _inside_sector(w, sec: int, x: float, y: float) -> bool:
    """is (x, y) inside sector `sec`'s polygon -- a ray to +x crossing its lines an odd number of times (a line with
    the sector on both sides bounds nothing)"""
    V = w.cmap.vertexes
    inside = False
    for ld in w.lds:
        f = w.sds[ld.front].sector
        b = w.sds[ld.back].sector if 0 <= ld.back < len(w.sds) else None
        if (f == sec) == (b == sec):
            continue
        (x1, y1), (x2, y2) = V[ld.v1], V[ld.v2]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _apply(w, rec):
    ws = w.ws
    ws.px, ws.py = rec["pos"]
    ws.leveltime = 1                                     # off the damage period: the secrets alone
    for k, v in enumerate(rec["found"]):
        ws.p_secret[k] = v
    ws.p_secretcount = sum(rec["found"])
    for d, v in enumerate(rec["doors"]):
        ws.d_state[d] = v
    for k, v in enumerate(rec["lifts"]):
        ws.l_state[k] = v
    w._door_phase_scene()


def _row(ws, nsec) -> str:
    return "%x" % ws.p_secretcount + "".join("%x" % ws.p_secret[k] for k in reversed(range(nsec)))


def _expected(records) -> bytes:
    w = _world()
    lines = []
    for rec in records:
        _apply(w, rec)
        w._special_sector(TicEvents(0))
        lines.append(_row(w.ws, len(w.secret_sectors)))
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "nofloor": (r"    hex\.cmp 8, cp_floor, cp_seedf, sc_fl_out, sc_fl_on, sc_fl_out\n", "    ;sc_fl_on\n"),
    # both found checks of secret 0 (the box loop's and the walk loop's): they back each other up -- on E1M1 no
    # secret's region lies in another's box, so the walk loop's alone is never reached -- and the PROPERTY is "a
    # found secret never counts again"
    "refound": (r"    hex\.if1 1, st_secm \+ 0\*dw, sc_(b1|w0)\n", ""),
    "shortbox": None,
    "nocount": (r"    hex\.inc 1, st_secn\n", ""),
}


def _program(w, mut=None):
    from doomfj.reference_model import ML_BLOCKING
    from doomfj.wall_renderer import DOOR_QUANT
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, ML_BLOCKING, secs_open=kw["secs_open"],
                     door_line_ids=kw["door_line_ids"])
    obs = mover_line_openings(w.lds, w.sds, w.secs, kw["msecs"])
    movers = {li: (kw["mcell"][m_], obs[li]) for li in obs
              for m_ in [next(x for x in (w.sds[w.lds[li].front].sector, w.sds[w.lds[li].back].sector)
                              if x in kw["msecs"])]}
    lists, things = L.player_cell_things(w, cell_lists(rows, PLAYER_RADIUS))
    cells, root = collision_cells_fj("e1m1", rows, lists, doors=kw["doors"], movers=movers, things=things,
                                     thing_test=L.THING_TEST16)
    if mut == "shortbox":                                # secret 0's box loses its last 32 units on x
        real = SC.sector_box
        SC.sector_box = lambda w_, s: ((lambda b: (b[0], b[1] - 32, b[2], b[3]) if s == w_.secret_sectors[0] else b)
                                       (real(w_, s)))
        try:
            text = "\n".join(SC.secret_lines(w, root)) + "\n"
        finally:
            SC.sector_box = real
    else:
        text = "\n".join(SC.secret_lines(w, root)) + "\n"
    if mut and MUTANTS[mut]:
        pat, new = MUTANTS[mut]
        text, n = re.subn(pat, new, text)
        assert n, mut
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    nleaf = len(w.cmap.subsectors)
    tables = [generate_dispatch_table_fj("lfsec", list(w.leaf_sector),
                                         index_nibbles=max(1, ((nleaf - 1).bit_length() + 3) // 4), result_nibbles=2),
              generate_point_location_fj(w.cmap)]
    ws = w.ws
    nd, nl = len(w.door_order), len(w.lift_order)
    decls = (SC.decls(w) + L.loot_decls(L.level_start(w))      # the loot's: the static blockers' test scratch
             + COLLISION_STATE_DECLS + MON_CELL_DECLS + point_location_decls() + MM.monster_seed_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "lvtime: hex.vec 5",
                "bar_solid: hex.vec %d, %d" % (len(w.barrel_things),
                                                sum(ws.bar_solid[b] << (4 * b) for b in range(len(w.barrel_things)))),
                "mc_don: hex.vec %d, %d" % (max(1, len(MM.static_blockers(w)[1])),
                                             sum(v << (4 * k) for k, v in
                                                 enumerate(MM.decor_presence(w, MM.static_blockers(w)[1],
                                                                             gd.SK_HARD)))),
                "dstate: hex.vec %d" % nd, "lstate: hex.vec %d" % max(1, nl), "fswitch: hex.vec 1"])
    return decls, text + "\n".join(seed) + "\n" + cells, tables


def _build(tmp_path, name, mut=None):
    w = _world()
    records = _records(w)
    nsec = len(w.secret_sectors)
    body = ["stl.startup_and_init_all"]
    for rec in records:
        body += ["hex.set 8, viewx, %d" % (rec["pos"][0] & M32), "hex.set 8, viewy, %d" % (rec["pos"][1] & M32),
                 "hex.set %d, st_secm, %d" % (nsec, sum(v << (4 * k) for k, v in enumerate(rec["found"]))),
                 "hex.set 1, st_secn, %d" % sum(rec["found"])]
        body += ["hex.set 1, dstate + %d*dw, %d" % (d, v) for d, v in enumerate(rec["doors"])]
        body += ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(rec["lifts"])]
        body += ["stl.fcall sc_go, sc_ret",
                 "hex.print_as_digit 1, st_secn, 0", "hex.print_as_digit %d, st_secm, 0" % nsec, "stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(w, mut)
    prog = "\n".join(body + decls + [text] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(records)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """a find in each of the four secrets, an edge in a secret that does not count (the floor test), a found secret
    stood in again, records inside a box but outside its sector, and records far outside every box"""
    w = _world()
    secrets = list(w.secret_sectors)
    boxes = [SC.sector_box(w, s) for s in secrets]
    seen = dict(find=0, ledge=0, refound=0, boxonly=0, out=0)
    finds = set()
    for rec in _records(w):
        _apply(w, rec)
        before = list(w.ws.p_secret)
        ev = TicEvents(0)
        w._special_sector(ev)
        sec = w.player_sector()
        ix, iy = rec["pos"][0] >> 16, rec["pos"][1] >> 16
        inbox = [k for k, (x0, x1, y0, y1) in enumerate(boxes) if x0 <= ix <= x1 and y0 <= iy <= y1]
        if ev.secrets:
            seen["find"] += 1
            finds.add(sec)
        elif sec in secrets and not before[secrets.index(sec)]:
            seen["ledge"] += 1
        seen["refound"] += sec in secrets and before[secrets.index(sec)]
        seen["boxonly"] += bool(inbox) and sec not in secrets
        seen["out"] += not inbox
    want = dict(find=30, ledge=3, refound=10, boxonly=10, out=10)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)
    assert finds == set(secrets), finds


def test_the_secrets_follow_the_model(tmp_path):
    assert _run(tmp_path, "secret"), "the fj secrets parted from the model's _special_sector"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_broken_secrets_are_caught(tmp_path, mut):
    assert not _run(tmp_path, "secret_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
