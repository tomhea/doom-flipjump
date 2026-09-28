"""p2a_gate.py -- M7 P2a.1's gate: doors and keys, byte- and state-exact (docs/gp-doors-keys.md 4).

    python scratchpad/gp/p2a_gate.py --fjm build/<new>.fjm --labels <its label table>
    python scratchpad/gp/p2a_gate.py --oracle-only          # the scenarios and controls, no binary

Each scenario starts by POKING the game tier (the probe machinery b0_scenarios uses): at frame 0's
start the world mode, the player's pose and -- where the scenario says -- the blue card; at every
frame's start the held-key flags (kb_f, kb_b, kb_l, kb_r, kb_u). The binary then runs its own door
tic, player tic (the collision move, the card at every tried candidate, the walk-over triggers after
an accepted move) and render. At every present the probe reads the pose, all four cells of every
door, `dreq`, `pcard` and `wfired`, and the frame is held against THE ORACLE: doomfj.doors.DoorPhase
and ReferenceModel.step_sim (the card's touch per tried candidate) on the scene of the doors not yet
passable -- m2_std_gate's order -- rendered by probe.Oracle with the card hidden once it was taken
in the run. STATE-EXACT AND BYTE-EXACT ON EVERY FRAME.

THE SCENARIOS (the design's six, and the card taken on its platform):
  S1 blue door 71 without the card: use -> it stays shut
  S2 on the card's platform: walk onto it -> pcard 1, the card gone from the picture
  S3 blue door 71 with the card (pcard poked 1): use -> it opens
  S4 from sector 124, inside the card's box but 112 units below it: NOT taken (the reach test)
  S5 blazing door 84: use -> it opens in BLAZE_STRIDE-stop strides
  S6 over tag 5's trigger: door 77 opens and stays open past WAIT; back over it: nothing (W1)
  S7 over tag 6's trigger: door 145 the same
  S8 the exit (M7 P2a.2, docs/gp-exit.md): use held from the start is no press; released and
     pressed in the exit box -> the level ends (that frame still draws the world), LEVEL COMPLETE
     under held movement keys, enter -> the main menu, esc -> the FROZEN world, enter, enter -> NEW
     GAME at the boot skill: the level start, moving again. Menu keys are real key events.

THE CONTROLS (R9): every scenario names the rule it tests, and the ORACLE WITHOUT THAT RULE must
part from the oracle on some frame -- else the scenario could not see the rule broken and the gate
FAILS as vacuous. Since the binary is held to the oracle frame by frame, a binary that broke the rule
parts from it where the control does. Controls: `card` (the key check dropped), `no_card` (the card
never taken / not held), `reach` (the reach test dropped), `stride` (stride 1), `stay` (a closing
door closes), `w1` (a trigger that fires every crossing), `edge` (a held use presses every tic),
`frozen` (a finished level's world still tics), `restart` (NEW GAME forgets `lvdone`).
"""
from __future__ import annotations

import argparse
import contextlib
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

import probe as P                                                            # noqa: E402
import onewalk                                                               # noqa: E402
from doomfj import doors as D                                                # noqa: E402
from doomfj.doors import in_use_box_fixed                                    # noqa: E402
from doomfj.fixedpoint import _signed                                        # noqa: E402
from doomfj.reference_model import SimState                                  # noqa: E402
from doomfj.things import drawable_things                                    # noqa: E402
from doomfj.doors import exit_boxes                                          # noqa: E402
from doomfj.menu import LEVEL_DONE_SCR, menu_step, palette_colours, pixels   # noqa: E402
from doomfj.wall_renderer import (BOOT_SKILL, DEFAULT_MENU, DEFAULT_MENU_SELECTED,  # noqa: E402
                                  LEVEL_DONE_MENU, LEVEL_DONE_SELECTED, SKILL_MENU,
                                  SKILL_MENU_FIRST, SKILLS, STANDALONE_POLLS)
from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent             # noqa: E402

M32 = 0xFFFFFFFF
KEYFLAG = {"forward": "kb_f", "back": "kb_b", "turn_left": "kb_l", "turn_right": "kb_r",
           "use": "kb_u"}
