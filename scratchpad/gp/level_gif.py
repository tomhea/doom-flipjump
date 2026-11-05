"""A GIF of a level's playthrough: the bot's start-to-exit play (playthrough_gate's route, skill and seed defaults)
stepped on the ORACLE, and its busiest window of world frames drawn. The playthrough gate holds the shipped binary
byte-, palette- and state-exact to this oracle on every frame of that very play (docs/ship-gate.md 14), so these
frames ARE the binary's frames.

usage (repo root): DOOMFJ_MAP=E1M3 python scratchpad/gp/level_gif.py --out docs/media/levels/e1m3.gif
    [--frames 100] [--scale 2] [--ms 70] [--start W]   (W: the first world frame; default the busiest window)

Two passes over the same deterministic play: the first steps the model with no pictures and scores every window of
--frames world frames (kills x4 + hits taken x2 + frames firing), the second steps it again and renders that window.
It prints the play's LEVEL COMPLETE world frame: compare it with the gate's record (playthrough_gate.DEFAULT_SEED).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "scripts", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))
if __name__ == "__main__":
    from doomfj.mapprofile import take_map_arg
    take_map_arg(keep=True)


def _play(on_frame):
    """the gate's play, model only: -> (Player, the run, the world frame of LEVEL COMPLETE or None)"""
    import level_route as LR
    import play as PLAY
    import playthrough_gate as PG
    from doomfj.mapprofile import ACTIVE
    from doomfj.menu import LEVEL_DONE_SCREENS
    mapname = ACTIVE.upper()
    skill = PG.DEFAULT_SKILL.get(mapname, "easy")
    route = LR.plan(mapname, skill)
    pl = PG._model_player(PLAY, skill)
    lv = LR.Level(mapname, route.get("wad"), skill)
    steer = PLAY.Steer(route, lv=lv, log=lambda s: None, seed=PG.DEFAULT_SEED.get((mapname, skill), 0))
    steer.rt = pl.monster_rows()
    st = {"done": None, "dead": None, "hp": None}

    def frame(rec):                                    # playthrough_gate.play's on_frame, what steers included
        c, f = rec["cells"], rec["f"]
        if f < pl.mf:
            return None
        if st["hp"] is not None and c.get("p_hp") is not None and c["p_hp"] < st["hp"]:
            steer.hurt_f = f
        st["hp"] = c.get("p_hp")
        if c.get("p_dead"):
            st["dead"] = f - pl.mf
            return "stop"
        if c.get("mode") == 1 and c.get("lvdone") == 1 and c.get("menu_scr") in LEVEL_DONE_SCREENS:
            st["done"] = f - pl.mf
            return "stop"
        return on_frame(pl, rec)
    r = pl.run_model([], pl.mf + 1 + 6000, decide=steer.decide, on_frame=frame)
    if st["dead"] is not None:
        print("the model play DIED at world %d" % st["dead"])
    return pl, r, st["done"], mapname, skill


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=100)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--ms", type=int, default=70)
    ap.add_argument("--start", type=int, default=None)
    a = ap.parse_args(argv)
    from PIL import Image
    t0 = time.time()

    score = []                                         # per world frame

    def tally(pl, rec):
        if rec["f"] < pl.mf:
            return None
        c, prev = rec["cells"], tally.prev
        s = 0
        if prev is not None:
            s += 4 * max(0, (c.get("st_kill") or 0) - (prev.get("st_kill") or 0))
            s += 2 * ((c.get("p_hp") or 0) < (prev.get("p_hp") or 0))
        s += "fire" in rec["keys"]
        score.append(s)
        tally.prev = c
        return None
    tally.prev = None
    if a.start is None:
        _pl, _r, done, mapname, skill = _play(tally)
        n = a.frames
        if done is None or len(score) < n:
            print("LEVEL GIF FAIL -- the model play did not reach LEVEL COMPLETE (%s frames)" % len(score))
            return 1
        sums = [sum(score[i:i + n]) for i in range(0, len(score) - n + 1)]
        start = max(range(len(sums)), key=lambda i: (sums[i], -i))
        print("%s at %s: LEVEL COMPLETE at world %d; busiest window of %d frames at world %d (score %d); %.0f s"
              % (mapname, skill, done, n, start, sums[start], time.time() - t0), flush=True)
    else:
        start = a.start
    end = start + a.frames
    shots = []

    def grab(pl, rec):
        w = rec["f"] - pl.mf
        if w < start:
            return None
        if w >= end:
            return "stop"
        G, fr = pl.G, rec["fr"]
        pic = (G.picture(pl.orc, pl.dsim, fr, pl.card_di) if fr["drawn"] == "world" else
               G.screen(pl.orc, fr["drawn"][1], fr["drawn"][2], fr["live"], fr["stats"]))
        shots.append((bytes(pic), fr["pal"]))
        return None
    pl, _r, _done, mapname, skill = _play(grab)
    W, H = 160, 100
    pals, ims = {}, []
    for pic, pal in shots:
        if pal not in pals:
            pals[pal] = [b for rgb in pl.orc.art.playpal(pal) for b in rgb]
        im = Image.frombytes("P", (W, H), pic)
        im.putpalette(pals[pal])
        ims.append(im.convert("RGB").resize((W * a.scale, H * a.scale), Image.NEAREST))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=a.ms, loop=0, optimize=True)
    print("LEVEL GIF %s -- %s world frames %d..%d at %s, %d frames, %d KB, %.0f s"
          % (out, mapname, start, end - 1, skill, len(ims), out.stat().st_size // 1024, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
