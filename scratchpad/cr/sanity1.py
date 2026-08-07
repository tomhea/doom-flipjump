"""CR fix-batch sanity: imports, degrade-merge semantics, and the sky-riser reach probe."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# 1) every edited module imports
import doomfj.wall_renderer as wr
import doomfj.reference_model as rmm
import doomfj.mapcompiler as mc
import doomfj.tables as tb
import doomfj.build as bd
import doomfj.fastrun as fr
import doomfj.coarse_cull as cc
import tests.fj.stream_screen as ss
print("imports OK")

# 2) scalelight is BYTE-IDENTICAL at view_w=160 (the certified width)
old = [[max(0, min(31, ((15 - i) * 2) * 32 // 16 - j * (320 // 160) // 2))
        for j in range(48)] for i in range(16)]
new = tb.scalelight_table(160, 32)
assert new == old, "scalelight changed at view_w=160!"
print("scalelight: byte-identical at 160")

# 3) recip assert fires
try:
    rmm.ReferenceModel._scale_recip_div(1, 0)
    raise SystemExit("recip div accepted den=0!")
except AssertionError:
    print("recip den=0 asserts (no hang)")

# 4) sky-riser probe: how many E1M1-lite two-sided boundaries are sky-sky with differing
#    ceil heights, split riser vs lip (riser = the newly suppressed case)
from doomfj.wad import WadFile
wad = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
lds, sds, secs = wad.linedefs("E1M1"), wad.sidedefs("E1M1"), wad.sectors("E1M1")
riser = lip = 0
for ld in lds:
    if ld.back == -1 or ld.front == -1:
        continue
    f, b = secs[sds[ld.front].sector], secs[sds[ld.back].sector]
    if (f.ceil_tex or "").upper() == "F_SKY1" and (b.ceil_tex or "").upper() == "F_SKY1" \
            and f.ceil_h != b.ceil_h:
        if f.ceil_h > b.ceil_h:
            riser += 1
        else:
            lip += 1
print(f"sky-sky differing-ceil boundaries: riser(front-higher)={riser} lip(front-lower)={lip}")

# 5) v5_side_modes now suppresses BOTH for sky-sky
class _S:
    def __init__(self, ch, ct, fh, ft):
        self.ceil_h, self.ceil_tex, self.floor_h, self.floor_tex = ch, ct, fh, ft
a = _S(128, "F_SKY1", 0, "X")
b = _S(96, "F_SKY1", 0, "X")
assert rmm.ReferenceModel.v5_side_modes(a, b, True) == (0, 0), "riser not suppressed"
assert rmm.ReferenceModel.v5_side_modes(b, a, True) == (0, 0), "lip not suppressed"
a2 = _S(128, "CEIL3_5", 0, "X")
assert rmm.ReferenceModel.v5_side_modes(a2, b, True)[0] == 1, "non-sky riser wrongly suppressed"
print("v5_side_modes: sky-sky suppression covers riser + lip; non-sky untouched")
