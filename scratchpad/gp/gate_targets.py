"""gate_targets.py -- M8 (docs/level-pipeline.md 4): a map's gate ROLES, generated from the model and VERIFIED on
the gates' own scenarios. Oracle only: no binary, no build.

    python scratchpad/gp/gate_targets.py --map E1M2                 # -> scenarios/e1m2/gates.json
    python scratchpad/gp/gate_targets.py --map E1M1 --compare       # E1M1: what it would pick vs gate_roles.E1M1
    ... [--no-verify-fight]                                         # skip fight_gate's placement of F1 F7 F8a F9

WHAT IT WRITES. `gate_roles.py` reads the file: {"map", "roles": {role: value}, "na": {role or scenario tag: the
reason it is N/A}, "candidates": {role: [what was tried, and why each was refused]}, "provenance": {...}}. The roles
are gate_roles.py's list; each is DERIVED from the model (doors.DoorPhase / door_sectors and its kinds, movers.
MoverPhase's lifts, use lines and switches, the World's things) and then VERIFIED:

  p2a roles (blue / blaze / walk-over doors, the sector below the card, the WR and SR lifts, the floor switch, the
             reversal door): the candidate is PINNED (gate_roles.PINNED), p2a_gate.scenarios builds ITS scenarios
             for it, and the oracle must do what each claims AND every control must part -- p2a_gate --oracle-only's
             own test, so a role written here passes that gate's oracle half;
  fight roles (the pickup walks, the barrel chain, the barrel F8a blocks, the nukage sector): fight_gate.place on
             the scenario as fight_gate builds it (claim met, no death);
  the court (S3, a stress row with no rule claim beyond a hurt monster) and the lift leaf: derived, not run;
  THE SWEEP: then every fight_gate and die_gate scenario is placed with the roles (claim, deaths, every control) and a
             scenario no candidate places is N/A BY ITS TAG with that reason (fight_gate prints it N/A off E1M1) --
             a coverage gap made visible, to be closed by better candidates, never hidden.

A role with no candidate that verifies is N/A with the reason (the candidates and what refused them are kept). The
map's other features that are not roles yet are LISTED (key doors per colour by their line specials, cards per
colour, teleport lines, exits), so the M8 feature rungs (door kinds F2, teleports F6, items F4) find their scenarios'
targets here when they add the gates' rows. Fight scenarios whose candidates come from the map's things are N/A by
tag when the thing is absent (F3: no chainsaw, F5: no berserk pack).

Deterministic: every list in map order, every choice the first that verifies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))
if __name__ == "__main__":                       # `--map E1Mn` before probe / gamespeed read their defaults
    from doomfj.mapprofile import take_map_arg
    take_map_arg()

import gate_roles                                                            # noqa: E402
from doomfj.mapprofile import check_checkout                                # noqa: E402
check_checkout(__file__)        # M8: this checkout's doomfj (the installed one is the main repo's)
from doomfj import doors as D                                               # noqa: E402
from doomfj import gamedata as gd                                           # noqa: E402

KEY_COLOURS = gate_roles.KEY_LINE_COLOURS     # M8: every key-door special (the blazing ones too), by colour
CARD_THINGS = {"blue": (5, 40), "yellow": (6, 39), "red": (13, 38)}       # card, skull key
TELEPORT_SPECIALS = (39, 97, 125, 126)
EXIT_LINE_SPECIALS = (11, 51, 52, 124)
WALK_LEN = 280                   # F1: 36 frames of forward from rest (DOOM's walk: ~8.3 units a tic at speed)
TOUCH = 16 + 20                  # the player's radius + an item's


def sha16(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


# ================================================================================================
# the oracle, as the gates build it
# ================================================================================================
class Ctx:
    def __init__(self, mapname: str):
        import probe as P
        import onewalk
        from doomfj.mapprofile import profile
        from doomfj.things import drawable_things
        from doomfj.monsters import MonsterPhase
        from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE, PLAYER_MODE
        self.map = mapname
        self.wad = profile(mapname).wad
        self.orc = P.Oracle(self.wad, P.DEFAULT_ASSET, mapname)
        self.dsim = onewalk.DoorSim(self.wad, mapname)
        self.card = self.dsim.dp.card_at
        self.card_di = ([di for di, t in enumerate(drawable_things(self.orc.rm, self.orc.mw.things(mapname),
                                                                   self.orc.art)[0]) if t.type == 5] or [-1])[0]
        self.w = MonsterPhase(self.dsim.mw, mapname, BOOT_SKILL, rm=self.dsim.rm, mode=MONSTER_MODE,
                              player=PLAYER_MODE).world
        self._fight_run = None

    def pin(self, roles: dict):
        """the candidate roles, every OTHER role N/A ("not under test"): the gate builds only their scenarios"""
        na = {r: "not under test" for r in gate_roles.ALL_ROLES if r not in roles}
        gate_roles.PINNED = gate_roles.Roles(self.map, roles, na, "gate_targets candidate")

    def fight_run(self):
        if self._fight_run is None:
            import fight_gate as FG
            self._fight_run = FG.Run(self.orc, self.dsim, self.card_di)
        return self._fight_run


# ================================================================================================
# p2a: the candidate pinned, the gate's own scenarios built, claims and controls run
# ================================================================================================
def p2a_verify(ctx: Ctx, role: str, value, tags) -> str | None:
    """None when every p2a scenario whose name starts with one of `tags` does what it claims on the oracle and each
    of its controls parts; else why not"""
    import p2a_gate as G
    ctx.pin({role: value})
    try:
        scen = [s for s in G.scenarios(ctx.dsim, ctx.card) if not s.get("na") and s["name"].split()[0] in tags]
    except (AssertionError, KeyError, ValueError, IndexError) as e:
        return "placing it: %s: %s" % (type(e).__name__, e)
    finally:
        gate_roles.PINNED = None
    if not scen:
        return "no scenario placed"
    for sc in scen:
        want = G.hooked(G.Mirror(ctx.dsim, ctx.card_di), ctx.orc, ctx.dsim, ctx.card_di).run(
            sc["pose"], sc["keys"], sc["pcard"])
        if not sc["claim"](want):
            return "%s: the oracle does not do what it claims" % sc["name"].split()[0]
        for ctl in sc["controls"]:
            alt = G.hooked(G.Mirror(ctx.dsim, ctx.card_di, ctl), ctx.orc, ctx.dsim, ctx.card_di).run(
                sc["pose"], sc["keys"], sc["pcard"])
            if not any(G.expected_cells(x, ctx.dsim.order, ctx.dsim.mp.order)
                       != G.expected_cells(y, ctx.dsim.order, ctx.dsim.mp.order) for x, y in zip(want, alt)):
                return "%s: control %s never parts (vacuous)" % (sc["name"].split()[0], ctl)
    return None


def first_verified(ctx, role, cands, tags, log) -> object:
    for v in cands:
        why = p2a_verify(ctx, role, v, tags)
        log.append({"value": v, "refused": why})
        print("    %-18s %-48s %s" % (role, json.dumps(v)[:48], "OK" if why is None else "refused: " + why),
              flush=True)
        if why is None:
            return v
    return None


def p2a_roles(ctx: Ctx, roles: dict, na: dict, tried: dict) -> None:
    import p2a_gate as G
    dsim, kinds, M = ctx.dsim, ctx.dsim.dp.kinds, ctx.map
    lds, sds, secs = dsim.lds, dsim.sds, dsim.secs
    doors = D.door_sectors(secs, lds, sds)
    # ---- the key doors by their LINE special, every colour (the model's kinds lag the WAD until M8 F2)
    key_doors = {c: [] for c in ("blue", "yellow", "red")}
    not_doors = {c: [] for c in ("blue", "yellow", "red")}   # M8: key LINES whose sector the model makes no door
    for i, ld in enumerate(lds):
        c = KEY_COLOURS.get(ld.special)
        if c and ld.back not in (-1, 0xFFFF) and ld.back < len(sds) and sds[ld.back].sector in doors:
            if sds[ld.back].sector not in key_doors[c]:
                key_doors[c].append(sds[ld.back].sector)
        elif c:
            not_doors[c].append((i, ld.special))
    key_doors = {c: sorted(v) for c, v in key_doors.items()}
    roles["key_doors"] = key_doors
    # ---- the cards per colour (the blue one where DoorPhase takes it: its floor)
    cards = {}
    for c, types in CARD_THINGS.items():
        ts = [t for t in dsim.mw.things(M) if t.type in types]
        if c == "blue" and ctx.card is not None:
            cards[c] = list(ctx.card)
        elif ts:
            t = ts[0]
            cards[c] = [t.x, t.y, secs[G._sector(dsim, t.x, t.y)].floor_h]
    roles["cards"] = cards
    # ---- blue door S1 / S3 (and S2, the card's platform)
    blue = [si for si in key_doors["blue"] if kinds.get(si) == "blue"]
    log = tried.setdefault("blue_door", [])
    if ctx.card is None:
        na["blue_door"] = "%s has no blue card (type 5)" % M
    elif not blue:
        na["blue_door"] = "%s has no door the model calls blue" % M
    else:
        v = first_verified(ctx, "blue_door", blue, ("S1", "S3"), log)
        if v is None:
            na["blue_door"] = "no blue door of %s verifies (S1 / S3; candidates %s)" % (M, blue)
        else:
            roles["blue_door"] = v
    # ---- S2 / F10: onto the card -- card_pose's (48 units off, on its platform) when it places, else searched
    if ctx.card is not None:
        try:
            G.card_pose(dsim, ctx.card)
            derived = True
        except AssertionError:
            derived = False
        if not derived:
            kx, ky, _kz = ctx.card
            cands = []
            for d in (24, 32, 40, 48, 56, 64):
                for k in range(16):
                    a = k * math.pi / 8
                    x, y = round(kx + d * math.cos(a)), round(ky + d * math.sin(a))
                    if G._ok(dsim, x << 16, y << 16):
                        cands.append([x, y, G.bam(kx - x, ky - y)])
            v = first_verified(ctx, "card_pose", cands[:16], ("S2",), tried.setdefault("card_pose", []))
            ksec = G._sector(dsim, kx, ky)
            mover = ("floor switch" if ksec in dsim.mp.switch else "lift" if ksec in dsim.mp.stops else None)
            if v is None:
                na["card_pose"] = "no standing pose of %s walks onto its blue card in 4 frames%s" % (
                    M, "" if mover is None else
                    " -- the card lies on sector %d, a %s's floor (%s), out of reach until it moves (the level "
                    "survey's 'pickups on a door or mover floor' row)" % (
                        ksec, mover, dsim.mp.switch.get(ksec, "lift")))
            else:
                roles["card_pose"] = v
    for c in ("yellow", "red"):
        if key_doors[c]:
            roles[c + "_door"] = key_doors[c][0]
        elif not_doors[c]:      # M8 (gen_dryrun on E1M5: its red D1 doors, special 33, are walls in the model -- C3)
            na[c + "_door"] = ("%s's %s key lines %s make no door in the model (doors.door_sectors: the special "
                               "is C3's)" % (M, c, not_doors[c][:4]))
        else:
            na[c + "_door"] = "%s has no %s key door" % (M, c)
    # ---- S4: a sector below the card, out of reach
    if ctx.card is None:
        na["below_card_sector"] = "%s has no blue card" % M
    else:
        kx, ky, kz = ctx.card
        ksec = G._sector(dsim, kx, ky)
        cand = []
        for dx in range(-80, 81, 4):
            for dy in range(-80, 81, 4):
                s = G._sector(dsim, kx + dx, ky + dy)
                if s != ksec and s not in cand and not (-D.CARD_REACH_DOWN <= kz - secs[s].floor_h
                                                        <= D.CARD_REACH_UP):
                    cand.append(s)
        cand.sort(key=lambda s: (abs(kz - secs[s].floor_h), s))
        v = first_verified(ctx, "below_card_sector", cand[:8], ("S4",), tried.setdefault("below_card_sector", []))
        if v is None:
            na["below_card_sector"] = ("no sector beside %s's card puts it out of a tried step's reach (tried %s)"
                                       % (M, cand[:8]))
        else:
            roles["below_card_sector"] = v
    # ---- S5: a blazing door
    blaze = sorted(si for si, k in kinds.items() if k == "blaze")
    v = first_verified(ctx, "blaze_door", blaze, ("S5",), tried.setdefault("blaze_door", [])) if blaze else None
    if v is None:
        na["blaze_door"] = ("%s has no blazing door" % M) if not blaze else "no blazing door verifies (%s)" % blaze
    else:
        roles["blaze_door"] = v
    # ---- S6, S7 ...: every walk-over trigger that verifies
    walk = []
    for t in dsim.dp.triggers:
        si = t[0]
        v = first_verified(ctx, "walkovers", [[[si, secs[si].tag]]], ("S6",), tried.setdefault("walkovers", []))
        if v is not None:
            walk.append(v[0])
    if walk:
        roles["walkovers"] = walk
    else:
        na["walkovers"] = ("%s has no W1 walk-over door" % M) if not dsim.dp.triggers else \
            "no walk-over trigger verifies"
    # ---- S9 / S12: a WR lift and a pose before its line
    mp = dsim.mp
    cands = []
    for (si, axis, coord, lo, hi) in mp.walk:
        mid = (lo + hi) // 2
        for back in (24, 32, 40, 48, 16):
            for side in (-1, 1):
                a = coord + side * back
                x, y = (mid, a) if axis == "y" else (a, mid)
                if G._ok(dsim, x << 16, y << 16):
                    ang = G.bam(0, -side) if axis == "y" else G.bam(-side, 0)
                    c = {"sector": si, "pose": [x, y, ang]}
                    if c not in cands:
                        cands.append(c)
    v = first_verified(ctx, "wr_lift", cands[:12], ("S9", "S12"), tried.setdefault("wr_lift", [])) if cands else None
    if v is None:
        na["wr_lift"] = ("%s has no WR lift line" % M) if not mp.walk else "no WR lift pose verifies"
    else:
        roles["wr_lift"] = v
    # ---- S10: an SR lift
    cands = []
    for tag, _box in mp.use:
        if tag in mp.of_tag and {"sector": mp.of_tag[tag], "tag": tag} not in cands:
            cands.append({"sector": mp.of_tag[tag], "tag": tag})
    v = first_verified(ctx, "sr_lift", cands, ("S10",), tried.setdefault("sr_lift", [])) if cands else None
    if v is None:
        na["sr_lift"] = ("%s has no SR lift line" % M) if not cands else "no SR lift verifies"
    else:
        roles["sr_lift"] = v
    # ---- S11: the floor switch -- a press, then the pillar it lowered (read off the oracle's frame 1)
    cands = []
    for k, box in enumerate(mp.switch_boxes):
        try:
            pose = G._in_box(dsim, box)
        except AssertionError:
            continue
        tr = G.hooked(G.Mirror(dsim, ctx.card_di), ctx.orc, dsim, ctx.card_di).run(pose, [{}, {"use": True}, {}, {}])
        for s in sorted(mp.switch):
            low = tr[1]["mheights"].get(s, (None,))[0]
            if low is not None and low != secs[s].floor_h:
                cands.append({"box": k, "sector": s, "lowered": low})
                break
    v = first_verified(ctx, "floor_switch", cands, ("S11",), tried.setdefault("floor_switch", [])) if cands else None
    if v is None:
        na["floor_switch"] = ("%s has no floor switch" % M) if not mp.switch_boxes else "no floor switch verifies"
    else:
        roles["floor_switch"] = v
    # ---- S13: a plain door the player stands in as it closes
    plain = [si for si in dsim.order if kinds.get(si) == "plain" and si in dsim.boxes
             and not any(si in v for v in key_doors.values())]
    v = first_verified(ctx, "reversal_door", plain, ("S13",), tried.setdefault("reversal_door", [])) if plain else None
    if v is None:
        na["reversal_door"] = "no plain door of %s verifies S13 (tried %s)" % (M, plain)
    else:
        roles["reversal_door"] = v
    # ---- D10l: a lift's leaf
    lifts = list(mp.order)
    if lifts:
        roles["lift_leaf_sector"] = roles["wr_lift"]["sector"] if "wr_lift" in roles else lifts[0]
    else:
        na["lift_leaf_sector"] = "%s has no lift" % M


# ================================================================================================
# fight: candidates by the map's things, placed by fight_gate
# ================================================================================================
def fight_place(ctx: Ctx, sc: dict, verify: bool):
    """fight_gate.place on `sc`, and every one of its `controls` must part (fight_gate's own test)"""
    if not verify:
        return True
    import fight_gate as FG
    got = FG.place(ctx.fight_run(), sc)
    if got is None:
        return False
    cand, want, _c = got
    return all(FG.ctl_parts(ctx.fight_run(), sc, cand, want, ctl) is not None for ctl in sc.get("controls", ()))


def sweep(ctx: Ctx, roles: dict, na: dict, gate: str) -> None:
    """M8: every scenario of fight_gate / die_gate, placed on the oracle with the generated roles as the gate places it
    (claim, no death unless the gate allows deaths, every control parts); a scenario that cannot be placed is N/A by its
    tag with the reason -- the gate prints it N/A on this map instead of failing to place it. Scenarios already N/A,
    awaiting a package or N/A by rule are left to the gate."""
    import fight_gate as FG
    import p8a_lib as P8
    if gate == "die":
        import die_gate as DG
        scen_fn, deaths_ok, run = DG.scenario_list, True, DG.Run(ctx.orc, ctx.dsim, ctx.card_di)
    else:
        scen_fn, deaths_ok, run = FG.scenario_list, False, ctx.fight_run()
    gate_roles.PINNED = gate_roles.Roles(ctx.map, roles, na, "gate_targets sweep")
    try:
        scen = scen_fn(ctx.dsim, ctx.w, ctx.card)
    finally:
        gate_roles.PINNED = None
    for sc in scen:
        tag = sc["name"].split()[0]
        if sc.get("na") or tag in na or not sc.get("cands") or P8.status(sc, FG.PMODE, FG.MMODE) != "run":
            continue
        got = FG.place(run, sc, deaths_ok=deaths_ok)
        why = None
        if got is None:
            why = "no candidate of %d places on %s's oracle (gate_targets sweep: the claim is not met%s)" % (
                len(sc["cands"][:sc.get("limit", 12)]), ctx.map, "" if deaths_ok else " without a death")
        else:
            cand, want, _c = got
            for ctl in sc.get("controls", ()):
                try:
                    if FG.ctl_parts(run, sc, cand, want, ctl) is None:
                        why = "placed, but control %s never parts there (gate_targets sweep)" % ctl
                        break
                except P8.Awaits:
                    continue
        print("    %-6s %-60s %s" % (gate, sc["name"][:60], "OK" if why is None else "N/A: " + why), flush=True)
        if why:
            na[tag] = why


def fight_roles(ctx: Ctx, roles: dict, na: dict, tried: dict, verify: bool) -> None:
    import fight_gate as FG
    dsim, w, M = ctx.dsim, ctx.w, ctx.map
    I, F, FIRE = FG.I, FG.F, FG.FIRE
    bit_h = gd.skill_bit(gd.SK_HARD)
    pk = [t for t in w.pickup_things if t.flags & bit_h]
    # ---- F1: straight walks through hard pickups (the most items within a touch of a WALK_LEN ray first)
    walks = []
    for t in pk:
        for k in range(8):
            a = k * math.pi / 4
            ca, sa = math.cos(a), math.sin(a)
            x0, y0 = round(t.x - 48 * ca), round(t.y - 48 * sa)
            n = hb = 0
            for u in pk:
                along = (u.x - x0) * ca + (u.y - y0) * sa
                perp = abs(-(u.x - x0) * sa + (u.y - y0) * ca)
                on = 0 <= along <= WALK_LEN and perp < TOUCH
                n += on
                hb += on and u.type in (2014, 2015)       # the bonuses: the cap and rounding controls see them
            if n >= 4:
                walks.append((-min(hb, 3), -n, x0, y0, (k << 29) & 0xFFFFFFFF))
    walks.sort()
    keep, log = [], tried.setdefault("pickup_walks", [])
    seen = set()
    for _nhb, negn, x0, y0, ang in walks:
        if len(keep) >= 3 or len(log) >= 24:
            break
        if (x0 >> 5, y0 >> 5, ang) in seen:
            continue
        seen.add((x0 >> 5, y0 >> 5, ang))
        poses = FG.walk_poses(dsim, x0, y0, ang, (0,))
        if not poses:
            continue
        sc = {"name": "F1", "keys": [F] * 36 + [I] * 6, "cands": [(p, None) for p in poses],
              "controls": ["bonus_cap", "bonus_round"],
              "claim": lambda c, tr: c["pickups"] >= 4 and c["bonus_frames"] >= 1}
        ok = fight_place(ctx, sc, verify)
        log.append({"value": [x0, y0, ang], "items_on_the_ray": -negn, "refused": None if ok else "claim not met"})
        print("    %-18s %-48s %s" % ("pickup_walks", json.dumps([x0, y0, ang]), "OK" if ok else "refused"),
              flush=True)
        if ok:
            keep.append([x0, y0, ang])
    if keep:
        roles["pickup_walks"] = keep
    else:
        na["pickup_walks"] = "no straight walk through 4 hard pickups of %s takes them (%d rays tried)" % (M, len(log))
    # ---- F7: the largest barrel chain (barrels within a blast's reach of each other)
    bt = w.barrel_things
    if not bt:
        na["chain"] = na["block_barrel"] = "%s has no barrel" % M
    else:
        adj = {b: [c for c in range(len(bt)) if c != b and max(abs(bt[b].x - bt[c].x), abs(bt[b].y - bt[c].y)) < 128
                   and w.los_points((bt[b].x << 16, bt[b].y << 16), (bt[c].x << 16, bt[c].y << 16))]
               for b in range(len(bt))}
        comps, seen = [], set()
        for b in range(len(bt)):
            if b in seen:
                continue
            comp, stack = [], [b]
            seen.add(b)
            while stack:
                u = stack.pop()
                comp.append(u)
                for v in adj[u]:
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
            comps.append(sorted(comp))
        comps.sort(key=lambda c: (-len(c), c))
        log = tried.setdefault("chain", [])
        for comp in comps:
            if len(comp) < 3:
                break
            ch = {"barrels": comp, "west_of": None}
            cands = [(p, FG.both(FG.bar_health(b, 1), FG.armor(200, 2))) for b in comp
                     for p in FG.poses_facing(dsim, w, bt[b].x, bt[b].y, (192, 224, 160, 256))]
            sc = {"name": "F7", "keys": [I] * 14 + [FIRE] * 2 + [I] * 30, "cands": cands,
                  "claim": lambda c, tr: c["barrel_blasts"] >= 3}
            ok = bool(cands) and fight_place(ctx, sc, verify)
            log.append({"value": ch, "refused": None if ok else "claim not met (no pose sets off 3)"})
            print("    %-18s %-48s %s" % ("chain", json.dumps(comp)[:48], "OK" if ok else "refused"), flush=True)
            if ok:
                roles["chain"] = ch
                break
        if "chain" not in roles:
            na["chain"] = "no 3 barrels of %s within one another's blast (largest group %d)" % (
                M, len(comps[0]) if comps else 0)
        # ---- F8a: a barrel the player walks into
        log = tried.setdefault("block_barrel", [])
        for b, t in enumerate(bt):
            cands = [(p, None) for p in FG.poses_facing(dsim, w, t.x, t.y, (64, 56, 72))]
            if not cands:
                continue
            sc = {"name": "F8a", "keys": [F] * 10, "cands": cands, "claim": lambda c, tr: c["player_blocked"] >= 1}
            ok = fight_place(ctx, sc, verify)
            log.append({"value": b, "refused": None if ok else "not blocked"})
            print("    %-18s %-48s %s" % ("block_barrel", b, "OK" if ok else "refused"), flush=True)
            if ok:
                roles["block_barrel"] = b
                break
        if "block_barrel" not in roles:
            na["block_barrel"] = "no barrel of %s blocks a walk into it" % M
    # ---- F9 / F9l / D6: a damaging sector
    from doomfj.combat import SECTOR_HURT
    hurt = [s for s, sec in enumerate(w.secs) if sec.special in SECTOR_HURT]
    log = tried.setdefault("nukage_sector", [])
    for s in hurt:
        cands = [(p, None) for p in FG.poses_in_sector(dsim, w, s, step=32, ledge=False)[:12]]
        if not cands:
            continue
        sc = {"name": "F9", "keys": [I] * 70, "cands": cands, "claim": lambda c, tr: c["nukage"] >= 2}
        ok = fight_place(ctx, sc, verify)
        log.append({"value": s, "refused": None if ok else "no damage in 70 frames"})
        if ok:
            roles["nukage_sector"] = s
            break
    if "nukage_sector" not in roles:
        na["nukage_sector"] = ("no sector of %s has a damaging special %s: F9 / F9l / D6 cannot be hosted"
                               % (M, sorted(SECTOR_HURT))) if not hurt else "no damaging sector of %s verifies" % M
    # ---- S3: the brawl court -- facing the densest group of imps and zombiemen / sergeants (a stress row: placed
    # by fight_gate itself; its claim is only that a monster is hurt)
    imps = FG.first_live(w, "MT_TROOP")
    zs = FG.first_live(w, "MT_POSSESSED") + FG.first_live(w, "MT_SHOTGUY")
    ws = w.ws
    best = None
    for m in imps + zs:
        near_i = sum(1 for j in imps if max(abs(ws.mon_x[j] - ws.mon_x[m]), abs(ws.mon_y[j] - ws.mon_y[m])) < 512)
        near_z = sum(1 for j in zs if max(abs(ws.mon_x[j] - ws.mon_x[m]), abs(ws.mon_y[j] - ws.mon_y[m])) < 512)
        if near_i and near_z:
            key = (-(min(near_i, near_z) * 4 + near_i + near_z), m)
            best = min(best, key) if best else key
    if best is None:
        na["court"] = "no imp within 512 units of a zombieman or sergeant on %s" % M
    else:
        m = best[1]
        mx, my = ws.mon_x[m], ws.mon_y[m]
        court = None
        for p in FG.poses_facing(dsim, w, mx, my, (320, 384, 256)):
            x, y, ang = p[0] >> 16, p[1] >> 16, p[2]
            pts = [[x, y]] + [[round(x - d * math.cos(ang / 2 ** 32 * 2 * math.pi)),
                               round(y - d * math.sin(ang / 2 ** 32 * 2 * math.pi))] for d in (24, 48)]
            pts = [q for q in pts if FG.standing(dsim, q[0], q[1])]
            if len(pts) >= 2:
                court = {"points": pts, "angle": ang, "facing_slot": m}
                break
        if court:
            roles["court"] = court
        else:
            na["court"] = "no standing pose facing %s's densest imp / zombieman group" % M
    # ---- the fight rows whose candidates are the map's things, by tag (fight_gate prints these as the reason)
    types = {t.type for t in w.pickup_things}
    if 2005 not in types:
        na["F3"] = "%s has no chainsaw (2005)" % M
    if 2023 not in types:
        na["F5"] = "%s has no berserk pack (2023) on any skill" % M
    if not [t for t in w.pickup_things if t.type == 2012 and t.flags & bit_h] and \
            not [t for t in w.pickup_things if t.type == 2007 and t.flags & bit_h]:
        na["F2"] = "%s has neither a medikit nor a clip at hard" % M


def listed(ctx: Ctx, roles: dict) -> None:
    """features listed for the feature rungs (not yet a gate's role)"""
    lds, secs = ctx.dsim.lds, ctx.dsim.secs
    tele = []
    for i, ld in enumerate(lds):
        if ld.special in TELEPORT_SPECIALS:
            dest = [s for s, sec in enumerate(secs) if ld.tag and sec.tag == ld.tag]
            tele.append([i, ld.special, ld.tag, dest[0] if len(dest) == 1 else dest])
    roles["teleports"] = tele
    ex = [[i, ld.special] for i, ld in enumerate(lds) if ld.special in EXIT_LINE_SPECIALS]
    roles["exit"] = ex[0] if len(ex) == 1 else ex


def generate(mapname: str, verify_fight: bool = True) -> dict:
    t0 = time.time()
    ctx = Ctx(mapname)
    roles, na, tried = {}, {}, {}
    print("gate_targets %s: %d doors %s, lifts %s, %d barrels, card %s" % (
        mapname, len(ctx.dsim.order), dict(sorted(ctx.dsim.dp.kinds.items())), ctx.dsim.mp.order,
        len(ctx.w.barrel_things), ctx.card), flush=True)
    print("  p2a roles (pinned, the gate's scenarios, claims and controls on the oracle):", flush=True)
    p2a_roles(ctx, roles, na, tried)
    print("  fight roles (fight_gate.place%s):" % ("" if verify_fight else " SKIPPED: --no-verify-fight"),
          flush=True)
    fight_roles(ctx, roles, na, tried, verify_fight)
    listed(ctx, roles)
    if verify_fight:
        print("  the sweep (every fight_gate / die_gate scenario placed with these roles; unplaceable -> N/A):",
              flush=True)
        for gate in ("fight", "die"):
            sweep(ctx, roles, na, gate)
    gen = Path(__file__)
    doc = {"map": mapname,
           "what": "the gates' ROLES on %s (scratchpad/gp/gate_roles.py reads them; gate_targets.py writes them)"
                   % mapname,
           "roles": roles, "na": na, "candidates": tried,
           "provenance": {"generator": "scratchpad/gp/gate_targets.py", "generator_sha16": sha16(gen),
                          "wad": ctx.wad, "wad_sha16": sha16(ROOT / ctx.wad),
                          "model_sha16": {f: sha16(ROOT / f) for f in (
                              "src/doomfj/doors.py", "src/doomfj/movers.py", "src/doomfj/world.py",
                              "src/doomfj/combat.py", "scratchpad/gp/p2a_gate.py", "scratchpad/gp/fight_gate.py")},
                          "fight_verified": verify_fight, "seconds": round(time.time() - t0)}}
    return doc


def main(argv=None) -> int:
    from doomfj.mapprofile import ACTIVE
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--compare", action="store_true", help="E1M1: print what it picks against gate_roles.E1M1")
    ap.add_argument("--no-verify-fight", action="store_true")
    ap.add_argument("--out", help="default: scenarios/<map>/gates.json (never written for E1M1)")
    a = ap.parse_args(argv)
    m = ACTIVE
    doc = generate(m, not a.no_verify_fight)
    print("\nROLES on %s:" % m)
    for k, v in doc["roles"].items():
        print("  %-18s %s" % (k, json.dumps(v)[:110]))
    print("N/A on %s:" % m)
    for k, v in doc["na"].items():
        print("  %-18s %s" % (k, v))
    if m == "E1M1":
        if a.compare:
            lit = gate_roles.E1M1
            for k in sorted(set(lit) | set(doc["roles"])):
                same = lit.get(k) == doc["roles"].get(k)
                print("  %-18s %s%s" % (k, "same as the literal" if same else "generated %s, literal %s" % (
                    json.dumps(doc["roles"].get(k))[:50], json.dumps(lit.get(k))[:50]), ""))
        print("(E1M1 keeps its literals: nothing written)")
        return 0
    out = Path(a.out) if a.out else gate_roles.roles_path(m)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="ascii", newline="\n")
    print("wrote %s (%d roles, %d N/A, %d s)" % (out,
                                                 len(doc["roles"]), len(doc["na"]), doc["provenance"]["seconds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
