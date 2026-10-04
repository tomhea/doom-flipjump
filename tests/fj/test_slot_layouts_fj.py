"""M7 P1.4 (PR #93's review, R6 / R9) -- the two slot layouts, EXECUTED.

A column's fragments live in `spslot`, a thing's constants in `gpslot`. frame.thing_record_body writes
both; frame.lines_spr_seed / lines_spr_step / lines_spr_load read a column's fragments, and
stream.frag_derive a thing's constants. wall_renderer states the layouts once: SPR_SLOT_STRIDE,
SPR_FRAG_FIELDS, SPR_SLOT_B_BYTE, SPR_THING_SLOT_BYTES, SPR_THING_SLOT_FIELDS, SPR_THING_Y0_BIAS
(four fields since M7 P1.6: the bucket, the rowmap's row). This RUNS the shipped fj and holds every byte and every register to them -- nothing is modelled:

  write  The record's code from its slot allocation (`hex.inc 2, gps_nslot`) to the end of its
         column loop, transplanted VERBATIM from frame.thing_record_body into a harness macro,
         records THINGS (below). Then EVERY byte of the hot block -- pclm through the cell after
         drawn, 6,785 of them -- must be the constants' layout of what was recorded: the bytes the
         layout names hold the fields, drawn its walls, and every other byte is still zero.
  read   From memory laid out by the constants, the real seed (and step) and load give each
         column's fragments, and the real derive each thing's y0, light row and bucket.

Each side is held to the constants ON ITS OWN, so a change made alike on both sides that the
constants do not describe fails too. The expected bytes come from the constants and THINGS alone.

The record's parameters come from the EMITTER'S OUTPUT: wall_renderer run for the game tier (in a
subprocess, on a copy of src/, so an emitter edit runs in the emitter's own scope) on the one-room
map in two rooms -- a lamp alone, which bakes, so both record bodies are emitted (`thing_leaf`, mt 1;
`thing_leaf_b`, mt 0), and 24 things of 15 kinds, 20 of which the runtime lists take -- and each
`frame.thing_record_body` call it emits zipped with the def's own parameter list. The arguments the
range uses must be integers, the same in every call (`agreed_binding`). An emitter that cannot run
is an error, never a refusal.

WHY the rooms' values are every map's is the SCOPE RULE (`scope_rule`, review round 8): each name in
a range argument's expressions is resolved as Python resolves it (symtable) and must be bound where
no map reaches it -- `cfg` (the emitter's parameter, never rebound: a frozen Config, the one the ship
build passes), `deg_flag` (bound once, at the emitter's top level, to an int literal), a module name
bound once at module level (to a constant, by a def whose own names obey the rule, or by an import
from a doomfj module where the same holds) that no `global` statement names, no attribute store in
src/doomfj reaches and no listed reflection could, or a pure builtin. Any other name is refused,
whatever the rooms give it: the emitter's locals -- where every map-derived value lives (the runtime
thing count's widths, the subsector index width, the light tables ...) -- and the record body's own
parameters.

The ENTRY STATE (review round 8): before each record, every register the range names holds a value
with no zero nibble, different per record and register (`hostile`), except its inputs (the THINGS
fields). So trb_tab_idx enters with a shade class of 16 or more in nibbles 2-3, where a class-16+
thing's shade row leaves one (and with more above them), and a clear narrowed to fewer nibbles leaves
garbage. That is stricter
than the build wherever the build happens to leave a register as a narrowed write would want it (a
register only ever set to one address, a nibble nothing writes) -- never looser. The read side
already enters that way where it matters: the load's outputs are preset to 0xAA, so a dropped zero
leaves garbage, and its seed and derive write their pointers and fetched fields whole.

THINGS: four of E1M1's own left clips first, their texture steps from the oracle (`hex.neg n`
negates only the low n nibbles, so a negation narrowed to n nibbles is off by a non-zero multiple of
16^n for every clip, and frac by that times the step: u, frac's bits 16-23, can move only if the
step's low 24 - 4n bits are not all zero -- LEFT_CLIP_MOVES has which clips do); then
columns across the 16, 64 and 1,024-index bounds up to 159, a first column below 0 and a last above
159 (both clamps), slot ids 1..255 across 16, fragments A and B, B refused by `ballow`, both slots
spent, columns a wall hides, a transparent block (its min_b past every bucket), a texture step
that moves the column and its clamp, y0 either side of zero, the record's min_b test (M7 P1.6: a
column is taken iff the thing's bucket >= the block's min_b) either side of the bucket and at it,
and across 16 -- and these operand ranges the shipped sprites reach (review rounds 5-6): a last
texture column past 16 (the shipped bank goes to 62), u past 15, a block past 0x1000, and a left
clip of 300 columns at half a texel a column (frac past five nibbles). What each records, column by column, is RECORDED -- held to the model.

The harness lays its hot block out as the build does: `pad 16384` (the block starts an arm5 window,
16,384 ops, and all of it fits in that one window), then pclm, sfflag, sprflag, sfslot, spslot,
gpslot and drawn in the real order, drawn followed by a zero cell as the build's `wrej: hex.vec 1`
follows it (a column past the right edge reads that cell as its wall) -- the real block holds more
arrays between gpslot and drawn, so the offsets inside the window differ.

What it does NOT cover:
  * the shipped binary's addresses: only the window the narrow arms need is the build's;
  * what the record computes BEFORE its slot allocation -- which things it accepts, their y0, light
    rows and blocks. The column check (scratchpad/gp/probes/sprite/ship_check.py) does not run it
    either: it feeds the oracle's values to this same code. The shipped binary's gates hold it,
    against the oracle, on the frames they play (m2_std_gate and m3_gate byte- and state-exact,
    b0_scenarios pixel-exact);
  * reflection the scope rule does not list, in a module other than wall_renderer.py and the ones
    its names come from (a `setattr` with a computed name, as combat.py uses on its own state);
  * an emitter that builds or rewrites the record call OUTSIDE `_thing_leaf_body`'s f-string,
    depending on the map: the rule reads the f-string, and the rooms emit only their own maps.
    E1M1's own call is the shipped binary's, and its gates hold every pixel it draws.

R9: every mutant in MUTANTS -- one real edit of the fj text, or of the emitter, each: every kind PR
#93's review rounds found, the reviewer's own edits among them as posted -- must make its side fail;
a mutant that does not assemble, or an emitter that does not run, is an error, never a catch. And
every edit in NEUTRAL moves no byte (unreachable filler deleted; an argument rewritten from module
constants) and must still pass: the harness does not fail on where the code happens to land, and
the scope rule does not refuse what cannot follow the map.
"""
import ast
import hashlib
import re
import subprocess
import symtable
import sys
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj

ROOT = Path(__file__).resolve().parents[2]
FJ_NAMES = ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
            "plane_bands.fj", "stream_render.fj")
EMITTER = "wall_renderer.py"
# M7 P4.0: the game tier's OWN config -- the emitter rebinds `cfg = tier_cfg(cfg, tier)` (an 84-row view under the bar)
CFG = wr.tier_cfg(Config(), "game")
VIEW_W = CFG.VIEW_W
STRIDE, B_BYTE = wr.SPR_SLOT_STRIDE, wr.SPR_SLOT_B_BYTE
SLOT_BYTES, BIAS, NSLOTS = wr.SPR_THING_SLOT_BYTES, wr.SPR_THING_Y0_BIAS, wr.SPR_THING_SLOTS
ARM5_WINDOW = 16384                                              # ops: 16^5 bits of 2 * W-bit ops

