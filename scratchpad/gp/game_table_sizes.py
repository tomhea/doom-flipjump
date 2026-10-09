"""game_table_sizes.py -- MEASURED word sizes of the M7 gameplay rungs' tables and cells (P4.0 .. P7), for DESIGN.md
section 1.2's span ledger (issues #119 item 3, #121 item 13, #123 R4). No build, no run: label addresses only.

    python scratchpad/gp/game_table_sizes.py [--labels scratchpad/12m/atlas/blocked51.labels.tsv.gz]
                                             [--gen-dir <the build's generated parts>] [--md] [--selftest]

Addresses in the label table are BITS; a word is 32 bits, an fj op 2 words. Every size is a difference of two label
addresses of the shipped image (blocked51 by default), so no model:
  * a D4 table (`lut_generator.generate_dispatch_table_fj`, per-entry): from its `.init` call's first op (2 words
    before `<t>.res`, or before `<t>.dsp` for a 1-nibble table) to `<t>.init---end` -- the result vector, the
    dispatch op, the ALIGNMENT PAD up to `switch` (reported apart), `switch` (pad entries x 1 op), the handlers
    (pad x (result nibbles + 1) ops) and the clean-up. The table's entry count and result width are DERIVED from
    the label distances (switch -> handlers -> clean), and `--selftest` checks them against the generated text's own
    header line (`// dispatch table "t": N entries, ... R-nibble result`) -- an independent source;
  * device data (playpal<k>) and code regions (the HUD tail, the missile cell set): label to label;
  * the cells: every top-level cell the rung's emitters declare (their `*_decls` lists, the same lists
    build.game_screen_persisted_decls reads), each measured label to next label.
The tables sit INLINE in this image (all below the block pool's base); the pool's own pads are poolmap.py's.

R9 (`--selftest`): the derivation must agree with every header (and fail on two mutants: a table's `clean` label moved
by one op, and a header's entry count changed), and the cell measure must equal 2 x the declared nibbles for every
numeric `hex.vec` (and fail on a mutated declaration).
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DEFAULT_LABELS = ROOT / "scratchpad/12m/atlas/blocked51.labels.tsv.gz"
DEFAULT_GEN = ROOT.parent / "doom-m7t/build/generated_doom_e1m1_blocked51"
WORD_BITS = 32
POOL_WORD = 0x60000000 // WORD_BITS
# (table, rung) -- the D4 tables the gameplay rungs added, in rung order
TABLES = (("ammobcd", "P4.1"), ("aimr", "P4.2a"), ("wpo", "P4.2a"), ("dmrnd", "P4.2a"),
          ("mbul", "P5"), ("trclaw", "P5"), ("sgbite", "P5"), ("dpsav", "P5"), ("palidx", "P5"), ("fxrnd", "P5"),
          ("pjst", "P5"), ("mobview", "P5"),
          ("barnext", "P6+P7"), ("bk10", "P6+P7"), ("bonpal", "P6+P7"), ("amcap", "P6+P7"), ("nkleaf", "P6+P7"),
          ("pkxyz", "P6+P7"), ("barview", "P6+P7"))
HEADER = re.compile(r'^// dispatch table "([A-Za-z0-9_]+)": (\d+) entries, per-entry mode, (\d+)-nibble result')


def load(path):
    """(top-level labels {name: word}, every label's word sorted) from a label table"""
    top, words = {}, []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if not addr.isdigit():
                continue
            w = int(addr) // WORD_BITS
            words.append(w)
            if "---" not in name and not re.match(r"f\d+:l\d+:", name):
                top.setdefault(name, w)
    return top, sorted(set(words))


def table_regions(path):
    """{table: {part: word}} -- the init-call labels of every per-entry dispatch table"""
    pat = re.compile(r"^(?:f\d+:l\d+:)?([A-Za-z0-9_]+)\.(?:init---(switch|handlers|clean|end)|(res|dsp))$")
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if name.count("---") > 1 or not addr.isdigit():
                continue
            m = pat.match(name)
            if m:
                out.setdefault(m.group(1), {})[m.group(2) or m.group(3)] = int(addr) // WORD_BITS
    return out


def table_size(t, reg):
    """{words, pad (alignment words), entries (the padded switch), rn (result nibbles)} from the labels alone"""
    r = reg[t]
    first = (r["res"] if "res" in r else r["dsp"]) - 2                # the init's `;end` op
    one = "handlers" not in r                                           # a 1-nibble table packs into `switch`
    entries = ((r["clean"] if one else r["handlers"]) - r["switch"]) // 2
    rn = 1 if one else (r["clean"] - r["handlers"]) // (2 * entries) - 1
    assert one or (r["clean"] - r["handlers"]) == 2 * entries * (rn + 1), (t, r)
    return {"words": r["end"] - first, "pad": r["switch"] - (r["dsp"] + 2), "entries": entries, "rn": rn,
            "first": first}


def headers(gen_dir):
    """{table: (entries, result nibbles)} from the generated parts' header comments"""
    out = {}
    for f in sorted(Path(gen_dir).glob("*.fj")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                m = HEADER.match(line)
                if m:
                    out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return out


def next_pow2(n):
    return 1 << max(0, (n - 1).bit_length())


def check_tables(reg, hdr):
    """the label-derived (padded entries, result nibbles) against each header: [mismatch, ...]"""
    bad = []
    for t, _r in TABLES:
        if t not in reg:
            continue
        s = table_size(t, reg)
        if t not in hdr:
            bad.append((t, "no header"))
        elif (s["entries"], s["rn"]) != (next_pow2(hdr[t][0]), hdr[t][1]):
            bad.append((t, (s["entries"], s["rn"]), hdr[t]))
    return bad


def region(top, words, lo, hi_label=None, hi=None):
    """words from label `lo` to label `hi_label` (or word `hi`)"""
    a = top[lo]
    b = top[hi_label] if hi_label else hi
    return b - a


def size_of(name, top, words):
    """a top-level label's words to the next label of the image"""
    import bisect
    a = top[name]
    i = bisect.bisect_right(words, a)
    return words[i] - a


def cell_groups():
    """[(rung, module, [decl, ...])] -- what each rung's emitters declare (the game tier's own calls)"""
    from doomfj import (aimcode, barrelcode, damagecode, hud, hudcode, hurtcode, lootcode, noisecode, projcode,
                        restartcode)
    from doomfj import weaponcode as WC
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import BOOT_SKILL, SKILLS
    from doomfj.world import World
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    w = World(mw, "E1M1")
    n = w.layout.nmon
    return [
        ("P4.0", "hudcode", hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START)))),
        ("P4.1", "weaponcode", WC.weapon_decls(WC.level_start(mw, "E1M1"), WC.weapon_states(), WC.overlay_frames())
         + WC.weapon_const_decls()),
        ("P4.2a", "weaponcode (the shot)", WC.shot_decls()),
        ("P4.2a", "aimcode", aimcode.decls(True)),
        ("P4.2a", "damagecode", damagecode.field_decls(w.schema, n, {f: [0] * n for f in damagecode.P42_FIELDS})
         + damagecode.DM_INTERFACE + damagecode.DM_WINDOW + damagecode.DM_SCRATCH + damagecode.DM_FULL_SCRATCH),
        ("P4.2b", "noisecode", noisecode.noise_decls(w)),
        ("P5", "hurtcode", hurtcode.hurt_decls(hurtcode.level_start(w)) + ["pal_bk: hex.vec 1"]),
        ("P5", "projcode", projcode.pool_decls(puffs=True)),
        ("P6+P7", "barrelcode", barrelcode.decls(w, BOOT_SKILL)),
        ("P6+P7", "lootcode", lootcode.loot_decls(lootcode.level_start(w))),
        ("P6+P7", "restartcode", restartcode.game_decls(SKILLS.index(BOOT_SKILL))),
    ]


