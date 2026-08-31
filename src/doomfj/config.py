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
    PID_NIBBLES: int = 2

    @property
    def SLOT_SHIFT(self) -> int:
        """Whole-nibble shifts for the per-column `sfslot` offset: log16(STEP_SLOT_STRIDE).

        V5 fills the slot COMPLETELY at the default width -- 2 groups x 2 pieces x 4 bytes
        (fy1, fy2, cls, bpid) = 16 of 16. (The constant's own comment still says "6 used", which
        is V3-era, before the second piece and the bpid byte.) A wider pid makes a piece 5 bytes,
        so the stride must grow -- and it must stay a POWER OF 16, because the offset is
        `hex.shl_hex w/4, SLOT_SHIFT, idx` and the alternative is a mul_const priced at ~72@.
        16 -> 256 is therefore the right jump: the SAME op count with a different constant, at
        +VIEW_W*240 words of `sfslot` (0.05% of the span). Stride 32 would need an extra shift op
        per column to save words that do not matter."""
        return 1 if self.PID_NIBBLES == 2 else 2

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
        return self.H

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

    def constants(self) -> dict:
        """The full set of fj-visible constants (the SSOT contents emitted to fj_consts.fj)."""
        return {
            "W": self.W, "H": self.H, "BPP": self.BPP, "TRIG_N": self.TRIG_N,
            "NCOLORS": self.NCOLORS, "COL_BITS": self.COL_BITS, "ROW_BITS": self.ROW_BITS,
            "VIEW_W": self.VIEW_W, "VIEW_H": self.VIEW_H,
            "CENTERX": self.CENTERX, "CENTERY": self.CENTERY, "PROJECTION": self.PROJECTION,
            "FB_SIZE": self.FB_SIZE, "PALETTE_SIZE": self.PALETTE_SIZE,
            "PID_NIBBLES": self.PID_NIBBLES, "SLOT_SHIFT": self.SLOT_SHIFT,
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
