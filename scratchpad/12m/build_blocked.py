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

    restore_words = {"set": None}

    def _reset_owned(address, labels):
        if restore_words["set"] is None:
            try:
                from doomfj.selfreset import load_restore_set
                from doomfj.build import STANDALONE_RESTORE_SET
                resolved = {k: int(v) for k, v in labels.items()}
                restore_words["set"] = set(load_restore_set(STANDALONE_RESTORE_SET, resolved,
                                                            check_layout=False))
                print("  pin-exclude: %s restore-set words will NOT be pinned"
                      % format(len(restore_words["set"]), ","), flush=True)
            except Exception as exc:                                    # noqa: BLE001
                print("  *** pin-exclude FAILED to load the restore set (%s) -- nothing excluded, "
                      "so the reset interaction is LIVE" % type(exc).__name__, flush=True)
                restore_words["set"] = frozenset()
        return (address // W) in restore_words["set"]

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
                real_assemble(*out_arg, **probe)
                frozen["counts"] = counting.counts
                frozen["widths"] = counting.widths
                print("  counting pass: %s groups, %s tables, %ds"
                      % (format(len(counting.counts), ","),
                         format(sum(counting.counts.values()), ","), int(time.time() - t0)),
                      flush=True)
        pool = BlockPool(W, a.pool_base, counts=frozen["counts"], widths=frozen["widths"],
                         span_bits=a.span_bits, wants=wants)
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
    from flipjump.assembler import assembler as asmmod
    real_resolve = asmmod.resolve_pinned
    if a.no_pin:
        asmmod.resolve_pinned = lambda exprs, labels, reserved_below=1024: ({}, 0)
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
