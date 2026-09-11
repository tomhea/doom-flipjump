"""Do the two new screen commands reassemble correctly from a BYTE STREAM?

fj 1.5.1 gained two window controls, specified by the project owner:

    0x12 set_window_title : [0x12] <utf-8 bytes> 0x00           -- letters until a NUL
    0x13 set_window_icon  : [0x13][w][h] w*h palette indices    -- indices into the palette 0x02 set

Both are IN-STREAM and variable length, which the device's command table did not previously
support in this shape. `ScreenIO._command_length` is consulted after every byte and can see the
partial buffer, so:

  * the TITLE asks for "one more than I have" until the buffer ends in 0x00, then for exactly what
    it has -- which fires the existing dispatch with no streaming-mode flag;
  * the ICON buffers its 3-byte header, reads w and h out of it, then asks for 3 + w*h -- the same
    shape CMD_UPDATE_SCREEN_RAW already uses to derive its length from the screen size.

The risk this file exists to cover is a command that fires EARLY (truncating a title, or executing
an icon before its pixels arrive) or one that never fires at all and swallows the rest of the
stream. Both are invisible without a byte-level test.

    python scratchpad/12m/wincmd_check.py --selftest

CONTROLS (R9)
  C1 EXACT ROUND TRIP -- the title that arrives is the title that was sent, terminator stripped.
  C2 IT MUST NOT FIRE EARLY -- with every byte but the NUL delivered, nothing has executed yet. A
     length rule that fires early would still pass C1 on a short title.
  C3 A TRUNCATED ICON MUST NOT FIRE -- w*h-1 pixels in, still nothing.
  C4 NO STREAM CORRUPTION -- a normal command sent AFTER the two new ones must still execute, i.e.
     the buffer was left clean. This is what a never-firing command would break.
  C5 EMBEDDED ZERO PIXELS ARE SAFE -- an icon whose pixel data contains 0x00 must not be cut short
     by the title's terminator rule.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path("C:/Users/tomhe/Documents/flipjump-151")))
from flipjump.interpreter.io_devices.ScreenIO import (                    # noqa: E402
    InMemoryScreen, CMD_INIT_SCREEN, CMD_SET_WINDOW_TITLE, CMD_SET_WINDOW_ICON)


def feed(screen, data):
    for byte in data:
        screen._handle_byte(byte)


def init_bytes(w=160, h=100, bpp=8, pal=256):
    return bytes([CMD_INIT_SCREEN, w & 0xFF, w >> 8, h & 0xFF, h >> 8, bpp, pal & 0xFF, pal >> 8])


def title_bytes(text):
    return bytes([CMD_SET_WINDOW_TITLE]) + text.encode("utf-8") + b"\x00"


def icon_bytes(w, h, indices):
    return bytes([CMD_SET_WINDOW_ICON, w, h]) + bytes(indices)


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("wincmd_check selftest -- a command that fires EARLY still round-trips a short title")

    scr = InMemoryScreen()
    feed(scr, init_bytes())
    feed(scr, title_bytes("FlipJump DOOM"))
    check("C1 the title round-trips exactly", scr.window_title == "FlipJump DOOM",
          repr(scr.window_title))

    # C2 -- everything but the terminator: nothing may have executed.
    scr2 = InMemoryScreen()
    feed(scr2, init_bytes())
    feed(scr2, bytes([CMD_SET_WINDOW_TITLE]) + b"NotDoneYet")
    check("C2 no NUL yet -> the command has NOT fired", scr2.window_title is None,
          repr(scr2.window_title))
    feed(scr2, b"\x00")
    check("C2 ...and it fires exactly on the NUL", scr2.window_title == "NotDoneYet")

    # C3 -- a truncated icon must not execute.
    scr3 = InMemoryScreen()
    feed(scr3, init_bytes())
    px = [7] * (4 * 4)
    feed(scr3, icon_bytes(4, 4, px[:-1]))
    check("C3 truncated icon (w*h-1 pixels) has NOT fired", scr3.window_icon is None,
          repr(scr3.window_icon))
    feed(scr3, bytes([px[-1]]))
    check("C3 ...and fires on the last pixel", scr3.window_icon == (4, 4, px))

    # C5 -- pixel data containing 0x00 must survive (the title rule must not touch it).
    scr5 = InMemoryScreen()
    feed(scr5, init_bytes())
    zpx = [0, 5, 0, 9]
    feed(scr5, icon_bytes(2, 2, zpx))
    check("C5 icon pixels may contain 0x00", scr5.window_icon == (2, 2, zpx),
          repr(scr5.window_icon))

    # C4 -- the stream must still be usable afterwards.
    scr4 = InMemoryScreen()
    feed(scr4, init_bytes(w=8, h=4))
    feed(scr4, title_bytes("T"))
    feed(scr4, icon_bytes(2, 2, [1, 2, 3, 4]))
    feed(scr4, init_bytes(w=32, h=16))          # a NORMAL command after the two new ones
    check("C4 a normal command after them still executes",
          (scr4.width, scr4.height) == (32, 16), "%dx%d" % (scr4.width, scr4.height))

    check("C1 unicode survives the round trip",
          (lambda s: (feed(s, init_bytes()), feed(s, title_bytes("FlipJump DOOM \u2014 E1M1")),
                      s.window_title == "FlipJump DOOM \u2014 E1M1")[2])(InMemoryScreen()))

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.parse_args()
    sys.exit(selftest())
