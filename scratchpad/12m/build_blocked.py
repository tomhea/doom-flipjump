"""Build a tier with the assembler's BLOCKING pass on (flipjump-151 `table-placement`, BlockPool).

Blocking gives every table dispatched through one jump word a block, so the arm flips an INDEX
instead of a whole address. FINDINGS BF measured the mechanism at 13.13 -> 8.16 ops per xor, and
the gate shows identical output on real stl programs (hex.xor -16.97%, hex.cmp -13.19%).

    python scratchpad/12m/build_blocked.py game --out build/doom_e1m1_blocked.fjm

TWO PASSES, AND ONE SET OF COUNTS FOR EVERY ASSEMBLY. A block's size must be known before its base
is chosen, so a counting run comes first. The counts are then FROZEN and reused for every assembly
in the build, which matters because the game tier assembles twice: pass 1 resolves labels, pass 2
appends the M1 self-reset part and assembles again. Reusing one counts dict keeps allocation
deterministic, so the two passes lay out identically up to the reset part; the reset part's own
tables land past their group's counted slots and are DECLINED, which leaves them inline and safe.

That determinism is not optional. FINDINGS BE: sharing a stateful pool across the passes made
pass 2 relocate nothing and the reset check refused the build with "434 baked addresses moved
between passes". The build prints the per-assembly counts so a mismatch is visible here rather
than 20 minutes later.
"""
import argparse
import gzip
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                   # noqa: E402
from flipjump.assembler.preprocessor import BlockPool                   # noqa: E402
from doomfj.build import build_wall_renderer                            # noqa: E402
from doomfj.config import Config                                        # noqa: E402
from doomfj.harness import W                                            # noqa: E402
from doomfj.wall_renderer import TIERS                                  # noqa: E402

# THE DECLARATION the assembler cannot infer (FINDINGS BG). Every one of these emits
# `pad N; <label>: <entries that all jump explicitly>; end: wflip` -- a table reached only by jump.
# `hex.pointers.xor_hex_to_flip_ptr` does NOT: its pad-4 block is selected by ADDRESS-BIT FLIPS and
# contains a wflip, so "a maximal run of a;b ops after a pad" splits it and the program dies.
SAFE_TABLE_MACROS = ("hex.exact_xor", "hex.sparse_exact_xor", "hex.double_exact_xor",
                     "hex.sparse_double_exact_xor", "hex.triple_exact_xor",
                     "hex.quadrupled_exact_xor")


def _counts_sig(a):
    """What the frozen counts actually depend on: the program, and which macros may be blocked."""
    # ⚠ THE PROGRAM ITSELF MUST BE IN THE KEY. tier/map/wad/macros do not change when an EMITTER
    # changes, so without this a cache made before (say) FORWARD_MOVE moved would be silently
    # reused for a different program -- wrong counts, wrong block sizes, overflow declines, and no
    # error. Hash the emitter sources and the fj sources that shape what gets emitted.
    h = hashlib.sha256()
    for f in sorted(list((ROOT / "src" / "doomfj").glob("*.py"))
                    + list((ROOT / "src" / "fj").glob("*.fj"))):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return {"tier": a.tier, "map": a.map, "wad": a.wad, "macros": sorted(SAFE_TABLE_MACROS),
            "src": h.hexdigest()[:16]}


def _load_counts(path, a):
    if not path or not Path(path).exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            blob = json.load(fh)
    except Exception as exc:                                          # noqa: BLE001
        print("  counts cache unreadable (%s) -- recounting" % exc, flush=True)
        return None
    if blob.get("sig") != _counts_sig(a):
        print("  counts cache is for a DIFFERENT program -- recounting", flush=True)
        return None
    frozen = {
        "counts": blob["counts"],
        "widths": {g: int(w) for g, w in blob["widths"].items()},
        "width_hist": {g: {int(w): int(c) for w, c in h.items()}
                       for g, h in blob["width_hist"].items()},
        "alias": blob.get("alias") or {},
    }
    print("  counts cache HIT: %s groups, %s tables (skipping the counting assembly)"
          % (format(len(frozen["counts"]), ","), format(sum(frozen["counts"].values()), ",")),
          flush=True)
    return frozen