READ = ("viewx", "viewy", "viewangle", "mode", "menu_scr", "dstate", "ddir", "dsub", "dwait", "dreq",
        "pcard", "wfired", "lvdone", "pusedn")
MENU_CODES = {"enter": 0x0D, "esc": 0x1B}
CARD_TYPE = 5


def bam(dx: float, dy: float) -> int:
    import math
    return int(round(math.atan2(dy, dx) / (2 * math.pi) * (1 << 32))) & M32


# ================================================================================================
# the oracle: DoorPhase + step_sim, with the controls
# ================================================================================================
class Mirror:
    """one scenario on the oracle. `ctl` drops ONE rule (the module docstring's controls)."""

    def __init__(self, dsim: "onewalk.DoorSim", card_di: int, ctl: str | None = None):
        self.sim, self.dp, self.ctl, self.card_di = dsim, dsim.dp, ctl, card_di
        self.exits = exit_boxes(dsim.lds, dsim.mw.vertexes(dsim.mapname))     # M7 P2a.2

    @contextlib.contextmanager
    def _rules(self):
        saved = (D.door_stride, D.door_stay)
        if self.ctl == "stride":
            D.door_stride = lambda kind: 1
        if self.ctl == "stay":
            D.door_stay = lambda kind: False
        try:
            yield
        finally:
            D.door_stride, D.door_stay = saved

    def run(self, pose, keys: list, pcard: int = 0) -> list:
        """-> per frame {"pose", "phase", "taken", "mode", "scr", "sel", "lvdone", "pusedn",
        "drawn"}: the state after the frame, and what it drew ("world", or the menu screen). The
        binary's order: the menu's state machine on the frame's events, then -- on a world frame,
        unless the level is done -- the door tic, the exit press, the player's move."""
        sim, dp = self.sim, self.dp
        st = SimState(pose[0], pose[1], pose[2], sim.mapname)
        ph = dp.initial()
        ph = (ph[0], ph[1], ph[2], pcard)
        taken, out = False, []
        mode, scr, sel = 0, 0, SKILLS.index(BOOT_SKILL)      # poked into the world; sel baked
        pusedn, lvdone = 1, 0                                  # baked: G_PlayerReborn's usedown
        with self._rules():
            for kd in keys:
                mode, scr, sel, ng = menu_step(mode, scr, sel, set(kd.get("menu", ())))
                if ng is not None:                            # NEW GAME: the level start
                    st = SimState(sim.spawn.x, sim.spawn.y, sim.spawn.angle, sim.mapname)
                    ph, taken, pusedn = dp.initial(), False, 1
                    if self.ctl != "restart":
                        lvdone = 0
                drawn = ("menu", scr, sel) if mode else "world"
                if mode == 0 and not (lvdone and self.ctl != "frozen"):
                    use = bool(kd.get("use"))
                    has_blue = {"card": True, "no_card": False}.get(self.ctl)
                    ph = dp.tic(ph, use, st.x, st.y, has_blue=has_blue)
                    if use:                                   # the exit: a PRESS in its box
                        if not pusedn or self.ctl == "edge":
                            pusedn = 1
                            if any(in_use_box_fixed(b, st.x, st.y) for b in self.exits):
                                lvdone, mode, scr = 1, 1, LEVEL_DONE_SCR
                    else:
                        pusedn = 0
                    blocked = frozenset(li for si in sim.order if ph[0][si][0] < sim.passes[si]
                                        for li in sim.lines_of.get(si, ()))
                    cur = [ph]

                    def touch(cx, cy, z):
                        if self.ctl == "no_card":
                            return
                        if self.ctl == "reach" and dp.card_at is not None:
                            z = dp.card_at[2]
                        cur[0] = dp.touch(cur[0], cx, cy, z)
                    new = sim.rm.step_sim(st, kd, scene=sim._scene(blocked), touch=touch)
                    ph = cur[0]
                    taken |= ph[3] == 1 and pcard == 0
                    if self.ctl == "w1":       # every crossing presses; the bits still read fired
                        was = ph[1]
                        ph = dp.after_move((ph[0], (0,) * len(was), ph[2], ph[3]), (st.x, st.y),
                                           (new.x, new.y))
                        ph = (ph[0], tuple(a | b for a, b in zip(was, ph[1])), ph[2], ph[3])
                    else:
                        ph = dp.after_move(ph, (st.x, st.y), (new.x, new.y))
                    st = new
                out.append({"pose": (st.x, st.y, st.angle), "phase": ph, "taken": taken,
                            "mode": mode, "scr": scr, "sel": sel, "lvdone": lvdone,
                            "pusedn": pusedn, "drawn": drawn})
        return out


