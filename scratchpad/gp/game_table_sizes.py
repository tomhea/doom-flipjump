"""game_table_sizes.py -- MEASURED word sizes of the M7 gameplay rungs' tables, data and cells (P4.0 .. P7, and P10),
for DESIGN.md section 1.2's span ledger (issues #119 item 3, #121 item 13, #123 R4; P10: PR #129's review, R4). No
build, no run: label addresses only (and, for the growth against a baseline, the two .fjm's segment tables).

    python scratchpad/gp/game_table_sizes.py [--labels scratchpad/12m/atlas/blocked51.labels.tsv.gz]
                                             [--gen-dir <the build's generated parts>] [--rung P10] [--md] [--selftest]
                                             [--fjm <the build's .fjm> --against <a baseline's label table>
                                              --against-gen <its generated parts> --against-fjm <its .fjm>
                                              [--split <a growth region's first label, e.g. seg_pass2_leaf>]]

Addresses in the label table are BITS; a word is 32 bits, an fj op 2 words. Every size is a difference of two label
addresses of the shipped image (blocked51 by default -- that block's inputs, gone with their worktree: the P10 block
names its own), so no model:
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

P10 (docs/gp-p10-plan.md) added NO D4 table -- `--against-gen` prints the two images' dispatch-table headers'
difference. Its rows, each label to label, the labels derived from the emitters' own lists (a renumbering moves them):
  * `sfbase` (G2: a column's ceiling / floor base pid, 2 x VIEW_W one-op cells declared between sfflag and sprflag);
  * the four main-menu frames RESUME added (wall_renderer._menu_lines: by_live's `_l` twins, shown while `g_live`, and
    RESUME highlighted), LEVEL COMPLETE's digit slots, frame, 13 x 10 digit blocks and division routine, and the
    secrets' check (doomfj.statcode);
  * the chaingun: its psprite states' blocks (weaponcode.weapon_lines' `wen<i>`, i its index in weapon_states()),
    and its weapon and flash overlays in the HUD tail (hudcode's `hwf` / `hff` frame dispatch, k its index in
    overlay_frames() / flash_frames());
  * the cells: statcode.decls, the menu's `g_live` / `ev_any`, and the hoisted scratch of G1 / G2 / G3 / G8.

THE GROWTH (`--against`: a baseline image's label table; `--fjm` / `--against-fjm`: the two .fjm's segment tables). An
image's data words are its INLINE segment (word 0 up) and the POOL's payload (the tables the blocking pass relocated,
above the pool base). The inline segment is the labeled code, then the wflip-chain ops flipjump appends after a
segment's code (assembler.BinaryData: `wflip_words`, written after `fj_words`); their `:wflips:N` labels are kept only
for a debugging file, so that TAIL is unlabeled and is NOT attributed here -- it is the inline segment's length minus
its last label's word. The labeled code is cut into the regions of the top-level labels BOTH images have (in address
order, increasing in both; a region runs from its label to the next one's), and every pool segment is put in the region
of its CALL SITE: the first component of its label path (`f<file>:l<line>:<macro>(...)`) names the top-level macro
call, whose inline labels carry the same component (a segment with no label, no inline call site or two call sites is
NOT attributed: the selftest requires there be none). Each row is one region's inline and pool words, baseline -> here.
`--split <region>` cuts one region further by the macros on its labels' paths (depths 1 and 2): inline, each label word
to the next, named by the deepest label there; pool, each segment by its first label.

R9 (`--selftest`): the derivation must agree with every header (and fail on two mutants: a table's `clean` label moved
by one op, and a header's entry count changed), and the cell measure must equal 2 x the declared nibbles for every
numeric `hex.vec` (and fail on a mutated declaration). P10: every BAKED region -- the four menu frames, LEVEL COMPLETE's
frame, its 130 digit blocks, the chaingun's overlay blocks -- must measure 16 words a byte (`stl.output_char`: 8 ops)
plus the one op after it, the bytes counted in the generated text (the frames' header lines, the blocks' own
`stl.output_char` lines), and `sfbase` 2 words a `;0 * dw` line of its declaration; it must fail on two mutants (a
frame's header byte count off by one, a digit block's label one op late). With --fjm / --against / --against-fjm, the
attribution must put every pool word of both images in a region and sum to their segment tables, and must fail on two
mutants (a pool segment dropped, a call site lost); with --split too, the split must sum to its region's attribution in
both images at both depths, and must fail on a region one op short.
"""
from __future__ import annotations

import argparse
import bisect
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
# ship-gate 1b's --pool-base since blocked52 (9070b02; 0x60000000 before): every inline table lies below it
POOL_BASE_BITS = 0x80000000
POOL_WORD = POOL_BASE_BITS // WORD_BITS
# (table, rung) -- the D4 tables the gameplay rungs added, in rung order (P10 added none: see the module docstring)
TABLES = (("ammobcd", "P4.1"), ("aimr", "P4.2a"), ("wpo", "P4.2a"), ("dmrnd", "P4.2a"),
          ("mbul", "P5"), ("trclaw", "P5"), ("sgbite", "P5"), ("dpsav", "P5"), ("palidx", "P5"), ("fxrnd", "P5"),
          ("pjst", "P5"), ("mobview", "P5"),
          ("barnext", "P6+P7"), ("bk10", "P6+P7"), ("bonpal", "P6+P7"), ("amcap", "P6+P7"), ("nkleaf", "P6+P7"),
          ("pkxyz", "P6+P7"), ("barview", "P6+P7"))
HEADER = re.compile(r'^// dispatch table "([A-Za-z0-9_]+)": (\d+) entries, per-entry mode, (\d+)-nibble result')

