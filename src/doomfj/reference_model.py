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
from doomfj.fixedpoint import fixed_mul, _signed  # shared signed Q-format kernel (R6)
from doomfj.mapcompiler import NF_SUBSECTOR, CompiledMap, compile_bsp, _point_side  # shared geometry (R6)
from doomfj.tables import sine_table
from doomfj.texturecompiler import downscale_canvas  # shared D5 downscale lever (R6/D12)
from doomfj.wad import WadFile

# ── sim / angle constants (BAM: full turn = 2**32) ──
FULL_CIRCLE = 1 << 32
ANG90 = FULL_CIRCLE // 4          # 0x40000000 — 90deg, sanity anchor for the trig index
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
    `map_wad` carries geometry (VERTEXES/LINEDEFS/SIDEDEFS/SECTORS + the THINGS spawn); `asset_wad`
    carries graphics (PLAYPAL/COLORMAP). `cmap` is the BSP built once by mapcompiler (H3)."""
    map_wad: WadFile
    asset_wad: WadFile
    mapname: str
    cmap: CompiledMap


def build_scene(map_wad: WadFile, asset_wad: WadFile, mapname: str) -> Scene:
    """Compile the level's BSP once and bundle the render inputs."""
    return Scene(map_wad, asset_wad, mapname, compile_bsp(map_wad, mapname))


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

    # ── trig (the M6 read_sin/read_cos idioms; cos shares the sine table at +N/4) ──
    def read_sin(self, angle: int) -> int:
        return self.sine[(angle >> self.angle_shift) & (self.cfg.TRIG_N - 1)]

    def read_cos(self, angle: int) -> int:
        idx = (angle >> self.angle_shift) + self.cfg.TRIG_N // 4
        return self.sine[idx & (self.cfg.TRIG_N - 1)]

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
