"""M7 P4.0 -- the game screen's weapon overlay and status bar, emitted as REAL fj (`doomfj.hudcode`) and presented by
the REAL device, against the oracle's picture (`doomfj.hud`). docs/gp-combat.md section 2.

Each frame of the program: a synthetic VIEW (84 rows of column records, some of them PARTIAL DITTOS, as the game
tier's renderer writes them), the frame's bar values set into the cells, then the game tier's tail -- the weapon
records and the bar's changed columns -- and the frame's 0xFF. A "menu" frame paints all 100 rows and sets
`hud_full`, as the menu producer does. Every presented frame must equal the oracle's composition of the same view and
values. The device keeps rows nobody writes, so a slot the fj forgets to redraw shows its OLD digit: the script
changes every slot at least once and covers the redraw after a menu.

R9: three mutants of the real emitted text, each caught at the frame stated in advance --
  * slot 0's change test inverted (redrawn only when it did NOT change): its boot draw is skipped -> frame 0
  * the full redraw leaves the shadows alone: after the menu the slots are not redrawn  -> frame 6, the first world
    frame after the menu (frame 5 is the menu itself)
  * the bar's KEEP stops one row short: the bar's first run paints the view's last row  -> frame 0
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
VH, H, WIDTH = GAME_CFG.VIEW_H, GAME_CFG.H, GAME_CFG.W
MENU_COLOUR = 77

# the bar values per frame: None = a MENU frame (all 100 rows, sets hud_full)
SCRIPT = [
    dict(hudcode.LEVEL_START),                                                             # 0: boot (hud_full)
    dict(hudcode.LEVEL_START),                                                             # 1: nothing changed
    dict(ammo=8, health=57, armor=0, owned=(True, True, False), blue=True),               # 2: every kind changes
    dict(ammo=0, health=100, armor=200, owned=(True, True, True), blue=True),             # 3
    dict(ammo=None, health=5, armor=7, owned=(True, False, False), blue=False),           # 4: no ammo, card gone
    None,                                                                                  # 5: a menu frame
    dict(ammo=None, health=5, armor=7, owned=(True, False, False), blue=False),           # 6: the whole bar again
    dict(ammo=123, health=0, armor=99, owned=(False, False, True), blue=True),            # 7
]


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


def _program(mutate=None):
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    colours = hud.bar_colours(bytes(b for rgb in art.playpal(0) for b in rgb))
    overlay = hud.psprite_columns(art.get_data(hudcode.READY_WEAPON))
    row = art.colormap()[0]
    tail = hudcode.hud_tail_lines(colours, overlay, row, view_rows=VH)
    text = "\n".join(tail)
    if mutate is not None:
        text = mutate(text)
    start = hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))
    lines = ["stl.startup_and_init_all", "present.init_screen", ";frames", *hudcode.hud_decls(start),
             "pcard: hex.vec 1", "hud_ret: hex.vec w/4",
             "hud_tail_leaf:", text, "stl.fret hud_ret",
             "frames:"]
    for f, vals in enumerate(SCRIPT):
        lines.append("present.begin_frame_collines")
        if vals is None:
            for x in range(WIDTH):
                lines += [f"stl.output_char {x}", f"stl.output_char {H}", f"stl.output_char {MENU_COLOUR}",
                          "stl.output_char 0xFF"]
            lines += ["hex.set 1, hud_full, 1", "stl.output_char 0xFF"]
            continue
        for x in range(WIDTH):
            rec, _px = _view_column(f, x)
            lines += [f"stl.output_char {b}" for b in rec]
        codes = hudcode.slot_codes(hud.slot_values(**vals))
        lines += [f"hex.set {len(codes)}, hud_v, {sum(c << (4 * i) for i, c in enumerate(codes))}",
                  f"hex.set 1, pcard, {int(vals['blue'])}",
                  "stl.fcall hud_tail_leaf, hud_ret", "stl.output_char 0xFF"]
    lines.append("stl.loop")
    return "\n".join(lines) + "\n", colours, overlay, row


def _expected(colours, overlay, row):
    """the oracle's picture per frame (the device keeps rows nobody writes, and so does this)"""
    screen = [0] * (WIDTH * H)
    frames = []
    for f, vals in enumerate(SCRIPT):
        if vals is None:
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
        bar = hud.bar_pixels(colours, **vals)
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


def test_every_frame_is_the_oracle_picture(tmp_path):
    frames, want = _run(tmp_path, "hud")
    bad = _first_bad(frames, want)
    assert bad is None, "frame %d differs from the oracle's screen" % bad


@pytest.mark.parametrize("name, mutate, frame", [
    ("inverted", lambda t: t.replace("hex.cmp 1, hud_v + 0*dw, hud_s + 0*dw, hud_d0, hud_n0, hud_d0",
                                     "hex.cmp 1, hud_v + 0*dw, hud_s + 0*dw, hud_n0, hud_d0, hud_n0"), 0),
    ("noinval", lambda t: t.replace("hex.set %d, hud_s, " % len(hud.bar_slots()), "hex.xor_by %d, hud_s, 0 // " %
                                    len(hud.bar_slots()), 1), 6),
    ("keepshort", lambda t: t.replace("stl.output_char 0xFC\nstl.output_char %d\n" % VH,
                                      "stl.output_char 0xFC\nstl.output_char %d\n" % (VH - 1)), 0),
])
def test_the_checks_catch_a_broken_tail(tmp_path, name, mutate, frame):
    text, *_ = _program()
    assert mutate(text) != text, "the mutant %s changed nothing -- its pattern no longer matches the emitter" % name
    frames, want = _run(tmp_path, name, mutate)
    assert _first_bad(frames, want) == frame
