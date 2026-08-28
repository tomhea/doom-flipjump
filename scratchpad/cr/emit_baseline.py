"""THE SAFETY NET FOR AN API-CHANGING REFACTOR: freeze the emitted text's hashes, then check them.

`emit_hash_vs_head.py` compares the working tree against a git ref by calling THE SAME SIGNATURE on
both sides. That is exactly right for a behaviour change and useless for a refactor that deletes
parameters: the moment `two_sided=` or `plane_near=` stops existing, the comparison cannot be made
at all, and the one guarantee worth having -- "I deleted only code the shipped picture never runs"
-- goes with it.

So this decouples the two halves. `--save` emits the shipped configs and writes their per-part
SHA-256 to a JSON file. `--check` emits again, through whatever the API looks like now, and diffs
against that file. Kwargs the signature no longer accepts are DROPPED and reported -- which is the
point: after a deletion, that value is the only one the emitter has, so the text must be the same.

    python scratchpad/cr/emit_baseline.py --save          # before the refactor
    python scratchpad/cr/emit_baseline.py --check         # after each stage
    python scratchpad/cr/emit_baseline.py --check --selftest   # R9: a mutated tree must FAIL

⚠ IT ONLY GUARDS THE CONFIGS IT WAS SAVED WITH. A part that changes for a config not listed here is
invisible to it. The two listed are the two that matter: what the M14 gates certify, and what
`build_wall_renderer` actually ships.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config                                          # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

BASELINE = ROOT / "scratchpad/cr/emit_baseline.json"

CONFIGS = {
    "certified": dict(over_align=False, floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                      plane_near=True, wall_noise=True, steps=True, stack_steps=True, things=True,
                      deg=True, state_wire="bin", player_sim=True, collide=True,
                      moving_things=True, sky=True, bbox_cull=True),
    "standalone": dict(over_align=False, floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                       plane_near=True, wall_noise=True, sky=True, steps=True, things=True,
                       stack_steps=True, bbox_cull=True, deg=True, state_wire="bin",
                       player_sim=True, collide=True, moving_things=True,
                       standalone=True, menu=True, doors=True),
}


def emit_parts(kw, mutate=False):
    """Emit one config through the CURRENT signature, dropping kwargs it no longer accepts."""
    import inspect

    from doomfj.wall_renderer import emit_wall_renderer
    accepted = set(inspect.signature(emit_wall_renderer).parameters)
    dropped = sorted(k for k in kw if k not in accepted)
    kw = {k: v for k, v in kw.items() if k in accepted}
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    aw = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    parts = emit_wall_renderer(mw, "E1M1", Config(), asset_wad=aw,
                               sprite_wad=aw, return_parts=True, **kw)
    out = {}
    for pname, lines in parts:
        text = "\n".join(lines) if isinstance(lines, list) else lines
        if mutate and pname == "state":
            text += "\n// selftest mutation\n"
        out[pname] = (hashlib.sha256(text.encode()).hexdigest(), len(text))
    return out, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="R9: perturb the emitted text and require --check to FAIL")
    args = ap.parse_args()
    assert args.save or args.check, "pass --save or --check"

    got = {}
    for name, kw in CONFIGS.items():
        t = time.perf_counter()
        parts, dropped = emit_parts(kw, mutate=args.selftest)
        got[name] = parts
        print("%-11s %d parts, %s chars, %.0f s%s"
              % (name, len(parts), format(sum(n for _h, n in parts.values()), ","),
                 time.perf_counter() - t,
                 ("   (dropped, no longer accepted: %s)" % ", ".join(dropped)) if dropped else ""),
              flush=True)

    if args.save:
        BASELINE.write_text(json.dumps({"configs": {k: {p: list(v) for p, v in c.items()}
                                                    for k, c in got.items()}}, indent=1),
                            encoding="utf-8")
        print("")
        print("saved -> %s" % BASELINE)
        return 0

    want = json.loads(BASELINE.read_text(encoding="utf-8"))["configs"]
    ok = True
    print("")
    for name in sorted(want):
        for part in sorted(want[name]):
            wh, wn = want[name][part]
            gh, gn = got.get(name, {}).get(part, ("<missing>", 0))
            same = gh == wh
            ok &= same
            print("  %-11s %-10s %s  %s"
                  % (name, part, "SAME" if same else "DIFF",
                     "%s chars" % format(wn, ",") if same
                     else "baseline %s / now %s chars" % (format(wn, ","), format(gn, ","))))
        extra = sorted(set(got.get(name, {})) - set(want[name]))
        if extra:
            ok = False
            print("  %-11s !! NEW PARTS the baseline does not have: %s" % (name, extra))
    print("")
    if args.selftest:
        print("SELF-TEST (one comment appended to the `state` part): %s"
              % ("PASS -- the check rejected it" if not ok else "!! FAIL -- it accepted a change"))
        return 0 if not ok else 1
    print("EMISSION %s" % ("IDENTICAL -- the refactor removed only code the shipped picture "
                           "never runs" if ok else "!! MOVED -- something live was deleted"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
