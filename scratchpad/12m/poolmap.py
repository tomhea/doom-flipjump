"""Where a blocked binary's SPAN goes: the segment split, and the padding inside the pool's blocks.

DESIGN.md section 1.2's blocked25 row needs four numbers that no tool printed. `fjmsize.py` reports
w, segments, data, span and file bytes -- not how much of the payload sits BELOW the table pool,
how much sits inside it, how wide the gap in front of the pool is, or how much of the pool is
PADDING rather than tables. `build_blocked.py --preflight-only` does price demand vs capacity, but
its preflight runs inside the patched `fj.assemble`, so reaching it costs the tier's whole emit
(~7 min) -- it prices a build, it does not read a binary. This reads the two artifacts that are
already on disk: the .fjm's own segment table, and the frozen counts cache that
`docs/ship-gate.md` 1b's build command names.

THE POOL'S ARITHMETIC, from flipjump-151 `flipjump/assembler/preprocessor.py`:

  * there are no gaps BETWEEN blocks. `BlockPool._preallocate` allocates biggest-first with each
    block aligned to its own power-of-two size; its docstring says allocating them in "encounter
    order leaves a hole in front of each one, up to a whole block's worth", while "in descending
    size each block lands on an address the previous ones already aligned past". The measurement
    that shows it is
    `demand == extent`: the block SIZES sum to the span the blocks occupy, so no block sits behind
    a hole. (`extent == the image's span above pool_base` is a DIFFERENT fact -- it says the image
    ends at the allocator's cursor -- and it cannot prove this one, because `_used` is the cursor
    and so already contains any hole.)
  * the padding is INSIDE the blocks, by three mechanisms, which `pad_breakdown` separates and the
    PAD line prints:
      - the whole block is rounded up to a power of two AFTER its buckets are laid out
        (`_bucket_layout`: `1 << max(0, (offset - 1).bit_length())`) -- a `--width-buckets` one; the
        uniform path's block IS its slots, so this term is 0 there;
      - slots past the group's table count are never written: the count is rounded up to a power
        of two, times `--spread` for a group above `--spread-min-count`. `__init__`'s own note:
        "unused slots emit no data, so it costs span, not data";
      - every slot is as wide as its bucket's widest table (`_bucket_layout`: "most of a mixed
        group's block is width padding"), and a table wider than `--max-slot-ops` is declined to
        inline and emits nothing into the pool at all.
    A fourth term, alignment BETWEEN buckets, is printed and is 0 for every group, at any
    `--spread`: a bucket is `spread * op_bits * 2**k` bits, so of two buckets in one group the
    bigger is a whole multiple of the smaller (the `spread` cancels), and laying them out
    biggest-first therefore always leaves the cursor aligned for the next. That is a property of
    `_bucket_layout`, not of this binary, so the term is MEASURED and printed rather than assumed:
    a layout whose bucket size was not a power of two times the group's spread would print it
    nonzero instead of quietly landing in one of the other three terms.

  sum(BlockPool._block_bits) - (words the .fjm actually emits into the pool) = that padding.

    python scratchpad/12m/poolmap.py
    python scratchpad/12m/poolmap.py --allow-stale      # counts cache signed for another tree
    python scratchpad/12m/poolmap.py --selftest

The knobs default to ship-gate 1b's build command. Only those that enter `_block_bits` /
`_preallocate` change these numbers: `--pool-base`, `--span-bits`, `--spread`,
`--spread-min-count`, `--max-slot-ops`, `--width-buckets` and the cache's alias map.
`--pin-broken` / `--pin-state-cells` decide PINNING, not placement, so they are not repeated here.

CONTROLS (R9)
  C1 THE SPLIT READER READS THE FILE -- a synthesised .fjm with a known, different split must be
     reported as ITS numbers. A reader that printed blocked25's constants would pass every run.
  C2 THE DEMAND READS THE COUNTS -- dropping one group's table count in a copy of the frozen counts
     must move the demand by exactly that group's block size, before minus after. A demand that
     ignored the cache, or a stubbed `_block_bits`, does not move at all.
  C3 A STALE CACHE IS REFUSED -- the counts are keyed by the emitter sources (`build_blocked.py`'s
     `_counts_sig`); a cache whose signature does not match the working tree must be reported STALE
     rather than priced, since its block sizes belong to a different program.
  C4 NON-VACUITY -- zero groups, zero demand, or zero words emitted into the pool is a FAILED
     measurement, not a 0-word pad.
  C5 THE PAD'S MECHANISMS ARE MEASURED, NOT APPORTIONED -- a hand-computed two-bucket block whose
     round-up, alignment, unused-slot and width terms are each known in advance; the same group
     with `--no-width-buckets`, where the round-up term must vanish (so the term names a mechanism
     rather than being a constant); and, on the real cache, that the breakdown's own total IS the
     demand the PAD line prices, which is what stops it drifting from `_block_bits`. A breakdown
     that charged the whole pad to unused slots -- what the PAD line claimed before 2026-09-15 --
     reports (2048, 0, 0, 0, 2048) for the hand-computed block, and 84,565,984 words of demand
     against the PAD line's 45,678,048.
"""
import argparse
import struct
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flipjump.assembler.preprocessor import BlockPool                    # noqa: E402
from flipjump.fjm.fjm_consts import (FJ_MAGIC, FJMVersion,               # noqa: E402
                                     _header_base_format, _header_base_size,
                                     _header_extension_size, _segment_format, _segment_size)

