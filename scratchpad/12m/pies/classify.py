"""The shipped game's program size and per-frame ops, by category.

    python classify.py <labels.tsv.gz> <game .fjm> <generated dir> <games .incl.bin> <calibration .incl.bin> <out.json>

Size: every stored word of the .fjm belongs to one category. Every border comes from the build itself: the generated
parts' lowest top-level label (as profx maps.py), named labels (`__hot_end`, `vpb_blk__`, `vql_blk__`, `m1_reset`),
the max label below the pool, and the fjm's stored segments. A word-flip chain's words are shared among the
categories whose ops reach it.
Ops: profx's per-word inclusive counts of gamespeed's ten games (`drive.py games`), less the calibration run's
(`drive.py still 0`) once for each of the eleven runs: the game frames only, each op charged to its word's category.
The output: {"size": {category: [own words, chain words]}, "ops": {category: ops per frame}, "borders": {...}}, and
<out>_iv.npz, the address -> category map.
"""
import collections
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
from flipjump.fjm import fjm_reader as R

LABELS, FJM, GEN, INCL, CAL, OUT = sys.argv[1:7]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profx"))
import phases as PH                                  # noqa: E402
from common import load_marks, load_sparse           # noqa: E402

POOL0 = 0x80000000 // 32

# ---------------------------------------------------------------------------------------------- the label table
rows = []
with gzip.open(LABELS, "rt", encoding="utf-8") as fh:
    for ln in fh:
        n, _, a = ln.rstrip("\n").rpartition("\t")
        if a:
            rows.append((int(a) // 32, n))
rows.sort()
byname = {}
for a, n in rows:
    byname.setdefault(n, a)
PART_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*):")
part = {}
for f in sorted(Path(GEN).glob("e1m1_0*.fj")):
    lo = None
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            m = PART_RE.match(line)
            if m and m.group(1) in byname:
                lo = byname[m.group(1)] if lo is None else min(lo, byname[m.group(1)])
    part[f.stem] = lo
TABLES0 = part["e1m1_01_tables"]                     # 65,536: the entry part (startup) ends here
HOT = byname["__hot_end"]                            # the main part's first op (input: kb.poll + key decode)
SEGC, WALK0 = part["e1m1_03_segconsts"], part["e1m1_04_walk"]
STATE0, BANKS0 = part["e1m1_05_state"], part["e1m1_06_banks"]
SPRB0 = min(a for a, n in rows if n.startswith("sprbkt") or "sprbkt.init" in n)     # the sprite bank (pictures)
VPB0, VQL0, RESET0 = byname["vpb_blk__"], byname["vql_blk__"], byname["m1_reset"]
CODE0 = min(a for a, n in rows if n.endswith("code_start"))   # the stl runtime ends, the entry part begins
below = [a for a, _ in rows if a < POOL0]
W0 = max(below) + 64                                 # the reset's last label + its exact_xor tail (profx maps.py)

_header, blob = R.read_fjm_raw(Path(FJM))            # flipjump's own loader: it reads every .fjm version
assert _header.memory_width == 32 and _header.relative_jumps, (_header.memory_width, _header.version)
segs = np.array(_header.segments, dtype=np.int64).reshape(-1, 4)
low = segs[segs[:, 0] < POOL0]
assert len(low) == 1 and low[0, 0] == 0 and low[0, 1] == low[0, 3], low[:3]
W1 = int(low[0, 1])                                  # everything below the pool is ONE stored segment [0, W1)
POOL_STORED = int(segs[segs[:, 0] >= POOL0][:, 3].sum())
POOL_TABLES = int((segs[:, 0] >= POOL0).sum())       # a pool table is its own segment (the build log's 'blocked N tables')
TOTAL = int(segs[:, 3].sum())
print("borders: code_start %d tables %d hot %d segconsts %d walk %d state %d banks %d sprite bank %d vpb %d vql %d "
      "reset %d wflip %d..%d; pool stored %d; total stored %d" % (CODE0, TABLES0, HOT, SEGC, WALK0, STATE0, BANKS0, SPRB0,
                                                                 VPB0, VQL0, RESET0, W0, W1, POOL_STORED, TOTAL))
assert CODE0 < TABLES0 < HOT < SEGC < WALK0 < STATE0 < BANKS0 < SPRB0 < VPB0 < VQL0 < RESET0 < W0 < W1 < POOL0

# ---------------------------------------------------------------------------------------------- code families
WALLS = {"seg", "dsw"}
SPRITES = {"thing", "thsel"}
BSP = {"bbgate", "bsp", "e1m1_bspcode", "ss", "bbgo", "bbmiss", "sfl"}   # sfl: a lift's floor inside the walk
WEAPON = {"hwf", "hff"}                  # the weapon in hand + its flash: DOOM's player sprites (r_things.c)
SCREEN = {"hud", "hb", "wpb", "p", "pl", "plm", "hpt", "mf", "mn", "menu"}
COLL = {"simcollide", "cma", "cmb", "cmc", "cmh", "cmv", "e1m1_mc",
        "e1m1_cc", "e1m1_dsccs", "ptloc", "e1m1_cs",
        "cse",                     # the collision seed's floor/ceiling on a mover leaf (in the dsccs walk)
        "pw",                      # a projectile linked into / out of the subsector thing lists (P_SetThingPosition)
        "ptt",                     # the solid-thing touch test of the collision cells (ptt_hit zeroes cp_ok)
        "ms",                      # a monster's move: P_CheckPosition's seed (mm: by label below; dubmb + mm_db*: the
                                   #   refused move's door press = P_Move's door logic -> game logic)
        "pb", "pbt"}               # the player blocked by a solid monster (lootcode._solid_thing_at)
VIEW = {"e1m1_dsc", "dsc", "lnd", "dvz",          # the eye's sector + height (and on a moving lift), the dying sink
        "vx", "vy", "vxsx", "vysx", "vxdone", "vydone"}  # the eye's integer position, read by the BSP walk + eye walk
INPUT = {"kn",                                    # P9: the key latch (keyboard.now_lines), after the 8 polls
         "kbm",                                   # M8: the M key test after each poll (map_key_lines)
         "sa", "simmv", "simsl", "simsr", "simfw", "simth", "simtlp", "simtlh", "simbk", "simtrp", "simtrh"}


def fam(n):
    if n.startswith("e1m1_"):
        m = re.match(r"e1m1_([a-z]+)", n)
        return "e1m1_" + (m.group(1) if m else "?")
    return re.sub(r"\d+.*$", "", n.split("_")[0] if "_" in n else n)


MM_COLL = re.compile(r"mm_(things|things_out|th\d+_[yn]|hit|plx|ply|stepped|lwdone|relink|same|block_end)$")
LABEL_CAT = {"kb_cell": "Collision and positions",       # knockback's P_CheckPosition (ptloc, seed, the cells)
             "pj_tl": "Collision and positions",         # a projectile's try-move against the monster cells
             # a block-END label: its span is the NEXT block's head (read in the generated program)
             "simcollide_skip": "View",                  # n_drawn, wnt / wnoff, proj.wedge_setup: the frame's view setup
             "lnd_vd_end": "Game logic",                 # P_ChangeSector (mcs) begins
             "bsp_done": "Sprites",                     # the weapon overlay (hwf) begins
             "hff_end": "Status bar and menus",          # the bar's static-column redraw begins
             "cmv_accept": "Game logic",                 # the walk-over triggers (wo) begin
             "simmv_done": "Game logic",                 # the player's knockback momentum test (kbp)
             "kbp_done": "Status bar and menus", # the bar's ammo digits (wpb) begin
             "lv_frozen": "View",                        # vx = viewx: the eye's integer position
             "sa_nfi": "Status bar and menus",   # the world / menu-screen dispatch (mn)
             "lt_bc_end": "Input and move",              # the turn keys (simth) begin
             "pl_out": "BSP walk",                       # the render walk's jump (e1m1_bspcode_walk)
             "p5_bar_skip": "Game logic"}                # the aim window's prologue (aim_sid, aimr) -- the palette
                                                         #   statements after it are split off below


KB_COLL = re.compile(r"^(kb_(cell|ptry|mtry|try|pz)|kq_(pst|pok|pno|msx|mt|m\d|mok|lwd|rl|mfr|mno))$")


def label_cat(n, where):
    if n in LABEL_CAT:
        return LABEL_CAT[n]
    if KB_COLL.match(n):                                 # the knock tries: opening / step / drop-off, the accept,
        return "Collision and positions"                 # the relink (the thrust + P_XYMovement stay game logic)
    f = fam(n)
    if f == "mm":
        return "Collision and positions" if MM_COLL.match(n) else "Game logic"
    return code_cat(f, where)


def code_cat(f, where):
    if f in WALLS:
        return "Walls"
    if f in SPRITES or (f == "mon" and where == "main"):       # main's mon_rot_leaf: the sprite's rotation
        return "Sprites"
    if f in BSP:
        return "BSP walk"
    if f in WEAPON:
        return "Sprites"
    if f in SCREEN:
        return "Status bar and menus"
    if f in COLL:
        return "Collision and positions"
    if f in VIEW:
        return "View"
    if f in INPUT:
        return "Input and move"
    return "Game logic"


# ---------------------------------------------------------------------------------------------- data labels
FLOOR_COLS = re.compile(r"col_(floor|ceil|plight|fstart|cexcl|fend|cend|flr|clg)")
# the variables, by their declarations (wall_renderer / config / selfreset / collision)
WALL_CELLS = {"stepcol",                                   # the step bank (_lines_step_bank): risers and lips
              "sfslot", "sfflag",                          # per-column step-face pieces (config STEP_SLOT_STRIDE)
              "tsf", "seg", "wnt", "wex", "wey", "wexy", "weyx", "wnoff"}
FLOOR_CELLS = {"pclm", "pval", "cpid", "pmin", "pmax", "vzcbase"}   # per-column plane ids, the plane walk, eye bands
SPRITE_CELLS = {"sprflag", "spslot", "gpslot", "sp", "thvis", "hdfl", "degfl", "ballow", "thfar", "tp", "thing"}
POS_CELLS = {"sshead", "thnext", "thss", "thpos",          # the thing lists (build.THING_PERSIST)
             "ptloc", "ptlocq", "ptlocp", "ptlocdx", "ptlocdy", "ptlock", "ptx", "pty", "ptp", "ptq", "ptss",
             "bdv", "bhv", "btv", "mm"}                     # collision.py's cells, a monster move's cells
VIEW_CELLS = {"vx", "vy", "viewx", "viewy", "viewz", "viewangle", "viewh"}
NAMED_TABLES = ("tantoangle", "viewangletox", "xtoviewangle", "finetangent", "slopediv_recip", "playpal", "sprlt",
                "throwc")


def data_cat(n):
    """a label in the tables / state / banks-head parts: a lookup table, or a variable of one feature"""
    if "---" in n or n.endswith(".dsp") or n.endswith(".res") or re.match(r"[fs]\d+:l\d+:", n):
        return "Sprites" if "sprbkt" in n else "Lookup tables"
    if n.startswith(NAMED_TABLES):
        return "Lookup tables"
    if n.startswith("col_"):
        return "Floors and ceilings" if FLOOR_COLS.match(n) else "Walls"
    f = re.sub(r"\d+.*$", "", n.split("_")[0] if "_" in n else n)
    for cells, cat in ((WALL_CELLS, "Walls"), (FLOOR_CELLS, "Floors and ceilings"), (SPRITE_CELLS, "Sprites"),
                       (POS_CELLS, "Collision and positions"), (VIEW_CELLS, "View")):
        if f in cells or n in cells:
            return cat
    return "Game logic"                                          # the game's state cells (player, monsters, ...)


# ---------------------------------------------------------------------------------------------- the interval table
END_RE = re.compile(r"(_end__|_end|_done|_out|_skip)$")
ELEM = re.compile(r"[fs]\d+:l\d+:")
by_addr = collections.defaultdict(list)
for a_, n_ in rows:
    by_addr[a_].append(n_)


def pick(names, top_only):
    """the label that NAMES the block starting at a word: an explicit override first, else the first label that does
    not END a block (a `*_end__` / `_done` / `_skip` shares its word with the next block's own label)"""
    c = [n for n in names if not top_only or (not ELEM.match(n) and "---" not in n)]
    for n in c:
        if n in LABEL_CAT:
            return n
    ne = [n for n in c if not END_RE.search(n)]
    return (ne or c or [None])[0]


cat_at = {}                                                      # word -> the category of the interval starting there
for a_, names_ in by_addr.items():
    if TABLES0 <= a_ < HOT or STATE0 <= a_ < SPRB0:               # data parts: every label (tables are macro-internal)
        cat_at[a_] = data_cat(pick(names_, False))
    elif HOT <= a_ < STATE0:
        n_ = pick(names_, True)
        if n_ is not None:
            cat_at[a_] = label_cat(n_, "main" if a_ < SEGC else ("segc" if a_ < WALK0 else "walk"))
# the banks part's tail [vql_blk__, m1_reset) is three runs, each of its own label families: the vq loaders and the
# floor's tables; the baked pages (the menu frames, the map page and its producers); the boot screen (init_screen and
# the palettes, run once from the entry)
FLOOR_TAIL, PAGES, BOOT = {"vpb", "vql", "vqh", "yslope", "zlight", "distscale"}, {"mf", "menu", "am"}, {"io"}
tail = [(a_, fam(n_)) for a_, n_ in rows if VQL0 <= a_ < RESET0 and not ELEM.match(n_) and "---" not in n_]
PAGES0, BOOT0 = min(a_ for a_, f_ in tail if f_ in PAGES), byname["io_boot"]
assert VQL0 < PAGES0 < BOOT0 < RESET0, (VQL0, PAGES0, BOOT0, RESET0)
assert all(f_ in (FLOOR_TAIL if a_ < PAGES0 else PAGES if a_ < BOOT0 else BOOT) for a_, f_ in tail), tail
print("banks tail: vq loaders + floor tables [%d, %d), baked pages [%d, %d), boot screen [%d, %d)"
      % (VQL0, PAGES0, PAGES0, BOOT0, BOOT0, RESET0))
# the data parts' first words keep their LABEL's category (finer); every other border overrides a label there
cat_at.setdefault(TABLES0, "Lookup tables")
cat_at.setdefault(STATE0, "Game logic")
for a, c in [(0, "Lookup tables"),                               # the stl runtime: pointer routines + their tables
             (CODE0, "Startup"),                                 # the entry part: the window icon, once
             (HOT, "Input and move"),                            # kb.poll x8 + the key decode (profx's first object)
             (SPRB0, "Sprites"),                                 # the sprite bank: the pictures
             (VPB0, "Floors and ceilings"), (VQL0, "Floors and ceilings"),   # the bands-as-code, their vq loaders
             (PAGES0, "Status bar and menus"), (BOOT0, "Startup"),
             (RESET0, "Frame reset"), (W0, "WFLIP"), (W1, "GAP"), (POOL0, "Lookup tables")]:
    cat_at[a] = c
# a leaf's base filler (`rep(N, i) stl.fj 0, 0` right before its label) is that leaf's layout, not the preceding
# label's
FILL = re.compile(r"^\s*rep\((\d+), *i\) +stl\.fj 0, *0\s*$")
for part_f in ("e1m1_02_main.fj", "e1m1_04_walk.fj"):
    prev = None
    with open(Path(GEN) / part_f, encoding="utf-8") as fh:
        for line in fh:
            if prev is not None:
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_.]*):", line)
                if m and m.group(1) in byname:
                    lab = m.group(1); a = byname[lab]
                    cat_at[a - 2 * prev] = cat_at.get(a, label_cat(lab, "main" if a < SEGC else "walk"))
                    print("filler: %d words before %s -> %s" % (2 * prev, lab, cat_at[a - 2 * prev]))
                prev = None
            m = FILL.match(line)
            if m:
                prev = int(m.group(1))
