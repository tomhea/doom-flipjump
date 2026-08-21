"""Is the MACRO-LOCAL SCRATCH class (65% of the restore set) actually needed?
Dropping it keeps `sshead`, so this cannot hang."""
import gzip, json, bisect, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT/"tests", ROOT/"src", ROOT, ROOT/"scratchpad"): sys.path.insert(0, str(q))
W = 32
from doomfj.config import Config
from doomfj.fastrun import FjmRunner, _fjcore
from doomfj.fixedpoint import _signed
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel, spawn_state
from doomfj.things import baked_thing_mask, vanishable_slots
from doomfj.wad import WadFile
from doomfj.wireformat import encode_bindings, encode_feed, encode_things, encode_visibility
from flipjump.interpreter.fjm_run import IOReadOnEOF
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from nb_validate import true_sector, _near_any_line
from tests.fj.stream_screen import StreamScreen

r = FjmRunner(Path("scratchpad/fjmcache/_rssprobe.fjm"))
sa, sn = [], []
with gzip.open("scratchpad/_m1b_labels.tsv.gz", "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t: sa.append(int(v)); sn.append(a)
o = sorted(range(len(sa)), key=lambda i: sa[i]); sa = [sa[i] for i in o]; sn = [sn[i] for i in o]
BITS = {}
for n, b in zip(sn, sa): BITS.setdefault(n, b)
HOT = BITS["__hot_end"]; saw = [b // W for b in sa]

def fresh():
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments: c.add_segment(s, n)
    for s, v in r._runs: c.set_words(s, v)
    return c

P = fresh()
w = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad"); art = WadFile.from_path("assets/freedoom1.wad")
rm = ReferenceModel(Config()); cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES); NV = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
BINDS = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])

def wire(vx, vy, va, keys=0, dx=0, dy=0):
    return (encode_feed(vx, vy, va, keys)
            + encode_things([((t.x+dx) << 16, ((t.y+dy)) << 16) for t in RT])
            + BINDS + encode_visibility([1]*NV))

sp = spawn_state(w, "E1M1"); SP = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
_v = [(v.x, v.y) for v in w.vertexes("E1M1")]; _l, _s = w.linedefs("E1M1"), w.sidedefs("E1M1")
_xs = [p[0] for p in _v]; _ys = [p[1] for p in _v]
_pts = [(x, y) for x in range(min(_xs)+13, max(_xs), 256) for y in range(min(_ys)+7, max(_ys), 256)
        if not _near_any_line(_v, _l, x, y, 24.0) and true_sector(_v, _l, _s, x, y) != -1]
CH = [(664 << 16, 291 << 16, 0x18000000, 0, 0, 0), (1272 << 16, (-724) << 16, 0x40000000, 5, 16, 0),
      (1869 << 16, 479 << 16, 0x80000000, 1, 0, 0), (SP[0], SP[1], SP[2], 4, -32, 48),
      (SP[0], SP[1], SP[2], 0, 64, 0), (SP[0], SP[1], SP[2], 8, 0, 0)]
for k, (x, y) in enumerate(_pts[::9][:6]):
    CH.append((x << 16, y << 16, ((k % 4)*(1 << 30)) & 0xFFFFFFFF, (k % 3) and 1, 0, 0))

class MF(StreamScreen):
    def __init__(self, **kw):
        super().__init__(**kw); self.frames = []
    def _present(self):
        super()._present(); self.frames.append(bytes(self.pixel_indices))

def run(core, blob, ip=0):
    scr = MF(stdin=blob, n_things=len(RT)); scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l2, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0, start_ip=ip)
    return ops, scr.frames

REF = []
for c in CH:
    core = fresh(); ops, fr = run(core, wire(*c)); REF.append(fr[0]); del core
print(f"chain {len(CH)} frames, {len(set(REF))} distinct", flush=True)

S0 = sorted(x for a, b in json.load(gzip.open("scratchpad/_m1_setB.json.gz", "rt", encoding="utf-8"))["runs"] for x in range(a, b))
piece = {}
for x in S0:
    i = bisect.bisect_right(saw, x) - 1
    piece.setdefault(sn[i] if i >= 0 else "<none>", []).append(x)

def patch(names):
    ws = sorted(x for n in names for x in piece[n])
    s0 = ws[0]; p = ws[0]; rr = []
    for c in ws[1:]:
        if c != p + 1: rr.append((s0, p+1)); s0 = c
        p = c
    rr.append((s0, p+1))
    return [(a, [P.get_word(x) for x in range(a, b)]) for a, b in rr]

def bad_frames(names):
    pt = patch(names); core = fresh(); bad = 0
    try:
        for k, c in enumerate(CH):
            ops, fr = run(core, wire(*c), 0 if k == 0 else HOT)
            if len(fr) != 1 or fr[0] != REF[k]: bad += 1
            if k+1 < len(CH):
                for a, vals in pt: core.set_words(a, vals)
    finally: del core
    return bad

ALL = list(piece)
NS = [n for n in ALL if not (n and "---" in n)]
wa = sum(len(piece[n]) for n in ALL); wn = sum(len(piece[n]) for n in NS)
print(f"full set        {wa:>8,} words -> {bad_frames(ALL)} bad frames of {len(CH)}", flush=True)
print(f"WITHOUT scratch {wn:>8,} words -> {bad_frames(NS)} bad frames of {len(CH)}", flush=True)
print(f"  macro-local scratch = {wa-wn:,} words = {100*(wa-wn)/wa:.0f}% of the set")