# ---- P10 (docs/gp-p10-plan.md) ---------------------------------------------------------------------------------------
# wall_renderer._menu_lines: by_live's twins of the main menu while a game is in progress (`g_live`: RESUME over NEW
# GAME), one per highlight, and the frame with RESUME highlighted
P10_MENU_FRAMES = (("menu_frame_l", "the main menu while a game is in progress (RESUME over NEW GAME), NEW GAME lit"),
                   ("menu_frame_help_l", "the same menu, HELP lit"),
                   ("menu_frame_exit_l", "the same menu, EXIT lit"),
                   ("menu_frame_resume", "the same menu, RESUME lit"))
# wall_renderer.MENU_STATE_DECLS' P10 cells, and hoisted_scratch_decls' P10 cells by package (the declarations -- their
# widths -- are read from those lists; a name missing there fails loudly)
P10_MENU_CELLS = ("g_live", "ev_any")
P10_HOIST = (("G2: the column bases", ("p2_basep", "p2_bcpid", "p2_bfpid", "p2_cbcpid", "p2_cbfpid", "p2_dbcpid",
                                       "p2_dbfpid", "p2_ecpid", "tsf_base_p")),
             ("G8: sky behind a stacked piece", ("p2_u1sk", "p2_u2sk", "p2_skyca", "p2_skycd")),
             ("G1: the fragments' clip windows", ("gps_ct", "gps_cb", "gps_cut", "gpsb_ct", "gpsb_cb", "gpsb_cut",
                                                  "ecl_bwlo", "ecl_bwhi", "p2_sc", "p2_scb", "p2_dsc", "p2_dscb",
                                                  "trb_clip_p", "trb_clip_v")),
             ("G3: the third fragment slot", ("p2_s3", "p2_sblk3", "p2_scc", "p2_ds3", "p2_dsblk3", "p2_dscc",
                                              "gpsc_has", "gpsc_ybase", "gpsc_top", "gpsc_sy1", "gpsc_sy2",
                                              "gpsc_smidx", "gpsc_ptr0", "gpsc_ridx", "gpsc_ct", "gpsc_cb",
                                              "gpsc_cut", "gpsc_w1", "gpsc_w2")))
CHAINGUN_SPRITES = ("CHGG", "CHGF")          # DOOM's chaingun psprites: the gun, its flash
# the growth table's notes (`--against`, with --rung P10): a region's first label -> (category, what it is). A region
# not named here is summed in "the rest"; a `<t>.dsp` region of a D4 table both images have is labeled by the tool
P10_GROWTH = {
    "seg_pass2_leaf": ("renderer", "the pass-2 leaf body (frame.seg_pass2_leaf_body_lines): G1's clip, G2's bases, "
                                   "G3's slot C (stream.emit_region_c), G8's sky"),
    "seg_pass1_ts_leaf": ("renderer", "the pass-1 leaf (G2: frame.ts_base_store)"),
    "thing_leaf": ("renderer", "a thing's record, frame.thing_record_body (G1: frame.rec_clip_read), its 1st "
                               "instance"),
    "thing_leaf_b": ("renderer", "the same macro's 2nd instance"),
    "thing_leaf_bb": ("renderer", "its 3rd"),
    "mf_lv": ("P10 menus + stats", "LEVEL COMPLETE: its digit slots, frame and 13 x 10 digit blocks (blocked54: the "
                                   "3-line frame)"),
    "mf_mainx": ("P10 menus + stats", "the main menu on EXIT, + its g_live twin and the RESUME-lit frame"),
    "mf_main": ("P10 menus + stats", "the boot main menu, + its g_live twin"),
    "mf_mainh": ("P10 menus + stats", "the main menu on HELP, + its g_live twin"),
    "nk_end": ("P10 menus + stats", "the secrets' check (statcode.secret_lines), placed after nukage"),
    "hwf1_n0": ("chaingun", "its weapon overlays (CHGGA0, CHGGB0) in the HUD tail"),
    "hff_n7": ("chaingun", "its flash overlays (CHGFA0, CHGFB0)"),
    "a44ok": ("chaingun", "its psprite states' blocks (wen49 .. wen54), after the last old state's"),
    "sprbank": ("chaingun", "the sprite bank: MGUN, the chaingun pickup's art (E1M1's single-player shotguns had "
                            "put SHOT in it already)"),
    "m1_reset": ("the M1 reset", "the self-reset part: the restore set's cells (P10 added some) and, from onepass56 "
                                 "on, ONE PASS's reset by label, its tables in the pool"),
    "vpb_dsp": ("align pad", "the visplane bands' dispatch: its pad up to the aligned vpb_switch__"),
}


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
    a = top[name]
    i = bisect.bisect_right(words, a)
    return words[i] - a


