"""A gameplay video driven by the BINARY ITSELF: a closed-loop player that reads the running binary's state at every
frame start through the probe (its view pose, health, death flag, every monster's health / activity / position) and
decides that frame's keys from it, delivered as key events on the frame's first poll -- so nothing depends on the
model staying in step with the binary (it does not, in combat: p12_diverge.py, game frame 69 of p12_video's plan).
The model is used only for GEOMETRY: p12_video.keyless_plan's walkable route and World.los_points.
PYTHONPATH="src;scratchpad;scratchpad/12m;scratchpad/gp" python scratchpad/gp/p12_video_live.py FJM LABELS OUT.mp4
    [--frames 1750] [--fps 17.5]"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path[:0] = ["scratchpad", "scratchpad/12m", "scratchpad/gp", "src"]
import b0_scenarios as B  # noqa: E402
import gamespeed as GS  # noqa: E402
import m2_std_gate as gate  # noqa: E402
import p12_video as V  # noqa: E402
import probe as P  # noqa: E402
from flipjump.interpreter.io_devices import KeyboardIO as KIO  # noqa: E402
from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent  # noqa: E402

LIVE = {}


class LiveSource(KIO.ScriptedKeyEventSource):
    """the scripted source, registered so the frame-start hook can append the frame's events"""

    def __init__(self, events):
        super().__init__(events)
        LIVE["src"] = self


