"""THE CONTROL for an opt-in emitter flag: does the SHIPPED path still emit the same text?

`emit_hash.py` compares against a stored baseline, which is only meaningful if nothing legitimate
changed the emission since. After a run of milestones it is stale, and a stale baseline reports
DIFF for every config whether or not the change under review touched anything -- i.e. it stops
being a control at all.

This one carries its own baseline: it emits the certified config TWICE, once with the working
tree's `wall_renderer.py` and once with **HEAD's**, in the same process, and diffs the two texts.
A flag that is genuinely opt-in must produce identical text with the flag off.

⚠ NEGATIVE CONTROL (R9): `--selftest` perturbs the HEAD copy by one character and requires this
script to report DIFF. A comparison that cannot fail is not evidence.

    python scratchpad/cr/emit_hash_vs_head.py [--selftest]
"""
import hashlib
import importlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELFTEST = "--selftest" in sys.argv

# HEAD's src tree, complete, so the import graph resolves exactly as it does in the working tree
head_dir = Path(tempfile.mkdtemp()) / "src"
shutil.copytree(ROOT / "src", head_dir)
head_txt = subprocess.run(["git", "show", "HEAD:src/doomfj/wall_renderer.py"], cwd=ROOT,
                          capture_output=True, check=True).stdout.decode("utf-8")
if SELFTEST:
    # the mutation: one baked constant, one character -- the smallest thing that must still trip it
    assert "sp_dw: hex.vec 2" in head_txt, "the self-test's anchor moved; pick another"
    head_txt = head_txt.replace("sp_dw: hex.vec 2", "sp_dw: hex.vec 3", 1)
(head_dir / "doomfj" / "wall_renderer.py").write_text(head_txt, encoding="utf-8")

CONFIGS = {
    # what the M14 gates certify
    "certified": dict(return_parts=True, over_align=False, floor_mode="FT1", wall_mode="W1R",
                      raster_mode="lines", plane_near=True, wall_noise=True, steps=True,
                      stack_steps=True, things=True, deg=True, state_wire="bin",
                      player_sim=True, collide=True),
    # ⚠ what `build.build_wall_renderer` ACTUALLY ships (its own defaults) -- a different flag set,
    # and the one `test_build_wall_renderer_e1m1_flat` spends ~70 minutes rebuilding. Identical
    # emitted text is the same proof that test gives, in minutes instead.
    "shipped": dict(return_parts=True, over_align=False, floor_mode="FT1", wall_mode="WPX",
                    raster_mode="lines", plane_near=True, wall_noise=True, sky=True, steps=True,
                    things=True),
}


def emit(src_dir):
    """Emit the certified config with `src_dir` first on the path. The doomfj modules are dropped
    between calls so the second import genuinely re-reads from the other tree."""
    for name in [m for m in list(sys.modules) if m == "doomfj" or m.startswith("doomfj.")]:
        del sys.modules[name]
    sys.path.insert(0, str(src_dir))
    try:
        importlib.invalidate_caches()
        from doomfj.config import Config
        from doomfj.wad import WadFile
        from doomfj.wall_renderer import emit_wall_renderer
        cfg = Config()
        # e1m1_lite carries the GEOMETRY only -- textures/colormap/palette come from the full wad
        # and the sprites from the art wad, exactly as emit_hash.py splits them
        mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
        aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
        art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
        out = []
        for cfg_name, kw in CONFIGS.items():
            parts = emit_wall_renderer(mw, "E1M1", cfg, asset_wad=aw, sprite_wad=art, **kw)
            out += [(f"{cfg_name}/{name}", hashlib.sha256(text.encode()).hexdigest(), len(text))
                    for name, text in parts]
        return out
    finally:
        sys.path.remove(str(src_dir))


head = emit(head_dir)
work = emit(ROOT / "src")
bad = 0
for (hn, hh, hl), (wn, wh, wl) in zip(head, work):
    same = (hn, hh) == (wn, wh)
    bad += not same
    print(f"  {wn:<22} {'SAME' if same else 'DIFF'}  {wh[:16]}  {wl:,} chars"
          + ("" if same else f"   (HEAD {hh[:16]}, {hl:,})"))
if len(head) != len(work):
    print(f"  !! part COUNT differs: HEAD {len(head)}, working tree {len(work)}")
    bad += 1

if SELFTEST:
    print("\nSELF-TEST: mutated HEAD's sp_dw declaration by one character")
    print("PASS -- the comparison rejects a mutated tree" if bad else
          "!! FAIL -- the comparison called a MUTATED tree identical; it proves nothing")
    sys.exit(0 if bad else 1)
print("\nEMISSION IDENTICAL -- the flag is opt-in and the certified binary is unaffected"
      if not bad else f"\n{bad} parts DIFFER -- the shipped path changed, re-certify it")
sys.exit(0 if not bad else 1)
