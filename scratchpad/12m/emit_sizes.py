"""Emit-only: which PART of a tier carries its size? No assembly, so it is the cheap first look.

The generated program is emitted as ordered, named parts (`emit_wall_renderer(..., return_parts=
True)`), and their sizes differ by four orders of magnitude -- `main` is ~55 lines while `banks` is
millions. This reports each part's lines and chars so the oversized region is NAMED before anyone
pays for an assembly.

Reference, P9-1's ritual-logged part LINE counts (visual tier + S2): entry 32, tables 338,599,
main 68, segconsts 44,419, walk 73,942, state 437, banks 2,137,148.

    python scratchpad/12m/emit_sizes.py hosted-loop
    python scratchpad/12m/emit_sizes.py --selftest
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def normalise(parts):
    """the emitter returns an ordered list of (name, text) or a dict -- yield (name, text) either
    way, and NEVER silently stringify an object into a size."""
    if hasattr(parts, "items"):
        items = list(parts.items())
    else:
        items = []
        for i, p in enumerate(parts):
            if isinstance(p, tuple) and len(p) == 2:
                items.append(p)                       # an ordered (name, text) pair
            else:
                items.append((getattr(p, "name", str(i)), p))
    out = []
    for name, text in items:
        if not isinstance(text, str):
            text = getattr(text, "text", None)
            if text is None:
                raise TypeError("part %r is neither a str nor has .text -- refusing to measure "
                                "repr() as if it were the emitted program" % (name,))
        out.append((str(name), text))
    return out


def measure(parts):
    """[(name, lines, chars)] in emission order -- ORDER IS THE CONTRACT, never sort these"""
    return [(n, t.count("\n"), len(t)) for n, t in normalise(parts)]


def report(rows):
    print("%-22s %14s %16s" % ("part", "lines", "chars (~bytes)"), flush=True)
    print("-" * 56, flush=True)
    tot_l = tot_c = 0
    for name, lines, chars in rows:
        tot_l += lines
        tot_c += chars
        print("%-22s %14s %16s" % (name[:22], format(lines, ","), format(chars, ",")), flush=True)
    print("-" * 56, flush=True)
    print("%-22s %14s %16s" % ("TOTAL", format(tot_l, ","), format(tot_c, ",")), flush=True)
    return tot_l, tot_c


def run(tier):
    from doomfj.build import DEFAULT_WAD, DEFAULT_SPRITE_WAD, _resolve_sprite_wad
    from doomfj.config import Config
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import emit_wall_renderer, tier_flags

    print("emitting tier %r ..." % tier, flush=True)
    wad = WadFile.from_path(DEFAULT_WAD)
    spr = _resolve_sprite_wad(wad, DEFAULT_SPRITE_WAD) if tier_flags(tier)["things"] else None
    parts = emit_wall_renderer(wad, "E1M1", Config(), sprite_wad=spr, tier=tier,
                               return_parts=True)
    rows = measure(parts)
    report(rows)
    print("DONE", flush=True)
    return rows


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

    print("emit_sizes selftest -- it must count the PROGRAM, not its repr()", flush=True)

    # C1 exact counts, both container shapes, and ORDER PRESERVED
    listed = [("a", "x\ny\n"), ("b", "z\n")]
    check("C1 lines and chars are exact", measure(listed) == [("a", 2, 4), ("b", 1, 2)],
          "got %s" % (measure(listed),))
    check("C1 a dict gives the same answer", measure(dict(listed)) == measure(listed))
    check("C1 emission ORDER is preserved (it is the contract)",
          [n for n, _l, _c in measure(listed)] == ["a", "b"])

    # C2 an object carrying .text is read, not stringified
    class Part:
        name, text = "banks", "q\nw\ne\n"

    check("C2 a .text part is measured by its text", measure([Part()]) == [("banks", 3, 6)],
          "got %s" % (measure([Part()]),))

    # C3  THE VACUITY CONTROL, and the reason this file has a selftest at all. The old code did
    #     `text = getattr(text, "text", str(text))` -- so a part object with no `.text` was
    #     measured by its repr(), reporting a ~60-char size for a multi-megabyte program part.
    class Opaque:
        name = "banks"

    try:
        measure([Opaque()])
        check("C3 a part with no .text is REJECTED, not measured as its repr()", False,
              "it returned a size!")
    except TypeError as e:
        check("C3 a part with no .text is REJECTED, not measured as its repr()",
              "repr()" in str(e))
    # ... and the control that this is not merely strict: the OLD expression, run here, silently
    # produces a size. That is the mutation this check rejects.
    old_expression = getattr(Opaque(), "text", str(Opaque()))
    check("C3 the OLD `getattr(t, 'text', str(t))` silently sizes a part it cannot read",
          isinstance(old_expression, str) and len(old_expression) < 200,
          "it would have reported %d chars for a multi-megabyte part" % len(old_expression))

    # C4 empty parts total zero rather than raising
    check("C4 an empty part list totals nothing", measure([]) == [])

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    run(sys.argv[1] if len(sys.argv) > 1 else "hosted-loop")
