"""p67e_visibility_probe.py -- M7 P6+P7 package E, the owner's VISIBILITY requests (2026-10-05): "sometimes monsters
went off screen if the scene was 'too much'. make sure monsters are almost always seen"; "sometimes [the fireball]
doesn't show at all ... you must always show the fireballs"; "monsters get off-rendered when I move a little bit to some
side ... a really small part of them is behind a corpse ... monsters should always be shown".

ORACLE ONLY (no build, no fj). Replays a frozen combat set's runs on the model (`scenarios_v2`, at the set's own monster
tempo, or `--tempo N`) and, after every K-th frame, renders the game picture TWICE from the gate oracle's inputs (the
monsters' positions and views, the mobiles, the doors and movers -- probe.Oracle's scene):
  * DEFAULT: blocked48's game picture (`exempt_actors=False`: DEG_SOFT_MON = 4, the B-gate on every thing, the
    mobiles scenery at MIN_SPRITE_H, a sprite with no row in the view still holding its fragment slots);
  * EXEMPT: the actors rule (`exempt_actors=True`, reference_model.render_wall_frame: the game tier's picture).
For each picture it attributes every sprite fragment slot to the thing whose column loop wrote it (a wrapper on
`ReferenceModel.project_thing` that reads the caller's frame -- census_lib's technique -- and diffs the two fragment
slot arrays between consecutive calls), and counts per frame:
  * SEEN: the LIVE monsters with an open column at their BASE size (the D3 e "seen" set) AND a row inside the
    view (a monster in a pit under the view has no pixel to show): what the player should see;
  * DRAWN: the live monsters that claimed at least one fragment slot;
  * MISSING = SEEN - DRAWN. DEFAULT's split: `soft` (refused at the budget's projection with the raised bar, accepted
    in EXEMPT), `slots` (projected, but no column took it), `other`. EXEMPT's split, from the slots at the moment
    the monster was recorded: `bgate` (slot A taken, B refused), `full` (both taken), `empty` (a free slot A where
    its sprite column is empty), `other`;
  * the MOBILES (fireballs, blood) that claimed a slot with a row inside the view, of those alive;
  * the cost proxy: the extra things recorded (past every reject) and the extra fragment columns EXEMPT records.

    PYTHONPATH="src;." python scratchpad/gp/p67e_visibility_probe.py [--set F] [--tempo N] [--runs 0,3] [--every K]

Its R9 control (`--selftest`): R0-aftermath's frame 57, where the player stands on a corpse, must show DEFAULT missing
live monsters (the corpse's off-view fragments holding slot A, the monsters behind B-gated) and EXEMPT strictly fewer;
and DEG_SOFT_MON forced to 1 must show `soft` losses.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

import probe as P                                                            # noqa: E402
import scenarios_v2 as S                                                     # noqa: E402
from doomfj import reference_model as RMOD                                   # noqa: E402
from doomfj.monsters import MonsterPhase                                     # noqa: E402
from doomfj.reference_model import GAME_RENDER_KW                            # noqa: E402

def _budget_line() -> int:
    import inspect
    lines, first = inspect.getsourcelines(RMOD.ReferenceModel.render_wall_frame)
    hits = [first + i for i, ln in enumerate(lines) if ln.strip().startswith("pr = self.project_thing(")]
    assert len(hits) == 1, hits
    return hits[0]


BUDGET_LINE = _budget_line()


def _onview(r, H) -> bool:
    """a projection (x1, x2, ytop, h, ...) whose drawn bucket [ytop + h - hb, ytop + h) meets the view's rows"""
    hb = RMOD.sprite_bucket_height(RMOD.sprite_bucket(r[3], H), H)
    y0 = r[2] + r[3] - hb
    return y0 < H and y0 + hb > 0


