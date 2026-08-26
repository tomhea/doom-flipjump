"""M4 — give one map's generated labels a private namespace, so several can share an image.

fj top-level labels are GLOBAL. Three levels in one image is three emissions concatenated, and
16,412 of E1M1's labels are map-specific names that a second level would collide with
(`scratchpad/m4_labels.py` counts them against the shipped emission).

WHY A POST-EMIT RENAME AND NOT 22 f-STRINGS. Rule 4 freezes the emitter ABI: generated global
labels are not refactorable by rename, and `scratchpad/cr/alpha_check.py` enforces exactly that.
Renaming after emission keeps the emitter untouched, makes the change OPT-IN BY CONSTRUCTION -- no
prefix, no substitution, byte-identical text -- and puts the whole thing in one auditable function
instead of scattered through the emitter.

WHAT IS AND IS NOT RENAMED

  renamed      the 17 map-specific families below: per-subsector, per-seg, per-thing, the baked
               point-location walk, and the bbox-gate arms. All are `<word><digits>` names the
               emitter generates, and NOTHING in `src/fj/` refers to one (checked).
  NOT renamed  * shared registers and leaves (`seg_pid`, `seg_pass1_leaf`, `ptloc_walk`,
                 `ptloc_ret`, ...): one per PROGRAM, and `src/fj/sim.fj` externs some by name.
                 None carries a digit where these patterns want one.
               * `vpb_*` / `vql_*` / `vqh_*`: the bands-as-code bank is indexed by half-list ID,
                 so several maps MERGE into one walk rather than colliding (and M2 rung 1 lifted
                 the id cap that used to make that impossible).
               * anything already carrying the map's name (`e1m1_bspcode_node...`): 6,135 labels
                 the emitter prefixes itself, via `_pfx(mapname)`.
               * macro-LOCALS. A label inside a generated `def ... { }` is one cell per expansion,
                 named by the assembler, and cannot collide. An earlier version of the counting
                 tool missed this and invented five families (`e#`, `l#`, `n#`, `t#`, `d#_#`).

⚠ THE PROOF IS A BUILD, NOT THIS FILE. A prefixed SINGLE-map build must render byte-exact against
the unprefixed one. Until that has run, this is a plausible transformation and nothing more.
"""
from __future__ import annotations

import re

# the 17 families, as five patterns. Each is anchored on a word boundary so a longer name that
# merely starts the same way is left alone.
FAMILIES = (
    r"ss\d+_\w+",              # ss#_visit, ss#_occluded, ss#_seg#_mark/_marked/_unseen,
                               # ss#_thing#_do/_skip
    r"seg\d+_\w+",             # seg#_geom_consts, _render_consts, _attrib_consts, _face_consts
    r"ptloc_[a-z]\d+",         # the baked point-location walk's arms
    r"thing\d+_\d+_consts",    # a baked thing's constant block
    r"bb(?:miss|go)\d+",       # the bbox-gate arms
)
_TOKEN = re.compile(r"\b(?:%s)\b" % "|".join(FAMILIES))


def apply(text: str, prefix: str) -> str:
    """Prefix every map-specific generated label in `text`.

    An empty prefix is the IDENTITY -- that is what makes single-level emission byte-identical and
    every existing certification transfer without re-running."""
    if not prefix:
        return text
    return _TOKEN.sub(lambda m: prefix + m.group(0), text)


def count(text: str) -> int:
    """How many tokens `apply` would touch -- for the build to report, and for a caller to assert
    on rather than trust."""
    return len(_TOKEN.findall(text))


def selftest() -> int:
    """R9. Each control breaks the rename the way a plausible mistake would."""
    ok = True

    sample = "\n".join([
        "ss12_visit:", "    stl.fcall seg7_geom_consts, seg_ret",
        "    ;ss12_seg3_mark", "ss12_seg3_marked:", "    ;bbmiss4",
        "thing9_2_consts:", "ptloc_l17:", "    ;ptloc_walk", "seg_pid: hex.vec 2",
        "    hex.set 2, seg_pid, 3", "e1m1_bspcode_node8:", "vpb_t900:",
    ])

    identity = apply(sample, "") == sample
    print("P1 an empty prefix is the identity ............ %s" % ("ok" if identity else "!! NO"))
    ok &= identity

    out = apply(sample, "m2_")
    renamed = count(sample)
    expect = ["m2_ss12_visit", "m2_seg7_geom_consts", "m2_ss12_seg3_mark", "m2_ss12_seg3_marked",
              "m2_bbmiss4", "m2_thing9_2_consts", "m2_ptloc_l17"]
    got_all = all(e in out for e in expect)
    print("P2 all %d map-specific tokens renamed ......... %s"
          % (renamed, "ok" if got_all and renamed == len(expect) else "!! MISMATCH"))
    ok &= got_all and renamed == len(expect)

    # C1: the shared names must survive untouched, or sim.fj's externs stop resolving.
    keep = ["ptloc_walk", "seg_pid", "vpb_t900", "e1m1_bspcode_node8"]
    survived = all(("m2_" + k) not in out for k in keep)
    print("C1 shared/extern/bank names untouched ........ %s"
          % ("ok" if survived else "!! RENAMED SOMETHING SHARED"))
    ok &= survived

    # C2: a definition and its use must move TOGETHER. Renaming one and not the other is the
    # failure that would assemble and then jump into the wrong map.
    pairs = out.count("m2_ss12_seg3_mark")     # the ;use and the :def of the _marked twin
    together = out.count("m2_seg7_geom_consts") == 1 and pairs == 2
    print("C2 definitions and uses move together ........ %s"
          % ("ok" if together else "!! SPLIT"))
    ok &= together

    # C3: two prefixes must not collide -- the whole point.
    a, b = apply(sample, "m1_"), apply(sample, "m2_")
    disjoint = not (set(re.findall(r"\bm1_\w+", a)) & set(re.findall(r"\bm2_\w+", b)))
    print("C3 two prefixes produce disjoint names ....... %s" % ("ok" if disjoint else "!! COLLIDE"))
    ok &= disjoint

    # C4: applying twice must be a NO-OP, not a double prefix. `` sits between two word
    # characters in `m2_ss12_visit`, so an already-prefixed name no longer matches -- which is the
    # safe outcome, and worth pinning because it is what makes a re-run of the build harmless.
    # (This control was first written backwards, asserting that a second pass must CHANGE
    # something. It fired, correctly, on behaviour that was right.)
    twice = apply(apply(sample, "m2_"), "m2_")
    print("C4 applying it twice is a no-op .............. %s"
          % ("ok" if twice == out else "!! DOUBLE-PREFIXED"))
    ok &= twice == out
    ok &= "m2_m2_" not in twice

    print("SELFTEST: %s" % ("PASS" if ok else "!! FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
