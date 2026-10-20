"""SSOT — resolution + every resolution-derived size and bit-width (the §1 2-const switch).

W/H live ONLY here; everything resolution-derived (table sizes, pow2 pads, AND bit-widths) is
computed from them — no literal that assumes W/H <= 256 (DESIGN §1, §1.1.4). `emit_fj_consts`
writes build/generated/fj_consts.fj, the constants file src/fj/memory_map.fj consumes, so the
fj side and the host side cannot drift (R6). The host span ledger here is the skeleton M10 (R0)
fills with real per-table numbers (§1.2).
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from pathlib import Path

# Default flat-limit (span-words) — flipjump's 2**23 (64 MB at w=32), §1.2. The R-3 budget ceiling.
FLAT_MAX_WORDS = 1 << 23

# The RAISED flat limit the full E1M1 renderer runs under (DESIGN §1.2, RAM-only cost).
#
# ⚠ R6 SSOT, added 2026-08-18. This was the literal `1 << 26` copy-pasted into build.py, fastrun.py,
# three gates, the host span test and seven fj tests — so "the limit" was twelve independent numbers
# and raising it meant finding them all.
#
# ⚠ RAISED 2**26 -> 2**27 (owner decision, 2026-08-18). MEASURED: the M14 tier — the tier that ships
# after B0 — is 68,213,458 words, 1.6% OVER 2**26. At 2**26 it silently ran in HYBRID storage, which
# R4 forbids, and `_fjcore.Memory.freeze()` requires PURE FLAT — so the frozen-image fast reset path
# (and with it B4.1's 357x restore) was unavailable to the shipped tier. Op counts are identical in
# both modes (43,115,656 at the spawn viewpoint either way), so no earlier measurement moved.
#
# THIS IS A LIMIT, NOT AN ALLOCATION: flipjump allocates the actual span (68.2M words ≈ 546 MB), and
# this only decides whether it may use flat storage. Raising it costs no memory by itself — it
# raises the ceiling under which a build is allowed to stay flat.
# ⚠ It is still a CEILING, and B3's nine-level table competes for the same headroom (handoff G3):
# at 68.2M of 134.2M the shipped tier now has ~1.97x, not the ~1.02x it had against 2**26.
RENDER_FLAT_MAX_WORDS = 1 << 27

# The map the renderer is built for unless a caller names another. Here rather than in
# build.py because a path resolved out of the package is a project constant, not a build fact.
DEFAULT_MAP_WAD = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "freedoom_e1m1.wad"

# M13-2S rung 3a — how many MARKING TWO-SIDED segs may attribute floor/ceiling surfaces in one frame
# (see ReferenceModel.render_wall_frame's `plane_near` and wall_renderer's ts leaf). A hard budget, in
# the spirit of vanilla DOOM's MAXVISPLANES/MAXDRAWSEGS: without one the cost is unbounded, because
# the natural stopping condition ("every column attributed") never fires when part of the view is open
# sky or void -- measured on E1M1, 13 of the sweep's 65 viewpoints never attribute all 160 columns and
# one of them cost 69.6M ops/frame, more than double the owner's 33M ceiling. Segs are visited
# nearest-first, so the budget only ever costs FAR attribution: those columns fall back to the
# claiming wall's sector, which is the pre-rung-3a behaviour. 128 was chosen by measurement --
# scratchpad/rung3a_budget.py: it bounds the worst frame while every viewpoint that closes the view
# (52 of the 65) needs far fewer. Shared by the oracle and the emitter so they cannot drift (R6).
PNEAR_SEG_BUDGET = 128


@dataclass(frozen=True)
class Config:
    # ── the two resolution constants (the §1 2-const switch) ──
    W: int = 160
    H: int = 100
    # ── other base constants ──
    BPP: int = 8        # bits/pixel -> 256 colors
    # M7 P4.0 (D6): the 3D view's rows when a status bar takes the screen's bottom rows; 0 = the whole screen.
    # The GAME tier's config sets 84 (`GAME_CFG`); every other tier keeps 0.
    VIEW_ROWS: int = 0
    TRIG_N: int = 4096  # trig LUT entries, 16**3 (§1.2/§2.1)
    NATIVE_W: int = 320  # DOOM's native authoring width (the F8 UI + D5 texture downscale reference)
    # M4 -- HOW WIDE A PLANE-PAIR ID IS, in nibbles. 2 (one byte) is E1M1's shipped width and the
    # DEFAULT, so every existing build and every gate is byte-identical under it.
    #
    # It lives HERE, and reaches the fj through `fj_consts.fj`, because that file is assembled
    # FIRST everywhere (`paths = [consts] + includes + prog`) and a constant in an earlier file IS
    # usable as a `rep` count later. TWO other routes were TESTED AND REJECTED (see
    # docs/handoff-m4-nine-levels.md): a constant emitted into a LATER part is refused at
    # macro-DEFINITION time, and declaring it `< EXTERN` satisfies the label checker but not the
    # preprocessor, which needs a VALUE to expand `rep`. Threading it as a macro argument instead
    # would have touched 13 macro signatures across two files; this touches none.
    #
    # ⚠ A pid is stored as PID_NIBBLES/2 BYTES per column in `pclm[]`, so this must stay EVEN.
    # MEASURED per map (scratchpad/m4_bands.py): E1M1 222, E1M5 147, E1M8 90 fit 2 nibbles;
    # E1M2 376, E1M3 337, E1M4 276, E1M9 340 need 4. A global seven-level space is ~1,788.
    # ⚠ THIS IS THE VALUE WIDTH, NOT THE STORAGE WIDTH -- they are separable and an earlier
    # version of this comment wrongly claimed the width "must stay EVEN". Only `pclm[]` storage is
    # byte-granular (`hex.write_byte`); the ARITHMETIC has no such constraint. So a multi-level
    # image reads TWO BYTES per column and then does every mov/cmp/if0/zero and the skypid dispatch
    # on the low THREE nibbles -- 4,095 values, against a global seven-map pid space of 1,788.
    #
    # It is worth doing because of hex.cmp's cost model: m(3@+8) counting DOWN FROM THE MOST
    # SIGNIFICANT nibble, and m=n when the two values are EQUAL -- which is the ditto-hit common
    # case. A permanently-zero top nibble is paid in full on every equal compare, and the V5 ditto
    # block runs four of them per column.
    PID_NIBBLES: int = 2

    # M4-R2 -- HOW WIDE THE BAND-LIST INDEX IS, in nibbles. 4 (65,536 ids) is E1M1's shipped
    # width and the DEFAULT. MEASURED 2026-09-01: the seven shippable levels need 384,156 ids,
    # whose pad is 524,288, so a multi-level image needs 5.
    #
    # ⚠ THE TABLE DOES NOT GROW WITH THIS. `generate_bands_walk_fj` derives its `pad` from the
    # LIST COUNT, so raising the width alone costs only `rep(index_nibbles, i) hex.xor ...` -- one
    # extra nibble of dispatch per band lookup. That is what makes the cost measurable on E1M1,
    # which needs only 4: force 5, and the picture must stay byte-exact while ops rise.
    BAND_NIBBLES: int = 4

    # M8 L1 -- `sshead`'s DECLARED cells per leaf. 2 is E1M1's (the M1 restore set was recorded over twice the
    # reachable cells, and the hosted / two-pass tiers still read those spans); a map without that history declares
    # what a leaf reaches (1). E1M2 MUST: its hot data block (pclm .. wrej) has to fit ONE 16^5-bit window for
    # frame.arm5, and at 2 it ran 96 ops past it (16,480 of 16,384) -- the binary jumped to op 0 on its first frame.
    SSHEAD_RATIO: int = 2

    # M8 wave 1 -- `thss_rt` (a runtime thing's leaf, 16 cells a row) declared PAST the hot data block instead of inside
    # it (the game tier: wall_renderer's hot block; lootcode.pk_drop, its one pointer reader, re-arms into the window
    # after it). E1M4's block was 17,482 ops of the 16,384-op window (346 runtime things: thss_rt 5,536 of them); with
    # it out, 11,946 (E1M3: 17,061 -> 11,605). 0 keeps E1M1's / E1M2's text
    THSS_COLD: int = 0

    # M8 F1.5 (docs/f1-runtime-ids.md, option A1) -- HOW WIDE A RUNTIME THING ID IS in the per-leaf lists (`sshead` /
    # `thnext`), in bits: 8 (E1M1's, E1M2's: an id + 1 in one byte, at most 254 ids) or 12 (at most 4,094: E1M3 341,
    # E1M4 345, E1M5 370 runtime things + pools + drops). A list entry stays ONE cell at the same stride either way --
    # the id sits in bits dbit .. dbit+11 of its jump word -- and only the accessors widen: the wide map reads and writes
    # it through flipjump's DUAL decoder table (`-D hex.pointers.PTR_WIDE_BITS=12`, `emit_fj_defines`; hex.read_cell /
    # hex.write_cell), and its emitter calls the `_w` twins of sim.fj's list macros. 8 lays no table and emits the text
    # it always did (not an fj constant: `constants()` leaves it out, so fj_consts.fj is unchanged too).
    LIST_ID_BITS: int = 8

    @property
    def LIST_WIDE(self) -> int:
        """M8 F1.5: 1 when the lists are 12-bit (the dual table, the `_w` macros), 0 at 8 bits"""
        assert self.LIST_ID_BITS in (8, 12), ("LIST_ID_BITS %d: the lists are 8 or 12 bits (docs/f1-runtime-ids.md)"
                                              % self.LIST_ID_BITS)
        return 1 if self.LIST_ID_BITS == 12 else 0

    @property
    def LIST_NIB(self) -> int:
        """M8 F1.5: a list id's width in nibbles (2 or 3) -- the relink's registers, the rank, the drop link's dr_t"""
        return 2 + self.LIST_WIDE

    def emit_fj_defines(self, out) -> "Path | None":
        """M8 F1.5: the assembler's -D file for this config, or None when it needs none (every 8-bit map: E1M1's and
        E1M2's assemblies take no defines file, as before). A wide-list map lays flipjump's second decoder table:
        `hex.pointers.PTR_WIDE_BITS = 12` (stl/runlib.fj declares it 0; the -D line overrides the declaration), written
        as the CLI writes a dotted -D: inside its namespaces (flipjump_cli.add_defines_file)."""
        if not self.LIST_WIDE:
            return None
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("// GENERATED by doomfj.config.emit_fj_defines -- the -D file of a wide-list map (M8 F1.5)\n"
                       "ns hex {\nns pointers {\nPTR_WIDE_BITS = %d\n}\n}\n" % self.LIST_ID_BITS, encoding="utf-8")
        return out

    # M8 C11 (E1M7) -- `n_tsv`'s width in nibbles: the per-frame count of MARKING two-sided segs that reach
    # frame.seg_pass1_leaf_body_ts, against the deg attribution budget TSV_BUDGET (16^n - 1, the counter's max). The
    # budget must provably NEVER bind (a binding one paints the smudged columns: reference_model.DEG_PNEAR), so the
    # emitter asserts the map's marking-seg count stays below it (wall_renderer._assert_pnear_unbound). 3 (4,095) is
    # E1M1's and every map's up to E1M6 (2,550); E1M7 marks 4,183 -> 4. Not an fj constant: the macro derives its
    # width from the budget it is passed (`(#budget + 3) / 4`), so the two cannot drift.
    TSV_NIBBLES: int = 3

    @property
    def TSV_BUDGET(self) -> int:
        """M8 C11: the deg attribution budget the fj and the oracle share -- the `n_tsv` counter's max (DEG_PNEAR = 4095
        at the default 3 nibbles)"""
        assert 1 <= self.TSV_NIBBLES <= 6, ("TSV_NIBBLES %d: 1 .. 6 (E1M1 3; below 3 only a test's binding budget)"
                                            % self.TSV_NIBBLES)
        return 16 ** self.TSV_NIBBLES - 1

    @property
    def PID_BYTES(self) -> int:
        """Bytes of `pclm[]` storage per column: ceil(PID_NIBBLES/2).

        The STORAGE is byte-granular because the array is walked with `hex.read_byte`/
        `hex.write_byte` and a pointer stepped per column. The VALUE width is PID_NIBBLES and is
        free of that: 3 nibbles live in 2 bytes with the top nibble permanently zero."""
        return (self.PID_NIBBLES + 1) // 2

    @property
    def SLOT_SHIFT(self) -> int:
        """Whole-nibble shifts for the per-column `sfslot` offset: log16(STEP_SLOT_STRIDE).

        V5 fills the slot COMPLETELY at the default width -- 2 groups x 2 pieces x 4 bytes
        (fy1, fy2, cls, bpid) = 16 of 16. (The constant's own comment still says "6 used", which
        is V3-era, before the second piece and the bpid byte.) A wider pid makes a piece 5 bytes,
        so the stride must grow -- and it must stay a POWER OF 16, because the offset is
        `hex.shl_hex w/4, SLOT_SHIFT, idx` and the alternative is a mul_const priced at ~72@.
        M8 L1 (E1M2): NOT 16 -> 256. `sfslot` lives in the narrow-armed hot block, which must fit ONE 16^5-bit window
        (frame.arm5; scratchpad/12m/ritual.py checks it): 256 bytes a column would make it 40,960 ops against 5,954 ops of
        headroom (measured on blocked62). The shift stays ONE nibble and a two-byte pid adds one BIT (`SLOT_BIT`, a
        `hex.shl_bit` after each shift): a 32-byte stride, 20 bytes used, +2,560 ops of `sfslot`."""
        return 1

    @property
    def SLOT_BIT(self) -> int:
        """M8 L1: the extra one-bit shift of the `sfslot` offset when a piece is 5 bytes (a two-byte pid): 0 or 1."""
        return 0 if self.PID_BYTES == 1 else 1

    @property
    def SLOT_STRIDE(self) -> int:
        """M8 L1: bytes per column in `sfslot`: 16, or 32 for a two-byte pid (SLOT_SHIFT nibbles + SLOT_BIT bits)."""
        return (16 ** self.SLOT_SHIFT) << self.SLOT_BIT

    @property
    def PIECE_BYTES(self) -> int:
        """Bytes per stored V5 boundary piece in `sfslot`: fy1, fy2, cls, then the back pid.

        4 at the default width, 5 when a pid needs two bytes. A slot is FOUR pieces -- u1@0, u2@4,
        l1@8, l2@12 at the default -- so the group offset is 2*PIECE_BYTES and the slot is
        4*PIECE_BYTES, which is why the stride has to grow with it."""
        return 3 + self.PID_BYTES

    @property
    def TEXTURE_DOWNSCALE(self) -> int:
        """World-texture D5 span-lever factor = NATIVE_W // W: 2 at W=160 (the R0 decision), 1 at the
        native 320 (no downscale — raise --flat-max-words instead, DESIGN §1.2 320 stretch). The single
        bit-exact factor shared by the texture compiler (H4) and the oracle (H5) — R6/D12."""
        return max(1, self.NATIVE_W // self.W)

    # ── resolution-derived (computed; NEVER hardcoded) ──
    @property
    def NCOLORS(self) -> int:
        return 1 << self.BPP

    @property
    def COL_BITS(self) -> int:
        """Screen column-x width = ceil(log2 W), §1.1.4 — 8 at W=160, 9 at W=320; never a fixed 8."""
        return math.ceil(math.log2(self.W))

    @property
    def ROW_BITS(self) -> int:
        """Screen row-y width = ceil(log2 H)."""
        return math.ceil(math.log2(self.H))

    @property
    def VIEW_W(self) -> int:
        """3D viewport width (full screen until a status bar exists, R3 — §10.4 VIEW_H note)."""
        return self.W

    @property
    def VIEW_H(self) -> int:
        """3D viewport height: the whole screen, or (M7 P4.0, D6) VIEW_ROWS when a status bar takes the rows below it.
        A screen drawn over EVERY row (a menu frame) uses H, never this."""
        return self.VIEW_ROWS or self.H

    @property
    def CENTERX(self) -> int:
        """Screen-centre column = VIEW_W//2 (the projection's horizontal vanishing point, M12)."""
        return self.VIEW_W // 2

    @property
    def CENTERY(self) -> int:
        """Screen-centre row = VIEW_H//2 (the horizon: wall top/bottom = CENTERY -/+ height*scale, M12)."""
        return self.VIEW_H // 2

    @property
    def PROJECTION(self) -> int:
        """Focal length in column units. FOV = 90deg => focal = CENTERX (tan 45deg = 1), so the screen
        edges sit at +/-45deg (D6 projection setup; viewangletox is built from this)."""
        return self.CENTERX

    @property
    def FB_SIZE(self) -> int:
        """Framebuffer: W*H packed bytes, no align (§1.2)."""
        return self.W * self.H

    @property
    def PALETTE_SIZE(self) -> int:
        """NCOLORS * 3 (RGB triplets), §1.2."""
        return self.NCOLORS * 3

    # M6: the two hot-path pad tiers, assigned by MEASURED median ops/frame of a site's
    # instances (>99 -> HOT_PAD, >1000 -> HOTTER_PAD). See FINDINGS AX/AZ.
    # ⚠ BOTH ARE 16 (2026-09-25), ON EVERY TIER: the plain table's own alignment, so the 91 hot
    # `sparse_` sites build exactly the table `hex.mov` / `hex.zero` / `hex.xor` would. The tiers
    # (1024 / 4096) aligned those tables to low-popcount addresses, which pays only where nothing
    # blocks. The shipped build blocks, and there a table's pad IS its slot width: a pad wider than
    # the build's --max-slot-ops (docs/ship-gate.md 1b; tests/host/test_hot_pads_block.py holds both
    # pads to it) is `declined_too_wide`, and all 988 tables stayed inline at 945,807 ops/frame. At
    # 16 they block: 19,855,016 -> 19,201,791 ops/frame on msframe's script, and the ship gate's
    # time verdict FASTER (handoff throughput-plan 15.4). The price, on the unblocked tiers only:
    # deg_gate's four viewpoints cost +0.7% .. +3.3% ops (same section). A build that does not
    # block should raise them.
    HOT_PAD: int = 16
    HOTTER_PAD: int = 16
    # P12 (T5): proj.project_thing's TIGHT far bound for the baked things, tz_map + (tz_map >> 1) + SPR_REACH map
    # units of L-inf distance -- SPR_REACH covers the widest sprite side of its origin (max(left, w - left): 76 on
    # E1M1, a tall tree) plus the floors' and the trig table's slop. doomfj.things.tight_far_bound_ok checks every
    # baked thing against it exactly, so a wider sprite on another map fails the emit, never a pixel.
    SPR_REACH: int = 80

    # M8 F1.4 (docs/f1-big-map-widths.md section 1, option B -- the owner, 2026-10-17): the PER-FRAME cap on accepted
    # things. A fragment names its thing by a ONE-BYTE slot id (`gps_nslot`, 1..255, 0 = no fragment), one per thing
    # frame.thing_record_body accepts; a map whose frame could accept more caps it -- DOOM's own rule (r_things.c
    # R_NewVisSprite: past MAXVISSPRITES = 128 it returns the overflow sprite, i.e. the thing is not drawn), and the
    # walk is front to back, so only the farthest drop. 0 = no cap (E1M1: its count bound fits, the record's two cap
    # lines expand to nothing -- SPR_SLOT_CAP_ON -- and the oracle takes the old path). wall_renderer.check_slot_ids
    # holds it below SPR_THING_SLOTS and asks for it when the map's bound does not fit.
    SPR_SLOT_CAP: int = 0
    # M8 (doomfj.lights): the map's SECTOR LIGHT SPECIALS animate (flash, strobes, glow, fire flicker: DOOM's p_lights.c
    # thinkers) -- 1 on E1M2. 0 (E1M1, the default): its lights stay static and its emission is unchanged. Not an fj
    # constant (`constants()` leaves it out): the emitter and the model read it here.
    SECTOR_LIGHTS: int = 0
    # M8 (the special-48 simplification, owner rule "implement it if it costs <= +0.5%"): 1 = the segs of a scrolling
    # wall line (doomfj.scrollcode.SCROLL_SPECIALS) slide their W1R pattern key by `leveltime & WALL_SCROLL_MASK` -- the
    # game tier's visible form of DOOM's textureoffset += FRACUNIT a tic (a 1x1 W1R canvas has no texture u to move).
    # A DELIBERATE APPROXIMATION: screen-space, not world-anchored, and the pattern jumps once every 256 frames when
    # the low byte wraps. 0 (E1M1): nothing is emitted and the oracle takes the old path.
    WALL_SCROLL: int = 0

    # M8 (the owner, 2026-10-18: a recorded simplification is implemented when it costs <= +0.5% speed) -- THE SWITCH
    # TEXTURES CHANGE: DOOM's P_ChangeSwitchTexture, a used switch line's SW1 texture shown as its SW2 (an S1 / exit line
    # for good, an SR line for BUTTONTIME). 1 on a map that animates them (doomfj.switches; the game picture's wall
    # tones draw the change), 0 on E1M1, whose emission stays byte-identical. Host-side only: NOT an fj constant.
    SWITCH_TEX: int = 0

    # M8 (doomfj.automap; the owner, 2026-10-18): 1 = the game tier has the MAP PAGE -- the main menu's MAP item, the key
    # M, the level's lines baked as a frame and the player's dot computed at run time. Per map (MAP_CONFIG), so E1M1's
    # emission is untouched while the page is off there (0, the default: not one line differs).
    AUTOMAP: int = 0
    # M8 size (the owner, 2026-10-19: "the 2^27 words-space is a super hard limit"): 1 = the baked point location
    # (`collision.generate_point_location_fj`) keeps each node's CONSTANTS in the node and runs the cross product / the
    # compare in SHARED subroutines (one hex.mul_lo pair, one hex.scmp per axis) instead of inlining them per node: the
    # same leaf for every point, for a fcall per node visited. `ptloc_walk` was 19.5M of E1M2 r4's 83.5M words (code,
    # wflip chains and pool tables). 0, the default: the inline walk, byte for byte.
    PTLOC_SHARED: int = 0
    # M8 size: 1 = the plane bands' per-id thunk cleans its id out of `vpb_dsp` FIRST and tail-jumps into the shared
    # body, which returns through hex.tables.ret (`lut_generator.generate_bands_walk_fj(direct=True)`): no fcall per
    # walk and no 2^k-entry clean table. The bands bank is 14.4M of E1M2 r4's words and grows with the band lists
    # (viewz classes x plane pairs: E1M7 ~2.5x E1M2). 0, the default: the fcall thunks, byte for byte.
    VPB_DIRECT: int = 0

    # #149 (the CR of #148, R6): the rule a door's open height is found among (doomfj.doors.door_neighbours,
    # P_FindLowestCeilingSurrounding's neighbours). "two_sided" (the default): DOOM's getNextSector -- only a line with a
    # back side and ML_TWOSIDED has a next sector. "legacy": every linedef, a one-sided line's missing back read as
    # the LAST sidedef's sector (issue #104 F1) -- E1M1's, whose door stops its one-byte pid budget froze (PR #103).
    # A per-map flag, not the map's record counts: another wad's E1M1 is still E1M1. Host-side only: NOT an fj constant.
    DOOR_NEIGHBOURS: str = "two_sided"

    @property
    def SPR_SLOT_CAP_ON(self) -> int:
        """M8 F1.4: 1 when the record compares `gps_nslot` against SPR_SLOT_CAP (frame.thing_record_body's rep), else 0"""
        assert 0 <= self.SPR_SLOT_CAP < 256, ("SPR_SLOT_CAP %d: the slot id is one byte" % self.SPR_SLOT_CAP)
        return 1 if self.SPR_SLOT_CAP else 0

    def constants(self) -> dict:
        """The full set of fj-visible constants (the SSOT contents emitted to fj_consts.fj)."""
        return {
            "W": self.W, "H": self.H, "BPP": self.BPP, "TRIG_N": self.TRIG_N,
            "NCOLORS": self.NCOLORS, "COL_BITS": self.COL_BITS, "ROW_BITS": self.ROW_BITS,
            "VIEW_W": self.VIEW_W, "VIEW_H": self.VIEW_H,
            "CENTERX": self.CENTERX, "CENTERY": self.CENTERY, "PROJECTION": self.PROJECTION,
            "FB_SIZE": self.FB_SIZE, "PALETTE_SIZE": self.PALETTE_SIZE,
            "PID_NIBBLES": self.PID_NIBBLES, "PID_BYTES": self.PID_BYTES,
            "SLOT_SHIFT": self.SLOT_SHIFT, "SLOT_BIT": self.SLOT_BIT, "SLOT_STRIDE": self.SLOT_STRIDE,
            "BAND_NIBBLES": self.BAND_NIBBLES,
            "PIECE_BYTES": self.PIECE_BYTES,
            # M6 hot-path wflip-target pads. A `wflip` costs popcount(target), so aligning the
            # target lowers it -- but the inserted shift pushes all later code up and RAISES
            # popcount for every downstream wflip, so this is not monotonic. MEASURED: these
            # widths gave -2.00% ops/frame (S2); one step wider at full coverage gave +0.92%,
            # i.e. WORSE on speed and size both (S3, FINDINGS AZ). Sweep per-site from here.
            "HOT_PAD": self.HOT_PAD, "HOTTER_PAD": self.HOTTER_PAD,
            "SPR_REACH": self.SPR_REACH,
            # M8 F1.4: the per-frame accepted-thing cap (frame.thing_record_body; 0 = none, the lines expand to nothing)
            "SPR_SLOT_CAP": self.SPR_SLOT_CAP, "SPR_SLOT_CAP_ON": self.SPR_SLOT_CAP_ON,
        }

    def span_ledger(self) -> dict:
        """Skeleton §1.2 address-span ledger (the M1 home). M10 (R0) fills the real per-table numbers."""
        return {"framebuffer": self.FB_SIZE, "palette": self.PALETTE_SIZE}

    def total_span(self) -> int:
        return sum(self.span_ledger().values())

    def emit_fj_consts(self, out="build/generated/fj_consts.fj") -> Path:
        """Write the SSOT constants as FlipJump `NAME = value` definitions for memory_map.fj."""
        # ASCII-only + explicit utf-8: flipjump's parser reads files as utf-8, and Path.write_text
        # would otherwise use the Windows locale codec (cp1252) and emit a non-utf-8 byte.
        lines = [
            "// GENERATED by doomfj.config -- DO NOT EDIT. Single source of truth: src/doomfj/config.py",
            f"// resolution {self.W}x{self.H}, bpp={self.BPP} ({self.NCOLORS} colors)",
            "",
        ]
        lines += [f"{name} = {val}" for name, val in self.constants().items()]
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out


# M7 P4.0 (docs/gp-combat.md section 2, D6): THE GAME TIER'S SCREEN -- 160x100 with a 16-row status bar, so a 160x84
# view (DOOM's 168-of-200 layout at half resolution). CENTERX and PROJECTION are unchanged: only rows clip.
GAME_CFG = Config(VIEW_ROWS=84)


# M8 L1 (E1M2, its own binary): the widths a map needs beyond the defaults (E1M1's). E1M2 bakes ~411 plane-pair ids
# (> 255: 3 nibbles, two bytes -- docs/handoff-e1m2.md section 4 (A)) and ~83k band lists (> 65,535: 5 nibbles). The
# emitter's own asserts (the pid bake, the bands walk) refuse a width a map outgrows, so a missing entry fails loudly.
MAP_CONFIG = {
    # M8 F1.4: SPR_SLOT_CAP -- 305 drawable things over the skills, hard's 295 + 10 pool things + 54 droppers' drops
    # (> 255 slot ids: wall_renderer.check_slot_ids)
    # M8: SECTOR_LIGHTS -- its light specials animate (doomfj.lights: 9 thinkers -- 3 flashes, a strobe, a fire flicker,
    # 4 glows; its other 9 glows sit between equal lights and stay static)
    # M8: WALL_SCROLL -- lines 1254 and 1338 (COMPBLUE) are special 48, the scrolling wall (doomfj.scrollcode)
    # M8: SWITCH_TEX -- the used switches change their texture (doomfj.switches)
    # M8: AUTOMAP -- the map page (doomfj.automap)
    "E1M2": {"PID_NIBBLES": 3, "BAND_NIBBLES": 5, "SSHEAD_RATIO": 1, "SPR_SLOT_CAP": 255, "SECTOR_LIGHTS": 1,
             "WALL_SCROLL": 1, "SWITCH_TEX": 1, "AUTOMAP": 1},
    # M8 C11 (E1M7, 1.9x E1M2): the WIDTHS only (its features are other clusters'): TSV_NIBBLES -- 4,183 marking
    # two-sided segs past the 3-nibble n_tsv's 4,095 (wall_renderer._assert_pnear_unbound); PID_NIBBLES / BAND_NIBBLES
    # -- ~545 plane pairs before directions (E1M2: 329 -> 411 baked), the band lists past E1M2's (> 65,535 there);
    # SSHEAD_RATIO 1 -- the hot data block (pclm .. wrej) inside frame.arm5's window, as E1M2; SPR_SLOT_CAP -- 606
    # drawable things over the skills (wall_renderer.check_slot_ids)
    "E1M7": {"PID_NIBBLES": 3, "BAND_NIBBLES": 5, "SSHEAD_RATIO": 1, "SPR_SLOT_CAP": 255, "TSV_NIBBLES": 4},
    # M8 C11 (E1M9): SPR_SLOT_CAP -- 293 drawable things over the skills (wall_renderer.check_slot_ids)
    "E1M9": {"SPR_SLOT_CAP": 255},
    # M8 C11: SPR_SLOT_CAP for the wave-1 / wave-3 maps past a byte of drawable things over the skills (level_survey:
    # E1M3 352, E1M4 340, E1M5 330, E1M6 461) -- a per-map entry their own level rungs extend with their widths
    # M8 wave 1 (docs/episode-plan.md 3): LIST_ID_BITS 12 -- 341 / 346 / 370 runtime ids (F1.5); E1M3 / E1M4 take E1M2's
    # widths (plane pairs 249 / 237 estimated, the band lists, the hot block: the lessons survey); the MAP page and the
    # switch textures as E1M2; the animated lights only where the survey has none on a mover / past a byte (E1M3)
    # E1M3 / E1M4: THSS_COLD -- their hot blocks were 677 / 1,098 ops past frame.arm5's window with thss_rt inside
    # (17,061 / 17,482 of 16,384 ops; thss_rt 5,456 / 5,536 of them: Config.THSS_COLD)
    "E1M3": {"SPR_SLOT_CAP": 255, "LIST_ID_BITS": 12, "PID_NIBBLES": 3, "BAND_NIBBLES": 5, "SSHEAD_RATIO": 1,
             "AUTOMAP": 1, "SWITCH_TEX": 1, "SECTOR_LIGHTS": 1, "THSS_COLD": 1},
    "E1M4": {"SPR_SLOT_CAP": 255, "LIST_ID_BITS": 12, "PID_NIBBLES": 3, "BAND_NIBBLES": 5, "SSHEAD_RATIO": 1,
             "AUTOMAP": 1, "SWITCH_TEX": 1, "THSS_COLD": 1},
    "E1M5": {"SPR_SLOT_CAP": 255, "LIST_ID_BITS": 12, "AUTOMAP": 1, "SWITCH_TEX": 1},
    "E1M6": {"SPR_SLOT_CAP": 255},
    # M8 (the owner, 2026-10-18: "Add it to e1m1 too"): the map page, at 40 units a pixel (doomfj.automap).
    # #149: DOOR_NEIGHBOURS "legacy" -- the door rule E1M1 shipped with (its stops are frozen, PR #103); it was the
    # default before E1M2, picked by the map's record counts until #149. Every other field keeps its default
    "E1M1": {"AUTOMAP": 1, "DOOR_NEIGHBOURS": "legacy"},
}


# M8 size: the 2^27-word cuts, per map -- kept apart from MAP_CONFIG so the feature branches' MAP_CONFIG rows merge
# cleanly (map_cfg applies both; MAP_CONFIG wins a key in both, so `emit_check --map-config PTLOC_SHARED=0` measures a
# map without a cut). E1M1 / E1M2 have none: their emission is untouched.
MAP_SIZE_CONFIG = {m: {"PTLOC_SHARED": 1, "VPB_DIRECT": 1}
                   for m in ("E1M3", "E1M4", "E1M5", "E1M6", "E1M7", "E1M8", "E1M9")}


def map_cfg(cfg: "Config", mapname: str) -> "Config":
    """`cfg` with `mapname`'s MAP_CONFIG widths and MAP_SIZE_CONFIG cuts (unchanged for a map in neither: E1M1's)"""
    from dataclasses import replace
    over = dict(MAP_SIZE_CONFIG.get(mapname.upper(), {}), **MAP_CONFIG.get(mapname.upper(), {}))
    return replace(cfg, **over) if over else cfg
