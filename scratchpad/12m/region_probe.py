"""Which top-level REGION carries the hosted tier's ~97M inline ops? Attribute by label gaps.

resolve_macros() assigns an address to every label BEFORE labels_resolve (the wflip-chain pass
that overflows). So we hook labels_resolve, grab `labels`, and abort -- no need to run the doomed
resolution. Sorting top-level labels (single-component names) by address and diffing consecutive
gives the inline WORDS per region; the biggest gaps name where the ops live. Compare hosted vs
visual to see what the sim flags add.

    python scratchpad/12m/region_probe.py hosted
    python scratchpad/12m/region_probe.py visual
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import selfreset                                          # noqa: E402
from doomfj.build import build_wall_renderer                          # noqa: E402
import flipjump.assembler.assembler as asm                            # noqa: E402

tier = sys.argv[1] if len(sys.argv) > 1 else "hosted"
GRAB = {}
_real = asm.labels_resolve


class Done(Exception):
    pass


def _hook(ops, labels, memory_width, fjm_writer, **k):
    GRAB["labels"] = labels
    GRAB["mw"] = memory_width
    raise Done()


asm.labels_resolve = _hook
# hosted has no self_reset; make sure the reset path (if any) also aborts cheaply
selfreset.emit_reset_part = lambda *a, **k: (_ for _ in ()).throw(Done())

print("resolving macros for tier %r (abort before wflip-resolve) ..." % tier, flush=True)
try:
    build_wall_renderer(ROOT / "build/region_probe.fjm", tier=tier)
except Done:
    pass
except Exception as e:                                                # noqa: BLE001
    print("build raised %s: %s" % (type(e).__name__, str(e)[:80]), flush=True)

labels = GRAB.get("labels")
if not labels:
    print("no labels captured -- overflow happened before labels_resolve", flush=True)
    raise SystemExit(1)

mw = GRAB["mw"]


def addr_of(v):
    try:
        return int(v)
    except Exception:                                                 # noqa: BLE001
        try:
            return int(v.value)
        except Exception:                                             # noqa: BLE001
            return None


# top-level labels only (no macro-expansion "---" component)
tops = []
for name, v in labels.items():
    if "---" in str(name):
        continue
    a = addr_of(v)
    if a is not None:
        tops.append((a, str(name)))
tops.sort()
maxa = tops[-1][0] if tops else 0
print("top-level labels: %s ; max address %s bits = %s words (ceiling 134,217,728)"
      % (format(len(tops), ","), format(maxa, ","), format(maxa // mw, ",")), flush=True)
print("", flush=True)
gaps = [(tops[i + 1][0] - tops[i][0], tops[i][1], tops[i + 1][1]) for i in range(len(tops) - 1)]
gaps.sort(reverse=True)
print("%-16s %-40s %s" % ("words in region", "from top-level label", "-> next")),
print("-" * 90, flush=True)
for g, a, b in gaps[:20]:
    print("%-16s %-40s -> %s" % (format(g // mw, ","), a[:40], b[:40]), flush=True)
print("DONE", flush=True)