def cell_groups():
    """[(rung, module, [decl, ...])] -- what each rung's emitters declare (the game tier's own calls)"""
    from doomfj import (aimcode, barrelcode, damagecode, hud, hudcode, hurtcode, lootcode, noisecode, projcode,
                        restartcode, statcode)
    from doomfj import wall_renderer as WR
    from doomfj import weaponcode as WC
    from doomfj.config import GAME_CFG
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import BOOT_SKILL, SKILLS
    from doomfj.world import World
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    w = World(mw, "E1M1")
    n = w.layout.nmon
    hoisted = {decl_name_nibbles(d)[0]: d for d in WR.hoisted_scratch_decls(GAME_CFG)}
    menu_state = {decl_name_nibbles(d)[0]: d for d in WR.MENU_STATE_DECLS}
    return [
        ("P4.0", "hudcode", hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START)))),
        ("P4.1", "weaponcode", WC.weapon_decls(WC.level_start(mw, "E1M1"), WC.weapon_states(), WC.overlay_frames())
         + WC.weapon_const_decls()),
        ("P4.2a", "weaponcode (the shot)", WC.shot_decls()),
        ("P4.2a", "aimcode", aimcode.decls(True)),
        # M7 P8a I: the game tier's damage_parts(fight=True) declares the window's mon_target cell TWO nibbles wide
        # (its `"dm_tg: hex.vec 2" if fight` rule); the cell check measures it, so a drift from that rule fails here
        ("P4.2a", "damagecode", damagecode.field_decls(w.schema, n, {f: [0] * n for f in damagecode.P42_FIELDS})
         + damagecode.DM_INTERFACE
         + [("dm_tg: hex.vec 2" if d == "dm_tg: hex.vec 1" else d) for d in damagecode.DM_WINDOW]
         + damagecode.DM_SCRATCH + damagecode.DM_FULL_SCRATCH),
        ("P4.2b", "noisecode", noisecode.noise_decls(w)),
        ("P5", "hurtcode", hurtcode.hurt_decls(hurtcode.level_start(w)) + ["pal_bk: hex.vec 1"]),
        ("P5", "projcode", projcode.pool_decls(puffs=True)),
        ("P6+P7", "barrelcode", barrelcode.decls(w, BOOT_SKILL)),
        ("P6+P7", "lootcode", lootcode.loot_decls(lootcode.level_start(w))),
        ("P6+P7", "restartcode", restartcode.game_decls(SKILLS.index(BOOT_SKILL))),
        # P10: the stats' counters, the secrets' and LEVEL COMPLETE's scratch and constants; the menu's two cells; the
        # renderer packages' hoisted scratch
        ("P10", "statcode", statcode.decls(w)),
        ("P10", "wall_renderer (the menu: g_live, ev_any)", [menu_state[c] for c in P10_MENU_CELLS]),
        *[("P10", "wall_renderer (hoisted scratch, %s)" % pkg, [hoisted[c] for c in names])
          for pkg, names in P10_HOIST],
    ]


def decl_name_nibbles(d):
    """`name: hex.vec N[, v]` -> (name, N or None when symbolic)"""
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_.]*):\s*hex\.vec\s+([^,\s]+)", d)
    if not m:
        return None, None
    return m.group(1), int(m.group(2)) if m.group(2).isdigit() else None


# ---- P10's regions ---------------------------------------------------------------------------------------------------
def p10_labels():
    """the label names P10's rows need, from the emitters' own lists: {
         'cg_states': the chaingun's psprite blocks `wen<i>` ('cg_state_names': their states),
         'cg_weapon': [(test start, records start, block end, lump, wp_frm)] per chaingun overlay frame
                      (hudcode._frame_dispatch2),
         'cg_flash': the same per chaingun flash frame, with fl_frm (hudcode._frame_dispatch, value 0 = no flash),
         'digit_blocks': LEVEL COMPLETE's `lvd<slot>_<digit>`, 'last_slot_end': `lvd<12>_x`}"""
    from doomfj import gamedata as gd
    from doomfj import weaponcode as WC
    from doomfj.statcode import DIGIT_SLOTS
    idx = {s: i for i, s in enumerate(WC.weapon_states())}
    cg = [s for s in WC.psprite_states() if gd.STATES[s].sprite in CHAINGUN_SPRITES]
    weapon = []                                     # (test start, records start, block end, the lump, wp_frm)
    for k, lump in enumerate(WC.overlay_frames()):
        if lump[:4] in CHAINGUN_SPRITES:
            h, v = divmod(k, 16)
            test = "hwf%d_n%d" % (h, v - 1) if v else "hwf_h%d" % h        # the label after the previous frame
            weapon.append((test, "hwf%d_y%d" % (h, v), "hwf%d_n%d" % (h, v), lump, k))
    flash = []                                      # the same, fl_frm (0: no flash)
    for j, lump in enumerate(WC.flash_frames()):
        if lump[:4] in CHAINGUN_SPRITES:
            v = j + 1
            flash.append(("hff_n%d" % (v - 1), "hff_y%d" % v, "hff_n%d" % v, lump, v))
    assert cg and weapon and flash, (cg, weapon, flash)
    return {"cg_states": ["wen%d" % idx[s] for s in cg], "cg_state_names": cg, "cg_weapon": weapon,
            "cg_flash": flash,
            "digit_blocks": ["lvd%d_%d" % (i, d) for i in range(DIGIT_SLOTS) for d in range(10)],
            "last_slot_end": "lvd%d_x" % (DIGIT_SLOTS - 1)}


def family_span(top, names, family):
    """words from the lowest of `names` to the next `family` label after the highest of them -- refusing a family label
    between them that is not one of `names` (the blocks must be contiguous)"""
    lo = min(top[n] for n in names)
    hi_name = max(names, key=lambda n: top[n])
    fam = sorted((w, n) for n, w in top.items() if family.fullmatch(n))
    inside = [n for w, n in fam if lo <= w <= top[hi_name] and n not in names]
    assert not inside, ("not contiguous", inside)
    return min(w for w, _n in fam if w > top[hi_name]) - lo


