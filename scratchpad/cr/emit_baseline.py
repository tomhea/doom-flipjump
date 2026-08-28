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
invisible to it. The three listed are the ones that matter: what the M14 gates certify, what
`build_wall_renderer` actually ships, and the hosted+doors binary the M2 gates build.
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
    # The third point in flag space, added 2026-08-28 before the next deletion batch: the HOSTED
    # tier with doors on. That is the binary `m2_r3_gate` / `m2_r4_gate` / `m2_ops` build, and
    # neither config above reaches it -- `certified` has no doors, `standalone` has doors only
    # together with standalone+menu. Without it a deletion could move the door emission in the
    # hosted tier and every part would still read SAME.
    "hosted_doors": dict(sky=True, steps=True, things=True, stack_steps=True, bbox_cull=True,
                         deg=True, player_sim=True, collide=True, moving_things=True,
                         doors=True),
}


def drop_unaccepted(kw):
    """`(kept, dropped)` for the CURRENT `emit_wall_renderer` signature.

    Its own function so that `emit_parts` and CONTROL 2 run the SAME code. The first version of
    that control re-implemented this filter inline, which made it a tautology: `dropped = []`
    inside `emit_parts` would have left it green."""
    import inspect

    from doomfj.wall_renderer import emit_wall_renderer
    accepted = set(inspect.signature(emit_wall_renderer).parameters)
    return ({k: v for k, v in kw.items() if k in accepted},
            sorted(k for k in kw if k not in accepted))


def emit_parts(kw, mutate=False):
    """Emit one config through the CURRENT signature, dropping kwargs it no longer accepts.

    `mutate` is R9's negative control, and it changes REAL EMITTER CODE rather than this
    function's output. The earlier version appended a comment to the text after emission,
    which proved only that sha256 can tell two strings apart -- nothing upstream of the
    comparison was ever different, so it could not have caught the check reading the wrong
    thing. Here the wall background colour index moves in BOTH modules that hold it, and the
    check has to notice a real emitter producing real different output. Which parts move is
    reported by the run itself -- this docstring does not claim a number it has not measured."""
    from doomfj import reference_model, wall_renderer
    from doomfj.wall_renderer import emit_wall_renderer
    kw, dropped = drop_unaccepted(kw)
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    aw = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    # ⚠ WHICH constant matters, and the first two guesses were both wrong. `WALL_BG` moves the
    # synthetic W1R texel, so it reaches `segconsts` and `tables` -- and NOT `banks`, which is
    # 124.3M of the 138.7M characters compared and is where the retirement deleted two wall-strip
    # banks. Rebinding it in both modules did not help: the banks come from the WAD's textures,
    # not from that index. `SPR_BLOCK_STRIDE` is the sprite bank's own stride, so mutating it
    # rewrites every block in `banks`. The two together are what make the control cover the file.
    _saved = {"wr_bg": wall_renderer.WALL_BG, "rm_bg": reference_model.WALL_BG,
              "stride": wall_renderer.SPR_BLOCK_STRIDE}
    if mutate == "texel":
        wall_renderer.WALL_BG = reference_model.WALL_BG = _saved["wr_bg"] ^ 1
    elif mutate == "banks":
        wall_renderer.SPR_BLOCK_STRIDE = _saved["stride"] * 2
    try:
        parts = emit_wall_renderer(mw, "E1M1", Config(), asset_wad=aw,
                                   sprite_wad=aw, return_parts=True, **kw)
    finally:
        wall_renderer.WALL_BG = _saved["wr_bg"]
        reference_model.WALL_BG = _saved["rm_bg"]
        wall_renderer.SPR_BLOCK_STRIDE = _saved["stride"]
    out = {}
    for pname, lines in parts:
        text = "\n".join(lines) if isinstance(lines, list) else lines
        out[pname] = (hashlib.sha256(text.encode()).hexdigest(), len(text))
    return out, dropped


def check_drop_is_reported():
    """The second control, for the shape that can defeat THIS tool in particular.

    Its whole job is to keep checking through a signature that is losing parameters, and it does
    that by DROPPING kwargs the emitter no longer accepts. A drop that went UNREPORTED would look
    exactly like a config still being exercised: the check would print SAME for a flag nobody
    passes any more, and a refactor could delete the live branch behind it unseen. So hand it a
    name no signature will ever have and require it back."""
    bogus = "__a_flag_that_was_retired__"
    kept, dropped = drop_unaccepted({bogus: True, "things": True})
    return dropped == [bogus] and "things" in kept


def selftest_mutations():
    """CONTROL 1: two REAL emitter mutations, each re-emitted and each required to be rejected.

    Why two. A negative control has to cover the shapes that can defeat the tool, and one mutation
    did not: `WALL_BG` moves the synthetic W1R texel and so reaches `segconsts` and `tables`, while
    `banks` -- 124.3M of the 138.7M characters this file compares, and where the retirement deleted
    two wall-strip banks -- stayed SAME under it. `SPR_BLOCK_STRIDE` rewrites every sprite block
    and is what covers that. The run prints which parts each one moved, so the claim is the log's
    and not this docstring's."""
    want = json.loads(BASELINE.read_text(encoding="utf-8"))["configs"]
    name, kw = list(CONFIGS.items())[0]
    ok = True
    for tag in ("texel", "banks"):
        t = time.perf_counter()
        got, _dropped = emit_parts(kw, mutate=tag)
        moved = sorted(pt for pt, (h, _n) in got.items() if want[name].get(pt, [None])[0] != h)
        rejected = bool(moved)
        ok &= rejected
        print("  %-6s %-40s %-28s %.0f s"
              % (tag,
                 "PASS -- the check rejected it" if rejected else "!! FAIL -- it accepted",
                 "moved: " + (", ".join(moved) if moved else "NOTHING"),
                 time.perf_counter() - t), flush=True)
    print("")
    print("CONTROL 1 (two real emitter mutations, config %r): %s"
          % (name, "PASS" if ok else "!! FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="R9: perturb the emitted text and require --check to FAIL")
    args = ap.parse_args()
    assert args.save or args.check, "pass --save or --check"

    if args.selftest:
        print("CONTROL 2 (a dropped kwarg is REPORTED, not silently ignored): %s"
              % ("PASS" if check_drop_is_reported() else "!! FAIL"))
        print("")
        return selftest_mutations()

    got = {}
    # The mutation control needs TEETH, not coverage: one config proves the check can see a real
    # emitter change, and three emissions of it would cost 30 minutes to say the same thing.
    for name, kw in list(CONFIGS.items()):
        t = time.perf_counter()
        parts, dropped = emit_parts(kw)
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
    print("EMISSION %s" % ("IDENTICAL -- the refactor removed only code the shipped picture "
                           "never runs" if ok else "!! MOVED -- something live was deleted"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
