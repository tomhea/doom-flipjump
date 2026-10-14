"""P12 (the owner, 2026-10-14: "playtest it yourself to see that nothing is weird") -- a class S binary against the
shipped one on the SAME keyboard: every presented frame's pixels AND palette must be byte-identical, because a class S
change moves no pixel. Each session is driven by nothing but scripted keys through m2_std_gate.run_fj (the
composition `fj --run ... --io pc` builds), menu boot pick included, in both binaries, and compared frame by frame.

Sessions (each its own run of both binaries):
  tour0 .. tour9   gamespeed's ten tours (route-planned walks across the level, doors used), 100 game frames each
  fight0 .. fight4 the tours re-played as a PLAYER: fire held in bursts, strafing, the weapon keys 1..5, a use press
                   every 20 frames (a dead player restarts on use) -- monsters wake, fight, die, drop; 160 frames each
  idle             160 frames standing still (monsters come to the player)
Per session: frames compared, the first frame that differs (pixels or palette), ops per presented frame in each.

--clips DIR: side-by-side GIFs (A left, B right, 3x) of the sessions named by --clip (default fight0, fight3, tour4),
and a PNG contact sheet of every 20th frame of each. Run in a doom-flipjump checkout:
PYTHONPATH="src;scratchpad;scratchpad/12m;scratchpad/gp" python scratchpad/gp/p12_playtest.py A.fjm B.fjm [--clips DIR]"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path[:0] = ["scratchpad", "scratchpad/12m", "scratchpad/gp", "src"]
import gamespeed as GS  # noqa: E402
import m2_std_gate as gate  # noqa: E402

N_TOUR, N_FIGHT, N_IDLE = 100, 160, 160


class PalRecording(gate.Recording):
    """the gate's Recording, plus each present's whole palette (the clips need the colours, not a hash)"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.pals = []

    def _present(self):
        super()._present()
        self.pals.append(bytes(b for rgb in self.palette for b in rgb))


def fight_script(seed, n):
    base = GS.script(seed, n)
    out = []
    for f, kd in enumerate(base):
        k = dict(kd)
        if (f // 6) % 3 != 2:                           # fire in bursts: 12 frames on, 6 off
            k["fire"] = True
        if (f // 25) % 4 == 1:
            k["strafe_left"] = True
        elif (f // 25) % 4 == 3:
            k["strafe_right"] = True
        if f % 40 == 10:                                # cycle the weapons
            k["w%d" % (1 + (f // 40 + seed) % 5)] = True
        if f % 20 == 19:
            k["use"] = True                             # doors -- and a dead player's restart
        out.append(k)
    return out


def sessions():
    out = {}
    for s in range(10):
        out["tour%d" % s] = GS.script(s, N_TOUR)
    for s in range(5):
        out["fight%d" % s] = fight_script(s * 2 + 1, N_FIGHT)
    out["idle"] = [{} for _ in range(N_IDLE)]
    return out


def run(fjm, per_frame):
    full = [{} for _ in range(gate.MENU_FRAMES)] + per_frame
    rec = {}

    def factory():
        rec["s"] = PalRecording()
        return rec["s"]
    frames, ops = gate.run_fj(fjm, GS.events_for(full), len(full), screen_factory=factory)
    return frames, rec["s"].pals, ops


def clip(path, fa, pa, fb, pb, w, h, scale=3, step=1):
    from PIL import Image, ImageDraw
    imgs = []
    for k in range(0, len(fa), step):
        canvas = Image.new("RGB", (2 * w * scale + 8, h * scale + 14), (16, 16, 16))
        for j, (fr, pal) in enumerate(((fa[k], pa[k]), (fb[k], pb[k]))):
            im = Image.frombytes("P", (w, h), fr)
            im.putpalette(pal)
            canvas.paste(im.convert("RGB").resize((w * scale, h * scale), Image.NEAREST), (j * (w * scale + 8), 14))
        d = ImageDraw.Draw(canvas)
        d.text((4, 1), "blocked57 (shipped)   frame %d" % k, fill=(230, 230, 230))
        d.text((w * scale + 12, 1), "P12 candidate   %s" % ("IDENTICAL" if (fa[k], pa[k]) == (fb[k], pb[k]) else "DIFFERS"),
               fill=(230, 230, 230))
        imgs.append(canvas)
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=70, loop=0, optimize=True)
    return len(imgs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--clips", default=None)
    ap.add_argument("--clip", default="fight0,fight3,tour4")
    ap.add_argument("--only", default=None, help="comma list of session names")
    args = ap.parse_args()
    from doomfj.config import Config
    W, H = Config().W, Config().H
    ss = sessions()
    if args.only:
        ss = {k: ss[k] for k in args.only.split(",")}
    print("A %s (sha256 %s)" % (args.a, hashlib.sha256(Path(args.a).read_bytes()).hexdigest()[:16]))
    print("B %s (sha256 %s)" % (args.b, hashlib.sha256(Path(args.b).read_bytes()).hexdigest()[:16]))
    bad, total, rows = [], 0, {}
    for name, pf in ss.items():
        t0 = time.time()
        fa, pa, oa = run(args.a, pf)
        fb, pb, ob = run(args.b, pf)
        n = len(fa)
        diff = [k for k in range(min(n, len(fb))) if fa[k] != fb[k] or pa[k] != pb[k]]
        ok = n == len(fb) == gate.MENU_FRAMES + len(pf) and not diff
        total += n
        rows[name] = {"frames": n, "identical": ok, "first_diff": diff[0] if diff else None,
                      "ops_a": oa / n, "ops_b": ob / n}
        print("%-8s %4d frames  %s  ops/frame A %s  B %s  (%+.2f%%)  %.0fs" % (
            name, n, "IDENTICAL (pixels + palette)" if ok else "DIFFER at frame %s (%d frames)" % (
                diff[0] if diff else "count", len(diff)), format(round(oa / n), ","), format(round(ob / n), ","),
            100.0 * (ob - oa) / oa, time.time() - t0), flush=True)
        if not ok:
            bad.append(name)
        if args.clips and name in args.clip.split(","):
            d = Path(args.clips)
            d.mkdir(parents=True, exist_ok=True)
            k = clip(d / ("p12_%s.gif" % name), fa, pa, fb, pb, W, H)
            print("   clip -> %s (%d frames)" % (d / ("p12_%s.gif" % name), k), flush=True)
    sa = sum(r["ops_a"] * r["frames"] for r in rows.values())
    sb = sum(r["ops_b"] * r["frames"] for r in rows.values())
    print("")
    print("%d sessions, %d frames each binary: %s; ops over all sessions A %s B %s (%+.2f%%)" % (
        len(rows), total, "EVERY FRAME IDENTICAL" if not bad else "DIFFER: " + ", ".join(bad),
        format(round(sa), ","), format(round(sb), ","), 100.0 * (sb - sa) / sa))
    if args.clips:
        Path(args.clips, "p12_playtest.json").write_text(json.dumps(rows, indent=1), encoding="ascii")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
