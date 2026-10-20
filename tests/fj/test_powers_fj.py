"""M8 C6 (doomfj.powers / doomfj.powercode): THE TIMED POWERS on the real flipjump engine -- the very text the emitter
splices, record by record or frame by frame against the model's own code (a HEAVY file: its two monster-tic
harnesses assemble E1M3's 152 slots -- run it through scripts/heavy.py):

  * THE GIVES (`lootcode.give_lines`): 2024 partial invisibility, 2025 the radiation suit (P_GivePower: the counter
    set to 2100, always taken; the invisibility a COUNTITEM, the suit not) and 2046 the box of rockets (P_GiveAmmo 5
    rockets, the cap, the launcher's switch from the fist) against `combat._touch`;
  * THE TIC AND THE PALETTE (`powercode.countdown_lines`, `hurtcode.pal_lines(loot=True, suit=True)`): a frame script
    of damage, berserk, bonus flashes and suit pickups -- the countdown, then the pickups, then the palette -- against
    `combat._power_tic` and `combat.palette_index` (RADIATIONPAL 13 while `p_rad > 128 || p_rad & 8`, under the red
    and the gold);
  * THE SUIT AT A HURT (`powercode.suit_lines`, nukage's): against `combat._suit_stops` -- 5 / 7 stopped, a 20-damage
    floor leaking at P_Random() < 5 (one rng_pl draw);
  * THE SHADOW AIM: `mm_shj` (A_FaceTarget at an invisible player: two mon_rng draws, md_jit = 2 * (a - b)) against
    `world._a_face_target`, and `powercode.missile_lines` (P_SpawnMissile's turn) against
    `combat._shadow_missile_turn`;
  * THE SHADOW WEAPON (`hudcode.hud_tail_lines(shadow=)`): every weapon and flash frame, plain and shadow by `p_inv`,
    presented by the real device against the oracle's `hud.GameScreen.frame(shadow=)` composition.

The World is E1M3's (it holds the invisibility and two kinds of hurting floor) with a radiation suit added next to the
invisibility (`_SuitWad`), so ONE World has both power fields. R9: every part carries mutants of the real emitted text,
each of which must part from the model.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.ScreenIO import CMD_SET_PALETTE, InMemoryScreen
from flipjump.utils.exceptions import IOReadOnEOF

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import hurtcode as H
from doomfj import lootcode as L
from doomfj import powercode as PC
from doomfj import powers as P
from doomfj import weaponcode as WC
from doomfj.config import GAME_CFG, Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.wad import Thing, WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FULL = ROOT / "assets" / "freedoom1.wad"
needs_wad = pytest.mark.skipif(not FULL.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")


class _SuitWad:
    """freedoom1.wad with a radiation suit on E1M3, beside its partial invisibility (E1M3 holds no suit)"""

    def __init__(self, wad):
        self._w = wad

    def __getattr__(self, name):
        return getattr(self._w, name)

    def things(self, mapname):
        out = list(self._w.things(mapname))
        if mapname == "E1M3":
            inv = next(t for t in out if t.type == P.INVIS_TYPE)
            out.append(Thing(inv.x, inv.y, 0, P.SUIT_TYPE, 7))
        return out


_CACHE = {}


def _world(monsters="final", player="final"):
    key = (monsters, player)
    if key not in _CACHE:
        _CACHE[key] = World(_SuitWad(WadFile.from_path(str(FULL))), "E1M3", skill=gd.SK_HARD, monsters=monsters,
                            player=player)
    w = _CACHE[key]
    w.reset(gd.SK_HARD)
    return w


def _mutate(text, muts, mut):
    if mut:
        pat, new = muts[mut]
        text, n = re.subn(pat, new, text)
        assert n == 1, "the mutant %s matches the emitted text %d times, not once" % (mut, n)
    return text


def _run_text(tmp_path, name, prog, want: bytes) -> bool:
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


# ==== THE GIVES ========================================================================================================
GIVE_KINDS = (P.INVIS_TYPE, P.SUIT_TYPE, 2046, 2010)
GCELLS = (("p_inv", 3), ("p_rad", 3), ("am_misl", 3), ("wp_pend", 1), ("gv_ok", 1), ("st_item", 2))
GIVE_MUTANTS = {
    "invis_tics": (r"(hex\.set 3, p_inv, )2100", r"\g<1>2099"),
    "suit_writes_inv": (r"(give_2025:\n    hex\.set 3, )p_rad", r"\1p_inv"),
    "invis_not_counted": (r"(  give_2024_ok:\n)    hex\.inc 2, st_item\n", r"\1"),
    "suit_counted": (r"(  give_2025_ok:\n)", r"\1    hex.inc 2, st_item\n"),
    "brok_one_rocket": (r"(give_2046:\n    hex\.set 3, ga_n, )5", r"\g<1>1"),
}


def _owned(r, x):
    return int(x in (gd.WP_FIST, gd.WP_PISTOL) or (x == gd.WP_MISSILE and r["launcher"]))


def _give_records():
    rnd = random.Random(0xC6)
    out = []
    for r in range(240):
        kind = GIVE_KINDS[r % len(GIVE_KINDS)] if r < 16 else rnd.choice(GIVE_KINDS)
        bp = rnd.choice((0, 1))
        cap = gd.MAXAMMO[gd.AM_MISL] * (2 if bp else 1)
        out.append(dict(kind=kind, p_backpack=bp, misl=rnd.choice((0, 0, 1, cap - 1, cap - 5, cap, rnd.randint(0, cap))),
                        launcher=rnd.choice((0, 1)), ready=rnd.choice((gd.WP_FIST, gd.WP_PISTOL)),
                        inv=rnd.choice((0, 1, 2100, rnd.randint(0, 2100))), rad=rnd.choice((0, 5, 2100)),
                        items=rnd.choice((0, 7, 41))))
    return out


def _give_expected(w, recs):
    from doomfj.statcode import counts_item
    lines = []
    for r in recs:
        ws = w.ws
        ws.p_backpack, ws.p_ready, ws.p_pending = r["p_backpack"], r["ready"], gd.WP_NOCHANGE
        ws.p_ammo[gd.AM_MISL] = r["misl"]
        for x in range(gd.NUMWEAPONS):
            ws.p_owned[x] = _owned(r, x)
        ws.p_invis, ws.p_ironfeet = r["inv"], r["rad"]
        taken = w._touch(r["kind"], False, 0, 0)
        items = r["items"] + int(bool(taken) and counts_item(r["kind"]))
        vals = (ws.p_invis, ws.p_ironfeet, ws.p_ammo[gd.AM_MISL], ws.p_pending, int(taken), items)
        lines.append("".join("%0*x" % (n, v) for (_c, n), v in zip(GCELLS, vals)))
    return ("\n".join(lines) + "\n").encode()


def _give_program(w, recs, mut=None):
    text = []
    for k in GIVE_KINDS:
        text += L.give_lines(k, False, stats=True)
    for a in range(gd.NUMAMMO):
        text += L.give_ammo_lines(a)
    text = _mutate("\n".join(text) + "\n", GIVE_MUTANTS, mut)
    body = ["stl.startup_and_init_all"]
    for r in recs:
        own = sum(_owned(r, x) << (4 * WC.OWN[x]) for x in WC.WEAPONS)
        body += ["hex.set 1, p_bp, %d" % r["p_backpack"], "hex.set 1, wp_rdy, %d" % r["ready"],
                 "hex.set 1, wp_pend, %d" % gd.WP_NOCHANGE, "hex.set 3, am_misl, %d" % r["misl"],
                 "hex.set %d, wp_own, %d" % (len(WC.WEAPONS), own),
                 "hex.set 3, p_inv, %d" % r["inv"], "hex.set 3, p_rad, %d" % r["rad"],
                 "hex.set 1, gv_ok, 7", "hex.set 2, st_item, %d" % r["items"],
                 "stl.fcall give_%d, gv_ret" % r["kind"]]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in GCELLS] + ["stl.output 10"]
    body += ["stl.loop"]
    decls = (L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(WC.level_start(w.mw, "E1M3"), WC.weapon_states(), WC.overlay_frames())
             + ["st_item: hex.vec 2"] + PC.decls(w.powers))
    tables = [generate_dispatch_table_fj("amcap", L.amcap_values(), index_nibbles=2, result_nibbles=3)]
    return "\n".join(body + decls) + "\n" + text + "\n".join(tables) + "\n"


def _give_run(tmp_path, name, mut=None):
    recs = _give_records()
    want = _give_expected(_world(), recs)
    return _run_text(tmp_path, name, _give_program(_world(), recs, mut), want)


@needs_wad
def test_the_world_holds_both_powers_and_the_gives_are_taken():
    w = _world()
    assert w.powers == (P.INVIS_TYPE, P.SUIT_TYPE)
    assert {f.name for f in w.schema} >= {"p_invis", "p_ironfeet"}
    for k in (P.INVIS_TYPE, P.SUIT_TYPE):
        setattr(w.ws, P.FIELD[k], 17)
        assert w._touch(k, False, 0, 0) and getattr(w.ws, P.FIELD[k]) == 2100    # re-taken: the counter restarts
    outcomes = {(r["kind"], r["misl"] == gd.MAXAMMO[gd.AM_MISL] * (2 if r["p_backpack"] else 1))
                for r in _give_records()}
    assert {(2046, True), (2046, False), (2010, True), (2010, False)} <= outcomes      # refused at the cap, and not


@needs_wad
def test_the_power_gives_follow_the_model(tmp_path):
    assert _give_run(tmp_path, "give_pw"), "the fj gives parted from combat._touch"


@needs_wad
@pytest.mark.parametrize("mut", sorted(GIVE_MUTANTS))
def test_control_a_broken_give_is_caught(tmp_path, mut):
    assert not _give_run(tmp_path, "give_pw_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ==== THE TIC AND THE PALETTE ==========================================================================================
TIC_FRAMES = 2600
TIC_MUTANTS = {
    "no_radiation": (r"pl_rad_on:\nhex\.set 1, pal_new, 13\n", "pl_rad_on:\n"),
    "radiation_over_gold": (r"hex\.if1 1, pal_new, pl_rad_end\n", ""),
    "no_flicker": (r"(hex\.if_flags p_rad, )0xFF00", r"\g<1>0x0000"),
    "blink_at_128": (r"hex\.cmp 3, p_rad, pw_c128, pl_rad_end, pl_rad_end, pl_rad_on",
                     "hex.cmp 3, p_rad, pw_c128, pl_rad_end, pl_rad_on, pl_rad_on"),
    "suit_never_counts": (r"hex\.dec 3, p_rad\n", ""),
}


class _PalDev(InMemoryScreen):
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


def _tic_script():
    """[(dc, strength, bc, take_suit, take_invis, menu)] -- suits taken at fixed frames (the full 2100 and its blinking
    end, one re-taken mid-way), damage and gold flashes over it"""
    rnd = random.Random(0xC61)
    out, dc, st, bc = [], 0, 0, 0
    takes = {10: 1, 400: 1}
    for f in range(TIC_FRAMES):
        if f == 1500:
            st = 1
        elif st:
            st = min(0xFFFF, st + 1)
        if rnd.random() < 0.02:
            dc = min(100, dc + rnd.choice((3, 9, 24)))
        elif dc:
            dc -= 1
        if rnd.random() < 0.02:
            bc = min(255, bc + rnd.choice((6, 12)))
        elif bc:
            bc -= 1
        out.append((dc, st, bc, takes.get(f, 0), int(f in (30, 2000)), int(rnd.random() < 0.02)))
    return out


def _tic_expected(art):
    from doomfj.combat import palette_index
    w = _world()
    want, cur = [], 0
    for f, (dc, st, bc, ts, ti, menu) in enumerate(_tic_script()):
        w._power_tic()
        if ts:
            w.ws.p_ironfeet = P.TICS[P.SUIT_TYPE]
        if ti:
            w.ws.p_invis = P.TICS[P.INVIS_TYPE]
        w.ws.p_damagecount, w.ws.p_strength, w.ws.p_bonuscount = dc, st, bc
        k = 0 if menu else palette_index(w.ws)
        want.append((int(k != cur) + int(f == 0), tuple(art.playpal(k))))
        cur = k
    return want


def _tic_run(tmp_path, name, mut=None):
    art = WadFile.from_path(str(FULL))
    text = "\n".join(["tic_leaf:"] + PC.countdown_lines((P.INVIS_TYPE, P.SUIT_TYPE)) + ["stl.fret pal_ret",
                      "world_pal:"] + H.pal_lines(loot=True, suit=True) + ["stl.fret pal_ret", "menu_pal:"]
                     + H.pal_menu_lines() + ["stl.fret pal_ret"]) + "\n"
    text = _mutate(text, TIC_MUTANTS, mut)
    lines = ["stl.startup_and_init_all", "present.init_screen", "present.set_palette playpal0",
             "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
             "hex.input 1, p_dc", "hex.input 2, p_str", "hex.input 1, p_bc", "hex.input 1, rflags",
             "stl.fcall tic_leaf, pal_ret",
             "hex.if_flags rflags, 0xAAAA, ts_n, ts_y", "ts_y:", "hex.set 3, p_rad, 2100", "ts_n:",
             "hex.if_flags rflags, 0xCCCC, ti_n, ti_y", "ti_y:", "hex.set 3, p_inv, 2100", "ti_n:",
             "hex.if_flags rflags, 0xF0F0, fw, fm",
             "fm:", "stl.fcall menu_pal, pal_ret", ";fr",
             "fw:", "stl.fcall world_pal, pal_ret",
             "fr:", "present.begin_frame_collines", "stl.output_char 0xFF", ";loop",
             "done:", "stl.loop",
             "rmagic: hex.vec 2", "rflags: hex.vec 2", "pal_ret: hex.vec w/4",
             "p_dc: hex.vec 2", "p_str: hex.vec 4", "p_bc: hex.vec 2", "pal_cur: hex.vec 1, 0", "pal_new: hex.vec 1",
             "pal_bk: hex.vec 1", *PC.decls((P.INVIS_TYPE, P.SUIT_TYPE)),
             text,
             generate_dispatch_table_fj("palidx", H.palidx_values(), index_nibbles=2, result_nibbles=1),
             generate_dispatch_table_fj("bonpal", H.bonpal_values(), index_nibbles=2, result_nibbles=1),
             *H.palette_tables_fj(art, n=H.NPALETTES_SUIT)]
    src = tmp_path / (name + ".fj")
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), (FJ / "present.fj").resolve(), (FJ / "sim.fj").resolve(), src.resolve()], out,
                memory_width=W, print_time=False)
    script = _tic_script()
    dev = _PalDev(b"".join(bytes([1, dc, st & 0xFF, st >> 8, bc, ts | ti << 1 | menu << 2])
                           for dc, st, bc, ts, ti, menu in script) + bytes([0]))
    fj.run(out, io_device=dev, print_time=False, print_termination=False)
    return dev.frames, _tic_expected(art)


def _first_bad(got, want):
    assert len(got) == len(want), "%d frames presented of %d" % (len(got), len(want))
    return next((f for f, (g, w) in enumerate(zip(got, want)) if g != w), None)


@needs_wad
def test_the_tic_script_shows_the_radiation_palette_and_its_flicker():
    from doomfj.combat import palette_index
    w, seen = _world(), []
    script = _tic_script()
    for dc, st, bc, ts, ti, menu in script:
        w._power_tic()
        if ts:
            w.ws.p_ironfeet = 2100
        w.ws.p_damagecount, w.ws.p_strength, w.ws.p_bonuscount = dc, st, bc
        seen.append((palette_index(w.ws), w.ws.p_ironfeet))
    assert any(k == P.RADIATIONPAL for k, _r in seen)
    assert any(k == 0 and 0 < r <= P.BLINK_TICS for k, r in seen)                    # the flicker's dark tics
    assert any(k == P.RADIATIONPAL and 0 < r <= P.BLINK_TICS for k, r in seen)       # ... and its lit ones
    assert any(k in range(1, 13) and r > P.BLINK_TICS for k, r in seen)              # a red / gold over the suit
    assert seen[-1][1] == 0 and any(r == P.BLINK_TICS + 1 for _k, r in seen)


@needs_wad
def test_the_tic_and_palette_follow_the_model(tmp_path):
    got, want = _tic_run(tmp_path, "pwtic")
    bad = _first_bad(got, want)
    assert bad is None, "frame %d parts from combat.palette_index / _power_tic" % bad


@needs_wad
@pytest.mark.parametrize("mut", sorted(TIC_MUTANTS))
def test_control_a_broken_tic_or_palette_is_caught(tmp_path, mut):
    got, want = _tic_run(tmp_path, "pwtic_" + mut, mut)
    assert _first_bad(got, want) is not None, "the mutant %s went unnoticed" % mut


# ==== THE SUIT AT A HURT ===============================================================================================
SUIT_MUTANTS = {
    "leaks_everywhere": (r"hex\.cmp 2, nk_dmg, pw_lk, sx_out, nk_suit_r, sx_out",
                         "hex.cmp 2, nk_dmg, pw_lk, nk_suit_r, nk_suit_r, nk_suit_r"),
    "no_draw": (r"hex\.inc 2, rng_pl\n", ""),
    "leak_inverted": (r"hex\.if0 1, pw_lk, sx_out", "hex.if1 1, pw_lk, sx_out"),
    "suit_ignored": (r"hex\.if0 3, p_rad, sx_hurt", ";sx_hurt"),
}


def _suit_records():
    rnd = random.Random(0xC62)
    return [(rnd.choice((0, 1, 2100)), rnd.choice((5, 10, 20, 20)), rnd.randint(0, 255)) for _ in range(500)]


def _suit_run(tmp_path, name, mut=None):
    w = _world()
    lines_want = []
    for rad, dmg, st in _suit_records():
        w.ws.p_ironfeet, w.ws.rng_player = rad, st
        hurt = not w._suit_stops(dmg)
        lines_want.append("%x%02x" % (int(hurt), w.ws.rng_player))
    text = _mutate("\n".join(["suit_leaf:", "hex.zero 1, sx_h"] + PC.suit_lines("sx_hurt", "sx_out")
                             + ["sx_hurt:", "hex.set 1, sx_h, 1", "sx_out:", "stl.fret sx_ret"]) + "\n",
                   SUIT_MUTANTS, mut)
    body = ["stl.startup_and_init_all"]
    for rad, dmg, st in _suit_records():
        body += ["hex.set 3, p_rad, %d" % rad, "hex.set 2, nk_dmg, %d" % dmg, "hex.set 2, rng_pl, %d" % st,
                 "stl.fcall suit_leaf, sx_ret", "hex.print_as_digit 1, sx_h, 0", "hex.print_as_digit 2, rng_pl, 0",
                 "stl.output 10"]
    body += ["stl.loop", "sx_h: hex.vec 1", "sx_ret: hex.vec w/4", "nk_dmg: hex.vec 2", "rng_pl: hex.vec 2",
             *PC.decls((P.SUIT_TYPE,)), *PC.tables_fj((P.SUIT_TYPE,))]
    return _run_text(tmp_path, name, "\n".join(body) + "\n" + text, ("\n".join(lines_want) + "\n").encode())


@needs_wad
def test_the_suit_records_leak_and_hold():
    w, out = _world(), set()
    for rad, dmg, st in _suit_records():
        w.ws.p_ironfeet, w.ws.rng_player = rad, st
        out.add((bool(rad), dmg, not w._suit_stops(dmg)))
    assert out >= {(False, 5, True), (True, 5, False), (True, 10, False), (True, 20, True), (True, 20, False)}, out


@needs_wad
def test_the_suit_follows_the_model(tmp_path):
    assert _suit_run(tmp_path, "suit"), "the fj suit parted from combat._suit_stops"


@needs_wad
@pytest.mark.parametrize("mut", sorted(SUIT_MUTANTS))
def test_control_a_broken_suit_is_caught(tmp_path, mut):
    assert not _suit_run(tmp_path, "suit_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ==== THE SHADOW AIM ===================================================================================================
AIM_MUTANTS = {
    "face_ignores_invis": (r"    hex\.if0 3, p_inv, shj_out\n", ""),
    "face_one_draw": (r"(shj\.lookup md_jit, mm_rng\n)    hex\.inc 2, mm_rng\n", r"\1"),
    "missile_low_nibble": (r"hex\.add 3, pw_ang \+ 5\*dw, pw_shm", "hex.add 3, pw_ang + 4*dw, pw_shm"),
    "missile_ignores_target": (r"    hex\.if0 1, mt_pl, pj_shn\n", ""),
}


def _aim_records():
    rnd = random.Random(0xC63)
    return [(rnd.choice((0, 1, 1)), rnd.choice((0, 1, 2100, 77)), rnd.randint(0, 255), rnd.getrandbits(32))
            for _ in range(400)]


def _aim_run(tmp_path, name, mut=None):
    w = _world()
    m = 0
    want = []
    for pl, inv, st, ang in _aim_records():
        w.ws.mon_target[m] = 1 if pl else 2 + 1                        # the player, or monster slot 1
        w.ws.p_invis = inv
        w.ws.mon_rng[m] = st
        jit = w._a_face_target(m)
        st1 = w.ws.mon_rng[m]
        an = w._shadow_missile_turn(m, ang)
        want.append("%04x%02x%08x%02x" % (jit & 0xFFFF, st1, an, w.ws.mon_rng[m]))
    text = _mutate("\n".join(PC.shj_leaf_lines() + ["pj_leaf:"] + PC.missile_lines() + ["    stl.fret pj_ret"]) + "\n",
                   AIM_MUTANTS, mut)
    body = ["stl.startup_and_init_all"]
    for pl, inv, st, ang in _aim_records():
        body += ["hex.set 1, mt_pl, %d" % pl, "hex.set 3, p_inv, %d" % inv, "hex.set 2, mm_rng, %d" % st,
                 "hex.set 8, pw_ang, %d" % ang,
                 "stl.fcall mm_shj, mm_shjret", "hex.print_as_digit 4, md_jit, 0", "hex.print_as_digit 2, mm_rng, 0",
                 "stl.fcall pj_leaf, pj_ret", "hex.print_as_digit 8, pw_ang, 0", "hex.print_as_digit 2, mm_rng, 0",
                 "stl.output 10"]
    body += ["stl.loop", "mt_pl: hex.vec 1", "mm_rng: hex.vec 2", "pw_ang: hex.vec 8", "pj_ret: hex.vec w/4",
             *PC.decls((P.INVIS_TYPE,)), *PC.tables_fj((P.INVIS_TYPE,))]
    return _run_text(tmp_path, name, "\n".join(body) + "\n" + text, ("\n".join(want) + "\n").encode())


@needs_wad
def test_the_aim_records_turn_and_not():
    w, seen = _world(), set()
    for pl, inv, st, ang in _aim_records():
        w.ws.mon_target[0], w.ws.p_invis, w.ws.mon_rng[0] = (1 if pl else 3), inv, st
        jit = w._a_face_target(0)
        seen.add((pl, bool(inv), jit != 0, w._shadow_missile_turn(0, ang) != ang))
    assert {(1, True, True, True), (1, False, False, False), (0, True, False, False)} <= seen, seen


@needs_wad
def test_the_shadow_aim_follows_the_model(tmp_path):
    assert _aim_run(tmp_path, "aim"), "the fj shadow turns parted from the model's"


@needs_wad
@pytest.mark.parametrize("mut", sorted(AIM_MUTANTS))
def test_control_a_broken_shadow_aim_is_caught(tmp_path, mut):
    assert not _aim_run(tmp_path, "aim_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ==== THE SHADOW WEAPON ================================================================================================
VH, HH, WIDTH = GAME_CFG.VIEW_H, GAME_CFG.H, GAME_CFG.W
# (wp_frm, fl_frm, p_inv) per frame: weapon frames plain and shadow, flashes over both, the blink's edges
PSP = [(0, 0, 0), (0, 0, 2100), (1, 1, 2100), (1, 1, 0), (4, 0, 129), (4, 0, 128), (5, 2, 8), (5, 3, 7),
       (7, 0, 24), (13, 0, 2100), (2, 1, 1), (15, 0, 2100), (16, 4, 2100), (16, 5, 0), (17, 8, 300), (18, 9, 2100),
       (0, 0, 15), (0, 0, 16)]
SHADOW_MUTANTS = {
    "always_shadow": (r"hex\.if_flags p_inv, 0xFF00, hw_shd_g, hsd_on", ";hsd_on"),
    "never_shadow": (r"hex\.if_flags p_inv, 0xFF00, hw_shd_g, hsd_on", ";hsd_off"),
}


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


def _shadow_run(tmp_path, name, mut=None):
    art = WadFile.from_path(str(FULL))
    colours = hud.bar_colours(bytes(b for rgb in art.playpal(0) for b in rgb))
    cols = lambda lump: hud.psprite_columns(art.get_data(lump))      # noqa: E731
    weapons, flashes = [cols(x) for x in WC.overlay_frames()], [cols(x) for x in WC.flash_frames()]
    row = art.colormap()[0]
    srow = hud.shadow_row(art.colormap(), row)
    shd = ([hud.shadow_columns(o) for o in weapons], [hud.shadow_columns(o) for o in flashes], srow)
    text = _mutate("\n".join(hudcode.hud_tail_lines(colours, (weapons, flashes), row, view_rows=VH, shadow=shd)),
                   SHADOW_MUTANTS, mut)
    start = hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))
    lines = ["stl.startup_and_init_all", "present.init_screen", ";frames", *hudcode.hud_decls(start),
             "pcard: hex.vec 1", "hud_ret: hex.vec w/4", "wp_frm: hex.vec 2", "fl_frm: hex.vec 1",
             *PC.decls((P.INVIS_TYPE,)),
             "hud_tail_leaf:", text, "stl.fret hud_ret", "frames:"]
    for f, (wf, ff, inv) in enumerate(PSP):
        lines.append("present.begin_frame_collines")
        for x in range(WIDTH):
            rec, _px = _view_column(f, x)
            lines += [f"stl.output_char {b}" for b in rec]
        lines += [f"hex.set 2, wp_frm, {wf}", f"hex.set 1, fl_frm, {ff}", f"hex.set 3, p_inv, {inv}",
                  "stl.fcall hud_tail_leaf, hud_ret", "stl.output_char 0xFF"]
    lines.append("stl.loop")
    src = tmp_path / (name + ".fj")
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), (FJ / "present.fj").resolve(), src.resolve()], out, memory_width=W,
                print_time=False)
    frames = []

    class Rec(_Screen):
        def _present(self):
            super()._present()
            frames.append(list(self.pixel_indices))
    fj.run(out, io_device=Rec(), print_time=False, print_termination=False)
    # the oracle: the view, then GameScreen.frame's own psprite composition (with the tables its __init__ makes)
    want = []
    names_w, names_f = WC.overlay_frames(), WC.flash_frames()
    gs = hud.GameScreen.__new__(hud.GameScreen)
    gs.overlays = dict(zip(names_w, weapons)) | dict(zip(names_f, flashes))
    gs.shadows = {k: hud.shadow_columns(v) for k, v in gs.overlays.items()}
    gs.row, gs.shadow_row = row, srow
    gs.cfg, gs.colours, gs.level_start = GAME_CFG, colours, dict(hudcode.LEVEL_START)
    for f, (wf, ff, inv) in enumerate(PSP):
        view = bytes(_view_column(f, x)[1][y] for y in range(VH) for x in range(WIDTH)) + bytes(WIDTH * (HH - VH))
        pic = gs.frame(view, weapon=names_w[wf], flash=names_f[ff - 1] if ff else None, shadow=P.blinking(inv))
        want.append(list(pic))
    return frames, want


@needs_wad
def test_the_shadow_frames_differ_from_the_plain_ones():
    art = WadFile.from_path(str(FULL))
    plain = hud.psprite_columns(art.get_data(WC.overlay_frames()[0]))
    sh = hud.shadow_columns(plain)
    n_plain = sum(y1 - y0 for runs in plain.values() for y0, y1, _t in runs)
    n_sh = sum(y1 - y0 for runs in sh.values() for y0, y1, _t in runs)
    assert 0.4 * n_plain < n_sh < 0.7 * n_plain, (n_plain, n_sh)        # FUZZ_SIGNS' 28 of 50
    assert {P.blinking(i) for _w, _f, i in PSP} == {True, False}


@needs_wad
def test_the_shadow_weapon_is_the_oracle_picture(tmp_path):
    frames, want = _shadow_run(tmp_path, "shd")
    assert len(frames) == len(want)
    bad = next((f for f, (a, b) in enumerate(zip(frames, want)) if a != b), None)
    assert bad is None, "frame %d differs: %s" % (bad, PSP[bad])


@needs_wad
@pytest.mark.parametrize("mut", sorted(SHADOW_MUTANTS))
def test_control_a_broken_shadow_weapon_is_caught(tmp_path, mut):
    frames, want = _shadow_run(tmp_path, "shd_" + mut, mut)
    assert any(a != b for a, b in zip(frames, want)), "the mutant %s went unnoticed" % mut


# ==== THE SHADOW TURN IN THE ATTACK (md_attack's fight emission) =======================================================
# tests/fj/test_monster_hitscan_fj.py's harness -- the attacker, its target, the crowd in the line of fire, the
# barrels, the stubs -- on E1M3's World with `attack_leaf_lines(shadow=True)` and mm_shj, each record poking the
# player's invisibility (`p_inv`). The model: `_monster_attack` (A_FaceTarget's draws, every bullet's spread + the
# turn), with the same recorders.
HS_MUTANTS = {
    "spread_ignores_turn": ("    hex.add 4, md_sp, md_jit\n", ""),
    "attack_face_no_draw": ("    stl.fcall mm_octant, mm_ocret\n    stl.fcall mm_shj, mm_shjret\n    hex.mov 1, md_fa",
                            "    stl.fcall mm_octant, mm_ocret\n    hex.mov 1, md_fa"),
}


def _hs_shadow(tmp_path, name, mut, monkeypatch):
    import tests.fj.test_monster_hitscan_fj as HS
    from doomfj import monsterdecide as MD
    from doomfj import monstercode as MC
    w = World(_SuitWad(WadFile.from_path(str(FULL))), "E1M3", skill=gd.SK_HARD, monsters="final", player="final",
              sight_rule="seen")
    orig_attack, orig_ctx, orig_tab, orig_apply = (MD.attack_leaf_lines, MD.context_decls, MD.fight_tables_fj,
                                                   HS._apply)
    monkeypatch.setattr(MD, "attack_leaf_lines", lambda **kw: orig_attack(**kw, shadow=True) + PC.shj_leaf_lines())
    monkeypatch.setattr(MD, "context_decls", lambda: orig_ctx() + PC.decls((P.INVIS_TYPE,)))
    monkeypatch.setattr(MD, "fight_tables_fj", lambda sine, *rest: orig_tab(sine, *rest) + PC.tables_fj((P.INVIS_TYPE,)))

    def apply(ww, rec, log):
        ww.ws.p_invis = rec["inv"]
        return orig_apply(ww, rec, log)
    monkeypatch.setattr(HS, "_apply", apply)
    monkeypatch.setattr(HS, "N", 100)                     # E1M3 holds 152 slots (E1M1 53): fewer records
    rnd = random.Random(0xC64)
    records = HS._records(w)
    for rec in records:
        rec["inv"] = rnd.choice((0, 2100, 2100, 5))
    want = HS._expected(w, records)
    n = w.layout.nmon
    body = ["stl.startup_and_init_all"]
    for rec in records:
        m = rec["m"]
        body += ["hex.zero %d, mon_shootable" % n, "hex.zero %d, thpos_rt" % (16 * n)]
        rows = {m: (rec["mx"], rec["my"], 1)}
        rows.update(rec["crowd"])
        if rec["target"] >= 2:
            rows[rec["target"] - 2] = rec["tpos"] + (rec["talive"],)
        for j, (x, y, alive) in sorted(rows.items()):
            body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 12, y & 0xFFFF)]
            if alive:
                body += ["hex.set 1, mon_shootable + %d*dw, 1" % j]
        nb = len(rec["bars"])
        body += ["hex.set %d, bar_st, %d" % (2 * nb, sum(st << (8 * b) for b, (st, _hp) in enumerate(rec["bars"]))),
                 "hex.set %d, bar_hp, %d" % (2 * nb, sum((hp & 0xFF) << (8 * b) for b, (_st, hp) in
                                                         enumerate(rec["bars"])))]
        body += ["hex.set 8, viewx, %d" % rec["px16"], "hex.set 8, viewy, %d" % rec["py16"],
                 "hex.set 1, p_dead, %d" % rec["pdead"], "hex.set 3, p_hp, %d" % (0 if rec["pdead"] else 100),
                 "hex.set 3, p_inv, %d" % rec["inv"],
                 "hex.set 4, mm_x, %d" % (rec["mx"] & 0xFFFF), "hex.set 4, mm_y, %d" % (rec["my"] & 0xFFFF),
                 "hex.set 2, mm_rng, %d" % rec["rng"], "hex.set 1, mm_seen, %d" % rec["seen"],
                 "hex.set 1, sl_hit, %d" % rec["hit"], "hex.set 1, mm_kind, %d" % MD.ATTACK_KINDS[HS.ACTION[rec["tp"]]],
                 "hex.set 2, md_src, %d" % (m + 1), "hex.set 2, mm_tg, %d" % rec["target"],
                 "stl.fcall mt_load, mt_lret", "stl.fcall md_attack, md_ret",
                 "hex.print_as_digit 2, mm_rng, 0", "hex.print_as_digit 1, mm_fa, 0", "stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = HS._program(w, None)
    if mut:
        old, new = HS_MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    from doomfj.wall_renderer import hoisted_scratch_fj
    prog = "\n".join(body + decls + [text] + tables) + "\n" + hoisted_scratch_fj()
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    assert MC is not None
    ok = fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                         should_raise_assertion_error=False)
    return ok, w, records


@needs_wad
def test_the_shadow_turn_in_the_attack_follows_the_model(tmp_path, monkeypatch):
    ok, w, records = _hs_shadow(tmp_path, "hs_shadow", None, monkeypatch)
    # the records reach the rule: bullets at an invisible player in sight (the turn read), and at a visible one
    shots = sum(1 for r in records if r["target"] == 1 and r["inv"] and r["tp"] in (3004, 9) and not r["pdead"])
    assert shots >= 20, shots
    assert ok, "the fj shadow turn parted from the model's _monster_attack"


@needs_wad
@pytest.mark.parametrize("mut", sorted(HS_MUTANTS))
def test_control_a_broken_shadow_turn_is_caught(tmp_path, monkeypatch, mut):
    ok, _w, _r = _hs_shadow(tmp_path, "hs_shadow_" + mut, mut, monkeypatch)
    assert not ok, "%s passed: the comparison is vacuous" % mut


# ==== THE SHADOW TURN IN THE FIGHT TIC (the slots, the decisions, the attacks) ==========================================
# tests/fj/test_monster_target_fj.py's whole monster tic (monstercode's fight slots, the chase, `mm_decide`,
# `md_attack`) on E1M3's World with the decide leaves' `shadow=True`: the player invisible for a stretch of the script.
# What only this harness reaches: the DECISION's facing (mm_decide's attack state A_FaceTarget) drawing its two.
TG_FRAMES = 60                              # E1M3's 152 slots are printed every frame
TG_MUTANTS = {
    "decide_face_no_draw": ("  mm_dc_face:\n    stl.fcall mm_octant, mm_ocret\n    stl.fcall mm_shj, mm_shjret\n",
                            "  mm_dc_face:\n    stl.fcall mm_octant, mm_ocret\n"),
    "spread_ignores_turn": ("    hex.add 4, md_sp, md_jit\n", ""),
}
M32 = 0xFFFFFFFF


def _tg_world():
    from doomfj.world import TicEvents
    w = World(_SuitWad(WadFile.from_path(str(FULL))), "E1M3", skill=gd.SK_HARD, monsters="final", player="final",
              sight_rule="seen")
    ws, n = w.ws, w.layout.nmon
    act = [m for m in range(n) if ws.mon_active[m]]
    best = max(act, key=lambda m: sum(1 for j in act if max(abs(ws.mon_x[j] - ws.mon_x[m]),
                                                            abs(ws.mon_y[j] - ws.mon_y[m])) < 600))
    cx, cy = ws.mon_x[best], ws.mon_y[best]
    near = [m for m in act if max(abs(ws.mon_x[m] - cx), abs(ws.mon_y[m] - cy)) < 600]
    rnd = random.Random(0xC65)
    for k, m in enumerate(near):
        w._set_state(m, w.mon_info[m].seestate, False, TicEvents(0))
        ws.mon_reaction[m] = 0
        others = [j for j in near if j != m]
        ws.mon_target[m] = 1 if (k % 3 or not others) else 2 + rnd.choice(others)
    w._tg_centre = (cx, cy)
    return w


def _tg_set(TG, w, x16, y16, ang, dead, seen, kill, inv=0):
    TG._set(w, x16, y16, ang, dead, seen, kill)
    w.ws.p_invis = inv


def _tg_script(TG):
    from doomfj.world import TicEvents
    w = _tg_world()
    rnd = random.Random(0xC66)
    awake = [m for m in range(w.layout.nmon) if w.ws.mon_target[m]]
    out = []
    px, py = w._tg_centre[0] + 150, w._tg_centre[1]
    for f in range(TG_FRAMES):
        px += rnd.randint(-30, 30)
        py += rnd.randint(-30, 30)
        seen = set(rnd.sample(awake, min(6, len(awake))))
        inv = 2100 - f if 10 <= f < 100 else 0
        rec = (((px << 16) | rnd.randrange(1 << 16)) & M32, ((py << 16) | rnd.randrange(1 << 16)) & M32,
               rnd.randrange(1 << 32), 0, seen, set(), inv)
        out.append(rec)
        _tg_set(TG, w, *rec)
        TG._hook(w, [])
        w._monsters_phase(TicEvents(0))
    return out


def _tg_shadow(tmp_path, name, mut, monkeypatch):
    import tests.fj.test_monster_target_fj as TG
    from doomfj import monsterdecide as MD
    orig_dl, orig_ctx, orig_tab = MD.decide_leaves, MD.context_decls, MD.fight_tables_fj
    monkeypatch.setattr(MD, "decide_leaves", lambda **kw: orig_dl(**kw, shadow=True))
    monkeypatch.setattr(MD, "context_decls", lambda: orig_ctx() + PC.decls((P.INVIS_TYPE,)))
    monkeypatch.setattr(MD, "fight_tables_fj", lambda sine, *rest: orig_tab(sine, *rest) + PC.tables_fj((P.INVIS_TYPE,)))
    script = _tg_script(TG)
    orig_set = TG._set
    monkeypatch.setattr(TG, "_world", _tg_world)

    def tset(w, x16, y16, ang, dead, seen, kill, inv=0):
        orig_set(w, x16, y16, ang, dead, seen, kill)
        w.ws.p_invis = inv
    monkeypatch.setattr(TG, "_set", tset)
    want = TG._expected(script)
    w = _tg_world()
    n = w.layout.nmon
    body = ["stl.startup_and_init_all"]
    for x16, y16, ang, dead, seen, kill, inv in script:
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set 1, p_dead, %d" % dead, "hex.set 3, p_hp, %d" % (0 if dead else 100),
                 "hex.set 3, p_inv, %d" % inv,
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen))]
        body += ["stl.fcall mt_tic_leaf, mt_tret"]
        for m in range(n):
            body += ["hex.print_as_digit 2, mon_state + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_tics + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_target + %d*dw, 0" % (TG.NTG * m),
                     "hex.print_as_digit 1, mon_reaction + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_threshold + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_movedir + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_movecount + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 2, mon_rng + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_justattacked + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_justhit + %d*dw, 0" % m,
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
                     "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m)]
        body += ["hex.print_as_digit 2, sched_cursor, 0",
                 "hex.zero %d, dreq" % (2 * len(w.door_order)), "hex.zero %d, lreq" % (2 * len(w.lift_order)),
                 "stl.output 10"]
    body += ["stl.loop"]
    decls, text = TG._parts(w, None)
    if mut:
        old, new = TG_MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    from doomfj.wall_renderer import hoisted_scratch_fj
    prog = "\n".join(body + decls + [text]) + "\n" + hoisted_scratch_fj()
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


@needs_wad
def test_the_fight_tic_script_decides_at_an_invisible_player():
    """the model's events over the script: decisions at the player while he is invisible (their facing draws) and
    bullets at him"""
    import tests.fj.test_monster_target_fj as TG
    from doomfj.world import TicEvents
    script = _tg_script(TG)
    w = _tg_world()
    dec = shots = 0
    for fr in script:
        TG._hook(w, [])
        _tg_set(TG, w, *fr)
        before = list(w.ws.mon_target[:w.layout.nmon])
        ev = TicEvents(0)
        w._monsters_phase(ev)
        if fr[6]:
            dec += sum(1 for m, _k in ev.decisions if before[m] == 1)
            shots += sum(1 for s in ev.mon_shots if w.ws.mon_target[s[0]] == 1)
    assert dec >= 5 and shots >= 5, (dec, shots)


@needs_wad
def test_the_fight_tic_at_an_invisible_player_follows_the_model(tmp_path, monkeypatch):
    assert _tg_shadow(tmp_path, "tg_shadow", None, monkeypatch), \
        "the fj fight tic parted from the model's with an invisible player"


@needs_wad
@pytest.mark.parametrize("mut", sorted(TG_MUTANTS))
def test_control_a_broken_fight_tic_shadow_is_caught(tmp_path, monkeypatch, mut):
    assert not _tg_shadow(tmp_path, "tg_shadow_" + mut, mut, monkeypatch), "%s passed: the comparison is vacuous" % mut