def p10_rows(top, words, facts=None):
    """P10's rows: (rung, row, what, words, pad, None) -- `facts` (text_facts) adds the frames' byte counts"""
    lab = p10_labels()
    rows = []

    def nbytes(label):
        f = (facts or {}).get(label)
        return "%s bytes" % format(f[0], ",") if f and f[0] is not None else "its bytes"

    def add(row, what, a, b=None, wds=None):
        if wds is None:
            if a not in top or (b is not None and b not in top):
                rows.append(("P10", row, "not in this image", None, None, None))
                return
            wds = size_of(a, top, words) if b is None else top[b] - top[a]
        rows.append(("P10", row, what, wds, 0, None))

    add("`sfbase`", "G2: a column's ceiling / floor BASE pid -- 2 x VIEW_W one-op cells, declared between sfflag and "
        "sprflag", "sfbase")
    for label, what in P10_MENU_FRAMES:
        add("`%s`" % label, "%s: a baked frame, %s x 8 ops, + `;frame_end`" % (what, nbytes(label)), label)
    add("`mf_lv` .. `menu_level_done`", "LEVEL COMPLETE's 13 digit slots from the cells (statcode.digit_lines)",
        "mf_lv", "menu_level_done")
    add("`menu_level_done` .. `lvd0_0`", "LEVEL COMPLETE's baked frame, %s x 8 ops, + slot 0's `sim.jump16` (its 16 "
        "trampolines; the switch is in the pool)" % nbytes("menu_level_done"), "menu_level_done", "lvd0_0")
    add("`lvd0_0` .. `%s`" % lab["last_slot_end"], "its 130 digit blocks (column records, 8 ops a byte, + a jump "
        "each) and slots 1-12's `sim.jump16`", "lvd0_0", lab["last_slot_end"])
    add("`lvd_dec` .. `do_world`", "statcode.routine_lines: the shared /10 (`hex.div`) and the unreachable `lvd_div0`",
        "lvd_dec", "do_world")
    add("`sc_go` .. `sc_end`", "the secrets' check, fcall'd from lootcode's `pre` (statcode.secret_lines; its 1-op "
        "jump-over in front is not in the row)", "sc_go", "sc_end")
    if all(n in top for n in lab["cg_states"]):
        add("`%s` .. `%s`" % (lab["cg_states"][0], lab["cg_states"][-1]),
            "the chaingun's %d psprite states' blocks (%s .. %s; weaponcode.weapon_lines), to the next block"
            % (len(lab["cg_states"]), lab["cg_state_names"][0], lab["cg_state_names"][-1]), None,
            wds=family_span(top, lab["cg_states"], re.compile(r"wen\d+|wp_flash")))
    else:
        add("the chaingun's psprite states", "", "-", "-")
    for key, what, cell in (("cg_weapon", "weapon overlays", "wp_frm"), ("cg_flash", "flash overlays", "fl_frm")):
        spans = lab[key]
        if all(s[0] in top and s[2] in top for s in spans):
            add("`%s` .. `%s`" % (spans[0][0], spans[-1][2]),
                "the chaingun's %s %s (%s %s) in the HUD tail: each frame's test, column records and jump"
                % (what, ", ".join(s[3] for s in spans), cell, ", ".join(str(s[4]) for s in spans)), None,
                wds=sum(top[s[2]] - top[s[0]] for s in spans))
        else:
            add("the chaingun's %s" % what, "", "-", "-")
    return rows


LABEL_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*):(?:\s|$)")
FRAME_BYTES = re.compile(r"^//.*?(?:(\d+) bytes of 0x0B column run-lists|\((\d+) bytes\), then the digit slots)")


def text_facts(gen_dir, wanted):
    """{label: [frame header bytes or None, `stl.output_char` lines, `;0 * dw` lines]} for the labels in `wanted`,
    from the generated parts' TEXT -- each count runs from the label's line to the next label line; a frame header
    is the comment line right before the label (menu._fj_text, statcode.frame_lines)"""
    out = {}
    for f in sorted(Path(gen_dir).glob("*.fj")):
        cur, hdr = None, None
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                m = LABEL_LINE.match(line)
                if m:
                    cur = None
                    if m.group(1) in wanted:
                        cur = out[m.group(1)] = [hdr, 0, 0]
                    hdr = None
                    continue
                s = line.strip()
                if s.startswith("//"):
                    mh = FRAME_BYTES.match(s)
                    hdr = int(mh.group(1) or mh.group(2)) if mh else None
                    continue
                hdr = None
                if cur is not None:
                    if s.startswith("stl.output_char"):
                        cur[1] += 1
                    elif s == ";0 * dw":
                        cur[2] += 1
    return out


def baked_labels():
    """(frames: labels whose header gives the bytes, blocks: labels whose block's own output_char lines are counted)"""
    lab = p10_labels()
    frames = [label for label, _w in P10_MENU_FRAMES] + ["menu_level_done"]
    blocks = lab["digit_blocks"] + [s[1] for s in lab["cg_weapon"] + lab["cg_flash"]]
    return frames, blocks


def check_baked(top, words, facts):
    """every baked P10 region measures 16 words a byte (8 ops, stl.output_char) + the one op after it, and sfbase 2
    words a declared cell: ([mismatch, ...], regions checked)"""
    frames, blocks = baked_labels()
    bad, n = [], 0
    for label in frames + blocks:
        if label not in top:
            continue
        f = facts.get(label)
        nb = None if f is None else (f[0] if label in frames else f[1])
        got = size_of(label, top, words)
        n += 1
        if nb is None or got != 16 * nb + 2:
            bad.append((label, nb, got))
    if "sfbase" in top:
        n += 1
        f = facts.get("sfbase")
        got = size_of("sfbase", top, words)
        if f is None or not f[2] or got != 2 * f[2]:
            bad.append(("sfbase", f and f[2], got))
    return bad, n


# ---- the measure --------------------------------------------------------------------------------------------------
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
    facts = None
    if gen_dir and Path(gen_dir).is_dir():
        frames, _blocks = baked_labels()
        facts = text_facts(gen_dir, set(frames))
    rows += p10_rows(top, words, facts)
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


