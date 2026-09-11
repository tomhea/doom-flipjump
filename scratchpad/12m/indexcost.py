"""What does ARMING cost per dispatch word, and would a better INDEX ORDER be cheaper?

BU left the campaign with coverage solved and index cost as the remaining lever. Two ways to narrow
an index are known: register splitting (BP -- duplicate the shared leaf so fewer sites share a word;
costs ~3M words of code) and simply handing the CHEAP indices to the HOT tables. `_cheap_indices`
returns the k lowest-popcount indices cheapest-first and `reserve` consumes them in ENCOUNTER ORDER,
so index 0 -- popcount 0, a free arm -- goes to whichever macro expanded first. Reordering is a
permutation: it costs nothing in size and needs no emitter change.

Whether it is worth anything depends entirely on whether calls WITHIN a group are skewed, which
nothing has measured. This measures it, on a shipped binary, with no labels build.

HOW. A wflip of value V into word W executes popcount(V) ops, each flipping one bit in
[W*w, W*w + w), and they run CONSECUTIVELY (the first op is inline, the rest chain). So a maximal
run of consecutive ops sharing `flip // w` is exactly one arm, and the bits it flips are V. That
reconstructs every arm's INDEX and how often it was issued -- which is the call distribution.

    python scratchpad/12m/indexcost.py --fjm build/doom_e1m1_blocked13.fjm --frames 3
    python scratchpad/12m/indexcost.py --selftest

CONTROLS (R9)
  C1 CONSERVATION -- the hook must see every op the interpreter counted.
  C2 CHAIN RECONSTRUCTION -- on a synthetic image, a known wflip of value V must come back as ONE
     chain whose value is V, and two wflips separated by other work must NOT merge.
  C3 NON-VACUITY -- no ops, or no chains, is reported as VACUOUS, never as "0% savings".
  C4 THE COUNTERFACTUAL IS HONEST -- reassignment can never cost MORE than the actual (it is an
     optimal permutation of the same index set), and under a UNIFORM call distribution it must save
     EXACTLY ZERO. A tool that reports a saving on uniform input is measuring its own bug.

CAVEAT. The run groups ALL consecutive same-word flips, so it counts every wflip in the program,
not only dispatch arms -- value-bit writes (hex.set/xor_by) land in the same bucket. It is an upper
bound on arming, and the per-word table is what separates the dispatch words from the rest.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT, ROOT / "scratchpad" / "12m"):
    sys.path.insert(0, str(q))


class _Chains:
    """Groups consecutive same-word flips into arms. See HOW above."""

    def __init__(self, memory, width):
        self.memory = memory
        self.width = width
        self.total = 0
        self.cur_word = None
        self.cur_val = 0
        self.arms = {}                      # word -> Counter{index_value: times issued}

    def _close(self):
        if self.cur_word is not None and self.cur_val:
            self.arms.setdefault(self.cur_word, Counter())[self.cur_val] += 1
        self.cur_word, self.cur_val = None, 0

    def should_break(self, ip, op_counter):
        self.total += 1
        flip = self.memory.get(ip // self.width, 0)
        word = flip // self.width
        bit = flip % self.width
        if word != self.cur_word:
            self._close()
            self.cur_word = word
        self.cur_val |= 1 << bit
        return False

    def finish(self):
        self._close()
        return self.arms


def _pc(v):
    return bin(v).count("1")


def optimal_cost(counter):
    """Cheapest total arm cost for this word if indices were handed out by HOTNESS.

    The index universe is 2^b covering the widest index actually observed, so the counterfactual is
    restricted to indices this word demonstrably could have used.
    """
    calls = sorted(counter.values(), reverse=True)
    span_bits = max(1, max(counter).bit_length())
    cheap = sorted(range(1 << span_bits), key=lambda v: (_pc(v), v))[:len(calls)]
    return sum(c * _pc(i) for c, i in zip(calls, cheap))


def report(fjm, frames, top):
    from flipjump.fjm.fjm_reader import Reader
    from flipjump.interpreter.fjm_run import run as fjm_run
    from m2_std_gate import MENU_FRAMES, Recording, Stopper, ScriptedKeyEventSource, PcIO
    from gamespeed import events_for, script

    reader = Reader(fjm)
    rec = _Chains(reader.get_memory(), reader.memory_width)
    per_frame = [{} for _ in range(MENU_FRAMES)] + script(0, frames)
    screen = Recording()
    keyboard = Stopper(ScriptedKeyEventSource(events_for(per_frame)), screen, len(per_frame))
    term = fjm_run(Path(fjm), io_device=PcIO(screen, keyboard), print_time=False,
                   flat_max_words=1 << 27, breakpoint_handler=rec)
    arms = rec.finish()

    print("fjm    : %s" % fjm)
    print("frames : %d presented" % len(screen.frames))
    print("ops    : %s interpreter, %s hook"
          % (format(term.op_counter, ","), format(rec.total, ",")))
    if rec.total == 0 or not arms or not screen.frames:
        print("VACUOUS -- nothing to measure")
        return 2
    if abs(rec.total - term.op_counter) > 1:
        print("C1 FAILED: hook missed %s ops" % format(abs(rec.total - term.op_counter), ","))
        return 1

    rows = []
    for word, ctr in arms.items():
        cost = sum(c * _pc(v) for v, c in ctr.items())
        rows.append((cost, cost - optimal_cost(ctr), word, sum(ctr.values()), len(ctr)))
    rows.sort(reverse=True)
    tot_cost = sum(r[0] for r in rows)
    tot_save = sum(r[1] for r in rows)
    tot_arms = sum(r[3] for r in rows)

    print("")
    print("arms   : %s issued into %s words, costing %s ops (%.2f%% of the run)"
          % (format(tot_arms, ","), format(len(rows), ","), format(tot_cost, ","),
             100.0 * tot_cost / rec.total))
    print("mean   : %.2f ops per arm" % (tot_cost / max(1, tot_arms)))
    print("")
    print("REORDERING INDICES BY HOTNESS would save %s ops = %.2f%% of arm cost, %.2f%% of the run"
          % (format(tot_save, ","), 100.0 * tot_save / max(1, tot_cost),
             100.0 * tot_save / rec.total))
    print("  (a permutation of the SAME index set: no size cost, no emitter change)")
    print("")
    print("  %-14s %12s %10s %10s %12s" % ("word", "arm ops", "arms", "distinct", "saving"))
    for cost, save, word, issues, distinct in rows[:top]:
        print("  %-14s %12s %10s %10s %12s"
              % (hex(word), format(cost, ","), format(issues, ","), format(distinct, ","),
                 format(save, ",")))
    return 0


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("indexcost selftest -- C4 requires ZERO saving on uniform input")

    # C2 -- word 100 gets bits 0 and 3 (value 9) in one run; word 200 splits them; then word 100
    # gets bit 0 alone. Op i sits at ip = i*2*w, and memory[ip//w] is its flip address.
    w = 32
    mem, ips = {}, []
    for i, flip in enumerate([100 * w + 0, 100 * w + 3, 200 * w + 1, 100 * w + 0]):
        mem[i * 2] = flip
        ips.append(i * 2 * w)
    rec = _Chains(mem, w)
    for ip in ips:
        rec.should_break(ip, 0)
    arms = rec.finish()
    check("C2 one chain per consecutive same-word run", arms.get(100) == Counter({9: 1, 1: 1}),
          str(dict(arms.get(100, {}))))
    check("C2 ...and an intervening word splits them", arms.get(200) == Counter({2: 1}))
    check("C2 chain ops == popcount of the value",
          sum(_pc(v) * c for v, c in arms[100].items()) == 3)

    uni = Counter({0: 10, 1: 10, 2: 10, 3: 10})
    cur_u = sum(c * _pc(v) for v, c in uni.items())
    check("C4 uniform calls save EXACTLY zero", optimal_cost(uni) == cur_u,
          "%d vs %d" % (optimal_cost(uni), cur_u))

    skew = Counter({7: 1000, 0: 1, 1: 1, 2: 1})       # hottest table holds the priciest index
    cur_s = sum(c * _pc(v) for v, c in skew.items())
    check("C4 skewed calls DO save", optimal_cost(skew) < cur_s,
          "%d -> %d" % (cur_s, optimal_cost(skew)))
    check("C4 reassignment never costs more",
          optimal_cost(skew) <= cur_s and optimal_cost(uni) <= cur_u)

    empty = _Chains({}, w)
    check("C3 an empty run has nothing to divide by", empty.finish() == {} and empty.total == 0)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked13.fjm")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    return selftest() if a.selftest else report(a.fjm, a.frames, a.top)


if __name__ == "__main__":
    sys.exit(main())