def expected_cells(fr: dict, order: list) -> dict:
    ds, fired, req, card = fr["phase"]
    x, y, a = fr["pose"]
    doors = [ds[si] for si in order]
    return {"viewx": _signed(x, 32), "viewy": _signed(y, 32), "viewangle": a & M32,
            "mode": fr["mode"], "menu_scr": fr["scr"],
            "dstate": tuple(d[0] for d in doors), "ddir": tuple(d[1] for d in doors),
            "dsub": tuple(d[2] for d in doors), "dwait": tuple(d[3] for d in doors),
            "dreq": tuple(int(si in req) for si in order), "pcard": card,
            "wfired": P.wfired_value(fired), "lvdone": fr["lvdone"], "pusedn": fr["pusedn"]}


def screen(orc, scr: int, sel: int) -> bytes:
    """a menu screen's picture: the main menu, the skill screen at `sel`, or LEVEL COMPLETE"""
    lines, hi = {0: (DEFAULT_MENU, DEFAULT_MENU_SELECTED), 1: (SKILL_MENU, SKILL_MENU_FIRST + sel),
                 LEVEL_DONE_SCR: (LEVEL_DONE_MENU, LEVEL_DONE_SELECTED)}[scr]
    cfg = orc.rm.cfg
    colours = palette_colours(bytes(b for rgb in orc.mw.playpal(0) for b in rgb))
    return bytes(pixels(cfg.VIEW_W, cfg.VIEW_H, lines, hi, colours))


def menu_events(keys: list) -> list:
    """each frame's "menu" keys as the device's events: down on the frame's first poll, up next"""
    out = []
    for f, kd in enumerate(keys):
        for k, name in enumerate(kd.get("menu", ())):
            out += [KeyEvent(f * STANDALONE_POLLS + 2 * k, True, MENU_CODES[name]),
                    KeyEvent(f * STANDALONE_POLLS + 2 * k + 1, False, MENU_CODES[name])]
    return out


# ================================================================================================
# the scenarios, placed from the map
# ================================================================================================
def _ok(dsim, x16, y16) -> bool:
    return dsim.rm.check_position(dsim._scene(frozenset(li for si in dsim.order
                                                         for li in dsim.lines_of.get(si, ()))),
                                  x16, y16)[0]


def _sector(dsim, x, y) -> int:
    """the sector INDEX (x, y) lies in: its subsector's first seg -> linedef -> sidedef"""
    rm = dsim.rm
    cmap = dsim._scene(frozenset()).cmap
    seg = cmap.segs[cmap.subsectors[rm.point_in_subsector(cmap, x, y)].firstseg]
    ld = dsim.lds[seg.linedef]
    return dsim.sds[ld.front if seg.side == 0 else ld.back].sector


def door_front(dsim, si: int):
    """a standing pose inside door `si`'s use box, facing its nearest line, off the door sector"""
    box = dsim.boxes[si]
    verts = dsim.mw.vertexes(dsim.mapname)
    best = None
    for li in sorted(dsim.lines_of[si]):
        ld = dsim.lds[li]
        v1, v2 = verts[ld.v1], verts[ld.v2]
        mx, my = (v1.x + v2.x) / 2, (v1.y + v2.y) / 2
        nx, ny = -(v2.y - v1.y), (v2.x - v1.x)
        n = (nx * nx + ny * ny) ** 0.5
        for side in (1, -1):
            for d in (40, 48, 56, 64):
                x, y = round(mx + side * nx / n * d), round(my + side * ny / n * d)
                if _sector(dsim, x, y) != si and in_use_box_fixed(box, x << 16, y << 16) \
                        and _ok(dsim, x << 16, y << 16):
                    cand = (d, x, y, bam(mx - x, my - y))
                    best = min(best, cand) if best else cand
    assert best, "no standing pose in door %d's box" % si
    return (best[1] << 16, best[2] << 16, best[3])


