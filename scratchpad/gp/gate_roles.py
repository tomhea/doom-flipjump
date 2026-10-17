"""gate_roles.py -- M8 (docs/level-pipeline.md 4): the ROLES the gameplay gates place their scenarios by, per map.

The gates (p2a_gate, fight_gate, die_gate) DERIVE their poses from the map (`door_front`, `card_pose`, `trigger_pose`,
`poses_in_sector`, `poses_facing` ...); what was E1M1 in them is WHICH door, lift, sector or barrel each scenario is
about -- its role. This module is the one place that names them:

    R = gate_roles.roles("E1M2")          # scenarios/e1m2/gates.json, written by gate_targets.py --map E1M2
    R["blaze_door"]                       # -> a door sector, or raises RoleNA (with the generator's reason)
    R.na("nukage_sector")                 # -> the reason the role is N/A on this map, or None when it exists

E1M1 KEEPS ITS LITERALS: `E1M1` below is exactly what the gates hard-wired before M8 (p2a_gate's 71 / 84 / 77+145 /
124 / 98+103 / (40, 256) / 129 / 10, fight_gate's walks, the barrel column at x 2512, barrel 13, sector 23, the brawl
court), so E1M1's scenarios cannot move -- `gate_roles_check.py` proves it against the gates at a git ref. Every other
map reads its generated file; a role the map cannot host is N/A there with the generator's reason, and the gate
prints the scenario N/A instead of failing to place it.

THE ROLES (a value, or N/A with a reason):
  key_doors        {"blue": [sector ...], "yellow": [...], "red": [...]} every key door by its LINE special
  blue_door        p2a S1 / S3: a blue-card door whose model kind is "blue"
  yellow_door, red_door   the same colours' doors (a gate runs them once the model has the kind: M8 F2)
  blaze_door       p2a S5: a blazing door
  walkovers        p2a S6, S7 ...: [[door sector, tag], ...] W1 walk-over doors (one scenario each)
  cards            {"blue": [x, y, z], ...} the cards' things (z: the floor they stand on)
  card_pose        p2a S2 / fight F10: [x, y, angle] onto the blue card, where its platform has no pose 48 units off
                   (absent: p2a_gate.card_pose derives it, as on E1M1)
  below_card_sector  p2a S4 / fight F1r: a sector whose floor puts the card out of reach of a tried step
  wr_lift          p2a S9 / S12: {"sector", "pose": [x, y, angle]} -- forward from the pose crosses its WR line
  sr_lift          p2a S10: {"sector", "tag"} -- the SR use line of that tag
  floor_switch     p2a S11: {"box": index in MoverPhase.switch_boxes, "sector": a pillar it lowers, "lowered": z}
  reversal_door    p2a S13 / die D2 D3d: a plain door the player stands in as it closes
  lift_leaf_sector die D10l: a lift's sector
  pickup_walks     fight F1: [[x, y, angle], ...] straight walks through a cluster of hard pickups
  chain            fight F7 / S2 / S4: {"x": X} the barrels at x == X (E1M1) or {"barrels": [...]}, and
                   "west_of": X (the poses' x < X) or null
  block_barrel     fight F8a: a barrel index
  nukage_sector    fight F9 / F9l, die D6: a damaging sector
  court            fight S3: {"points": [[x, y], ...], "angle": BAM}
  teleports        (M8 F6) [[line, special, tag, destination sector], ...] -- for the teleport rung's scenarios
  exit             [line, special] the exit switch (p2a S8 places by doors.exit_boxes)

`GATE_ROLES_OVERRIDE` (a JSON object merged over the roles) exists for ONE purpose: gate_roles_check.py's negative
control (R9) moves a role and requires the scenarios' fingerprint to move. Nothing else may set it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

FILE_NAME = "gates.json"
NORTH, WEST = 0x40000000, 0x80000000

# what the gates hard-wired on E1M1 before M8, role by role (the literals, verbatim)
E1M1 = {
    "key_doors": {"blue": [51, 71], "yellow": [], "red": []},
    "blue_door": 71,
    "blaze_door": 84,
    "walkovers": [[77, 5], [145, 6]],
    "cards": {"blue": [2192, 576, 136]},
    "below_card_sector": 124,
    "wr_lift": {"sector": 98, "pose": [40, 256, 0]},
    "sr_lift": {"sector": 103, "tag": 2},
    "floor_switch": {"box": 0, "sector": 129, "lowered": 136},
    "reversal_door": 10,
    "lift_leaf_sector": 98,
    "pickup_walks": [[-160, 112, NORTH], [32, 1440, WEST], [174, 898, 0xE0000000]],
    "chain": {"x": 2512, "west_of": 2512},
    "block_barrel": 13,
    "nukage_sector": 23,
    "court": {"points": [[1424, 732], [1424, 760], [1400, 732]], "angle": NORTH},
    "teleports": [],
    "exit": [407, 11],
}
E1M1_NA: dict = {"yellow_door": "E1M1 has no yellow door", "red_door": "E1M1 has no red door"}
# every role name (E1M1's, the other colours' doors, the card pose a map may need)
ALL_ROLES = tuple(E1M1) + ("yellow_door", "red_door", "card_pose")


class RoleNA(KeyError):
    """a role this map cannot host -- the gate prints the scenario N/A with `reason`"""

    def __init__(self, role: str, reason: str):
        super().__init__(role)
        self.role, self.reason = role, reason

    def __str__(self):
        return "%s: N/A -- %s" % (self.role, self.reason)


class Roles:
    def __init__(self, mapname: str, roles: dict, na: dict, source: str):
        self.map, self.roles, self.na_reasons, self.source = mapname, dict(roles), dict(na), source

    def __getitem__(self, name):
        if name in self.roles:
            return self.roles[name]
        raise RoleNA(name, self.na_reasons.get(name, "no such role in %s" % self.source))

    def __contains__(self, name):
        return name in self.roles

    def get(self, name, default=None):
        return self.roles.get(name, default)

    def na(self, name) -> str | None:
        """the reason role `name` is N/A on this map, or None when it is present"""
        if name in self.roles:
            return None
        return self.na_reasons.get(name, "no such role in %s" % self.source)


def roles_path(mapname: str) -> Path:
    from doomfj.mapprofile import scenario_dir
    return scenario_dir(mapname) / FILE_NAME


def _override(roles: dict) -> dict:
    raw = os.environ.get("GATE_ROLES_OVERRIDE")
    if not raw:
        return roles
    return dict(roles, **json.loads(raw))


# gate_targets.py's CANDIDATE roles while it verifies them on the gates' own scenarios (a Roles, or None)
PINNED = None


def roles(mapname: str | None = None) -> Roles:
    """the map's roles: E1M1's literals, or the generated scenarios/<map>/gates.json"""
    from doomfj.mapprofile import profile
    m = profile(mapname).map
    if PINNED is not None and PINNED.map == m:
        return PINNED
    if m == "E1M1":
        return Roles(m, _override(E1M1), E1M1_NA, "gate_roles.E1M1 (the pre-M8 literals)")
    p = roles_path(m)
    if not p.exists():
        raise SystemExit("no gate roles for %s: run `python scratchpad/gp/gate_targets.py --map %s` (writes %s)"
                         % (m, m, p.relative_to(ROOT)))
    doc = json.loads(p.read_text(encoding="ascii"))
    assert doc.get("map", "").upper() == m, "%s names map %s" % (p, doc.get("map"))
    return Roles(m, _override(doc["roles"]), doc.get("na", {}), str(p.relative_to(ROOT)))


# ---- small resolvers the gates share (a role -> what the scenario needs) ---------------------------------------
def chain_barrels(R: Roles, w) -> list:
    """fight F7 / S2 / S4: the chain's barrel indices"""
    ch = R["chain"]
    if "barrels" in ch:
        return list(ch["barrels"])
    return [b for b, t in enumerate(w.barrel_things) if t.x == ch["x"]]


def chain_pose_ok(R: Roles, p) -> bool:
    """the chain's pose filter: E1M1's "west of the column" (x < 2512), or none"""
    lim = R["chain"].get("west_of")
    return lim is None or p[0] >> 16 < lim
