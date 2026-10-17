"""M8 F4 -- the status bar's KEYS area with E1M2's yellow and red cards, emitted as REAL fj (`hudcode.hud_tail_lines(
cards=)`) and presented by the REAL device, against the oracle's picture (`hud.bar_pixels(yellow=, red=)`, what
`hud.GameScreen.frame` composes from `monsters.MonsterPhase.screen_kw`'s values).

The yellow and red icons are slots after every E1M1 slot (`hud.bar_slots(cards)`), each reading its card cell directly
(`hudcode.VALUE_CELLS`: `pcard_y` / `pcard_r`, lootcode's), as the blue icon reads `pcard`. Each frame: a synthetic view
(84 rows), the cards and the bar values set, the game tier's tail, the frame's 0xFF; a "menu" frame paints every row
and sets `hud_full`. The device keeps rows nobody writes, so an icon the fj forgets to redraw shows its OLD state: the
script takes and loses each card alone and together, and covers the redraw after a menu.

E1M1 (`cards=()`) keeps its slots and its tail text -- tests/host/test_hud_keys.py.

R9: three mutants of the real emitted text, each caught at the frame stated in advance --
  * the red icon reading the yellow card's cell -> frame 1 (the yellow card alone);
  * the yellow icon's change test inverted (redrawn only when it did NOT change) -> frame 0 (its boot draw skipped);
  * the red icon's variants swapped (held drawn as empty) -> frame 0.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj import hud, hudcode
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
SRC = [ROOT / "src" / "fj" / "present.fj"]
ART = ROOT / "assets" / "freedoom1.wad"
VH, H, WIDTH = GAME_CFG.VIEW_H, GAME_CFG.H, GAME_CFG.W
MENU_COLOUR = 77
CARDS = ("yellow", "red")
needs_art = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")

_B = dict(ammo=50, health=100, armor=0, owned=(True, False, False, False, False, False))
# (blue, yellow, red) per frame: None = a MENU frame
SCRIPT = [(False, False, False),        # 0: boot (hud_full)
          (False, True, False),         # 1: the yellow card alone
          (False, True, True),          # 2: + the red
          (True, True, True),           # 3: all three
          (True, False, True),          # 4: the yellow lost (NEW GAME's zero, as a value)
          None,                         # 5: a menu frame
          (True, False, True),          # 6: the bar again, unchanged values
          (False, False, False),        # 7: every card gone
          (False, False, True)]         # 8: the red alone


class _Screen(InMemoryScreen):
    def read_bit(self):
        from flipjump.utils.exceptions import IOReadOnEOF
        raise IOReadOnEOF("no input")


def _view_column(f, x):
    """frame f's synthetic view column x: (records, pixels) -- a 3-run column, or a partial ditto of x - 1"""
    if x % 7 == 3:
        return [x, 0xFD, VH, 0xFF], None
    a, b = 10 + (x * 3 + f) % 40, 50 + (x + 5 * f) % 30
    cols = [(a, (x + f) % 256), (b, (2 * x + 1) % 256), (VH, (3 * x + f + 7) % 256)]
    out, px, y = [x], [], 0
    for y2, c in cols:
        out += [y2, c]
        px += [c] * (y2 - y)
        y = y2
    return out + [0xFF], px


def _vals(cards):
    blue, yellow, red = cards
    return dict(_B, blue=blue, yellow=yellow, red=red)


def _program(mutate=None):
    art = WadFile.from_path(str(ART))
    colours = hud.bar_colours(bytes(b for rgb in art.playpal(0) for b in rgb))
    overlay = hud.psprite_columns(art.get_data(hudcode.READY_WEAPON))
    row = art.colormap()[0]
    text = "\n".join(hudcode.hud_tail_lines(colours, overlay, row, view_rows=VH, cards=CARDS))
    if mutate is not None:
        text = mutate(text)
    start = hudcode.slot_codes(hud.slot_values(**_B, blue=False, cards=CARDS), CARDS)
    lines = ["stl.startup_and_init_all", "present.init_screen", ";frames", *hudcode.hud_decls(start, CARDS),
             "pcard: hex.vec 1", "pcard_y: hex.vec 1", "pcard_r: hex.vec 1", "hud_ret: hex.vec w/4",
             "hud_tail_leaf:", text, "stl.fret hud_ret",
             "frames:"]
    for f, cards in enumerate(SCRIPT):
        lines.append("present.begin_frame_collines")
        if cards is None:
            for x in range(WIDTH):
                lines += [f"stl.output_char {x}", f"stl.output_char {H}", f"stl.output_char {MENU_COLOUR}",
                          "stl.output_char 0xFF"]
            lines += ["hex.set 1, hud_full, 1", "stl.output_char 0xFF"]
            continue
        for x in range(WIDTH):
            rec, _px = _view_column(f, x)
            lines += [f"stl.output_char {b}" for b in rec]
        codes = hudcode.slot_codes(hud.slot_values(**_vals(cards), cards=CARDS), CARDS)
        lines += [f"hex.set {len(codes)}, hud_v, {sum(c << (4 * i) for i, c in enumerate(codes))}"]
        lines += [f"hex.set 1, {cell}, {int(v)}" for cell, v in zip(("pcard", "pcard_y", "pcard_r"), cards)]
        lines += ["stl.fcall hud_tail_leaf, hud_ret", "stl.output_char 0xFF"]
    lines.append("stl.loop")
    return "\n".join(lines) + "\n", colours, overlay, row


