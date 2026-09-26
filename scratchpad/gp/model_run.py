"""Run the S3a gameplay model (`doomfj.world`) N tics from spawn with scripted player keys, and dump
one JSON line per tic.

    python scratchpad/gp/model_run.py --tics 300 --skill hard --keys "f40 l6 f30 u2 F1 -20" \
        --out run.jsonl [--wake-all] [--full] [--k 3]

KEY SCRIPT: whitespace-separated tokens LETTERS[COUNT] -- the letters held together for COUNT tics
(default 1): f forward, b back, l turn_left, r turn_right, u use, F fire (in S3a fire only makes a
NOISE -- the weapon state machine is S3b), and - for nothing. "fl6" is forward+left for 6 tics.
After the script runs out the player stands still. `--keys-file` takes a JSON list of per-tic dicts
({"forward": true, ...}) instead.

EACH LINE: {"tic", "keys", "player": {x16, y16, angle, x, y, sector}, "doors": [state per door],
"monsters": [one dict per ACTIVE monster], "events": {...}, "digest"} -- plus "state" (every schema
field) with --full. The last line is {"summary": ...}. Output is ASCII.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import gamedata as gd          # noqa: E402
from doomfj import world as W              # noqa: E402

LETTERS = {"f": "forward", "b": "back", "l": "turn_left", "r": "turn_right", "u": "use",
           "F": "fire", "-": None}


def parse_keys(script: str) -> list:
    out = []
    for tok in script.split():
        m = re.fullmatch(r"([fblruF-]+)(\d*)", tok)
        if not m:
            raise SystemExit("bad key token %r (letters f b l r u F -, then an optional count)"
                             % tok)
        held = {LETTERS[c]: True for c in m.group(1) if LETTERS[c]}
        out += [dict(held) for _ in range(int(m.group(2) or 1))]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tics", type=int, default=200)
    ap.add_argument("--skill", choices=sorted(gd.SKILL_NAMES), default="hard")
    ap.add_argument("--keys", default="", help="key script, see the module docstring")
    ap.add_argument("--keys-file", help="JSON list of per-tic key dicts")
    ap.add_argument("--out", help="JSON-lines file (default: stdout)")
    ap.add_argument("--wake-all", action="store_true", help="every monster starts awake")
    ap.add_argument("--full", action="store_true", help="also dump every schema field per tic")
    ap.add_argument("--k", type=int, default=W.K_HEAVY, help="heavy actions per tic")
    a = ap.parse_args(argv)

    keys = (json.loads(Path(a.keys_file).read_text()) if a.keys_file else parse_keys(a.keys))
    keys = (keys + [{}] * a.tics)[:a.tics]
    w = W.World(skill=gd.SKILL_NAMES[a.skill], k_heavy=a.k)
    if a.wake_all:
        w.wake_all()
    sink = open(a.out, "w", encoding="ascii", newline="\n") if a.out else sys.stdout
    total = {"moves": 0, "heavy": 0, "deferred": 0, "wakes": 0, "leaf_changes": 0,
             "decisions": 0, "attacks": 0, "door_uses": 0}
    try:
        for k in keys:
            ev = w.tic(k)
            ws = w.ws
            for name in total:
                total[name] += len(getattr(ev, name))
            line = {
                "tic": ev.tic,
                "keys": "".join(c for c, n in LETTERS.items() if n and k.get(n)),
                "player": {"x16": ws.px, "y16": ws.py, "angle": ws.pangle, "x": ws.px >> 16,
                           "y": ws.py >> 16, "sector": w.player_sector()},
                "doors": list(ws.d_state),
                "monsters": [w.monster_view(m) for m in range(w.layout.nmon) if ws.mon_active[m]],
                "events": ev.as_dict(),
                "digest": w.digest(),
            }
            if a.full:
                line["state"] = ws.as_dict()
            sink.write(json.dumps(line, separators=(",", ":")) + "\n")
        sink.write(json.dumps({"summary": {"tics": len(keys), "skill": a.skill, "k": a.k,
                                           "active_monsters": sum(w.ws.mon_active),
                                           **total, "final_digest": w.digest()}}) + "\n")
    finally:
        if a.out:
            sink.close()
    print("model_run: %d tics, skill %s, %s -> %s" % (
        len(keys), a.skill, ", ".join("%s %d" % kv for kv in total.items()),
        a.out or "stdout"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
