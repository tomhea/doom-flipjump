"""M4 size lever -- what a SHARED raw-byte emitter is worth, in WORDS not in characters.

`generate_bands_walk_fj` inlines `_raw_byte_out` (8 bits x 7 lines) into the CLAMP arm of every
band pair. MEASURED on the shipped emission: 40,567 clamp arms, and the rb_* label families are
58.3 MB of the 142.3 MB banks part. The block is byte-for-byte IDENTICAL every time -- it emits
`vq_hi`'s eight bits and nothing else -- so it can live ONCE and be reached by stl.fcall.

Characters are not the currency; SPAN-WORDS are. This assembles N copies of the inlined block and
N copies of the fcall replacement and reports words/copy for each, so the saving is a measurement
and not an inference from file size.

⚠⚠ THIS TOOL READS LOW, AND THAT IS NOW MEASURED. It predicted 281.1 words/arm => 11,401,761 words
=> 12.74% of the span. The real `game`-tier build came in at 15,403,444 => 17.21%, i.e. 379.7
words/arm -- 35% MORE. The same construct costs more inside a 90M-word program than in the 17k-word
one this assembles. **Treat the output as a FLOOR, never as a quotable figure**; a full build is the
only authority on span. It is still useful for the thing it is good at: comparing two SHAPES against
each other under identical conditions.

    python scratchpad/m4_rawbyte_cost.py [--n 200]
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                     # noqa: E402
from flipjump.fjm.fjm_reader import Reader                                # noqa: E402

from doomfj.config import Config                                          # noqa: E402
from doomfj.harness import W, FJM_LZMA_FAST                               # noqa: E402
from doomfj.lut_generator import _raw_byte_out                            # noqa: E402


def span(p):
    return max(s.segment_start + s.segment_length for s in Reader(p).memory_segments)


def build(tmp, name, body):
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    p = tmp / (name + ".fj")
    p.write_text("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n", encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), p.resolve()], out, memory_width=W, print_time=False,
                lzma_fast=FJM_LZMA_FAST)
    return span(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()
    n = args.n

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        head = ["vq_hi: bit.vec 8", "vpb_y: ;0", ";skip_all", "skip_all:"]
        base = build(tmp, "base", head + ["  ;done", "done: stl.loop"])

        # A: N inlined copies, exactly as generate_bands_walk_fj emits them today
        inl = list(head)
        for k in range(n):
            inl += ["c%d:" % k]
            inl += _raw_byte_out("vq_hi", "t%d_rb" % k)
            inl += ["    stl.output_char 7", "    ;fin%d" % k, "fin%d: stl.loop" % k]
        a = build(tmp, "inline", inl)

        # B: the same N arms calling ONE shared copy
        sh = list(head)
        sh += ["vpb_rb:"] + _raw_byte_out("vq_hi", "shared_rb") + ["    stl.fret vpb_y"]
        for k in range(n):
            sh += ["c%d:" % k,
                   "    stl.fcall vpb_rb, vpb_y",
                   "    stl.output_char 7", "    ;fin%d" % k, "fin%d: stl.loop" % k]
        b = build(tmp, "shared", sh)

        # C: share the WHOLE clamp tail per COLOUR. The tail is raw_byte_out + output_char c +
        # ";vpb_fin{k}", and every vpb_fin is the identical `stl.fret vpb_x` -- so a per-colour
        # block can fret directly and the per-pair arm collapses to ONE JUMP. 256 blocks total.
        cl = list(head) + ["vpb_x: ;0"]
        for c in range(256):
            cl += ["vpb_cl_%d:" % c] + _raw_byte_out("vq_hi", "clt%d" % c) + [
                "    stl.output_char %d" % c, "    stl.fret vpb_x"]
        for k in range(n):
            cl += ["c%d:" % k, "    ;vpb_cl_7"]
        cc = build(tmp, "colour", cl)
        # the 256 blocks are a fixed overhead, so price the ARM alone against a 0-arm build
        cl0 = [l for l in cl if not l.startswith("c") or not l[1:].split(":")[0].isdigit()]
        cl0 = list(head) + ["vpb_x: ;0"]
        for c in range(256):
            cl0 += ["vpb_cl_%d:" % c] + _raw_byte_out("vq_hi", "clt%d" % c) + [
                "    stl.output_char %d" % c, "    stl.fret vpb_x"]
        cc0 = build(tmp, "colour0", cl0)

    print("baseline span (startup + decls)      %10d" % base)
    print("N = %d" % n)
    print("inlined  total %10d   per copy %8.1f words" % (a, (a - base) / n))
    print("shared   total %10d   per copy %8.1f words" % (b, (b - base) / n))
    print("colour   total %10d   per arm  %8.1f words  (+%d fixed for 256 blocks)"
          % (cc, (cc - cc0) / n, cc0 - base))
    per = (a - b) / n
    perc = (a - base) / n - (cc - cc0) / n
    print("SAVING (fcall)  %8.1f words per clamp arm" % per)
    print("SAVING (colour) %8.1f words per clamp arm" % perc)
    per = perc
    print()
    arms = 40567          # MEASURED: grep -c "_rb_z0:" build/generated_menu/e1m1_06_banks.fj
    print("shipped E1M1 has %d clamp arms -> %s words (%.2f%% of the 89,494,606 span)"
          % (arms, format(int(per * arms), ","), 100 * per * arms / 89_494_606))
    print("!! THAT IS A FLOOR. The real build measured 15,403,444 words = 17.21% (379.7 words/arm)."
          " This harness under-reads by ~35%; see the module docstring.")


if __name__ == "__main__":
    main()