def _save_counts(path, a, frozen):
    if not path:
        return
    blob = {"sig": _counts_sig(a), "counts": frozen["counts"], "widths": frozen["widths"],
            "width_hist": frozen.get("width_hist") or {}, "alias": frozen.get("alias") or {}}
    tmp = Path(str(path) + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh)
    tmp.replace(path)
    print("  counts cached to %s" % path, flush=True)


def _preflight(pool_cls, W, a, frozen, wants):
    """Price the configuration BEFORE the 25-minute assembly.

    Twice now a config has been launched on an eyeballed span estimate and come back 31 minutes
    later with the pool exhausted (blocked10's margin, blocked14's spread=4: 26,945 of 27,032 groups
    broken). The counting pass already knows every block's exact size, so demand vs capacity is
    arithmetic, not a guess. Reports; does not decide.
    """
    probe = pool_cls(W, a.pool_base, counts=frozen["counts"], widths=frozen["widths"],
                     span_bits=a.span_bits, alias=frozen.get("alias"), spread=a.spread,
                     spread_min_count=a.spread_min_count, max_slot_ops=a.max_slot_ops,
                     width_hist=frozen.get("width_hist"), width_buckets=a.width_buckets,
                     wants=wants)
    demand = sum(probe._block_bits(g) for g in frozen["counts"])
    limit = (1 << W) if a.span_bits is None else min(1 << W, a.pool_base + a.span_bits)
    capacity = limit - a.pool_base
    placed = len(probe.groups)
    print("  PREFLIGHT: demand %s words, capacity %s words (%.1f%% used); %s of %s groups placed"
          % (format(demand // W, ","), format(capacity // W, ","),
             100.0 * demand / capacity, format(placed, ","), format(len(frozen["counts"]), ",")),
          flush=True)
    if placed < len(frozen["counts"]):
        print("  *** %s GROUPS GET NO BLOCK -- they lose their pin entirely. This config does not fit."
              % format(len(frozen["counts"]) - placed, ","), flush=True)
    return demand, capacity, placed


def _report_width_waste(counting):
    """How much of the pool goes to PADDING rather than to tables.

    A block's slots are uniform, so the group's widest table sets the width of every slot in it.
    `widths` is a max and hides this: a group of 32,768 eight-op tables plus one 514-op table looks
    identical to a group of 32,769 wide ones. The counting pass keeps the distribution so the two
    can be told apart -- and the answer decides whether splitting groups by width is worth building.

    Accounting only. Reports ops, not bits, so it reads against `max_slot_ops` directly.
    """
    alloc = pad_width = pad_count = real = 0
    mixed = mixed_tables = 0
    worst = []
    for g, n in counting.counts.items():
        hist = counting.width_hist.get(g)
        if not hist:
            continue
        slots = 1 << max(0, (n - 1).bit_length())
        wmax = max(hist)
        slot_ops = 1 << max(0, (wmax - 1).bit_length())
        alloc += slots * slot_ops
        pad_count += (slots - n) * slot_ops
        for w, c in hist.items():
            real += c * w
            pad_width += c * (slot_ops - w)
        # "mixed" = the widest table is more than twice the most COMMON one, i.e. a few wide
        # tables are dragging many narrow ones up.
        common = max(hist, key=lambda w: (hist[w], -w))
        if wmax > 2 * common:
            mixed += 1
            mixed_tables += n
            worst.append((n * (slot_ops - common), g, n, common, wmax))
    if not alloc:
        return
    print("  width waste: %s ops allocated = %s real + %s width-pad + %s count-pad"
          % (format(alloc, ","), format(real, ","), format(pad_width, ","), format(pad_count, ",")),
          flush=True)
    print("  MIXED groups (widest > 2x most-common): %s groups, %s tables; splitting them by width "
          "would free up to %s ops of pool"
          % (format(mixed, ","), format(mixed_tables, ","),
             format(sum(w[0] for w in worst), ",")), flush=True)
    for cost, g, n, common, wmax in sorted(worst, reverse=True)[:5]:
        print("    %14s ops  %-44s n=%-7s common=%-5s widest=%s"
              % (format(cost, ","), g[:44], format(n, ","), common, wmax), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", choices=sorted(TIERS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--preflight-only", action="store_true",
                    help="price the configuration and exit without assembling. With "
                         "--counts-cache populated this costs SECONDS, so a spread/slot/span grid "
                         "can be searched before spending a 31-minute build on it.")
    ap.add_argument("--counts-cache", default=None,
                    help="reuse the counting assembly's counts/widths/histogram from this file "
                         "(and write it when absent). The counting pass costs ~430s and depends "
                         "only on the program and the allowed macros, not on pool geometry, so "
                         "every spread/slot/span config can share one.")
    ap.add_argument("--width-buckets", action="store_true",
                    help="give each WIDTH its own sub-block instead of widening every slot in a "
                         "group to its widest table. Measured on blocked11: 41,479,139 of "
                         "68,224,992 allocated pool ops are width padding, and the pool being full "
                         "is what breaks 12,579 of 27,032 groups. Homogeneous groups are "
                         "unaffected; see scratchpad/12m/bucket_check.py.")
    ap.add_argument("--pin-broken", action="store_true",
                    help="pin a group even when some of its tables were declined. The arithmetic "
                         "says an inline table still dispatches correctly (its arm is rewritten to "
                         "A ^ base and the word rests at base, so the base cancels); the exclusion "
                         "it removes costs every sibling in the group. ONLY m2_std_gate can "
                         "adjudicate -- the toy gate passed the version this guards against.")
    ap.add_argument("--evict-by-value", action="store_true",
                    help="when pool demand exceeds span, drop groups by ascending tables-per-bit "
                         "instead of letting the biggest-first cursor drop whatever it reaches "
                         "last. A broken group loses its pin for ALL its tables (FINDINGS BQ), so "
                         "which groups get dropped is worth more than how many.")
    ap.add_argument("--macros", nargs="*", default=list(SAFE_TABLE_MACROS),
                    help="only block tables emitted by these MACROS -- the declaration the "
                         "assembler cannot infer (FINDINGS BG). Defaults to the exact_xor family, "
                         "whose tables are verified jump-only.")
    ap.add_argument("--view-w", type=int, default=160,
                    help="cfg.VIEW_W, needed to derive the byte arrays (build metrics print it)")
    ap.add_argument("--subsectors", type=int, default=682,
                    help="subsector count, needed to derive the byte arrays")
    ap.add_argument("--max-slot-ops", type=int, default=32,
                    help="widest table a block slot may hold. 10,052 tables decline as too-wide at "
                         "32, and hex.tables.* is both the hottest source word and the macro with "
                         "oversized tables -- a declined table stays inline and pays the FULL "
                         "address (~18.6 ops).")
    ap.add_argument("--spread", type=int, default=1,
                    help="give a big group SPREAD times the slots and hand out only the cheapest "
                         "indices. The arm costs 2*popcount(index) and the index is as wide as the "
                         "group (FINDINGS BN); unused slots emit no data, so this spends SPAN, not "
                         "DATA.")
    ap.add_argument("--spread-min-count", type=int, default=256,
                    help="only groups with at least this many tables get the spread")
    ap.add_argument("--merge-aliases", action="store_true",
                    help="merge groups whose source-word expressions resolve to ONE address into a "
                         "single block, instead of un-pinning both (3,801 words on the game tier)")
    ap.add_argument("--pin-state-cells", action="store_true",
                    help="pin the M1 reset's NIBBLE state cells too, excluding only the BYTE cells "
                         "(m1.zerobyte jumps through those). Worth ~10.7%% more on a walk, and the "
                         "reason it failed before was the base-stripping using the pool's raw pin "
                         "set instead of the assembler's filtered one (FINDINGS BJ).")
    ap.add_argument("--no-pin", action="store_true",
                    help="relocate into blocks but do NOT pin the source words. Splits blocking's "
                         "two halves against the standalone gate, the way --no-pin split them "
                         "against deg_gate (FINDINGS BG).")
    a = ap.parse_args()

    print("blocking: pool base %s, span %s"
          % (hex(a.pool_base), hex(a.span_bits) if a.span_bits else "unbounded"), flush=True)

    allow = frozenset(a.macros)
    wants = (lambda macro_name, prefix: macro_name.name in allow) if allow else None
    print("macros allowed: %s" % ", ".join(sorted(allow)), flush=True)

    # WHICH RESET-OWNED WORDS CAN BE PINNED, and which cannot.
    #
    # NIBBLE cells are restored by `hex.set 1, addr, v` / `hex.zero n, addr`, which dispatch THROUGH
    # the cell and only ever flip its value bits -- so a pinned cell's base survives, and these CAN
    # be pinned. What broke them was not the restore, it was emit_reset_part READING the pristine
    # word: `word >> VAL_SHIFT > 15` reads `base + value` as a packed LUT and drops the cell from
    # the set entirely (FINDINGS BH). Stripping the base before that read fixes it.
    #
    # BYTE cells cannot. `m1.zerobyte c` does `c+dbit+8; c` -- it JUMPS THROUGH the cell into the
    # pointer read table, so the cell's word is a dispatch target whose value the machinery
    # computes itself. A base there sends it somewhere else.
    excluded = {"words": None}

    def _byte_cell_words(labels):
        from doomfj.selfreset import byte_arrays
        bits = {k: int(v) for k, v in labels.items()}
        words_sorted = sorted(v // W for v in bits.values())
        out = set()
        for name, n in byte_arrays(bits, words_sorted, a.view_w, a.subsectors):
            base = bits[name] // W
            for k in range(n):
                out.add(base + 2 * k)
                out.add(base + 2 * k + 1)
        return out

    def _reset_owned(address, labels):
        """Words the M1 self-reset owns. THE WHOLE RESTORE SET, not just the byte cells.

        ⚠ PINNING ONLY THE BYTE CELLS WAS TRIED AND FAILED (FINDINGS BJ). The reasoning looked
        sound -- byte cells are restored by `m1.zerobyte`, which does `c+dbit+8; c` and JUMPS
        THROUGH the cell, while nibble cells are restored by `hex.set`/`hex.zero`, which only flip
        value bits and leave a base intact. Excluding 2,004 byte-cell words instead of 12,400 and
        stripping the base from 26,305 pinned words before emit_reset_part's LUT test built
        cleanly, verified the reset (labels_moved 0, values_changed 0) -- and then died on the
        FIRST frame with a screen-protocol violation:

            IODeviceException: collines run ends at row 37, behind the fill cursor at 50

        Zero byte-exact frames. Something else about a pinned state cell is unsound, and the
        nibble/byte split is not where the line falls. Until that is understood, the whole restore
        set stays unpinned -- which is the configuration that PASSES the standalone gate at
        21,963,752 ops/frame and 34.69% size.
        """
        if excluded["words"] is None:
            if a.pin_state_cells:
                excluded["words"] = _byte_cell_words(labels)
                print("  pin-exclude: %s BYTE-cell words only (m1.zerobyte jumps through them); "
                      "nibble state cells ARE pinned" % format(len(excluded["words"]), ","),
                      flush=True)
            else:
                from doomfj.selfreset import load_restore_set
                from doomfj.build import STANDALONE_RESTORE_SET
                excluded["words"] = set(load_restore_set(
                    STANDALONE_RESTORE_SET, {k: int(v) for k, v in labels.items()},
                    check_layout=False))
                print("  pin-exclude: %s restore-set words will NOT be pinned"
                      % format(len(excluded["words"]), ","), flush=True)
        return (address // W) in excluded["words"]

    # STRIP THE BASE before emit_reset_part reads a pristine word. The restore code itself is
    # base-safe; only this read is not.
    # CAPTURE THE MAP THE ASSEMBLER ACTUALLY USED, not the pool's raw one.
    #
    # `pool.pinned_words()` is the set BEFORE resolve_pinned drops aliased words (3,801) and the
    # caller's exclusions. The BAKE uses the filtered map. Stripping with the raw set therefore
    # XORs a base into words that never got one -- the value then looks enormous,
    # emit_reset_part classifies the cell as a packed LUT and SILENTLY DROPS IT from the restore
    # set. Measured: 4 cells vanished from one `hex.zero 25` run alone, and the binary rendered 37
    # frames before the missing state showed up as a screen-protocol violation at frame 38.
    from flipjump.assembler import assembler as _asmmod
    _real_resolve = _asmmod.resolve_pinned
    live_pins = {"map": {}}

    def _capture_resolve(pinned_exprs, labels, reserved_below=1024, exclude=None):
        out, conflicts = _real_resolve(pinned_exprs, labels, reserved_below, exclude)
        live_pins["map"] = dict(out)
        return out, conflicts

    _asmmod.resolve_pinned = _capture_resolve

    import doomfj.selfreset as _selfreset
    _real_emit = _selfreset.emit_reset_part

    def _emit_reset_part(gen_dir, labels, pristine_get_word, *rest, **kw):
        pinned_by_word = {addr // W: base for addr, base in live_pins["map"].items()}
        stripped = len(pinned_by_word)

        def unpinned_word(word_index):
            value = pristine_get_word(word_index)
            base = pinned_by_word.get(word_index)
            return (value ^ base) if base else value

        # A COLLAPSE HERE IS SILENT OTHERWISE. spread=4 exhausted the pool, almost every group got
        # no block, and pinning fell from 25,701 words to 72 -- which builds fine, passes the gate,
        # and measures like the un-pinned regression. Say it loudly instead.
        expected = sum(1 for pool in pools for _ in pool.groups)
        print("  reset: stripping the block base from %s pinned words before the LUT test"
              % format(stripped, ","), flush=True)
        if expected and stripped < expected // 10:
            print("  *** PINNING COLLAPSED: %s pinned words against %s groups. The pool is almost "
                  "certainly exhausted -- lower --pool-base or reduce --spread."
                  % (format(stripped, ","), format(expected, ",")), flush=True)
        return _real_emit(gen_dir, labels, unpinned_word, *rest, **kw)

    _selfreset.emit_reset_part = _emit_reset_part

    frozen = {}          # counts/widths from the first counting run, reused by every assembly
    pools = []
    real_assemble = fj.assemble

    def assemble_blocked(*args, **kwargs):
        if not frozen:
            cached = _load_counts(a.counts_cache, a)
            if cached:
                frozen.update(cached)
        if not frozen:
            with tempfile.TemporaryDirectory() as td:
                counting = BlockPool(W, a.pool_base, span_bits=a.span_bits,
                                     spread=a.spread, spread_min_count=a.spread_min_count,
                                     max_slot_ops=a.max_slot_ops, wants=wants)
                probe = dict(kwargs)
                probe["table_pool"] = counting
                out_arg = list(args)
                if len(out_arg) > 1:
                    out_arg[1] = Path(td) / "count.fjm"
                else:
                    probe["output_fjm_path"] = Path(td) / "count.fjm"
                t0 = time.time()
                # capture the counting assembly's labels so its group EXPRESSIONS can be resolved
                import flipjump.assembler.assembler as _asm_mod
                seen_labels = {}
                _real_lr = _asm_mod.labels_resolve

                def _lr(ops, labels, memory_width, fjm_writer, **k):
                    seen_labels.update({kk: int(vv) for kk, vv in labels.items()})
                    return _real_lr(ops, labels, memory_width, fjm_writer, **k)

                _asm_mod.labels_resolve = _lr
                try:
                    real_assemble(*out_arg, **probe)
                finally:
                    _asm_mod.labels_resolve = _real_lr
                frozen["counts"] = counting.counts
                frozen["widths"] = counting.widths
                frozen["width_hist"] = counting.width_hist
                # MERGE ALIASED GROUPS. Two expressions can name one word -- `(x + 32)` and
                # `(x + w)` at w=32 -- and separate blocks meant resolve_pinned had to UN-PIN both
                # (3,801 words). Merging keeps the pins.
                alias = counting.canonical_alias(seen_labels) if a.merge_aliases else {}
                if alias:
                    merged_counts, merged_widths = {}, {}
                    for g, n in counting.counts.items():
                        c = alias.get(g, g)
                        merged_counts[c] = merged_counts.get(c, 0) + n
                        merged_widths[c] = max(merged_widths.get(c, 0), counting.widths.get(g, 16))
                    merged_hist = {}
                    for g, h in counting.width_hist.items():
                        c = alias.get(g, g)
                        into = merged_hist.setdefault(c, {})
                        for w, n in h.items():
                            into[w] = into.get(w, 0) + n
                    frozen["counts"] = merged_counts
                    frozen["widths"] = merged_widths
                    frozen["width_hist"] = merged_hist
                    print("  alias: %s groups merged into %s (was %s)"
                          % (format(len(alias), ","), format(len(merged_counts), ","),
                             format(len(counting.counts), ",")), flush=True)
                frozen["alias"] = alias
                _save_counts(a.counts_cache, a, frozen)
                _report_width_waste(counting)
                print("  counting pass: %s groups, %s tables, %ds"
                      % (format(len(counting.counts), ","),
                         format(sum(counting.counts.values()), ","), int(time.time() - t0)),
                      flush=True)
        if not frozen.get("_preflighted"):
            frozen["_preflighted"] = True
            _preflight(BlockPool, W, a, frozen, wants)
            if a.preflight_only:
                print("  --preflight-only: priced, not built.", flush=True)
                raise SystemExit(0)
        pool = BlockPool(W, a.pool_base, counts=frozen["counts"], widths=frozen["widths"],
                         span_bits=a.span_bits, alias=frozen.get("alias"),
                         spread=a.spread, spread_min_count=a.spread_min_count,
                         max_slot_ops=a.max_slot_ops, evict_by_value=a.evict_by_value,
                         pin_broken=a.pin_broken, width_hist=frozen.get("width_hist"),
                         width_buckets=a.width_buckets, wants=wants)
        # NEVER PIN A WORD THE M1 SELF-RESET OWNS. emit_reset_part drops a cell from the restore
        # set when `pristine_word >> VAL_SHIFT > 15`, reading it as a packed LUT -- and a pinned
        # word holds `base + value`, so every pinned state cell is misclassified and silently
        # stops being restored. The standalone gate saw exactly that: frame 2 byte-exact, frame 3
        # stale (FINDINGS BH).
        pool.pin_exclude = _reset_owned
        pools.append(pool)
        kwargs["table_pool"] = pool
        return real_assemble(*args, **kwargs)

    fj.assemble = assemble_blocked
    asmmod = _asmmod
    real_resolve = _real_resolve
    if a.no_pin:
        asmmod.resolve_pinned = lambda exprs, labels, reserved_below=1024, exclude=None: ({}, 0)
        print("PINNING OFF -- relocation only", flush=True)
    import doomfj.build as build_module
    assert build_module.fj.assemble is assemble_blocked, "build.py does not call fj.assemble"

    t0 = time.time()
    try:
        info = build_wall_renderer(ROOT / a.out, wad_path=str(ROOT / a.wad), mapname=a.map,
                                   cfg=Config(), tier=a.tier)
    finally:
        fj.assemble = real_assemble
        asmmod.resolve_pinned = real_resolve

    print(json.dumps(info, indent=2, default=str), flush=True)
    print("", flush=True)
    print("assemblies: %d; blocked per assembly: %s"
          % (len(pools), ", ".join(format(q.allocated, ",") for q in pools)), flush=True)
    if len({q.allocated for q in pools}) > 1:
        print("*** THE PASSES BLOCKED DIFFERENT COUNTS -- their addresses cannot agree", flush=True)
    last = pools[-1]
    print("pin conflicts (aliased source-word expressions, un-pinned): %s"
          % format(getattr(last, "pin_conflicts", 0), ","), flush=True)
    print("runtime-reserved words skipped (stl.IO etc): %s"
          % format(getattr(last, "reserved_words", 0), ","), flush=True)
    print("declines by reason: no-block %s, too-wide %s, overflow %s"
          % (format(getattr(last, "declined_no_block", 0), ","),
             format(getattr(last, "declined_too_wide", 0), ","),
             format(getattr(last, "declined_overflow", 0), ",")), flush=True)
    # BROKEN GROUPS is the number that matters, not the decline count: `pinned_words` excludes a
    # broken group ENTIRELY, so one declined table un-pins every sibling table in its group.
    print("broken groups: %s of %s (these lose their pin for ALL their tables); evicted %s"
          % (format(len(getattr(last, "broken_groups", ())), ","),
             format(len(last.counts), ","),
             format(getattr(last, "evicted_low_value", 0), ",")), flush=True)
    print("blocked: %s tables in %s groups; declined %s; ungrouped %s"
          % (format(last.allocated, ","), format(len(last.groups), ","),
             format(last.declined, ","), format(last.ungrouped, ",")), flush=True)
    if last.allocated == 0:
        print("*** NOTHING WAS BLOCKED", flush=True)
    print("total %ds" % int(time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
