"""M8 C6: the per-frame op cost of the timed powers' fj, MEASURED by running each spliced fragment K times on the real
engine against the same loop with an empty fragment (the difference / K). Prints one line per (fragment, state).

    PYTHONPATH=src python scratchpad/c6/power_costs.py

R9 (the harness measures something): the empty fragment's difference is 0, and a fragment of exactly one `hex.inc 1`
must cost what the engine counts for it (> 0) -- both asserted.
"""
import sys
import tempfile
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IOReadOnEOF

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import hud, hudcode  # noqa: E402
from doomfj import hurtcode as H  # noqa: E402
from doomfj import powercode as PC  # noqa: E402
from doomfj import powers as P  # noqa: E402
from doomfj import weaponcode as WC  # noqa: E402
from doomfj.config import GAME_CFG  # noqa: E402
from doomfj.harness import W  # noqa: E402
from doomfj.lut_generator import generate_dispatch_table_fj  # noqa: E402
from doomfj.wad import WadFile  # noqa: E402

FJ = ROOT / "src" / "fj"
K = 64
BOTH = (P.INVIS_TYPE, P.SUIT_TYPE)


class _Screen(InMemoryScreen):
    def read_bit(self):
        raise IOReadOnEOF("no input")


def ops(frag, setup, decls, tables=(), frames=False):
    """ops of K runs of `frag` (a leaf) after `setup`"""
    body = ["stl.startup_and_init_all", "screen.init_screen W, H, 8", *setup]
    for _ in range(K):
        body += (["screen.draw_collines"] if frames else []) + ["stl.fcall frag_leaf, frag_ret"] + (
            ["stl.output_char 0xFF"] if frames else [])
    body += ["stl.loop", "frag_ret: hex.vec w/4", "frag_leaf:", *frag, "stl.fret frag_ret", *decls, *tables]
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "c.fj"
        src.write_text("\n".join(body) + "\n", encoding="utf-8")
        out = Path(d) / "c.fjm"
        consts = GAME_CFG.emit_fj_consts(Path(d) / "fj_consts.fj")
        fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()], out,
                    memory_width=W, print_time=False)
        st = fj.run(out, io_device=_Screen(), print_time=False, print_termination=False)
        return st.op_counter


def per(frag, setup=(), decls=(), tables=(), frames=False, pre=()):
    """`pre`: lines run before the fragment inside every iteration (a state the fragment changes, put back), priced
    out by the baseline"""
    return (ops(list(pre) + frag, setup, decls, tables, frames) - ops(list(pre), setup, decls, tables, frames)) / K


def main():
    pdecls = PC.decls(BOTH)
    assert per([], (), pdecls) == 0
    one = per(["hex.inc 1, x1"], (), ["x1: hex.vec 1"])
    assert one > 0
    print("control: hex.inc 1 = %.1f ops" % one)
    for st in ((0, 0), (2100, 0), (2100, 2100)):
        print("countdown (p_inv, p_rad) = %s: %.1f" % (st, per(PC.countdown_lines(BOTH),
                                                             ["hex.set 3, p_inv, %d" % st[0],
                                                              "hex.set 3, p_rad, %d" % st[1]], pdecls)))
    pal_d = ["pal_new: hex.vec 1"] + pdecls
    for pn, rad in ((3, 2100), (0, 0), (0, 2100), (0, 100)):
        print("radiation palette test pal_new=%d p_rad=%d: %.1f" % (pn, rad, per(
            PC.pal_lines(), ["hex.set 3, p_rad, %d" % rad], pal_d, pre=["hex.set 1, pal_new, %d" % pn])))
    for pl, inv in ((0, 2100), (1, 0), (1, 2100)):
        print("mm_shj (A_FaceTarget) mt_pl=%d p_inv=%d: %.1f" % (pl, inv, per(
            ["stl.fcall mm_shj, mm_shjret"], ["hex.set 1, mt_pl, %d" % pl, "hex.set 3, p_inv, %d" % inv],
            pdecls + ["mt_pl: hex.vec 1", "mm_rng: hex.vec 2"] + PC.shj_leaf_lines(), PC.tables_fj(BOTH))))
    for pl, inv in ((1, 0), (1, 2100)):
        print("missile turn mt_pl=%d p_inv=%d: %.1f" % (pl, inv, per(
            PC.missile_lines(), ["hex.set 1, mt_pl, %d" % pl, "hex.set 3, p_inv, %d" % inv],
            pdecls + ["mt_pl: hex.vec 1", "mm_rng: hex.vec 2", "pw_ang: hex.vec 8"], PC.tables_fj(BOTH))))
    for rad, dmg in ((0, 20), (2100, 10), (2100, 20)):
        print("suit at a hurt p_rad=%d dmg=%d: %.1f" % (rad, dmg, per(
            PC.suit_lines("sx_h", "sx_o") + ["sx_h:", "sx_o:"],
            ["hex.set 3, p_rad, %d" % rad, "hex.set 2, nk_dmg, %d" % dmg],
            pdecls + ["nk_dmg: hex.vec 2", "rng_pl: hex.vec 2"], PC.tables_fj(BOTH))))
    # the weapon's tail: the pistol (frame 0, no flash) -- E1M1's tail, the shadow tail visible, the shadow tail shown
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    colours = hud.bar_colours(bytes(b for rgb in art.playpal(0) for b in rgb))
    cols = lambda lump: hud.psprite_columns(art.get_data(lump))      # noqa: E731
    weapons, flashes = [cols(x) for x in WC.overlay_frames()], [cols(x) for x in WC.flash_frames()]
    row = art.colormap()[0]
    shd = ([hud.shadow_columns(o) for o in weapons], [hud.shadow_columns(o) for o in flashes],
           hud.shadow_row(art.colormap(), row))
    start = hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))
    hd = [*hudcode.hud_decls(start), "pcard: hex.vec 1", "wp_frm: hex.vec 2", "fl_frm: hex.vec 1"] + pdecls
    setup = ["hex.zero 1, hud_full"]
    plain = per(hudcode.hud_tail_lines(colours, (weapons, flashes), row, view_rows=GAME_CFG.VIEW_H), setup, hd,
                frames=True)
    print("weapon tail, pistol, E1M1's text: %.1f" % plain)
    for inv in (0, 2100):
        t = per(hudcode.hud_tail_lines(colours, (weapons, flashes), row, view_rows=GAME_CFG.VIEW_H, shadow=shd),
                setup + ["hex.set 3, p_inv, %d" % inv], hd, frames=True)
        print("weapon tail, pistol, shadow text, p_inv=%d: %.1f (%+.1f)" % (inv, t, t - plain))


if __name__ == "__main__":
    main()
