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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", choices=sorted(TIERS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--macros", nargs="*", default=list(SAFE_TABLE_MACROS),
                    help="only block tables emitted by these MACROS -- the declaration the "
                         "assembler cannot infer (FINDINGS BG). Defaults to the exact_xor family, "
                         "whose tables are verified jump-only.")
    ap.add_argument("--view-w", type=int, default=160,
                    help="cfg.VIEW_W, needed to derive the byte arrays (build metrics print it)")
    ap.add_argument("--subsectors", type=int, default=682,
                    help="subsector count, needed to derive the byte arrays")
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

        print("  reset: stripping the block base from %s pinned words before the LUT test"
              % format(stripped, ","), flush=True)
        return _real_emit(gen_dir, labels, unpinned_word, *rest, **kw)

    _selfreset.emit_reset_part = _emit_reset_part

    frozen = {}          # counts/widths from the first counting run, reused by every assembly
    pools = []
    real_assemble = fj.assemble

    def assemble_blocked(*args, **kwargs):
        if not frozen:
            with tempfile.TemporaryDirectory() as td:
                counting = BlockPool(W, a.pool_base, span_bits=a.span_bits, wants=wants)
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
                    frozen["counts"] = merged_counts
                    frozen["widths"] = merged_widths
                    print("  alias: %s groups merged into %s (was %s)"
                          % (format(len(alias), ","), format(len(merged_counts), ","),
                             format(len(counting.counts), ",")), flush=True)
                frozen["alias"] = alias
                print("  counting pass: %s groups, %s tables, %ds"
                      % (format(len(counting.counts), ","),
                         format(sum(counting.counts.values()), ","), int(time.time() - t0)),
                      flush=True)
        pool = BlockPool(W, a.pool_base, counts=frozen["counts"], widths=frozen["widths"],
                         span_bits=a.span_bits, alias=frozen.get("alias"), wants=wants)
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
    print("blocked: %s tables in %s groups; declined %s; ungrouped %s"
          % (format(last.allocated, ","), format(len(last.groups), ","),
             format(last.declined, ","), format(last.ungrouped, ",")), flush=True)
    if last.allocated == 0:
        print("*** NOTHING WAS BLOCKED", flush=True)
    print("total %ds" % int(time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
