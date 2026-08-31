"""M4-R1 -- the geometry-only emission, GATED WITHOUT A BUILD.

R1 asks: can maps 2..N contribute ONLY their `segconsts` + `walk` parts, prefixed, and be
concatenated into one image? That is decidable from LABEL SETS alone -- fj top-level labels are
global, so the ordered parts are equivalent to their concatenation, and the question is exactly
"do two prefixed geometry emissions collide, and do they reference anything that is not shared?"

WHY NO NEW EMITTER MODE. A geometry-only emission is a PROJECTION of the normal one: take the
`segconsts` and `walk` parts and drop the rest. That is the same text a dedicated tier would emit,
it needs no change to a 2,957-line emitter, and it cannot drift from what actually ships.

⚠ ONLY THREE MAPS EMIT TODAY (E1M1, E1M5, E1M8) -- the rest hit the pid byte or the thing cap; see
docs/handoff-m4-phase-a.md. Three is enough to gate the machinery.

CONTROLS (R9), because a disjointness check that trivially passes is worse than none:
  * NEGATIVE: the SAME two maps UNPREFIXED must COLLIDE. If they do not, disjointness proves
    nothing and the run fails.
  * REFERENCE: every name a geometry part USES but does not DEFINE must be in the shared set the
    full emission defines, or a concatenated image would not link.

    python scratchpad/m4_r1_labels.py [--maps E1M1,E1M5,E1M8]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import mapprefix                                              # noqa: E402
from doomfj.build import _resolve_sprite_wad, DEFAULT_SPRITE_WAD          # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer                       # noqa: E402

CACHE = ROOT / "scratchpad" / "_m4_r1"
GEOM = ("segconsts", "walk")
# a label DEFINITION at depth 0. Labels inside a generated `def ... { }` are macro-LOCALS, named by
# the assembler per expansion, and cannot collide between maps -- m4_labels.py learned that the
# hard way (five bogus families, 368 labels).
# ⚠ NO `(?!hex.vec|bit.vec)` LOOKAHEAD, unlike m4_labels.py. That tool counts CODE labels; this one
# asks "is this name defined anywhere", and `foo: hex.vec 2` defines `foo` just as much as a code
# label does. With the lookahead every register declaration was missing from the defined set and
# check 4 called 156 of them unresolved.
LABEL = re.compile(r"^\s*([A-Za-z_][\w]*)\s*:")
DEF = re.compile(r"^\s*def\s")
USE = re.compile(r"[A-Za-z_][\w]*")


DEFNAME = re.compile(r"^\s*def\s+([A-Za-z_][\w]*)")


def defined(text):
    """Every name this text DEFINES at depth 0: labels, declarations, and MACRO NAMES.

    ⚠ The macro names matter and were missed at first. `generate_state_switch_fj` emits a
    `def <name>_go` per door-touching seg (M2), so the walk part both defines and calls ~thousands
    of `dsw_seg####_*_go` macros. Without them check 4 called every one unresolved."""
    out, depth = set(), 0
    for line in text.splitlines():
        if DEF.match(line):
            m = DEFNAME.match(line)
            if m and depth == 0:
                out.add(m.group(1))
            depth += line.count("{") - line.count("}")
            continue
        if depth:
            depth += line.count("{") - line.count("}")
            continue
        m = LABEL.match(line)
        if m:
            out.add(m.group(1))
    return out


def used(text):
    """Every bare identifier this text REFERENCES.

    ⚠ Dotted paths are dropped. `hex.tables.clean_table_entry__table` is a namespaced macro the
    assembler resolves through `ns`, not a top-level label -- counting its segments as free names
    is how `clean_table_entry__table` kept showing up as unresolved."""
    out = set()
    for line in text.splitlines():
        line = re.sub(r"//.*", "", line)
        line = re.sub(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+", " ", line)
        out.update(USE.findall(line))
    return out


def from_dir(m, d):
    """Take the parts from a generated directory instead of re-emitting. The .fj files ARE the
    emitted parts (write_program_files writes them verbatim), so this is the same text for free --
    and it lets the analysis be validated in seconds before an emission is spent on it.
    ⚠ A built directory also holds `07_reset`, which a live emission does not; that only ever adds
    to `all_def`, which the checks use as a superset."""
    d = Path(d)
    geom, allt = [], []
    for f in sorted(d.glob("*_0*.fj")):
        name = f.stem.split("_", 2)[2]
        t = f.read_text(encoding="utf-8", errors="replace")
        allt.append(t)
        if name in GEOM:
            geom.append(t)
    assert len(geom) == len(GEOM), sorted(f.name for f in d.glob("*_0*.fj"))
    return {"map": m, "secs": 0.0, "src": str(d),
            "geom_def": sorted(defined("\n".join(geom))),
            "geom_use": sorted(used("\n".join(geom))),
            "all_def": sorted(defined("\n".join(allt)))}


def emit(wad, m, cfg, spr):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / ("%s.json" % m)
    if f.exists():
        return json.loads(f.read_text())
    t = time.perf_counter()
    # !! `parts` is a SEQUENCE OF (name, text) PAIRS, not a dict -- write_program_files iterates
    # `for i, (name, text) in enumerate(parts)` and that ORDER is the contract. Treating it as a
    # dict is an AttributeError eleven minutes into an emission.
    parts = list(emit_wall_renderer(wad, m, cfg, sprite_wad=spr, tier="game", return_parts=True))
    names = [n for n, _t in parts]
    assert set(GEOM) <= set(names), (GEOM, names)
    geom = "\n".join(t for n, t in parts if n in GEOM)
    allt = "\n".join(t for _n, t in parts)
    rec = {"map": m, "secs": round(time.perf_counter() - t, 1),
           "geom_def": sorted(defined(geom)), "geom_use": sorted(used(geom)),
           "all_def": sorted(defined(allt))}
    f.write_text(json.dumps(rec))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="assets/freedoom1.wad")
    ap.add_argument("--maps", default="E1M1,E1M5,E1M8")
    ap.add_argument("--from-dir", action="append", default=[], metavar="MAP=DIR",
                    help="take a map's parts from a generated dir instead of re-emitting")
    args = ap.parse_args()
    maps = args.maps.split(",")

    wad = WadFile.from_path(str(ROOT / args.wad))
    cfg = Config()
    spr = _resolve_sprite_wad(wad, DEFAULT_SPRITE_WAD)

    pre = dict(x.split("=", 1) for x in args.from_dir)
    recs = {}
    for m in maps:
        if m in pre:
            r = from_dir(m, pre[m])
            (CACHE / ("%s.json" % m)).parent.mkdir(parents=True, exist_ok=True)
            (CACHE / ("%s.json" % m)).write_text(json.dumps(r))
        else:
            r = emit(wad, m, cfg, spr)
        recs[m] = r
        print("%-6s geometry defines %s labels, whole emission defines %s   (%.0f s)"
              % (m, format(len(r["geom_def"]), ","), format(len(r["all_def"]), ","), r["secs"]),
              flush=True)

    ok = True
    print("")
    print("CHECK 1 -- a geometry part defines only names the whole emission also defines")
    for m, r in recs.items():
        extra = set(r["geom_def"]) - set(r["all_def"])
        print("   %-6s %s" % (m, "ok" if not extra else "!! %d NOT in the full set: %s"
                              % (len(extra), sorted(extra)[:5])))
        ok &= not extra

    print("")
    print("CHECK 2 -- two PREFIXED geometry emissions must not collide")
    base = maps[0]
    for m in maps[1:]:
        a = {mapprefix.apply(x, base.lower() + "_") for x in recs[base]["geom_def"]}
        b = {mapprefix.apply(x, m.lower() + "_") for x in recs[m]["geom_def"]}
        hit = a & b
        print("   %-6s vs %-6s  %s" % (base, m, "DISJOINT ok" if not hit
                                       else "!! %d COLLIDE: %s" % (len(hit), sorted(hit)[:6])))
        ok &= not hit

    print("")
    print("CHECK 3 (NEGATIVE CONTROL) -- the same pairs UNPREFIXED must COLLIDE, or check 2")
    print("                             proves nothing")
    for m in maps[1:]:
        hit = set(recs[base]["geom_def"]) & set(recs[m]["geom_def"])
        print("   %-6s vs %-6s  %s" % (base, m, "collide (%d) ok" % len(hit) if hit
                                       else "!! DISJOINT ALREADY -- check 2 is vacuous"))
        ok &= bool(hit)

    print("")
    print("CHECK 4 -- names a geometry part USES but does not DEFINE must be resolvable, either")
    print("           by the shared emission or by src/fj -- else a concatenated image would not")
    print("           link. (The FIRST version of this check knew only about the emitted parts")
    print("           and called 237 register/macro names from src/fj unresolved.)")
    known = set()
    for f in sorted((ROOT / "src" / "fj").glob("*.fj")):
        known |= set(USE.findall(f.read_text(encoding="utf-8", errors="replace")))
    for m, r in recs.items():
        free = set(r["geom_use"]) - set(r["geom_def"]) - set(r["all_def"]) - known
        free = {x for x in free if not x.isdigit()}
        print("   %-6s %d free names; %s" % (m, len(free),
              "all resolved (emitted parts + src/fj)" if not free
              else "!! UNRESOLVED: %s" % sorted(free)[:8]))
        ok &= not free
    print("")
    print("m4_r1_labels: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
