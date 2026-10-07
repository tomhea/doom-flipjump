"""M7 P5 (doomfj.hurtcode): the red damage palette on the real flipjump engine and the stock screen device --
`pal_lines` / `pal_menu_lines`, the very text the emitter splices, with `palidx` and the PLAYPAL 0..8 data, against
DOOM's ST_doPaletteStuff (red only: berserk and the bonus flash are P6).

A loop reads, per frame, a damagecount (0..100) and a menu flag; a world frame runs pal_lines, a menu frame
pal_menu_lines, and each frame is presented as an empty 0x0B frame. The device records, per frame, how many
set_palette commands arrived and the palette it then holds -- READ FROM THE PROGRAM'S MEMORY at the address the
command named, so the table, the dispatch and the emitted palette bytes are all under test: every frame must show
PLAYPAL[red_palette(dc)] (0 on a menu frame), and a palette is sent only when it changes.

R9: `dc >> 3` for `(dc + 7) >> 3` (the table), a palette sent every frame (the change test gone), a menu frame that
does not force palette 0, and a dispatch that sends the wrong lump (k -> k + 1) must each part.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.ScreenIO import CMD_SET_PALETTE, InMemoryScreen
from flipjump.utils.exceptions import IOReadOnEOF

from doomfj import hurtcode as H
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
SRC = [ROOT / "src" / "fj" / "present.fj", ROOT / "src" / "fj" / "sim.fj"]
ART = ROOT / "assets" / "freedoom1.wad"          # 14 palettes (the map wad holds one: hurtcode.palette_tables_fj)
FRAMES = 160


def _script():
    """[(dc, menu)]: damage spikes and fades (every red palette, runs of equal ones), menu frames between"""
    rnd = random.Random(0xA1)
    out, dc = [], 0
    for f in range(FRAMES):
        if rnd.random() < 0.05:
            dc = min(100, dc + rnd.choice((3, 9, 15, 24, 40, 100)))
        elif dc:
            dc = max(0, dc - rnd.choice((1, 2, 3)))            # a faster fade than DOOM's: every palette in turn
        menu = int(rnd.random() < 0.06 or 70 <= f < 74)
        out.append((dc, menu))
    return out


class _Dev(InMemoryScreen):
    """the stock screen fed stdin; per frame: (set_palette commands since the last frame, the palette held)"""

    def __init__(self, stdin: bytes):
        super().__init__()
        self._inp, self._byte, self._bits = stdin, 0, 0
        self.sent, self.frames = 0, []

    def read_bit(self) -> bool:
        if self._bits == 0:
            if not self._inp:
                raise IOReadOnEOF("EOF")
            self._byte, self._inp, self._bits = self._inp[0], self._inp[1:], 8
        bit = self._byte & 1
        self._byte >>= 1
        self._bits -= 1
        return bool(bit)

    def _execute_command(self, command, payload):
        if command == CMD_SET_PALETTE:
            self.sent += 1
        super()._execute_command(command, payload)

    def _present(self):
        super()._present()
        self.frames.append((self.sent, tuple(self.palette)))
        self.sent = 0


MUTANTS = {
    "dcshr3": None,                                                        # the table, below
    "everyframe": ("hex.cmp 1, pal_new, pal_cur, pl_chg, pl_out, pl_chg\n", ""),
    "menukeeps": ("hex.zero 1, pal_cur\npresent.set_palette playpal0\n", ""),
    "wronglump": ("pl_k3:\npresent.set_palette playpal3\n", "pl_k3:\npresent.set_palette playpal4\n"),
}


def _program(mut=None):
    art = WadFile.from_path(str(ART))
    text = "\n".join(["world_pal:"] + H.pal_lines() + ["stl.fret pal_ret", "menu_pal:"] + H.pal_menu_lines()
                     + ["stl.fret pal_ret"]) + "\n"
    if mut and MUTANTS[mut]:
        old, new = MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    vals = H.palidx_values() if mut != "dcshr3" else [0 if not dc else 1 + min(7, dc >> 3) for dc in range(256)]
    lines = ["stl.startup_and_init_all", "present.init_screen", "present.set_palette playpal0",
             "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
             "hex.input 1, p_dc", "hex.input 1, pmenu",
             "hex.if0 2, pmenu, fw", "stl.fcall menu_pal, pal_ret", ";fr",
             "fw:", "stl.fcall world_pal, pal_ret",
             "fr:", "present.begin_frame_collines", "stl.output_char 0xFF", ";loop",
             "done:", "stl.loop",
             "rmagic: hex.vec 2", "pmenu: hex.vec 2", "pal_ret: hex.vec w/4",
             "p_dc: hex.vec 2", "pal_cur: hex.vec 1, 0", "pal_new: hex.vec 1",
             text,
             generate_dispatch_table_fj("palidx", vals, index_nibbles=2, result_nibbles=1),
             *H.palette_tables_fj(art)]
    return "\n".join(lines) + "\n", art


def _run(tmp_path, name, mut=None):
    text, art = _program(mut)
    src = tmp_path / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()], out, memory_width=W,
                print_time=False)
    script = _script()
    dev = _Dev(b"".join(bytes([1, dc, menu]) for dc, menu in script) + bytes([0]))
    fj.run(out, io_device=dev, print_time=False, print_termination=False)
    want, cur = [], 0
    for f, (dc, menu) in enumerate(script):
        k = 0 if menu else H.red_palette(dc)
        want.append((int(k != cur) + int(f == 0), tuple(art.playpal(k))))     # frame 0: the boot's playpal0 too
        cur = k
    return dev.frames, want


def _first_bad(got, want):
    assert len(got) == len(want), "%d frames presented of %d" % (len(got), len(want))
    return next((f for f, (g, w) in enumerate(zip(got, want)) if g != w), None)


def test_the_script_reaches_every_palette():
    seen = {H.red_palette(dc) for dc, menu in _script() if not menu}
    assert seen == set(range(H.NPALETTES)) - {H.STARTREDPALS}, seen      # damage never shows palette 1 (DOOM's)
    assert any(menu and dc for dc, menu in _script())                    # a menu over a red screen


def test_the_palette_follows_the_damagecount(tmp_path):
    got, want = _run(tmp_path, "pal")
    bad = _first_bad(got, want)
    assert bad is None, "frame %d: got %d sends, want %d" % (bad, got[bad][0], want[bad][0])
    assert sum(g[0] for g in got) < len(got) // 2, "the palette is not sent only on change"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_palette_is_caught(tmp_path, mut):
    got, want = _run(tmp_path, "pal_" + mut, mut)
    bad = _first_bad(got, want)
    assert bad is not None, "the mutant %s went unnoticed" % mut
    print("mutant %s caught at frame %d" % (mut, bad))


# ---- M7 P6 (doomfj.lootcode): berserk and the bonus flash -- `pal_lines(loot=True)` with `palidx`, `bonpal` and
# PLAYPAL 0..12, against combat.palette_index (ST_doPaletteStuff over damagecount, strength and bonuscount).
# The script runs berserk from 1 up past 768 (its red fades 3 -> 2 -> none), bonus flashes fading over it and
# alone, damage spikes over both, and menu frames. R9 (LOOT_MUTANTS): the gold flash gone, the berserk red without
# its fade, the berserk red without the max (it replaces a stronger damage red), gold shown over a red.
LOOT_FRAMES = 1300


def _loot_script():
    """[(dc, strength, bc, menu)]"""
    rnd = random.Random(0xA2)
    out, dc, st, bc = [], 0, 0, 0
    for f in range(LOOT_FRAMES):
        if f == 300:
            st = 1
        elif st:
            st = min(0xFFFF, st + 1)
        if rnd.random() < 0.03:
            dc = min(100, dc + rnd.choice((3, 9, 24, 60)))
        elif dc:
            dc -= 1
        if rnd.random() < 0.04:
            bc = min(255, bc + rnd.choice((6, 12, 40)))
        elif bc:
            bc -= 1
        out.append((dc, st, bc, int(rnd.random() < 0.04)))
    return out


LOOT_MUTANTS = {
    "nogold": ("pl_gold:\nbonpal.lookup pal_new, p_bc\n", "pl_gold:\n"),
    "berserk_nofade": ("pl_bk2:\nhex.set 1, pal_bk, 2\n", "pl_bk2:\nhex.set 1, pal_bk, 3\n"),
    "berserk_nomax": ("hex.cmp 1, pal_new, pal_bk, pl_bset, pl_bz, pl_bz\n", ""),
    "gold_over_red": ("hex.if0 1, pal_new, pl_gold\n;pl_have\n", ";pl_gold\n"),
}


def _loot_run(tmp_path, name, mut=None):
    from types import SimpleNamespace
    from doomfj.combat import palette_index
    art = WadFile.from_path(str(ART))
    text = "\n".join(["world_pal:"] + H.pal_lines(loot=True) + ["stl.fret pal_ret", "menu_pal:"]
                     + H.pal_menu_lines() + ["stl.fret pal_ret"]) + "\n"
    if mut:
        old, new = LOOT_MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    lines = ["stl.startup_and_init_all", "present.init_screen", "present.set_palette playpal0",
             "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
             "hex.input 1, p_dc", "hex.input 2, p_str", "hex.input 1, p_bc", "hex.input 1, pmenu",
             "hex.if0 2, pmenu, fw", "stl.fcall menu_pal, pal_ret", ";fr",
             "fw:", "stl.fcall world_pal, pal_ret",
             "fr:", "present.begin_frame_collines", "stl.output_char 0xFF", ";loop",
             "done:", "stl.loop",
             "rmagic: hex.vec 2", "pmenu: hex.vec 2", "pal_ret: hex.vec w/4",
             "p_dc: hex.vec 2", "p_str: hex.vec 4", "p_bc: hex.vec 2", "pal_cur: hex.vec 1, 0", "pal_new: hex.vec 1",
             "pal_bk: hex.vec 1",
             text,
             generate_dispatch_table_fj("palidx", H.palidx_values(), index_nibbles=2, result_nibbles=1),
             generate_dispatch_table_fj("bonpal", H.bonpal_values(), index_nibbles=2, result_nibbles=1),
             *H.palette_tables_fj(art, n=H.NPALETTES_LOOT)]
    src = tmp_path / (name + ".fj")
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()], out, memory_width=W,
                print_time=False)
    script = _loot_script()
    dev = _Dev(b"".join(bytes([1, dc, st & 0xFF, st >> 8, bc, menu]) for dc, st, bc, menu in script) + bytes([0]))
    fj.run(out, io_device=dev, print_time=False, print_termination=False)
    want, cur = [], 0
    for f, (dc, st, bc, menu) in enumerate(script):
        k = 0 if menu else palette_index(SimpleNamespace(p_damagecount=dc, p_strength=st, p_bonuscount=bc))
        want.append((int(k != cur) + int(f == 0), tuple(art.playpal(k))))
        cur = k
    return dev.frames, want


def test_the_loot_script_reaches_every_palette():
    from types import SimpleNamespace
    from doomfj.combat import palette_index
    s = _loot_script()
    seen = {palette_index(SimpleNamespace(p_damagecount=dc, p_strength=st, p_bonuscount=bc))
            for dc, st, bc, menu in s if not menu}
    # (DOOM's arithmetic never shows palette 1 nor 9: (n + 7) >> 3 >= 1 for any count n >= 1)
    assert seen == set(range(H.NPALETTES_LOOT)) - {H.STARTREDPALS, H.STARTBONUSPALS}, seen
    # berserk red under a stronger damage red, and gold suppressed by a red
    assert any(dc > 20 and 0 < st < 256 for dc, st, bc, m in s) and any(bc and (dc or 0 < st < 768) for dc, st, bc, m in s)


def test_the_loot_palette_follows_the_model(tmp_path):
    got, want = _loot_run(tmp_path, "lpal")
    bad = _first_bad(got, want)
    assert bad is None, "frame %d: got %d sends, want %d" % (bad, got[bad][0], want[bad][0])


@pytest.mark.parametrize("mut", sorted(LOOT_MUTANTS))
def test_control_a_broken_loot_palette_is_caught(tmp_path, mut):
    got, want = _loot_run(tmp_path, "lpal_" + mut, mut)
    assert _first_bad(got, want) is not None, "the mutant %s went unnoticed" % mut
