"""Do the new fj macros actually reach the device? End to end, through a real assemble+run.

`wincmd_check.py` proves the DEVICE reassembles 0x12/0x13 from a byte stream, and the emitter test
proves the right fj TEXT is generated. Neither proves the two meet: a wrong operand order, a
miscounted string length or a macro that emits nothing at all would pass both and still ship a
window called "FlipJump".

This assembles a ~10-line fj program that calls `present.set_window_title` and
`present.set_window_icon_header`, runs it on the stock interpreter with a headless InMemoryScreen,
and asserts what the screen received. Seconds, not a 35-minute game build.

    python scratchpad/12m/chrome_e2e.py --selftest

CONTROLS (R9)
  C1 THE TITLE ARRIVES INTACT -- the exact string, terminator stripped, byte for byte.
  C2 NEGATIVE CONTROL -- a program that does NOT call the macro must leave the title unset. Without
     this, a device that defaulted its title to the right string would pass C1.
  C3 THE ICON ARRIVES WITH THE RIGHT SHAPE AND PIXELS -- dimensions and every index.
  C4 THE STREAM SURVIVES -- a normal screen command issued afterwards still executes, proving the
     new commands consumed exactly their own bytes and no more.
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path("C:/Users/tomhe/Documents/flipjump-151")))

import flipjump as fj                                                      # noqa: E402
from flipjump.interpreter.fjm_run import run as fjm_run                    # noqa: E402
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen        # noqa: E402
from doomfj.config import Config                                           # noqa: E402

W = 32


def build_and_run(body):
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        consts = Config().emit_fj_consts(t / "fj_consts.fj")
        src = t / "s.fj"
        src.write_text(body, encoding="utf-8")
        out = t / "o.fjm"
        fj.assemble([consts.resolve(), (ROOT / "src" / "fj" / "present.fj").resolve(),
                     src.resolve()], out, memory_width=W, print_time=False)
        screen = InMemoryScreen()
        fjm_run(out, io_device=screen, print_time=False)
        return screen


PROLOGUE = """
stl.startup_and_init_all
    present.init_screen
"""
EPILOGUE = """
    stl.loop
"""


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("chrome_e2e selftest -- a device that DEFAULTED to the right title would pass C1 alone")

    text = "FlipJump DOOM"
    big = 0
    for i, ch in enumerate(text.encode("utf-8")):
        big |= ch << (8 * i)

    scr = build_and_run(PROLOGUE + "    present.set_window_title %s, %d\n" % (hex(big), len(text))
                        + EPILOGUE)
    check("C1 the title arrives intact through assemble+run", scr.window_title == text,
          repr(scr.window_title))

    bare = build_and_run(PROLOGUE + EPILOGUE)
    check("C2 a program that never calls it leaves the title UNSET", bare.window_title is None,
          repr(bare.window_title))

    px = [0, 1, 2, 3, 4, 5, 6, 7, 8]
    icon = (PROLOGUE + "    present.set_window_icon_header 3, 3\n"
            + "".join("    stl.output_char %d\n" % v for v in px) + EPILOGUE)
    scr3 = build_and_run(icon)
    check("C3 the icon arrives with the right shape and pixels",
          scr3.window_icon == (3, 3, px), repr(scr3.window_icon))

    both = (PROLOGUE + "    present.set_window_title %s, %d\n" % (hex(big), len(text))
            + "    present.set_window_icon_header 2, 2\n"
            + "".join("    stl.output_char %d\n" % v for v in (9, 9, 9, 9))
            + "    present.init_screen\n" + EPILOGUE)
    scr4 = build_and_run(both)
    check("C4 a normal command after both still executes",
          scr4.window_title == text and scr4.window_icon == (2, 2, [9, 9, 9, 9])
          and (scr4.width, scr4.height) == (Config().W, Config().H),
          "%s / %s / %dx%d" % (scr4.window_title, scr4.window_icon,
                               scr4.width, scr4.height))

    # C5 -- THE EMITTER'S OWN OUTPUT, not a hand-written equivalent. The first version of this
    # file hand-wrote the icon one statement per line while the emitter joined them with spaces,
    # so the test passed and the 34-minute game build died on a parse error. Assemble what the
    # emitter actually produces.
    from doomfj.wall_renderer import window_chrome_fj, WINDOW_TITLE
    macro, calls = window_chrome_fj()      # generated art now -- no wad, no lump, every tier
    src = (PROLOGUE + "".join("    " + c + "\n" for c in calls) + EPILOGUE
           + "\n" + "\n".join(macro) + "\n")
    scr5 = build_and_run(src)
    check("C5 the EMITTER's own fj text assembles and arrives",
          scr5.window_title == WINDOW_TITLE and scr5.window_icon is not None
          and scr5.window_icon[0] == 32 and len(scr5.window_icon[2]) == 32 * 32,
          "%r / icon %s" % (scr5.window_title,
                            None if not scr5.window_icon else
                            "%dx%d, %d px" % (scr5.window_icon[0], scr5.window_icon[1],
                                              len(scr5.window_icon[2]))))

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.parse_args()
    sys.exit(selftest())