# ---- the growth against a baseline (`--against`) --------------------------------------------------------------------
_SITE = re.compile(r"f\d+:l\d+:")


def scan_image(labels, pool_word=POOL_WORD):
    """two passes over a label table: {top-level inline label: word}, the highest inline label's word, the pool's
    labels [(word, the first component of the path)] sorted, and each such component's lowest INLINE word (its call
    site)"""
    top, pool, last = {}, [], 0
    with gzip.open(labels, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if not addr.isdigit():
                continue
            w = int(addr) // WORD_BITS
            if w >= pool_word:
                pool.append((w, name.split("---", 1)[0]))
                continue
            last = max(last, w)
            if "---" not in name and not _SITE.match(name) and (name not in top or w < top[name]):
                top[name] = w
    pool.sort()
    wanted = {c for _w, c in pool}
    site = {}
    with gzip.open(labels, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if not addr.isdigit():
                continue
            w = int(addr) // WORD_BITS
            if w < pool_word:
                c = name.split("---", 1)[0]
                if c in wanted and (c not in site or w < site[c]):
                    site[c] = w
    return {"top": top, "last": last, "pool": pool, "site": site}


def fjm_split(fjm, pool_word=POOL_WORD):
    """(the inline segment's words, [(start, words)] of the pool's segments) from the .fjm's segment table"""
    from flipjump.fjm.fjm_reader import read_fjm_header
    segs = read_fjm_header(Path(fjm)).segments
    low = [(s, n) for s, n, _ds, dn in segs if s < pool_word]
    assert len(low) == 1 and low[0][0] == 0, "one inline segment from word 0: %r" % low[:3]
    return low[0][1], sorted((s, n) for s, n, _ds, _dn in segs if s >= pool_word)


def common_chain(new, old):
    """the top-level labels both images have, in the new image's address order, kept while increasing in the old"""
    chain, last = [], -1
    for n in sorted((n for n in new["top"] if n in old["top"]), key=lambda n: new["top"][n]):
        if old["top"][n] > last:
            chain.append(n)
            last = old["top"][n]
    return chain


def attribute(img, chain, pool_segs=None):
    """per region of `chain`: (inline words, pool words); and the pool words NOT attributed -- a segment with no label,
    or no inline call site, or whose labels name more than one call site (none of the three is guessed)"""
    starts = [img["top"][n] for n in chain]
    inline = [(starts[i + 1] if i + 1 < len(starts) else img["last"]) - starts[i] for i in range(len(starts))]
    pool = [0] * len(starts)
    lost = 0
    if pool_segs is not None:
        pw = [w for w, _c in img["pool"]]
        for s, n in pool_segs:
            i, j = bisect.bisect_left(pw, s), bisect.bisect_left(pw, s + n)
            comps = {img["pool"][k][1] for k in range(i, j)}
            at = img["site"].get(comps.pop()) if len(comps) == 1 else None
            if at is None:
                lost += n
                continue
            pool[max(0, bisect.bisect_right(starts, at) - 1)] += n
    return inline, pool, lost


def _macro(component):
    """`f5:l2948:rep0:stream.emit_col_lines(38)` -> `stream.emit_col_lines`"""
    c = re.sub(r"^[fs]\d+:l\d+:", "", component)
    c = re.sub(r"^(?:rep\d+:)+", "", c)
    return re.sub(r"\(\d+\)$", "", c)


def split_region(g, key, labels, region_label, depth):
    """one chain region of image `key` ("new" / "old"), split by the macros on its labels' paths: {"a / b": [inline,
    pool]} for path components 1 .. `depth` (component 0 is the region's own top-level call). Inline: each label word
    to the next one (or the region's end), named by the deepest label there; pool: each segment whose call site lies in
    the region, named by its first label. A word whose labels stop above `depth` keeps the shorter path. Also returns
    the region's [lo, hi) words"""
    img, chain = g[key], g["chain"]
    i = chain.index(region_label)
    lo = img["top"][region_label]
    hi = img["top"][chain[i + 1]] if i + 1 < len(chain) else img["last"]
    sites = {c for c, w in img["site"].items() if lo <= w < hi}
    inl, pool = {}, []
    with gzip.open(labels, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if not addr.isdigit():
                continue
            w = int(addr) // WORD_BITS
            if lo <= w < hi:
                if w not in inl or name.count("---") > inl[w].count("---"):
                    inl[w] = name
            elif w >= POOL_WORD and name.split("---", 1)[0] in sites:
                pool.append((w, name))
    pool.sort()

    def path(name):
        parts = name.split("---")
        return " / ".join(_macro(p) for p in parts[1:depth + 1]) or "(the region's own ops)"

    out = {}
    ws = sorted(inl)
    for k, w in enumerate(ws):
        out.setdefault(path(inl[w]), [0, 0])[0] += (ws[k + 1] if k + 1 < len(ws) else hi) - w
    if ws and ws[0] > lo:                                       # never: the region starts at its own label
        out.setdefault("(the region's own ops)", [0, 0])[0] += ws[0] - lo
    pw = [w for w, _n in pool]
    for s, n in g.get("%s_pool_segs" % key, ()):
        j = bisect.bisect_left(pw, s)
        if j < len(pw) and pw[j] < s + n:
            out.setdefault(path(pool[j][1]), [0, 0])[1] += n
    return out, (lo, hi)


def split_report(g, new_labels, old_labels, region_label, depth=2, top_n=12, md=False):
    """the region's growth by the macros on its paths, depth 1 .. `depth`; returns the two images' splits"""
    res = {}
    for d in range(1, depth + 1):
        new, _r = split_region(g, "new", new_labels, region_label, d)
        old, _r = split_region(g, "old", old_labels, region_label, d)
        res[d] = (old, new)
        keys = sorted(set(new) | set(old), key=lambda k: (-abs(sum(new.get(k, [0, 0])) - sum(old.get(k, [0, 0]))), k))
        print("")
        print(("**`%s` by the macros at path depth %d**" if md else "SPLIT `%s` at path depth %d")
              % (region_label, d))
        if md:
            print("")
            print("| macro path | inline | pool | total |")
            print("|---|---:|---:|---:|")
        rest = [0, 0]
        for k in keys[top_n:]:
            for x in (0, 1):
                rest[x] += new.get(k, [0, 0])[x] - old.get(k, [0, 0])[x]
        for k in keys[:top_n]:
            di = new.get(k, [0, 0])[0] - old.get(k, [0, 0])[0]
            dp = new.get(k, [0, 0])[1] - old.get(k, [0, 0])[1]
            if md:
                print("| %s | %s | %s | **%s** |" % (k, format(di, "+,"), format(dp, "+,"), format(di + dp, "+,")))
            else:
                print("%11s = inline %10s + pool %10s  %s"
                      % (format(di + dp, "+,"), format(di, "+,"), format(dp, "+,"), k))
        if keys[top_n:]:
            row = (len(keys) - top_n, format(rest[0], "+,"), format(rest[1], "+,"), format(sum(rest), "+,"))
            print(("| the other %d paths | %s | %s | **%s** |" if md else
                   "%d other paths: inline %s + pool %s = %s") % row)
    return res


def check_split(g, res, region_label):
    """the split sums to the region's attribution, in both images, at every depth: [failure, ...]"""
    bad = []
    i = g["chain"].index(region_label)
    for d, (old, new) in res.items():
        for key, sp in (("old", old), ("new", new)):
            inline, pool, _lost = g["%s_attr" % key]
            got = (sum(v[0] for v in sp.values()), sum(v[1] for v in sp.values()))
            if got != (inline[i], pool[i]):
                bad.append((key, d, got, (inline[i], pool[i])))
    return bad


def growth(new_labels, old_labels, new_fjm=None, old_fjm=None, new_gen=None, old_gen=None):
    """the attribution of a new image's growth over a baseline's: a dict the report prints (see the module docstring)"""
    new, old = scan_image(new_labels), scan_image(old_labels)
    chain = common_chain(new, old)
    g = {"chain": chain, "new": new, "old": old}
    if new_fjm and old_fjm:
        g["new_inline"], new_pool = fjm_split(new_fjm)
        g["old_inline"], old_pool = fjm_split(old_fjm)
        g["new_pool_segs"], g["old_pool_segs"] = new_pool, old_pool
    else:
        new_pool = old_pool = None
    g["new_attr"] = attribute(new, chain, new_pool)
    g["old_attr"] = attribute(old, chain, old_pool)
    # every D4 table's size and alignment pad in both images (a `<t>.dsp` region's change is its pad when the table is
    # in both)
    tabs = {}
    for key, path in (("new", new_labels), ("old", old_labels)):
        reg = table_regions(path)
        tabs[key] = {t: table_size(t, reg) for t in reg if {"dsp", "switch", "end"} <= set(reg[t])}
    g["tables"] = tabs
    if new_gen and old_gen and Path(new_gen).is_dir() and Path(old_gen).is_dir():
        g["headers"] = (headers(old_gen), headers(new_gen))
    return g


def growth_rows(g, min_row=5000, notes=None):
    """[(region, category, note, inline old, inline new, pool old, pool new)] for |delta| >= min_row, then the rest"""
    chain = g["chain"]
    ni, np_ = g["new_attr"][:2]
    oi, op_ = g["old_attr"][:2]
    tn, to = g["tables"]["new"], g["tables"]["old"]
    rows, rest = [], [0, 0, 0, 0, 0]
    for i, n in enumerate(chain):
        d = (ni[i] - oi[i]) + (np_[i] - op_[i])
        if abs(d) < min_row:
            rest[0] += 1
            rest[1] += oi[i]
            rest[2] += ni[i]
            rest[3] += op_[i]
            rest[4] += np_[i]
            continue
        cat, note = (notes or {}).get(n, ("", ""))
        t = n[:-4] if n.endswith(".dsp") else None
        if t in tn and t in to and not note:
            dw, dp = tn[t]["words"] - to[t]["words"], tn[t]["pad"] - to[t]["pad"]
            if ni[i] - oi[i] == dw == dp and np_[i] == op_[i]:       # the region's whole change is the table's pad
                cat, note = "align pad", "D4 table `%s`: only its alignment pad moved" % t
        rows.append((n, cat, note, oi[i], ni[i], op_[i], np_[i]))
    rows.sort(key=lambda r: -abs((r[4] - r[3]) + (r[6] - r[5])))
    return rows, rest


def growth_report(g, min_row=5000, notes=None, md=False):
    def c(v):                                    # a count
        return format(v, ",")

    def s(v):                                    # a delta
        return format(v, "+,")

    new, old = g["new"], g["old"]
    rows, rest = growth_rows(g, min_row, notes)
    out = []
    code_d = new["last"] - old["last"]
    if "new_inline" in g:
        pool_o, pool_n = sum(n for _s, n in g["old_pool_segs"]), sum(n for _s, n in g["new_pool_segs"])
        do, dn = g["old_inline"] + pool_o, g["new_inline"] + pool_n
        tail_o, tail_n = g["old_inline"] - old["last"], g["new_inline"] - new["last"]
        out.append("DATA   %s -> %s words (%s) = the inline segment %s -> %s (%s) + the pool's payload %s -> %s (%s)"
                   % (c(do), c(dn), s(dn - do), c(g["old_inline"]), c(g["new_inline"]),
                      s(g["new_inline"] - g["old_inline"]), c(pool_o), c(pool_n), s(pool_n - pool_o)))
        out.append("INLINE the labeled code (word 0 .. the last label) %s -> %s (%s) + the wflip tail after it "
                   "%s -> %s (%s, unlabeled: NOT attributed)"
                   % (c(old["last"]), c(new["last"]), s(code_d), c(tail_o), c(tail_n), s(tail_n - tail_o)))
        tot = dn - do
    else:
        out.append("INLINE the labeled code (word 0 .. the last label) %s -> %s (%s); no --fjm / --against-fjm: the "
                   "pool and the wflip tail are not measured" % (c(old["last"]), c(new["last"]), s(code_d)))
        tot = None
    ni, np_, nl = g["new_attr"]
    oi, op_, ol = g["old_attr"]
    out.append("REGIONS %s common top-level labels; inline %s, pool %s; pool words with no call site: %s here, %s "
               "in the baseline" % (c(len(g["chain"])), s(sum(ni) - sum(oi)), s(sum(np_) - sum(op_)), c(nl), c(ol)))
    tn, to = g["tables"]["new"], g["tables"]["old"]
    both = set(tn) & set(to)
    out.append("D4     %d tables here, %d in the baseline (%d in both); their words %s, of which alignment pad %s"
               % (len(tn), len(to), len(both), s(sum(tn[t]["words"] for t in both) - sum(to[t]["words"] for t in both)),
                  s(sum(tn[t]["pad"] for t in both) - sum(to[t]["pad"] for t in both))))
    if "headers" in g:
        ho, hn = g["headers"]
        changed = sorted(t for t in set(ho) & set(hn) if ho[t] != hn[t])
        out.append("HEADERS %d dispatch-table headers here, %d in the baseline: added %s, removed %s, changed %s"
                   % (len(hn), len(ho), sorted(set(hn) - set(ho)), sorted(set(ho) - set(hn)),
                      ", ".join("`%s` %d -> %d entries (%d -> %d result nibbles)"
                                % (t, ho[t][0], hn[t][0], ho[t][1], hn[t][1]) for t in changed) or "none"))
    cats = {}
    for n, cat, _note, a, b, cc, d in rows:
        cats[cat or "the rest"] = cats.get(cat or "the rest", 0) + (b - a) + (d - cc)
    rest_i, rest_p = rest[2] - rest[1], rest[4] - rest[3]
    cats["the rest"] = cats.get("the rest", 0) + rest_i + rest_p
    if md:
        print("\n".join("- " + line for line in out))
        print("")
        print("| region (its first label) | what | inline | pool | total |")
        print("|---|---|---:|---:|---:|")
        for n, cat, note, a, b, cc, d in rows:
            what = ("%s: " % cat if cat else "") + note
            print("| `%s` | %s | %s | %s | **%s** |" % (n, what, s(b - a), s(d - cc), s((b - a) + (d - cc))))
        print("| the other %s regions | | %s | %s | **%s** |" % (c(rest[0]), s(rest_i), s(rest_p), s(rest_i + rest_p)))
    else:
        print("\n".join(out))
        for n, cat, note, a, b, cc, d in rows:
            what = "[%s] %s" % (cat, note) if cat else note
            print("%11s = inline %10s + pool %10s  %-26s %s"
                  % (s((b - a) + (d - cc)), s(b - a), s(d - cc), n[:26], what))
        print("%11s = inline %10s + pool %10s  the other %s regions"
              % (s(rest_i + rest_p), s(rest_i), s(rest_p), c(rest[0])))
    if tot is not None:
        tail = (g["new_inline"] - new["last"]) - (g["old_inline"] - old["last"])
        cats["the wflip tail (not attributed)"] = tail
        print(("- " if md else "") + "BY CATEGORY (of %s): " % s(tot)
              + "; ".join("%s %s (%.1f%%)" % (k, s(v), 100.0 * v / tot) for k, v in
                          sorted(cats.items(), key=lambda kv: -abs(kv[1]))))
    return rows, rest, cats


def check_growth(g):
    """the attribution's identities: every pool word of both images in a region, the regions summing to the segment
    tables' payload, and the inline regions to the labeled code: [failure, ...]"""
    bad = []
    for key in ("new", "old"):
        inline, pool, lost = g["%s_attr" % key]
        img = g[key]
        first = img["top"][g["chain"][0]]
        if sum(inline) != img["last"] - first:
            bad.append((key, "inline regions", sum(inline), img["last"] - first))
        if "%s_pool_segs" % key in g:
            payload = sum(n for _s, n in g["%s_pool_segs" % key])
            if lost or sum(pool) != payload:
                bad.append((key, "pool", sum(pool), payload, "lost %d" % lost))
    return bad


def report(rows, cells, md=False, rungs=None):
    if rungs:
        rows = [r for r in rows if r[0] in rungs]
        cells = [c for c in cells if c[0] in rungs]
    if md:
        print("| rung | table / region | what | words | of which align pad |")
        print("|---|---|---|---:|---:|")
        for rung, t, what, wds, pad, _ in rows:
            print("| %s | %s | %s | %s | %s |" % (rung, t if t.startswith("`") else "`%s`" % t, what,
                                                  "-" if wds is None else format(wds, ","),
                                                  "-" if not pad else format(pad, ",")))
        print("")
        print("| rung | module (cells) | labels | words |")
        print("|---|---|---:|---:|")
        for rung, mod, k, tot, miss in cells:
            print("| %s | `%s` | %d | %s |" % (rung, mod, k, format(tot, ",")))
        print("")
        print("- rows %s words; cells %s words"
              % (format(sum(r[3] or 0 for r in rows), ","), format(sum(c[3] for c in cells), ",")))
        return
    for rung, t, what, wds, pad, _ in rows:
        print("%-6s %-58s %10s  pad %8s  %s" % (rung, t, "-" if wds is None else format(wds, ","),
                                                 format(pad or 0, ","), what))
    for rung, mod, k, tot, miss in cells:
        print("%-6s cells %-52s %10s  (%d labels%s)" % (rung, mod, format(tot, ","), k,
                                                        "; not in the image: %s" % miss if miss else ""))
    print("total tables + data + code regions: %s words; cells: %s words"
          % (format(sum(r[3] or 0 for r in rows), ","), format(sum(c[3] for c in cells), ",")))


def selftest(labels, gen_dir, against=None, fjm=None, against_fjm=None, split=None):
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
    # P10: the baked regions against the generated text
    frames, blocks = baked_labels()
    facts = text_facts(gen_dir, set(frames + blocks + ["sfbase"]))
    pbad, pn = check_baked(top, words, facts)
    print("P10 baked regions: %d checked (16 words a byte + 1 op; sfbase 2 words a cell), %d mismatched %s"
          % (pn, len(pbad), pbad[:5]))
    # mutant 4: a frame header's byte count off by one; mutant 5: a digit block's label one op late (an image without
    # them -- not P10's -- fails the controls rather than passing them)
    m4 = m5 = False
    if facts.get("menu_frame_resume") and facts["menu_frame_resume"][0] is not None:
        off_by_one = [facts["menu_frame_resume"][0] + 1] + facts["menu_frame_resume"][1:]
        m4 = bool(check_baked(top, words, dict(facts, menu_frame_resume=off_by_one))[0])
    if "lvd3_8" in top:
        w0 = top["lvd3_8"]
        mtop = dict(top, lvd3_8=w0 + 2)
        mwords = sorted((set(words) - {w0}) | {w0 + 2})
        m5 = bool(check_baked(mtop, mwords, facts)[0])
    print("P10 controls: a frame's byte count +1 caught %s; a digit block's label one op late caught %s" % (m4, m5))
    ok = ok and not pbad and pn >= 5 + 130 and m4 and m5
    if against and fjm and against_fjm:
        g = growth(labels, against, fjm, against_fjm)
        gbad = check_growth(g)
        print("growth: every pool word in a region, the regions summing to the segment tables: %d failures %s"
              % (len(gbad), gbad))
        # mutant 6: one pool segment dropped from the new image's attribution
        g6 = dict(g, new_attr=attribute(g["new"], g["chain"], g["new_pool_segs"][1:]))
        m6 = bool(check_growth(g6))
        # mutant 7: the call site of the new image's first pool segment lost
        comp = g["new"]["pool"][0][1]
        img7 = dict(g["new"], site={c: w for c, w in g["new"]["site"].items() if c != comp})
        g7 = dict(g, new_attr=attribute(img7, g["chain"], g["new_pool_segs"]))
        m7 = bool(check_growth(g7))
        print("growth controls: a dropped pool segment caught %s; a lost call site caught %s" % (m6, m7))
        ok = ok and not gbad and m6 and m7
        if split:
            res = {d: (split_region(g, "old", against, split, d)[0], split_region(g, "new", labels, split, d)[0])
                   for d in (1, 2)}
            sbad = check_split(g, res, split)
            # mutant 8: the new image's split one op short (the label that ends its region one op early)
            nxt = g["chain"][g["chain"].index(split) + 1]
            short = dict(g, new=dict(g["new"], top=dict(g["new"]["top"], **{nxt: g["new"]["top"][nxt] - 2})))
            m8 = bool(check_split(g, {1: (res[1][0], split_region(short, "new", labels, split, 1)[0])}, split))
            print("split `%s`: depths 1-2 sum to its region in both images: %d failures %s; a region one op short "
                  "caught %s" % (split, len(sbad), sbad, m8))
            ok = ok and not sbad and m8
    else:
        print("growth: skipped (no --fjm / --against / --against-fjm)")
    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--gen-dir", default=str(DEFAULT_GEN))
    ap.add_argument("--rung", action="append", help="print only this rung's rows (repeatable), e.g. P10")
    ap.add_argument("--fjm", help="this image's .fjm (its segment table: the inline segment, the pool's payload)")
    ap.add_argument("--against", help="a baseline image's label table: the growth attribution")
    ap.add_argument("--against-gen", help="the baseline's generated parts: the dispatch-table headers' difference")
    ap.add_argument("--against-fjm", help="the baseline's .fjm")
    ap.add_argument("--min-row", type=int, default=5000, help="the growth rows printed: |delta| >= this (words)")
    ap.add_argument("--split", help="with --against: one growth region (its first label) split by the macros on its "
                                    "labels' paths, depths 1 and 2 -- e.g. seg_pass2_leaf")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.labels, a.gen_dir, a.against, a.fjm, a.against_fjm, a.split)
    rows, cells, *_ = measure(a.labels, a.gen_dir)
    report(rows, cells, a.md, set(a.rung) if a.rung else None)
    if a.against:
        print("")
        g = growth(a.labels, a.against, a.fjm, a.against_fjm, a.gen_dir, a.against_gen)
        growth_report(g, a.min_row, P10_GROWTH if a.rung and "P10" in a.rung else None, a.md)
        if a.split:
            split_report(g, a.labels, a.against, a.split, 2, md=a.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
