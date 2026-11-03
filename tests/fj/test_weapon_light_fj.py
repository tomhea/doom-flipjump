"""M8 (E1M9's dark sector) -- THE WEAPON'S LIGHT ROW, run in fj against the oracle.

DOOM lights a psprite with `scalelight[lightnum][MAXLIGHTSCALE - 1]` of the PLAYER'S sector (R_DrawPSprite), and a
FF_FULLBRIGHT frame -- every flash -- with `colormaps` (row 0). E1M9's sector 141 (light 48) gives row 1, every other
sector row 0, so `hudcode.game_hud_parts` bakes one weapon drawing per row (plain and shadow), picked per frame by the
nibble `hud_lrow` that the view's descend leaf sets (`hudcode.weapon_row_lines` -- the leaf's exact text is what each
frame below runs), and the flash once, fullbright.

The program is E1M9's REAL game-screen tail (`game_hud_parts(...)["tail"]`, plasma and the shadow weapon on), presented
by the real device; the oracle is `hud.GameScreen.frame(sector=)` on the same E1M9 config. R9: a mutant that draws the
row-0 weapon whatever `hud_lrow` holds (plain, and shadow) must part from the oracle, and two oracle-side controls --
a GameScreen pinned to one row, and one lighting the flash by the sector -- must part from the fj's pictures.
"""
import re
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IOReadOnEOF

from doomfj import hud, hudcode
from doomfj import powercode as PC
from doomfj import powers as P
from doomfj import weaponcode as WC
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FULL = ROOT / "assets" / "freedoom1.wad"
needs_wad = pytest.mark.skipif(not FULL.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")

VH, HH, WIDTH = GAME_CFG.VIEW_H, GAME_CFG.H, GAME_CFG.W
DARK, LIT = 141, 0                     # E1M9: the row-1 sector (light 48) and a row-0 one
# (wp_frm, fl_frm, p_inv, sector) per frame: the weapon in both sectors, plain and shadow, with and without a flash
FRAMES = [(4, 0, 0, LIT), (4, 0, 0, DARK), (5, 1, 0, DARK), (5, 1, 0, LIT), (0, 0, 2100, DARK), (0, 0, 2100, LIT),
          (16, 4, 2100, DARK), (13, 0, 0, DARK), (15, 2, 0, DARK), (2, 0, 7, DARK), (2, 0, 8, DARK), (1, 0, 0, LIT)]
MUTANTS = {
    "fixed_row": (r"hex\.if_flags hud_lrow, 1<<0, hwfr_n0, hwfr_y0", ";hwfr_y0"),
    "fixed_shadow_row": (r"hex\.if_flags hud_lrow, 1<<0, hswr_n0, hswr_y0", ";hswr_y0"),
}
_CACHE = {}


def _setup():
    if not _CACHE:
        art = WadFile.from_path(str(FULL))
        rm = ReferenceModel(GAME_CFG)
        secs = art.sectors("E1M9")
        _CACHE.update(art=art, rm=rm, secs=secs,
                      parts=hudcode.game_hud_parts(rm, art, art, secs, shadow=True, plasma=True),
                      screen=hud.GameScreen(rm, art, art, secs, plasma=True))
    return _CACHE


class _Screen(InMemoryScreen):
    def read_bit(self):
        raise IOReadOnEOF("no input")


def _view_column(f, x):
    a, b = 10 + (x * 3 + f) % 40, 50 + (x + 5 * f) % 30
    cols = [(a, (x + f) % 256), (b, (2 * x + 1) % 256), (VH, (3 * x + f + 7) % 256)]
    out, px, y = [x], [], 0
    for y2, c in cols:
        out += [y2, c]
        px += [c] * (y2 - y)
        y = y2
    return out + [0xFF], px


def _views():
    return [bytes(_view_column(f, x)[1][y] for y in range(VH) for x in range(WIDTH)) + bytes(WIDTH * (HH - VH))
            for f in range(len(FRAMES))]


def _fj_frames(tmp_path, name, mut=None):
    c = _setup()
    parts = c["parts"]
    text = "\n".join(parts["tail"])
    if mut:
        pat, new = MUTANTS[mut]
        text, n = re.subn(pat, new, text)
        assert n == 1, "the mutant %s matches the emitted text %d times, not once" % (mut, n)
    lines = ["stl.startup_and_init_all", "screen.init_screen W, H, 8", ";frames", *parts["decls"],
             "pcard: hex.vec 1", "p_dead: hex.vec 1", "hud_ret: hex.vec w/4", "wp_frm: hex.vec 2", "fl_frm: hex.vec 1",
             *PC.decls((P.INVIS_TYPE,)),
             "hud_tail_leaf:", text, "stl.fret hud_ret", "frames:"]
    for f, (wf, ff, inv, sec) in enumerate(FRAMES):
        lines.append("screen.draw_collines")
        for x in range(WIDTH):
            lines += [f"stl.output_char {b}" for b in _view_column(f, x)[0]]
        lines += [*hudcode.weapon_row_lines(parts, sec),          # the view's descend leaf in `sec`, verbatim
                  f"hex.set 2, wp_frm, {wf}", f"hex.set 1, fl_frm, {ff}", f"hex.set 3, p_inv, {inv}",
                  "stl.fcall hud_tail_leaf, hud_ret", "screen.end_frame W, 0"]
    lines.append("stl.loop")
    src = tmp_path / (name + ".fj")
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W,
                print_time=False)
    frames = []

    class Rec(_Screen):
        def _present(self):
            super()._present()
            frames.append(bytes(self.pixel_indices))
    fj.run(out, io_device=Rec(), print_time=False, print_termination=False)
    return frames