def card_pose(dsim, card):
    """on the card's platform (its sector), 48 units off, facing it"""
    kx, ky, _kz = card
    ksec = _sector(dsim, kx, ky)
    for dx, dy in ((-48, 0), (48, 0), (0, -48), (0, 48), (-34, -34), (34, 34), (-34, 34), (34, -34)):
        x, y = kx + dx, ky + dy
        if _sector(dsim, x, y) == ksec and _ok(dsim, x << 16, y << 16):
            return (x << 16, y << 16, bam(-dx, -dy))
    raise AssertionError("no pose on the card's platform")


def below_card_pose(dsim, card, sector: int = 124, frames: int = 3):
    """standing in `sector` (floor 24: 112 units below the card), facing the card, near enough that a
    TRIED step lands inside the card's box -- proven by the reach control taking it; nearest first"""
    kx, ky, _kz = card
    pts = sorted(((dx * dx + dy * dy, kx + dx, ky + dy) for dx in range(-80, 81, 4)
                  for dy in range(-80, 81, 4)))
    for _d2, x, y in pts:
        if _sector(dsim, x, y) != sector or not _ok(dsim, x << 16, y << 16):
            continue
        pose = (x << 16, y << 16, bam(kx - x, ky - y))
        tr = Mirror(dsim, -1, "reach").run(pose, [{"forward": True}] * frames)
        if tr[-1]["phase"][3] == 1:
            return pose
    raise AssertionError("no pose in sector %d whose step reaches the card's box" % sector)


def exit_pose(dsim):
    """a standing pose inside the exit box, off the exit line, facing it"""
    (x0, y0, x1, y1), = exit_boxes(dsim.lds, dsim.mw.vertexes(dsim.mapname))
    verts = dsim.mw.vertexes(dsim.mapname)
    ld = [ld for ld in dsim.lds if ld.special in D.EXIT_SPECIALS][0]
    v1, v2 = verts[ld.v1], verts[ld.v2]
    mx, my = (v1.x + v2.x) / 2, (v1.y + v2.y) / 2
    nx, ny = -(v2.y - v1.y), (v2.x - v1.x)
    n = (nx * nx + ny * ny) ** 0.5
    for d in (32, 40, 48, 24, 56):
        for side in (1, -1):
            x, y = round(mx + side * nx / n * d), round(my + side * ny / n * d)
            if x0 <= x <= x1 and y0 <= y <= y1 and _ok(dsim, x << 16, y << 16):
                return (x << 16, y << 16, bam(mx - x, my - y))
    raise AssertionError("no standing pose in the exit box")


def trigger_pose(dsim, trig, back: int = 40):
    """`back` units before the trigger line's middle, facing across it"""
    _si, axis, coord, lo, hi = trig
    mid = (lo + hi) // 2
    for side in (-1, 1):
        a = coord + side * back
        x, y = (mid, a) if axis == "y" else (a, mid)
        if _ok(dsim, x << 16, y << 16):
            ang = bam(0, -side) if axis == "y" else bam(-side, 0)
            return (x << 16, y << 16, ang)
    raise AssertionError("no pose before trigger %s" % (trig,))


def _strides(tr, si: int, nstates: int) -> bool:
    """door `si` opened AND closed again, every move a full stride (BLAZE_STRIDE stops, clamped
    at the ends)"""
    st = [0] + [fr["phase"][0][si][0] for fr in tr]
    moves = [b - a for a, b in zip(st, st[1:]) if b != a]
    full = all(abs(m) == min(D.BLAZE_STRIDE, nstates - 1) for m in moves)
    return max(st) == nstates - 1 and st[-1] == 0 and full and len(moves) >= 2


