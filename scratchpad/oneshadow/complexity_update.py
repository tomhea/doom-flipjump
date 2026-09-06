"""Rewrite the published stl complexity comments that the one-shadow setters invalidate.

Every affected formula is a sum of terms of the form w(A@+B). This file states the DECOMPOSITION
of each distinct w(...) group into named primitives, and refuses to rewrite a group unless the
decomposition reproduces the number the stl publishes today -- that check is the whole point,
because a rewritten complexity comment is a published contract and a wrong one is worse than a
stale one. Groups it cannot reproduce are reported and left alone.

The only primitives that move are the three pointer setters, which used to cost
    combined  time w(0.75@+5)   space w(0.75@+29)
    one-sided time w(0.5@+2)    space w(0.5@+14)
and now all cost
              time w(0.5@+4)    space w(0.5@+22)
because one k=3 xor writes to_flip, to_jump+w and the single shared shadow in two passes over the
pointer hexes instead of three, and the one-sided setters are aliases of it.

usage:  python complexity_update.py [--apply]      (default is a dry run)
"""

import re
import sys
from pathlib import Path

WORKTREE = Path(r"C:\Users\tomhe\Documents\flipjump-wide")
STL = WORKTREE / "flipjump" / "stl"

# --- primitives, as (A, B) in w(A@+B). Only the setters move. ------------------------------
SETUP_C_T, SETUP_C_S = (0.75, 5.0), (0.75, 29.0)     # old combined setter
SETUP_O_T, SETUP_O_S = (0.5, 2.0), (0.5, 14.0)       # old one-sided setter
SETUP_T, SETUP_S = (0.5, 4.0), (0.5, 22.0)           # both, now
PTRINC_S = (0.375, 3.25)                             # ptr_inc / ptr_dec space
PTRIDX_T, PTRIDX_S = (2.25, 5.25), (2.25, 40.0)      # ptr_index: pure arithmetic, no setter
WALK_T = WALK_S = (1.0, 3.0)                         # ptr_wflip minus its setter


def add(*terms, scale=1.0):
    return (sum(t[0] for t in terms) * scale, sum(t[1] for t in terms) * scale)


# (published_old, old_terms, new_terms, published_new)
GROUPS = [
    ("w(0.75@+ 5)", [SETUP_C_T], [SETUP_T], "w( 0.5@+ 4)"),
    ("w(0.75@+5)", [SETUP_C_T], [SETUP_T], "w( 0.5@+4)"),
    ("w(0.75@+29)", [SETUP_C_S], [SETUP_S], "w( 0.5@+22)"),
    ("w(0.5@+2)", [SETUP_O_T], [SETUP_T], "w(0.5@+4)"),
    ("w(0.5@+14)", [SETUP_O_S], [SETUP_S], "w(0.5@+22)"),
    ("w(1.13@+32)", [SETUP_C_S, PTRINC_S], [SETUP_S, PTRINC_S], "w(0.88@+25)"),
    ("w(0.9@+17)", [SETUP_O_S, PTRINC_S], [SETUP_S, PTRINC_S], "w(0.88@+25)"),
    ("w(3@+10.25)", [PTRIDX_T, SETUP_C_T], [PTRIDX_T, SETUP_T], "w(2.75@+9.25)"),
    ("w(3@+69)", [PTRIDX_S, SETUP_C_S], [PTRIDX_S, SETUP_S], "w(2.75@+62)"),
    ("w(  1.5@+ 5)", [SETUP_O_T, WALK_T], [SETUP_T, WALK_T], "w(  1.5@+ 7)"),
    ("w(1.5@+5)", [SETUP_O_T, WALK_T], [SETUP_T, WALK_T], "w(1.5@+7)"),
    ("w(1.5@+17)", [SETUP_O_S, WALK_S], [SETUP_S, WALK_S], "w(1.5@+25)"),
    ("w(2.25@+10)", [SETUP_C_T, SETUP_O_T, WALK_T], [SETUP_T, SETUP_T, WALK_T], "w(2@+11)"),
    ("w(2.62@+49)", [SETUP_C_S, SETUP_O_S, WALK_S, PTRINC_S],
     [SETUP_S, SETUP_S, WALK_S, PTRINC_S], "w(2.38@+50)"),
    ("w(2.625@+49)", [SETUP_C_S, SETUP_O_S, WALK_S, PTRINC_S],
     [SETUP_S, SETUP_S, WALK_S, PTRINC_S], "w(2.375@+50)"),
    ("w(1.875@+20)", [SETUP_O_S, WALK_S, PTRINC_S], [SETUP_S, WALK_S, PTRINC_S], "w(1.875@+28)"),
    ("w(2.375@+34)", [SETUP_O_S, SETUP_O_S, WALK_S, PTRINC_S],
     [SETUP_S, SETUP_S, WALK_S, PTRINC_S], "w(2.375@+50)"),
    ("w(2@+7)", [SETUP_O_T, SETUP_O_T, WALK_T], [SETUP_T, SETUP_T, WALK_T], "w(2@+11)"),
    ("w(0.38@+ 3)", [SETUP_C_T], [SETUP_T], "w(0.25@+ 2)"),      # push/pop n: half a push_byte
    ("w(0.56@+16)", [SETUP_C_S, PTRINC_S], [SETUP_S, PTRINC_S], "w(0.44@+13)"),
]
HALVED = {"w(0.38@+ 3)", "w(0.56@+16)"}   # these are per-element, i.e. half of a byte push/pop

