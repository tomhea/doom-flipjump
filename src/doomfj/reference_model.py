"""H5 — reference model / oracle (M9). The host-side **exact-integer** golden renderer + sim (D12):
the test oracle every fj-program milestone (M11+) diffs against, byte-for-byte.

It composes only the **shared** integer kernels — `tables.py` (finesine), `fixedpoint.py` (signed
Q-format mul), `mapcompiler.py` (the built BSP + its `_point_side` geometry), `config.py` (the
resolution SSOT), and the WAD's own COLORMAP — so the oracle and the program cannot drift (R6).
Nothing here re-derives a constant or a formula that already lives in one of those modules.

M9 is the smallest honest cut (it grows as F5 features land, per the ladder):
  * `step_sim`  — turn (BAM add) + collision-free move (FixedMul against the finesine table). S0's
    line-based collision lands at M14; until then a step is pure turn/translate.
  * `point_in_subsector` — R_PointInSubsector: the permanent BSP point-location primitive (signed
    side tests, DOOM right=front convention) shared by both the sim and the renderer.
  * `render_frame` — the spawn frame: a colormap-shaded ceiling/floor background at the sub-sector's
    sector light. With no walls/visplanes yet (M12/M13) an empty view IS this two-band clear; walls
    will overwrite columns later. The band base indices are placeholders (CEIL_BG/FLOOR_BG) until
    real flats land — refining them only re-blesses the goldens off this oracle, which is the point.

Angles are BAM (binary angle measurement: a full turn = 2**32). The finesine table is indexed by the
top log2(TRIG_N) bits (ANGLE_TO_FINE_SHIFT, config-derived — never a literal 20/12), and cosine
shares the sine table at +TRIG_N/4 (the M6 idiom). Player position is the only genuine 16.16 quantity
(§1.1.4); BSP side tests truncate it to 16.0 integer map coords.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul, fixed_div, _signed  # shared signed Q-format kernels (R6)
from doomfj.mapcompiler import NF_SUBSECTOR, CompiledMap, bake_bsp, _point_side  # shared geometry (R6)
from doomfj.tables import sine_table, tantoangle_table, viewangletox_table
from doomfj.texturecompiler import downscale_canvas  # shared D5 downscale lever (R6/D12)
from doomfj.wad import WadFile

# ── sim / angle constants (BAM: full turn = 2**32) ──
FULL_CIRCLE = 1 << 32
ANGLE_MASK = FULL_CIRCLE - 1      # wrap BAM arithmetic to unsigned 32-bit
ANG90 = FULL_CIRCLE // 4          # 0x40000000 — 90deg, sanity anchor for the trig index
ANG180 = FULL_CIRCLE // 2         # 0x80000000
ANG270 = 3 * (FULL_CIRCLE // 4)   # 0xC0000000
ANG45 = FULL_CIRCLE // 8          # 0x20000000
CLIPANGLE = ANG45                 # half the 90° FOV — the view frustum's edge angle (R_AddLine clip)
SLOPERANGE = 2048                 # R_PointToAngle slope quotient range (DOOM SLOPERANGE); tantoangle has +1
DBITS = 5                          # FRACBITS(16) - SLOPEBITS(11): the FixedDiv→tantoangle index shift (R_PointToDist)
SCALE_MIN = 256                    # R_ScaleFromGlobalAngle clamp floor (16.16)
SCALE_MAX = 64 << 16               # R_ScaleFromGlobalAngle clamp ceiling = 64.0 (16.16)
VIEWHEIGHT = 41                    # DOOM player eye height above the floor (map units)
FORWARD_MOVE = 50 << 16           # 16.16 map-units per tic (DOOM run forwardmove 0x32); S0 magnitude
ANGLE_TURN = 640 << 16            # BAM per tic (DOOM angleturn[]); turn-left adds, turn-right subtracts

# ── render: placeholder background band base indices (until real flats/visplanes, M13) ──
CEIL_BG = 0                       # ceiling band palette index (pre-colormap)
FLOOR_BG = 96                     # floor band palette index (pre-colormap)
LIGHT_SHIFT = 3                   # sector light (0..255) -> colormap row (0..31): light >> 3
COLORMAP_LIGHTS = 32              # COLORMAP usable light rows (0..31; invuln/black sit past these)


def _deg_to_bam(deg: int) -> int:
    """A THINGS angle (degrees) as BAM. 90deg -> 0x40000000 exactly (360 divides 2**32 evenly here)."""
    return round(deg / 360 * FULL_CIRCLE) % FULL_CIRCLE


@dataclass(frozen=True)
class SimState:
    x: int          # player position, 16.16 (the only genuine 16.16 quantity, §1.1.4)
    y: int          # 16.16
    angle: int      # 32-bit BAM
    level: str      # current level lump name


@dataclass(frozen=True)
class Scene:
    """The static data a frame is rendered against — the SAME inputs the program is built from (R6).
    `map_wad` carries geometry (VERTEXES/LINEDEFS/SIDEDEFS/SECTORS + the THINGS spawn + the baked
    SEGS/SSECTORS/NODES); `asset_wad` carries graphics (PLAYPAL/COLORMAP). `cmap` is the BSP baked
    once from those lumps by mapcompiler (H3)."""
    map_wad: WadFile
    asset_wad: WadFile
    mapname: str
    cmap: CompiledMap


def build_scene(map_wad: WadFile, asset_wad: WadFile, mapname: str) -> Scene:
    """Bake the level's BSP once (from the WAD's NODES/SSECTORS/SEGS) and bundle the render inputs."""
    return Scene(map_wad, asset_wad, mapname, bake_bsp(map_wad, mapname))


def spawn_state(wad: WadFile, mapname: str, *, player: int = 1) -> SimState:
    """The player-`player` start (THINGS type 1 = Player 1) as a SimState: pos<<16, angle as BAM."""
    th = next(t for t in wad.things(mapname) if t.type == player)
    return SimState(th.x << 16, th.y << 16, _deg_to_bam(th.angle), mapname)


def frame_hash(frame: bytes) -> str:
    """The per-frame sha256 the present layer logs (ScreenIO) — the bit-exact golden key (D12)."""
    return hashlib.sha256(frame).hexdigest()


def screen_frame_hash(indices, palette_rgb) -> str:
    """The device's per-frame sha256 (ScreenIO logs it per present, D12): sha256 over the raw palette
    indices followed by the palette RGB bytes. The golden key M11a+ diffs against."""
    return hashlib.sha256(bytes(indices) + bytes(palette_rgb)).hexdigest()


class ReferenceModel:
    """Holds the config + the shared finesine table (built once) and exposes the oracle entry points
    `step_sim(state, keys) -> state` and `render_frame(state, scene) -> bytes` (the H5 signatures)."""

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.sine = sine_table(self.cfg.TRIG_N, 16, 32)        # shared LUT values (R6)
        # finesine index = top log2(TRIG_N) bits of the BAM angle (config-derived, not a literal 20)
        self.angle_shift = 32 - (self.cfg.TRIG_N.bit_length() - 1)
        self.downscale = self.cfg.TEXTURE_DOWNSCALE   # the shared D5 factor (used once textures sample, M11b)
        self.tantoangle = tantoangle_table(SLOPERANGE)        # R_PointToAngle slope->BAM (M12b, shared R6)
        self.viewangletox = viewangletox_table(self.cfg.VIEW_W, self.cfg.TRIG_N)   # angle->column (M12c, R6)

    # ── trig (the M6 read_sin/read_cos idioms; cos shares the sine table at +N/4) ──
    def read_sin(self, angle: int) -> int:
        return self.sine[(angle >> self.angle_shift) & (self.cfg.TRIG_N - 1)]

    def read_cos(self, angle: int) -> int:
        idx = (angle >> self.angle_shift) + self.cfg.TRIG_N // 4
        return self.sine[idx & (self.cfg.TRIG_N - 1)]

    # ── projection angles (R_PointToAngle2, M12b) ──
    @staticmethod
    def _slope_div(num: int, den: int) -> int:
        """DOOM SlopeDiv: the tantoangle index for slope num/den (num <= den, both >= 0). Tuned for
        16.16 magnitudes — `den < 512` ⇒ the slope is ~0/clamped to SLOPERANGE; else `(num<<3)/(den>>8)`
        clamped to SLOPERANGE. Inputs must be 16.16-scale (the renderer's world units) to match DOOM."""
        if den < 512:
            return SLOPERANGE
        ans = (num << 3) // (den >> 8)
        return ans if ans <= SLOPERANGE else SLOPERANGE

    def point_to_angle(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """R_PointToAngle2: the BAM angle of the vector (x1,y1) -> (x2,y2). Octant fold + `tantoangle`
        lookup on the SlopeDiv quotient (the shared kernel, R6) — no atan at runtime. Coords are 16.16
        world units (the SlopeDiv tuning is scale-dependent). Returns a 32-bit BAM (East=0, North≈ANG90,
        with DOOM's ±1 octant-boundary quirks; e.g. due north = ANG90-1). The fj renderer matches this."""
        x, y = x2 - x1, y2 - y1
        if x == 0 and y == 0:
            return 0
        t = self.tantoangle
        if x >= 0:
            if y >= 0:
                return t[self._slope_div(y, x)] if x > y \
                    else (ANG90 - 1 - t[self._slope_div(x, y)]) & ANGLE_MASK
            y = -y
            return (-t[self._slope_div(y, x)]) & ANGLE_MASK if x > y \
                else (ANG270 + t[self._slope_div(x, y)]) & ANGLE_MASK
        x = -x
        if y >= 0:
            return (ANG180 - 1 - t[self._slope_div(y, x)]) & ANGLE_MASK if x > y \
                else (ANG90 + t[self._slope_div(x, y)]) & ANGLE_MASK
        y = -y
        return (ANG180 + t[self._slope_div(y, x)]) & ANGLE_MASK if x > y \
            else (ANG270 - 1 - t[self._slope_div(x, y)]) & ANGLE_MASK

    def angle_to_x(self, view_relative_angle: int) -> int:
        """Screen column for a view-relative BAM angle (0 = straight ahead, + = left, per the BAM/CCW
        convention). Index `viewangletox` at `(angle + ANG90) >> angle_shift`; the angle should already be
        clipped to the FOV [-ANG90, ANG90) by the wall path — out-of-range indices clamp to the table ends
        (DOOM's off-screen sentinels). Returns a column in [-1, VIEW_W+1]."""
        idx = ((view_relative_angle + ANG90) & ANGLE_MASK) >> self.angle_shift
        idx = max(0, min(len(self.viewangletox) - 1, idx))
        return self.viewangletox[idx]

    def point_to_dist(self, viewx: int, viewy: int, x: int, y: int) -> int:
        """R_PointToDist: the distance from (viewx,viewy) to (x,y) — `dist = dx / cos(atan(dy/dx))` =
        sqrt(dx²+dy²), computed via tantoangle + finesine + FixedDiv (no sqrt). Fold to the major octant
        (dx >= dy), index tantoangle by the FixedDiv slope >> DBITS, then divide dx by sin(angle+90°) =
        cos(angle). Coords + result are 16.16 (the FixedDiv tuning is scale-dependent). Exact for
        axis-aligned (dy=0 ⇒ dist=dx); ~quantization error off-axis. Returns 0 for the degenerate point."""
        dx, dy = abs(x - viewx), abs(y - viewy)
        if dy > dx:
            dx, dy = dy, dx
        if dx == 0:
            return 0
        idx = min((fixed_div(dy, dx, 8, 4) >> DBITS), SLOPERANGE)   # slope dy/dx in [0,1] -> [0,SLOPERANGE]
        angle = (self.tantoangle[idx] + ANG90) & ANGLE_MASK
        sine = self.read_sin(angle)                                 # sin(atan(slope)+90deg) = cos(atan(slope))
        return fixed_div(dx, sine, 8, 4) if sine else 0

    # ── wall scale (R_StoreWallRange setup + R_ScaleFromGlobalAngle, M12e) ──
    def wall_setup(self, viewx: int, viewy: int, seg, verts) -> tuple:
        """The per-wall projection setup (DOOM R_StoreWallRange): returns `(rw_normalangle, rw_distance)`.
        `rw_normalangle = seg.angle_BAM + ANG90` (the wall's normal — DOOM's native convention, valid now
        the segs are BAKED with DOOM-standard winding; verified on real E1M1: it yields the true
        perpendicular distance + positive scale, whereas -ANG90 gives 0). `rw_distance` = the perpendicular
        view→wall-line distance = `hyp · sin(distangle)`, where hyp = point_to_dist(view, v1) and distangle
        = ANG90 - the clamped normal↔v1 offset angle. `viewx/y` are 16.16; `verts` are 16.0 (shifted <<16)."""
        v1x, v1y = verts[seg.v1]
        v1x <<= 16
        v1y <<= 16
        rw_normalangle = ((seg.angle << 16) + ANG90) & ANGLE_MASK
        angle1 = self.point_to_angle(viewx, viewy, v1x, v1y)
        offsetangle = (rw_normalangle - angle1) & ANGLE_MASK
        if offsetangle > ANG180:
            offsetangle = (-offsetangle) & ANGLE_MASK                # BAM abs (fold to [0, ANG180])
        if offsetangle > ANG90:
            offsetangle = ANG90
        distangle = (ANG90 - offsetangle) & ANGLE_MASK
        hyp = self.point_to_dist(viewx, viewy, v1x, v1y)
        rw_distance = fixed_mul(hyp, self.read_sin(distangle), 8, 4)
        return rw_normalangle, rw_distance

    def scale_from_global_angle(self, visangle: int, viewangle: int,
                                rw_normalangle: int, rw_distance: int) -> int:
        """R_ScaleFromGlobalAngle: the wall's projected scale (16.16 pixels per world unit) for the screen
        column whose ABSOLUTE view angle is `visangle`. scale = PROJECTION·sin(angleb) / (rw_distance·
        sin(anglea)), where anglea = ANG90+(visangle-viewangle), angleb = ANG90+(visangle-rw_normalangle),
        PROJECTION = CENTERX<<16. Clamped to [SCALE_MIN, SCALE_MAX]. At the centre of a perpendicular wall
        (visangle=viewangle=rw_normalangle) this is exactly PROJECTION/rw_distance."""
        anglea = (ANG90 + (visangle - viewangle)) & ANGLE_MASK
        angleb = (ANG90 + (visangle - rw_normalangle)) & ANGLE_MASK
        num = fixed_mul(self.cfg.PROJECTION << 16, self.read_sin(angleb), 8, 4)
        den = fixed_mul(rw_distance, self.read_sin(anglea), 8, 4)
        if den == 0:
            return SCALE_MAX
        return max(SCALE_MIN, min(SCALE_MAX, fixed_div(num, den, 8, 4)))

    def wall_x_range(self, viewx: int, viewy: int, viewangle: int, seg, verts):
        """R_AddLine: the seg's screen column range. Returns `(x1, x2, rw_angle1)` — x1 the left column,
        x2 the right column (x1 < x2; the wall covers [x1, x2) per DOOM) and rw_angle1 the absolute angle
        to v1 (for the per-column scale, M12g) — or None if the seg is back-facing or entirely outside the
        90° FOV. Both seg endpoints' absolute angles (point_to_angle), back-face cull (span ≥ ANG180),
        then make view-relative and clip to [-CLIPANGLE, CLIPANGLE] via DOOM's unsigned tspan logic, then
        map to columns via angle_to_x. `viewx/y/angle` are 16.16/BAM; `verts` are 16.0 (shifted <<16)."""
        v1, v2 = verts[seg.v1], verts[seg.v2]
        # DOOM-standard winding (baked segs): v1 is the seg's LEFT screen vertex, v2 the RIGHT — so a
        # front-facing wall gives span < ANG180 (verified on real E1M1; the M7-era v1/v2 swap is gone).
        angle1 = self.point_to_angle(viewx, viewy, v1[0] << 16, v1[1] << 16)   # left vertex
        angle2 = self.point_to_angle(viewx, viewy, v2[0] << 16, v2[1] << 16)   # right vertex
        span = (angle1 - angle2) & ANGLE_MASK
        if span >= ANG180:
            return None                                  # back-facing (or degenerate)
        rw_angle1 = angle1
        angle1 = (angle1 - viewangle) & ANGLE_MASK        # view-relative
        angle2 = (angle2 - viewangle) & ANGLE_MASK
        two_clip = 2 * CLIPANGLE                           # = ANG90 (full FOV)

        tspan = (angle1 + CLIPANGLE) & ANGLE_MASK          # clip to the LEFT frustum edge
        if tspan > two_clip:
            if ((tspan - two_clip) & ANGLE_MASK) >= span:
                return None                              # wall entirely off the left
            angle1 = CLIPANGLE
        tspan = (CLIPANGLE - angle2) & ANGLE_MASK          # clip to the RIGHT frustum edge
        if tspan > two_clip:
            if ((tspan - two_clip) & ANGLE_MASK) >= span:
                return None                              # wall entirely off the right
            angle2 = (-CLIPANGLE) & ANGLE_MASK

        x1, x2 = self.angle_to_x(angle1), self.angle_to_x(angle2)
        if x1 >= x2:
            return None                                  # sub-column / not visible
        return x1, x2, rw_angle1

    # ── wall heights (R_RenderSegLoop top/bottom projection, M12g) ──
    @staticmethod
    def view_z(floor_h: int) -> int:
        """The view (eye) z in 16.16 — for a flat level the player z is the floor height, so the eye sits
        VIEWHEIGHT(41) map units above it."""
        return (floor_h + VIEWHEIGHT) << 16

    def wall_screen_span(self, ceil_h: int, floor_h: int, viewz: int, scale: int) -> tuple:
        """The screen rows `(top, bottom)` a wall column occupies, for the front sector's ceiling/floor
        heights (map units), the eye `viewz` (16.16), and the column's `scale` (16.16). DOOM: worldtop =
        ceiling - viewz, worldbottom = floor - viewz (16.16); top = CENTERY - worldtop·scale, bottom =
        CENTERY - worldbottom·scale. Rows may be off-screen (< 0 or >= VIEW_H) — the render loop (M12h)
        clips them. `top < bottom` always (ceiling above floor)."""
        centeryfrac = self.cfg.CENTERY << 16
        worldtop = (ceil_h << 16) - viewz
        worldbottom = (floor_h << 16) - viewz
        topfrac = centeryfrac - _signed(fixed_mul(worldtop, scale, 8, 4), 32)
        bottomfrac = centeryfrac - _signed(fixed_mul(worldbottom, scale, 8, 4), 32)
        return topfrac >> 16, bottomfrac >> 16

    # ── sim ──
    def step_sim(self, state: SimState, keys: dict) -> SimState:
        """One tic: turn then collision-free move (collision is M14). FixedMul(move, cos/sin) in 16.16
        (n=8 nibbles, f=4 fraction nibbles) mirrors the fj path exactly; angle wraps mod 2**32."""
        angle = state.angle
        if keys.get("turn_left"):
            angle = (angle + ANGLE_TURN) & 0xFFFFFFFF
        if keys.get("turn_right"):
            angle = (angle - ANGLE_TURN) & 0xFFFFFFFF

        move = 0
        if keys.get("forward"):
            move += FORWARD_MOVE
        if keys.get("back"):
            move -= FORWARD_MOVE

        x, y = state.x, state.y
        if move:
            m = move & 0xFFFFFFFF  # two's-complement; fixed_mul interprets the sign (n=8)
            x = (x + fixed_mul(m, self.read_cos(angle), 8, 4)) & 0xFFFFFFFF
            y = (y + fixed_mul(m, self.read_sin(angle), 8, 4)) & 0xFFFFFFFF
        return replace(state, x=x, y=y, angle=angle)

    def render_textured_column(self, texels, texheight, texcol, colormap, light, *,
                               count, frac0, step, fracbits=8):
        """One textured wall column (F5 core) — the texture-v DDA. For `count` screen rows, sample the
        texture's `texcol` column at v = (frac >> fracbits) & (texheight-1) (heightmask, pow2 height),
        apply the colormap at `light`, accumulate frac += step in 8.8 (wraps mod 2**16). Returns the
        lit palette bytes top-to-bottom. The fj renderer reproduces this exactly (D12); `texels` and
        `colormap` are the shared M8 data (R6). texel index is column-major: col*texheight + v."""
        out = bytearray()
        frac = frac0
        mask = texheight - 1
        for _ in range(count):
            v = (frac >> fracbits) & mask
            pal = texels[texcol * texheight + v]
            out.append(colormap[light][pal])
            frac = (frac + step) & 0xFFFF
        return bytes(out)

    def render_unroll_frame(self, texels, texheight, texwidth, colormap, light, *,
                            width, count, frac0, step, fracbits=8) -> bytes:
        """The M11c synthetic full-unroll frame (the D2 bake-off workload): every screen column x in
        [0, width) is the texture-v DDA over texcol = x % texwidth (a full-width texture splat), `count`
        rows tall, at a constant column `light`. Returns a row-major W*H frame; the rendered region is
        [row<count][x<width], everything else stays zero (the register framebuffer's zero-init). The fj
        full-unroll renderer reproduces this bit-exactly (D12) — each column is render_textured_column,
        placed row-major at (x, row)."""
        cfg = self.cfg
        fb = bytearray(cfg.FB_SIZE)
        for x in range(width):
            col = self.render_textured_column(texels, texheight, x % texwidth, colormap, light,
                                              count=count, frac0=frac0, step=step, fracbits=fracbits)
            for row in range(count):
                fb[row * cfg.W + x] = col[row]
        return bytes(fb)

    def render_solid_column(self, col_x: int, color: int, *, bg: int = 0) -> bytes:
        """M11a's golden frame: a framebuffer cleared to `bg` with column `col_x` filled with `color`
        (row-major W*H palette indices). The simplest renderer-primitive frame — the fj program
        produces it bit-exactly via F4 fixed-address packed stores + the F7 0x03 present."""
        cfg = self.cfg
        fb = bytearray([bg]) * cfg.FB_SIZE
        for row in range(cfg.H):
            fb[row * cfg.W + col_x] = color
        return bytes(fb)

    # ── BSP point location (R_PointInSubsector) ──
    def point_in_subsector(self, cmap: CompiledMap, x: int, y: int) -> int:
        """Walk the BSP from the root to the leaf containing integer map point (x, y). The side test is
        mapcompiler's shared `_point_side` (>0 back/left, else front/right — DOOM's right=front, with
        on-the-line counted as front). Returns the subsector index (the NF_SUBSECTOR bit stripped)."""
        node = cmap.root
        while not node & NF_SUBSECTOR:
            n = cmap.nodes[node]
            side = _point_side(n.x, n.y, n.dx, n.dy, x, y)
            node = n.left if side > 0 else n.right
        return node & (NF_SUBSECTOR - 1)

    def bsp_render_order(self, cmap: CompiledMap, vx: int, vy: int) -> list:
        """R_RenderBSPNode: the front-to-back subsector visit order from viewpoint (vx, vy) [16.0 map
        coords]. At each node the viewer's side (`_point_side > 0` ⇒ back/left, else front/right, R6) is
        the NEAR child — descend it first, then the far child — so subsectors come out nearest-first (the
        order walls are drawn for solid-seg clipping). Iterative (explicit stack): the M7-built BSP is
        unbalanced/deep (~1829 segs on E1M1), so recursion would overflow — exactly why F5 reserves the
        runtime stack for the BSP's upper levels (§2.1). Returns subsector indices."""
        order = []
        stack = [cmap.root]
        while stack:
            child = stack.pop()
            if child & NF_SUBSECTOR:
                order.append(child & (NF_SUBSECTOR - 1))
            else:
                n = cmap.nodes[child]
                back = _point_side(n.x, n.y, n.dx, n.dy, vx, vy) > 0
                near, far = (n.left, n.right) if back else (n.right, n.left)
                stack.append(far)    # far pushed first ⇒ popped (drawn) after the whole near subtree
                stack.append(near)   # near on top ⇒ drawn first (front-to-back)
        return order

    def visible_segs(self, cmap: CompiledMap, vx: int, vy: int) -> list:
        """The seg indices (into `cmap.segs`) of every visible subsector, flattened in BSP front-to-back
        order — the wall draw order. Each subsector contributes its `firstseg .. firstseg+numsegs`."""
        segs = []
        for ss in self.bsp_render_order(cmap, vx, vy):
            s = cmap.subsectors[ss]
            segs.extend(range(s.firstseg, s.firstseg + s.numsegs))
        return segs

    def _sector_light(self, scene: Scene, subsector: int) -> int:
        """Light level of the sector the subsector belongs to: subsector -> first seg -> linedef side
        -> sidedef -> sector (all from the same WAD geometry, R6)."""
        ss = scene.cmap.subsectors[subsector]
        seg = scene.cmap.segs[ss.firstseg]
        ld = scene.map_wad.linedefs(scene.mapname)[seg.linedef]
        sd_idx = ld.front if seg.side == 0 else ld.back
        sd = scene.map_wad.sidedefs(scene.mapname)[sd_idx]
        return scene.map_wad.sectors(scene.mapname)[sd.sector].light

    # ── render ──
    def render_frame(self, state: SimState, scene: Scene) -> bytes:
        """The spawn frame: a colormap-shaded ceiling/floor background. Find the player's subsector
        (16.0 truncation of the 16.16 position), read its sector light, pick the colormap row, and
        fill the top VIEW_H/2 rows with the shaded ceiling index and the rest with the floor index.
        Returns W*H packed palette-index bytes (row-major, D3)."""
        cfg = self.cfg
        colormap = scene.asset_wad.colormap()

        px = _signed(state.x, 32) >> 16   # 16.16 -> 16.0 integer map coord (sign-extended, §1.1.4)
        py = _signed(state.y, 32) >> 16
        subsector = self.point_in_subsector(scene.cmap, px, py)
        light = self._sector_light(scene, subsector)
        row = max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

        ceil = colormap[row][CEIL_BG]
        floor = colormap[row][FLOOR_BG]

        fb = bytearray(cfg.FB_SIZE)
        horizon = cfg.VIEW_H // 2
        for y in range(cfg.VIEW_H):
            val = ceil if y < horizon else floor
            base = y * cfg.VIEW_W
            for x in range(cfg.VIEW_W):
                fb[base + x] = val
        return bytes(fb)