# (slot id, y0, light row, block base (the thing's region), first column, last column, texture step
#  (16.16), bucket,
#  ballow, sp_dw), recorded in this order: a later record into a column that holds A takes B
#  (if ballow lets it), a third finds both slots spent
THINGS = [# four of E1M1's left clips from the player start (x1, x2, texture step, dw, as the oracle
          # projects them -- PR #93's review, round 7); which of them a narrowed negation moves is
          # LEFT_CLIP_MOVES
          (60, 81, 18, 0x0100, -1, 0, 0x4B808, 20, 1, 13),
          (61, 82, 19, 0x0110, -3, 1, 0x4AD00, 21, 1, 20),
          (62, 83, 20, 0x0120, -2, 1, 0x61860, 22, 1, 20),
          (63, 84, 21, 0x0130, -1, 2, 0x4C8F8, 23, 1, 17),
          (1, -200, 3, 0x0102, 0, 1, 0, 21, 1, 1),                 # y0 below zero, into spent columns
          (15, 0, 30, 0x0201, 15, 17, 0, 23, 1, 1),                # A across the 16-index bound
          (16, 150, 31, 0x0003, 62, 66, 0, 24, 1, 1),              # across the 64-index bound
          (255, -32000, 17, 0x01FF, 158, 159, 0, 23, 1, 1),        # the last slot id
          (17, 7, 5, 0x0100, 0, 0, 0, 25, 1, 1),                   # column 0, spent (its sixth record)
          (40, -1, 9, 0x0004, 15, 16, 0, 24, 1, 1),                # B across the 16-index bound
          (41, 100, 2, 0x0005, 0, 0, 0, 25, 1, 1),                 # column 0, spent (its seventh record)
          (42, 33, 4, 0x0006, 10, 14, 0, 26, 1, 1),                # 12..14 hidden by a wall
          (43, 55, 6, 0x0007, 100, 101, 0, 27, 1, 1),              # a fully transparent block
          (44, 12, 7, 0x0008, 17, 17, 0, 28, 0, 1),                # column 17 holds A, ballow 0: no B
          (45, -5, 8, 0x0009, -3, 2, 0, 29, 1, 1),                 # a first column below 0
          (46, 20, 10, 0x0010, 157, 170, 0, 30, 1, 1),             # a last column above 159
          (47, 60, 11, 0x0020, 30, 37, 0x8000, 31, 1, 3),          # half a texel a column, clamped at 2
          (48, 61, 12, 0x0030, 40, 45, 0x10000, 20, 1, 9),         # a unit texture step
          (49, 62, 13, 0x0040, -2, 3, 0x10000, 21, 1, 8),          # below 0 WITH a step: u 5 at column 3
          # the shipped operand ranges (review round 5): E1M1's sprites reach 62 texture columns, so u
          # and the block index leave the widths where a narrowed op is still exact
          (50, 70, 14, 0x0040, 110, 126, 0x40000, 22, 1, 63),      # u 0..64 by 4, clamped at 62
          (51, 71, 15, 0x0030, 130, 139, 0x50000, 23, 1, 45),      # u 0..45 by 5, clamped at 44
          (52, 72, 16, 0x1007, 140, 141, 0, 24, 1, 1),             # a block past 0x1000 whose low three
                                                                  # nibbles name the transparent 0x0007
          (53, 73, 17, 0x0060, -300, 9, 0x8000, 25, 1, 63),       # a left clip of 300 at half a texel:
                                                                  # frac starts at 0x960000, u clamped at 62
          # the min_b test (M7 P1.6): bucket 16 against min_b 15, 16 (taken), 17, 31 (not), 0 (taken)
          # and past every bucket (not); bucket 15 against min_b 16 -- a one-nibble test takes it
          (54, 64, 22, 0x0A00, 50, 55, 0x10000, 16, 1, 16),
          (55, 65, 23, 0x0B00, 56, 57, 0, 15, 1, 1)]
HIDDEN = {12, 13, 14}
TRANSPARENT = {0x0007}
# what each record records, column by column ("B0 A1": fragment B at column 0, A at column 1; "-":
# nothing) -- held to the model by test_the_things_record_what_RECORDED_says (review round 8: the
# comments had drifted from THINGS)
RECORDED = {60: "A0", 61: "B0 A1", 62: "B1", 63: "A2", 1: "-", 15: "A15-17", 16: "A62-66",
            255: "A158-159", 17: "-", 40: "B15-16", 41: "-", 42: "A10-11", 43: "-", 44: "-", 45: "B2",
            46: "A157 B158-159", 47: "A30-37", 48: "A40-45", 49: "A3", 50: "A110-126", 51: "A130-139",
            52: "A140-141", 53: "B3 A4-9", 54: "A50-51 A54", 55: "-"}
# the left clips whose recorded block moves under `hex.neg n, trb_negx1`, per n: a negation narrowed
# to n nibbles is off by a non-zero multiple of 16^n for EVERY clip, and frac by that times the step,
# so u (frac's bits 16-23) can move only if the step's low 24 - 4n bits are not all zero (review
# round 8) -- held to the model too
LEFT_CLIP_MOVES = {2: {60, 61, 62, 63, 53}, 3: {60, 61, 62, 63}, 4: {60, 62, 63}, 5: {60, 63}}


def _neg_narrowed(x1, n):
    """`hex.neg n` of x1's 32-bit two's complement: the low n nibbles negated, the rest kept"""
    v, m = x1 & 0xFFFFFFFF, 16 ** n - 1
    return (v & ~m & 0xFFFFFFFF) | (-(v & m) & m)


def _columns(x1, x2, istep, sp_dw, base, nibbles=8):
    """the record's column walk for one thing, from THINGS alone: (column, block) per column -- its
    left clip negated as `hex.neg nibbles` does (8: exactly)"""
    dw_max = (sp_dw - 1) & 0xFF
    frac = (_neg_narrowed(x1, nibbles) * istep) & 0xFFFFFFFF if x1 < 0 else 0
    for x in range(max(x1, 0), min(x2, VIEW_W - 1) + 1):
        u = min((frac >> 16) & 0xFF, dw_max)
        yield x, (base + u) & 0xFFFF                       # M7 P1.6: the region + u
        frac = (frac + istep) & 0xFFFFFFFF


NBLOCKS = 1 + max(b for t in THINGS for _, b in _columns(t[4], t[5], t[6], t[9], t[3]))
# each block's header: op 0 (n_first, the derive's), op 1 = min_b (M7 P1.6: the record takes a column
# iff the thing's bucket >= min_b; a transparent column's is past every bucket), the rest zero
MIN_B = {0x0A00: 15, 0x0A01: 16, 0x0A02: 17, 0x0A03: 31, 0x0A04: 0, 0x0A05: 0xFF, 0x0B00: 16}
HEADER = {b: (5 + b % 7, 0xFF if b in TRANSPARENT else MIN_B.get(b, b % 3)) for b in range(NBLOCKS)}
# the read side's columns: (seed column, steps) -- empty, A, A+B, across the index bounds
LOADS = [(0, 0), (1, 0), (2, 0), (3, 0), (10, 0), (12, 0), (15, 0), (16, 0), (17, 0), (31, 0),
         (36, 1), (44, 0), (62, 0), (63, 1), (64, 0), (157, 0), (158, 0), (159, 0), (100, 0), (13, 3),
         (110, 0), (118, 5), (126, 0), (135, 0), (140, 0), (141, 0)]
DERIVE_BLOCK = 0x0102


def _record_all(things=THINGS):
    """sprflag, spslot and gpslot after `things` are recorded -- the constants' layout -- and what
    each record recorded: {slot id: [(column, "A" or "B")]}"""
    sprflag, spslot, gpslot = [0] * VIEW_W, [0] * (VIEW_W * STRIDE), [0] * (NSLOTS * SLOT_BYTES)
    took = {}
    for sid, y0, light, base, x1, x2, istep, bucket, ballow, sp_dw in things:
        yb = (y0 + BIAS) & 0xFFFF
        fields = {"y0 lo": yb & 0xFF, "y0 hi": yb >> 8, "light row": light, "bucket": bucket}
        for i, f in enumerate(wr.SPR_THING_SLOT_FIELDS):
            gpslot[sid * SLOT_BYTES + i] = fields[f]
        took[sid] = []
        for x, blk in _columns(x1, x2, istep, sp_dw, base):
            n = sprflag[x]
            if x in HIDDEN or n == 2 or (n == 1 and not ballow) or bucket < HEADER[blk][1]:
                continue
            frag = {"slot id": sid, "block lo": blk & 0xFF, "block hi": blk >> 8}
            for i, f in enumerate(wr.SPR_FRAG_FIELDS):
                spslot[x * STRIDE + (B_BYTE if n else 0) + i] = frag[f]
            sprflag[x] = n + 1
            took[sid].append((x, "AB"[n]))
    return (sprflag, spslot, gpslot), took


def expected_memory():
    """sprflag, spslot and gpslot after THINGS are recorded -- the constants' layout"""
    return _record_all()[0]


def _runs(took):
    """[(column, fragment)] as RECORDED writes it"""
    out = []
    for x, f in took:
        if out and out[-1][0] == f and out[-1][2] == x - 1:
            out[-1][2] = x
        else:
            out.append([f, x, x])
    return " ".join("%s%d" % (f, a) if a == b else "%s%d-%d" % (f, a, b) for f, a, b in out) or "-"


def expected_reads():
    """what the read side must give: per LOADS column (sprfl, s, sblk lo, hi, sb, sblkb lo, hi),
    then per thing (y0 lo, y0 hi, light row, bucket)"""
    sprflag, spslot, _ = expected_memory()
    out = []
    for x0, k in LOADS:
        x = x0 + k
        a = {f: spslot[x * STRIDE + i] for i, f in enumerate(wr.SPR_FRAG_FIELDS)}
        b = {f: spslot[x * STRIDE + B_BYTE + i] for i, f in enumerate(wr.SPR_FRAG_FIELDS)}
        n = sprflag[x]
        frag_a = [a["slot id"], a["block lo"], a["block hi"]] if n >= 1 else [0, 0, 0]
        frag_b = [b["slot id"], b["block lo"], b["block hi"]] if n == 2 else [0, 0, 0]
        out += [n] + frag_a + frag_b
    for sid, y0, light, base, x1, x2, istep, bucket, *_ in THINGS:
        out += [y0 & 0xFF, (y0 >> 8) & 0xFF, light, bucket]
    return out