# inside the column renderer the ops are walls, floors/ceilings and sprites -- split by the innermost source macro:
# sprite fragments + sprite rows -> Sprites; band walks, plane-id derivation, sky ids, the stacked floor/ceiling
# splices' own control -> Floors and ceilings; step faces, wall texture, the rest -> Walls. The two-sided leaf's
# claim scan ([xa_use_pmin, ret): pclm attribution) -> Floors and ceilings.
SPR_M = {"stream.frag_runs", "stream.frag_derive", "stream.frag_runs_win", "frame.lines_spr_load", "frame.lines_spr_step",
         "frame.lines_spr_seed"}
FLR_M = {"stream.half_walk_code", "frame.lines_pid_ids_f", "frame.lines_pid_ids_c", "frame.lines_col_plane_ids",
         "frame.lines_sky_ceil_ids", "frame.lines_sky_base", "frame.lines_plane_ptr", "frame.lines_ditto_plane"}
WAL_M = {"stream.steps_face", "w1rpat.walk", "w1rpat.walk_win"}
SPL_M = {"stream.steps_splice_f", "stream.steps_splice_c"}


def macro_of(p):
    m = re.match(r"(?:[fs]\d+:l\d+:)?(?:rep\d+:)*([\w.]+)", p)
    return m.group(1) if m else p


