"""WHERE are a tier's words? Attribute them to top-level regions by label-address gaps.

`resolve_macros()` assigns an address to every label BEFORE `labels_resolve` (the wflip-chain pass
that overflows on an oversized tier). So we hook `labels_resolve`, grab `labels`, and abort -- no
need to run the doomed resolution. Sorting the TOP-LEVEL labels (names with no `---`
macro-expansion component) by address and diffing consecutive ones gives the inline words per
region; the biggest gaps name where the size lives.

This is what named the four ~2.16M-word collision bodies (`cm{a,b,c,h}_vyd`).

    python scratchpad/12m/region_probe.py hosted
    python scratchpad/12m/region_probe.py --selftest
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad" / "12m"):
    sys.path.insert(0, str(q))

from fjmsize import ceiling_words                                     # noqa: E402


def addr_of(v):
    """labels map to ints or to objects with `.value`; anything else is not an address"""
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(v.value)
        except (AttributeError, TypeError, ValueError):
            return None


def top_level(labels):
    """(address, name) for labels with no macro-expansion component, sorted by address"""
    tops = []
    for name, v in labels.items():
        if "---" in str(name):
            continue
        a = addr_of(v)
        if a is not None:
            tops.append((a, str(name)))
    tops.sort()
    return tops


def regions(labels, memory_width):
    """[(words, from_label, to_label)] largest first -- the inline size of each top-level region"""
    tops = top_level(labels)
    gaps = [((tops[i + 1][0] - tops[i][0]) // memory_width, tops[i][1], tops[i + 1][1])
            for i in range(len(tops) - 1)]
    gaps.sort(reverse=True)
    return gaps


def run(tier):
    from doomfj import selfreset
    from doomfj.build import build_wall_renderer
    import flipjump.assembler.assembler as asm

    grab = {}
    real = asm.labels_resolve

    class Done(Exception):
        pass

    def hook(ops, labels, memory_width, fjm_writer, **k):
        grab["labels"], grab["mw"] = labels, memory_width
        raise Done()

    asm.labels_resolve = hook
    real_emit = selfreset.emit_reset_part
    selfreset.emit_reset_part = lambda *a, **k: (_ for _ in ()).throw(Done())
    print("resolving macros for tier %r (abort before wflip-resolve) ..." % tier, flush=True)
    try:
        build_wall_renderer(ROOT / "build/region_probe.fjm", tier=tier)
    except Done:
        pass
    except Exception as e:                                            # noqa: BLE001
        print("build raised %s: %s" % (type(e).__name__, str(e)[:100]), flush=True)
    finally:
        asm.labels_resolve = real
        selfreset.emit_reset_part = real_emit

    labels = grab.get("labels")
    if not labels:
        # ⚠ NOT an empty table. A run that captured nothing must say so: printing "no regions"
        # next to a total of 0 reads as "this tier is tiny".
        print("NO LABELS CAPTURED -- the build failed before labels_resolve, so this run proves "
              "nothing about where the words are.", flush=True)
        return None

    mw = grab["mw"]
    tops = top_level(labels)
    maxa = tops[-1][0] if tops else 0
    print("top-level labels: %s ; max address %s bits = %s words (ceiling %s at w=%d)"
          % (format(len(tops), ","), format(maxa, ","), format(maxa // mw, ","),
             format(ceiling_words(mw), ","), mw), flush=True)
    print("", flush=True)
    print("%-16s %-40s %s" % ("words in region", "from top-level label", "-> next"), flush=True)
    print("-" * 90, flush=True)
    for g, a, b in regions(labels, mw)[:20]:
        print("%-16s %-40s -> %s" % (format(g, ","), a[:40], b[:40]), flush=True)
    print("DONE", flush=True)
    return regions(labels, mw)


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

    print("region_probe selftest -- the attribution must be arithmetic, not vibes", flush=True)

    class Val:
        def __init__(self, v):
            self.value = v

    # a synthetic label map with KNOWN gaps: 32 bits/word, so 3200 bits = 100 words
    labels = {
        "aaa": 0,                       # -> bbb : 3200 bits = 100 words
        "bbb": Val(3200),               # -> ccc : 6400 bits = 200 words   (the biggest)
        "ccc": 9600,                    # -> ddd : 1600 bits =  50 words
        "ddd": Val(11200),
        "bbb---inner---x": 5000,        # a macro expansion: must be IGNORED
        "ccc---deep": 9601,
        "not_an_address": object(),     # must be skipped, not crash
    }
    r = regions(labels, 32)
    check("C1 macro-expansion labels are excluded", len(top_level(labels)) == 4,
          "%d top-level of %d" % (len(top_level(labels)), len(labels)))
    check("C1 an unaddressable value is skipped, not fatal",
          "not_an_address" not in [n for _a, n in top_level(labels)])
    check("C2 the gaps are exact and sorted largest-first",
          r == [(200, "bbb", "ccc"), (100, "aaa", "bbb"), (50, "ccc", "ddd")], "got %s" % (r,))
    check("C3 `.value` objects are read the same as bare ints",
          addr_of(Val(3200)) == addr_of(3200) == 3200)

    # C4  THE WIDTH CONTROL. The same bit gaps are HALF as many words at w=64.
    r64 = regions(labels, 64)
    check("C4 words derive from memory_width, not a hardcoded 32",
          [g for g, _a, _b in r64] == [100, 50, 25],
          "w32=%s w64=%s" % ([g for g, _a, _b in r], [g for g, _a, _b in r64]))

    # C5  VACUITY. No labels must not look like a small tier.
    check("C5 an empty label map yields no regions (and run() says NO LABELS CAPTURED)",
          regions({}, 32) == [])
    check("C5 a single label yields no regions (nothing to diff)",
          regions({"only": 0}, 32) == [])

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else "hosted") is not None else 1)
