"""M7 P6+P7: the ops one more weapon pass a frame costs (weaponcode.weapon_lines(tics=2) vs tics=1), in the
tests/fj/test_weapon_fj.py harness -- the real emitted text, NOT the game: a flip's cost is the popcount of its
address, so in-game numbers move with placement (UNVERIFIED in game; profx on the build is the measure).

    python scratchpad/gp/weapon_tics_cost.py

Three key scripts of N frames each: idle (the pistol ready, no key), fire held (the pistol firing and refiring),
a mix (test_weapon_fj's own script). ops/frame for tics 1 and 2 and the difference. Each run is checked against
the model at the same tempo first (world.WEAPON_TICS is patched for the tics=1 row), so the ops are those of a
correct program.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "fj")]

import flipjump as fj                                                 # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO          # noqa: E402

import test_weapon_fj as T                                           # noqa: E402
from doomfj import world as WD                                       # noqa: E402
from doomfj.config import GAME_CFG                                   # noqa: E402
from doomfj.harness import W                                         # noqa: E402
from doomfj.world import KEYS                                        # noqa: E402

N = 200


def scripts():
    idle = [{k: False for k in KEYS} for _ in range(N)]
    held = [dict({k: False for k in KEYS}, fire=True) for _ in range(N)]
    return {"idle": idle, "fire held": held, "mix (test_weapon_fj)": T._script()[:N]}


def run(script, tics, tmp):
    WD.WEAPON_TICS = tics                    # the model's count, for the correctness check of this row
    w = T._world(True)
    text, states, frames = T._program(T._start(w), None, tics)
    src = tmp / ("w%d.fj" % tics)
    src.write_text(text, encoding="utf-8")
    out = tmp / ("w%d.fjm" % tics)
    consts = GAME_CFG.emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    feed = b"".join(bytes([1, int(k["fire"]) | int(k["w1"]) << 1 | int(k["w2"]) << 2 | int(k["w3"]) << 3
                           | int(k["w4"]) << 4]) for k in script) + bytes([0])
    io = FixedIO(feed)
    stats = fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = [[int(v, 16) for v in line.split(",")[:len(T.CELLS)]]
           for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:len(script)]]
    rows = []
    wm = T._world(True)
    for k in script:
        wm.tic(k)
        rows.append({f: getattr(wm.ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                                    "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown",
                                                    "rng_player")} | {"ammo": tuple(wm.ws.p_ammo),
                                                                       "owned": tuple(wm.ws.p_owned)})
    want = [T._want(r, states, frames) for r in rows]
    assert got == want, ("tics", tics, "the program is not the model")
    return stats.op_counter / len(script)


def main():
    keep = WD.WEAPON_TICS
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        print("ops/frame of the weapon harness (the whole loop: input decode, the weapon, the prints)")
        for name, sc in scripts().items():
            a, b = run(sc, 1, tmp), run(sc, 2, tmp)
            print("  %-22s tics=1 %8.0f  tics=2 %8.0f  +%6.0f (+%.0f%%)" % (name, a, b, b - a, 100 * (b - a) / a))
    WD.WEAPON_TICS = keep


if __name__ == "__main__":
    main()