def signed(v):
    v &= 0xFFFFFFFF                     # the probe may already hand back a signed value
    return v - (1 << 32) if v & 0x80000000 else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fjm")
    ap.add_argument("labels")
    ap.add_argument("out")
    ap.add_argument("--frames", type=int, default=1750)
    ap.add_argument("--fps", type=float, default=17.5)
    ap.add_argument("--skill", default="medium", choices=("easy", "medium", "hard"))
    args = ap.parse_args()
    from doomfj.config import Config
    from doomfj.reference_model import ANGLE_TURN, FORWARD_MOVE, SimState
    from doomfj.sight import SeenHook
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import STANDALONE_POLLS
    W, H = Config().W, Config().H
    sim = GS.GameSim()
    world = sim.w
    views = SeenHook(world).views                       # monster slot -> runtime row (views.rt)
    rm, _scene, _sp = GS._oracle(GS.DEFAULT_WAD, GS.DEFAULT_MAP)
    open_scene, targets, boxes, in_box = V.keyless_plan(world)
    sx, sy = -416, 256
    order, left, cx, cy = [], list(targets), sx, sy
    while left:
        k = min(range(len(left)), key=lambda i: (left[i][0] - cx) ** 2 + (left[i][1] - cy) ** 2)
        cx, cy = left.pop(k)
        order.append((cx, cy))
    print("route:", order, flush=True)
    radius = (FORWARD_MOVE >> 16) / (ANGLE_TURN * 2 * math.pi / (1 << 32))
    art = WadFile.from_path("assets/freedoom1.wad")
    pal_by_sha = {P.palette_sha(art, k): bytes(b for rgb in art.playpal(k) for b in rgb) for k in range(14)}
    S = dict(di=0, wps=[], wi=0, stuck=0, tgt=None, tf=0, thp=0, thit=0, ignored={}, held=set(), last=None,
             dead_since=None, reached=0, log=[])
    cells = ["viewx", "viewy", "viewangle", "p_hp", "p_dead", "mon_health", "mon_active", "mon_target", "thpos_rt"]
    mf = gate.MENU_FRAMES

    def decide(f, c):
        px16, py16, ang = signed(c["viewx"]), signed(c["viewy"]), c["viewangle"] & 0xFFFFFFFF
        px, py = px16 >> 16, py16 >> 16
        mons = []
        for m, row in enumerate(views.rt):
            v = c["thpos_rt"][row]
            mons.append((signed(v & 0xFFFFFFFF) >> 16, signed((v >> 32) & 0xFFFFFFFF) >> 16))
        kd = {}

        def face(tx, ty):
            want = int(math.atan2(ty - py, tx - px) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
            e = (want - ang) & 0xFFFFFFFF
            return e - (1 << 32) if e > (1 << 31) else e
        if c["p_dead"]:
            S["dead_since"] = f if S["dead_since"] is None else S["dead_since"]
            if f - S["dead_since"] > 40 and f % 4 == 0:
                kd["use"] = True                            # restart after the death view has played
            S.update(di=0, wps=[], tgt=None)
            return kd
        S["dead_since"] = None
        if f % 60 == 30:
            kd["w3"] = True                                 # the shotgun, once owned
        hp = c["p_hp"]
        live = [m for m in range(len(mons))
                if c["mon_active"][m] and signed(c["mon_health"][m]) > 0 and S["ignored"].get(m, -1) < f
                and (mons[m][0] - px) ** 2 + (mons[m][1] - py) ** 2
                <= (V.FIGHT_RANGE if c["mon_target"][m] else V.NEAR_RANGE if hp >= V.LOW_HP else 0) ** 2]
        los = lambda m: world.los_points((mons[m][0] << 16, mons[m][1] << 16), (px16, py16))  # noqa: E731
        t = S["tgt"]
        if t is not None and (t not in live or not los(t)):
            S["tgt"] = t = None
        if t is None:
            vis = sorted((m for m in live if los(m)), key=lambda m: (mons[m][0] - px) ** 2 + (mons[m][1] - py) ** 2)
            if vis:
                t = vis[0]
                S.update(tgt=t, tf=0, thp=signed(c["mon_health"][t]), thit=f)
        if t is not None:
            S["tf"] += 1
            h = signed(c["mon_health"][t])
            if h < S["thp"]:
                S.update(thp=h, thit=f)
            if S["tf"] > V.GIVE_UP or f - S["thit"] > V.NO_DAMAGE:
                S["ignored"][t] = f + V.IGNORE
                S["tgt"] = t = None
        if t is not None:
            e = face(*mons[t])
            if e > ANGLE_TURN // 2:
                kd["turn_left"] = True
            elif e < -(ANGLE_TURN // 2):
                kd["turn_right"] = True
            if abs(e) <= ANGLE_TURN:
                kd["fire"] = True
            if (f // 20) % 2:
                kd["strafe_left" if (f // 40) % 2 else "strafe_right"] = True
        else:
            st = SimState(c["viewx"] & 0xFFFFFFFF, c["viewy"] & 0xFFFFFFFF, ang, GS.DEFAULT_MAP)
            while S["di"] < len(order) and not S["wps"]:
                S["wps"] = GS._waypoints(rm, open_scene, st, order[S["di"]])
                S["wi"] = 0
                if not S["wps"]:
                    S["di"] += 1
            if S["di"] >= len(order):
                S["di"], S["wps"] = 0, []
            wps = S["wps"]
            if wps:
                while S["wi"] < len(wps) and (px - wps[S["wi"]][0]) ** 2 + (py - wps[S["wi"]][1]) ** 2 <= (gate.NAV_CELL * 2) ** 2:
                    S["wi"] += 1
                if S["wi"] >= len(wps):
                    if (px - wps[-1][0]) ** 2 + (py - wps[-1][1]) ** 2 <= (gate.NAV_CELL * 3) ** 2:
                        S["reached"] += 1
                        print("  frame %d: reached %s" % (f, order[S["di"]]), flush=True)
                        S["di"] += 1
                    S["wps"] = []
                else:
                    tx, ty = wps[S["wi"]]
                    e = face(tx, ty)
                    kd["forward"] = True
                    if e > ANGLE_TURN // 2:
                        kd["turn_left"] = True
                    elif e < -(ANGLE_TURN // 2):
                        kd["turn_right"] = True
                    if ("turn_left" in kd or "turn_right" in kd) and math.hypot(tx - px, ty - py) < \
                            2 * radius * abs(math.sin(e * 2 * math.pi / (1 << 32))):
                        del kd["forward"]
            # stuck: the binary did not move although forward was held
            if S["last"] is not None and "forward" in S["held"] and abs(px16 - S["last"][0]) + abs(py16 - S["last"][1]) < GS.UNIT:
                S["stuck"] += 1
                if S["stuck"] >= 6:
                    S["wi"] += 1
                if S["stuck"] >= 18:
                    S["wps"], S["stuck"] = [], 0
            else:
                S["stuck"] = 0
        if any(in_box(b, px16, py16) for b in boxes):
            kd["use"] = True
        S["last"] = (px16, py16)
        return kd

    with P.binary_lock("p12-video-live"):
        orc = P.Oracle()
        specs = {k: c for k, c in B.setup_cell_specs(orc).items() if k in cells}
        table = P.LabelTable.load(Path(args.labels), {c.label for c in specs.values()})
        gb = P.GameBinary(Path(args.fjm))
        p = P.Probe(specs, table, gb.width)
        t0 = time.time()

        def start(pr, f):
            if f < mf:
                return
            c = pr.read_cells(cells)
            kd = {k for k, v in decide(f - mf, c).items() if v}
            src = LIVE["src"]
            for name in sorted(S["held"] ^ kd):
                src.events.append(KeyEvent(f * STANDALONE_POLLS, name in kd, gate.CODE[name]))
            S["held"] = kd
            if (f - mf) % 100 == 99:
                print("  frame %d (%.0fs): at (%d, %d) hp %d target %s, route %d" % (
                    f - mf + 1, time.time() - t0, signed(c["viewx"]) >> 16, signed(c["viewy"]) >> 16, c["p_hp"],
                    S["tgt"], S["di"]), flush=True)
        p.on_frame_start(start)
        KIO.ScriptedKeyEventSource = LiveSource
        try:
            from doomfj import gamedata as gd
            skill = {"easy": gd.SK_EASY, "medium": gd.SK_MEDIUM, "hard": gd.SK_HARD}[args.skill]
            r = gb.run(mf + args.frames, gate.menu_exit_events(skill), p)
        finally:
            KIO.ScriptedKeyEventSource = LiveSource.__mro__[1]
    evs = [(e.tic, bool(e.is_down), e.keycode) for e in LIVE["src"].events]
    Path(args.out).with_suffix(".events.json").write_text(json.dumps(evs), encoding="ascii")
    frames, shas = r.frames[mf:], r.palettes[mf:]
    pals = [pal_by_sha[s] for s in shas]
    print("binary: %d game frames, %s ops; destinations reached %d" % (len(frames), format(r.ops, ","), S["reached"]),
          flush=True)
    V.FPS = args.fps
    fourcc = V.encode(args.out, frames, pals, W, H)
    Path(args.out).with_suffix(".frames.json").write_text(json.dumps({"n": len(frames)}), encoding="ascii")
    print("video -> %s (%d frames, %.1f s at %.1f fps, %s)" % (args.out, len(frames), len(frames) / args.fps,
                                                              args.fps, fourcc), flush=True)


if __name__ == "__main__":
    main()