def block_arrays(mem):
    """the hot block's arrays in the build's order, with the contents `mem` gives sprflag, spslot and
    gpslot: [(label, cells)]"""
    sprflag, spslot, gpslot = mem
    return [("pclm", [0] * (VIEW_W * CFG.PID_BYTES)), ("sfflag", [0] * VIEW_W), ("sprflag", list(sprflag)),
            ("sfslot", [0] * (VIEW_W * 16 ** CFG.SLOT_SHIFT)), ("spslot", list(spslot)),
            ("gpslot", list(gpslot)), ("drawn", [1 if x in HIDDEN else 0 for x in range(VIEW_W)]),
            ("lay_wrej", [0])]


def expected_block():
    """every byte of the hot block after THINGS are recorded, and where each one is"""
    where, values = [], []
    for label, cells in block_arrays(expected_memory()):
        where += [(label, i) for i in range(len(cells))]
        values += cells
    return where, values


def _code(text):
    return "\n".join(line.split("//")[0] for line in text.splitlines())


GLOBALS = ({d.split(":")[0].strip() for d in wr.hoisted_scratch_decls(CFG)}
           | {"drawn", "pclm", "sfflag", "sprflag", "sfslot", "spslot", "gpslot", "sprbank", "sp_dw",
              "ballow", "hdfl"})


class BindingRefused(Exception):
    """the emitter's output does not give the transplanted range ONE set of values"""


# ---- the scope rule: why the rooms' values are every map's ------------------------------------------
# A range argument is an expression in the emitter's f-string. Each name in it is resolved as Python
# resolves it (symtable), and must be bound where no map reaches it:
#   * `cfg`      -- the emitter's parameter, a frozen Config (the ship build passes Config(), as the rooms
#                   do), rebound only by ONE top-level `cfg = tier_cfg(cfg, tier)` (M7 P4.0: the game
#                   tier's view under the bar) with `tier` a keyword-only parameter never rebound -- a
#                   function of the Config and the tier name alone, which the harness calls itself (CFG);
#   * `deg_flag` -- bound once in the emitter, at its top level, to an int literal;
#   * a MODULE name bound once, at module level, by `NAME = <constant expression>`, by a def whose
#     own names obey this rule, or by an import from a doomfj module where the same holds -- and that
#     no `global` statement names, no attribute store in src/doomfj reaches and no reflection could;
#   * a pure builtin.
# Anything else is refused -- the emitter's locals (every map-derived value lives there: the runtime
# thing count's widths, the subsector index width, the light tables ...), the record body's own
# parameters -- whatever value the rooms give it.
PURE_BUILTINS = frozenset({"sum", "range", "min", "max", "abs", "len", "int", "bool"})
REFLECTION = frozenset({"globals", "vars", "exec", "eval", "compile", "__import__", "setattr", "delattr",
                        "__dict__", "__globals__", "f_globals", "f_locals", "f_back", "modules", "_getframe",
                        "currentframe", "import_module", "__builtins__"})
REFLECTION_MODULES = frozenset({"importlib", "inspect", "ctypes", "gc"})
_EXPR_NODES = (ast.Name, ast.Constant, ast.Attribute, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
               ast.IfExp, ast.Call, ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context)
_CONST_NODES = (ast.Name, ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
                ast.Tuple, ast.Call, ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context)


def _bound_names(node):
    """the names `node` itself binds, however Python spells the binding -- a target, a parameter, an
    import, a def or class, `global` / `nonlocal`, `except ... as`, a `match` capture"""
    if isinstance(node, ast.Name):
        return [] if isinstance(node.ctx, ast.Load) else [node.id]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.alias):
        return [(node.asname or node.name).split(".")[0]]
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
        return [node.name] if node.name else []
    if isinstance(node, ast.MatchMapping):
        return [node.rest] if node.rest else []
    return []


_PARSED = {}


def _parse(text):
    if text not in _PARSED:
        _PARSED[text] = ast.parse(text)
    return _PARSED[text]


class _Module:
    """one doomfj module, parsed for the scope rule"""

    def __init__(self, name, text):
        self.name, self.tree = name, _parse(text)
        self.table = symtable.symtable(text, name + ".py", "exec")
        self.declared = {n for g in ast.walk(self.tree) if isinstance(g, (ast.Global, ast.Nonlocal))
                         for n in g.names}
        for node in ast.walk(self.tree):
            word = (node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute)
                    else None)
            if word in REFLECTION:
                raise BindingRefused("%s.py reaches a namespace by reflection (`%s`)" % (name, word))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # the modules this binds: `import a.b` binds a.b; `from a import b` binds a.b when b
                # is a module (a name in it otherwise -- a doomfj module name either way)
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                else:
                    mods = [node.module or ""] + ["%s.%s" % (node.module, a.name) for a in node.names]
                for m in mods:
                    if m.split(".")[0] in REFLECTION_MODULES or m == "doomfj." + name:
                        raise BindingRefused("%s.py imports %s" % (name, m))
                if any(a.name == "*" for a in node.names):
                    raise BindingRefused("%s.py has a star import" % name)

    def bindings(self, name):
        """the nodes that bind `name` in the module's own scope: not inside a def, lambda or class body
        (their decorators, defaults and bases are the module's)"""
        out, stack = [], list(self.tree.body)
        while stack:
            n = stack.pop()
            if name in _bound_names(n):
                out.append(n)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                stack += n.args.defaults + [d for d in n.args.kw_defaults if d is not None]
                stack += getattr(n, "decorator_list", [])
            elif isinstance(n, ast.ClassDef):
                stack += n.decorator_list + n.bases + [k.value for k in n.keywords]
            else:
                stack += ast.iter_child_nodes(n)
        return out


def _src_modules(emitter_text):
    """every doomfj module, wall_renderer's text being `emitter_text`"""
    mods = {}
    for p in sorted((ROOT / "src" / "doomfj").glob("*.py")):
        text = emitter_text if p.name == EMITTER else p.read_text(encoding="utf-8")
        mods[p.stem] = text
    return mods


class _ScopeRule:
    def __init__(self, emitter_text):
        self.texts, self.parsed, self.accepted = _src_modules(emitter_text), {}, set()

    def module(self, name):
        if name not in self.parsed:
            if name not in self.texts:
                raise BindingRefused("no doomfj module %s" % name)
            self.parsed[name] = _Module(name, self.texts[name])
        return self.parsed[name]

    def name_ok(self, mod, name):
        """`name`, read at `mod`'s module level, cannot follow the map -- or refused"""
        if (mod, name) in self.accepted:
            return
        m = self.module(mod)
        found = m.bindings(name)
        if not found and name in PURE_BUILTINS:
            return
        if len(found) != 1:
            raise BindingRefused("%s.%s is bound %d times at module level" % (mod, name, len(found)))
        if name in m.declared:
            raise BindingRefused("a `global` statement names %s.%s" % (mod, name))
        self.accepted.add((mod, name))
        top = {id(s): s for s in m.tree.body}
        node = found[0]
        stmt = next((s for s in m.tree.body if node is s or node in getattr(s, "targets", ())
                     or node is getattr(s, "target", None)
                     or (isinstance(s, ast.ImportFrom) and node in s.names)), None)
        if stmt is None or id(stmt) not in top:
            raise BindingRefused("%s.%s is not bound by a top-level statement" % (mod, name))
        if isinstance(stmt, ast.ImportFrom):
            if stmt.level or not (stmt.module or "").startswith("doomfj."):
                raise BindingRefused("%s.%s is imported from %s" % (mod, name, stmt.module))
            self.name_ok(stmt.module.split(".", 1)[1], node.name)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            if isinstance(stmt, ast.Assign) and len(stmt.targets) != 1 or stmt.value is None:
                raise BindingRefused("%s.%s is not bound by a plain assignment" % (mod, name))
            self.const_ok(mod, stmt.value)
        elif isinstance(stmt, ast.FunctionDef):
            self.def_ok(mod, stmt)
        else:
            raise BindingRefused("%s.%s is bound by a %s" % (mod, name, type(stmt).__name__))

    def const_ok(self, mod, expr):
        for n in ast.walk(expr):
            if not isinstance(n, _CONST_NODES) or isinstance(n, ast.Constant) and \
                    not isinstance(n.value, (int, bool, str, type(None))):
                raise BindingRefused("%s: a module constant built from a %s" % (mod, type(n).__name__))
            if isinstance(n, ast.Call) and (not isinstance(n.func, ast.Name) or n.keywords):
                raise BindingRefused("%s: a module constant built by a call that is not a name" % mod)
            if isinstance(n, ast.Name):
                self.name_ok(mod, n.id)

    def def_ok(self, mod, fn):
        if fn.decorator_list:
            raise BindingRefused("%s.%s is decorated" % (mod, fn.name))
        for d in fn.args.defaults + [d for d in fn.args.kw_defaults if d is not None]:
            self.const_ok(mod, d)
        tables = [t for t in self.module(mod).table.get_children() if t.get_name() == fn.name]
        if len(tables) != 1:
            raise BindingRefused("%s.%s has %d scopes" % (mod, fn.name, len(tables)))
        stack = tables
        while stack:
            t = stack.pop()
            stack += t.get_children()
            for s in t.get_symbols():
                if s.is_declared_global() or s.is_nonlocal():
                    raise BindingRefused("%s.%s declares %s global or nonlocal" % (mod, fn.name, s.get_name()))
                if s.is_global() and s.is_referenced():
                    self.name_ok(mod, s.get_name())

    def attribute_stores(self):
        """no doomfj module assigns an accepted module name as an attribute (`wr.NAME = ...`)"""
        names = {n for _m, n in self.accepted}
        for mod in self.texts:
            for n in ast.walk(_parse(self.texts[mod])):
                if isinstance(n, ast.Attribute) and n.attr in names and not isinstance(n.ctx, ast.Load):
                    raise BindingRefused("%s.py assigns .%s" % (mod, n.attr))


