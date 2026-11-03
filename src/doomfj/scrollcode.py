"""M8 -- THE SCROLLING WALL (DOOM's line special 48), as the game tier can show it: both mirrors' ONE definition.

DOOM: P_UpdateSpecials adds FRACUNIT to the front sidedef's textureoffset of every special-48 line once a tic, so its
texture slides one texel a tic. THE GAME TIER HAS NO TEXTURE U: a W1R wall is a two-texel, ONE-COLUMN canvas
(`ReferenceModel._tiny_wall_canvas`) drawn as pseudo-random runs keyed on the SCREEN column (`w1r_runs(h, x +
w1r_xoff)`; fj: `p2_xkey = x + wnoff`), and the fj never emits `proj.texture_u` -- a moved textureoffset changes no
pixel (measured: scratchpad/p48_scroll_probe.py, 0 pixels at offsets 1..64 where the textured control moves 89 ..
1,137).

So the tier's visible form (the integrator's decision, 2026-10-18, under the owner's "<= +0.5%" rule): the pattern KEY
of a scrolling line's segs slides instead -- key = x + wnoff + (leveltime & WALL_SCROLL_MASK), a screen column a
frame (the walls run one world tic a frame). RECORDED AS A DELIBERATE APPROXIMATION: screen-space, not world-anchored
(the pattern does not stick to the wall), and it jumps once every 256 frames when the low byte wraps.

  * the model: `render_wall_frame(wall_scroll=)` (`World.wall_scroll()`, the ONE place the value is made, from
    `ws.leveltime`), applied to the segs of `scroll_lines(lds)` when the map's Config has WALL_SCROLL
    (config.MAP_CONFIG: E1M2) -- the wall's runs AND the step faces of every column that seg draws (fj keys a column's
    faces on the same p2_xkey);
  * the fj: `pass2_lines(True)` wraps the seg's pass-2 call in a wnoff save / add / restore (lvtime's low byte), and
    the wnoise tables grow by WALL_SCROLL_MASK entries (`wnoise_domain`) -- in the game tier (lvtime exists) of a map
    with WALL_SCROLL only. E1M1 (WALL_SCROLL 0) emits exactly the text it did.
"""
from __future__ import annotations

from typing import List

SCROLL_SPECIALS = frozenset({48})          # DOOM's "scroll texture left" line (P_UpdateSpecials)
WALL_SCROLL_MASK = 0xFF                    # the key's slide: leveltime's low byte (lvtime's nibbles 0..1)
SCROLL_NIBBLES = 2
assert WALL_SCROLL_MASK == (1 << (4 * SCROLL_NIBBLES)) - 1
W1R_TURN_COLS = 640                        # wnoff's range: viewangle * 640 columns a turn >> 32 (W1R-ANCHOR)

# the per-seg wrap's two cells: `wnsave` is written before it is read (the save); `wnscr`'s nibbles 2..3 are never
# written (only its low byte is, by the mov), so they stay the declared 0 -- neither needs the M1 restore set
DECLS = ["wnsave: hex.vec 4", "wnscr: hex.vec 4, 0"]

PASS2_CALL = "    stl.fcall seg_pass2_leaf, seg_ret2"


def scroll_lines(lds) -> frozenset:
    """the linedef indices whose texture scrolls (special 48)"""
    return frozenset(i for i, ld in enumerate(lds) if ld.special in SCROLL_SPECIALS)


def seg_scrolls(seg, lines: frozenset) -> bool:
    """the emitter's choice for one seg: it slides when its linedef is one of `lines` (`scroll_lines`, or the empty
    set off a scrolling map's game tier)"""
    return seg.linedef in lines


def scroll_on(cfg, mapname: str) -> bool:
    """the map scrolls its walls (config.MAP_CONFIG's WALL_SCROLL for `mapname`, over `cfg`)"""
    from doomfj.config import map_cfg
    return bool(map_cfg(cfg, mapname).WALL_SCROLL)


def wall_scroll_of(leveltime: int) -> int:
    """the frame's key slide from the model's leveltime (fj: lvtime's low SCROLL_NIBBLES nibbles)"""
    return leveltime & WALL_SCROLL_MASK


def pass2_lines(scrolls: bool) -> List[str]:
    """a seg's pass-2 call in the BSP code (wall_renderer's seg block): the plain call, or -- a scrolling seg --
    wrapped: wnoff saved, lvtime's low byte added (hex.add 4: wnoff + it < 4096 never carries out), the
    pass (every column's p2_xkey = x + wnoff reads the slid offset), wnoff restored for the segs after it"""
    if not scrolls:
        return [PASS2_CALL]
    return ["    hex.mov 4, wnsave, wnoff",
            "    hex.mov %d, wnscr, lvtime" % SCROLL_NIBBLES,
            "    hex.add 4, wnoff, wnscr",
            PASS2_CALL,
            "    hex.mov 4, wnoff, wnsave"]


def wnoise_domain(view_w: int, w1r: bool, scroll: bool) -> int:
    """the wnoise / wnoise2 / wnoise3 tables' entry count: every key a column can form -- x (0..VIEW_W) + wnoff
    (0..639, W1R) + the slide (0..WALL_SCROLL_MASK, a scrolling map's game tier)"""
    return view_w + 1 + (W1R_TURN_COLS if w1r else 0) + (WALL_SCROLL_MASK if scroll else 0)
