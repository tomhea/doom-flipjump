"""A gameplay video from the REAL binary (the owner, 2026-10-14: "a 100s that gets into action and travels many rooms").

PLAN (the model): a closed-loop player driven through gamespeed's GameSim -- the whole game at the game tier's modes,
the model gamespeed_trail.py proves equal to the binary frame by frame -- one frame at a time:
  * ROUTE: gamespeed's ten farthest-point destinations (the whole reachable level, doors open), visited nearest
    first from the spawn, each walked along a BFS path thinned to waypoints, forward held, turning on the move (the
    tours' `_steer` rule, per frame); `use` inside a door's use box;
  * FIGHT: a live monster within FIGHT_RANGE in the game's own line of sight (World.los_points) is faced and shot
    once the heading is within one turn step; a target that takes too long is let go for a while;
  * the best weapon owned with ammo (chaingun, shotgun, pistol), switched to by its number key;
  * a dead player restarts (use).
PLAY: the planned keys -> the binary (`m2_std_gate.run_fj`, the composition `fj --run ... --io pc` builds), menu boot
pick included; with --check B.fjm the same keys go to a second binary and every frame must be byte-identical.
VIDEO: the presented world frames, 4x nearest, at 17.5 fps (the monsters run 2 tics a frame: DOOM's 35 Hz), MP4.
PYTHONPATH="src;scratchpad;scratchpad/12m;scratchpad/gp" python scratchpad/gp/p12_video.py A.fjm OUT.mp4
    [--frames 1750] [--check B.fjm] [--keys KEYS.json (reuse a plan)]"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path[:0] = ["scratchpad", "scratchpad/12m", "scratchpad/gp", "src"]
import gamespeed as GS  # noqa: E402
import m2_std_gate as gate  # noqa: E402

FIGHT_RANGE = 900            # a monster already chasing the player
NEAR_RANGE = 550             # any other live monster
HEAL_HP = 50                 # below it the nearest health item is the destination
LOW_HP = 40                  # below it only monsters chasing the player are fought
NO_DAMAGE = 30               # frames without a hit before a target is let go
GIVE_UP = 70                 # frames on one target before it is let go
IGNORE = 120                 # ... for this many frames
FPS = 12.0                   # ~the binary's own speed on this machine (83 ms a frame)


def keyless_plan(world, n_targets=12):
    """gamespeed._tour_plan with only the doors a player opens WITHOUT a key open (door_kind plain / blaze): the
    blue doors stay shut, so no route runs through them and no destination lies behind them"""
    from doomfj.doors import door_states, heights_for_states, in_use_box_fixed, use_boxes_xy
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import _signed, build_scene
    from doomfj.wad import WadFile
    rm, _scene, sp = GS._oracle(GS.DEFAULT_WAD, GS.DEFAULT_MAP)
    mw = WadFile.from_path(str(GS.ROOT / GS.DEFAULT_WAD))
    M = GS.DEFAULT_MAP
    secs, lds, sds = mw.sectors(M), mw.linedefs(M), mw.sidedefs(M)
    tbl = door_states(secs, lds, sds)
    boxes = use_boxes_xy(secs, lds, sds, bake_bsp(mw, M).vertexes)
    tbl = {si: v for si, v in tbl.items() if si in boxes and world.door_kind.get(si) in ("plain", "blaze")}
    scene = build_scene(mw, mw, M, heights_for_states(secs, lds, sds, {si: len(v) - 1 for si, v in tbl.items()}))
    sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    pts, _cells = GS._reachable(rm, scene, sx, sy)
    return scene, GS._spread_targets(pts, sx, sy, n_targets), [boxes[si] for si in sorted(tbl)], in_use_box_fixed


class SkillSim(GS.GameSim):
    """gamespeed.GameSim at a chosen skill (its reset, with the skill the boot pick will choose)"""
    skill = None

    def reset(self):
        from doomfj.reference_model import SimState
        from doomfj.sight import SeenHook
        from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
        from doomfj.world import World
        self.w = World(self.mw, self.mapname, skill=self.skill, monsters=MONSTER_MODE, player=PLAYER_MODE)
        self.w.set_sight_rule("seen", SeenHook(self.w))
        self.ever = {si: 0 for si in getattr(self, "order", ())}
        ws = self.w.ws
        return SimState(ws.px, ws.py, ws.pangle, self.mapname)


def plan(n_frames, skill, log=print, order=None):
    from doomfj.reference_model import ANGLE_TURN, FORWARD_MOVE, _signed
    SkillSim.skill = skill
    sim = SkillSim()
    st = sim.reset()
    w = sim.w
    rm, _scene, _sp = GS._oracle(GS.DEFAULT_WAD, GS.DEFAULT_MAP)
    open_scene, targets, boxes, in_box = keyless_plan(w)
    # nearest-first order from the spawn
    x0, y0 = _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16
    left = list(targets)
    cx, cy = x0, y0
    if order is not None:
        left = []
    else:
        order = []
    while left:
        k = min(range(len(left)), key=lambda i: (left[i][0] - cx) ** 2 + (left[i][1] - cy) ** 2)
        cx, cy = left.pop(k)
        order.append((cx, cy))
    log("route: %s" % order)
    radius = (FORWARD_MOVE >> 16) / (ANGLE_TURN * 2 * math.pi / (1 << 32))
    keys, di, wps, wi, stuck = [], 0, [], 0, 0
    tgt, tgt_frames, tgt_hp, tgt_hit, ignored, heal, heal_retry = None, 0, 0, 0, {}, None, 0
    kills = rooms = 0
    t0 = time.time()
    for f in range(n_frames):
        ws = w.ws
        px, py = _signed(ws.px, 32) >> 16, _signed(ws.py, 32) >> 16
        kd = {}

        def face(tx, ty):
            want = int(math.atan2(ty - py, tx - px) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
            err = (want - ws.pangle) & 0xFFFFFFFF
            return err - (1 << 32) if err > (1 << 31) else err
        if ws.p_dead:
            kd["use"] = f % 4 == 0                          # restart
            di, wps, tgt, heal = 0, [], None, None
        else:
            # the weapon: the best owned with ammo
            want_w = 1
            if ws.p_owned[2] and ws.p_ammo[1] > 0:
                want_w = 2
            if ws.p_owned[3] and ws.p_ammo[0] > 0:
                want_w = 3
            if ws.p_ready != want_w and ws.p_pending in (10, ws.p_ready) and f % 3 == 0:
                kd["w%d" % (want_w + 1)] = True
            # the fight
            live = [m for m in range(len(ws.mon_health))
                    if ws.mon_active[m] and ws.mon_health[m] > 0 and ignored.get(m, -1) < f
                    and (ws.mon_x[m] - px) ** 2 + (ws.mon_y[m] - py) ** 2
                    <= (FIGHT_RANGE if ws.mon_target[m] else NEAR_RANGE if ws.p_health >= LOW_HP else 0) ** 2]
            if tgt is not None and (tgt not in live or not w.los_points((ws.mon_x[tgt] << 16, ws.mon_y[tgt] << 16),
                                                                      (ws.px, ws.py))):
                if ws.mon_health[tgt] <= 0:
                    kills += 1
                tgt = None
            if tgt is None:
                vis = sorted((m for m in live if w.los_points((ws.mon_x[m] << 16, ws.mon_y[m] << 16), (ws.px, ws.py))),
                             key=lambda m: (ws.mon_x[m] - px) ** 2 + (ws.mon_y[m] - py) ** 2)
                if vis:
                    tgt, tgt_frames, tgt_hp, tgt_hit = vis[0], 0, ws.mon_health[vis[0]], f
            if tgt is not None:
                tgt_frames += 1
                if ws.mon_health[tgt] < tgt_hp:
                    tgt_hp, tgt_hit = ws.mon_health[tgt], f
                if tgt_frames > GIVE_UP or f - tgt_hit > NO_DAMAGE:
                    ignored[tgt] = f + IGNORE
                    tgt = None
            if tgt is not None:
                err = face(ws.mon_x[tgt], ws.mon_y[tgt])
                if err > ANGLE_TURN // 2:
                    kd["turn_left"] = True
                elif err < -(ANGLE_TURN // 2):
                    kd["turn_right"] = True
                if abs(err) <= ANGLE_TURN:
                    kd["fire"] = True
                if (f // 20) % 2:                           # sidestep while fighting
                    kd["strafe_left" if (f // 40) % 2 else "strafe_right"] = True
            else:
                # low health: detour to the nearest untaken stimpack / medikit, then back to the route
                if ws.p_health < HEAL_HP and heal is None and f >= heal_retry:
                    heal_retry = f + 40                     # a failed search is not repeated every frame
                    cands = [(t.x, t.y) for k2, t in enumerate(w.pickup_things)
                             if t.type in (2011, 2012) and not ws.pickup_taken[k2]
                             and (t.x - px) ** 2 + (t.y - py) ** 2 <= 1400 ** 2]
                    for c in sorted(cands, key=lambda c: (c[0] - px) ** 2 + (c[1] - py) ** 2):
                        hw = GS._waypoints(rm, open_scene, st, c)
                        if hw:
                            heal, wps, wi = c, hw, 0
                            log("  frame %d: health %d -> detour to %s" % (f, ws.p_health, c))
                            break
                if heal is not None and ws.p_health >= HEAL_HP:
                    heal, wps = None, []
                # the route
                while di < len(order) and not wps:
                    wps = GS._waypoints(rm, open_scene, st, order[di])
                    wi = 0
                    if not wps:
                        di += 1
                if di >= len(order):
                    di, wps = 0, []                         # tour again
                if wps:
                    while wi < len(wps) and (px - wps[wi][0]) ** 2 + (py - wps[wi][1]) ** 2 <= (gate.NAV_CELL * 2) ** 2:
                        wi += 1
                    if wi >= len(wps) and (px - wps[-1][0]) ** 2 + (py - wps[-1][1]) ** 2 > (gate.NAV_CELL * 3) ** 2:
                        wps = []                            # skipped past the end: re-plan from here
                    elif wi >= len(wps) and heal is not None:
                        heal, wps = None, []                # at the item (taken, or not there): resume
                    elif wi >= len(wps):
                        rooms += 1
                        log("  frame %d: reached destination %d %s" % (f, di, order[di]))
                        di, wps = di + 1, []
                    else:
                        tx, ty = wps[wi]
                        err = face(tx, ty)
                        kd["forward"] = True
                        if err > ANGLE_TURN // 2:
                            kd["turn_left"] = True
                        elif err < -(ANGLE_TURN // 2):
                            kd["turn_right"] = True
                        if ("turn_left" in kd or "turn_right" in kd) and math.hypot(tx - px, ty - py) < \
                                2 * radius * abs(math.sin(err * 2 * math.pi / (1 << 32))):
                            del kd["forward"]
            if any(in_box(b, ws.px, ws.py) for b in boxes):
                kd["use"] = True
        kd = {k: v for k, v in kd.items() if v}
        nst = sim.step(st, kd)
        if not ws.p_dead and tgt is None and "forward" in kd:
            if abs(nst.x - st.x) + abs(nst.y - st.y) < GS.UNIT:
                stuck += 1
                if stuck >= 6:                              # re-plan from here
                    wi += 1
                    if stuck >= 18:
                        wps, stuck = [], 0
            else:
                stuck = 0
        st = nst
        keys.append(kd)
        if f % 100 == 99:
            log("  frame %d (%.0fs): at (%d, %d) hp %d, destination %d, target %s, kills %d" % (
                f + 1, time.time() - t0, _signed(w.ws.px, 32) >> 16, _signed(w.ws.py, 32) >> 16, w.ws.p_health,
                di, tgt, w.ws.p_killcount))
    log("plan: %d frames, kills %d, destinations reached %d, deaths %s" % (n_frames, w.ws.p_killcount, rooms,
                                                                          getattr(w.ws, "p_dead", "?")))
    return keys


class PalRec(gate.Recording):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pals = []

    def _present(self):
        super()._present()
        self.pals.append(bytes(b for rgb in self.palette for b in rgb))


def play(fjm, keys, skill):
    full = [{} for _ in range(gate.MENU_FRAMES)] + keys
    rec = {}

    def factory():
        rec["s"] = PalRec()
        return rec["s"]
    frames, ops = gate.run_fj(fjm, gate.to_events(full) + gate.menu_exit_events(skill), len(full),
                              screen_factory=factory)
    return frames, rec["s"].pals, ops


def encode(out, frames, pals, W, H, scale=4):
    import cv2
    import numpy as np
    vw = None
    for fourcc in ("avc1", "mp4v"):
        vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*fourcc), FPS, (W * scale, H * scale))
        if vw.isOpened():
            break
    assert vw is not None and vw.isOpened(), "no MP4 encoder"
    for fr, pal in zip(frames, pals):
        p = np.frombuffer(pal, dtype=np.uint8).reshape(-1, 3)
        img = p[np.frombuffer(fr, dtype=np.uint8)].reshape(H, W, 3)[:, :, ::-1]
        vw.write(np.ascontiguousarray(np.repeat(np.repeat(img, scale, 0), scale, 1)))
    vw.release()
    return fourcc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fjm")
    ap.add_argument("out")
    ap.add_argument("--frames", type=int, default=1750)
    ap.add_argument("--check", default=None)
    ap.add_argument("--keys", default=None)
    ap.add_argument("--skill", default="hard", choices=("easy", "medium", "hard"))
    args = ap.parse_args()
    from doomfj import gamedata as gd
    from doomfj.config import Config
    skill = {"easy": gd.SK_EASY, "medium": gd.SK_MEDIUM, "hard": gd.SK_HARD}[args.skill]
    W, H = Config().W, Config().H
    kpath = Path(args.out).with_suffix(".keys.json")
    if args.keys:
        keys = json.loads(Path(args.keys).read_text(encoding="ascii"))
    else:
        keys = plan(args.frames, skill)
        kpath.write_text(json.dumps(keys), encoding="ascii")
        print("keys -> %s" % kpath, flush=True)
    t = time.time()
    frames, pals, ops = play(args.fjm, keys, skill)
    print("%s: %d frames presented, %s ops (%s per frame), %.0fs" % (
        args.fjm, len(frames), format(ops, ","), format(ops // len(frames), ","), time.time() - t), flush=True)
    world = frames[gate.MENU_FRAMES:], pals[gate.MENU_FRAMES:]
    if args.check:
        fb, pb, ob = play(args.check, keys, skill)
        diff = [k for k in range(min(len(frames), len(fb))) if frames[k] != fb[k] or pals[k] != pb[k]]
        print("%s: %s ops (%+.2f%%); frames %s" % (
            args.check, format(ob, ","), 100.0 * (ob - ops) / ops,
            "IDENTICAL, all %d (pixels + palette)" % len(frames) if not diff and len(fb) == len(frames)
            else "DIFFER from frame %s (%d)" % (diff[:1], len(diff))), flush=True)
    fourcc = encode(args.out, *world, W, H)
    print("video -> %s (%d frames, %.1f s at %.1f fps, %s, %dx%d)" % (
        args.out, len(world[0]), len(world[0]) / FPS, FPS, fourcc, W * 4, H * 4), flush=True)


if __name__ == "__main__":
    main()
