"""playthrough_gate.py -- THE AUTO-GAMEPLAY GATE (docs/episode-plan.md 5): the level PLAYED on the game binary, start to
LEVEL COMPLETE, by real play, with the oracle checking every frame.

    python scratchpad/gp/playthrough_gate.py --map E1M2 --fjm build/doom_e1m2_r4.fjm \
        --labels scratchpad/12m/atlas/e1m2_r4.labels.tsv.gz [--skill easy] [--budget 6000] [--route FILE]
    ... --model-only        # the steering on the ORACLE alone (no binary, no picture): a dev loop, never evidence
    ... --controls-only     # the two R9 controls alone (short)
    wrap it: python scripts/heavy.py play --log <file> -- python scratchpad/gp/playthrough_gate.py ...

WHAT IT RUNS. The route (scripts/level_route.py: the keys in order, the switches, lifts and floors, the exit) planned
from the map, at the skill; the binary booted to its menu and a NEW GAME picked at the skill (m2_std_gate.boot_pick);
then every frame's keys DECIDED at the frame's start from the cells the BINARY presented (scripts/play.py's Steer:
pursuit along each leg's path, doors pressed open, lifts waited for and ridden, monsters the picture saw and that
hunt the player turned to and shot) and delivered as real key events. No cheat: no cell is ever written, no god
mode, no warp -- a pistol start (DOOM's -warp), every key one a player could press.

WHAT IT CHECKS, EVERY FRAME (menus, the world, LEVEL COMPLETE): the oracle (p2a_gate.Mirror.steps from boot, the same
keys by the device's own rule) and the binary byte-exact (the picture), palette-exact and state-exact (every cell
p2a_gate.expected_cells names, read through the build's label table) -- fight_gate.binary_scenario's three checks.

VERDICT. PASS when LEVEL COMPLETE shows (the oracle's and the binary's `mode` 1, `menu_scr` LEVEL COMPLETE's, `lvdone`
1) and stays exact through its hold to the screen that takes a key. FAIL on the first frame that parts (it writes
playthrough_mismatch_f<n>.png: binary | oracle | diff), on the player's death (reported with the frame, the place and
the attacker), or when the frame budget runs out (where the steering was).

R9 -- THE CONTROLS, run first, each on the same composition for CONTROL_FRAMES frames: `keys` -- the ORACLE's keys
mutated on one world frame (a turn added): the state must part on that frame; `pixel` -- one pixel of the BINARY's
picture changed on one frame: the picture check must part on exactly that frame. A gate whose controls do not fail
does not run its play.

THE STEERING SEED (DEFAULT_SEED, --seed, --search). The steering is deterministic, and so are the binary and the model:
a play is a function of (map, skill, steering code, seed). The seed shifts the dodge rhythm, the fight range and the
health threshold -- each seed is a different, equally real play. `--model-only --search ROUNDS` finds a seed (or a
schedule F:N,F:N: seed N from frame F on) that reaches LEVEL COMPLETE on the model alone, at ~0.15-0.25 s a frame and
with no heavy lock; since the steering reads exactly the cells the oracle checks, the binary run with that seed makes
the same play key for key (or parts from the oracle, which is a FAIL). A change to play.py's Steer moves every play:
re-search and re-pin DEFAULT_SEED after one. The final creator's order: search on the model, then the gate on the
binary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "scripts", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))
if __name__ == "__main__":                         # `--map E1Mn` before probe / gamespeed read their defaults
    from doomfj.mapprofile import take_map_arg
    take_map_arg(keep=True)

# the skill and the steering seed each shipped map's playthrough PASSES at by real play (the defaults; --skill /
# --seed override). The seed only shifts the steering's dodge rhythm: every seed is real play, none is a cheat
DEFAULT_SKILL = {"E1M1": "medium", "E1M2": "easy", "E1M3": "easy", "E1M4": "easy", "E1M5": "easy"}
# found by --search on the model (M8 bot, the steering of 8c9324ec): each a whole play from boot to LEVEL COMPLETE
DEFAULT_SEED = {("E1M1", "medium"): 1,                                                      # world 499
                ("E1M2", "easy"): [(0, 1), (1532, 2), (3463, 22), (3992, 32)],             # world 4319
                ("E1M3", "easy"): [(0, 0), (415, 1)],                                       # world 2279 (3143 before 8183305d)
                ("E1M5", "easy"): [(0, 0), (342, 3), (1630, 11), (3352, 24)],              # world 4253
                ("E1M6", "easy"): 0,                                                         # world 964
                ("E1M8", "easy"): 0,                    # world 1709 (the M8 C8 kill leg: both Barons, then the W1 exit)
                ("E1M9", "easy"): 2}                                                         # world 4659
# THE SPEED SET (the owner, 2026-10-29: every level's speed set is "an average active game" -- the level's own
# playthrough, E1M1's included, in place of the checkpoint-planned combat sets): SPEED_WINDOWS windows of SPEED_FRAMES
# world frames spread evenly from NEW GAME to LEVEL COMPLETE, each window's average from the probe's frame-start
# readings (a window's sum telescopes between two readings: within 2^18 ops, i.e. +-2,622 ops/frame on its average),
# and the binding statistic is gamespeed's (mean + p80) / 2 over the windows -- B0's, so CAP-22 reads the same way.
SPEED_WINDOWS, SPEED_FRAMES = 11, 100


def speed_windows(frame_ops, start: int, end: int, n: int = SPEED_WINDOWS, w: int = SPEED_FRAMES):
    """[(the window's first frame, its average ops/frame)] -- n windows of w frames spread evenly over [start, end)
    (overlapping when the play is shorter than n * w frames: E1M1's)"""
    span = end - start
    assert span >= w and len(frame_ops) >= end, (span, w, len(frame_ops), end)
    starts = [start + round(k * (span - w) / (n - 1)) for k in range(n)]
    return [(s, sum(frame_ops[s:s + w]) / w) for s in starts]


def speed_record(frame_ops, start: int, end: int) -> dict:
    """the speed set's numbers: the windows, their mean and p80, the binding (gamespeed.binding_speed)"""
    import gamespeed as GS
    win = speed_windows(frame_ops, start, end)
    avgs = [v for _s, v in win]
    return {"windows": [[s - start, round(v)] for s, v in win], "world_frames": end - start,
            "mean": sum(avgs) / len(avgs), "p80": GS.percentile_run(avgs), "binding": GS.binding_speed(avgs),
            "target": GS.SPEED_TARGET, "window_frames": SPEED_FRAMES}


CONTROL_FRAMES = 40           # world frames a control runs
CONTROL_AT = 25               # the world frame a control mutates


def parse_seed(text):
    """`--seed`: an int, or a schedule `frame:seed,frame:seed,...` (the seed in force from each frame on)"""
    if text is None:
        return None
    if ":" not in str(text):
        return int(text)
    return [tuple(int(v) for v in part.split(":")) for part in str(text).split(",")]


def seed_text(seed) -> str:
    return str(seed) if isinstance(seed, int) else ",".join("%d:%d" % fs for fs in seed)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", default=None)
    ap.add_argument("--fjm")
    ap.add_argument("--labels")
    ap.add_argument("--skill", default=None, choices=("easy", "medium", "hard"))
    ap.add_argument("--budget", type=int, default=6000, help="world frames before FAIL")
    ap.add_argument("--seed", default=None, help="the steering's dodge rhythm: N or a schedule F:N,F:N (default: the "
                                                 "map's DEFAULT_SEED)")
    ap.add_argument("--route", default=None, help="a level_route.py JSON (default: planned now)")
    ap.add_argument("--model-only", action="store_true")
    ap.add_argument("--search", type=int, default=0, metavar="ROUNDS",
                    help="--model-only: on a death, re-play with the seed changed SEARCH_BACK frames before it, keep "
                         "the attempt that got furthest, up to ROUNDS rounds -> a seed schedule for DEFAULT_SEED")
    ap.add_argument("--search-seeds", default="1,2,3,4", help="--search: the seeds tried each round")
    ap.add_argument("--search-workers", type=int, default=6, help="--search: attempts run at once (processes)")
    ap.add_argument("--controls-only", action="store_true")
    ap.add_argument("--no-controls", action="store_true", help="skip the R9 controls (a dev run; never PASS evidence)")
    ap.add_argument("--keys-out", default=None, help="write the played key log (JSON) here")
    ap.add_argument("--speed-json", default=None, help="a binary PASS: write the speed set's record (JSON) here")
    ap.add_argument("--workers", type=int, default=3, help="processes rendering the oracle's world pictures")
    ap.add_argument("--trace", action="store_true", help="one line a world frame: pose, health, keys, the steering")
    a = ap.parse_args(argv)
    import play as PLAY
    import level_route as LR
    from doomfj.mapprofile import ACTIVE
    mapname = (a.map or ACTIVE).upper()
    skill = a.skill or DEFAULT_SKILL.get(mapname, "easy")
    if not a.model_only and not (a.fjm and a.labels):
        ap.error("--fjm and --labels (the build's label table), or --model-only")
    t0 = time.time()
    if a.route:
        doc = json.loads(Path(a.route).read_text())
        route = doc["skills"][skill] if "skills" in doc else doc
    else:
        route = LR.plan(mapname, skill)
    print("PLAYTHROUGH GATE -- %s at %s%s" % (mapname, skill, "" if a.model_only else ", %s" % a.fjm), flush=True)
    print(LR.summary(route), flush=True)
    if not route.get("ok") or not all(g.get("path") for g in route.get("legs", ())):
        print("\nPLAYTHROUGH GATE FAIL -- no route (%s)" % route.get("why", "a leg has no path"))
        return 1
    if not route["exit"]["model"]:
        print("\nPLAYTHROUGH GATE FAIL -- the route's exit (special %d) is not in the model" % route["exit"]["special"])
        return 1
    pl = PLAY.Player(a.fjm, a.labels, skill, check=True) if not a.model_only else _model_player(PLAY, skill)
    pl.workers = 0 if a.model_only else a.workers
    lv = LR.Level(mapname, route.get("wad"), skill)
    print("setup %.0f s (NEW GAME on frame %d)" % (time.time() - t0, pl.mf), flush=True)

    # ---- R9: the controls, first
    if not (a.model_only or a.no_controls):
        ok_ctl = controls(PLAY, pl)
        if a.controls_only:
            print("\nCONTROLS %s" % ("PASS" if ok_ctl else "FAIL"))
            return 0 if ok_ctl else 1
        if not ok_ctl:
            print("\nPLAYTHROUGH GATE FAIL -- a control did not part: the comparison is vacuous")
            return 1

    seed = parse_seed(a.seed) if a.seed is not None else DEFAULT_SEED.get((mapname, skill), 0)
    if a.search:
        if not a.model_only:
            ap.error("--search is a --model-only tool")
        seed = search(PLAY, pl, route, lv, seed, a.budget, a.search,
                      tuple(int(v) for v in a.search_seeds.split(",")), workers=a.search_workers)
    print("steering seed %s" % seed_text(seed), flush=True)
    res = play(PLAY, pl, route, lv, seed, a.budget, a.model_only, a.trace)
    r, steer, st = res["r"], res["steer"], res["st"]
    wall = time.time() - t0
    if a.keys_out:
        Path(a.keys_out).write_text(json.dumps({"map": mapname, "skill": skill, "fjm": a.fjm, "seed": seed_text(seed),
                                                "keys": ["".join(PLAY.NAME_LET[n] for n in sorted(k))
                                                         for k in r["keys"]]}))
    print("")
    print("frames: %d presented (%d menu, %d world), legs done %d/%d: %s" % (
        r["frames"], pl.mf, r["frames"] - pl.mf, len(steer.events), len(steer.legs),
        ", ".join("%s@w%d" % (e[2], e[0] - pl.mf) for e in steer.events)))
    print("time: %.0f s wall; the binary %.0f s (%.1f ms/frame), the oracle %.0f s (%.0f ms/frame); %s ops; seed %s" % (
        wall, r["t_binary"], 1000 * r["t_binary"] / max(1, r["frames"]), r["t_oracle"],
        1000 * r["t_oracle"] / max(1, r["frames"]), format(r["ops"], ","), seed_text(seed)))
    if r["mismatch"]:
        mm = r["mismatch"]
        dump_mismatch(pl, r)
        print("\nPLAYTHROUGH GATE FAIL -- the binary parted from the oracle at frame %d (world %d): %d cells %s, "
              "%d px, palette %s" % (mm["frame"], mm["frame"] - pl.mf, mm["ncells"], mm["cells"], mm["px"],
                                     mm["palette"]))
        return 1
    if st["dead"] is not None:
        f, x, y, atk = st["dead"]
        print("\nPLAYTHROUGH GATE FAIL -- the player DIED at frame %d (world %d) at (%d, %d), p_atk %s, on leg %d -> %s"
              % (f, f - pl.mf, x, y, atk, steer.li, steer.leg["to"] if steer.leg else "-"))
        return 1
    if st["done"] is None:
        x, y, _a = PLAY.pose_of(r["last"]["cells"])
        print("\nPLAYTHROUGH GATE FAIL -- the frame budget (%d world frames) ran out at (%d, %d) on leg %d -> %s"
              % (a.budget, x, y, steer.li, steer.leg["to"] if steer.leg else "-"))
        return 1
    exact = "" if a.model_only else "byte-, palette- and state-exact on all %d frames, " % r["frames"]
    label = ("PASS (model only -- NOT evidence)" if a.model_only else
             "PASS (no controls -- NOT evidence)" if a.no_controls else "PASS")
    print("\nPLAYTHROUGH GATE %s -- %s LEVEL COMPLETE at frame %d (world %d) at %s, %s%.0f s"
          % (label, mapname, st["done"], st["done"] - pl.mf, skill, exact, wall))
    if not a.model_only and r.get("frame_ops"):
        sp = speed_record(r["frame_ops"], pl.mf, st["done"])
        p80w = next(wv for wv in sp["windows"] if round(sp["p80"]) == wv[1])
        print("PLAYTHROUGH SPEED binding (mean + p80)/2 over %d windows of %d world frames: %s ops/frame (mean %s, p80 "
              "window at world %d = %s; target <= %s) %s" % (
                  len(sp["windows"]), sp["window_frames"], format(int(round(sp["binding"])), ","),
                  format(int(round(sp["mean"])), ","), p80w[0], format(p80w[1], ","), format(sp["target"], ","),
                  "PASS" if sp["binding"] <= sp["target"] else "OVER"))
        if a.speed_json:
            sp.update(map=mapname, skill=skill, fjm=a.fjm, seed=seed_text(seed), level_complete_world=st["done"] - pl.mf)
            Path(a.speed_json).write_text(json.dumps(sp, indent=1) + "\n", encoding="ascii")
    return 0


def play(PLAY, pl, route, lv, seed, budget, model_only, trace=False, quiet=False):
    """ONE play of the route with steering seed `seed`: -> {"r": the run, "steer", "st": done / dead frames}"""
    from doomfj.menu import LEVEL_DONE_SCR, LEVEL_DONE_SCREENS
    log = (lambda s: None) if quiet else (lambda s: print(s, flush=True))
    steer = PLAY.Steer(route, lv=lv, log=log, seed=seed)
    steer.rt = pl.monster_rows()
    st = {"done": None, "dead": None, "hold": 0, "lastlog": 0, "hp": None, "t": time.time()}

    def on_frame(rec):
        c, f = rec["cells"], rec["f"]
        if f < pl.mf:
            return None
        if st["hp"] is not None and c.get("p_hp") is not None and c["p_hp"] < st["hp"]:
            steer.hurt_f = f
        st["hp"] = c.get("p_hp")
        if c.get("p_dead") and st["dead"] is None:
            x, y, _a = PLAY.pose_of(c)
            st["dead"] = (f, x, y, c.get("p_atk"))
            return "stop"
        mode, scr = c.get("mode"), c.get("menu_scr")
        if mode == 1 and c.get("lvdone") == 1 and scr in LEVEL_DONE_SCREENS:
            if st["done"] is None:
                st["done"] = f
                if steer.leg is not None and steer.leg["to"] == "exit":
                    steer._next(f, "LEVEL COMPLETE")
            if scr == LEVEL_DONE_SCR:                 # through the hold: the screen that takes a key, exact too
                st["hold"] += 1
                if st["hold"] >= 2:
                    return "stop"
        if trace:
            x, y, ang = PLAY.pose_of(c)
            log("    t%d (%d,%d) a%d hp %s %s %s" % (f - pl.mf, x, y, ang, c.get("p_hp"), PLAY.keys_str(rec["keys"]),
                                                  steer.why))
        if f - st["lastlog"] >= 200:
            st["lastlog"] = f
            x, y, _a = PLAY.pose_of(c)
            log("  f%d (w%d): (%d, %d) hp %s ar %s, leg %d/%d -> %s, kills %s, %.0f s" % (
                f, f - pl.mf, x, y, c.get("p_hp"), c.get("p_ar"), steer.li, len(steer.legs),
                steer.leg["to"] if steer.leg else "-", c.get("st_kill"), time.time() - st["t"]))
        return None
    frames = pl.mf + 1 + budget
    r = (pl.run_model if model_only else pl.run)([], frames, decide=steer.decide, on_frame=on_frame)
    return {"r": r, "steer": steer, "st": st}


SEARCH_BACK = (600, 300, 1200)   # frames before a death the seed changes at (each tried)
SEARCH_SEEDS = (1, 2, 3, 4)
_JOB = {}


def _search_job(args):
    """one search attempt in a worker process (its own model player, built once): -> the attempt's summary"""
    mapname, skill, route, sched, budget = args
    if "pl" not in _JOB:
        import play as PLAY
        import level_route as LR
        _JOB.update(PLAY=PLAY, pl=_model_player(PLAY, skill), lv=LR.Level(mapname, route.get("wad"), skill))
        _JOB["pl"].workers = 0
    res = play(_JOB["PLAY"], _JOB["pl"], route, _JOB["lv"], sched, budget, True, quiet=True)
    return _summ(sched, res)


def _summ(sched, res):
    st = res["st"]
    return {"sched": sched, "done": st["done"], "dead": st["dead"], "legs": len(res["steer"].events),
            "frames": res["r"]["frames"], "leg": res["steer"].leg["to"] if res["steer"].leg else "-"}


def _score(s):
    """further is better (legs done, then frames lived); among plays that PASS, the shortest"""
    if s["done"] is not None:
        return (True, 0, -s["frames"])
    return (False, s["legs"], s["frames"])


def search(PLAY, pl, route, lv, seed, budget, rounds, seeds=SEARCH_SEEDS, workers: int = 6):
    """--search: from `seed`, while the play dies (or stalls), re-play with the seed changed SEARCH_BACK frames before
    the end (each of its distances), trying SEARCH_SEEDS (shifted by 10 a round), and keep the attempt that went
    furthest (legs done, then frames lived). Each attempt is a whole play from boot, run `workers` at a time in
    processes of their own -- the steering is deterministic, so a schedule found here is the play the gate makes"""
    import multiprocessing as MP
    sched = [(0, seed)] if isinstance(seed, int) else list(seed)
    best = _summ(sched, play(PLAY, pl, route, lv, sched, budget, True, quiet=True))
    print("  search: %s -> %s %s" % (seed_text(sched), _score(best), best["dead"]), flush=True)
    pool = MP.get_context("spawn").Pool(workers) if workers > 1 else None
    mapname = route["map"]
    try:
        for rnd in range(rounds):
            if best["done"] is not None:
                break
            end = best["frames"]
            cands = [[(0, sd + 10 * rnd)] for sd in seeds] if rnd == 0 else []    # whole plays on one seed first
            for back in SEARCH_BACK:
                for sd in seeds:
                    cut = max(0, end - back)
                    head = [fs for fs in sched if fs[0] < cut]
                    if cut < 100 or (head and head[-1][1] == sd + 10 * rnd):
                        continue                     # a whole-seed play (tried above), or no change at the cut
                    cand = head + [(cut, sd + 10 * rnd)]
                    if cand not in cands and cand != sched:
                        cands.append(cand)
            jobs = [(mapname, pl.skill, route, cand, budget) for cand in cands]
            outs = pool.imap_unordered(_search_job, jobs) if pool else (_search_job(j) for j in jobs)
            found = None
            for o in outs:
                print("  search round %d: %s -> %s %s on leg -> %s" % (rnd, seed_text(o["sched"]), _score(o),
                                                                      o["dead"] or "", o["leg"]), flush=True)
                if _score(o) > _score(best) and (found is None or _score(o) > _score(found)):
                    found = o
                if o["done"] is not None:            # a PASS: taken at once (the round's other plays dropped)
                    break
            if found is None:                        # the next round tries the next seeds (sd + 10 * round)
                print("  search: no seed got further than %s this round" % (_score(best),), flush=True)
                continue
            sched, best = found["sched"], found
            if best["done"] is not None and pool is not None:
                pool.terminate()                     # the round's unfinished plays
                pool = None
    finally:
        if pool is not None:
            pool.terminate()
    print("  search: the schedule %s (%s)" % (seed_text(sched), "PASS" if best["done"] is not None else
                                                "still failing"), flush=True)
    return sched


def _model_player(PLAY, skill):
    """a Player for --model-only: the oracle without the binary"""
    pl = PLAY.Player.__new__(PLAY.Player)
    import onewalk
    import p2a_gate as G
    import probe as P
    from doomfj import gamedata as gd
    from doomfj.things import drawable_things
    from m2_std_gate import boot_pick, menu_exit_events
    pl.P, pl.G, pl.skill, pl.sk, pl.check = P, G, skill, gd.SKILL_NAMES[skill], True
    pl.orc = P.Oracle()
    pl.mapname = pl.orc.mapname
    pl.dsim = onewalk.DoorSim()
    pl.card_di = ([di for di, t in enumerate(drawable_things(pl.orc.rm, pl.orc.mw.things(pl.mapname), pl.orc.art)[0])
                   if t.type == G.CARD_TYPE] or [-1])[0]
    pl.mf = boot_pick(pl.sk)[-1][0]
    pl.menu_events = list(menu_exit_events(pl.sk))
    pl.oracle_keys = pl.binary_pic = None
    pl.run = pl.run_model
    return pl


def controls(PLAY, pl) -> bool:
    """R9: (1) the oracle's keys mutated on world frame CONTROL_AT -- the state must part there; (2) one pixel of the
    binary's picture flipped on that frame -- the picture must part there. The key log: forward and a turn"""
    log = [frozenset({"forward"}) if i % 7 else frozenset({"forward", "turn_left"}) for i in range(CONTROL_FRAMES)]
    at = pl.mf + 1 + CONTROL_AT
    ok = True
    for name in ("keys", "pixel"):
        pl.oracle_keys = pl.binary_pic = None
        if name == "keys":
            pl.oracle_keys = lambda f, kd: ({**kd, "turn_right": True} if f == at else kd)
        else:
            pl.binary_pic = lambda f, pic: (bytes([pic[0] ^ 1]) + pic[1:] if f == at else pic)
        r = pl.run(log, pl.mf + 1 + CONTROL_FRAMES)
        mm = r["mismatch"]
        good = mm is not None and mm["frame"] == at and (mm["ncells"] > 0 if name == "keys" else mm["px"] == 1)
        ok &= good
        print("  CONTROL %-5s the %s on frame %d: %s" % (
            name, "oracle's keys mutated" if name == "keys" else "binary's picture changed (1 px)", at,
            "parted there (%s) -- the check sees it" % ("%d cells: %s" % (mm["ncells"], sorted(mm["cells"])[:4])
                                                       if name == "keys" else "%d px" % mm["px"])
            if good else "!! NOT REJECTED as it must be: %s" % mm), flush=True)
    pl.oracle_keys = pl.binary_pic = None
    # and the same log unmutated: exact (the controls part because of their mutation, not of the log)
    r = pl.run(log, pl.mf + 1 + CONTROL_FRAMES)
    clean = r["mismatch"] is None and r["frames"] == pl.mf + 1 + CONTROL_FRAMES
    print("  CONTROL clean the same %d frames unmutated: %s" % (r["frames"], "exact" if clean else
                                                                 "!! parted: %s" % r["mismatch"]), flush=True)
    return ok and clean


def dump_mismatch(pl, r):
    """the evidence of a parting: binary | oracle | diff, and the record"""
    try:
        from PIL import Image
        rec = r["last"]
        W, H = pl.orc.rm.cfg.W, pl.orc.rm.cfg.H
        f, got, want = r["mismatch_pics"] if r.get("mismatch_pics") else (rec["f"], rec["pic"], rec.get("oracle_pic"))
        if want is None or len(got) != len(want):
            return
        pal = list(pl.orc.art.playpal(0))
        sheet = Image.new("RGB", (W * 3, H))
        for col, px in enumerate((got, want, bytes(255 if x != y else 0 for x, y in zip(got, want)))):
            im = Image.new("RGB", (W, H))
            im.putdata([(v, v, v) if col == 2 else tuple(pal[v]) for v in px])
            sheet.paste(im, (W * col, 0))
        out = ROOT / "scratchpad" / "gp" / ("playthrough_mismatch_f%d.png" % f)
        sheet.resize((W * 6, H * 2), Image.NEAREST).save(out)
        print("  wrote %s (binary | oracle | diff)" % out)
    except Exception as e:                       # noqa: BLE001 -- a dump failing must not hide the verdict
        print("  (mismatch dump failed: %s)" % e)


if __name__ == "__main__":
    sys.exit(main())