def column_cat(n):
    for m in reversed([macro_of(p) for p in n.split("---")]):
        if m in SPR_M:
            return "Sprites"
        if m in FLR_M:
            return "Floors and ceilings"
        if m in WAL_M:
            return "Walls"
        if m in SPL_M:
            return "Floors and ceilings"
    return "Walls"


TS0, P2_0 = byname["seg_pass1_ts_leaf"], byname["seg_pass2_leaf"]
TS1, P2_1 = byname["thing_leaf"], byname["bbgate_leaf"]
ts_lab = {n.split("---")[1]: a for a, n in rows if TS0 <= a < TS1 and len(n.split("---")) == 2}
CLAIM0, CLAIM1 = ts_lab["xa_use_pmin"], ts_lab["ret"]
moved = collections.Counter()
for a, names_ in by_addr.items():
    if TS0 < a < TS1:
        c_ = "Floors and ceilings" if CLAIM0 <= a < CLAIM1 else "Walls"
    elif P2_0 < a < P2_1:
        c_ = column_cat(sorted(names_, key=lambda n: -n.count("---"))[0])
    else:
        continue
    cat_at[a] = c_
    moved[c_] += 1
cat_at[CLAIM1] = "Walls"
print("column renderer: %d interval starts by macro %s; claim scan [%d, %d)" % (sum(moved.values()), dict(moved), CLAIM0, CLAIM1))
pl_line = None
with open(Path(GEN) / "e1m1_02_main.fj", encoding="utf-8") as fh:
    for i_, line in enumerate(fh, 1):
        if line.strip() == "p5_bar_skip:":
            pl_line = i_ + 3
            break