import fjmsize                                                           # noqa: E402
# the signature, and what it hashes, must not drift from the builder's -- import it, never copy it
from build_blocked import _counts_sig, _load_counts                      # noqa: E402

# ship-gate 1b's build command, plus build_blocked.py's own defaults for what it does not pass
SHIP_GATE = dict(pool_base=0x60000000, span_bits=0x9FFFFFE0, spread=2, spread_min_count=256,
                 max_slot_ops=512, width_buckets=True, tier="game", map="E1M1",
                 wad="tests/fixtures/freedoom_e1m1.wad")


def read_segments(path):
    """the .fjm's segment table as (start, length, data_start, data_length) words -- the header
    only, so this costs no decompression"""
    raw = Path(path).read_bytes()
    magic, memory_width, version, segment_num = struct.unpack(
        _header_base_format, raw[:_header_base_size])
    if magic != FJ_MAGIC:
        raise ValueError("%s: bad magic 0x%x -- not an .fjm?" % (path, magic))
    off = _header_base_size
    if FJMVersion(version) != FJMVersion.BaseVersion:
        off += _header_extension_size
    segments = [struct.unpack(_segment_format,
                              raw[off + i * _segment_size:off + (i + 1) * _segment_size])
                for i in range(segment_num)]
    return memory_width, segments


def split_at(segments, pool_base_words):
    """{below, in_pool} -> (segments, payload words, lowest word, highest word)"""
    out = {}
    for name, part in (("below", [s for s in segments if s[0] < pool_base_words]),
                       ("in_pool", [s for s in segments if s[0] >= pool_base_words])):
        out[name] = (len(part), sum(s[3] for s in part),
                     min((s[0] for s in part), default=0),
                     max((s[0] + s[1] for s in part), default=0))
    return out


def probe_pool(memory_width, counts, widths, width_hist, alias, knobs):
    """a BlockPool that only PRICES: `_preallocate` runs in __init__, nothing is assembled"""
    return BlockPool(memory_width, knobs["pool_base"], counts=counts, widths=widths,
                     span_bits=knobs["span_bits"], alias=alias, spread=knobs["spread"],
                     spread_min_count=knobs["spread_min_count"],
                     max_slot_ops=knobs["max_slot_ops"], width_hist=width_hist,
                     width_buckets=knobs["width_buckets"], wants=None)