# plain-text edits, each exactly -w/4 ops: one hex.vec w/4 shadow is gone from ptr_init.
PLAIN = [
    ("Space Complexity: 0.75w+261", "Space Complexity: 0.5w+261"),
    ("Complexity: 6725 + 2.75w+@ + n", "Complexity: 6725 + 2.5w+@ + n"),
    ("(7026 for w=64, 6894 for w=16)", "(7010 for w=64, 6890 for w=16)"),
]

FILES = [
    STL / "hex" / "pointers" / "basic_pointers.fj",
    STL / "hex" / "pointers" / "read_pointers.fj",
    STL / "hex" / "pointers" / "write_pointers.fj",
    STL / "hex" / "pointers" / "xor_from_pointer.fj",
    STL / "hex" / "pointers" / "xor_to_pointer.fj",
    STL / "hex" / "pointers" / "stack.fj",
    STL / "ptrlib.fj",
    STL / "runlib.fj",
]


def parse(text):
    """w( A @+ B ) -> (A, B)."""
    m = re.fullmatch(r"w\(\s*([0-9.]+)@\+\s*([0-9.]+)\)", text)
    if not m:
        raise ValueError("cannot parse " + repr(text))
    return float(m.group(1)), float(m.group(2))


def selfcheck():
    """every decomposition must reproduce what the stl publishes today. Returns problem list."""
    problems = []
    for old_text, old_terms, new_terms, new_text in GROUPS:
        scale = 0.5 if old_text in HALVED else 1.0
        want_a, want_b = parse(old_text)
        got_a, got_b = add(*old_terms, scale=scale)
        # published values are rounded to 1-2 decimals (A) and to whole ops (B).
        if abs(got_a - want_a) > 0.051 or abs(got_b - want_b) > 0.55:
            problems.append("%-14s decomposes to w(%g@+%g), published w(%g@+%g)"
                            % (old_text, got_a, got_b, want_a, want_b))
            continue
        want_a, want_b = parse(new_text)
        got_a, got_b = add(*new_terms, scale=scale)
        if abs(got_a - want_a) > 0.051 or abs(got_b - want_b) > 0.55:
            problems.append("%-14s NEW text w(%g@+%g) does not match computed w(%g@+%g)"
                            % (old_text, want_a, want_b, got_a, got_b))
    return problems


def main():
    apply = "--apply" in sys.argv
    problems = selfcheck()
    print("SELF-CHECK of %d decompositions against the published stl:" % len(GROUPS))
    if problems:
        print("  FAILED:")
        for p in problems:
            print("    " + p)
        print("Refusing to rewrite anything.")
        return 1
    print("  all %d reproduce the current published value; rewriting is derived, not guessed."
          % len(GROUPS))

    # one pass, longest pattern first: w(0.5@+2) is a prefix of the w(0.5@+22) we write.
    table = {old: new for old, _, _, new in GROUPS}
    table.update(dict(PLAIN))
    pattern = re.compile("|".join(re.escape(k) for k in sorted(table, key=len, reverse=True)))

    total = 0
    for path in FILES:
        text = path.read_text()
        out, changed = [], 0
        for i, line in enumerate(text.split(chr(10)), 1):
            new_line = pattern.sub(lambda m: table[m.group(0)], line)
            if new_line != line:
                changed += 1
                print("  %s:%d" % (path.name, i))
                print("      - " + line.strip())
                print("      + " + new_line.strip())
            out.append(new_line)
        if changed and apply:
            path.write_text(chr(10).join(out))
        total += changed
    print()
    print("%d lines %s" % (total, "rewritten" if apply else "would change (dry run; pass --apply)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
