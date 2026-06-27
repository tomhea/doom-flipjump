"""Compare floor band functions for fj-friendliness vs fidelity. The current oracle uses the log MANT=4
band (variable-shift mantissa — expensive in fj). Test a nibble-aligned band (top_nibble_pos<<4 | nibble_val),
which is cheap in fj (scan nibbles, no variable shift). Render both + diff% between them."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import doomfj.reference_model as RM
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state, frame_hash
from doomfj.wad import WadFile

mw = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
sc = build_scene(mw, mw, "E1M1")
st = spawn_state(mw, "E1M1")
pal = [tuple(c) for c in mw.playpal()[:256]]
W, H = 160, 100


def render(bandfn):
    orig = RM.floor_band
    RM.floor_band = bandfn
    try:
        fr = ReferenceModel().render_wall_frame(st, sc)
    finally:
        RM.floor_band = orig
    return fr


def save(fr, name):
    img = Image.new("RGB", (W, H)); px = img.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = pal[fr[y * W + x]]
    img.resize((W * 3, H * 3), Image.NEAREST).save(Path(__file__).resolve().parent / name)


def nibble_band(d):
    if d <= 0:
        return 0
    p = (d.bit_length() - 1) // 4            # top nonzero nibble index
    return (p << 4) | ((d >> (p * 4)) & 0xF)  # exponent (nibble pos) | top nibble value


def log_band(d):                              # the current MANT=4 oracle band
    if d <= 0:
        return 0
    e = d.bit_length()
    return (e << 4) | ((d >> (e - 5)) & 0xF) if e > 4 else d


flog = render(log_band)
fnib = render(nibble_band)
diff = sum(1 for a, b in zip(flog, fnib) if a != b)
# count distinct bands each scheme produces over the real spans (proxy: just report)
print(f"log MANT4 hash : {frame_hash(flog)}")
print(f"nibble    hash : {frame_hash(fnib)}")
print(f"nibble vs log  : {diff}/{W*H} differ ({100*diff/(W*H):.1f}%)")
save(fnib, "band_nibble_e1m1.png")
save(flog, "band_log_e1m1.png")