def decl_name_nibbles(d):
    """`name: hex.vec N[, v]` -> (name, N or None when symbolic)"""
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_.]*):\s*hex\.vec\s+([^,\s]+)", d)
    if not m:
        return None, None
    return m.group(1), int(m.group(2)) if m.group(2).isdigit() else None


def measure(labels, gen_dir=None, groups=None):
    top, words = load(labels)
    reg = table_regions(labels)
    # every table's first op is a boundary too (the init's `;end` op carries no label: without this the label
    # before a table -- playpal12 before fxrnd -- would take that op)
    words = sorted(set(words) | {table_size(t, reg)["first"] for t in reg if {"dsp", "switch", "end"} <= set(reg[t])})
    rows = []
    for t, rung in TABLES:
        if t not in reg:
            rows.append((rung, t, "not in this image", None, None, None))
            continue
        s = table_size(t, reg)
        assert s["first"] < POOL_WORD
        rows.append((rung, t, "D4 table: %d-entry switch x %d-nibble result" % (s["entries"], s["rn"]),
                     s["words"], s["pad"], None))
    pp = sorted((n for n in top if re.fullmatch(r"playpal\d+", n)), key=lambda n: int(n[7:]))
    for n in pp:
        k = int(n[7:])
        rows.append(("P5" if k <= 8 else "P6+P7", n, "device data: 256 RGB", size_of(n, top, words), 0, None))
    if "e1m1_mc6_n0" in top:
        mc = [n for n in top if n.startswith("e1m1_mc6")]
        lo = min(top[n] for n in mc)
        end = max(top[n] for n in mc)
        rows.append(("P5", "e1m1_mc6_* (the missile cell set)", "code: %d labels, e1m1_mc6_n0 .. the label after "
                     "e1m1_mc6_end" % len(mc), size_of_word(end, words) + end - lo, 0, None))
    if "bsp_done" in top and "frame_end" in top:
        rows.append(("P4.0", "the HUD tail (weapon and flash overlays, the bar's columns)",
                     "code: bsp_done .. frame_end", top["frame_end"] - top["bsp_done"], 0, None))
    cells = []
    for rung, mod, decls in (groups if groups is not None else cell_groups()):
        tot, k, miss = 0, 0, []
        for d in decls:
            name, nib = decl_name_nibbles(d)
            if name is None:
                continue
            if name not in top:
                miss.append(name)
                continue
            tot += size_of(name, top, words)
            k += 1
        cells.append((rung, mod, k, tot, miss))
    return rows, cells, reg, top, words


