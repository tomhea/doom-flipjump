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


class Done(Exception):
    """raised by the hook to abort the build once the labels are in hand"""


def install_label_hook(grab, stop=True):
    """wrap `asm.labels_resolve` so the resolved labels are captured; returns the uninstaller.

    Extracted so the selftest can fire it against a REAL assembly. CR-2026-09-06: every control in
    this file ran on a synthetic dict, so nothing checked the one thing the tool actually does --
    and a hook that silently stopped firing would report "NO LABELS CAPTURED" forever while looking
    like a tool that works.
    """
    import flipjump.assembler.assembler as asm
    real = asm.labels_resolve

    def hook(ops, labels, memory_width, fjm_writer, **k):
        grab["labels"], grab["mw"] = labels, memory_width
        if stop:
            raise Done()
        return real(ops, labels, memory_width, fjm_writer, **k)

    asm.labels_resolve = hook
    return lambda: setattr(asm, "labels_resolve", real)


def run(tier):
    from doomfj import selfreset
    from doomfj.build import build_wall_renderer

    grab = {}
    uninstall = install_label_hook(grab)
    real_emit = selfreset.emit_reset_part
    selfreset.emit_reset_part = lambda *a, **k: (_ for _ in ()).throw(Done())
    print("resolving macros for tier %r (abort before wflip-resolve) ..." % tier, flush=True)
    try:
        build_wall_renderer(ROOT / "build/region_probe.fjm", tier=tier)
    except Exception as e:                                            # noqa: BLE001
        # ⚠ NOT `except Done`. The assembler catches everything and re-raises it as
        # FlipJumpAssemblerException("Unknown exception ... please report this bug"), so our own
        # abort never arrives as itself. The signal that the hook worked is the GRAB, not the
        # exception type -- which is why only an uncaptured grab is worth reporting.
        if not grab.get("labels"):
            print("build raised %s: %s" % (type(e).__name__, str(e)[:100]), flush=True)
    finally:
        uninstall()
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
    check("C5 an empty label map yields no regions",
          regions({}, 32) == [])
    check("C5 a single label yields no regions (nothing to diff)",
          regions({"only": 0}, 32) == [])

    # C6  THE HOOK CONTROL, against the REAL assembler -- the pattern overflow_probe C4 uses and
    #     that this file was missing. Everything above runs on a synthetic dict, so none of it
    #     would notice if `labels_resolve` were renamed and the hook silently stopped firing.
    import tempfile
    import flipjump as fj
    TINY = chr(10).join(["stl.startup_and_init_all", "    stl.loop", ""])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "tiny.fj"
        src.write_text(TINY, encoding="utf-8")

        grab = {}
        un = install_label_hook(grab)
        try:
            fj.assemble([src], tmp / "tiny.fjm", memory_width=32, print_time=False)
        except Exception:                                             # noqa: BLE001
            pass          # the assembler re-wraps our Done; the grab is the signal, not the type
        finally:
            un()
        check("C6 the hook FIRES on a real assembly", "labels" in grab)
        check("C6 it captures real labels, and the width with them",
              len(grab.get("labels", {})) > 0 and grab.get("mw") == 32,
              "%s labels at w=%s" % (format(len(grab.get("labels", {})), ","), grab.get("mw")))
        check("C6 those real labels attribute into regions",
              len(regions(grab.get("labels", {}), grab.get("mw", 32))) > 0,
              "%d regions" % len(regions(grab.get("labels", {}), grab.get("mw", 32))))

        # ... and uninstall must really uninstall. Install into a SECOND dict, remove the hook,
        # then assemble again: if the uninstaller did not restore `labels_resolve`, this dict
        # fills and the build aborts. (Checking an untouched dict is falsy would prove nothing.)
        after = {}
        un2 = install_label_hook(after)
        un2()
        raised = None
        try:
            fj.assemble([src], tmp / "tiny2.fjm", memory_width=32, print_time=False)
        except Exception as e:                                        # noqa: BLE001
            raised = type(e).__name__
        check("C6 uninstall really uninstalls (a later build is untouched)",
              not after and raised is None,
              "captured %d labels, raised=%s" % (len(after), raised))


    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else "hosted") is not None else 1)
