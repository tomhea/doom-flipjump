"""PR #93 round 8: every emitter mutant and neutral edit, through the scope rule AND the emitter itself.
A refusal is a meaningful catch only if the edit is a working emitter: this prints, per edit, the
rule's verdict and the range arguments the edited emitter really emits on the rooms (and whether
they are the head's -- the edits that would have bound as the head without the rule)."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests" / "fj")]
import test_slot_layouts_fj as t  # noqa: E402

fr = t.source("frame_render.fj")
params = t.def_params(fr)
used = ["viewwc", "buckets", "slotstride", "deg", "spn", "nld"]


def ranges(calls):
    out = set()
    for _room, _label, call in calls:
        args = [x.strip() for x in call[len("frame.thing_record_body "):].split(",")]
        b = dict(zip(params, args))
        out.add(tuple(b[p] for p in used))
    return sorted(out)


t0 = time.time()
head = ranges(t.emitted_calls(t.source(t.EMITTER)))
print("head: range arguments %s (%s) -- %.0f s" % (head, ", ".join(used), time.time() - t0))
for label, side, name, old, new in [m for m in t.MUTANTS + t.NEUTRAL if m[2] == t.EMITTER]:
    text = t._mutate(name, old, new)[name]
    try:
        t.scope_rule(text, params, used)
        rule = "accepted"
    except t.BindingRefused as e:
        rule = "REFUSED (%s)" % e
    t0 = time.time()
    try:
        got = ranges(t.emitted_calls(text))
        emitted = "%s%s" % (got, "  = the head's" if got == head else "")
    except RuntimeError as e:
        emitted = "the emitter did not run: %s" % str(e)[-120:]
    print("%-58s | rule: %s\n%-58s | emits: %s (%.0f s)" % (label, rule, "", emitted, time.time() - t0))