class Attribution:
    """wraps ReferenceModel.project_thing for one render: which drawable claimed which fragment slots"""

    def __init__(self):
        self.orig = RMOD.ReferenceModel.project_thing
        self.reset()

    def reset(self):
        self.last = None                 # (t_di, mon, sfrag snapshot, sfrag2 snapshot) of the last accepted thing
        self.frag = Counter()            # t_di -> columns claimed
        self.accepted = {}               # t_di -> mon flag (projected at the budget site)
        self.rejected = set()            # monster t_di rejected at the budget site
        self.cause = {}                  # monster t_di that claimed nothing -> "bgate" / "full" / "empty"
        self.owner = {}                  # column -> the t_di whose fragment holds its slot A
        self.tz = {}                     # accepted t_di -> its projected depth (16.16)
        self.blockers = []               # (monster t_di, its tz, [(slot-A owner t_di, owner tz)]) for each bgate
        self.onview = {}                 # t_di -> its projection has a row inside the view (seen site, then budget)
        self.arrays = None
        self.budget_line = None

    def _flush(self, sfrag, sfrag2):
        if self.last is None:
            return
        di, mon, a, b, dr, x1, x2 = self.last
        n = sum(1 for x in range(len(sfrag)) if sfrag[x] != a[x]) + sum(
            1 for x in range(len(sfrag2)) if sfrag2[x] != b[x])
        self.frag[di] += n
        for x in range(len(sfrag)):
            if sfrag[x] != a[x]:
                self.owner[x] = di
        if mon and not n:
            cols = [x for x in range(max(0, x1), min(len(dr), x2 + 1)) if not dr[x]]
            if any(a[x] is None for x in cols):
                self.cause[di] = "empty"         # a free slot A, and the sprite's column there is empty
            elif any(b[x] is None for x in cols):
                self.cause[di] = "bgate"         # slot A taken by a nearer sprite, slot B refused (hb < DEG_SPRB_MINH)
                own = sorted({self.owner.get(x) for x in cols})
                self.blockers.append((di, self.tz.get(di), [(o, self.tz.get(o)) for o in own]))
            else:
                self.cause[di] = "full"          # both fragment slots taken by nearer sprites
        self.last = None

    def __enter__(self):
        me = self

        def wrapped(rm, *a, **k):
            f = sys._getframe(1)
            loc = f.f_locals
            if f.f_code.co_name == "render_wall_frame" and "sfrag" in loc and "t_di" in loc:
                sfrag, sfrag2 = loc["sfrag"], loc["sfrag2"]
                me.arrays = (sfrag, sfrag2)
                me._flush(sfrag, sfrag2)
                r = me.orig(rm, *a, **k)
                # the budget site: the line of `pr = self.project_thing(` (the seen site is a different line)
                budget = f.f_lineno == BUDGET_LINE
                if r is not None:
                    me.onview[loc["t_di"]] = _onview(r, loc["H"])
                if budget:
                    di, mon = loc["t_di"], bool(loc["mon"])
                    if r is not None:
                        me.accepted[di] = mon
                        me.tz[di] = r[5]
                        me.last = (di, mon, list(sfrag), list(sfrag2), list(loc["drawn"]), r[0], r[1])
                    elif mon:
                        me.rejected.add(di)
                return r
            return me.orig(rm, *a, **k)
        RMOD.ReferenceModel.project_thing = wrapped
        return self

    def finish(self):
        if self.arrays is not None:
            self._flush(*self.arrays)

    def __exit__(self, *exc):
        RMOD.ReferenceModel.project_thing = self.orig
        return False



def render(orc, mph, exempt, deg_things=None):
    w = mph.world
    ws = w.ws
    x16, y16 = ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF
    mv = orc._mv(w)
    hidden = set(orc.hidden) | {mv.mdi[m] for m in range(w.layout.nmon) if not ws.mon_active[m]}
    seen = set()
    mobs = mph.mobiles()
    att = Attribution()
    with att:
        orc.rm.render_wall_frame(RMOD.SimState(ws.px, ws.py, ws.pangle, orc.mapname),
                                 orc.scene_for(tuple(ws.d_state), w.mover_heights_now()),
                                 sprite_wad=orc.art, thing_hidden=hidden,
                                 thing_views=mv(mph, x16, y16), seen_out=seen,
                                 thing_positions=mv.positions(mph), mobiles=mobs,
                                 **dict(GAME_RENDER_KW, exempt_actors=exempt, deg_things=deg_things))
        att.finish()
    # the LIVE monsters (a corpse is not what the owner asked about; its fragments still count in the cost)
    # ... and of those, the ones with a row inside the view: a monster in a pit under the view is seen (an open
    # column) yet has no pixel to show, whatever the rule (the oracle's seen test has no vertical part)
    mons = {mv.mdi[m] for m in range(w.layout.nmon) if ws.mon_active[m] and ws.mon_health[m] > 0}
    drawn = {di for di, n in att.frag.items() if n and di in mons}
    return {"seen": {di for di in seen & mons if att.onview.get(di)}, "drawn": drawn, "accepted": {d for d, m in att.accepted.items() if m},
            "rejected": att.rejected, "cols": sum(att.frag.values()), "nacc": len(att.accepted),
            "mob": len(mobs), "mob_drawn": sum(1 for di, n in att.frag.items() if n and di >= mv.n and att.onview.get(di)),
            "cause": att.cause, "blockers": att.blockers}


