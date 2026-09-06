"""Does a tier FIT under the address ceiling, and if not, by how much?

This is the tool that found the shipped `game` tier over the ceiling after the P7 pad round
(reported at the time as 45.6% over -- UNVERIFIED, measured before this probe had controls)
-- an assembler `OverflowError` that every gate missed, because every gate built the `deg` tier.
`docs/handoff-fullgame-metrics.md` §6b therefore makes it MANDATORY on any stl or shared-emitter
change.

HOW. The assembler hands out wflip-chain slots through `BinaryData.get_wflip_spot`, and the
address it returns is what eventually blows past `1 << memory_width` bits at
`flipjump/assembler/assembler.py:24`. So we wrap that method, track the peak address handed out,
and report it in words against `fjmsize.ceiling_words(w)`. The build is driven only as far as
pass 1 (`selfreset.emit_reset_part` aborts it), so a doomed tier costs one pass, not two.

⚠ The peak this reports is a PASS-1 number and is NOT the decompressed word count the SIZE metric
measures -- pass 2 adds the reset part. A pass-1 -> decompressed ratio of ~1.184 was recorded on
the padded game build, but BOTH of its numbers predate the controls in this file and in
`fjmsize.py`, so it is UNVERIFIED and is a planning estimate only; rung 1 re-measures it. Use
`fjmsize.py` on the built .fjm for the metric; use this to answer "will it assemble at all".

    python scratchpad/12m/overflow_probe.py game
    python scratchpad/12m/overflow_probe.py --selftest
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad" / "12m"):
    sys.path.insert(0, str(q))

from fjmsize import ceiling_words                                     # noqa: E402


class WflipSpy:
    """the peak wflip address the assembler handed out, and what it means"""

    def __init__(self, memory_width=32):
        self.memory_width = memory_width
        self.peak_bits = 0
        self.spots = 0

    def observe(self, address):
        self.spots += 1
        if address > self.peak_bits:
            self.peak_bits = address
        return address

    @property
    def peak_words(self):
        # ⚠ // memory_width, NOT // 32. The ceiling and the word size move together; a probe that
        # hardcodes 32 disagrees with `fjmsize` the moment the campaign asks the w=64 question.
        return self.peak_bits // self.memory_width

    @property
    def ceiling(self):
        return ceiling_words(self.memory_width)

    @property
    def over(self):
        return self.peak_words - self.ceiling

    def verdict(self):
        """FITS / OVER / UNKNOWN -- and UNKNOWN is a real answer, not a silent pass.

        A spy that observed nothing has peak 0, which compares as comfortably under the ceiling.
        That is the failure mode that would make this probe rubber-stamp every tier, so it is
        named rather than reported as a fit."""
        if self.spots == 0:
            return "UNKNOWN"
        return "OVER" if self.peak_words > self.ceiling else "FITS"

    def report(self):
        print("", flush=True)
        print("wflip spots handed out : %s" % format(self.spots, ","), flush=True)
        print("peak wflip address     : %s bits = %s words"
              % (format(self.peak_bits, ","), format(self.peak_words, ",")), flush=True)
        print("ceiling (w=%d)          : %s words (2^%d)"
              % (self.memory_width, format(self.ceiling, ","), self.ceiling.bit_length() - 1),
              flush=True)
        if self.spots == 0:
            print("VERDICT                : UNKNOWN -- the hook never fired, so this run proves "
                  "NOTHING about the tier", flush=True)
        else:
            print("OVER by                : %s words (%+.1f%% of the ceiling)"
                  % (format(self.over, "+,"), 100.0 * self.over / self.ceiling), flush=True)
            print("VERDICT                : %s" % self.verdict(), flush=True)


def install(spy):
    """wrap `BinaryData.get_wflip_spot`; returns the uninstall callable"""
    import flipjump.assembler.assembler as asm
    real = asm.BinaryData.get_wflip_spot

    def spy_spot(self):
        s = real(self)
        spy.observe(s.address)
        return s

    asm.BinaryData.get_wflip_spot = spy_spot
    return lambda: setattr(asm.BinaryData, "get_wflip_spot", real)


def probe(tier, memory_width=32):
    from doomfj import selfreset
    from doomfj.build import build_wall_renderer

    spy = WflipSpy(memory_width)
    uninstall = install(spy)

    class Done(Exception):
        pass

    real_emit = selfreset.emit_reset_part
    selfreset.emit_reset_part = lambda *a, **k: (_ for _ in ()).throw(Done())
    err = None
    try:
        build_wall_renderer(ROOT / "build/overflow_probe.fjm", tier=tier)
    except Done:
        print("reached emit_reset_part without an OverflowError -- pass 1 completed", flush=True)
    except Exception as e:                                            # noqa: BLE001
        err = e
    finally:
        selfreset.emit_reset_part = real_emit
        uninstall()
    spy.report()
    if err is not None:
        print("crash: %s: %s" % (type(err).__name__, str(err)[:100]), flush=True)
    return spy


# ----------------------------------------------------------------------------------------------
# R9: the negative controls
# ----------------------------------------------------------------------------------------------

def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("overflow_probe selftest -- a probe that cannot say OVER cannot say FITS", flush=True)

    # C1  it tracks the MAXIMUM, not the last or the first
    s = WflipSpy(32)
    for a in (10, 500, 3, 499):
        s.observe(a)
    check("C1 peak is the max address seen, not the last", s.peak_bits == 500,
          "peak=%d spots=%d" % (s.peak_bits, s.spots))
    check("C1 every spot is counted", s.spots == 4)

    # C2  THE WIDTH CONTROL. The same bit address is a different word count at a different width,
    #     and the ceiling moves with it. A probe with `BITS_PER_WORD = 32` gets this wrong.
    a = WflipSpy(32)
    b = WflipSpy(64)
    a.observe(1 << 40)
    b.observe(1 << 40)
    check("C2 words derive from memory_width", a.peak_words == 2 * b.peak_words,
          "w32=%s w64=%s" % (format(a.peak_words, ","), format(b.peak_words, ",")))
    check("C2 the ceiling derives too", a.ceiling == ceiling_words(32)
          and b.ceiling == ceiling_words(64))

    # C3  THE VERDICT CONTROL. It must be able to say OVER, and it must not say FITS on silence.
    over = WflipSpy(32)
    over.observe((1 << 32) + (1 << 20))                # past 2^32 bits = past 2^27 words
    check("C3 it SAYS OVER when the peak passes the ceiling", over.verdict() == "OVER",
          "peak=%s words, ceiling=%s" % (format(over.peak_words, ","), format(over.ceiling, ",")))
    under = WflipSpy(32)
    under.observe(1 << 20)
    check("C3 it says FITS when the peak is under", under.verdict() == "FITS")
    check("C3 a spy that saw NOTHING says UNKNOWN, not FITS", WflipSpy(32).verdict() == "UNKNOWN",
          "this is the silent-rubber-stamp failure mode")

    # C4  THE HOOK CONTROL, against the REAL assembler. This is the one that matters: the probe's
    #     whole claim rests on `get_wflip_spot` actually being wrapped. Assemble a tiny real
    #     program with the hook in, and again with it out.
    import tempfile
    import flipjump as fj
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "tiny.fj"
        src.write_text("stl.startup_and_init_all\n    stl.loop\n", encoding="utf-8")
        hooked = WflipSpy(32)
        un = install(hooked)
        try:
            fj.assemble([src], tmp / "hooked.fjm", memory_width=32, print_time=False)
        finally:
            un()
        check("C4 the hook FIRES on a real assembly", hooked.spots > 0,
              "%s spots, peak %s words"
              % (format(hooked.spots, ","), format(hooked.peak_words, ",")))
        check("C4 a real tiny program FITS", hooked.verdict() == "FITS")

        after = WflipSpy(32)
        fj.assemble([src], tmp / "unhooked.fjm", memory_width=32, print_time=False)
        check("C4 uninstall really uninstalls (a fresh spy sees nothing)", after.spots == 0,
              "and it therefore reports %s" % after.verdict())

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    tier = sys.argv[1] if len(sys.argv) > 1 else "hosted-loop"
    print("driving the %r build to pass 1 (instrumented) ..." % tier, flush=True)
    sys.exit(0 if probe(tier).verdict() == "FITS" else 2)
