"""The engine's three inputs, derived from a game-tier binary's label table -> <WORK>:

  objects.json / map.txt   COARSE OBJECTS: word ranges of OPAQUE code, each with an id (1..127).
                           Unlisted words are TRANSPARENT (id 0): the stl runtime and tables part
                           [0, __hot_end), the state part, and everything past the reset code (the
                           wflip area and the block pool). Data cells (`;v*dw`, f == 0) are
                           transparent wherever they sit.
  labels.u32               every label's word: a LABELLED opaque op is a real program point and may
                           become the owner from anywhere; an unlabelled one only from nearby.
  marks.txt / marks.json   PHASE MARKERS: label words whose every execution is logged with the op
                           index and a snapshot of the object counters.

    python maps.py [--labels atlas/blocked27.labels.tsv.gz] [--gen-dir build/generated_doom_e1m1_blocked27]

The object boundaries are LABEL NAMES of the game tier's generated program, so the map follows a
rebuilt binary as long as those names exist; the part boundaries come from the generated parts.
"""
import argparse
import json
import re

import numpy as np

from common import POOL_BASE_WORD, ROOT, default_fjm, default_labels, labels, work_dir

PART_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*):")
ELEM_RE = re.compile(r"^(f\d+):l(\d+):")


def part_starts(gen_dir, byname):
    """{part file stem: lowest word of a top-level label it defines}"""
    out = {}
    for f in sorted(gen_dir.glob("e1m1_0*.fj")):
        lo = None
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                m = PART_RE.match(line)
                if m and m.group(1) in byname:
                    a = byname[m.group(1)]
                    lo = a if lo is None or a < lo else lo
        if lo is not None:
            out[f.stem] = lo
    return out


