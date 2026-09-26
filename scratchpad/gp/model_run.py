"""Run the gameplay model (`doomfj.world` + `doomfj.combat`) N tics from spawn with scripted player
keys, and dump one JSON line per tic.

    python scratchpad/gp/model_run.py --tics 300 --skill hard --keys "F40 f20 P1 F60 u2 -20" \
        --place 3004:160:0,3001:220:40 --out run.jsonl [--wake-all] [--full] [--k 3] [--legacy]

KEY SCRIPT: whitespace-separated tokens LETTERS[COUNT] -- the letters held together for COUNT tics
(default 1): f forward, b back, l turn_left, r turn_right, u use, F fire; the weapon number keys
K (1: fist, or the chainsaw if owned), P (2: pistol), S (3: shotgun), C (4: chaingun); and - for
nothing. "fl6" is forward+left for 6 tics, "FS" fires while selecting the shotgun. After the script
runs out the player stands still. `--keys-file` takes a JSON list of per-tic dicts
({"forward": true, "w3": true, ...}) instead. Use while dead asks for the restart.

--place DOOMEDNUM:DX:DY[,...] puts the first active monster of each type DX, DY map units from the
player's start (he faces east), awake with the player as its target -- a scripted fight without
walking to one. --legacy is the old walk-through-things player (`player_blocking=False`).

EACH LINE: {"tic", "keys", "player": {x16, y16, angle, x, y, sector, health, armor, ammo, weapon,
dead, ...}, "doors": [state per door], "monsters": [one dict per ACTIVE monster], "events": {...,
the combat events: fired, shots, hits, kills, pickups, fireballs, ...}, "digest"} -- plus "state"
(every schema field) with --full. The last line is {"summary": ...} with every event total, which
is what a gate requires non-zero. Output is ASCII.
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
           "F": "fire", "K": "w1", "P": "w2", "S": "w3", "C": "w4", "-": None}


def parse_keys(script: str) -> list:
    out = []
    pat = "([%s]+)(\\d*)" % re.escape("".join(LETTERS))
    for tok in script.split():
        m = re.fullmatch(pat, tok)
        if not m:
            raise SystemExit("bad key token %r (letters %s, then an optional count)"
                             % (tok, " ".join(LETTERS)))
        held = {LETTERS[c]: True for c in m.group(1) if LETTERS[c]}
        out += [dict(held) for _ in range(int(m.group(2) or 1))]
    return out


def place(w, spec: str) -> list:
    """--place: put monsters in front of the player's start, awake (see the module docstring)."""
    ws, placed = w.ws, []
    px, py = ws.px >> 16, ws.py >> 16
    for item in filter(None, spec.split(",")):
        num, dx, dy = (int(v) for v in item.split(":"))
        slots = [m for m in range(w.layout.nmon)
                 if w.mon_things[m].type == num and ws.mon_active[m] and m not in placed]
        if not slots:
            raise SystemExit("--place: no active monster of type %d left at this skill" % num)
        m = slots[0]
        w.teleport_monster(m, px + dx, py + dy)
        ws.mon_target[m] = 1
        w._set_state(m, w.mon_info[m].seestate, False, W.TicEvents(w.tic_count))
        placed.append(m)
    return placed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tics", type=int, default=200)
    ap.add_argument("--skill", choices=sorted(gd.SKILL_NAMES), default="hard")
    ap.add_argument("--keys", default="", help="key script, see the module docstring")
    ap.add_argument("--keys-file", help="JSON list of per-tic key dicts")
    ap.add_argument("--place", default="", help="DOOMEDNUM:DX:DY,... monsters put in front")
    ap.add_argument("--out", help="JSON-lines file (default: stdout)")
    ap.add_argument("--wake-all", action="store_true", help="every monster starts awake")
    ap.add_argument("--full", action="store_true", help="also dump every schema field per tic")
    ap.add_argument("--k", type=int, default=W.K_HEAVY, help="heavy actions per tic")
    ap.add_argument("--legacy", action="store_true", help="the player walks through things")
    a = ap.parse_args(argv)

    keys = (json.loads(Path(a.keys_file).read_text()) if a.keys_file else parse_keys(a.keys))
    keys = (keys + [{}] * a.tics)[:a.tics]
    w = W.World(skill=gd.SKILL_NAMES[a.skill], k_heavy=a.k, player_blocking=not a.legacy)
    if a.wake_all:
        w.wake_all()
    placed = place(w, a.place)
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
                           "y": ws.py >> 16, "sector": w.player_sector(), **w.player_view()},
                "doors": list(ws.d_state),
                "monsters": [dict(w.monster_view(m), health=ws.mon_health[m])
                             for m in range(w.layout.nmon) if ws.mon_active[m]],
                "events": ev.as_dict(),
                "digest": w.digest(),
            }
            if a.full:
                line["state"] = ws.as_dict()
            sink.write(json.dumps(line, separators=(",", ":")) + "\n")
        combat = w.event_totals()
        sink.write(json.dumps({"summary": {"tics": len(keys), "skill": a.skill, "k": a.k,
                                           "placed": placed,
                                           "active_monsters": sum(w.ws.mon_active),
                                           **total, "combat": combat,
                                           "player": w.player_view(),
                                           "final_digest": w.digest()}}) + "\n")
    finally:
        if a.out:
            sink.close()
    print("model_run: %d tics, skill %s, %s | %s -> %s" % (
        len(keys), a.skill, ", ".join("%s %d" % kv for kv in total.items()),
        ", ".join("%s %d" % kv for kv in combat.items() if kv[1]), a.out or "stdout"),
        file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
