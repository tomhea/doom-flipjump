"""M4-D1 -- the LABEL COLLISION surface of putting a second level in the same image.

fj top-level labels are GLOBAL. Three levels in one image means three emissions concatenated, so
every map-specific label the emitter writes must either already carry the map's name or be renamed.
This counts them, split by whether they are already prefixed.

!! THE FIRST VERSION OF THIS SCAN ANCHORED AT COLUMN 0 and reported 102 labels. Per-seg blocks are
INDENTED (`  seg6_geom_consts:`), so it missed the entire per-seg and per-subsector population --
i.e. it missed almost exactly the thing it was written to count. Leading whitespace is allowed now.

    python scratchpad/m4_labels.py [--gen build/generated_std] [--map e1m1]
"""
import argparse
import collections
import re
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--gen", default="build/generated_std")
ap.add_argument("--map", default="e1m1")
args = ap.parse_args()

LABEL = re.compile(r"^\s*([A-Za-z_][\w]*)\s*:(?!\s*hex\.vec|\s*bit\.vec)")
labels = []
for f in sorted(Path(args.gen).glob("%s_0*.fj" % args.map)):
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LABEL.match(line)
        if m:
            labels.append(m.group(1))

pref = [l for l in labels if l.lower().startswith(args.map)]
rest = [l for l in labels if not l.lower().startswith(args.map)]
# the bands-as-code walk is indexed by half-list ID, not by map: three levels share ONE walk with
# more ids, so these merge rather than collide.
bank = [l for l in rest if l.startswith(("vpb_", "vql_", "vqh_"))]
rest = [l for l in rest if not l.startswith(("vpb_", "vql_", "vqh_"))]

print("labels emitted for %s: %d" % (args.map.upper(), len(labels)))
print("  already map-prefixed (%s_*) ........ %8d" % (args.map, len(pref)))
print("  bands-as-code bank (vpb_/vql_/vqh_)  %8d   <- ID-indexed, merges rather than collides"
      % len(bank))
print("  everything else .................... %8d" % len(rest))
print("")

fam = collections.Counter(re.sub(r"\d+", "#", l) for l in rest)
mapish = {n: c for n, c in fam.items() if "#" in n and c > 8}
shared = {n: c for n, c in fam.items() if n not in mapish}
print("  MAP-SPECIFIC families -- these are what a second level collides with:")
for n, c in sorted(mapish.items(), key=lambda kv: -kv[1])[:16]:
    print("     %-38s %8d" % (n, c))
print("     ... %d families, %d labels in total" % (len(mapish), sum(mapish.values())))
print("")
print("  shared registers/leaves (one per PROGRAM, not per map): %d labels in %d families"
      % (sum(shared.values()), len(shared)))
print("")
print("  => THE M4 RENAME SURFACE IS %d LABELS in %d families." % (sum(mapish.values()), len(mapish)))
print("     (%d are already prefixed and need nothing.)" % len(pref))