def scenarios(dsim, card) -> list:
    kinds = dsim.dp.kinds
    blue = 71
    assert kinds[blue] == "blue", kinds[blue]
    blaze = [si for si, k in kinds.items() if k == "blaze"]
    assert blaze == [84], blaze
    trig = {t[0]: t for t in dsim.dp.triggers}
    assert sorted(trig) == [77, 145], trig
    n = dsim.nstates
    F, B, U, I = {"forward": True}, {"back": True}, {"use": True}, {}
    out = [
        {"name": "S1 blue door 71, no card: stays shut", "pose": door_front(dsim, blue),
         "keys": [U] * 3 + [I] * 12, "pcard": 0, "controls": ["card"],
         "claim": lambda tr: all(fr["phase"][0][blue][0] == 0 for fr in tr)},
        {"name": "S2 onto the card: taken, gone from the picture", "pose": card_pose(dsim, card),
         "keys": [F] * 4 + [I] * 2, "pcard": 0, "controls": ["no_card"],
         "claim": lambda tr: tr[-1]["phase"][3] == 1 and tr[-1]["taken"]},
        {"name": "S3 blue door 71 with the card: opens", "pose": door_front(dsim, blue),
         "keys": [U] * 3 + [I] * (D.SPEED * n[blue] + 2), "pcard": 1, "controls": ["no_card"],
         "claim": lambda tr: tr[-1]["phase"][0][blue][0] == n[blue] - 1},
        {"name": "S4 from sector 124 in the card's box: out of reach", "pose": below_card_pose(dsim, card),
         "keys": [F] * 3, "pcard": 0, "controls": ["reach"],
         "claim": lambda tr: all(fr["phase"][3] == 0 for fr in tr)},
        {"name": "S5 blazing door 84: opens and closes in strides", "pose": door_front(dsim, 84),
         "keys": [U] * 2 + [I] * (D.WAIT + 10), "pcard": 0, "controls": ["stride"],
         "claim": lambda tr: _strides(tr, 84, n[84])},
    ]
    for si, tag in ((77, 5), (145, 6)):
        t = trig[si]
        stay = D.SPEED * (n[si] - 1) + D.WAIT + 8
        out.append({"name": "S%d over tag %d's trigger: door %d opens, stays; back over: nothing"
                            % (6 if si == 77 else 7, tag, si),
                    "pose": trigger_pose(dsim, t), "keys": [F] * 5 + [I] * stay + [B] * 5 + [I] * 3,
                    "pcard": 0, "controls": ["stay", "w1"],
                    "claim": lambda tr, si=si: tr[-1]["phase"][0][si][0] == n[si] - 1
                    and sum(1 for fr in tr if si in fr["phase"][2]) == 1})
    F_ = {"forward": True}
    out.append({
        "name": "S8 the exit: a press ends the level; LEVEL COMPLETE; the frozen world; NEW GAME",
        "pose": exit_pose(dsim),
        "keys": [U, I, U, F_, F_, dict(F_, menu=["enter"]), dict(F_, menu=["esc"]), F_,
                 dict(F_, menu=["enter"]), {"menu": ["enter"]}, dict(F_, menu=["enter"]), F_, I],
        "pcard": 0, "controls": ["edge", "frozen", "restart"],
        "claim": lambda tr: (tr[1]["lvdone"], tr[2]["lvdone"]) == (0, 1)
        and tr[2]["drawn"] == "world" and tr[3]["drawn"] == ("menu", LEVEL_DONE_SCR, tr[3]["sel"])
        and tr[5]["drawn"][:2] == ("menu", 0) and tr[6]["drawn"] == "world"
        and tr[7]["pose"] == tr[2]["pose"] and tr[10]["lvdone"] == 0
        and tr[11]["pose"] != tr[10]["pose"]})
    return out