def frame_stats(orc, mph, soft_default):
    base = (RMOD.DEG_SOFT_SCENERY, RMOD.DEG_MINH2_SCENERY, soft_default, RMOD.DEG_MINH2_MON)
    d, e = render(orc, mph, False, base), render(orc, mph, True, base)
    miss_d = d["seen"] - d["drawn"]
    soft = {di for di in miss_d if di in d["rejected"] and di in e["accepted"]}
    slots = {di for di in miss_d - soft if di in d["accepted"]}
    ce = Counter(e["cause"].get(di, "other") for di in e["seen"] - e["drawn"])
    return {"seen": len(d["seen"]), "miss_d": len(miss_d), "miss_e": len(e["seen"] - e["drawn"]),
            "soft": len(soft), "slots": len(slots), "other": len(miss_d - soft - slots),
            "e_bgate": ce["bgate"], "e_full": ce["full"], "e_empty": ce["empty"], "e_other": ce["other"],
            "cols_d": d["cols"], "cols_e": e["cols"], "nacc_d": d["nacc"], "nacc_e": e["nacc"],
            "mob": d["mob"], "mob_d": d["mob_drawn"], "mob_e": e["mob_drawn"]}


def replay_run(run, orc, tempo, every, soft_default, frames=None):
    w = S.start_world(run["setup"])
    if tempo is not None:
        w.monster_tics = tempo
    mph = MonsterPhase.__new__(MonsterPhase)
    mph.world, mph.gd = w, S.gd
    rows = []
    for f, k in enumerate(run["keys"]):
        w.tic(S.str_to_keys(k))
        if (f in frames) if frames is not None else (f % every == 0):
            rows.append(frame_stats(orc, mph, soft_default))
    return rows, w


def summarize(name, rows):
    n = len(rows)
    tot = Counter()
    for r in rows:
        tot.update(r)
    fd = sum(1 for r in rows if r["miss_d"])
    fe = sum(1 for r in rows if r["miss_e"])
    line = ("%-20s frames %4d  live seen %4d  MISSING default %3d (frames %3d: soft %d, slots %d, other %d)  "
            "exempt %3d (frames %3d: bgate %d, full %d, empty %d, other %d)  mobiles drawn %d of %d -> %d  "
            "+things recorded %.2f/frame  +fragment columns %.1f/frame"
            % (name, n, tot["seen"], tot["miss_d"], fd, tot["soft"], tot["slots"], tot["other"], tot["miss_e"], fe,
               tot["e_bgate"], tot["e_full"], tot["e_empty"], tot["e_other"], tot["mob_d"], tot["mob"], tot["mob_e"],
               (tot["nacc_e"] - tot["nacc_d"]) / max(1, n), (tot["cols_e"] - tot["cols_d"]) / max(1, n)))
    return line, tot, fd, fe


def selftest(orc) -> int:
    """R9 (see the docstring): the corpse frame and the forced soft count must each show the loss DEFAULT has"""
    doc = json.loads((HERE / "scenarios" / "combat_scenarios_v5.json").read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    after = next(r for r in doc["runs"] if r["name"] == "R0-aftermath")
    rows, _w = replay_run(after, orc, None, 1, RMOD.DEG_SOFT_MON, frames={57})
    corpse_ok = rows[0]["miss_d"] > rows[0]["miss_e"]
    court = next(r for r in doc["runs"] if r["name"] == "R0-imp-court")
    rows2, _w = replay_run(dict(court, keys=court["keys"][:40]), orc, None, 4, 1)
    soft = sum(r["soft"] for r in rows2)
    ok = corpse_ok and soft > 0
    print("selftest: R0-aftermath frame 57 missing %d -> %d (must drop); DEG_SOFT_MON=1: %d soft losses (must be > 0)"
          " -> %s" % (rows[0]["miss_d"], rows[0]["miss_e"], soft, "PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", default=str(HERE / "scenarios" / "combat_scenarios_v5.json"))
    ap.add_argument("--tempo", type=int, default=None, help="override the set's monster tempo")
    ap.add_argument("--runs", default=None, help="comma-separated run indices (default all)")
    ap.add_argument("--every", type=int, default=1, help="probe every K-th frame")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    orc = P.Oracle()
    if a.selftest:
        return selftest(orc)
    doc = json.loads(Path(a.set).read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    idx = [int(i) for i in a.runs.split(",")] if a.runs else range(len(doc["runs"]))
    print("set %s, monster tempo %s, every %d frame(s); DEFAULT = blocked48's picture, EXEMPT = the actors rule"
          % (Path(a.set).name, a.tempo or S.MONSTER_TICS, a.every), flush=True)
    allrows = []
    t0 = time.time()
    for i in idx:
        run = doc["runs"][i]
        rows, w = replay_run(run, orc, a.tempo, a.every, RMOD.DEG_SOFT_MON)
        print(summarize(run["name"], rows)[0] + "  dead %d" % w.ws.p_dead, flush=True)
        allrows += rows
    print(summarize("ALL", allrows)[0] + "  (%.0f s)" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