pal_at = re.compile(r"f(\d+):l%d:palidx\.lookup" % pl_line)      # the main file's index follows the build's file list
pal_hits = [(a, m.group(1)) for a, m in ((a, pal_at.match(n)) for a, n in rows) if m]
assert pal_hits and len({f for _, f in pal_hits}) == 1, (pl_line, pal_hits[:4])
pal = [a for a, _ in pal_hits]
cat_at[min(pal)] = "Status bar and menus"            # palidx.lookup + the berserk tests: the palette flash
print("p5_bar_skip: aim prologue [%d, %d) game logic, palette from %d" % (byname["p5_bar_skip"], min(pal), min(pal)))
# thing_leaf's SEEN probe (frame.thing_record_body with seen=1: seen_probe2 .. the leaf's end) is A_Look's monster
# sight, not drawing (src/fj/frame_render.fj)
probes = sorted(a for a, n in rows if n.endswith("---seen_probe2"))
probe = [a for a in probes if byname["thing_leaf"] < a < byname["thing_leaf_b"]]
assert len(probe) == 1, probes
# thing_leaf_b / _bb are built with seen=0: their probe label is EMPTY, right on the next leaf's own label
tops = {a for a, n in rows if not ELEM.match(n) and "---" not in n}
assert all(a in tops for a in probes if a != probe[0]), probes
cat_at[probe[0]] = "Game logic"
assert byname["thing_leaf"] < probe[0] < byname["thing_leaf_b"]
print("seen probe: %d words at %d -> Game logic" % (byname["thing_leaf_b"] - probe[0], probe[0]))
iv = sorted(cat_at.items())
starts = np.array([a for a, _ in iv], dtype=np.int64)
names = np.array([c for _, c in iv])
np.savez(OUT.replace('.json', '_iv.npz'), starts=starts, names=names)   # the address -> category map, for audits
# nothing between VPB0 and W0 may come from a label (the bands, the tail's three runs, the reset: one category each)
assert not ((starts > VPB0) & (starts < W0) & ~np.isin(starts, [VQL0, PAGES0, BOOT0, RESET0])).any()
CATS = sorted({c for c in names if c not in ("WFLIP", "GAP")})
ci = {c: i for i, c in enumerate(CATS)}