def _expected(colours, overlay, row):
    """the oracle's picture per frame (the device keeps rows nobody writes, and so does this)"""
    screen = [0] * (WIDTH * H)
    frames = []
    for f, cards in enumerate(SCRIPT):
        if cards is None:
            screen = [MENU_COLOUR] * (WIDTH * H)
            frames.append(list(screen))
            continue
        for x in range(WIDTH):
            _rec, px = _view_column(f, x)
            for y in range(VH):
                screen[y * WIDTH + x] = screen[y * WIDTH + x - 1] if px is None else px[y]
        for x, runs in overlay.items():
            for y0, y1, texel in runs:
                for y in range(y0, y1):
                    screen[y * WIDTH + x] = row[texel]
        bar = hud.bar_pixels(colours, **_vals(cards))
        for y in range(hud.BAR_ROWS):
            for x in range(WIDTH):
                screen[(VH + y) * WIDTH + x] = bar[y][x]
        frames.append(list(screen))
    return frames


def _run(tmp_path, name, mutate=None):
    text, colours, overlay, row = _program(mutate)
    src = tmp_path / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()], out, memory_width=W,
                print_time=False)
    frames = []

    class Rec(_Screen):
        def _present(self):
            super()._present()
            frames.append(list(self.pixel_indices))
    screen = Rec()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    return frames, _expected(colours, overlay, row)


def _first_bad(frames, want):
    assert len(frames) == len(want), "presented %d frames, the script has %d" % (len(frames), len(want))
    return next((f for f, (a, b) in enumerate(zip(frames, want)) if a != b), None)


def _slot(name):
    return [n for n, *_r in hud.bar_slots(CARDS)].index(name)


def _icons_differ():
    """the three icons' pixels are three different pictures (a card drawn in another card's colour would show)"""
    art = WadFile.from_path(str(ART))
    colours = hud.bar_colours(bytes(b for rgb in art.playpal(0) for b in rgb))
    return len({colours["card"], colours["ycard"], colours["rcard"], colours["bg"]}) == 4


@needs_art
def test_every_frame_is_the_oracle_picture(tmp_path):
    assert _icons_differ()
    frames, want = _run(tmp_path, "hud_keys")
    bad = _first_bad(frames, want)
    assert bad is None, "frame %d differs from the oracle's screen" % bad


def _mut_red_reads_yellow(t):
    i = _slot("card_r")
    return t.replace("hex.cmp 1, pcard_r, hud_s + %d*dw" % i, "hex.cmp 1, pcard_y, hud_s + %d*dw" % i).replace(
        "hex.if_flags pcard_r, ", "hex.if_flags pcard_y, ").replace(
        "hex.mov 1, hud_s + %d*dw, pcard_r" % i, "hex.mov 1, hud_s + %d*dw, pcard_y" % i)


def _mut_yellow_inverted(t):
    i = _slot("card_y")
    return t.replace("hex.cmp 1, pcard_y, hud_s + %d*dw, hud_d%d, hud_n%d, hud_d%d" % (i, i, i, i),
                     "hex.cmp 1, pcard_y, hud_s + %d*dw, hud_n%d, hud_d%d, hud_n%d" % (i, i, i, i))


def _mut_red_swapped(t):
    i = _slot("card_r")
    return t.replace("hex.if_flags pcard_r, 1<<0, hud_d%d_1, hud_d%d_v0" % (i, i),
                     "hex.if_flags pcard_r, 1<<1, hud_d%d_1, hud_d%d_v0" % (i, i)).replace(
        "hex.if_flags pcard_r, 1<<1, hud_d%d_2, hud_d%d_v1" % (i, i),
        "hex.if_flags pcard_r, 1<<0, hud_d%d_2, hud_d%d_v1" % (i, i))


@needs_art
@pytest.mark.parametrize("name, mutate, frame", [
    ("red_reads_yellow", _mut_red_reads_yellow, 1),
    ("yellow_inverted", _mut_yellow_inverted, 0),
    ("red_swapped", _mut_red_swapped, 0),
])
def test_the_checks_catch_a_broken_key_icon(tmp_path, name, mutate, frame):
    text, *_ = _program()
    assert mutate(text) != text, "the mutant %s changed nothing -- its pattern no longer matches the emitter" % name
    frames, want = _run(tmp_path, name, mutate)
    assert _first_bad(frames, want) == frame
