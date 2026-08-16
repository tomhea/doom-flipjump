"""M14.5 — do the BAKED constants and the RUNTIME row describe the same thing? Seconds, no build.

The hybrid draws some things from an xor_by block of compile-time constants and the rest from the
`throw`/`throwc` tables, through the SAME `thing_record_body`. Both halves were gated on their own,
so if the hybrid moves pixels, the first question is whether the two descriptions of one thing are
even equal -- and that is pure Python.

For EVERY drawable thing this prints any field where the two disagree:

    sp_left sp_w sp_hh sp_tzmax sp_tzmax2 sp_mon sp_base sp_base2 sp_dw   (per-thing constants)
    sp_z    = leaf floor + art z-offset                                   (per bound leaf)
    sp_lt   = the light class                                             (per bound leaf)

⚠ It compares what the EMITTER bakes against what `thing_rows`/`sprite_light_table` put in the
tables -- the same equality `things.check_row_equivalence` asserts for the two leaf-derived fields,
extended to the whole register set the hybrid now sources two different ways.

    python scratchpad/m145_consts.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (DEG_MINH2_MON, DEG_MINH2_SCENERY,     # noqa: E402
                                    DEG_SPR_NEAR_TZ, MIN_SPRITE_H,
                                    MIN_SPRITE_H_MONSTER, MONSTER_TYPES,
                                    ReferenceModel)
from doomfj.things import drawable_things, thing_rows                     # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import (_lines_sprite_bank, _lines_sprite_light,  # noqa: E402
                                  _thing_sector)

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cmap = bake_bsp(mw, "E1M1")
lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")

_, spr_base, spr_dw, spr_ldbase = _lines_sprite_bank(rm, art, cfg, mw, "E1M1")
_, spr_cls = _lines_sprite_light(rm, cfg, art, mw, "E1M1", cmap, lds, sds, secs,
                                 moving_things=True)

drawable, _ = drawable_things(rm, mw.things("E1M1"), art, {})
rows, idx = thing_rows(rm, mw.things("E1M1"), art, spr_base, spr_ldbase, spr_dw, MONSTER_TYPES,
                       MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                       deg=True, spr_near=bool(DEG_SPR_NEAR_TZ), cache={})
assert len(rows) == len(drawable), f"{len(rows)} rows vs {len(drawable)} drawable"

bad = 0
for i, (t, row) in enumerate(zip(drawable, rows)):
    a = rm.sprite_art(art, t.type, {})
    sec = _thing_sector(rm, cmap, lds, sds, secs, t)
    mon = t.type in MONSTER_TYPES
    baked = {
        "left": a[5], "w": a[3], "hh": a[4], "zoff": a[6],
        "tzmax": rm.sprite_tz_min_size(a[4], MIN_SPRITE_H_MONSTER if mon else MIN_SPRITE_H)
        & 0xFFFFFFFF,
        "tzmax2": rm.sprite_tz_min_size(a[4], DEG_MINH2_MON if mon else DEG_MINH2_SCENERY)
        & 0xFFFFFFFF,
        "base": spr_base[t.type], "base2": spr_ldbase[t.type],
        "mon": 1 if mon else 0, "dw": spr_dw[t.type],
        "z": (sec.floor_h + a[6]) & 0xFFFF,
        "lt": spr_cls[(rm.wall_lightnum(sec.light, 0), max(1, a[4]))],
    }
    table = dict(zip(("left", "w", "hh", "zoff", "tzmax", "tzmax2", "base", "base2", "mon", "dw"),
                     row))
    diff = {k: (baked[k], table[k]) for k in table if baked[k] != table[k]}
    if diff:
        bad += 1
        print(f"  thing {i:3d} type {t.type:5d} at ({t.x},{t.y}): {diff}")

print(f"{len(drawable)} drawable things, {bad} with a baked/table mismatch")
sys.exit(1 if bad else 0)