own = np.zeros(len(CATS))
ends = np.append(starts[1:], POOL0 + 10 ** 9)
for a, b, c in zip(starts, ends, names):
    if c in ci:
        own[ci[c]] += POOL_STORED if a == POOL0 else (min(b, W1) - a if a < W1 else 0)
assert int(own.sum()) + (W1 - W0) == TOTAL, (own.sum(), W1 - W0, TOTAL)

# ---------------------------------------------------------------------------------------------- the wflip chains
data = np.frombuffer(blob, dtype="<u4")              # read_fjm_raw gave the decompressed data
del blob
opa, opj = [], []
for s0, slen, d0, dlen in segs:
    k = np.arange(0, dlen, 2, dtype=np.int64)
    a = s0 + k
    j = (data[d0 + k + 1].astype(np.int64) + (a + 1) * 32) & 0xFFFFFFFF
    opa.append(a)
    opj.append(j // 32)
opa, opj = np.concatenate(opa), np.concatenate(opj)
in_area = (opa >= W0) & (opa < W1)
r0, nreg = W0 // 2, (W1 - W0) // 2
assert W0 % 2 == 0 and W1 % 2 == 0
nxt = np.full(nreg, -1, dtype=np.int64)
ai, aj = opa[in_area] // 2 - r0, opj[in_area]
ok = (aj >= W0) & (aj < W1)
nxt[ai[ok]] = aj[ok] // 2 - r0
heads = (~in_area) & (opj >= W0) & (opj < W1)
hc = names[np.searchsorted(starts, opa[heads], side="right") - 1]
codes = np.array([ci.get(c, -1) for c in hc], dtype=np.int64)
assert (codes >= 0).all(), collections.Counter(hc[codes < 0].tolist())
pos = opj[heads] // 2 - r0
counts = np.zeros(len(CATS) * nreg, dtype=np.uint32)
cod = codes
while pos.size:
    np.add.at(counts, cod * nreg + pos, 1)
    nx = nxt[pos]
    keep = nx >= 0
    pos, cod = nx[keep], cod[keep]
counts = counts.reshape(len(CATS), nreg).astype(np.float64)
tot = counts.sum(axis=0)
share = (counts[:, tot > 0] / tot[tot > 0]).sum(axis=1) * 2
unreached = (W1 - W0) - share.sum()
print("wflip area %d words: reached by chains %.0f, unreached %.0f" % (W1 - W0, share.sum(), unreached))
total = own + share

# ---------------------------------------------------------------------------------------------- ops
pw, pc = load_sparse(INCL)
pc_full = pc.copy()
pcat = names[np.searchsorted(starts, pw, side="right") - 1]
ops = collections.Counter()
for c, v in zip(pcat.tolist(), pc.tolist()):
    ops[c] += v
cw, cc = load_sparse(CAL)                            # boot + 2 menu frames + its tail: gamespeed's calibration run
# the calibration run's own op count (drive.py's runs.json)
CAL_OPS = json.load(open(CAL.replace(".incl.bin", ".runs.json")))["runs"][0]["ops"]
assert cc.sum() == CAL_OPS, (cc.sum(), CAL_OPS)
ccat = names[np.searchsorted(starts, cw, side="right") - 1]
for c, v in zip(ccat.tolist(), cc.tolist()):
    ops[c] -= 11 * v                                 # the calibration run + each game run's boot and menu frames
STARTUP = int(cc[ccat == "Lookup tables"].sum())     # the calibration run's ops in the runtime's words: a fresh
                                                     # engine charges them there...
_cal = collections.Counter()
for c, v in zip(ccat.tolist(), cc.tolist()):
    _cal[c] += v
print("calibration run by category:", dict(_cal.most_common()))
assert 0 <= STARTUP < 50000, STARTUP                 # a few ops to a few thousand, by the stl's init
print("startup (the runtime words' ops in the calibration run):", STARTUP)
ops["Lookup tables"] += 10 * STARTUP                 # ...and each of the 10 game runs charges them to the input owner
ops["Input and move"] -= 10 * STARTUP                #    the previous run's tail ended on (profx's per-frame log)
assert all(v >= 0 for v in ops.values()), ops
MK = load_marks(INCL.replace(".incl.bin", ".marks.bin"))
desc = {"  of which dsccs seed walks": None, "eye point location (dsc walk)": None, "render walk, all": None}
for fa, fb in PH.frames(MK):
    sp_ = PH.spans(MK, fa, fb)
    for k_ in desc:
        d_ = sp_[k_][1]
        if d_ is not None:
            desc[k_] = d_ if desc[k_] is None else desc[k_] + d_
seed_bsp = int(desc["  of which dsccs seed walks"][18])    # obj 18 = the bspcode walk: pos_leaf + the partitions
eye_bsp = int(desc["eye point location (dsc walk)"][18])
MT0, NZ0 = byname["mt_dist_leaf"], byname["nz_leaf"]
body = int(pc_full[(pw >= byname["thing_pass_leaf"]) & (pw < MT0)].sum())
mt_render = int(desc["render walk, all"][14]) - body        # obj 14 in the render walk = thing pass + thsel + this
assert 0 < mt_render < int(pc_full[(pw >= MT0) & (pw < NZ0)].sum())
for frm, to, v in (("BSP walk", "Collision and positions", seed_bsp), ("BSP walk", "View", eye_bsp),
                   ("Game logic", "Sprites", mt_render)):
    ops[frm] -= v
    ops[to] += v
    print("shared leaf: %d ops (%.1f/frame) %s -> %s" % (v, v / 1000, frm, to))
pc = np.array([sum(ops.values())])
print("size (words, own + chains):")
for c in sorted(CATS, key=lambda c: -total[ci[c]]):
    print("  %-30s %11.0f = own %10d + chains %10.0f   %5.2f%%" % (c, total[ci[c]], own[ci[c]], share[ci[c]],
                                                                  100 * total[ci[c]] / TOTAL))
print("  total %.0f (stored %d)" % (total.sum(), TOTAL))
print("ops (owner-attributed, gamespeed's GAME-ONLY frames: 10 games x 100; per frame):")
for c, v in sorted(ops.items(), key=lambda kv: -kv[1]):
    print("  %-30s %14.1f  %6.2f%%" % (c, v / 1000, 100 * v / pc.sum()))
print("  total %.1f per frame" % (pc.sum() / 1000))
json.dump({"size": {c: [float(own[ci[c]]), float(share[ci[c]])] for c in CATS},
           "ops": {c: v / 1000 for c, v in ops.items()},
           "borders": dict(code_start=CODE0, tables=TABLES0, hot=HOT, segconsts=SEGC, walk=WALK0, state=STATE0,
                           banks=BANKS0, sprite_bank=SPRB0, vpb=VPB0, vql=VQL0, pages=PAGES0, boot=BOOT0,
                           reset=RESET0, wflip=[W0, W1],
                           pool_stored=POOL_STORED, total_stored=TOTAL, pool_tables=POOL_TABLES)},
          open(OUT, "w"), indent=1)