def _oracle(gs=None):
    gs = gs or _setup()["screen"]
    names_w, names_f = WC.overlay_frames(plasma=True), WC.flash_frames(True)
    return [gs.frame(v, weapon=names_w[wf], flash=names_f[ff - 1] if ff else None, shadow=P.blinking(inv),
                     sector=sec) for v, (wf, ff, inv, sec) in zip(_views(), FRAMES)]


@pytest.fixture(scope="module")
def fj_frames(tmp_path_factory):
    return _fj_frames(tmp_path_factory.mktemp("wlight"), "wlight")


@needs_wad
def test_e1m9_lights_the_weapon_with_two_rows_and_one_leaf_line_each():
    c = _setup()
    parts = c["parts"]
    assert parts["light_rows"] == (0, 1) and parts["sector_rows"][DARK] == 1 and parts["sector_rows"][LIT] == 0
    assert [i for i, k in enumerate(parts["sector_rows"]) if k] == [DARK]
    assert hudcode.weapon_row_lines(parts, DARK) == ["    hex.set 1, hud_lrow, 1"]
    assert "hud_lrow: hex.vec 1" in parts["decls"]
    # one row (E1M1): no cell, no leaf line -- the descend leaf's text as before
    e1 = hudcode.game_hud_parts(c["rm"], c["art"], c["art"], c["art"].sectors("E1M1"))
    assert e1["light_rows"] == (0,) and hudcode.weapon_row_lines(e1, 0) == []
    assert not any("hud_lrow" in ln for ln in e1["decls"] + e1["tail"])
    assert P.blinking(2100) and not P.blinking(7) and P.blinking(8)


@needs_wad
def test_the_weapon_takes_the_players_sector_row(fj_frames):
    want = _oracle()
    assert len(fj_frames) == len(want)
    bad = [f for f, (a, b) in enumerate(zip(fj_frames, want)) if a != b]
    assert not bad, "frames %s differ: %s" % (bad, [FRAMES[f] for f in bad])
    # the rows really differ where the weapon is: the dark sector's weapon is not the lit one's
    assert want[0] != _oracle_one(4, 0, 0, DARK)


def _oracle_one(wf, ff, inv, sec):
    gs = _setup()["screen"]
    names_w, names_f = WC.overlay_frames(plasma=True), WC.flash_frames(True)
    return gs.frame(_views()[0], weapon=names_w[wf], flash=names_f[ff - 1] if ff else None, shadow=P.blinking(inv),
                    sector=sec)


@needs_wad
@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_fixed_row_weapon_is_caught(tmp_path, mut):
    frames = _fj_frames(tmp_path, "wl_" + mut, mut)
    want = _oracle()
    assert any(a != b for a, b in zip(frames, want)), "the mutant %s went unnoticed" % mut


@needs_wad
def test_control_an_oracle_pinned_to_one_row_or_lighting_the_flash_parts(fj_frames):
    import copy
    gs = copy.copy(_setup()["screen"])
    gs.sector_rows = tuple(0 for _ in gs.sector_rows)              # the old baked row, whatever the sector
    assert any(a != b for a, b in zip(fj_frames, _oracle(gs))), "a fixed-row oracle matched the fj"
    gs = copy.copy(_setup()["screen"])
    gs.flash_lumps = set()                                         # the flash lit by the sector, not fullbright
    assert any(a != b for a, b in zip(fj_frames, _oracle(gs))), "a sector-lit flash matched the fj"