def _fstring_args(js):
    """a `frame.thing_record_body ...` f-string's arguments, each a list of text and FormattedValue"""
    args, cur = [], []
    for v in js.values:
        if isinstance(v, ast.Constant):
            parts = str(v.value).split(",")
            cur.append(parts[0])
            for p in parts[1:]:
                args.append(cur)
                cur = [p]
        else:
            cur.append(v)
    args.append(cur)
    args[0][0] = args[0][0][len("frame.thing_record_body "):]
    return args


def scope_rule(emitter_text, params, used):
    """refuse unless every name in the arguments of `used` (parameters of `params`, in order) is bound
    where no map reaches it (above)"""
    rule = _ScopeRule(emitter_text)
    wr_mod = rule.module(EMITTER[:-3])
    ewr = [n for n in wr_mod.tree.body if isinstance(n, ast.FunctionDef) and n.name == "emit_wall_renderer"]
    ewr_t = [t for t in wr_mod.table.get_children() if t.get_name() == "emit_wall_renderer"]
    if len(ewr) != 1 or len(ewr_t) != 1:
        raise BindingRefused("emit_wall_renderer is not one top-level def")
    leaf = [n for n in ewr[0].body if isinstance(n, ast.FunctionDef) and n.name == "_thing_leaf_body"]
    leaf_t = [t for t in ewr_t[0].get_children() if t.get_name() == "_thing_leaf_body"]
    if len(leaf) != 1 or len(leaf_t) != 1:
        raise BindingRefused("_thing_leaf_body is not one def in emit_wall_renderer's body")
    calls = [n for n in ast.walk(leaf[0]) if isinstance(n, ast.JoinedStr) and n.values
             and isinstance(n.values[0], ast.Constant)
             and str(n.values[0].value).startswith("frame.thing_record_body ")]
    if len(calls) != 1:
        raise BindingRefused("%d record calls in _thing_leaf_body" % len(calls))
    args = _fstring_args(calls[0])
    if len(args) != len(params):
        raise BindingRefused("the record call has %d arguments for %d parameters" % (len(args), len(params)))
    in_ewr = list(ast.walk(ewr[0]))
    for p in used:
        for piece in args[params.index(p)]:
            if isinstance(piece, str):
                if not re.fullmatch(r"[\s0-9]*", piece):
                    raise BindingRefused("%s's text %r" % (p, piece))
                continue
            if piece.conversion != -1 or piece.format_spec is not None:
                raise BindingRefused("%s is formatted" % p)
            for n in ast.walk(piece.value):
                if not isinstance(n, _EXPR_NODES):
                    raise BindingRefused("%s uses a %s" % (p, type(n).__name__))
                if isinstance(n, ast.Attribute) and not (isinstance(n.value, ast.Name) and n.value.id == "cfg"
                                                         and not n.attr.startswith("_")):
                    raise BindingRefused("%s reads an attribute that is not cfg's" % p)
                if isinstance(n, ast.Call) and (not isinstance(n.func, ast.Name) or n.keywords):
                    raise BindingRefused("%s calls something that is not a name" % p)
                if not isinstance(n, ast.Name):
                    continue
                s = leaf_t[0].lookup(n.id)
                if n.id in ("cfg", "deg_flag") and s.is_free():
                    # every binding of it anywhere in the emitter, nested scopes included
                    binds = [b for b in in_ewr if n.id in _bound_names(b)]
                    if n.id == "cfg":
                        sig = ewr[0].args
                        own = [a for a in sig.posonlyargs + sig.args + sig.kwonlyargs if a.arg == "cfg"]
                        # M7 P4.0: the one rebinding allowed -- `cfg = tier_cfg(cfg, tier)` at the top level
                        tiered = [st.targets[0] for st in ewr[0].body
                                  if isinstance(st, ast.Assign) and len(st.targets) == 1
                                  and isinstance(st.targets[0], ast.Name) and st.targets[0].id == "cfg"
                                  and ast.dump(st.value) == ast.dump(ast.parse("tier_cfg(cfg, tier)",
                                                                               mode="eval").body)]
                        tier_own = [a for a in sig.kwonlyargs if a.arg == "tier"]
                        tier_binds = [b for b in in_ewr if "tier" in _bound_names(b)]
                        if len(own) != 1 or binds != own + tiered[:1] or len(tiered) > 1 \
                                or (tiered and (len(tier_own) != 1 or tier_binds != tier_own)):
                            raise BindingRefused("cfg is bound in the emitter other than as its parameter")
                        if not Config.__dataclass_params__.frozen:
                            raise BindingRefused("Config is not frozen")
                    else:
                        one = [st for st in ewr[0].body if isinstance(st, ast.Assign) and len(st.targets) == 1
                               and binds and st.targets[0] is binds[0]]
                        if len(binds) != 1 or not one or not isinstance(one[0].value, ast.Constant) \
                                or type(one[0].value.value) is not int:
                            raise BindingRefused("deg_flag is not bound once, at the emitter's top level, "
                                                 "to an int literal")
                elif s.is_global() and not s.is_declared_global():
                    rule.name_ok(EMITTER[:-3], n.id)
                else:
                    raise BindingRefused("%s reads %s, %s in the record body's scope" % (
                        p, n.id, "the emitter's local" if s.is_free() else "a local or parameter"))
    rule.attribute_stores()
    return sorted(rule.accepted)