# ================================================================================================
# the run
# ================================================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fjm")
    ap.add_argument("--labels")
    ap.add_argument("--oracle-only", action="store_true", help="the scenarios and controls, no binary")
    a = ap.parse_args(argv)
    if not a.oracle_only and not (a.fjm and a.labels):
        ap.error("--fjm and --labels (the build's label table), or --oracle-only")
    t0 = time.time()
    orc = P.Oracle()
    dsim = onewalk.DoorSim()
    assert dsim.order == orc.door_order
    card = dsim.dp.card_at
    assert card == (2192, 576, 136), card
    card_di = [di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
               if t.type == CARD_TYPE]
    assert len(card_di) == 1, card_di
    scen = scenarios(dsim, card)
    ok = True
    print("P2A GATE -- %d scenarios%s" % (len(scen), "" if a.oracle_only else ", %s" % a.fjm))
    if not a.oracle_only:
        gb = P.GameBinary(ROOT / a.fjm)
        cells = P.game_cells(orc.ndoors, orc.nwalk)
        table = P.LabelTable.load(ROOT / a.labels, {c.label for c in cells.values()})
        assert not table.absent & {"dreq", "pcard", "wfired"}, (
            "the label table has no %s: a binary before P2a.1" % sorted(table.absent))
    for sc in scen:
        want = Mirror(dsim, card_di[0]).run(sc["pose"], sc["keys"], sc["pcard"])
        claim = bool(sc["claim"](want))
        ok &= claim
        print("\n%s -- %d frames from (%.0f, %.0f) angle %08x%s" % (
            sc["name"], len(sc["keys"]), sc["pose"][0] / 65536, sc["pose"][1] / 65536, sc["pose"][2],
            ", pcard poked 1" if sc["pcard"] else ""))
        print("  the oracle does what the scenario claims: %s" % ("yes" if claim else "NO -- FAIL"))
        for ctl in sc["controls"]:
            alt = Mirror(dsim, card_di[0], ctl).run(sc["pose"], sc["keys"], sc["pcard"])
            part = next((f for f, (x, y) in enumerate(zip(want, alt))
                         if expected_cells(x, dsim.order) != expected_cells(y, dsim.order)), None)
            ok &= part is not None
            print("  CONTROL %-8s the oracle without the rule parts at frame %s%s" % (
                ctl, part, "" if part is not None else " -- NEVER: the scenario is VACUOUS, FAIL"))
        if a.oracle_only:
            continue
        reads = []
        p = P.Probe(cells, table, gb.width)

        def start(pr, f, sc=sc):
            vals = {k: int(bool(sc["keys"][f].get(n))) for n, k in KEYFLAG.items()}
            if f == 0:
                vals.update({"mode": 0, "viewx": _signed(sc["pose"][0], 32),
                             "viewy": _signed(sc["pose"][1], 32), "viewangle": sc["pose"][2],
                             "pcard": sc["pcard"]})
            pr.write_cells(vals)
        p.on_frame_start(start)
        p.on_present(lambda pr, f: reads.append(pr.read_cells(list(READ))))
        r = gb.run(len(sc["keys"]), menu_events(sc["keys"]), p)
        s_bad = x_bad = None
        for f, fr in enumerate(want):
            exp = expected_cells(fr, dsim.order)
            got = reads[f] if f < len(reads) else {}
            if s_bad is None and any(got.get(k) != v for k, v in exp.items()):
                s_bad = (f, {k: (got.get(k), v) for k, v in exp.items() if got.get(k) != v})
            if fr["drawn"] == "world":
                pic = orc.render(fr["pose"][0], fr["pose"][1], fr["pose"][2],
                                 tuple(fr["phase"][0][si][0] for si in dsim.order),
                                 hidden_extra=card_di if fr["taken"] else ())
            else:
                pic = screen(orc, fr["drawn"][1], fr["drawn"][2])
            if x_bad is None and (f >= len(r.frames) or r.frames[f] != pic):
                x_bad = (f, P.px_diff(r.frames[f], pic) if f < len(r.frames) else -1)
        ok &= s_bad is None and x_bad is None
        print("  binary: %d frames, %s ops -- STATE %s, PIXELS %s" % (
            len(r.frames), format(r.ops, ","),
            "exact on every frame" if s_bad is None else "PART at frame %d: %s" % s_bad,
            "byte-exact on every frame" if x_bad is None else "PART at frame %d (%d px)" % x_bad))
    print("\nP2A GATE %s (%.0f s)" % ("PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
