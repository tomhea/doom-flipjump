"""M4 -- READS WIDER THAN THE SOURCE. The bug class that cost two gate cycles in one session.

TWICE in one day a `hex.mov`/`hex.read_byte` read more nibbles than the source register declares,
picked up whatever was declared next to it, and painted wrong pixels on a HANDFUL of frames:

  * `hex.mov 4, cbufa, u1bp` where `u1bp` was still `hex.vec 2`  -> 3 wrong frames of 260;
  * `hex.mov w/4, tmp, idx` where `idx` is a 2-nibble column     -> 4 wrong viewpoints.

Both are invisible to `deg_gate` most of the time, because the neighbouring declaration is USUALLY
zero. That is what makes the class worth a lint rather than more care.

It reads DECLARED widths out of a generated program (the parts are the real declarations) and flags
any `hex.<op> N, ..., <reg>` in src/fj where N exceeds the declaration. `w/4` counts as 8 (w=32).

    python scratchpad/m4_width_lint.py [--gen build/generated_doom_e1m1_menu_m4]

⚠⚠ A WHOLE-TREE RUN IS NOT A GATE, AND MEASURING IT SAID SO: it reports 10 sites and ALL TEN are
shipped, gated, correct code. Over-reading is a deliberate idiom here (R11: "reads w/4 nibbles of
its source") and its safety depends on the neighbouring cell being zero AT RUNTIME, which no static
tool can know. Do not wire it into a suite; it would cry wolf and then be ignored.

**USE `--regs`.** Scoped to the registers a width change actually touches, the noise disappears and
it answers the one question that matters: did I miss a site? That is precisely the check that would
have caught both of the bugs above.

⚠ IT IS A LINT, NOT A PROOF. It only knows registers the generated parts declare, it cannot see
macro parameters, and a read of exactly the declared width can still be wrong. It catches ONE
shape -- the one that has now bitten twice.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECL = re.compile(r"^\s*([A-Za-z_][\w]*)\s*:\s*hex\.vec\s+([\w/]+)")
# hex.<op> <n>, <a>, <b>  -- the reads whose width is explicit
OP = re.compile(r"hex\.(mov|cmp|scmp|read_byte|read_hex|write_byte|write_hex|if0|if1|zero|set)"
                r"\s+([\w/]+)\s*,\s*([A-Za-z_][\w]*)\s*(?:,\s*([A-Za-z_][\w]*))?")


CONSTS = {}          # filled from Config: PID_NIBBLES, SLOT_SHIFT, PIECE_BYTES


def width(tok):
    """Nibble count for a width token.

    ⚠ IT MUST RESOLVE THE fj CONSTANTS, or the tool silently SKIPS every op it should check. The
    first version returned None for `PID_NIBBLES` and duly reported "0 over-reads" for the pid
    registers -- while every one of their reads had just been rewritten to use that very constant.
    A check that passes because it looked at nothing is worse than no check."""
    if tok == "w/4":
        return 8
    if tok.isdigit():
        return int(tok)
    m = re.fullmatch(r"([A-Za-z_][\w]*)(?:\s*/\s*(\d+))?", tok)
    if m and m.group(1) in CONSTS:
        v = CONSTS[m.group(1)]
        return v // int(m.group(2)) if m.group(2) else v
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", default="build/generated_doom_e1m1_menu_m4")
    ap.add_argument("--pid-nibbles", type=int, default=4,
                    help="resolve PID_NIBBLES/SLOT_SHIFT/PIECE_BYTES at this width. Default 4 -- "
                         "the WIDE config is the one worth checking.")
    ap.add_argument("--regs", default="",
                    help="comma-separated registers to scope to. THIS IS THE USEFUL MODE: ask it "
                         "about the registers a width change touches and the noise disappears.")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from doomfj.config import Config
    cfg = Config(PID_NIBBLES=args.pid_nibbles)
    CONSTS.update(PID_NIBBLES=cfg.PID_NIBBLES, SLOT_SHIFT=cfg.SLOT_SHIFT,
                  PIECE_BYTES=cfg.PIECE_BYTES)
    print("constants resolved at PID_NIBBLES=%d: %s"
          % (cfg.PID_NIBBLES, ", ".join("%s=%d" % kv for kv in sorted(CONSTS.items()))))
    decls, order = {}, []      # order: declarations as they appear, per file
    gen = ROOT / args.gen
    if not gen.exists():
        print("no generated dir at %s -- build one first" % gen)
        return 2
    for f in sorted(gen.glob("*_0*.fj")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = DECL.match(line)
            if m:
                w = width(m.group(2))
                if w:
                    decls[m.group(1)] = w
                    order.append((m.group(1), w))
    print("declared registers found: %d  (from %s)" % (len(decls), gen.name))
    # ⚠ THE GENERATED DIR MUST HAVE BEEN BUILT AT THE WIDTH BEING CHECKED. Pointing a width-4
    # analysis at a width-2 emission flags EVERY pid read (47 of them) and every one is noise --
    # the third distinct way this tool found to mislead. It refuses instead.
    seen = decls.get("seg_pid")
    if seen is not None and seen != cfg.PID_NIBBLES:
        print("")
        print("!! REFUSING TO REPORT. %s declares `seg_pid: hex.vec %d`, but --pid-nibbles is %d."
              % (gen.name, seen, cfg.PID_NIBBLES))
        print("   Every width-%d read would flag against a width-%d declaration and all of it "
              "would be noise." % (cfg.PID_NIBBLES, seen))
        print("   Point --gen at an emission built at the SAME width, or pass --pid-nibbles %d."
              % seen)
        return 2

    scope = {x for x in args.regs.split(",") if x}
    nextof = {order[k][0]: order[k + 1][0] for k in range(len(order) - 1)}
    if scope:
        print("scoped to %d register(s): %s" % (len(scope), ", ".join(sorted(scope))))
    bad = 0
    for f in sorted((ROOT / "src" / "fj").glob("*.fj")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = re.sub(r"//.*", "", line)
            for m in OP.finditer(code):
                n = width(m.group(2))
                if n is None:
                    continue
                # WHICH OPERANDS THE WIDTH ACTUALLY APPLIES TO. Getting this wrong is most of
                # the noise: in `hex.read_hex 16, pos, pptr` the 16 is the DESTINATION width and
                # `pptr` is a w/4 pointer; in `hex.set 10, cpx, px` the second operand is a LITERAL.
                op = m.group(1)
                if op in ("mov", "cmp", "scmp"):
                    regs = (m.group(3), m.group(4))          # both operands are n wide
                elif op in ("zero", "if0", "if1"):
                    regs = (m.group(3),)
                elif op == "set":
                    regs = (m.group(3),)                     # the value is a literal
                elif op in ("read_byte", "read_hex"):
                    regs = (m.group(3),)                     # dst; the ptr is w/4
                elif op in ("write_byte", "write_hex"):
                    regs = (m.group(4),)                     # src; the ptr is w/4
                else:
                    regs = ()
                if op in ("read_byte", "write_byte"):
                    n = n * 2                                # n is BYTES here, not nibbles
                for reg in regs:
                    if scope and reg not in scope:
                        continue
                    if reg in decls and n > decls[reg]:
                        nxt = nextof.get(reg)
                        # OVER-READING IS A DELIBERATE IDIOM HERE (R11: "reads w/4 nibbles of its
                        # source"), and it is SAFE when what follows is zero. It is only dangerous
                        # when the over-read reaches into another LIVE cell -- which is exactly how
                        # `hex.mov 4, cbufa, u1bp` picked up `u2y1`. So report the neighbour and
                        # rank on it, rather than flagging every over-read as a bug.
                        if nxt is None:
                            continue
                        bad += 1
                        print("  !! %s:%d  reads %d of `%s` (declared %d) -> reaches `%s`"
                              % (f.name, i, n, reg, decls[reg], nxt))
                        print("       %s" % code.strip()[:96])
    print("")
    print("over-reads that reach a LIVE neighbouring cell: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
