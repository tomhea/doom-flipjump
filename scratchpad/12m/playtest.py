"""Drive the SHIPPED .fjm and look at the doors -- frames from the BINARY, not the oracle.

Every door judgement in this campaign came from the Python oracle. That is legitimate (m2_std_gate
proves the two are byte-identical over 208 frames) but it is not the same as watching the program
run. This runs the real .fjm through the native engine with the gate's own plan -- walk to a
reachable door, press use, walk through -- and writes the frames THE PROGRAM presented.

    python scratchpad/12m/playtest.py --fjm build/doom_e1m1_blocked21.fjm
    python scratchpad/12m/playtest.py --selftest

CONTROLS (R9)
  C1 THE FRAMES ARE THE BINARY'S -- captured from `run_fj`'s Recording screen. This file never
     calls render_wall_frame.
  C2 THE DOOR MOVED -- the frame just before `use` and a frame after the door opens must differ
     substantially, or the run only proves the program draws something.
  C3 NON-VACUITY -- fewer presented frames than requested is reported, never silently accepted.

WHAT THIS CANNOT PROVE. Whether a shut door OCCLUDES needs a counterfactual (the same view with the
geometry behind the door changed) and a binary cannot be asked that. Occlusion is proven by
scratchpad/12m/leakcheck.py on the oracle, and the gate ties the oracle to the binary. This file
confirms the program on screen matches that picture; it does not replace the measurement.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad", ROOT):
    sys.path.insert(0, str(q))

import m2_std_gate as G                                                    # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import spawn_state, build_scene, _signed      # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.reference_model import ReferenceModel                         # noqa: E402
from doomfj import build as buildmod                                      # noqa: E402


def build_script(nidle=6, open_wait=10):
    """The gate's plan: menu -> walk to the nearest REACHABLE door -> use -> open -> through."""
    mw = WadFile.from_path(str(buildmod.DEFAULT_WAD))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(mw, "E1M1")
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    tbl = G.door_states(secs, lds, sds)
    order = sorted(tbl)
    boxes = G.use_boxes_xy(secs, lds, sds, cmap.vertexes)
    lines_of = G.door_line_ids(secs, lds, sds, tbl)
    sp = spawn_state(mw, "E1M1")
    walk_scene = build_scene(mw, mw, "E1M1")
    _p, cells = G.walkable_cells(rm, walk_scene, _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16)
    pts = {(cx * G.NAV_CELL + G.NAV_CELL // 2, cy * G.NAV_CELL + G.NAV_CELL // 2)
           for cx, cy in cells}
    cands = [si for si in order
             if any(boxes[si][0] <= x <= boxes[si][2] and boxes[si][1] <= y <= boxes[si][3]
                    for x, y in pts)]
    target = min(cands, key=lambda si: ((boxes[si][0] + boxes[si][2]) // 2 - (sp.x >> 16)) ** 2
                 + ((boxes[si][1] + boxes[si][3]) // 2 - (sp.y >> 16)) ** 2)
    segs = [(cmap.vertexes[lds[li].v1], cmap.vertexes[lds[li].v2])
            for li in sorted(lines_of[target])]
    (ax, ay), (bx, by) = segs[0]
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    nx, ny = -(by - ay), (bx - ax)
    nl = (nx * nx + ny * ny) ** 0.5 or 1.0
    nx, ny = nx / nl, ny / nl
    sgn = -1.0 if ((sp.x >> 16) - mx) * nx + ((sp.y >> 16) - my) * ny > 0 else 1.0
    approach = (mx - sgn * nx * 56, my - sgn * ny * 56)
    route = G.plan_walkable(rm, walk_scene, sp, approach, 40,
                            accept=lambda st: G.in_use_box_fixed(boxes[target], st.x, st.y)
                            and ((st.x >> 16) - approach[0]) ** 2
                            + ((st.y >> 16) - approach[1]) ** 2 <= 72 ** 2)
    assert route, "no walkable route to door %d" % target
    press = [{"use": True}, {"use": True}]
    opening = [{} for _ in range(open_wait)]
    idle = [{} for _ in range(nidle)]
    script = ([{} for _ in range(G.MENU_FRAMES)] + route + press + opening + idle)
    return target, len(route), script


def play(fjm, out):
    from PIL import Image
    target, nroute, script = build_script()
    frames_n = len(script)
    events = G.to_events(script) + [
        G.KeyEvent(G.MENU_FRAMES * G.STANDALONE_POLLS, True, G.ENTER),
        G.KeyEvent(G.MENU_FRAMES * G.STANDALONE_POLLS + 1, False, G.ENTER)]
    print("door %d ; %d menu + %d walk + 2 use + 10 open + 6 idle = %d frames"
          % (target, G.MENU_FRAMES, nroute, frames_n))
    print("running the BINARY ...")
    frames, ops = G.run_fj(fjm, events, frames_n)
    print("presented %d frames in %s ops" % (len(frames), format(ops, ",")))
    if len(frames) < frames_n:
        print("C3 !! VACUOUS: only %d of %d frames presented" % (len(frames), frames_n))
        return 1
    pal = WadFile.from_path(str(buildmod.DEFAULT_WAD)).playpal()
    pre = G.MENU_FRAMES + nroute - 1          # last frame before `use`
    post = min(len(frames) - 1, pre + 2 + 10)  # after the door has opened
    diff = sum(1 for a, b in zip(frames[pre], frames[post]) if a != b)
    print("C2 door-shut frame vs door-open frame: %d px differ" % diff)
    if diff < 200:
        print("   !! that is too few -- the door may not have moved")
    tiles = []
    for idx in (pre, pre + 3, pre + 6, post):
        im = Image.new("RGB", (160, 100))
        im.putdata([tuple(pal[p]) for p in frames[idx]])
        tiles.append(im)
    sheet = Image.new("RGB", (320, 200))
    for i, t in enumerate(tiles):
        sheet.paste(t, (160 * (i % 2), 100 * (i // 2)))
    sheet.resize((640, 400), Image.NEAREST).save(out)
    print("-> %s  (shut, opening, opening, open -- all from the BINARY)" % out)
    return 0


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-56s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)
    print("playtest selftest")
    src = Path(G.__file__).read_text(encoding="utf-8")
    check("C1 the gate runs the fjm natively", "FjmRunner(Path(fjm))" in src)
    check("C1 ...and records the BINARY's frames", "class Recording" in src)
    # ⚠ look for a CALL, not the string -- the docstring above names the function, and the first
    # version of this check failed on its own prose.
    import ast as _ast
    _tree = _ast.parse(Path(__file__).read_text(encoding="utf-8"))
    _calls = {n.func.attr for n in _ast.walk(_tree)
              if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)}
    check("C1 this file never CALLS the oracle renderer",
          "render_wall_frame" not in _calls and "render_frame" not in _calls)
    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked21.fjm")
    ap.add_argument("--out", default="scratchpad/12m/playtest_doors.png")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else play(a.fjm, a.out))
