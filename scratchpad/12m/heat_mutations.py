"""heat_mutations.py -- each mutation of flipjump#363's heat machinery must FAIL its pool tests.

    python scratchpad/12m/heat_mutations.py [<flipjump checkout on pin-heat>]

Mutates the checkout's flipjump/assembler/preprocessor.py in place, runs
tests/unit/test_table_pool.py, restores it byte-identically (asserted). M1-M3 are the escapes review
round 1 of tomhea/flipjump#363 found, M12-M15 the ones rounds 2 and 3 found.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\tomhe\Documents\flipjump-pr")
SRC = REPO / "flipjump" / "assembler" / "preprocessor.py"
UNIFORM_NEED = "        need = count + self.hot_ranks.get((group, slot_ops if self.width_buckets else 0), 0)\n"
CASES = [
    ("M1 every listed site takes rank 0 (review round 1)",
     "                rank = self.hot_ranks.get((group, width), 0)\n",
     "                rank = 0\n"),
    ("M2 the width-change check deleted (review round 1)",
     "        if listed is not None and listed[0] != width:\n",
     "        if False:\n"),
    ("M3 begin_relocation drops the site path (review round 1)",
     "        reserved = pool.reserve(ops_alignment, table_ops, group, group_expr, labels_prefix)\n",
     "        reserved = pool.reserve(ops_alignment, table_ops, group, group_expr)\n"),
    ("M4 occurrences never advance",
     "        self._hot_seen[(group, site)] = occurrence + 1\n",
     "        self._hot_seen[(group, site)] = occurrence\n"),
    ("M5 a hot width is sized without its reserved ranks (uniform)",
     UNIFORM_NEED,
     "        need = count\n"),
    ("M6 a hot width is sized without its reserved ranks (buckets)",
     "                need = count + self.hot_ranks.get((group, slot_ops), 0)",
     "                need = count"),
    ("M7 hot groups not placed first",
     "        order = [g for g in self.hot_sites if g in keep] + sorted(\n"
     "            (g for g in keep if g not in self.hot_sites), key=lambda g: (-bits[g], g)\n"
     "        )\n",
     "        order = sorted(keep, key=lambda g: (-bits[g], g))\n"),
    ("M8 a hot group is not always pinned",
     "(self.pin_broken or group in self.hot_sites or group not in self.broken_groups)",
     "(self.pin_broken or group not in self.broken_groups)"),
    ("M9 a lost hot group does not raise",
     "        if lost:\n",
     "        if False:\n"),
    ("M10 eviction may drop a hot group",
     "                evictable = keep - set(self.hot_sites)  # a hot group is never evicted\n",
     "                evictable = set(keep)\n"),
    ("M11 heat_key keeps stl coordinates",
     "_SITE_COORDINATES = re.compile(r'(?<![\\w.])[fs]\\d+:l\\d+:')",
     "_SITE_COORDINATES = re.compile(r'(?<![\\w.])[f]\\d+:l\\d+:')"),
    ("M12 a hot uniform width sized before the spread (round 1)",
     "        slots = 1 << max(0, (count - 1).bit_length())\n"
     "        if self.spread > 1 and count >= self.spread_min_count:\n"
     "            slots *= self.spread\n"
     "        # a hot group holds its reserved ranks too; bucket mode (whose group without a width\n"
     "        # histogram lands here) keys them by the slot width, uniform mode by 0\n"
     + UNIFORM_NEED +
     "        while slots < need:  # double only when they do not fit: a spread group has room\n"
     "            slots *= 2\n",
     UNIFORM_NEED +
     "        slots = 1 << max(0, (need - 1).bit_length())\n"
     "        if self.spread > 1 and count >= self.spread_min_count:\n"
     "            slots *= self.spread\n"),
    ("M13 a hot bucket sized before the spread (round 1; review round 2)",
     "                slots = (1 << max(0, (count - 1).bit_length())) * spread\n"
     "                need = count + self.hot_ranks.get((group, slot_ops), 0)  # a hot width holds its ranks too\n"
     "                while slots < need:  # double only when they do not fit: a spread width has room\n"
     "                    slots *= 2\n",
     "                need = count + self.hot_ranks.get((group, slot_ops), 0)\n"
     "                slots = (1 << max(0, (need - 1).bit_length())) * spread\n"),
    ("M14 eviction ignores the hole hot-first leaves (review round 2)",
     "                if not self.hot_sites:\n"
     "                    return rest\n",
     "                if True:\n"
     "                    return rest\n"),
    ("M15 a bucket group without a histogram keys its ranks by 0 (review round 2)",
     UNIFORM_NEED,
     "        need = count + self.hot_ranks.get((group, 0), 0)\n"),
]
TEST = [sys.executable, "-m", "pytest", "tests/unit/test_table_pool.py", "-q", "-p", "no:cacheprovider"]

print("# flipjump#363: each mutation must FAIL tests/unit/test_table_pool.py (mutated, run, restored)")
orig = SRC.read_bytes()
for name, a, b in CASES:
    text = orig.decode("utf-8")
    assert text.count(a) == 1, (name, text.count(a))
    try:
        SRC.write_bytes(text.replace(a, b).encode("utf-8"))
        r = subprocess.run(TEST, cwd=REPO, capture_output=True, text=True, timeout=900)
        failed = [line.split("::")[-1].split(" ")[0] for line in r.stdout.splitlines() if line.startswith("FAILED")]
        print("%-66s -> %s %s" % (name, r.stdout.strip().splitlines()[-1], failed[:3]), flush=True)
    finally:
        SRC.write_bytes(orig)
    assert SRC.read_bytes() == orig
r = subprocess.run(TEST, cwd=REPO, capture_output=True, text=True, timeout=900)
print("%-66s -> %s" % ("unmutated (restored, byte-identical)", r.stdout.strip().splitlines()[-1]))