def pad_breakdown(pool, counts):
    """the block bits, in the four nested totals the PAD line differences -- all in BITS.

    Each follows exactly what `_block_bits` charges, so the mechanisms cannot drift from the sizes:

      demand    what the allocator hands out: `_block_bits` per group
      top       the highest bit any bucket's slots reach inside its block
      slots     what the slots themselves cover
      occupied  the slot each COUNTED table sits in

    demand - top is then the block's power-of-two round-up, top - slots the alignment between
    buckets, slots - occupied the unused slots, and occupied - (bits the .fjm emits) the slot-width
    padding plus the tables declined to inline.
    """
    ob = pool.op_bits
    totals = dict(demand=0, top=0, slots=0, occupied=0)
    for group in counts:
        if pool.width_buckets:
            layout, block = pool._bucket_layout(group)
        else:
            # the uniform path: one implicit bucket at offset 0, so the block IS its slots
            n_slots, slot_bits = pool._uniform_shape(group)
            block = n_slots * slot_bits
            layout = {slot_bits // ob: (0, n_slots, counts.get(group, 1))}
        totals["demand"] += block
        totals["top"] += max(off + n * so * ob for so, (off, n, _c) in layout.items())
        totals["slots"] += sum(n * so * ob for so, (_off, n, _c) in layout.items())
        totals["occupied"] += sum(c * so * ob for so, (_off, _n, c) in layout.items())
    return totals


def cache_args(knobs):
    """the three fields `_counts_sig` reads off build_blocked.py's parsed arguments"""
    return types.SimpleNamespace(tier=knobs["tier"], map=knobs["map"], wad=knobs["wad"])


def load_cache(cache_path, knobs, allow_stale=False):
    """the frozen counts, and whether their signature still matches this working tree.

    The signature hashes the emitter sources' BYTES (`build_blocked._counts_sig` reads
    `f.read_bytes()` over `src/doomfj/*.py` + `src/fj/*.fj`), so ANY byte movement in those files
    moves it -- a line-ending rewrite as surely as an edit, with `git diff` showing nothing in the
    first case. The block sizes depend only on the counts, the widths and the histogram, so a
    signature miss does not make the arithmetic wrong; it makes it a claim about WHICHEVER program
    those counts were taken from. Hence: refuse by default, price it loudly under --allow-stale.

    Returns (counts or None, one of HIT / STALE / MISSING / UNREADABLE). Callers must handle None
    on every one of those states -- see the selftest, which reports a FAIL rather than raising.
    """
    args = cache_args(knobs)
    if not Path(cache_path).exists():
        return None, "MISSING"
    import gzip
    import json
    try:
        with gzip.open(cache_path, "rt", encoding="utf-8") as fh:
            stored = json.load(fh)["sig"]
    except Exception as exc:                                          # noqa: BLE001
        print("       cache at %s exists but does not read as a signed counts blob (%s)"
              % (cache_path, exc), flush=True)
        return None, "UNREADABLE"
    tree = _counts_sig(args)
    fresh = _load_counts(cache_path, args)
    if fresh is not None:
        return fresh, "HIT"
    print("       cache sig src=%s, this tree hashes to src=%s"
          % (stored.get("src"), tree.get("src")), flush=True)
    if not allow_stale:
        return None, "STALE"
    # Pricing a stale cache is a deliberate bypass, so make ONE call see a matching signature
    # rather than re-implementing _load_counts' normalisation here (which would be free to drift).
    # `_load_counts` then prints its own `counts cache HIT` -- against the FORCED signature, so say
    # so before it does, or the two lines read as a contradiction.
    print("       --allow-stale: forcing the cache's OWN signature; the `counts cache HIT` below "
          "is that forced match, NOT this tree.", flush=True)
    import build_blocked
    original = build_blocked._counts_sig
    build_blocked._counts_sig = lambda _a: stored
    try:
        frozen = _load_counts(cache_path, args)
    finally:
        build_blocked._counts_sig = original
    if frozen is None:
        return None, "UNREADABLE"
    print("       --allow-stale: PRICED ANYWAY. These block sizes are the cached program's.",
          flush=True)
    return frozen, "STALE"


def report(fjm_path, cache_path, knobs):
    size = fjmsize.read_fjm_size(fjm_path)
    memory_width, segments = read_segments(fjm_path)
    W = memory_width
    print("FJM    %s" % size, flush=True)
    seg_words = sum(s[3] for s in segments)
    print("       segment table sums to the payload: %s (%s words)"
          % ("yes" if seg_words == size.data_words else "NO", format(seg_words, ",")), flush=True)

    pool_base_words = knobs["pool_base"] // W
    window_end_words = min(1 << W, knobs["pool_base"] + knobs["span_bits"]) // W
    parts = split_at(segments, pool_base_words)
    below_n, below_words, _, below_end = parts["below"]
    pool_n, pool_words, pool_lo, pool_hi = parts["in_pool"]
    print("SPLIT  below word %s: %s segment%s, %s payload words, ending at word %s"
          % (format(pool_base_words, ","), format(below_n, ","), "" if below_n == 1 else "s",
             format(below_words, ","), format(below_end, ",")), flush=True)
    print("       in the pool   : %s segments, %s payload words, words %s..%s"
          % (format(pool_n, ","), format(pool_words, ","), format(pool_lo, ","),
             format(pool_hi, ",")), flush=True)
    gap = pool_base_words - below_end
    print("GAP    program end -> pool base: %s words" % format(gap, ","), flush=True)
    print("POOL   base word %s, window ends word %s (--pool-base %s --span-bits %s); %s words of "
          "the window above the image"
          % (format(pool_base_words, ","), format(window_end_words, ","),
             hex(knobs["pool_base"]), hex(knobs["span_bits"]),
             format(window_end_words - pool_hi, ",")), flush=True)

    cache, state = load_cache(cache_path, knobs, allow_stale=knobs.get("allow_stale", False))
    if cache is None:
        print("PAD    counts cache %s (%s) -- the block sizes are not priced. Re-run with "
              "--allow-stale to price it anyway, or `build_blocked.py --preflight-only` to "
              "re-count." % (state, cache_path), flush=True)
        return size, parts, None
    pool = probe_pool(W, cache["counts"], cache["widths"], cache["width_hist"],
                      cache.get("alias"), knobs)
    demand = sum(pool._block_bits(g) for g in cache["counts"]) // W
    extent = pool._used // W
    capacity = (min(1 << W, knobs["pool_base"] + knobs["span_bits"]) - knobs["pool_base"]) // W
    print("BLOCKS %s of %s groups placed (%s broken); demand %s words, extent %s words, capacity "
          "%s words (%.1f%% used)"
          % (format(len(pool.groups), ","), format(len(cache["counts"]), ","),
             format(len(pool.broken_groups), ","), format(demand, ","), format(extent, ","),
             format(capacity, ","), 100.0 * demand / capacity), flush=True)
    broken = len(pool.broken_groups)
    print("       demand == extent, i.e. no hole in front of any block: %s%s"
          % ("yes" if demand == extent else "NO",
             "" if not broken else
             " (and with %s groups broken the two sums are over DIFFERENT blocks, so this "
             "equality decides nothing either way)" % format(broken, ",")), flush=True)
    print("       extent == the image's span above the pool base, i.e. the image ends at the "
          "allocator's cursor: %s"
          % ("yes" if extent == pool_hi - pool_base_words else "NO"), flush=True)
    pad = demand - pool_words
    print("PAD    %s - %s = %s words INSIDE the blocks, by mechanism:"
          % (format(demand, ","), format(pool_words, ","), format(pad, ",")), flush=True)
    t = pad_breakdown(pool, cache["counts"])
    terms = (("block power-of-two round-up", t["demand"] - t["top"], "--width-buckets only"),
             ("alignment between buckets", t["top"] - t["slots"], "structurally 0"),
             ("unused slots", t["slots"] - t["occupied"], "count rounded up, times --spread"),
             ("slot width + declined tables", t["occupied"] - pool_words * W, ""))
    for name, bits, why in terms:
        print("       %-30s %14s words  %5.1f%%%s"
              % (name, format(bits // W, ","), 100.0 * bits / (pad * W) if pad else 0.0,
                 ("  (%s)" % why) if why else ""), flush=True)
    print("       the four terms sum to the pad: %s"
          % ("yes" if sum(b for _n, b, _w in terms) == pad * W else "NO"), flush=True)
    print("SUM    span - data = %s - %s = %s = %s gap + %s pad: %s"
          % (format(size.span_words, ","), format(size.data_words, ","),
             format(size.span_words - size.data_words, ","), format(gap, ","), format(pad, ","),
             "yes" if size.span_words - size.data_words == gap + pad else "NO"), flush=True)
    return size, parts, (demand, extent, capacity, pad)


# ------------------------------------------------------------------------------------------------
# R9. C1-C3 are true negative controls: each FAILS a plausible broken version of this script
# (constants instead of a read; a demand that ignores the cache; a cache from another program).
# C4 is the vacuity check the measurement process asks for, and is labelled as such.
# ------------------------------------------------------------------------------------------------

def selftest(fjm_path, cache_path, knobs):
    import gzip
    import json
    import tempfile
    fails = []

    def check(name, cond, detail=""):
        print("  %-62s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("poolmap selftest -- C1..C3 and C5 are the negative controls; C4 is the vacuity check.",
          flush=True)
    print("  cache signature is %s" % _counts_sig(cache_args(knobs)), flush=True)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # C1  THE SPLIT READER READS THE FILE. Synthesise an .fjm whose split is known and is
        #     nothing like blocked25's, and require those numbers back.
        synth = tmp / "synth.fjm"
        segs = [(0, 10, 0, 10), (1000, 5, 10, 5), (1010, 7, 15, 7)]
        synth.write_bytes(fjmsize._synth_fjm(32, segs, data_words=22))
        _, got = read_segments(synth)
        parts = split_at(got, 1000)
        check("C1 the synthetic split comes back as the SYNTHETIC one",
              parts["below"] == (1, 10, 0, 10) and parts["in_pool"] == (2, 12, 1000, 1017),
              "below=%s in_pool=%s" % (parts["below"], parts["in_pool"]))
        check("C1 it differs from the binary under test (a constant would fail here)",
              parts["below"][1] != 27_527_046)

        # C3  A STALE CACHE IS REFUSED. Same counts, one field of the signature changed -- and the
        #     mirror image, a copy signed for THIS tree, which must be accepted so the check is
        #     shown to separate rather than to refuse everything.
        if Path(cache_path).exists():
            # a cache that exists but does not parse is a reported FAIL here too, not a traceback
            try:
                with gzip.open(cache_path, "rt", encoding="utf-8") as fh:
                    blob = json.load(fh)
            except Exception as exc:                                  # noqa: BLE001
                blob = None
                check("C3 the counts cache at %s reads as a signed blob" % cache_path, False,
                      str(exc))
            if blob is not None:
                for name, sig in (("stale", dict(blob["sig"], src="0" * 16)),
                                  ("fresh", _counts_sig(cache_args(knobs)))):
                    blob["sig"] = sig
                    with gzip.open(tmp / (name + ".json.gz"), "wt", encoding="utf-8") as fh:
                        json.dump(blob, fh)
                check("C3 a cache signed for another program is REFUSED",
                      _load_counts(tmp / "stale.json.gz", cache_args(knobs)) is None)
                check("C3 a cache signed for THIS tree is accepted (the check separates)",
                      _load_counts(tmp / "fresh.json.gz", cache_args(knobs)) is not None)
                _, state = load_cache(cache_path, dict(knobs, allow_stale=False))
                print("  (the real cache at %s is %s against this working tree)"
                      % (cache_path, state), flush=True)
        else:
            check("C3 SKIPPED -- no counts cache at %s" % cache_path, True)

    if not Path(cache_path).exists():
        print("", flush=True)
        print("SELFTEST %s (C2/C4 skipped: no counts cache)"
              % ("PASS" if not fails else "FAIL"), flush=True)
        return 1 if fails else 0

    # the controls price the cache either way -- but a cache that exists and still does not LOAD
    # (truncated, half-written, not a counts blob) must be a reported FAIL, never a traceback:
    # a control set that raises is one whose verdict line never prints.
    cache, state = load_cache(cache_path, knobs, allow_stale=True)
    if cache is None:
        check("C2/C4 the counts cache at %s loads" % cache_path, False, state)
        print("", flush=True)
        print("SELFTEST FAIL: " + ", ".join(fails), flush=True)
        return 1
    pool = probe_pool(32, cache["counts"], cache["widths"], cache["width_hist"],
                      cache.get("alias"), knobs)
    demand = sum(pool._block_bits(g) for g in cache["counts"])

    # C2  THE DEMAND READS THE COUNTS. Shrink the biggest group to a single table.
    biggest = max(cache["counts"], key=lambda g: (pool._block_bits(g), g))
    before = pool._block_bits(biggest)
    shrunk = dict(cache["counts"])
    shrunk[biggest] = 1
    hist2 = dict(cache["width_hist"])
    if biggest in hist2:
        widest = max(hist2[biggest])
        hist2[biggest] = {widest: 1}
    pool2 = probe_pool(32, shrunk, cache["widths"], hist2, cache.get("alias"), knobs)
    demand2 = sum(pool2._block_bits(g) for g in shrunk)
    after = pool2._block_bits(biggest)
    check("C2 dropping one group's count moves the demand by that block's size",
          demand - demand2 == before - after and before > after,
          "%s -> %s words for %s" % (format(before // 32, ","), format(after // 32, ","),
                                     biggest[:40]))
    check("C2 the demand MOVED (a cache-blind demand would not)", demand != demand2,
          "%s -> %s words" % (format(demand // 32, ","), format(demand2 // 32, ",")))

    # C4  NON-VACUITY, on the real artifacts.
    check("C4 groups > 0", len(cache["counts"]) > 0, format(len(cache["counts"]), ","))
    check("C4 demand > 0", demand > 0, "%s words" % format(demand // 32, ","))
    if Path(fjm_path).exists():
        _, segments = read_segments(fjm_path)
        parts = split_at(segments, knobs["pool_base"] // 32)
        check("C4 the binary emits words INTO the pool", parts["in_pool"][1] > 0,
              "%s words" % format(parts["in_pool"][1], ","))
        check("C4 the pad is not negative (demand covers what was emitted)",
              demand // 32 - parts["in_pool"][1] >= 0)
        real = pad_breakdown(pool, cache["counts"])
        emitted = parts["in_pool"][1] * 32
        check("C5 the breakdown's total IS the demand the PAD line prices",
              real["demand"] == demand,
              "%s vs %s words" % (format(real["demand"] // 32, ","), format(demand // 32, ",")))
        check("C5 no term is negative (demand >= top >= slots >= occupied >= emitted)",
              real["demand"] >= real["top"] >= real["slots"] >= real["occupied"] >= emitted)
    else:
        check("C4 SKIPPED -- no binary at %s" % fjm_path, True)

    # C5  THE PAD'S MECHANISMS ARE MEASURED, NOT APPORTIONED. One group, two width buckets, worked
    #     out by hand at op_bits = 2*32 = 64:
    #       width 1 x3 -> slot_ops 1, slots 1<<(3-1).bit_length() = 4, bits 4*1*64 =  256
    #       width 5 x1 -> slot_ops 8, slots 1<<(1-1).bit_length() = 1, bits 1*8*64 =  512
    #       biggest-first: the 512 bucket at offset 0, the 256 bucket at offset 512, offset 768,
    #       block = 1 << (768-1).bit_length() = 1024.
    #     So round-up 1024-768 = 256, alignment 768-768 = 0, unused slots 768-(512+3*64) = 64,
    #     occupied 704. A breakdown that charged the whole pad to unused slots reports a 0 round-up.
    synth = dict(knobs, pool_base=1 << 20, span_bits=1 << 20, spread=1, spread_min_count=1 << 30,
                 max_slot_ops=512, width_buckets=True)
    sp = probe_pool(32, {"g": 4}, {"g": 5}, {"g": {1: 3, 5: 1}}, {}, synth)
    b = pad_breakdown(sp, {"g": 4})
    got = (b["demand"], b["demand"] - b["top"], b["top"] - b["slots"],
           b["slots"] - b["occupied"], b["occupied"])
    check("C5 the hand-computed block breaks down as (1024, 256, 0, 64, 704) bits",
          got == (1024, 256, 0, 64, 704), "got %s" % (got,))
    uni = probe_pool(32, {"g": 4}, {"g": 5}, {"g": {1: 3, 5: 1}}, {},
                     dict(synth, width_buckets=False))
    bu = pad_breakdown(uni, {"g": 4})
    check("C5 with --no-width-buckets the round-up term vanishes (it names --width-buckets)",
          bu["demand"] - bu["top"] == 0 and bu["demand"] == 4 * 8 * 64,
          "demand %s bits, round-up %s bits" % (bu["demand"], bu["demand"] - bu["top"]))

    print("", flush=True)
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked27.fjm")
    ap.add_argument("--counts-cache", default="scratchpad/12m/_counts_game.json.gz")
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=SHIP_GATE["pool_base"])
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=SHIP_GATE["span_bits"])
    ap.add_argument("--spread", type=int, default=SHIP_GATE["spread"])
    ap.add_argument("--spread-min-count", type=int, default=SHIP_GATE["spread_min_count"])
    ap.add_argument("--max-slot-ops", type=int, default=SHIP_GATE["max_slot_ops"])
    ap.add_argument("--no-width-buckets", action="store_true")
    ap.add_argument("--tier", default=SHIP_GATE["tier"])
    ap.add_argument("--map", default=SHIP_GATE["map"])
    ap.add_argument("--wad", default=SHIP_GATE["wad"])
    ap.add_argument("--allow-stale", action="store_true",
                    help="price a counts cache whose signature no longer matches the working tree. "
                         "The signature hashes the emitter sources' bytes, so a line-ending sweep "
                         "moves it without the program changing (ship-gate 1b saw this); the "
                         "block sizes are then the CACHED program's, and the run says so.")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    knobs = dict(pool_base=a.pool_base, span_bits=a.span_bits, spread=a.spread,
                 spread_min_count=a.spread_min_count, max_slot_ops=a.max_slot_ops,
                 width_buckets=not a.no_width_buckets, tier=a.tier, map=a.map, wad=a.wad,
                 allow_stale=a.allow_stale)
    fjm = Path(a.fjm) if Path(a.fjm).is_absolute() else ROOT / a.fjm
    cache = Path(a.counts_cache) if Path(a.counts_cache).is_absolute() else ROOT / a.counts_cache
    if a.selftest:
        return selftest(fjm, cache, knobs)
    report(fjm, cache, knobs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