# the rooms the emitter is run on: a lamp alone bakes (the game tier then emits both record bodies,
# n_thc 1, nltic 1); 24 things led by monsters take the room's one leaf into the runtime lists (n_thc 2,
# nltic 2 -- the index widths that follow the runtime thing count)
# M7 P3.1: every kind is one the model knows (gamedata.THING_TYPES) -- the game tier's emitter builds a World for the
# monsters now, and E1M1 has no baron (3003) or lost soul (3006): the room's two of them became a shotgun and a clip
_KINDS = [3004, 9, 3001, 3002, 58, 2001, 2007, 2028, 2011, 2012, 2014, 2015, 2018, 2019, 2035]
ROOMS = [[(64, 64, 2028)],
         [(16 + (i % 12) * 20, 16 + (i // 12) * 20, _KINDS[i % len(_KINDS)]) for i in range(24)]]
EMIT = r"""
import ast
import sys
sys.path.insert(0, sys.argv[1])
from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.wad import Thing, WadFile
for i, room in enumerate(ast.literal_eval(sys.argv[5])):
    mw = WadFile.from_path(sys.argv[2])
    base = mw.things
    mw.things = lambda name, base=base, room=room: base(name) + [Thing(x, y, 0, t, 7) for x, y, t in room]
    parts = wr.emit_wall_renderer(mw, "MAP01", Config(), tier="game", asset_wad=WadFile.from_path(sys.argv[3]),
                                  sprite_wad=WadFile.from_path(sys.argv[4]), return_parts=True)
    label = None
    for _n, text in parts:
        for line in text.splitlines():
            line = line.strip()
            if line.endswith(":") and line.startswith("thing_leaf"):
                label = line[:-1]
            if line.startswith("frame.thing_record_body "):
                print("%d\t%s\t%s" % (i, label, line))
"""


_EMITTED = {}


def emitted_calls(emitter_text):
    """every (room, leaf label, `frame.thing_record_body ...` line) the game tier's emitter gives on
    ROOMS -- run in a subprocess on a copy of src/ whose wall_renderer.py is `emitter_text`. One text
    gives one output, so a test process emits each text once (every fj mutant shares the head's)."""
    if emitter_text not in _EMITTED:
        _EMITTED[emitter_text] = tuple(_emit(emitter_text))
    return list(_EMITTED[emitter_text])


def _emit(emitter_text):
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        shutil.copytree(ROOT / "src", Path(t) / "src")
        (Path(t) / "src" / "doomfj" / EMITTER).write_text(emitter_text, encoding="utf-8")
        r = subprocess.run([sys.executable, "-c", EMIT, str(Path(t) / "src"),
                            str(ROOT / "tests/fixtures/square_room.wad"),
                            str(ROOT / "tests/fixtures/freedoom_assets.wad"),
                            str(ROOT / "assets/freedoom1.wad"), repr(ROOMS)],
                           capture_output=True, text=True, timeout=600)
    if r.returncode:           # an environment (or a broken mutant), never a refusal: never a catch
        raise RuntimeError("the emitter did not run: %s" % r.stderr.strip()[-300:])
    return [tuple(line.split("\t", 2)) for line in r.stdout.splitlines() if line.count("\t") == 2]


def def_params(frame_text):
    """thing_record_body's own parameter list (frame_render.fj)"""
    m = re.search(r"^    def thing_record_body (.*?)^\s*@", frame_text, re.M | re.S)
    return [p.strip() for p in m.group(1).replace("\\", " ").split(",")]


def record_bindings(frame_text, emitter_text):
    """every binding of thing_record_body's parameters the game tier's EMITTED program gives: the
    def's own parameter list zipped with each emitted call's arguments. Both record bodies must be
    emitted (the lamp-alone room gives `thing_leaf` and `thing_leaf_b`)."""
    params = def_params(frame_text)
    calls = emitted_calls(emitter_text)
    if {lab for _r, lab, _c in calls} != {"thing_leaf", "thing_leaf_b"}:
        raise BindingRefused("the game tier emitted record bodies %s, not thing_leaf and thing_leaf_b"
                             % sorted({lab for _r, lab, _c in calls}))
    out = []
    for _room, _label, call in calls:
        args = [x.strip() for x in call[len("frame.thing_record_body "):].split(",")]
        if len(args) != len(params):
            raise BindingRefused("%d arguments for %d parameters" % (len(args), len(params)))
        out.append(dict(zip(params, args)))
    return out


# M7 P3: the record's rep()-gated FEATURE switches (P3.1's mirror: `mir`, and `mirf` / `miru`, the cells it names;
# P3.2a's seen mark: `seen`, `sa`, `sflag`, `one`) are bound PER LEAF -- a monster-capable leaf of the animated tier
# turns them on -- so no module constant binds them and no one integer is in every emitted call. This harness binds
# them OFF, where they expand no op (`feature_lines_are_gated` checks that every line naming one is a rep() line), so
# it tests the layout the build writes; their ON path is issue #109's F1.
FEATURE_OFF = {"mir": "0", "mirf": "0", "miru": "0", "seen": "0", "sa": "0", "sflag": "0", "one": "0"}


def feature_lines_are_gated(code):
    """every code line naming a FEATURE_OFF parameter is a `rep(<switch>, ...)` line -- so OFF expands no op"""
    bad = [ln.strip() for ln in _code(code).splitlines()
           if any(re.search(r"\b%s\b" % f, ln) for f in FEATURE_OFF) and not re.match(r"\s*rep\(", ln)]
    if bad:
        raise BindingRefused("a feature switch outside rep(): %s" % bad[:2])


def agreed_binding(frame_text, emitter_text, used):
    """the parameters of `used` and the ONE integer each takes in every emitted call -- refused
    unless the scope rule holds first (the FEATURE_OFF switches: bound off, above)"""
    params = [p for p in def_params(frame_text) if p in used]
    checked = [p for p in params if p not in FEATURE_OFF]
    scope_rule(emitter_text, def_params(frame_text), checked)
    bindings = record_bindings(frame_text, emitter_text)
    bindings = [dict(b, **{f: v for f, v in FEATURE_OFF.items() if f in params}) for b in bindings]
    for p in checked:
        seen = {b[p] for b in bindings}
        if len(seen) != 1:
            raise BindingRefused("the emitted calls bind %s to %s" % (p, sorted(seen)))
        if not re.fullmatch(r"-?\d+", bindings[0][p]):
            raise BindingRefused("the emitted calls bind %s to %r, not an integer" % (p, bindings[0][p]))
    return params, bindings[0]


def transplant(frame_text, emitter_text):
    """the record's code from the slot allocation to the end of its column loop, VERBATIM, as a
    harness macro -- and the call that binds its parameters as the shipped build does"""
    body = frame_text[frame_text.index("    def thing_record_body"):]
    code = body[body.index("        hex.inc 2, gps_nslot"):body.index("      set_tstop:")]
    labels = re.findall(r"^\s*(\w+):\s*(?://.*)?$", code, re.M)
    words = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", _code(code)))
    feature_lines_are_gated(code)
    params, bound = agreed_binding(frame_text, emitter_text, words)
    macro = ("ns frame {\n    def lay_rec %s @ %s < %s {\n%s      ret:\n    }\n}\n"
             % (", ".join(params), ", ".join(labels + ["ret"]), ", ".join(sorted(words & GLOBALS)), code))
    return (macro, "frame.lay_rec " + ", ".join(bound[p] for p in params),
            sorted(r for r in words & set(WIDTHS) if r not in INPUTS))


# ---- the entry state ------------------------------------------------------------------------------------
# the range's inputs: what the build computes before it, set per record from THINGS
INPUTS = {"gps_nslot", "trb_y0", "trb_shade_row", "trb_tx1", "trb_tx2", "trb_tistep", "trb_blk_const",
          "trb_bucket", "ballow", "sp_dw"}
WIDTHS = {d.split(":")[0].strip(): d.split("hex.vec", 1)[1].strip()
          for d in wr.hoisted_scratch_decls(CFG) if "hex.vec" in d}


def hostile(i, reg):
    """record i's entry value for `reg`, as `hex.set`: no zero nibble in its width, and different per
    record and register -- a clear narrowed to fewer nibbles leaves garbage, and no one value is the
    one a wrong clear happens to undo"""
    n = W // 4 if WIDTHS[reg] == "w/4" else int(WIDTHS[reg])
    assert n <= 32, (reg, n)
    h = hashlib.sha256(("%d:%s" % (i, reg)).encode()).digest()
    return "    hex.set %d, %s, 0x%s" % (n, reg, "".join("%x" % (1 + b % 15) for b in h[:n]))


def _cells(values):
    return [";%d * dw" % v for v in values]


def hot_block(mem):
    """laid out as the build lays its hot block (wall_renderer: `pad 16384`, then pclm, sfflag,
    sprflag, sfslot, spslot, gpslot ... drawn, wrej)"""
    block = []
    for label, cells in block_arrays(mem):
        block += [label + ":"] + _cells(cells)
    assert sum(not c.endswith(":") for c in block) <= ARM5_WINDOW, "the block outgrew one arm5 window"
    return ["pad %d" % ARM5_WINDOW] + block


def bank():
    """the bank, NBLOCKS blocks of SPR_BLOCK_STRIDE cells: a used block's header, zeros elsewhere
    (runs of zero cells as `rep(n, i) stl.fj 0, 0`, the zero cell the layout freezes use)"""
    out, zeros = list(wr.sprite_bank_header()), 0
    used = {blk for t in THINGS for _, blk in _columns(t[4], t[5], t[6], t[9], t[3])} | {DERIVE_BLOCK}
    for b in range(NBLOCKS):
        if b not in used:
            zeros += wr.SPR_BLOCK_STRIDE
            continue
        if zeros:
            out.append("rep(%d, i) stl.fj 0, 0" % zeros)
        out += _cells(HEADER[b])
        zeros = wr.SPR_BLOCK_STRIDE - 2
    if zeros:
        out.append("rep(%d, i) stl.fj 0, 0" % zeros)
    return out


def emit(reg, nbytes):
    return ["    byte.emit %s" % (reg if i == 0 else "%s + %d*dw" % (reg, 2 * i)) for i in range(nbytes)]


DUMP = """def lay_dump arr, n @ loop, done < lay_p, lay_n, lay_v {
    hex.set w/4, lay_p, arr
    hex.set 4, lay_n, n
  loop:
    hex.read_byte_and_inc lay_v, lay_p
    byte.emit lay_v
    hex.dec 4, lay_n
    hex.if0 4, lay_n, done
    ;loop
  done:
}
"""
REGS = ["lay_p: hex.vec w/4", "lay_n: hex.vec 4", "lay_v: hex.vec 2", "lay_x: hex.vec 8",
        "lay_arm: hex.vec 2", "sp_dw: hex.vec 2", "ballow: hex.vec 1", "hdfl: hex.vec 1",
        "ld_sprfl: hex.vec 2", "ld_s: hex.vec 2", "ld_sblk: hex.vec 4", "ld_sb: hex.vec 2",
        "ld_sblkb: hex.vec 4", "dv_s: hex.vec 2", "dv_sblk: hex.vec 4", "dv_ybase: hex.vec 4",
        "dv_top: hex.vec 4", "dv_sy1: hex.vec 4", "dv_sy2: hex.vec 4", "dv_smidx: hex.vec 4",
        "dv_ptr: hex.vec w/4", "dv_ridx: hex.vec 4"]
HEAD = ["stl.startup_and_init_all", generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)]


def write_program(frame_text, emitter_text):
    macro, call, scratch = transplant(frame_text, emitter_text)
    main = list(HEAD)
    for i, (sid, y0, light, base, x1, x2, istep, bucket, ballow, sp_dw) in enumerate(THINGS):
        main += [hostile(i, r) for r in scratch]                     # the entry state (above)
        main += ["    hex.set 2, gps_nslot, %d" % (sid - 1),       # the record takes the next slot id
                 "    hex.set 8, trb_y0, %d" % (y0 & 0xFFFFFFFF), "    hex.set 2, trb_shade_row, %d" % light,
                 "    hex.set 8, trb_tx1, %d" % (x1 & 0xFFFFFFFF), "    hex.set 8, trb_tx2, %d" % (x2 & 0xFFFFFFFF),
                 "    hex.set 8, trb_tistep, %d" % istep, "    hex.set w/4, trb_blk_const, %d" % base,
                 # the bucket as sprbkt.lookup leaves it: [its height hb][bucket] (M7 P1.6)
                 "    hex.set 4, trb_bucket, %d" % ((0xA0 + bucket) << 8 | bucket),
                 "    hex.set 1, ballow, %d" % ballow,
                 "    hex.set 2, sp_dw, %d" % sp_dw, "    " + call]
    main += ["    lay_dump pclm, %d" % len(expected_block()[1]), "    stl.loop"]
    zero = ([0] * VIEW_W, [0] * (VIEW_W * STRIDE), [0] * (NSLOTS * SLOT_BYTES))
    return "\n".join([macro, DUMP] + main + REGS + [wr.hoisted_scratch_fj(CFG)] + hot_block(zero) + bank()) + "\n"


def read_program():
    main = list(HEAD)
    for x0, k in LOADS:
        main += ["    hex.set 8, lay_x, %d" % x0, "    frame.lines_spr_seed lay_x"]
        main += ["    frame.lines_spr_step"] * k
        main += ["    hex.read_byte lay_arm, p2_spfp",             # a hot-block arm, as the leaf's reads leave it
                 "    hex.set 1, p2_sdirty, 1",                    # an empty column zeroes the outputs
                 "    hex.set 2, ld_s, 0xAA", "    hex.set 4, ld_sblk, 0xAAAA",
                 "    hex.set 2, ld_sb, 0xAA", "    hex.set 4, ld_sblkb, 0xAAAA",
                 "    frame.lines_spr_load ld_sprfl, ld_s, ld_sblk, ld_sb, ld_sblkb"]
        main += emit("ld_sprfl", 1) + emit("ld_s", 1) + emit("ld_sblk", 2) + emit("ld_sb", 1) + emit("ld_sblkb", 2)
    for sid, *_ in THINGS:
        main += ["    hex.set 2, gps_cur_s, 0",                   # a new thing: the derive fetches its slot
                 "    hex.set 2, dv_s, %d" % sid, "    hex.set 4, dv_sblk, %d" % DERIVE_BLOCK,
                 "    stream.frag_derive dv_s, dv_sblk, dv_ybase, dv_top, dv_sy1, dv_sy2, dv_smidx, dv_ptr, dv_ridx"]
        main += emit("gps_y0", 2) + emit("gps_lr", 1) + emit("gps_b", 1)
    main.append("    stl.loop")
    return "\n".join([DUMP] + main + REGS + [wr.hoisted_scratch_fj(CFG), wr.sprite_rowmap_fj(CFG)]
                     + hot_block(expected_memory()) + bank()) + "\n"


RUNNER = r"""
import sys
import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
io = FixedIO(b"")
term = fj.run(sys.argv[1], io_device=io, print_time=False, print_termination=False)
print(str(term.termination_cause))
print(io.get_output(allow_incomplete_output=True).hex())
"""


def source(name):
    return (ROOT / ("src/doomfj" if name == EMITTER else "src/fj") / name).read_text(encoding="utf-8")


def run(tmp, name, program, texts=None, timeout=600):
    """assemble `program` against the fj sources -- `texts` replaces some ({file: text}) -- and run
    it in a subprocess with a timeout (fj.run has no op limit, and a broken layout may never end):
    the output bytes, or None if it did not end on its closing loop"""
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    files = []
    for f in FJ_NAMES:
        p = tmp / f
        p.write_text((texts or {}).get(f) or source(f), encoding="utf-8")
        files.append(p.resolve())
    prog = tmp / (name + ".fj")
    prog.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *files, prog.resolve()], out, memory_width=W, print_time=False)
    try:
        r = subprocess.run([sys.executable, "-c", RUNNER, str(out)], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    cause, _, data = r.stdout.strip().partition("\n")
    return list(bytes.fromhex(data.strip())) if "loop" in cause.lower() else None


def run_side(tmp, side, texts=None, timeout=600):
    """(got, want) for one side, the fj and the emitter's call as `texts` has them; a binding the
    emitter's text does not give in ONE way is `got` = the refusal, never a run"""
    texts = texts or {}
    if side == "write":
        try:
            prog = write_program(texts.get("frame_render.fj") or source("frame_render.fj"),
                                 texts.get(EMITTER) or source(EMITTER))
        except BindingRefused as e:
            return "binding refused: %s" % e, expected_block()[1]
        return run(tmp, "w", prog, texts, timeout), expected_block()[1]
    return run(tmp, "r", read_program(), texts, timeout), expected_reads()


def test_the_record_writes_every_byte_where_the_constants_say(tmp_path):
    got, want = run_side(tmp_path, "write")
    assert isinstance(got, list), got or "the record's program did not end on its loop"
    where = expected_block()[0]
    bad = [(where[i], g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert len(got) == len(want) and not bad, (len(got), len(want), bad[:10])
    # not vacuous: every kind of record happened (the expectation is what `got` just equalled)
    sprflag, spslot, _ = expected_memory()
    assert sprflag[0] == 2 and sprflag[15] == 2 and sprflag[64] == 1 and sprflag[159] == 2
    assert sprflag[17] == 1, "ballow 0 must leave column 17 at A only"
    assert all(sprflag[x] == 0 for x in HIDDEN | {100, 101})
    # half a texel a column: u moves every second column, so the block does at 32, 34, 36 (clamped)
    assert spslot[32 * STRIDE + 1] != spslot[30 * STRIDE + 1], "the texture step moved no block"
    assert spslot[44 * STRIDE + 1] != spslot[40 * STRIDE + 1], "the unit step moved no block"
    # ... and each shipped range was reached, by the thing that is there for it
    def block(x):
        return spslot[x * STRIDE + 1] | spslot[x * STRIDE + 2] << 8
    assert block(126) == 0x40 + 62, "u clamped at 62"
    assert block(139) == 0x30 + 44, "u clamped at 44"
    assert block(140) == 0x1007, "a block past 0x1000"
    assert block(4) == 0x60 + 62, "the 300-column left clip: frac past five nibbles, u 62"
    # the min_b test (thing 54, bucket 16): min_b 15 and 16 taken, 17 and 31 not, 0 taken, 0xFF not;
    # thing 55 (bucket 15) against min_b 16: not
    assert [sprflag[x] for x in range(50, 58)] == [1, 1, 0, 0, 1, 0, 0, 0], "the min_b test"
    for x1, x2, istep, dw, base, col in ((-1, 0, 0x4B808, 13, 0x0100, 0), (-3, 1, 0x4AD00, 20, 0x0110, 1),
                                        (-1, 2, 0x4C8F8, 17, 0x0130, 2)):
        want_blk = dict(_columns(x1, x2, istep, dw, base))[col]
        assert block(col) == want_blk != base, "an E1M1 left clip's u at column %d" % col


def test_the_things_record_what_RECORDED_says():
    """review round 8: what each record records, and which left clips a narrowed negation moves, are
    the model's -- not a comment's"""
    took = _record_all()[1]
    assert {sid: _runs(t) for sid, t in took.items()} == RECORDED
    for n, want in LEFT_CLIP_MOVES.items():
        moved = {sid for sid, _y0, _lt, base, x1, x2, st, _bk, _ba, dw in THINGS if x1 < 0
                 and any(dict(_columns(x1, x2, st, dw, base, n))[x] != dict(_columns(x1, x2, st, dw, base))[x]
                         for x, _f in took[sid])}
        assert moved == want, (n, sorted(moved), sorted(want))


def test_the_load_and_the_derive_read_every_field_where_the_constants_say(tmp_path):
    got, want = run_side(tmp_path, "read")
    assert got is not None, "the read side's program did not end on its loop"
    assert got == want, [(i, g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w][:10]


# (label, side, file, old, new): one real edit each -- of the fj text, or of the emitter's call
_W = "\n        "
FR, SR = "frame_render.fj", "stream_render.fj"
MUTANTS = [
    ("slot B's byte", "write", FR, "hex.set w/4, trb_slot_ofs, 8", "hex.set w/4, trb_slot_ofs, 9"),
    ("the record's bias", "write", FR, "hex.add_constant 8, gps_yb8, 32768", "hex.add_constant 8, gps_yb8, 32767"),
    ("the record's fragment order", "write", FR,
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw",
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk + 2*dw" + _W + "frame.write_byte5 trb_tbl_p, trb_blk"),
    ("the record's fragment: an increment dropped", "write", FR,
     "hex.write_byte_and_inc trb_tbl_p, gps_s_rec", "hex.write_byte trb_tbl_p, gps_s_rec"),
    ("the record's fragment: a step inserted", "write", FR,
     "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw", "hex.ptr_inc trb_tbl_p" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw"),
    ("the record's slot: an increment dropped", "write", FR,
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw", "hex.write_byte gps_ptr, gps_yb8 + 2*dw"),
    ("the record's slot: a step inserted", "write", FR,
     "hex.write_byte_and_inc gps_ptr, trb_shade_row", "hex.ptr_inc gps_ptr" + _W + "hex.write_byte_and_inc gps_ptr, trb_shade_row"),
    ("the record's slot: a prearmed write", "write", FR,
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw", "frame.write_byte_and_inc_prearmed gps_ptr, gps_yb8 + 2*dw"),
    ("the slot offset never added", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.zero w/4, trb_slot_ofs"),
    ("the slot offset bumped", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.inc 1, trb_slot_ofs" + _W + "hex.add w/4, trb_tab_idx, trb_slot_ofs"),
    ("slot A falls into slot B", "write", FR, "hex.set 2, trb_slot_flag, 1" + _W + ";slot_done", "hex.set 2, trb_slot_flag, 1"),
    ("the column index one nibble wide", "write", FR, "hex.mov 2, trb_tab_idx, trb_col_x", "hex.mov 1, trb_tab_idx, trb_col_x"),
    ("the column index shifted back", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.shr_hex w/4, 1, trb_tab_idx" + _W + "hex.add w/4, trb_tab_idx, trb_slot_ofs"),
    ("the record's column stride", "write", FR,
     "rep(slotstride/16, k) hex.shl_hex w/4, 1, trb_tab_idx", "rep(slotstride/8, k) hex.shl_hex w/4, 1, trb_tab_idx"),
    ("the record's index bound", "write", FR,
     "frame.ptr_index6 trb_tbl_p, trb_tbl_b, trb_tab_idx" + _W + "// P2-5", "frame.ptr_index4 trb_tbl_p, trb_tbl_b, trb_tab_idx" + _W + "// P2-5"),
    ("the slot id one nibble wide", "write", FR, "hex.mov 2, gps_sidx, gps_s_rec", "hex.mov 1, gps_sidx, gps_s_rec"),
    ("the slot index written through r + dw", "write", FR,
     "hex.shl_bit w/4, gps_sidx" + _W + "hex.shl_bit w/4, gps_sidx", "hex.shl_bit w/4, gps_sidx" + _W + "hex.inc 1, gps_sidx + dw" + _W + "hex.shl_bit w/4, gps_sidx"),
    # the review's round-3 edits, exactly as posted
    ("r3: the record's first slot write prearmed", "write", FR,
     "hex.write_byte_and_inc gps_ptr, gps_yb8" + _W, "frame.write_byte_and_inc_prearmed gps_ptr, gps_yb8" + _W),
    ("r3: the slot index bumped through r + dw", "write", FR,
     "hex.set w/4, gps_sbase, gpslot" + _W + "frame.ptr_index gps_ptr", "hex.inc 1, gps_sidx + dw" + _W + "hex.set w/4, gps_sbase, gpslot" + _W + "frame.ptr_index gps_ptr"),
    ("r3: a one-nibble shift after the slot offset", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.add w/4, trb_tab_idx, trb_slot_ofs" + _W + "hex.shr_hex 1, 1, trb_tab_idx"),
    ("r3: slot A's branch taken to slot B", "write", FR, "hex.if0 2, trb_sprflag_v, slot_a", "hex.if0 2, trb_sprflag_v, slot_b"),
    ("r3: the record's column shift two nibbles wide", "write", FR,
     "rep(slotstride/16, k) hex.shl_hex w/4, 1, trb_tab_idx", "rep(slotstride/16, k) hex.shl_hex 2, 1, trb_tab_idx"),
    ("r3: the record's block-lo write prearmed", "write", FR,
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk" + _W, "frame.write_byte_and_inc_prearmed trb_tbl_p, trb_blk" + _W),
    ("r3: the seed's column shift two nibbles wide", "read", FR, "hex.shl_hex w/4, 1, sidx ", "hex.shl_hex 2, 1, sidx "),
    # the review's round-4 edits
    ("r4: B allowed whatever ballow says", "write", FR,
     "rep(deg, k) hex.if0 1, ballow, col_next", "rep(deg, k) hex.if0 1, ballow, slot_a"),
    ("r4: the right-edge clamp never fires", "write", FR,
     "hex.scmp 8, trb_tx2, trb_cbound, x2_done, x2_done, x2_clamp", "hex.scmp 8, trb_tx2, trb_cbound, x2_done, x2_done, x2_done"),
    ("r4: the clamp one column wide", "write", FR, "        hex.dec 8, trb_cbound" + "\n", ""),
    ("r4: the def's hdb and slotstride swapped", "write", FR,
     "viewwc, viewh, ds, hdb, slotstride, ttwice,", "viewwc, viewh, ds, slotstride, hdb, ttwice,"),
    ("r4: the emitter passes twice the slot stride", "write", EMITTER,
     "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE}, ", "{sprite_hd_bucket(cfg)}, {2 * SPR_SLOT_STRIDE}, "),
    # M7 P4.0: the one rebinding of cfg the rule allows -- any other is refused
    ("P4: cfg rebound to a fixed tier", "write", EMITTER,
     "    cfg = tier_cfg(cfg, tier) ", "    cfg = tier_cfg(cfg, 'game') "),
    ("P4: cfg rebound twice", "write", EMITTER,
     "    cfg = tier_cfg(cfg, tier) ", "    cfg = tier_cfg(cfg, tier); cfg = tier_cfg(cfg, tier) "),
    ("P4: tier rebound before the rebinding", "write", EMITTER,
     "    cfg = tier_cfg(cfg, tier) ", "    tier = 'game'; cfg = tier_cfg(cfg, tier) "),
    # the review's round-5 edits
    ("r5: deg_flag computed per tier", "write", EMITTER,
     "    deg_flag = 1 ", "    deg_flag = 1 if not standalone else 0 "),
    ("r5: the baked leaf's deg 0", "write", EMITTER, "{deg_flag}, {DEG_SOFT_SCENERY}", "{deg_flag if mt else 0}, {DEG_SOFT_SCENERY}"),
    ("r5: the texture column one nibble wide", "write", FR,
     "hex.mov 2, trb_u, trb_frac_u + 4*dw", "hex.mov 1, trb_u, trb_frac_u + 4*dw"),
    ("r5: the last texture column one nibble wide", "write", FR,
     "hex.mov 2, trb_dw_max, sp_dw", "hex.mov 1, trb_dw_max, sp_dw"),
    ("r5: the texture column clamp one nibble wide", "write", FR,
     "hex.cmp 2, trb_u, trb_dw_max, col_check, col_check, u_clamp", "hex.cmp 1, trb_u, trb_dw_max, col_check, col_check, u_clamp"),
    ("r5: blk_addr places three nibbles", "write", FR,
     "hex.mov 4, gps_boff + 3*dw, blk", "hex.mov 3, gps_boff + 3*dw, blk"),
    # the review's round-6 edits
    ("r6: deg 0 for the standalone tier, after the literal", "write", EMITTER,
     "    deg_flag = 1                                # 25M-CAP: load-adaptive degradation package\n",
     "    deg_flag = 1                                # 25M-CAP: load-adaptive degradation package\n"
     "    if standalone: deg_flag = 0\n"),
    ("r6: the record body's own deg default", "write", EMITTER,
     "    def _thing_leaf_body(label, mt):", "    def _thing_leaf_body(label, mt, deg_flag=0):"),
    ("r6: the record body's own slot-stride default", "write", EMITTER,
     "    def _thing_leaf_body(label, mt):", "    def _thing_leaf_body(label, mt, SPR_SLOT_STRIDE=32):"),
    # M7 P1.6: the bucket in the slot, the region, the min_b test
    ("P1.6: the light row written where the bucket goes", "write", FR,
     "hex.write_byte gps_ptr, trb_bucket", "hex.write_byte gps_ptr, trb_shade_row"),
    ("P1.6: the light row's write without its increment", "write", FR,
     "hex.write_byte_and_inc gps_ptr, trb_shade_row", "hex.write_byte gps_ptr, trb_shade_row"),
    ("P1.6: the region added two nibbles wide", "write", FR,
     "hex.add w/4, trb_blk, trb_blk_const", "hex.add 2, trb_blk, trb_blk_const"),
    ("P1.6: the min_b test one nibble wide", "write", FR,
     "hex.cmp 2, trb_bucket, trb_run_last, col_next, do_store, do_store",
     "hex.cmp 1, trb_bucket, trb_run_last, col_next, do_store, do_store"),
    ("P1.6: the min_b test three nibbles wide", "write", FR,
     "hex.cmp 2, trb_bucket, trb_run_last, col_next, do_store, do_store",
     "hex.cmp 3, trb_bucket, trb_run_last, col_next, do_store, do_store"),
    ("P1.6: the min_b test skips at equality", "write", FR,
     "hex.cmp 2, trb_bucket, trb_run_last, col_next, do_store, do_store",
     "hex.cmp 2, trb_bucket, trb_run_last, col_next, col_next, do_store"),
    ("P1.6: the min_b test inverted", "write", FR,
     "hex.cmp 2, trb_bucket, trb_run_last, col_next, do_store, do_store",
     "hex.cmp 2, trb_bucket, trb_run_last, do_store, do_store, col_next"),
    ("P1.6: the derive's bucket read without the light row's increment", "read", SR,
     "hex.read_byte_and_inc gps_lr, ptr", "hex.read_byte gps_lr, ptr"),
    ("r6: the left clip's negation two nibbles wide", "write", FR,
     "hex.neg 8, trb_negx1", "hex.neg 2, trb_negx1"),
    ("r6: the left clip's product five nibbles wide", "write", FR,
     "hex.mul_lo 8, trb_frac_u, trb_negx1, trb_tistep", "hex.mul_lo 5, trb_frac_u, trb_negx1, trb_tistep"),
    # the review's round-7 edits
    ("r7: the left clip's negation three nibbles wide", "write", FR, "hex.neg 8, trb_negx1", "hex.neg 3, trb_negx1"),
    ("r7: the left clip's negation four nibbles wide", "write", FR, "hex.neg 8, trb_negx1", "hex.neg 4, trb_negx1"),
    ("r7: the left clip's negation five nibbles wide", "write", FR, "hex.neg 8, trb_negx1", "hex.neg 5, trb_negx1"),
    ("r7: the slot stride follows the runtime thing count", "write", EMITTER,
     "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE}, ", "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE * _MT_NTH}, "),
    # the review's round-8 edits, and the scope rule's other doors
    ("r8: the slot stride follows the subsector index width", "write", EMITTER,
     "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE}, ", "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE * _MT_NSSN}, "),
    ("r8: the slot stride follows the light tables", "write", EMITTER,
     "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE}, ", "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE * len(_MT_LTB)}, "),
    ("r8: the column index cleared three nibbles wide", "write", FR,
     "hex.set w/4, trb_tab_idx, 0", "hex.set 3, trb_tab_idx, 0"),
    ("the slot stride rebound through globals()", "write", EMITTER,
     "    _MT_NSSN = _index_nibbles(max(1, _MT_NSS))\n",
     "    _MT_NSSN = _index_nibbles(max(1, _MT_NSS))\n    globals()['SPR_SLOT_STRIDE'] = 16 * _MT_NSSN\n"),
    ("the slot stride rebound through the emitter's own module", "write", EMITTER,
     "    _MT_NSSN = _index_nibbles(max(1, _MT_NSS))\n",
     "    _MT_NSSN = _index_nibbles(max(1, _MT_NSS))\n    from doomfj import wall_renderer as _self\n"
     "    _self.SPR_SLOT_STRIDE = 16 * _MT_NSSN\n"),
    ("the slot stride rebound by a global statement", "write", EMITTER,
     "    _MT_NSSN = _index_nibbles(max(1, _MT_NSS))\n",
     "    _MT_NSSN = _index_nibbles(max(1, _MT_NSS))\n\n    def _rebind(n):\n        global SPR_SLOT_STRIDE\n"
     "        SPR_SLOT_STRIDE = 16 * n\n    _rebind(_MT_NSSN)\n"),
    # the read side
    ("the load's skip to B", "read", FR, "hex.ptr_add spslot_p, 5", "hex.ptr_add spslot_p, 4"),
    ("the load: an increment dropped", "read", FR,
     "frame.read0_byte_and_inc sblk + 2*dw, spslot_p", "frame.read_byte5 sblk + 2*dw, spslot_p"),
    ("the load: a step inserted", "read", FR,
     "frame.read0_byte_and_inc sblkb, spslot_p", "hex.ptr_inc spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p"),
    ("the load: a narrow-arm read", "read", FR, "frame.read0_byte_and_inc s, spslot_p", "frame.read3_and_inc s, spslot_p"),
    ("the load's field order", "read", FR,
     "frame.read0_byte_and_inc sblkb, spslot_p" + _W + "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p",
     "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p"),
    ("the seed's column stride", "read", FR, "hex.shl_hex w/4, 1, sidx ", "hex.shl_hex w/4, 2, sidx "),
    ("the seed's index bound", "read", FR, "frame.ptr_index5 p2_sspp, bteam, sidx", "frame.ptr_index4 p2_sspp, bteam, sidx"),
    ("the seed's column one nibble wide", "read", FR,
     "hex.mov 2, sidx, x1" + _W + "hex.shl_hex w/4, 1, sidx ", "hex.mov 1, sidx, x1" + _W + "hex.shl_hex w/4, 1, sidx "),
    ("the step's column stride", "read", FR, "hex.ptr_add p2_sspp, 16", "hex.ptr_add p2_sspp, 8"),
    ("the derive's bias", "read", SR, "hex.sub_constant 4, gps_y0, 32768", "hex.sub_constant 4, gps_y0, 16384"),
    ("the derive: an increment dropped", "read", SR, "hex.read_byte_and_inc gps_y0 + 2*dw, ptr", "hex.read_byte gps_y0 + 2*dw, ptr"),
    ("the derive: a step inserted", "read", SR, "hex.read_byte_and_inc gps_lr, ptr", "hex.ptr_inc ptr" + _W + "hex.read_byte_and_inc gps_lr, ptr"),
    ("the derive's field order", "read", SR,
     "hex.read_byte_and_inc gps_y0, ptr" + _W + "hex.read_byte_and_inc gps_y0 + 2*dw, ptr",
     "hex.read_byte_and_inc gps_y0 + 2*dw, ptr" + _W + "hex.read_byte_and_inc gps_y0, ptr"),
    ("the derive's slot id one nibble wide", "read", SR, "hex.mov 2, gps_sidx, s", "hex.mov 1, gps_sidx, s"),
]
# edits that move NO byte must still PASS -- unreachable filler, each a layout freeze: the harness
# anchors its hot block, so its verdict does not depend on where the code lands (review round 4); and
# an argument rewritten from module constants to the same value: the scope rule refuses only what
# could follow the map (review round 8)
NEUTRAL = [
    ("the record's layout freeze deleted", "write", FR, "        rep(703, i) stl.fj 0, 0\n", ""),
    ("the load's layout freeze deleted", "read", FR, "        rep(980, i) stl.fj 0, 0\n", ""),
    ("the slot stride written from module constants", "write", EMITTER,
     "{sprite_hd_bucket(cfg)}, {SPR_SLOT_STRIDE}, ", "{sprite_hd_bucket(cfg)}, {SPR_THING_SLOTS // SPR_SLOT_STRIDE}, "),
]


def _mutate(name, old, new):
    text = source(name)
    assert text.count(old) == 1, "the edit's site is not in %s exactly once: %r" % (name, old)
    return {name: text.replace(old, new)}


@pytest.mark.parametrize("label, side, name, old, new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_a_mutated_layout_fails(tmp_path, label, side, name, old, new):
    """R9: each mutant edits the real text once -- and the side it moves must no longer hold"""
    got, want = run_side(tmp_path, side, _mutate(name, old, new), timeout=120)
    assert got != want, "%s: the layout still holds -- the test has no teeth here" % label


@pytest.mark.parametrize("label, side, name, old, new", NEUTRAL, ids=[m[0] for m in NEUTRAL])
def test_an_edit_that_moves_no_byte_still_passes(tmp_path, label, side, name, old, new):
    got, want = run_side(tmp_path, side, _mutate(name, old, new))
    assert got == want, "%s: the harness failed an edit that moves no byte" % label


def test_an_emitter_that_cannot_run_is_an_error_not_a_refusal():
    """review round 7: a refusal counts as a caught mutant, so an emitter that does not RUN (an
    environment without the art, a mutant that breaks it) must never become one"""
    with pytest.raises(RuntimeError):
        emitted_calls(source(EMITTER) + "\nraise SystemExit(3)\n")
