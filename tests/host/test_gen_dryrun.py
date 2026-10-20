"""M8 (gates-ready): scratchpad/gp/gen_dryrun.py -- the per-map generator dry-run -- tells a missing FEATURE (the model
refuses the map: named cluster, a stand-in to get past it) from a TOOL failure (the generator's own bug), and its
stand-ins get past exactly the refusal they name.

Controls (R9): an error no feature pattern names stays TOOL; E1M9's door 135 refuses without `door-first-kind` and
passes with it; a map's things lose only the unknown types under `unknown-things`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad" / "gp"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))

import gen_dryrun as G      # noqa: E402


def _tb(line):
    return "noise\nTraceback (most recent call last):\n  File \"x.py\", line 1, in f\n" + line + "\n"


def test_classify_features_and_tools():
    cases = {
        "AssertionError: thing types missing from gamedata.THING_TYPES: [2024, 2046]": ("FEATURE", "unknown-things"),
        "AssertionError: door 135 is asked two motions: ['plain', 'stay']": ("FEATURE", "door-first-kind"),
        "AssertionError: leaf lists store mobile index + 1 in a byte": ("FEATURE", None),
        "AssertionError: S1 door switch tag 9 opens a door that closes: its latch would be seen": ("FEATURE", None),
    }
    for line, (kind, sin) in cases.items():
        k, _d, s = G.classify(_tb(line))
        assert (k, s) == (kind, sin), line
    # CONTROL: the generator's own bug stays TOOL
    assert G.classify(_tb("ValueError: max() arg is an empty sequence"))[0] == "TOOL"
    assert G.classify(_tb("KeyError: 'R0-courtyard'"))[0] == "TOOL"


def _run(code):
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), timeout=600)
    return r.returncode, r.stdout + r.stderr


PRE = ("import sys; sys.path[:0] = [r'%s', r'%s']\n" % (ROOT / "src", ROOT / "scratchpad" / "gp")
       + "from doomfj.wad import WadFile\nfrom doomfj import doors as D\nimport gen_dryrun as G\n"
       + "w = WadFile.from_path(r'%s')\n" % (ROOT / "tests" / "fixtures" / "freedoom_e1m9.wad"))


def test_door_first_kind_gets_past_e1m9s_door_135():
    rc, out = _run(PRE + "D.door_kinds(w.sectors('E1M9'), w.linedefs('E1M9'), w.sidedefs('E1M9'))")
    # the model refused it ("door 135 is asked two motions") until M8 C3 gave E1M9's mixed door its two kinds; the
    # stand-in stays harmless on top of it
    assert rc == 0 and "two motions" not in out, out[-800:]
    rc, out = _run(PRE + "G._door_first_kind()\n"
                   "k = D.door_kinds(w.sectors('E1M9'), w.linedefs('E1M9'), w.sidedefs('E1M9'))\nprint('K', k[135])")
    assert rc == 0 and "K " in out, out[-800:]


def test_unknown_things_drops_only_the_unknown():
    rc, out = _run(PRE + "from doomfj import gamedata as gd\n"
                   # every E1M9 type is known since M8 C6 / C7: one (a hanging body, 59) is made unknown here
                   "gd.THING_TYPES.pop(59)\n"
                   "before = w.things('E1M9')\nG._unknown_things()\nafter = w.things('E1M9')\n"
                   "gone = {t.type for t in before} - {t.type for t in after}\n"
                   "assert gone and all(t not in gd.THING_TYPES for t in gone), gone\n"
                   "assert all(t.type in gd.THING_TYPES or t.type in gd.NOT_THINGS for t in after)\n"
                   "assert len(after) == sum(1 for t in before if t.type not in gone)\nprint('OK', sorted(gone))")
    assert rc == 0 and "OK" in out, out[-800:]


def test_a_map_without_monsters_refuses_by_name(tmp_path):
    """E1M8's only monsters are four Barons (3003, C8): with them dropped by the stand-in, suggest() raised ValueError
    (max of nothing). It now refuses by name, and gen_dryrun files the refusal under C8 (a FEATURE, not the tool)"""
    out = tmp_path / "cp.json"
    r = subprocess.run([sys.executable, str(ROOT / "scratchpad" / "gp" / "gen_dryrun.py"), "--one", "E1M8", "--standin",
                        "unknown-things", "undrawn-pickups", "--", "scratchpad/gp/scenarios_map.py", "--map", "E1M8",
                        "--suggest-checkpoints", "--checkpoints", str(out)], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=900)
    text = r.stdout + r.stderr
    assert r.returncode == 1 and "suggest: no monster of E1M8" in text and "ValueError" not in text, text[-1500:]
    assert G.classify(text)[0] == "FEATURE"
