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

ONE PASS (2026-10-13). The game tier is in selfreset.ONE_PASS_TIERS: its reset is emitted by LABEL from the
declarations, so it assembles ONCE (no pass 2). `--one-pass-blocks` removes the counting assembly too: flipjump's
BlockPool(one_pass=True) (flipjump #369) takes every table it would block out of the op stream as the expansion
reaches it and places them all when the expansion ends, sizing the blocks from that same expansion's census. No
counts cache is read; `--counts-cache` receives the census (pinreport reads it). Given the same counts it makes the
two-pass binary byte for byte, except where a table gets no block -- it goes to an overflow region after the blocks
instead of inline (see BlockPool's docstring).

NO PATCHING (flipjump 1.6.0's API, 2026-10-31). This driver used to replace `flipjump.assemble`, wrap the assembler's
`resolve_pinned` to learn the pin map, subclass BlockPool to record the table sites, and hand the pool a `pin_exclude`
callback after construction. Now it only says HOW to assemble: `build_wall_renderer(..., assembly=Assembly(
lzma_preset, pool=<BlockPool's knobs>))`. The build makes a fresh pool per assembly with `pin_all_but` -- the cells the
program reads raw, which the BUILD names from the emitted program (selfreset.pin_all_but_cells; the byte cells and the
pointer-read cells, what `--pin-state-cells` always excluded) -- and returns the pools; their `report` says what each
did: the FINAL pin map (`report.pinned`), every table's site and address (`report.table_sites`), the census.
"""
import argparse
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from flipjump.assembler.inner_classes.table_pool import HotSite                      # noqa: E402
from doomfj.build import Assembly, build_wall_renderer                  # noqa: E402
from doomfj.config import Config                                        # noqa: E402
from doomfj.harness import W, SHIP_LZMA_PRESET                          # noqa: E402
from doomfj.wall_renderer import TIERS                                  # noqa: E402

# WHICH TABLES MOVE is the stl's declaration since flipjump 1.6.0, not this script's: a pool moves exactly the
# tables of a macro whose innermost namespace is `__relocatable__` (preprocessor.is_relocatable). The stl declares
# nine -- hex.exact_xor, sparse_exact_xor, double_exact_xor, sparse_double_exact_xor, triple_exact_xor,
# quadrupled_exact_xor, shifts.shl_bit_once, shifts.shr_bit_once and hex.switch -- the nine this script used to name in
# its own allow-list for the pool's macro filter, which 1.6.0 removed. Why those and no other (FINDINGS
# BG): each emits `pad N; <label>: <entries that all jump explicitly>`, a table reached only by jump.
# `hex.pointers.xor_hex_to_flip_ptr` is selected by address-bit flips and holds a wflip; `hex.inc1`'s entry 15
# falls through into its carry tail -- neither is declared.


def _counts_sig(a):
    """What the frozen counts actually depend on: the program (and the stl's declared tables)."""
    # ⚠ THE PROGRAM ITSELF MUST BE IN THE KEY. tier/map/wad do not change when an EMITTER
    # changes, so without this a cache made before (say) FORWARD_MOVE moved would be silently
    # reused for a different program -- wrong counts, wrong block sizes, overflow declines, and no
    # error. Hash the emitter sources and the fj sources that shape what gets emitted.
    h = hashlib.sha256()
    for f in sorted(list((ROOT / "src" / "doomfj").glob("*.py"))
                    + list((ROOT / "src" / "fj").glob("*.fj"))):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    # (no "macros" since flipjump 1.6.0: the stl declares the tables that move, and the stl's sources are not
    # hashed here -- a new stl is a new flipjump checkout, so regenerate the census with it, as 4b does)
    return {"tier": a.tier, "map": a.map, "wad": a.wad, "src": h.hexdigest()[:16]}


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
        if not getattr(a, "counts_trust", False):
            print("  counts cache is for a DIFFERENT program -- recounting", flush=True)
            return None
        # ONE PASS (2026-10-13): the signature hashes every emitter source, so a change that moves no table (the
        # one-pass reset itself) misses the cache. --counts-trust reuses it anyway: stale counts are SAFE -- a table
        # past its group's counted slots is declined and stays inline -- and the build reports the declines.
        print("  counts cache is for a DIFFERENT program -- TRUSTED anyway (--counts-trust; its sig %s, ours %s)"
              % (blob.get("sig", {}).get("src"), _counts_sig(a)["src"]), flush=True)
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


def _pack_kw(a):
    """BlockPool(pack=True) under --pack-blocks; nothing otherwise (so a flipjump without pack= still builds)"""
    return {"pack": True} if getattr(a, "pack_blocks", False) else {}


def _preflight(pool, a):
    """Price the layout the one-pass pool placed: its blocks' demand against the pool's capacity (flipjump's
    BlockPool refuses a pool too small for its blocks, so every group is placed). Reports; does not decide."""
    demand = sum(pool._block_bits(g) for g in pool.counts)
    if getattr(a, "pack_blocks", False):
        print("  PREFLIGHT (--pack-blocks): the packed blocks end %s words past the pool base (the demand below is "
              "the blocks' whole sizes, unpacked)" % format(pool._used // W, ","), flush=True)
    limit = (1 << W) if pool.pool_end is None else min(1 << W, pool.pool_end)
    capacity = limit - a.pool_base
    placed = len(pool.groups)
    print("  PREFLIGHT: demand %s words, capacity %s words (%.1f%% used); %s of %s groups placed"
          % (format(demand // W, ","), format(capacity // W, ","),
             100.0 * demand / capacity, format(placed, ","), format(len(pool.counts), ",")),
          flush=True)
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


def pool_knobs(a, heat=None) -> dict:
    """BlockPool's keyword arguments for this command line (build.Assembly.pool). The flags keep their recorded
    spellings (docs/ship-gate.md 1b): --span-bits is a length from --pool-base (BlockPool's pool_end is the address it
    ends below), --spread / --spread-min-count / --pin-broken are spread_factor / spread_min_tables /
    pin_incomplete_groups. No pin_all_but: the build names the cells the program reads raw."""
    knobs = {"pool_base": a.pool_base, "pool_end": None if a.span_bits is None else a.pool_base + a.span_bits,
             "max_slot_ops": a.max_slot_ops, "spread_factor": a.spread, "spread_min_tables": a.spread_min_count,
             "pin_incomplete_groups": a.pin_broken}
    if heat:
        knobs["heat"] = heat
    knobs.update(_pack_kw(a))
    return knobs


def load_heat(path):
    """a heatsites.py list (--pin-heat) as BlockPool's `heat` -> (heat, the list's raw bytes)"""
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)      # the sha printed is the LIST's, in either form
    heat = {g: [HotSite(*site) for site in sites] for g, sites in json.loads(raw)["groups"].items()}
    return heat, raw


def report_pins(pool, heat, labels=None):
    """the pool's FINAL pin map (report.pinned: after every pin that could not hold was dropped), the collapse alarm,
    and the hot words that did not end up pinned"""
    pinned = pool.report.pinned
    groups = len(pool.groups)
    print("  pins: %s words pinned, %s groups blocked" % (format(len(pinned), ","), format(groups, ",")), flush=True)
    # A COLLAPSE IS SILENT OTHERWISE (spread=4 once fell from 25,701 pinned words to 72, built fine and passed the gate)
    if groups and len(pinned) < max(1, groups // 10):      # none at all, on a program of < 10 groups
        print("  *** PINNING COLLAPSED: %s pinned words against %s groups. The pool is almost certainly "
              "exhausted -- lower --pool-base or reduce --spread." % (format(len(pinned), ","), format(groups, ",")),
              flush=True)
    if heat and labels is not None:
        # a hot word that did not end up pinned: a raw cell (pin_all_but), an alias conflict, or a pin that cannot hold
        hot = [(g, pool.groups[g][1]) for g in pool.hot_sites if g in pool.groups and pool.groups[g][1] is not None]
        lost = [g for g, expr in hot if expr.exact_eval(labels) not in pinned]
        print("  pin-heat: %d of %d hot words pinned%s"
              % (len(hot) - len(lost), len(hot), "; NOT pinned: %s" % lost[:5] if lost else ""), flush=True)


def write_sites(path, a, pool):
    """--record-sites: every table the pool met, per canonical group, in expansion order -- [site (heat_key), occurrence,
    slot_ops, address] (flipjump's report.table_sites; address 0: it stayed in place). heatsites.py names a profile's
    tables by them."""
    by_group = {}
    for t in pool.report.table_sites:
        by_group.setdefault(t.group, []).append([t.site, t.occurrence, t.slot_ops, t.address])
    blob = {"what": "every table the assembly reached, per canonical group, in expansion order: "
                    "[macro-expansion path (heat_key), occurrence, slot ops, address (0: in place)]",
            "program": _counts_sig(a), "tables": len(pool.report.table_sites), "groups": by_group}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(blob, fh)
    print("  recorded %s tables in %s groups -> %s"
          % (format(blob["tables"], ","), format(len(by_group), ","), path), flush=True)


def write_labels(path, labels):
    """the build's label table, `name<TAB>bit-address` gzipped -- what the assembler resolved, as flipjump's assemble
    returned it (build_labeled.py --labels; the gates' --labels)"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for name, addr in labels.items():
            fh.write(f"{name}\t{addr}\n")
    print(f"labels -> {path}  ({len(labels):,} labels)", flush=True)


def main(argv=None, labels_out=None):
    """`argv`: build_blocked.py's arguments (None: sys.argv); `labels_out`: write the label table there
    (build_labeled.py)"""
    ap = argparse.ArgumentParser(prog="build_blocked.py")
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
    ap.add_argument("--counts-trust", action="store_true",
                    help="use --counts-cache even when its signature names a different program (the one-pass build's "
                         "validation reuses blocked55's counts: its tables are unchanged). Stale counts are safe -- "
                         "an uncounted table is declined and stays inline.")
    ap.add_argument("--counts-cache", default=None,
                    help="reuse the counting assembly's counts/widths/histogram from this file "
                         "(and write it when absent). The counting pass costs ~430s and depends "
                         "only on the program (and the stl's declared tables), not on pool geometry, so "
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
                    help="REQUIRED (the only mode left): pin the M1 reset's NIBBLE state cells too, leaving unpinned "
                         "only the cells the program reads raw -- the BYTE cells (m1.zerobyte jumps through those) "
                         "and the pointer-read cells (selfreset.pin_all_but_cells; FINDINGS BJ). The other mode, "
                         "which left the whole restore set unpinned, went with flipjump's pin_exclude callback: "
                         "no recorded build used it.")
    ap.add_argument("--record-sites", default=None, metavar="SITES.json.gz",
                    help="pin protection (M7 P1.1): write every table the assembly reached -- its group, its "
                         "macro-expansion path, its occurrence, its slot and its address, in expansion order "
                         "(flipjump's pool.report.table_sites) -- here. heatsites.py joins them with a profile into "
                         "a --pin-heat list.")
    ap.add_argument("--pin-heat", default=None, metavar="HEAT.json[.gz]",
                    help="pin protection (M7 P1.1, docs/gp-pin-protection.md): heatsites.py's list of "
                         "hot groups and their hot table sites. Every placing pool protects them: a "
                         "hot group keeps its block and its pin (or the build stops), and its hottest "
                         "tables take the cheapest indices of their width. Needs flipjump with "
                         "BlockPool(heat=).")
    ap.add_argument("--one-pass-blocks", action="store_true",
                    help="ONE expansion, no counting assembly (flipjump #369, BlockPool(one_pass=True)): the tables wait "
                         "out of the op stream and the blocks are sized from the same expansion's census. "
                         "--counts-cache is written (the census), never read.")
    ap.add_argument("--pack-blocks", action="store_true",
                    help="M8 size: BlockPool(pack=True) -- every block keeps its size, alignment and every table's index "
                         "(so every arm flips what it flips without it), but the space inside it that its own tables "
                         "do not use (bucket tails, the power-of-two round-up, the slots the cheap-index order skips) "
                         "holds other blocks. E1M2 r4's census: spread 1 56.46M -> 33.37M words of pool, spread 2 "
                         "94.19M -> 64.12M. Needs flipjump with BlockPool(pack=) (branch block-pack).")
    ap.add_argument("--lzma-preset", type=int, default=SHIP_LZMA_PRESET, choices=range(10), metavar="0-9",
                    help="the .fjm's LZMA preset (flipjump 1.6.0's lzma_preset). This script makes the SHIP builds "
                         "(docs/ship-gate.md 1b), so its default is harness.SHIP_LZMA_PRESET (6, the owner's A10: "
                         "-10.8%% file size); pass 1 (harness.FJM_LZMA_PRESET) for a day-to-day build. Encoder-only: the "
                         "program image is the same at every preset. The counting assembly's throwaway .fjm keeps the "
                         "caller's preset.")
    a = ap.parse_args(argv)
    if a.pack_blocks:
        import inspect
        from flipjump.assembler.preprocessor import BlockPool as _BP
        if "pack" not in inspect.signature(_BP.__init__).parameters:
            ap.error("--pack-blocks needs flipjump with BlockPool(pack=) (the block-pack branch); this one is %s"
                     % inspect.getfile(_BP))
        if a.evict_by_value:
            ap.error("--pack-blocks and --evict-by-value are not combined (BlockPool refuses it)")
    if not a.one_pass_blocks:
        ap.error("flipjump's BlockPool is one-pass only: pass --one-pass-blocks")
    if not (a.width_buckets and a.merge_aliases) or a.evict_by_value:
        ap.error("flipjump's BlockPool always buckets widths and merges aliases, and never evicts: pass "
                 "--width-buckets --merge-aliases, and no --evict-by-value")
    if not a.pin_state_cells:
        ap.error("pass --pin-state-cells: the build leaves unpinned exactly the cells the program reads raw "
                 "(the restore-set mode is gone)")
    clash = [f for f, on in (("--counts-trust", a.counts_trust), ("--preflight-only", a.preflight_only)) if on]
    if clash:
        ap.error("--one-pass-blocks has no counting assembly and reads no counts: %s" % ", ".join(clash))

    print("blocking: pool base %s, span %s; .fjm LZMA preset %d"
          % (hex(a.pool_base), hex(a.span_bits) if a.span_bits else "unbounded", a.lzma_preset), flush=True)

    heat = None
    if a.pin_heat:
        heat, raw = load_heat(a.pin_heat)
        print("pin-heat: %s (sha256 %s...): %d hot groups, %s hot sites"
              % (a.pin_heat, hashlib.sha256(raw).hexdigest()[:16], len(heat),
                 format(sum(len(v) for v in heat.values()), ",")), flush=True)

    t0 = time.time()
    info = build_wall_renderer(ROOT / a.out, wad_path=str(ROOT / a.wad), mapname=a.map, cfg=Config(), tier=a.tier,
                               assembly=Assembly(lzma_preset=a.lzma_preset, pool=pool_knobs(a, heat)))
    pools = info.pop("table_pools", [])
    labels = info.pop("labels", None)
    if labels_out:
        write_labels(labels_out, labels)
    print(json.dumps(info, indent=2, default=str), flush=True)
    print("", flush=True)
    assert pools, "the build made no table pool -- build_wall_renderer did not take the Assembly"
    cells = info.get("pin_all_but") or []
    print("  pin_all_but: %s cells -- the BYTE cells (m1.zerobyte jumps through them) %s and the pointer-read cells %s;"
          " every other word may be pinned" % (len(cells), [c for c in cells if not isinstance(c, str)],
                                               [c for c in cells if isinstance(c, str)]), flush=True)
    for pool in pools:
        print("  one pass: %s tables deferred, %s alias words unresolved; the census: %s groups, %s tables; "
              "%s declined (too wide for any slot)"
              % (format(pool.deferred, ","), format(pool.alias_unresolved, ","), format(len(pool.counts), ","),
                 format(sum(pool.counts.values()), ","), format(pool.declined, ",")), flush=True)
        _preflight(pool, a)
        report_pins(pool, heat, labels)
    last = pools[-1]
    if a.counts_cache:
        census = last.report.census
        _save_counts(a.counts_cache, a, {"counts": census.counts, "widths": census.widths,
                                         "width_hist": census.width_hist, "alias": census.alias})
    if heat:
        print("  pin-heat: %s" % last.heat_report(), flush=True)
    if a.record_sites:
        write_sites(a.record_sites, a, last)
    print("assemblies: %d; blocked per assembly: %s"
          % (len(pools), ", ".join(format(q.allocated, ",") for q in pools)), flush=True)
    print("pin conflicts (aliased source-word expressions, un-pinned): %s" % format(last.report.pin_conflicts, ","),
          flush=True)
    print("runtime-reserved words skipped (stl.IO etc): %s" % format(last.report.runtime_words, ","), flush=True)
    print("declined (too wide for any slot): %s" % format(last.declined, ","), flush=True)
    # BROKEN GROUPS is the number that matters, not the decline count: `pinned_words` excludes a
    # broken group ENTIRELY, so one declined table un-pins every sibling table in its group.
    print("broken groups: %s of %s (these lose their pin for ALL their tables)"
          % (format(len(last.broken_groups), ","), format(len(last.counts), ",")), flush=True)
    if last.report.unpins:
        print("unpinned (a pin that could not hold), by why: %s" % dict(last.report.unpins), flush=True)
    if heat:
        print("pin-heat after the last assembly: %s" % last.heat_report(), flush=True)
    print("blocked: %s tables in %s groups; declined %s; ungrouped %s"
          % (format(last.allocated, ","), format(len(last.groups), ","),
             format(last.declined, ","), format(last.ungrouped, ",")), flush=True)
    if last.allocated == 0:
        print("*** NOTHING WAS BLOCKED", flush=True)
    print("total %ds" % int(time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
