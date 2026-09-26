"""S6 -- the fj micro-probe HARNESS: price one fj fragment, exactly, in the ship build's placement.

A probe is a tiny standalone fj program on flipjump-151's stl at w=32. Nothing of the doom program
is built and the game binary is never run.

WHAT ONE NUMBER MEANS. `measure()` returns the EXECUTED ops of the probe's BODY per call:

    per_call = [(ON, HI) - (ON, LO)  -  (OFF, HI) + (OFF, LO)] / (HI - LO)

  * ON / OFF are two assemblies of the SAME text that differ in ONE jump target: `_mgo: ;_bon`
    runs the body, `_mgo: ;_boff` jumps over it. The body stays in the image either way, so the
    layout, every address, every table count and therefore every pool pin are identical -- the
    harness ASSERTS that the two label tables are equal (a moved label would contaminate the delta).
  * LO / HI are loop counts, poked into the `_mlim` cell of the SAME image before the run, so the
    image is assembled once per arm. HI - LO = 256, so a body indexed by the counter's low byte
    sees every index value exactly once inside the delta.
  * The loop harness (a `hex.cmp 8`, a `hex.inc 8`, two jumps) and any per-iteration `pre` lines
    (loading a sample point, advancing an entity index) run in BOTH arms and cancel exactly.

PLACEMENT. The probe's code sits in a segment at bit address PLACE = 0x09A53C40, inside blocked27's
own code region (simcollide_skip 0x4D6F000 .. e1m1_bspcode_pos_leaf 0x8BE6A00 .. viewx 0xF4CE740)
and with popcount 11 like the game's hot code (~10-11 set bits). A tiny program's natural address
is small and low-popcount, and every address-sized wflip (call/return flips, un-pooled tables)
would read CHEAPER than in the game. The stl's own tables sit at low addresses in both.

TABLE POOL. mode "plain" assembles like flipjump 1.5.1 without a pool. mode "pool" runs the ship
build's two-pass BlockPool with the ship knobs (docs/ship-gate.md 1b: --pool-base 0x60000000
--span-bits 0x9fffffe0 --merge-aliases --spread 2 --spread-min-count 256 --max-slot-ops 512
--pin-broken --width-buckets; --pin-state-cells only concerns the M1 restore set, which a probe
does not have) and the ship's SAFE_TABLE_MACROS, imported from scratchpad/12m/build_blocked.py so
the list cannot drift. mode "pool+" adds the probe's own `extra_safe` macros to the list (what a
table would cost IF it were declared SAFE). A probe's groups are SMALL (few sites per source
word), so its pinned indices are narrow; the game's shared stl words (hundreds of sites) pay wider
indices. That is the known direction of the probe-vs-game gap; the `calib` probes measure it
against the plan's in-game MEASURED primitives.

CONTROLS (`python scratchpad/gp/probes/s6/fjprobe.py --selftest`, R9):
  K0  a probe with its body REMOVED (the RNG probe's full scaffolding) measures exactly 0.
  K1  ten chained `stl.fj 0, next` ops (stl: "Complexity: 1") measure exactly 10. (Ten `stl.skip`
      in a row measure 5 -- skip jumps OVER the next op -- which is how this control was first
      written wrong and caught by its own FAIL.)
  K2  `stl.output_char` (stl: "Complexity: 8") measures exactly 8, and its output is checked.
  K3  (info only) `stl.startup_and_init_all`: the stl documents "Complexity: ~7000 (7010 for w=64,
      6890 for w=16)". Measured: that is its SPACE, it EXECUTES one op, and the space is 8,654 ops
      at w=32 on this stl -- a stale doc, so it is printed, never used as a control.
  L1  the on/off layout-identity assert FIRES on a probe whose OFF arm deletes its body.
  V1  a verifier rejects a probe whose D4 table has one entry mutated.
  V2  a verifier rejects a stub table whose stub 5 reads entity 6's cell.
  E1  flat vs paged engine storage give the identical op count.
"""
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for _q in (ROOT / "src", ROOT / "scratchpad" / "12m", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

import flipjump as fj                                                     # noqa: E402
import flipjump.assembler.assembler as _asm                               # noqa: E402
from flipjump.assembler.preprocessor import BlockPool                     # noqa: E402
from flipjump.fjm import fjm_reader                                       # noqa: E402
from flipjump.interpreter import _fjcore                                  # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402

from build_blocked import SAFE_TABLE_MACROS                               # noqa: E402

W = 32
DW = 2 * W
VAL = 6                     # a hex cell's jump word holds value * dw = value << 6
PLACE = 0x09A53C40          # bit address of the probe segment (see the docstring)
LO, HI = 16, 16 + 256
FLAT = 1 << 20              # engine flat window in words; the rest pages (op counts identical, E1)
SHIP = dict(pool_base=0x60000000, span_bits=0x9fffffe0, spread=2, spread_min_count=256,
            max_slot_ops=512)
MODES = ("plain", "pool")


# ---------------------------------------------------------------------------------------------
# a probe
# ---------------------------------------------------------------------------------------------
@dataclass
class Probe:
    name: str
    body: List[str]                                   # the lines being priced
    pre: List[str] = field(default_factory=list)      # every iteration, both arms (cancels)
    setup: List[str] = field(default_factory=list)    # once, before the loop
    tables: List[str] = field(default_factory=list)   # self-skipping code (D4 inits, stub tables)
    blob: List[str] = field(default_factory=list)     # called code, placed after the loop's end
    data: List[str] = field(default_factory=list)     # cell declarations
    prelude: List[str] = field(default_factory=list)  # macro/ns definitions (no code)
    files: List[Path] = field(default_factory=list)   # extra .fj sources (doom's), before the probe
    verify: List[str] = field(default_factory=list)   # after the body, in the VERIFY build only
    verify_tail: List[str] = field(default_factory=list)  # after the loop, VERIFY build only
    expected: Optional[Callable[[int], bytes]] = None     # output of the VERIFY build for n iters
    mem_check: Optional[Callable[["Mem", int], Tuple[bool, str]]] = None
    extra_safe: Tuple[str, ...] = ()                  # macros "pool+" declares SAFE
    note: str = ""
    vbody: Optional[List[str]] = None                 # replaces `body` in the VERIFY build

    def program(self, body_on: bool, verify: bool = False, drop_body_when_off: bool = False) -> str:
        body = list(self.vbody if (verify and self.vbody is not None) else self.body)
        body += list(self.verify) if verify else []
        if drop_body_when_off and not body_on:
            body = []                                  # L1's negative control only
        lines = list(self.prelude) + [
            "stl.startup_and_init_all",
            ";_gp_seg",
            "segment %s" % hex(PLACE),
            "_gp_seg:",
            *self.tables,
            *self.setup,
            "_mloop:",
            "    hex.cmp 8, _mcnt, _mlim, _mgo, _mdone, _mdone",
            "_mgo:",
            *["    " + ln for ln in self.pre],
            "    ;%s" % ("_bon" if body_on else "_boff"),
            "_bon:",
            *["    " + ln for ln in body],
            "_boff:",
            "    hex.inc 8, _mcnt",
            "    ;_mloop",
            "_mdone:",
            *(["    " + ln for ln in self.verify_tail] if verify else []),
            "    stl.loop",
            *self.blob,
            *self.data,
            "_mcnt: hex.vec 8",
            "_mlim: hex.vec 8",
        ]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------
# assembling (plain, or with the ship's two-pass BlockPool)
# ---------------------------------------------------------------------------------------------
@dataclass
class Build:
    fjm: Path
    labels: Dict[str, int]
    mode: str
    stats: Dict[str, object]
    pins: Dict[int, int] = field(default_factory=dict)


def _assemble_spy(files, out, pool=None):
    grabbed: Dict[str, int] = {}
    orig = _asm.labels_resolve

    def spy(ops, labels, memory_width, fjm_writer, **kw):
        grabbed.update({k: int(v) for k, v in labels.items() if ":" not in k})
        return orig(ops, labels, memory_width, fjm_writer, **kw)

    _asm.labels_resolve = spy
    pins: Dict[int, int] = {}
    orig_rp = _asm.resolve_pinned

    def rp(pinned_exprs, labels, reserved_below=1024, exclude=None):
        o, c = orig_rp(pinned_exprs, labels, reserved_below, exclude)
        pins.update(o)
        return o, c

    _asm.resolve_pinned = rp
    try:
        kw = dict(memory_width=W, print_time=False, lzma_fast=True)
        if pool is not None:
            kw["table_pool"] = pool
        fj.assemble([Path(f).resolve() for f in files], out, **kw)
    finally:
        _asm.labels_resolve = orig
        _asm.resolve_pinned = orig_rp
    return grabbed, pins


def assemble(text: str, mode: str, files: Sequence[Path] = (), extra_safe: Sequence[str] = (),
             tag: str = "p") -> Build:
    tmp = Path(tempfile.mkdtemp(prefix="gpprobe_"))
    src = tmp / (tag + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp / (tag + ".fjm")
    allf = list(files) + [src]
    if mode == "plain":
        labels, _ = _assemble_spy(allf, out)
        return Build(out, labels, mode, {})
    allow = frozenset(SAFE_TABLE_MACROS) | (frozenset(extra_safe) if mode == "pool+" else frozenset())
    wants = (lambda macro_name, prefix: macro_name.name in allow)
    counting = BlockPool(W, SHIP["pool_base"], span_bits=SHIP["span_bits"], spread=SHIP["spread"],
                         spread_min_count=SHIP["spread_min_count"],
                         max_slot_ops=SHIP["max_slot_ops"], wants=wants)
    counting.pin_exclude = lambda address, labels: False
    seen, _ = _assemble_spy(allf, tmp / (tag + ".count.fjm"), pool=counting)
    counts, widths, hist = counting.counts, counting.widths, counting.width_hist
    alias = counting.canonical_alias(seen)                  # --merge-aliases, as build_blocked
    if alias:
        mc, mw, mh = {}, {}, {}
        for g, n in counts.items():
            c = alias.get(g, g)
            mc[c] = mc.get(c, 0) + n
            mw[c] = max(mw.get(c, 0), widths.get(g, 16))
        for g, h in hist.items():
            into = mh.setdefault(alias.get(g, g), {})
            for wdt, n in h.items():
                into[wdt] = into.get(wdt, 0) + n
        counts, widths, hist = mc, mw, mh
    pool = BlockPool(W, SHIP["pool_base"], counts=counts, widths=widths,
                     span_bits=SHIP["span_bits"], alias=alias, spread=SHIP["spread"],
                     spread_min_count=SHIP["spread_min_count"], max_slot_ops=SHIP["max_slot_ops"],
                     pin_broken=True, width_hist=hist, width_buckets=True, wants=wants)
    # No cell of any probe is BOTH pointer-read and an exact_xor source (pointer-read cells are raw
    # `;v*dw` data or byte arrays), so nothing needs vetoing -- but the assembler requires the
    # declaration once any pointer read expands (RAW_READERS).
    pool.pin_exclude = lambda address, labels: False
    labels, pins = _assemble_spy(allf, out, pool=pool)
    stats = dict(groups=len(counts), tables=sum(counts.values()), allocated=pool.allocated,
                 declined=pool.declined, pinned=len(pins),
                 broken=len(getattr(pool, "broken_groups", ())))
    return Build(out, labels, mode, stats, pins)


# ---------------------------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------------------------
class Mem:
    """Reads cells back after a run. A hex cell's value is bits VAL..VAL+3 of its jump word; a
    pinned cell rests at base + value*dw with the base aligned far above those bits."""

    def __init__(self, core, labels):
        self.core, self.labels = core, labels

    def word(self, name, cell=0):
        return self.core.get_word(self.labels[name] // W + 2 * cell + 1)

    def hexv(self, name, n, offset=0):
        return sum(((self.word(name, offset + i) >> VAL) & 0xF) << (4 * i) for i in range(n))

    def byte_cell(self, name, cell=0):
        return (self.word(name, cell) >> VAL) & 0xFF


class Image:
    def __init__(self, build: Build, flat=FLAT):
        self.build, self.flat = build, flat
        r = fjm_reader.Reader(build.fjm)
        self.segments = [(s.segment_start, s.segment_length) for s in r.memory_segments]
        self.runs: List[Tuple[int, List[int]]] = []
        start, nxt, vals = None, 0, []
        for a in sorted(r.memory):
            if start is None or a != nxt:
                if start is not None:
                    self.runs.append((start, vals))
                start, vals = a, []
            vals.append(r.memory[a])
            nxt = a + 1
        if start is not None:
            self.runs.append((start, vals))

    def run(self, pokes: Dict[str, Tuple[int, int]] = None, want_output=False):
        core = _fjcore.Memory(W, flat_max_words=self.flat)
        for s, n in self.segments:
            core.add_segment(s, n)
        for s, vals in self.runs:
            core.set_words(s, vals)
        for name, (ncells, value) in (pokes or {}).items():
            base = self.build.labels[name] // W
            for i in range(ncells):
                wd = base + 2 * i + 1
                core.set_words(wd, [core.get_word(wd) ^ (((value >> (4 * i)) & 0xF) << VAL)])
        bits: List[int] = []
        _c, ops, _e, _l, _p = core.run(lambda: 0, (bits.append if want_output else (lambda b: None)),
                                        IOReadOnEOF, last_ops_length=0)
        out = bytes(sum(bits[i + k] << k for k in range(8)) for i in range(0, len(bits) - 7, 8))
        return ops, out, Mem(core, self.build.labels)


def _limit(n):
    return {"_mlim": (8, n)}


# ---------------------------------------------------------------------------------------------
# measuring and verifying
# ---------------------------------------------------------------------------------------------
class LayoutMoved(Exception):
    pass


@dataclass
class Result:
    name: str
    mode: str
    per_call: float
    ok: Optional[bool]
    why: str
    stats: Dict[str, object]


def measure(p: Probe, mode: str, drop_body_when_off=False) -> Tuple[float, Dict[str, object]]:
    on = assemble(p.program(True), mode, p.files, p.extra_safe, "on")
    off = assemble(p.program(False, drop_body_when_off=drop_body_when_off), mode, p.files,
                   p.extra_safe, "off")
    moved = {k for k in on.labels if k in off.labels and on.labels[k] != off.labels[k]}
    moved |= set(on.labels) ^ set(off.labels)
    if moved:
        raise LayoutMoved("%s/%s: %d labels differ between the ON and OFF arms, e.g. %s"
                          % (p.name, mode, len(moved), sorted(moved)[:3]))
    ops = {}
    for tag, b in (("on", on), ("off", off)):
        img = Image(b)
        for n in (LO, HI):
            ops[tag, n] = img.run(_limit(n))[0]
    per = ((ops["on", HI] - ops["on", LO]) - (ops["off", HI] - ops["off", LO])) / (HI - LO)
    return per, on.stats


def verify(p: Probe, mode: str, n: int = 64) -> Tuple[Optional[bool], str]:
    if p.expected is None and p.mem_check is None:
        return None, "no verifier"
    b = assemble(p.program(True, verify=True), mode, p.files, p.extra_safe, "v")
    _ops, out, mem = Image(b).run(_limit(n), want_output=p.expected is not None)
    if p.expected is not None:
        want = p.expected(n)
        if out != want:
            k = next((i for i in range(min(len(out), len(want))) if out[i] != want[i]),
                     min(len(out), len(want)))
            return False, "output differs at byte %d of %d/%d: got %s want %s" % (
                k, len(out), len(want), out[k:k + 4].hex(), want[k:k + 4].hex())
    if p.mem_check is not None:
        ok, why = p.mem_check(mem, n)
        if not ok:
            return False, why
    return True, "%d iterations checked" % n


def price(p: Probe, modes=MODES, check=True) -> List[Result]:
    res = []
    for m in modes:
        per, stats = measure(p, m)
        ok, why = verify(p, m) if check else (None, "not verified")
        res.append(Result(p.name, m, per, ok, why, stats))
    return res


# ---------------------------------------------------------------------------------------------
# the controls
# ---------------------------------------------------------------------------------------------
def selftest() -> int:
    import probes as P                                     # the probe definitions
    ok = True

    def say(tag, good, text):
        nonlocal ok
        ok &= bool(good)
        print("  %-3s %-4s %s" % (tag, "ok" if good else "FAIL", text))

    print("fjprobe selftest -- MEASURED by this run "
          "(python scratchpad/gp/probes/s6/fjprobe.py --selftest)")
    rng = P.rng_probes()[0]
    empty = Probe("K0:" + rng.name, body=[], pre=rng.pre, setup=rng.setup, tables=rng.tables,
                  blob=rng.blob, data=rng.data, prelude=rng.prelude)
    for m in MODES:
        v, _ = measure(empty, m)
        say("K0", v == 0, "%s: the RNG probe with its body removed = %s ops/call (want exactly 0)"
            % (m, v))
    chain = []
    for i in range(10):
        chain += ["stl.fj 0, _k1_%d" % i, "_k1_%d:" % i]
    skip = Probe("K1", body=chain)
    for m in MODES:
        v, _ = measure(skip, m)
        say("K1", v == 10, "%s: 10 chained stl.fj = %s ops/call (stl: Complexity 1 each; want 10)"
            % (m, v))
    oc = Probe("K2", body=["stl.output_char 0x5a"], expected=lambda n: b"\x5a" * n)
    for m in MODES:
        v, _ = measure(oc, m)
        good, why = verify(oc, m, n=40)
        say("K2", v == 8 and good, "%s: stl.output_char = %s ops/call (stl: Complexity 8), output %s"
            % (m, v, why))
    st = assemble("stl.startup_and_init_all\n_k3_end:\nstl.loop\n", "plain", tag="k3")
    space = st.labels["_k3_end"] // DW
    s_ops = Image(st).run()[0]
    print("  K3  info stl.startup_and_init_all = %d ops of SPACE and EXECUTES %d op (its jump past "
          "the tables). NOT a control: the stl's 'Complexity: ~7000 (6890..7010)' is space and "
          "is stale for this stl, so it cannot certify anything." % (space, s_ops - 1))
    try:
        measure(rng, "plain", drop_body_when_off=True)
        say("L1", False, "the layout-identity assert did NOT fire on an OFF arm without its body")
    except LayoutMoved as e:
        say("L1", True, "the layout-identity assert fired on an OFF arm without its body: %s"
            % str(e)[:90])
    for tag, bad in (("V1", P.mutated_d4_probe()), ("V2", P.mutated_stub_probe())):
        for m in MODES:
            good, why = verify(bad, m)
            say(tag, good is False, "%s: the verifier rejects %s: %s" % (m, bad.note, why[:80]))
    b = assemble(rng.program(True), "pool", rng.files, (), "e1")
    flat_ops = Image(b, flat=1 << 26).run(_limit(HI))[0]
    paged_ops = Image(b, flat=1 << 12).run(_limit(HI))[0]
    say("E1", flat_ops == paged_ops, "flat %d vs paged %d ops, same image" % (flat_ops, paged_ops))
    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit("use --selftest; the probes are run by probes.py")