def size_of_word(a, words):
    import bisect
    i = bisect.bisect_right(words, a)
    return words[i] - a


def check_cells(groups, top, words):
    """every numeric `hex.vec N` decl measures 2N words (one op per nibble): [mismatch, ...]"""
    bad = []
    for _rung, _mod, decls in groups:
        for d in decls:
            name, nib = decl_name_nibbles(d)
            if name is None or nib is None or name not in top:
                continue
            got = size_of(name, top, words)
            if got != 2 * nib:
                bad.append((name, nib, got))
    return bad


def report(rows, cells, md=False):
    if md:
        print("| rung | table / region | what | words | of which align pad |")
        print("|---|---|---|---:|---:|")
        for rung, t, what, wds, pad, _ in rows:
            print("| %s | `%s` | %s | %s | %s |" % (rung, t, what, "-" if wds is None else format(wds, ","),
                                                     "-" if not pad else format(pad, ",")))
        print("")
        print("| rung | module (cells) | labels | words |")
        print("|---|---|---:|---:|")
        for rung, mod, k, tot, miss in cells:
            print("| %s | `%s` | %d | %s |" % (rung, mod, k, format(tot, ",")))
        return
    for rung, t, what, wds, pad, _ in rows:
        print("%-6s %-58s %10s  pad %8s  %s" % (rung, t, "-" if wds is None else format(wds, ","),
                                                 format(pad or 0, ","), what))
    for rung, mod, k, tot, miss in cells:
        print("%-6s cells %-52s %10s  (%d labels%s)" % (rung, mod, format(tot, ","), k,
                                                        "; not in the image: %s" % miss if miss else ""))
    print("total tables + data + code regions: %s words; cells: %s words"
          % (format(sum(r[3] or 0 for r in rows), ","), format(sum(c[3] for c in cells), ",")))


def selftest(labels, gen_dir):
    if not Path(gen_dir).is_dir():
        print("SELFTEST SKIPPED: no generated parts at %s (--gen-dir)" % gen_dir)
        return 2
    rows, cells, reg, top, words = measure(labels, gen_dir)
    hdr = headers(gen_dir)
    bad = check_tables(reg, hdr)
    print("tables vs their headers: %d checked, %d mismatched %s" % (
        sum(1 for t, _ in TABLES if t in reg), len(bad), bad))
    ok = not bad and sum(1 for t, _ in TABLES if t in reg) >= 18
    # mutant 1: aimr's clean label one op later -> the derivation must disagree
    mreg = {t: dict(r) for t, r in reg.items()}
    mreg["aimr"]["clean"] += 2
    try:
        m1 = bool(check_tables(mreg, hdr))
    except AssertionError:
        m1 = True
    # mutant 2: a header's entry count changed (pjst: 51 -> 65 entries, a different power of two)
    m2 = bool(check_tables(reg, dict(hdr, pjst=(65, hdr["pjst"][1]))))
    groups = cell_groups()
    cbad = check_cells(groups, top, words)
    print("cells: every numeric hex.vec measures 2N words: %d mismatched %s" % (len(cbad), cbad[:5]))
    mg = [(r, m, [re.sub(r"hex\.vec (\d+)", lambda q: "hex.vec %d" % (int(q.group(1)) + 1), d, count=1)
                  for d in ds]) for r, m, ds in groups[:1]]
    m3 = bool(check_cells(mg, top, words))
    print("controls: moved `clean` caught %s; changed header caught %s; widened decl caught %s" % (m1, m2, m3))
    ok = ok and not cbad and m1 and m2 and m3
    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--gen-dir", default=str(DEFAULT_GEN))
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.labels, a.gen_dir)
    rows, cells, *_ = measure(a.labels, a.gen_dir)
    report(rows, cells, a.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
