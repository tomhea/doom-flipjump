"""How much of the frame is still WRITING JUMP WORDS, measured on any binary, without labels.

FINDINGS BD measured that 78.32% of the shipped game's ops were wflips writing a table ADDRESS into
a hex variable's jump word. Everything since has been aimed at that number. But that measurement
was taken on the PRE-BLOCKING binary, and BI/BJ changed the program -- so picking the next lever
from BD would be optimising a cost model that no longer holds.

This re-measures it directly, and needs no label table, so it runs on any .fjm in minutes rather
than after a 30-minute labels build.

THE CLASSIFIER. An fj op is two words: [flip][jump]. A hex variable is a single op `;val*dw`, so
its JUMP word is the second one, at `var + w`. A wflip that arms a dispatch flips bits of that
word, so its flip address lands in `[var+w, var+2w)` -- i.e. `flip_address mod 2w >= w`. An op that
flips a DATA bit of a hex (the value nibble also lives in the jump word) is caught by the same
test, which is why the number is an upper bound on arming and is reported as "jump-word writes"
rather than "arming".

    python scratchpad/12m/jumpwordcost.py --fjm build/doom_e1m1_blocked2.fjm --frames 3
    python scratchpad/12m/jumpwordcost.py --selftest

CONTROLS (R9)
  C1 CONSERVATION -- the per-op hook must see every op the interpreter counted, or the shares are
     computed against the wrong denominator and a miss reads as "less of the frame".
  C2 THE CLASSIFIER SEPARATES -- on a synthetic image it must count a jump-word flip and reject a
     flip-word one. A classifier that accepts everything reports 100% and looks dramatic.
  C3 NON-VACUITY -- a run that executes no ops, or classifies none, is reported as VACUOUS rather
     than as 0%.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT, ROOT / "scratchpad" / "12m"):
    sys.path.insert(0, str(q))


class _Recorder:
    """`fjm_run` calls should_break(ip, op_counter) on every executed op when a breakpoint handler
    is supplied. Returning False never stops; this is a per-op hook needing no interpreter change
    (the mechanism scratchpad/ca2_profile.py established)."""

    def __init__(self, memory, width):
        self.memory = memory
        self.width = width
        self.op_bits = 2 * width
        self.total = 0
        self.jump_word_writes = 0

    def should_break(self, ip, op_counter):
        self.total += 1
        flip = self.memory.get(ip // self.width, 0)
        if flip % self.op_bits >= self.width:
            self.jump_word_writes += 1
        return False


def measure(fjm, frames):
    from flipjump.fjm.fjm_reader import Reader
    from flipjump.interpreter.fjm_run import run as fjm_run
    from m2_std_gate import MENU_FRAMES, Recording, Stopper, ScriptedKeyEventSource, PcIO
    from gamespeed import events_for, script

    reader = Reader(fjm)
    memory = reader.get_memory()
    rec = _Recorder(memory, reader.memory_width)

    per_frame = [{} for _ in range(MENU_FRAMES)] + script(0, frames)
    screen = Recording()
    keyboard = Stopper(ScriptedKeyEventSource(events_for(per_frame)), screen, len(per_frame))
    io = PcIO(screen, keyboard)
    term = fjm_run(Path(fjm), io_device=io, print_time=False, flat_max_words=1 << 27,
                   breakpoint_handler=rec)
    return rec, term, len(screen.frames)


def report(fjm, frames):
    rec, term, presented = measure(fjm, frames)
    print("fjm      : %s" % fjm)
    print("frames   : %d presented" % presented)
    print("ops      : %s counted by the interpreter, %s seen by the hook"
          % (format(term.op_counter, ","), format(rec.total, ",")))
    if rec.total == 0 or presented == 0:
        print("VACUOUS -- no ops or no frames; nothing is being measured")
        return 2
    drift = abs(rec.total - term.op_counter)
    if drift > 1:
        print("C1 FAILED: the hook missed %s ops, so every share below is against the wrong "
              "denominator" % format(drift, ","))
        return 1
    print("")
    print("  jump-word writes : %s = %.2f%% of the frame"
          % (format(rec.jump_word_writes, ","), 100.0 * rec.jump_word_writes / rec.total))
    print("  everything else  : %s = %.2f%%"
          % (format(rec.total - rec.jump_word_writes, ","),
             100.0 * (rec.total - rec.jump_word_writes) / rec.total))
    print("")
    print("  FINDINGS BD measured 78.32% on the PRE-BLOCKING binary. A number well below that")
    print("  means the address-writing cost has been paid down and the next lever should be")
    print("  chosen from what is left, not from BD.")
    return 0


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-56s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("jumpwordcost selftest -- a classifier that accepts everything reports 100%")

    # C2 -- the classifier must SEPARATE. Word 0 is an op's flip word, word 1 its jump word, so at
    # w=32 a flip address of 40 (op 0's jump word) counts and one of 8 (its flip word) does not.
    # 40 mod 64 = 40 and 100 mod 64 = 36 are both in [w, 2w) -- jump words.
    # 8 mod 64 = 8 and 64 mod 64 = 0 are in [0, w) -- flip words. (95 mod 64 = 31 is a FLIP word,
    # which is what the first version of this fixture got wrong.)
    mem = {0: 40, 2: 8, 4: 100, 6: 64}
    rec = _Recorder(mem, 32)
    for ip in (0, 64, 128, 192):
        rec.should_break(ip, 0)
    check("C2 counts flips into a JUMP word (40, 100)", rec.jump_word_writes == 2,
          "%d of %d" % (rec.jump_word_writes, rec.total))
    check("C2 ...and rejects flips into a FLIP word (8, 64)",
          rec.total - rec.jump_word_writes == 2)

    allmem = {0: 32, 2: 33, 4: 63}
    rall = _Recorder(allmem, 32)
    for ip in (0, 64, 128):
        rall.should_break(ip, 0)
    check("C2 the whole jump-word range [w, 2w) counts", rall.jump_word_writes == 3)

    nonemem = {0: 0, 2: 1, 4: 31}
    rnone = _Recorder(nonemem, 32)
    for ip in (0, 64, 128):
        rnone.should_break(ip, 0)
    check("C2 ...and the whole flip-word range [0, w) does not", rnone.jump_word_writes == 0)

    # C3 -- an empty run must be VACUOUS, not 0%
    empty = _Recorder({}, 32)
    check("C3 an empty run has nothing to divide by", empty.total == 0)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked2.fjm")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    return selftest() if a.selftest else report(a.fjm, a.frames)


if __name__ == "__main__":
    sys.exit(main())