def build(labels_path=None, gen_dir=None):
    la, ln = labels(labels_path)
    byname = {}
    for a, n in zip(la.tolist(), ln):
        byname.setdefault(n, a)
    gen_dir = gen_dir or (ROOT / "build" / ("generated_" + default_fjm().stem))
    parts = part_starts(gen_dir, byname)
    need = ["e1m1_03_segconsts", "e1m1_05_state", "e1m1_06_banks"]
    missing = [p for p in need if p not in parts]
    if missing:
        raise SystemExit("generated parts not found in %s: %s" % (gen_dir, missing))

    # the statement after sim.bind_things in the main part: the first label of a LATER line there
    bind = [n for n in ln if "sim.bind_things(" in n.split("---")[0]]
    if not bind:
        raise SystemExit("no sim.bind_things expansion in the label table")
    m = ELEM_RE.match(bind[0])
    fmain, bline = m.group(1), int(m.group(2))
    lo, hi = byname["simcollide_skip"], byname["dsc_done"]
    after_bind = min(a for a, n in zip(la.tolist(), ln)
                     if lo < a < hi and ELEM_RE.match(n) and ELEM_RE.match(n).group(1) == fmain
                     and int(ELEM_RE.match(n).group(2)) > bline)
    below_pool = la[la < POOL_BASE_WORD]
    reset_end = int(below_pool.max()) + 64      # the last reset label, its exact_xor tail, ;__hot_end

    b = [
        ("input (kb.poll x8 + key decode)", byname["__hot_end"]),
        ("menu", byname["menu_frame"]),
        ("doors (use + 13 door tics)", byname["do_world"]),
        ("move sim (turn/move/finesine/mul)", byname["simtl_yes"]),
        ("collision (4x vx/vy + dsccs fcall + try_move)", byname["simcollide"]),
        ("sim.bind_things", byname["simcollide_skip"]),
        ("view setup (wnt, wedge_setup)", after_bind),
        ("frame glue (collines begin, bsp jump)", byname["dsc_done"]),
        ("bad/padding", byname["bad"]),
        ("seg_pass1_leaf", byname["seg_pass1_leaf"]),
        ("seg_pass1_ts_leaf", byname["seg_pass1_ts_leaf"]),
        ("thing_leaf", byname["thing_leaf"]),
        ("thing_leaf_b", byname["thing_leaf_b"]),
        ("thing_pass_leaf", byname["thing_pass_leaf"]),
        ("seg_pass2_leaf", byname["seg_pass2_leaf"]),
        ("bbgate_leaf", byname["bbgate_leaf"]),
        ("segconsts (per-seg/thing const blocks)", parts["e1m1_03_segconsts"]),
        ("bspcode walk (nodes, pos_leaf, ss code)", byname["e1m1_bspcode_walk"]),
        ("dsc walk (eye point-location)", byname["e1m1_dsc_walk"]),
        ("dsccs walk (collision point-location)", byname["e1m1_dsccs_walk"]),
        ("ptloc_walk (M14-e point location)", byname["ptloc_walk"]),
        (None, parts["e1m1_05_state"]),                     # the state part: transparent
        ("banks head (vars, sprbkt tables)", parts["e1m1_06_banks"]),
        ("vpb bands-as-code (plane bands)", byname["vpb_blk__"]),
        ("banks tail (vql/vqh, yslope, zlight)", byname["vql_blk__"]),
        ("m1_reset code", byname["m1_reset"]),
        (None, reset_end),                                  # wflip area + block pool: transparent
    ]
    for (n0, a0), (n1, a1) in zip(b, b[1:]):
        if not a0 < a1:
            raise SystemExit("object boundaries out of order: %s %d >= %s %d" % (n0, a0, n1, a1))
    wd = work_dir()
    names, lines, oid = {}, [], 0
    for (n0, a0), (_n1, a1) in zip(b, b[1:]):
        if n0 is None:
            continue
        oid += 1
        names[oid] = {"name": n0, "lo": int(a0), "hi": int(a1)}
        lines.append("%d %d %d" % (a0, a1, oid))
    (wd / "map.txt").write_text("\n".join(lines) + "\n", encoding="ascii")
    (wd / "objects.json").write_text(json.dumps(names, indent=1), encoding="ascii")
    words = np.unique(la.astype(np.uint32))
    words.tofile(str(wd / "labels.u32"))

    # phase markers (id -> label); the analyses pair them into spans (phases.py)
    B = bind[0].split("---")[0] + "---"
    # the dirty path's `hex.write_hex 4, sptr, ptss` runs right after ptloc_walk returns; it is the
    # only write_hex in bind_things
    wh = [a for a, n in zip(la.tolist(), ln)
          if n.startswith(B) and a < reset_end and ":hex.write_hex(" in n.split("---")[1]]
    after_ptloc = min(wh) if wh else None
    alive = [a for a, n in zip(la.tolist(), ln)
             if "sim.thing_pass(" in n.split("---")[0] and n.endswith("---alive") and a < reset_end]
    M = [(1, "__hot_end", "frame start (input)"), (2, "sa_nf", "key decode"), (3, "menu_frame", "menu"),
         (4, "do_world", "doors"), (5, "dr12_done", "turn/move"), (6, "simcollide", "collision start"),
         (7, "cmh_vyd", "try H"), (8, "cma_vyd", "try A"), (9, "cmb_vyd", "try B"), (10, "cmc_vyd", "try C"),
         (11, "e1m1_dsccs_walk", "dsccs walk"), (12, "e1m1_cs_seeded", "dsccs done"),
         (13, "cmv_done", "collision done"), (14, "simmv_done", "post-move vx/vy"),
         (15, "simcollide_skip", "bind_things"), (16, after_bind, "view setup"),
         (17, "e1m1_dsc_walk", "dsc walk"), (18, "dsc_done", "dsc done"),
         (19, "e1m1_bspcode_walk", "render walk"), (20, "bsp_done", "render done"), (21, "m1_reset", "reset"),
         (22, "ptloc_walk", "ptloc walk"), (23, after_ptloc, "ptloc done (write_hex)"),
         (24, B + "dirty", "bind dirty"), (25, B + "clean", "bind clean"), (26, B + "bl", "bind loop head"),
         (30, "seg_pass1_leaf", "seg_pass1 call"), (31, "seg_pass1_ts_leaf", "seg_pass1_ts call"),
         (32, "thing_leaf", "thing_leaf call"), (33, "thing_leaf_b", "thing_leaf_b call"),
         (34, "thing_pass_leaf", "thing_pass call"), (35, "seg_pass2_leaf", "seg_pass2 call"),
         (36, "bbgate_leaf", "bbgate call"), (37, "e1m1_bspcode_pos_leaf", "pos_leaf call"),
         (38, min(alive) if alive else None, "thing_pass alive (thing loaded)")]
    out, meta = [], {}
    for i, lab, nm in M:
        a = lab if isinstance(lab, int) or lab is None else byname.get(lab)
        if a is None:
            print("  marker %d (%s) not found -- skipped" % (i, nm))
            continue
        out.append("%d %d" % (a, i))
        meta[i] = {"name": nm, "label": lab if isinstance(lab, str) else "word%d" % a, "word": int(a)}
    (wd / "marks.txt").write_text("\n".join(out) + "\n", encoding="ascii")
    (wd / "marks.json").write_text(json.dumps(meta, indent=1), encoding="ascii")
    print("maps -> %s: %d objects, %d label words, %d markers, reset code ends at word %d"
          % (wd, len(names), len(words), len(meta), reset_end))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=None, help="label table (default: blocked27's)")
    ap.add_argument("--gen-dir", default=None, help="generated parts dir (default: build/generated_<fjm stem>)")
    a = ap.parse_args()
    from pathlib import Path
    names = build(a.labels or default_labels(), Path(a.gen_dir) if a.gen_dir else None)
    for k, v in names.items():
        print("%3d  %10d %10d  %9d  %s" % (k, v["lo"], v["hi"], v["hi"] - v["lo"], v["name"]))


if __name__ == "__main__":
    main()
