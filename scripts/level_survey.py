"""M8 -- THE LEVEL SURVEY: everything a new map needs, found in seconds, before the first (12 GB, 30-minute) emission.

E1M2 found its blockers one emission at a time: the plane-pair ids, the band index, the sector ids, the one-pass reset
prefix, two movers on one seg -- each a dead build, hours apart. Every one of them was computable from the WAD and the
model. This runs each such check through THE MODEL'S OWN FUNCTIONS (doors.door_states, movers.lift_states, World,
lootcode.give_lines, things.drawable_things, wall_renderer.marking_seg_count ...), never a re-derivation, so a check
cannot drift from the cap it predicts; each check runs in its own try, so one refusal does not hide the next.

    python scripts/level_survey.py E1M3                     # one map: the full report (markdown, stdout)
    python scripts/level_survey.py E1M3 --out docs/levels/E1M3.md
    python scripts/level_survey.py --matrix E1M2 E1M3 E1M4 E1M5 E1M8 E1M9    # what each map needs, side by side

WHAT IT DOES NOT SEE (and says so): caps whose input exists only part-way through an emission -- the plane-pair count
(`lines_pid`), the band lists, the step/sprite light classes -- are ESTIMATED here (`pid~` has no guaranteed direction;
scratchpad/m4_bands.py measures them by running the emitter up to the band walk), and the address-space fit is a
projection from E1M1/E1M2's measured parts until the map's own build. A clean survey is a forecast, not a gate.
"""
import argparse
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import gamedata as gd                                           # noqa: E402
from doomfj.config import Config, map_cfg                                   # noqa: E402
from doomfj.wad import WadFile                                              # noqa: E402

ASSET_WAD = ROOT / "assets" / "freedoom1.wad"

# DOOM's line specials by number (p_spec.c / the DOOM wiki's table) -- LABELS for the report only; nothing depends on them
LINE_SPECIAL_NAMES = {
    1: "DR door", 2: "W1 door open stay", 3: "W1 door close", 4: "W1 door", 5: "W1 floor up to lowest ceiling",
    7: "S1 stairs 8", 8: "W1 stairs 8", 9: "S1 donut", 10: "W1 lift", 11: "S1 exit", 12: "W1 light max neighbour",
    13: "W1 light 255", 14: "S1 floor up 32 + texture", 15: "S1 floor up 24 + texture", 16: "W1 door close 30 s",
    17: "W1 light blink", 18: "S1 floor up to next higher", 19: "W1 floor down to highest neighbour",
    20: "S1 floor up next higher + texture", 21: "S1 lift", 22: "W1 floor up next higher + texture",
    23: "S1 floor down to lowest", 24: "G1 floor up to lowest ceiling", 25: "W1 crusher", 26: "DR blue door",
    27: "DR yellow door", 28: "DR red door", 29: "S1 door", 30: "W1 floor up by shortest lower texture",
    31: "D1 door open stay", 32: "D1 blue door stay", 33: "D1 red door stay", 34: "D1 yellow door stay",
    35: "W1 light 35", 36: "W1 floor down to 8 above highest", 37: "W1 floor down to lowest + texture",
    38: "W1 floor down to lowest", 39: "W1 teleport", 40: "W1 ceiling up to highest", 41: "S1 ceiling down to floor",
    42: "SR door close", 43: "SR ceiling down to floor", 44: "W1 ceiling crush", 45: "SR floor down to highest",
    46: "GR door open stay", 47: "G1 floor up next higher + texture", 48: "scrolling wall", 49: "S1 crusher",
    50: "S1 door close", 51: "S1 secret exit", 52: "W1 exit", 53: "W1 perpetual lift", 54: "W1 stop lift",
    55: "S1 floor up crush", 56: "W1 floor up crush", 57: "W1 stop crusher", 58: "W1 floor up 24",
    59: "W1 floor up 24 + texture", 60: "SR floor down to lowest", 61: "SR door open stay", 62: "SR lift",
    63: "SR door", 64: "SR floor up to lowest ceiling", 65: "SR floor up crush", 66: "SR floor up 24 + texture",
    67: "SR floor up 32 + texture", 68: "SR floor up next higher + texture", 69: "SR floor up to next higher",
    70: "SR floor down to 8 above highest", 71: "S1 floor down to 8 above highest", 72: "WR ceiling crush",
    73: "WR crusher", 74: "WR stop crusher", 75: "WR door close", 76: "WR door close 30 s", 77: "WR fast crusher",
    79: "WR light 35", 80: "WR light max neighbour", 81: "WR light 255", 82: "WR floor down to lowest",
    83: "WR floor down to highest", 84: "WR floor down to lowest + texture", 86: "WR door open stay",
    87: "WR perpetual lift", 88: "WR lift", 89: "WR stop lift", 90: "WR door", 91: "WR floor up to lowest ceiling",
    92: "WR floor up 24", 93: "WR floor up 24 + texture", 94: "WR floor up crush", 95: "WR floor up next higher + tex",
    96: "WR floor up by shortest lower texture", 97: "WR teleport", 98: "WR floor down to 8 above highest",
    100: "W1 turbo stairs 16", 101: "S1 floor up to lowest ceiling", 102: "S1 floor down to highest",
    103: "S1 door open stay", 104: "W1 light min neighbour", 105: "WR blaze door", 106: "WR blaze open stay",
    107: "WR blaze close", 108: "W1 blaze door", 109: "W1 blaze open stay", 110: "W1 blaze close",
    111: "S1 blaze door", 112: "S1 blaze open stay", 113: "S1 blaze close", 114: "SR blaze door",
    115: "SR blaze open stay", 116: "SR blaze close", 117: "DR blaze door", 118: "D1 blaze door",
    119: "W1 floor up to next higher", 120: "WR fast lift", 121: "W1 fast lift", 122: "S1 fast lift",
    123: "SR fast lift", 124: "W1 secret exit", 125: "W1 monster teleport", 126: "WR monster teleport",
    127: "S1 turbo stairs 16", 128: "WR floor up to next higher", 129: "WR turbo floor up next higher",
    130: "W1 turbo floor up next higher", 131: "S1 turbo floor up next higher", 132: "SR turbo floor up next higher",
    133: "S1 blue blaze door", 134: "SR red blaze door", 135: "S1 red blaze door", 136: "SR yellow blaze door",
    137: "S1 yellow blaze door", 138: "SR light 255", 139: "SR light 35", 140: "S1 floor up 512",
    141: "W1 silent crusher",
}


def supported_line_specials():
    """{special: what implements it} -- read from the SSOT sets, so a special added there shows up here"""
    from doomfj import doors, movers
    out = {1: "doors (plain DR; monsters open it: world)", 11: "doors (S1 exit)"}
    for s in doors.SECRET_EXIT_SPECIALS:          # M8 C9: the level ends there too (plan G11); LEVEL COMPLETE says so
        out[s] = "exit (M8 C9: S1 secret exit -- LEVEL COMPLETE, SECRET EXIT; exitcode)"
    for s in doors.WALK_EXIT_SPECIALS:
        out[s] = "exit (M8 C9: W1, the player crossing either way; exitcode.walk_lines)"
    for s in doors.BLUE_DOOR_SPECIALS:
        out[s] = "doors (blue card)"
    for s in doors.YELLOW_DOOR_SPECIALS:
        out[s] = "doors (yellow card: pcard_y)"
    for s in doors.RED_DOOR_SPECIALS:
        out[s] = "doors (red card: pcard_r)"
    for s in doors.BLAZE_DOOR_SPECIALS:
        out[s] = "doors (blaze)"
    for s in doors.STAY_DOOR_SPECIALS:
        out[s] = "doors (D1 open-stay)"
    for s in doors.WALKOVER_SPECIALS:
        out[s] = "doors (walk-over %s, per line, by tag%s)" % (doors.WALK_DOOR_KINDS[s],
                                                                ", WR: at rest" if s in doors.WALK_REPEAT else "")
    for s, (_k, once) in doors.SWITCH_DOOR_KINDS.items():
        out[s] = "doors (%s switch, by tag%s)" % ("S1" if once else "SR", ", locked %s" % doors.SWITCH_DOOR_CARDS[s]
                                                  if s in doors.SWITCH_DOOR_CARDS else "")
    for s, stride in doors.CLOSE_DOOR_KINDS.items():         # M8 C3
        out[s] = "doors (WR close, stride %d, holds on a thing)" % stride
    for s in doors.SHOOT_DOOR_SPECIALS:                       # M8 C3
        out[s] = "doors (GR shot line: the picture's aim window, guns only)"
    for s in movers.LIFT_WALK_SPECIALS | movers.LIFT_USE_SPECIALS:
        out[s] = "movers (lift)"
    for s in movers.FLOOR_SWITCH_SPECIALS:
        out[s] = "movers (floor switch, instant; a group per tag)"
    for s, (trig, rule, sub) in movers.FLOOR_SPECIALS.items():      # M8 F1.3: every one-shot floor mover
        if s not in movers.FLOOR_SWITCH_SPECIALS:
            out[s] = "movers (%s1 floor group per tag: %s, %s)" % (trig, rule, "a stop every %d frames" % sub)
    for s in movers.LIFT_FAST_SPECIALS:
        out[s] = "movers (blazing lift: stride %d)" % movers.LIFT_FAST_STRIDE
    for s in movers.LIFT_PERPETUAL_SPECIALS:          # M8 C4
        out[s] = "movers (perpetual lift: a stop every %d frames, first DOWN)" % movers.PERP_SUB
    for s in movers.FLOOR_CHANGE_SPECIALS:
        out[s] += "; the flat changes (from its first stop), the damage stops (at the trigger)"
    from doomfj import lights
    for s, b in lights.SWITCH_LIGHT_SPECIALS.items():
        out[s] = "lights (switch thinker: light %d on a use press)" % b
    from doomfj import teleport
    for s in teleport.TELEPORT_SPECIALS:
        out[s] = ("teleport (M8 C5: monsters only%s; fog, no telefrag)" % (", W1 latch" if s in teleport.ONCE_SPECIALS
                                                                           else "")
                  if s in teleport.MONSTER_ONLY_SPECIALS else "teleport (M8 L4: player and monsters; telefrag, fog)")
    return out


def fj_gives(kind):
    """does the fj loot code have a give routine for this pickup kind? (asks lootcode.give_lines itself)"""
    from doomfj import lootcode
    try:
        lootcode.give_lines(kind)
        return True
    except (KeyError, AssertionError, ValueError, NotImplementedError):
        return False


# line specials kept as a decided SIMPLIFICATION (docs/handoff-e1m2.md 3), not a missing feature
STATIC_SPECIALS = {48: "drawn static, no scroll (simplification, as the lights)"}


# M8 C11: every DOOM monster's doomednum (info.c), gamedata's and the ones it lacks: the slot count is the WAD's
DOOM_MONSTERS = frozenset({3004, 9, 3001, 3002, 58, 3006, 3003, 3005, 16, 7, 64, 65, 66, 67, 68, 69, 71, 84})



def teleport_mover_destinations(secs, lds, sds, tels) -> dict:
    """M8 C5b: {"mover": [(line, sector)], "door": [(line, sector)]} -- the teleport lines whose destination sector is a
    lift or a floor group (the world's mover_order: its z read at run time) or a door (World refuses it)"""
    from doomfj import movers
    from doomfj.doors import door_states
    from doomfj.movers import lift_states
    mv = set(lift_states(secs, lds, sds)) | {si for g in movers.floor_groups(secs, lds, sds) for si in g.sectors}
    dr = set(door_states(secs, lds, sds))
    return {"mover": [(t.line, t.dest_sector) for t in tels if t.dest_sector in mv],
            "door": [(t.line, t.dest_sector) for t in tels if t.dest_sector in dr]}

class Survey:
    def __init__(self, wad, mapname, asset):
        self.wad, self.m, self.asset = wad, mapname, asset
        self.secs, self.lds, self.sds = wad.sectors(mapname), wad.linedefs(mapname), wad.sidedefs(mapname)
        self.verts = wad.vertexes(mapname)
        self.rows = []          # (status, check, value, limit, note)   status: OK / OVER / REFUSED / ERROR / INFO / WARN
        self.facts = {}

    def row(self, status, check, value="", limit="", note=""):
        self.rows.append((status, check, str(value), str(limit), note))

    def guard(self, check, fn):
        try:
            fn()
        except AssertionError as e:
            self.row("REFUSED", check, note=("%s" % e).replace("\n", " ")[:300])
        except Exception as e:  # noqa: BLE001 -- a survey reports every failure, it does not stop at one
            self.row("ERROR", check, note="%s: %s" % (type(e).__name__, ("%s" % e).replace("\n", " ")[:260]))
            self.facts.setdefault("errors", []).append(traceback.format_exc(limit=3))

    def cap(self, check, value, limit, note="", strict_less=False):
        ok = value < limit if strict_less else value <= limit
        self.row("OK" if ok else "OVER", check, value, ("< %s" if strict_less else "<= %s") % limit, note)

    # ------------------------------------------------------------------ the checks
    def geometry(self):
        w, m = self.wad, self.m
        segs, ssecs, nodes = w.segs(m), w.subsectors(m), w.nodes(m)
        xs = [v.x for v in self.verts]
        ys = [v.y for v in self.verts]
        f = self.facts
        f.update(linedefs=len(self.lds), sidedefs=len(self.sds), sectors=len(self.secs), segs=len(segs),
                 subsectors=len(ssecs), nodes=len(nodes), extent=(max(xs) - min(xs), max(ys) - min(ys)))
        self.cap("subsectors (3-nibble leaf ids: ptss, nkleaf, sim.fj)", len(ssecs), 4096)
        self.row("INFO", "build_blocked --subsectors", len(ssecs), "", "pass this (the pin veto's byte arrays; E1M1 682)")
        ex = max(f["extent"])
        from doomfj import monstersight as ms
        self.cap("map extent, far LOS (monstersight: FAR_PIECES*PIECE, 2^13)", ex,
                 min(ms.FAR_PIECES * ms.PIECE, (1 << 13) - 2), "map units, the larger axis (far_margin adds 1)")
        self.cap("map extent sum (mapcompiler: span_x+span_y+512 < 32768)", sum(f["extent"]) + 512, 32768,
                 strict_less=True)
        nib = 2
        while 16 ** nib < len(self.secs):
            nib += 1
        self.row("INFO", "sector-id nibbles (World.sec_nibbles, derived)", nib, "", "3 since M8 L1 works")

    def textures(self):
        e1 = Survey(self.wad, "E1M1", self.asset) if self.m != "E1M1" else None
        def used(s):
            tex = {t.upper() for sd in s.sds for t in (sd.upper, sd.lower, sd.middle) if t and t != "-"}
            flats = {t.upper() for sec in s.secs for t in (sec.floor_tex, sec.ceil_tex)}
            return tex, flats
        t, fl = used(self)
        if e1:
            t1, f1 = used(e1)
            self.row("INFO", "wall textures (new vs E1M1)", "%d (%d new)" % (len(t), len(t - t1)), "",
                     "the texture bank grows with the new ones")
            self.row("INFO", "flats (new vs E1M1)", "%d (%d new)" % (len(fl), len(fl - f1)))
        sky = any(s.ceil_tex.upper() == "F_SKY1" for s in self.secs)
        self.row("INFO", "sky", "yes" if sky else "NO", "", "no sky: the skyoff/skypid tables are absent")

    def specials(self):
        sup = supported_line_specials()
        c = Counter(ld.special for ld in self.lds if ld.special)
        self.facts["line_specials"] = dict(c)
        for s, n in sorted(c.items()):
            name = LINE_SPECIAL_NAMES.get(s, "special %d" % s)
            if s in sup:
                self.row("OK", "line special %d %s" % (s, name), n, "", sup[s])
            elif s in STATIC_SPECIALS:
                self.row("INFO", "line special %d %s" % (s, name), n, "", STATIC_SPECIALS[s])
            else:
                self.row("MISSING", "line special %d %s" % (s, name), n, "", "no implementation: INERT today")
        self.guard("teleport lines (teleport.teleporters: a destination per skill, one teleport per move)",
                   self._teleports)
        from doomfj.combat import SECTOR_HURT, SECRET_SPECIAL
        sc = Counter(sec.special for sec in self.secs if sec.special)
        self.facts["sector_specials"] = dict(sc)
        for s, n in sorted(sc.items()):
            if s in SECTOR_HURT:
                self.row("OK", "sector special %d (damage %d)" % (s, SECTOR_HURT[s]), n)
            elif s == SECRET_SPECIAL:
                self.row("OK", "sector special 9 (secret)", n)
            elif s in (1, 2, 3, 8, 12, 13, 17):
                self.row("INFO", "sector special %d (light)" % s, n, "", "static, as E1M1 (simplification)")
            else:
                self.row("MISSING", "sector special %d" % s, n, "", "no implementation")
        blk = sum(1 for ld in self.lds if ld.flags & gd.ML_SOUNDBLOCK)
        self.row("INFO" if not blk else "WARN", "ML_SOUNDBLOCK lines", blk, "",
                 "the model has them (M8 L0); the fj noise flood refuses them (noisecode) until M8 L5")

    def _teleports(self):
        """M8 C5: the teleport lines as the model bakes them (its refusals are this row's REFUSED); INFO the lines whose
        destination some skill lacks (teleportcode's g_skill test: E1M5) and the lines one move can touch together
        (the first decides, where DOOM's spechit may teleport twice: teleport.py's KNOWN SIMPLIFICATION)"""
        from doomfj import teleport
        tels = teleport.teleporters(self.wad, self.m)
        if not tels:
            return
        self.row("OK", "teleport lines baked (player / monster-only / W1)",
                 "%d / %d / %d" % (len(teleport.player_teleporters(tels)), sum(t.monster_only for t in tels),
                                   len(teleport.once_lines(tels))))
        gated = [(t.line, t.skills) for t in tels if t.skills != teleport.ALL_SKILLS]
        if gated:
            self.row("INFO", "teleport destinations some skill lacks (line, MTF bits): inert there", gated)
        on_mover = teleport_mover_destinations(self.secs, self.lds, self.sds, tels)
        if on_mover["mover"]:
            self.row("OK", "teleport destinations on a mover (line, sector): z read where it stands (M8 C5b)",
                     on_mover["mover"], "", "world._teleport_monster's secs_c; teleportcode's ms_seed_leaf")
        if on_mover["door"]:
            self.row("REFUSED", "teleport destinations on a door (line, sector)", on_mover["door"], "",
                     "world.World refuses them (M8 L4)")
        touch = [(a.line, b.line) for i, a in enumerate(tels) for b in tels[i + 1:] if teleport.neighbours(a, b)]
        if touch:
            self.row("INFO", "teleport line pairs one move can touch (the first decides)", len(touch), "",
                     "%s" % touch[:6])

    def things(self):
        from doomfj.things import single_player
        allth = [t for t in self.wad.things(self.m) if t.type not in gd.NOT_THINGS and single_player(t)]
        c = Counter(t.type for t in allth)
        self.facts["things"] = dict(c)
        from doomfj.combat import GETTABLE
        for ty, n in sorted(c.items()):
            tt = gd.THING_TYPES.get(ty)
            if tt is None:
                self.row("MISSING", "thing type %d" % ty, n, "", "not in gamedata.THING_TYPES: World refuses the map")
                continue
            label = "thing %d %s" % (ty, getattr(tt, "sprite", "") or "")
            if ty in gd.MONSTER_DOOMEDNUMS:
                self.row("OK", label + " (monster %s)" % gd.MONSTER_DOOMEDNUMS[ty], n)
            elif tt.flags & gd.MF_SPECIAL:
                model = ty in GETTABLE
                fj = fj_gives(ty)
                # M8 (gates-ready, gen_dryrun on E1M8): a pickup must be DRAWN too -- one with no sprite
                # (reference_model.THING_SPRITE: E1M8's cell pack 17) is no drawable, and every gate's views
                # (monsters.MonsterViews: pickups by drawable index) KeyError on the map's first frame
                from doomfj.reference_model import THING_SPRITE
                drawn = ty in THING_SPRITE
                st = "OK" if model and fj and drawn else "MISSING"
                self.row(st, label + " (pickup)", n, "", "model %s, fj give %s, sprite %s" % (
                    "yes" if model else "NO", "yes" if fj else "NO", "yes" if drawn else "NO"))
            else:
                self.decor_row(ty, tt, label, n)
        self.guard("hanging things on still sectors", self.hanging)
        # M8 C11: THE MONSTER SLOT IDS, from the WAD (the World refuses E1M6 / E1M7 before its own row runs): a slot per
        # monster of EVERY skill plus the barrels -- dm_id, sp_sid, aim_sid, mon_target / bar_src (2 + slot), p_atk are
        # BYTES in fj with two-level jump16 dispatches (world._code_bits, aim_bits, barrelcode's `dm_id is two nibbles`).
        # DOOM's monsters, the ones gamedata lacks included (3003 the Baron, 3006 the lost soul, ...)
        # M8 C2 (docs/c2-slot-ids.md): past world.SLOT_IDS_NARROW every one of them is THREE nibbles -- the cap is the
        # map's Config.SLOT_ID_BITS (MAP_CONFIG), the width the emitter checks (wall_renderer.check_slot_bits)
        nslot = sum(n for ty, n in c.items() if ty in DOOM_MONSTERS) + c.get(2035, 0)
        from doomfj.world import SLOT_IDS_NARROW, SLOT_IDS_WIDE
        _sbits = map_cfg(Config(), self.m).SLOT_ID_BITS
        self.cap("monster slots + barrels, every skill, from the WAD (slot ids: dm_id, aim_sid, mon_target)",
                 nslot, SLOT_IDS_NARROW if _sbits == 8 else SLOT_IDS_WIDE,
                 "%d-bit slot ids (Config.SLOT_ID_BITS)" % _sbits
                 + ("" if nslot <= SLOT_IDS_NARROW or _sbits == 12 else ": set MAP_CONFIG SLOT_ID_BITS 12 (C2)"))
        # M8 C6 (lesson): a pickup the model and the fj both take can still be INVISIBLE -- its kind needs a sprite
        # prefix (reference_model.THING_SPRITE) whose lump is in the asset wad, or the renderers silently skip it
        from doomfj import reference_model as _RM
        nosprite = []
        for ty in sorted(c):
            tt = gd.THING_TYPES.get(ty)
            if tt is None or not tt.flags & gd.MF_SPECIAL:
                continue
            pre = _RM.THING_SPRITE.get(ty)
            if pre is None or not any(self._has_lump(pre + sfx) for sfx in ("A0", "A1", "A2A8", "A1D1")):
                nosprite.append(ty)
        self.row("MISSING" if nosprite else "OK", "pickup sprite (a gettable kind is drawn)", nosprite or "",
                 "", "reference_model.THING_SPRITE + the asset wad's lump: a pickup with no art is taken unseen")

    def _has_lump(self, name):
        try:
            self.asset.get_data(name)
            return True
        except (KeyError, ValueError, IndexError):
            return False


    def decor_row(self, ty, tt, label, n):
        """M8 C7: a decoration is OK when it is DRAWN (its picture in the asset wad: reference_model.sprite_art); a type
        THING_SPRITE leaves out is not drawn (WARN: E1M1's corpses and hanging body 60, a standing decision -- and
        E1M1's impaled body 26 at (1184, 32), MF_SOLID: an invisible BLOCKER the shipped binary has; drawing it moves
        E1M1's pixels, the owner's call), and one THING_SPRITE names whose lump the asset wad lacks is MISSING (it
        would vanish with no other symptom)"""
        from doomfj.reference_model import THING_SPRITE, ReferenceModel
        kind = label + (" (solid decor)" if tt.solid else " (decor)") + (" hanging" if tt.hangs else "")
        if THING_SPRITE.get(ty) is None:
            self.row("WARN", kind, n, "",
                     "NOT DRAWN: no picture in reference_model.THING_SPRITE" + (" -- an invisible BLOCKER" if tt.solid
                                                                               else ""))
        elif ReferenceModel(Config()).sprite_art(self.asset, ty, {}) is None:
            self.row("MISSING", kind, n, "", "THING_SPRITE %s: no such lump in the asset wad" % THING_SPRITE[ty])
        else:
            self.row("OK", kind, n)

    def hanging(self):
        """M8 C7: every mirror draws a hanging thing at its spawn sector's ceiling - height; a sector that can move
        breaks that (things.hanging_on_movers, the emitter's refusal)"""
        from doomfj.mapcompiler import bake_bsp
        from doomfj.reference_model import ReferenceModel
        from doomfj.things import hanging_on_movers, single_player
        bad = hanging_on_movers(ReferenceModel(Config()), bake_bsp(self.wad, self.m), self.wad, self.m)
        n = sum(1 for t in self.wad.things(self.m)
                if t.type in gd.THING_TYPES and gd.THING_TYPES[t.type].hangs and single_player(t))
        if bad:
            self.row("REFUSED", "hanging things on a moving sector", len(bad), "0",
                     "(wad index, type, sector) %s: the emitter refuses (things.hanging_on_movers)" % (bad[:6],))
        else:
            self.row("OK", "hanging things on still sectors", n)

    def doors_and_movers(self):
        from doomfj import doors, movers
        secs, lds, sds = self.secs, self.lds, self.sds
        st = doors.door_states(secs, lds, sds)
        kinds = doors.door_kinds(secs, lds, sds)
        self.facts["doors"] = len(st)
        self.cap("door states (one nibble)", max((len(v) for v in st.values()), default=0), 16)
        # a door whose special is not a supported door kind is classified "plain" by door_sectors: WRONG behaviour
        sup = supported_line_specials()
        wrong = Counter()
        for ld in lds:
            if ld.special and ld.back not in (0xFFFF, -1) and ld.back < len(sds) and sds[ld.back].sector in st \
                    and ld.special not in sup:
                wrong[ld.special] += 1
        for s, n in sorted(wrong.items()):
            self.row("WRONG", "door behind special %d %s" % (s, LINE_SPECIAL_NAMES.get(s, "")), n, "",
                     "doors.door_sectors makes it a PLAIN DR door (no key, re-closes)")
        self.row("INFO", "door kinds", dict(Counter(kinds.values())))
        geo = doors.door_contact_geo(secs, lds, sds, self.verts)
        slanted = [si for si, (area, _) in geo.items() if area and area[0] == "poly"]
        if slanted:
            self.row("INFO", "doors with slanted or split sides", slanted, "",
                     "contact by every boundary line (M8 L2: doorcode runs the slanted lines)")
        # a CLOSING door some box fits inside needs the centre-inside test, which doorcode runs (M8 C3) for a CONVEX
        # polygon only (doorcode.convex_edges); a door closes when its kind does or a close line moves it
        from doomfj.doorcode import convex_edges
        closing = doors.close_strides(secs, lds, sds) if st else {}
        fit = [si for si, (area, _) in geo.items() if area and area[0] == "poly" and area[2]
               and (not doors.door_stay(kinds[si]) or si in closing)]
        refused = []
        for si in fit:
            try:
                convex_edges(geo[si][0][1])
            except AssertionError:
                refused.append(si)
        if fit:
            self.row("INFO", "closing doors a box fits inside (doorcode: the convex centre-inside test)", fit)
        if refused:
            self.row("REFUSED", "closing doors a box fits inside, not convex (doorcode.convex_edges)", refused, "", "")
        # M8 C3: the door rules every map is checked against (each asserts in the model: a refusal names the line)
        mixed = doors.mixed_card_doors(secs, lds, sds) if st else {}
        if mixed:
            self.row("INFO", "doors whose lines need different cards (front use boxes: doors.keyed_boxes_xy)",
                     sorted(mixed))
        self.guard("WR close lines (doors.close_strides: an open-stay door, one stride)",
                   lambda: doors.close_strides(secs, lds, sds))
        lat = []
        self.guard("S1 door switches that keep a latch (doors.switch_latches: one door each)",
                   lambda: lat.extend(doors.switch_latches(secs, lds, sds)))
        if lat:
            self.row("INFO", "S1 door switches with a latch (a W1 bit each)", len(lat))
        shots = []
        self.guard("GR shot lines (doors.shot_lines: one-sided)", lambda: shots.extend(doors.shot_lines(secs, lds, sds)))
        if shots:
            self.row("INFO", "GR shot lines (aim ids from 0xFF down; guns only; no monster hitscan)",
                     [li for li, _t in shots])
        self.guard("walk-over triggers (per line, every tagged door)",
                   lambda: doors.walkover_triggers(secs, lds, sds, self.verts))
        self.guard("door switches (SR 63 / S1 103)",
                   lambda: doors.switch_door_triggers(secs, lds, sds, self.verts))
        lifts = {}
        self.guard("lift states", lambda: lifts.update(movers.lift_states(secs, lds, sds)))
        sw = {}
        self.guard("floor-switch sectors", lambda: sw.update(movers.switch_sectors(secs, lds, sds)))
        self.facts.update(lifts=len(lifts), switch_sectors=len(sw))
        groups = []
        self.guard("floor groups (movers.floor_groups: one per tag)",
                   lambda: groups.extend(movers.floor_groups(secs, lds, sds)))
        if groups:
            self.row("INFO", "floor groups (a state cell each: movers.switch_cell)", len(groups), "",
                     "specials %s" % sorted({g.special for g in groups}))
        cells = {}
        self.guard("mover table", lambda: cells.update({si: c for si, (c, _h) in
                                                       movers.mover_table(secs, lds, sds).items()}))
        dyn = {si: "door" for si in st}
        dyn.update({si: "lift" for si in lifts})
        dyn.update({si: ("switch" if si in sw else "floor") for si in cells if si not in lifts})
        pairs = Counter()
        lines = []
        self.facts["dyn_pairs"] = lines        # M8 C4: `world` runs the readers over each of them
        for i, ld in enumerate(lds):
            if ld.back in (0xFFFF, -1) or ld.back >= len(sds):
                continue
            a, b = sds[ld.front].sector, sds[ld.back].sector
            if a in dyn and b in dyn and a != b:
                k = "-".join(sorted((dyn[a], dyn[b])))
                if "door" not in k and cells.get(a) == cells.get(b):
                    k += " (one cell)"
                pairs[k] += 1
                lines.append((i, a, b, k))
        for k, n in sorted(pairs.items()):
            if k == "door-door":            # wall_renderer._seg_door: one door a seg
                self.row("REFUSED", "lines between two dynamic sectors: %s" % k, n, "",
                         "the renderer's door switch addresses one door -- linedefs %s"
                         % [x[0] for x in lines if x[3] == k][:8])
        # M8 C4: every other pair is HANDLED -- the renderer's pair switch (a door and a mover: E1M3's 519 / 1077; two
        # movers: the PAIR of cells), and the readers (sight / noise / missiles: monstersight.line_states; collision:
        # collision.mover_line_states, a door line beside a mover by `collision_cells_fj`'s door_mover arm) take the cell
        # the opening depends on. `world` runs those functions on each line: a pair they refuse is a REFUSED row there

    def world(self):
        from doomfj.world import World
        holder = {}

        def build():
            holder["w"] = World(self.wad, self.m, strict=True)
        self.guard("World(strict=True) builds", build)
        w = holder.get("w")
        if w is None:
            # the counts below are still worth having: retry with the thing types gamedata lacks left out (reported
            # above as MISSING), so one unknown decoration does not hide an overflowing monster count
            unknown = {t.type for t in self.wad.things(self.m)} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
            saved = gd.NOT_THINGS
            try:
                gd.NOT_THINGS = frozenset(saved | unknown)
                self.guard("World(strict=True) without the unknown types %s" % sorted(unknown), build)
            finally:
                gd.NOT_THINGS = saved
            w = holder.get("w")
            if w is None:
                # M8 C2 (docs/c2-slot-ids.md): the runtime-ids row needs only the level's things -- count its droppers
                # from the WAD's lists (World's own `level_things`) when the World refuses for another reason (E1M7)
                gd.NOT_THINGS = frozenset(saved | unknown)
                try:
                    from doomfj.world import level_things
                    _t, mon, bar = level_things(self.wad, self.m)
                finally:
                    gd.NOT_THINGS = saved
                self.facts["_level_things"] = (_t, mon, bar)
                return
            self.row("INFO", "the counts below exclude the unknown thing types", sorted(unknown))
        else:
            self.row("OK", "World(strict=True) builds")
        self.facts["_world"] = w
        self._readers(w)
        self.monster_extensions(w)                          # M8 C8: the lost soul, the extension rows, the pain bits
        nmon, nbar = len(w.mon_things), len(w.barrel_things)
        self.facts.update(monsters=nmon, barrels=nbar, pickups=len(w.pickup_things), secrets=len(w.secret_sectors),
                          sound_nodes=getattr(w, "nsound", "?"))
        self._slot_caps(nmon, nbar)
        from doomfj.world import aim_bits
        self.cap("monsters + barrels -> aim_sid (world.aim_bits: the fj cell)", nmon + nbar,
                 0xFF if aim_bits(w.layout) <= 8 else 0xFFF, "aim_sid %d bits" % aim_bits(w.layout))
        # M8 C10: a map with no barrel is a supported case (barrelcode: no per-barrel stub, its cells one dead slot)
        self.row("OK" if nbar else "INFO", "barrels (barrelcode: none is supported, M8 C10)", nbar)
        from doomfj.statcode import count_digits, count_nibbles
        # M8 C2: the counters are 12-bit cells on a map past a byte (world.count_bits); three digits hold 999
        cmax = 0xFF if count_nibbles(w) == 2 else 999
        self.cap("monsters on LEVEL COMPLETE (st_kill: statcode.count_nibbles / count_digits)", nmon, cmax,
                 "%d nibbles, %d digits a count" % (count_nibbles(w), count_digits(w)))
        from doomfj import statcode
        items = sum(1 for t in w.pickup_things if statcode.counts_item(t.type))
        self.cap("COUNTITEM pickups on LEVEL COMPLETE (st_item: statcode.count_nibbles)", items, cmax)
        self.cap("secret sectors on LEVEL COMPLETE (p_secretcount 4 bits, 1 digit)", len(w.secret_sectors), 9)
        self.cap("pickups (pkxyz index, 2 nibbles)", len(w.pickup_things), 256, strict_less=True)
        self.guard("statcode.check_world", lambda: statcode.check_world(w) if hasattr(statcode, "check_world") else None)
        from doomfj import barrelcode
        self.guard("barrels: level start the same on every skill (barrelcode.check_model_rules)",
                   lambda: barrelcode.check_model_rules(w, (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)))
        # M8 F1.3 (docs/f1-big-map-widths.md 9): an item on a mover's floor touches at the live floor (pk_mbox) and
        # renders runtime (things.mover_leaves); a door's floor never moves
        moving = [(t.type, w.pickup_sector[i]) for i, t in enumerate(w.pickup_things) if w.pickup_on_mover[i]]
        self.row("INFO", "pickups on a mover floor (lootcode.pk_mbox: the live floor)", len(moving), "",
                 "" if not moving else "(type, sector) %s" % moving[:8])
        self.monsters_c8(w)
        from doomfj.monstermove import static_blockers
        _things, var = static_blockers(w)
        # M8 F1.2: a solid decoration some skill lacks is a `mc_don` presence flag, set at NEW GAME (monstermove.mc_don_restart)
        self.row("OK", "solid decorations some skill lacks (monstercode: mc_don at NEW GAME)",
                 len(var), "", "" if not var else "mc_don flags for decor_solid indices %s" % var[:10])

    def weapon_light(self):
        """M8 (gates-ready, gen_dryrun on E1M9): the weapon sprite is lit by ONE baked colormap row
        (hudcode.game_hud_parts asserts it); a sector dark enough for another row refuses every game-tier tool"""
        from doomfj import hud
        from doomfj.config import GAME_CFG
        from doomfj.reference_model import ReferenceModel
        rm = ReferenceModel(GAME_CFG)
        rows = {}
        for i, sec in enumerate(self.secs):
            rows.setdefault(hud.psprite_light_row(rm, sec.light), []).append(i)
        if len(rows) == 1:
            self.row("OK", "weapon light: one colormap row", 1, 1)
        else:
            odd = sorted((r, v[:6]) for r, v in rows.items() if len(v) < max(len(x) for x in rows.values()))
            self.row("REFUSED", "weapon light: colormap rows", len(rows), 1,
                     "hudcode bakes one row; sectors on the others (row, sectors): %s" % odd)

    def monster_extensions(self, w):
        """M8 C8 (doomfj.lostsoul / soulcode; the lessons of the lost soul): the extension states' borrowed thing indices
        (gamedata.EXT_ALIAS_CODES: a new monster's states take weapon-only states' indices -- check_thing_aliases proves
        each; a later monster can run out of them), damagecode's pain classes (one nibble of dmrnd: at most 4
        painchances on a map), and a map's souls -- their 16.16 heights (soulcode.check_model_rules) and a teleport line
        beside them (EV_Teleport's z: the model's, not yet the fj's)"""
        bad = gd.check_thing_aliases()
        self.row("OK" if not bad else "REFUSED",
                 "extension states' borrowed thing indices (gamedata.EXT_ALIAS_CODES, check_thing_aliases)",
                 len(gd.EXT_STATE_NAMES), "", "; ".join(bad[:3]))
        from doomfj.damagecode import pain_classes, profiles
        self.cap("monster pain classes (damagecode: dmrnd's pain bits, one nibble)",
                 len(pain_classes(profiles(w, gib=True)[0])), 4)
        souls = getattr(w, "soul_slots", ())
        if not souls:
            return
        from doomfj import soulcode
        self.row("OK", "lost souls (MT_SKULL: doomfj.lostsoul, soulcode)", len(souls))
        self.guard("lost souls: soulcode.check_model_rules (16.16 heights, radius 16)",
                   lambda: soulcode.check_model_rules(w))
        tels = getattr(w, "teleports", ())
        self.row("REFUSED" if tels else "OK", "lost souls beside teleport lines (fj: EV_Teleport's soul z unwired)",
                 len(tels), "", "wall_renderer refuses a map with both until soulcode wires tp_hit's z" if tels else "")

    def monsters_c8(self, w):
        """M8 C8 (the Baron): what the fj bakes per map about its monsters -- A_BossDeath's floor group (E1M8's tag 666),
        the two radius classes (world.radius_classes), the ONE monster missile (projcode.missile_of_world) -- each by
        the emitters' own functions, so a map that trips one is caught here, not after an emission"""
        from doomfj import gamedata as _gd
        names = {mi.name for mi in w.mon_info}
        boss = _gd.BOSS_MAPS.get(self.m.upper())
        tag666 = [s for s, sec in enumerate(self.secs) if sec.tag == 666]
        if boss and boss[0] in names:
            def bossrow():
                g = w.boss_group
                grp = w.floor_groups[g]
                self.row("OK", "A_BossDeath (%s's last death: tag %d, %s)" % (boss[0], boss[1], boss[2]),
                         "group %d, sectors %s" % (g, list(grp.sectors)), "",
                         "monstercode.boss_lines fires its timer; the group's lines: specials %s" % grp.special)
            self.guard("A_BossDeath (%s's last death: tag %d)" % (boss[0], boss[1]), bossrow)
        elif tag666:
            self.row("INFO", "tag 666 sectors on a map without its boss", tag666, "",
                     "A_BossDeath acts on %s only (gamedata.BOSS_MAPS): inert here" % sorted(_gd.BOSS_MAPS))
        from doomfj.world import radius_classes
        self.guard("monster radius classes (world.radius_classes: 30 and one other)",
                   lambda: self.row("OK", "monster radius classes (world.radius_classes)",
                                    radius_classes(w.mon_radius[:w.layout.nmon]), "",
                                    "radii %s" % sorted(set(w.mon_radius[:w.layout.nmon]))))
        from doomfj.projcode import missile_of_world
        self.guard("one monster missile species (projcode.missile_of_world: the pool bakes one)",
                   lambda: self.row("OK", "one monster missile species (projcode.missile_of_world)",
                                    missile_of_world(w) or "MT_TROOPSHOT"))
        heights = sorted(set(w.mon_height[:w.layout.nmon]))
        self.row("OK" if len(heights) <= 1 else "REFUSED", "one monster height (try_move_mon / kb_mmove bake it)",
                 heights)
        ext = [n for n in _gd.EXT_MONSTER_TYPES if n in names]
        if ext:
            self.row("INFO", "extension monster types (gamedata.THING_STATE_INDEX: borrowed state indices)", ext)

    def _readers(self, w):
        """M8 C4: THE MOVERS' READERS, run on the map (each the model's own function, in its own guard): every line
        between two dynamic sectors through the cell its opening depends on (sight / noise / missiles), the collision
        cells' per-state openings and low floors, the missile cells (a lift line that shuts a fireball), the nukage
        query's separation from the instant floors and the S1 texture-change lines -- each was an emit-time refusal
        E1M3 / E1M4 would have met 30 minutes into an emission"""
        from doomfj import collision, lootcode, monstersight, movers, noisecode, projcode
        lines = self.facts.get("dyn_pairs", [])
        handled = Counter()

        def check(name, fn):            # an OK row when it passes (lesson P6: a refusal-only guard proves nothing)
            n = len(self.rows)
            self.guard(name, fn)
            if len(self.rows) == n:
                self.row("OK", name)

        def pairs():
            for li, a, b, k in lines:
                if k != "door-door":
                    monstersight.line_states(w, a, b)
                    handled[k] += 1
        check("lines between two dynamic sectors (monstersight.line_states: the cell the opening reads)", pairs)
        for k, n in sorted(handled.items()):
            self.row("INFO", "lines between two dynamic sectors: %s" % k, n, "",
                     "handled: the renderer's pair switch, the readers through the cell the opening depends on -- "
                     "linedefs %s" % [x[0] for x in lines if x[3] == k][:8])
        msecs = movers.mover_secs(w.mover_table, w.secs, movers.change_table(w.floor_groups))
        mcell = {si: c for si, (c, _h) in w.mover_table.items()}
        for fn in (max, min):
            check("collision cells: mover lines' %s floor (collision.mover_line_states)"
                  % ("opening" if fn is max else "low"),
                  lambda fn=fn: collision.mover_line_states(w.lds, w.sds, msecs, mcell, fn))
        check("sight segments (monstersight.sight_segments)", lambda: monstersight.sight_segments(w))
        check("sound edges (noisecode.sound_edges)", lambda: noisecode.sound_edges(w))
        check("missile cells (projcode.missile_rows: a mover line shut below a pass state)",
              lambda: projcode.missile_rows(w))
        check("nukage vs the movers (lootcode.nukage_lines)", lambda: lootcode.nukage_lines(w, "root"))

    def _slot_caps(self, nmon: int, nbar: int, src: str = ""):
        """M8 C2 (docs/c2-slot-ids.md): the monster + barrel SLOT IDS against the map's Config.SLOT_ID_BITS (MAP_CONFIG:
        254 slots at 8 bits, SLOT_IDS_WIDE at 12), and an INFO row with the width the counts need (world.slot_nibbles)
        -- a mismatch is what the emitter refuses"""
        from types import SimpleNamespace
        from doomfj.world import SLOT_IDS_NARROW, SLOT_IDS_WIDE, slot_nibbles
        bits = map_cfg(Config(), self.m).SLOT_ID_BITS
        self.cap("monster slots + barrels (slot ids, Config.SLOT_ID_BITS: aim_sid, dm_id, the codes)", nmon + nbar,
                 SLOT_IDS_NARROW if bits == 8 else SLOT_IDS_WIDE, "%d-bit slot ids%s" % (bits, src))
        need = 4 * slot_nibbles(SimpleNamespace(nmon=nmon, nbarrel=nbar)) if nmon + nbar <= SLOT_IDS_WIDE else None
        self.row("INFO", "slot id bits needed (world.slot_nibbles)", need if need else "> 12", "",
                 "MAP_CONFIG has %d%s" % (bits, "" if need == bits else
                                         ": set SLOT_ID_BITS %s (C2)" % need if need else ": past three nibbles"))

    def render_caps(self):
        from doomfj import wall_renderer as WR
        from doomfj.mapcompiler import bake_bsp
        from doomfj.reference_model import ReferenceModel
        from doomfj.things import baked_thing_mask, drawable_things, mover_leaves, mover_mask_kw
        rm = ReferenceModel(Config())
        cmap = bake_bsp(self.wad, self.m)
        draw, draw_idx = drawable_things(rm, self.wad.things(self.m), self.asset, {})
        baked = baked_thing_mask(rm, cmap, draw, WR.MONSTER_TYPES,     # M8 F1.3: things on movers run
                                 **mover_mask_kw(rm, cmap, draw, mover_leaves(self.wad, self.m, cmap)))
        nt = len({i for i, b in zip(draw_idx, baked) if not b})
        # M8 C11: the emitter's own bound (wall_renderer.check_slot_ids): a map with a per-frame SPR_SLOT_CAP (F1.4,
        # MAP_CONFIG) is bounded by construction; without one, every skill's drawable things must fit the byte
        _cfg = map_cfg(Config(), self.m)
        try:
            WR.check_slot_ids(len(draw), 0, 0, _cfg)
            self.row("OK", "drawable things, every skill (1-byte fragment slot id)", len(draw),
                     "cap %d a frame" % _cfg.SPR_SLOT_CAP if _cfg.SPR_SLOT_CAP else "< 256",
                     "SPR_SLOT_CAP (MAP_CONFIG): past it the farthest drop, DOOM's MAXVISSPRITES rule"
                     if _cfg.SPR_SLOT_CAP else "")
        except AssertionError:
            self.row("OVER", "drawable things, every skill (1-byte fragment slot id)", len(draw), "< 256",
                     "give the map a SPR_SLOT_CAP (config.MAP_CONFIG; docs/f1-big-map-widths.md 1)")
        # M8 F1.5 (docs/f1-runtime-ids.md): the lists' id width is the map's Config.LIST_ID_BITS (MAP_CONFIG) -- 8 bits
        # hold 254 ids, 12 hold 4,094 (things.list_max); the caps below are against the map's OWN width
        from doomfj.things import list_bits, list_max
        lbits = map_cfg(Config(), self.m).LIST_ID_BITS
        self.cap("runtime things (thing lists, Config.LIST_ID_BITS)", nt, list_max(lbits),
                 "%d-bit lists; plus mobiles and drops: the next row" % lbits)
        # F1 item 12 (docs/f1-big-map-widths.md 0.3): the lists hold the runtime things, the fireball and effect pools
        # and every monster drop -- the sum monstercode.p31_parts bounds by list_max(LIST_ID_BITS)
        def ids():
            from doomfj.world import FIREBALL_POOL, FX_POOL, World
            if self.facts.get("_world") is None and self.facts.get("_level_things"):
                # M8 C2: the World refused for another reason -- the droppers from the WAD's monsters (combat's rule)
                from doomfj.combat import DROP_ITEM
                ndrop = sum(1 for t in self.facts["_level_things"][1]
                            if DROP_ITEM.get(gd.DROPS.get(gd.MONSTER_DOOMEDNUMS[t.type])) is not None)
            else:
                from doomfj.barrelcode import droppers
                ndrop = len(droppers(self.facts.get("_world") or World(self.wad, self.m, monsters="idle")))
            n = nt + FIREBALL_POOL + FX_POOL + ndrop
            self.cap("runtime ids: things + pools + drops (list cells, Config.LIST_ID_BITS)", n, list_max(lbits),
                     "%d-bit lists (MAP_CONFIG)" % lbits)
            need = list_bits(n) if n <= list_max(12) else None
            self.row("INFO", "list id bits needed (things.list_bits)", need if need else "> 12", "",
                     "MAP_CONFIG has %d%s" % (lbits, "" if need == lbits else
                                             ": set LIST_ID_BITS %s (F1.5)" % need if need else ": past 4,094 ids"))
        self.guard("runtime ids: things + pools + drops (list cells, Config.LIST_ID_BITS)", ids)
        self.guard("marking segs < DEG_PNEAR", lambda: self._marking(WR, cmap))
        pid_lo = len({((s.ceil_h, s.light, s.ceil_tex.upper()), (s.floor_h, s.light, s.floor_tex.upper()))
                      for s in self.secs})
        cfg = map_cfg(Config(), self.m)
        # docs/level-lessons.md: E1M2's plane ids (376 > 255) were found by an emission; the measured real/estimate
        # ratios are 1.46 (E1M1) and 1.25 (E1M2), so x1.5 past the cap makes this a WARN, not a footnote
        self.row("WARN" if pid_lo * 1.5 >= 16 ** cfg.PID_NIBBLES else "INFO",
                 "plane pairs (ESTIMATE, no direction; measured: m4_bands.py)", pid_lo,
                 "< %d" % 16 ** cfg.PID_NIBBLES,
                 "E1M1 est 152 -> 222 real; E1M2 329 -> 411. PID_NIBBLES %d for this map%s"
                 % (cfg.PID_NIBBLES, "" if pid_lo * 1.5 < 16 ** cfg.PID_NIBBLES or cfg.PID_NIBBLES >= 3
                    else ": likely needs 3 (MAP_CONFIG)"))

    def _marking(self, WR, cmap):
        from doomfj import doors
        from doomfj.reference_model import apply_sector_heights
        st = doors.door_states(self.secs, self.lds, self.sds)
        variants = [self.secs]
        for si, stops in st.items():
            for k in range(len(stops)):
                variants.append(apply_sector_heights(self.secs, doors.heights_for_states(
                    self.secs, self.lds, self.sds, {si: k})))
        # and every lift stop and the floor switch fired (the emitter's _msecs: a seg marks in ANY state of its mover)
        from doomfj import movers
        for si, stops in movers.lift_states(self.secs, self.lds, self.sds).items():
            variants += [apply_sector_heights(self.secs, {si: (h, self.secs[si].ceil_h)}) for h in stops]
        # M8 F1.3: every floor group at every state (E1M1: the switch fired, as before)
        for g in movers.floor_groups(self.secs, self.lds, self.sds):
            for k in range(1, g.n):
                variants.append(apply_sector_heights(self.secs, {si: (h[k], self.secs[si].ceil_h)
                                                                 for si, h in g.heights}))
        marking = sum(1 for seg in cmap.segs if self.lds[seg.linedef].back != -1
                      and any(WR.seg_marks_in(self.lds, self.sds, seg, v) for v in variants))
        cfg = map_cfg(Config(), self.m)       # M8 C11: the map's n_tsv width (MAP_CONFIG TSV_NIBBLES; E1M7 4)
        self.cap("marking two-sided segs (n_tsv %d nibbles)" % cfg.TSV_NIBBLES, marking, cfg.TSV_BUDGET,
                 "" if marking < cfg.TSV_BUDGET else "raise the map's TSV_NIBBLES (config.MAP_CONFIG)", strict_less=True)

    # ------------------------------------------------------------------ docs/level-lessons.md: checks a mistake earned
    # Each check below is a lesson E1M1 or E1M2 paid for (a dead build, a gate failure, a CR blocker, a playtest
    # finding), moved to the cheap end. Each calls the model's own functions, as every check above, and each is a row
    # of docs/level-lessons.md; tests/host/test_level_lessons.py runs each with a negative control (R9).

    def lessons(self):
        for name, fn in (("door clearance", self._door_clearance),
                         ("back sides without ML_TWOSIDED", self._twosided_flags),
                         ("the door neighbour rule", self._neighbour_rule),
                         ("NEW GAME restarts the floor groups", self._restart_floors),
                         ("the renderer's per-seg machines", self._seg_machines),
                         ("the openings of lines between dynamic sectors", self._dyn_openings),
                         ("slanted W1 floor lines", self._slanted_floor_lines),
                         ("barrel chains", self._barrel_chains),
                         ("the oracle's thvis mirror", self._vis_mirror),
                         ("the per-map feature flags", self._feature_flags),
                         ("the state byte", self._state_byte),
                         ("the pool and the RAM, projected", self._projection)):
            self.guard("lesson: " + name, fn)

    def _door_clearance(self):
        """E1M2 playtest (a0af8d4f): blue door 54 opened 12 units over its floor -- the legacy neighbour rule read a
        one-sided line's missing back as the last sidedef's sector -- and could never be passed. Every door must
        reach the player's 56-unit gap at its top state (`doors.pass_state`, the threshold fj bakes per door)."""
        from doomfj import doors
        st = doors.door_states(self.secs, self.lds, self.sds)
        never = [(si, self.secs[si].floor_h, st[si][-1]) for si in sorted(st)
                 if doors.pass_state(self.secs, self.lds, self.sds, si) >= len(st[si])]
        self.row("OK" if not never else "WARN", "doors the player can pass when open (doors.pass_state, 56 units)",
                 "%d of %d" % (len(st) - len(never), len(st)), "all",
                 "" if not never else "NEVER passable (sector, floor, open ceiling): %s -- check the open height "
                                      "against DOOM's (the E1M2 door 54 lesson)" % never[:8])

    def _twosided_flags(self):
        """CR of #148 (#149 item 1): DOOM's getNextSector skips a line without ML_TWOSIDED; `lights` tests the flag,
        `doors.two_sided_neighbours` tests the back side -- the two agree only while no line has a back side without
        the flag (E1M2: none)"""
        bad = [i for i, ld in enumerate(self.lds) if ld.back not in (0xFFFF, -1) and ld.back < len(self.sds)
               and not ld.flags & gd.ML_TWOSIDED]
        self.row("OK" if not bad else "WARN", "lines with a back side but no ML_TWOSIDED", len(bad), "0",
                 "" if not bad else "the doors' and the lights' neighbour rules part on linedefs %s" % bad[:8])

    def _neighbour_rule(self):
        """CR of #148 (#149 item 1): the doors' neighbour rule is the map's config.MAP_CONFIG flag DOOR_NEIGHBOURS
        (doors.door_rule), no longer a (sectors, linedefs, sidedefs) fingerprint. "legacy" is E1M1's frozen deviation
        (#104 F1, its pid budget): any other map that asks for it opens its doors by the wrong rule; and
        door_neighbours must return the rule the flag names on this map's own records"""
        from doomfj import doors
        rule = doors.door_rule(self.m)
        got = doors.door_neighbours(self.secs, self.lds, self.sds)
        want = (doors.neighbours if rule == "legacy" else doors.two_sided_neighbours)(self.lds, self.sds)
        if got != want:
            self.row("WRONG", "door neighbour rule (doors.door_neighbours)", rule, "the flag's rule",
                     "door_neighbours does not follow MAP_CONFIG DOOR_NEIGHBOURS on %s" % self.m)
        elif rule == "legacy" and self.m.upper() != "E1M1":
            self.row("WRONG", "door neighbour rule (doors.door_neighbours)", "legacy", "two-sided",
                     "%s's MAP_CONFIG asks for E1M1's legacy rule: its doors open by it" % self.m)
        else:
            self.row("OK", "door neighbour rule (doors.door_neighbours)",
                     "legacy (E1M1, MAP_CONFIG DOOR_NEIGHBOURS)" if rule == "legacy" else "DOOM's two-sided")

    def _restart_floors(self):
        """CR of #146 (#147): `wall_renderer.restart_lines` zeroes `fswitch` only when the map has a lift -- a map with
        floor groups and no lift keeps its floors moved across NEW GAME and the restart after death"""
        from types import SimpleNamespace
        from doomfj import movers
        from doomfj.wall_renderer import restart_lines
        groups = movers.floor_groups(self.secs, self.lds, self.sds)
        check = "NEW GAME restarts the floor groups (wall_renderer.restart_lines)"
        if not groups:
            self.row("OK", check, 0, "", "no floor group")
            return
        nlift = len(movers.lift_states(self.secs, self.lds, self.sds))
        common, _sk = restart_lines(SimpleNamespace(x=0, y=0, angle=0), 0, [], [], 0, [], nlift=nlift,
                                    nfs=movers.fswitch_nibbles(groups), nfloor=len(groups))
        ok = any("fswitch" in ln for ln in common)
        self.row("OK" if ok else "WRONG", check, "%d groups, %d lifts" % (len(groups), nlift), "fswitch zeroed",
                 "" if ok else "fswitch is zeroed only with a lift: the floors stay moved after NEW GAME (#147)")

    def _machines(self):
        """the door / mover tables the game tier's emitter builds (emit_wall_renderer's `_dst_tbl`, `_dsecs`, `_mtab`,
        `_msecs`, `_mcell`), by the same model calls"""
        if "_machines" not in self.facts:
            from doomfj import doors, movers
            from doomfj.reference_model import apply_sector_heights
            secs, lds, sds = self.secs, self.lds, self.sds
            dst = doors.door_states(secs, lds, sds)
            dmax = max((len(v) for v in dst.values()), default=0)
            dsecs = [apply_sector_heights(secs, doors.heights_for_states(
                secs, lds, sds, {si: min(k, len(s) - 1) for si, s in dst.items()})) for k in range(dmax)]
            mtab = movers.mover_table(secs, lds, sds)
            self.facts["_machines"] = (dst, dsecs,      # M8 C4: the texture-change floors' flats, as the emitter
                                       movers.mover_secs(mtab, secs, movers.change_table(movers.floor_groups(
                                           secs, lds, sds))),
                                       {si: c for si, (c, _h) in mtab.items()})
        return self.facts["_machines"]

    def _line_machines(self, f, b):
        """emit_wall_renderer's `_seg_machines` for a seg between sectors f and b (lights aside): [(sector, its
        per-state sector lists)], or the refusal (`_seg_door` / `_seg_movers`' asserts) as a string"""
        dst, dsecs, msecs, mcell = self._machines()
        if f in dst and b in dst:
            return "a door on both sides (%d, %d)" % (f, b)
        door = f if f in dst else (b if b in dst else None)
        hit = tuple(sorted({x for x in (f, b) if x in msecs}))
        if len(hit) == 2 and mcell[hit[0]] == mcell[hit[1]] and msecs[hit[0]] == msecs[hit[1]]:
            hit = hit[:1]                                       # one machine (a floor group's sectors)
        # M8 C4: a door and a mover on one seg are a PAIR, the door first (wall_renderer._seg_machines)
        out = [(door, dsecs[:len(dst[door])])] if door is not None else []
        out += [(m, msecs[m]) for m in hit]
        if len(out) > 2:
            return "a door (%d) and two movers %s on one seg" % (door, list(hit))
        return out

    @staticmethod
    def shut_gate(st, dims):
        """emit_wall_renderer's `_seg_dual_cell` on a dynamic seg's shut pattern `st` (one bool per state, the first
        machine's state major) over machines of `dims` states: "never" (a marking seg), "every" (the solid path,
        `_seg_closed_moving`: the CR of #146's lines), the index of the machine whose state 0 is EXACTLY the shut set
        (the one-op `hex.if0` gate), or None -- the emitter refuses it. M8 C4: the emitter's own rule now
        (`wall_renderer.seg_shut_gate`): (machine, shut mask) when one machine's state decides it"""
        from doomfj.wall_renderer import seg_shut_gate
        return seg_shut_gate(st, dims)

    def _seg_machines(self):
        """CR of #146 (BLOCKING, 9b8ef2c0): four E1M2 lines shut at EVERY floor state took the marking path in fj and
        the solid one in the oracle -- no gate looked there. The emitter now refuses an open-then-shut seg and a seg
        on a door and a mover; this runs the same classification over every two-sided line in seconds"""
        refused, every = [], []
        for i, ld in enumerate(self.lds):
            if ld.back in (0xFFFF, -1) or ld.back >= len(self.sds):
                continue
            f, b = self.sds[ld.front].sector, self.sds[ld.back].sector
            ms = self._line_machines(f, b)
            if isinstance(ms, str):
                refused.append((i, ms))
                continue
            if not ms:
                continue
            if len(ms) == 1:
                svs = ms[0][1]
            else:
                (_a, sva), (mb, svb) = ms
                svs = []
                for sa in sva:
                    for sb in svb:
                        sv = list(sa)
                        sv[mb] = sb[mb]
                        svs.append(sv)
            st = [min(sv[f].ceil_h, sv[b].ceil_h) <= max(sv[f].floor_h, sv[b].floor_h) for sv in svs]
            g = self.shut_gate(st, [len(m[1]) for m in ms])
            if g is None:
                refused.append((i, "shut at states %s of %s" % ([k for k, x in enumerate(st) if x],
                                                               [m[0] for m in ms])))
            elif g == "every":
                every.append(i)
        self.row("OK" if not refused else "REFUSED",
                 "dynamic segs the renderer can gate (wall_renderer._seg_dual_cell / _seg_movers)", len(refused), "0",
                 "" if not refused else "linedefs %s" % refused[:6])
        if every:
            self.row("INFO", "dynamic segs shut at EVERY state (the solid path: _seg_closed_moving)", len(every), "",
                     "linedefs %s" % every[:10])

    def _dyn_openings(self):
        """CR of #142 (#143): the survey's "lines between two dynamic sectors" note was hand-written; these are the
        readers' OWN functions -- collision.mover_line_states (the opening and the low floor) and
        monstersight.line_states (sight, sound and missiles) -- each refusing a line whose value needs both cells"""
        from doomfj.collision import mover_line_states
        _dst, _ds, msecs, mcell = self._machines()
        n0 = len(self.rows)
        for fn in (max, min):
            self.guard("collision.mover_line_states(%s): every mover line read through one cell" % fn.__name__,
                       lambda fn=fn: mover_line_states(self.lds, self.sds, msecs, mcell, fn))
        if len(self.rows) == n0:
            self.row("OK", "collision.mover_line_states (max, min): every mover line read through one cell")
        w = self.facts.get("_world")
        if w is None:
            self.row("INFO", "monstersight.line_states over the dynamic lines", "", "", "needs the World (above)")
            return
        from doomfj.monstersight import line_states
        dyn = set(w.door_order) | set(w.mover_order)
        bad, n = [], 0
        for i, ld in enumerate(self.lds):
            if ld.back in (0xFFFF, -1) or ld.back >= len(self.sds):
                continue
            a, b = self.sds[ld.front].sector, self.sds[ld.back].sector
            if a == b or not ({a, b} & dyn):
                continue
            n += 1
            try:
                line_states(w, a, b)
            except AssertionError as e:
                bad.append((i, ("%s" % e)[:80]))
        self.row("OK" if not bad else "REFUSED", "monstersight.line_states: every dynamic line read through one cell",
                 "%d of %d" % (n - len(bad), n), "all", "" if not bad else "linedefs %s" % bad[:4])

    def _slanted_floor_lines(self):
        """CR of #146 (#147): a slanted W1 floor line crosses by `movers.crossed_shape` (the bounding box grown by
        the radius), a slanted door line by DOOM's spechit straddle (`doors.crossed`) -- each mirror matches its own
        model, so no gate sees the difference from DOOM; the playtest should"""
        from doomfj import movers
        groups = movers.floor_groups(self.secs, self.lds, self.sds)
        slanted = [li for li, ld in enumerate(self.lds) if ld.special in movers.FLOOR_WALK_SPECIALS and ld.tag
                   and self.verts[ld.v1].x != self.verts[ld.v2].x and self.verts[ld.v1].y != self.verts[ld.v2].y]
        n = sum(1 for _g, shape in movers.floor_walk_triggers(self.lds, self.verts, groups) if shape[0] == "d")
        assert n == len(slanted), (n, slanted)
        self.row("OK" if not slanted else "WARN", "slanted W1 floor lines (movers.crossed_shape: not DOOM's rule)",
                 len(slanted), "0", "" if not slanted else "linedefs %s: crossed by the grown box, not spechit -- "
                                                           "play-test them" % slanted[:8])

    def _barrel_chains(self):
        """F1.2 / emit_check's `barrel-chains-static` stand-in: a barrel chain whose trace only a DYNAMIC line touches
        is refused by `barrelcode.chain_pairs` at emit time (its LOS would depend on the tic)"""
        w = self.facts.get("_world")
        if w is None or not w.barrel_things:
            return
        from doomfj import barrelcode
        pairs = barrelcode.chain_pairs(w)
        self.row("OK", "barrel chains (barrelcode.chain_pairs: no chain behind a dynamic line)",
                 sum(len(v) for v in pairs.values()))

    def _vis_mirror(self):
        """CR of #142 (BLOCKING, cd969f2): the oracle's thvis mirror (`MonsterViews.vis_state`) knew pickups and
        barrels only; E1M2's hard-only lamp got a slot from `things.vanishable_slots` and every gate reading thvis
        raised KeyError. The mirror runs here at every skill, against the slot count the emitter declares"""
        w = self.facts.get("_world")
        if w is None:
            self.row("INFO", "the oracle's thvis mirror (MonsterViews.vis_state)", "", "", "needs the World (above)")
            return
        from types import SimpleNamespace
        from doomfj.monsters import MonsterViews
        from doomfj.wall_renderer import SKILLS
        # the mirror keys every World thing by its DRAWABLE index (things.drawable_things: art in the sprite wad) -- a
        # World thing with no art (E1M8's cell pack 17: a pickup whose type names no sprite) has none
        cache = {}
        noart = sorted({t.type for t in list(w.mon_things) + list(w.pickup_things) + list(w.barrel_things)
                        if w.rm.sprite_art(self.asset, t.type, cache) is None})
        self.row("OK" if not noart else "REFUSED", "World things with sprite art (things.drawable_things)",
                 len(noart), "0", "" if not noart else "types %s: in the World, never drawn; the oracle's mirror "
                                                       "cannot key them" % noart)
        mv = MonsterViews(w.rm, w.mw, self.m, self.asset, w)
        n = len(mv.vis_slots) + len(mv.rt_pickups)
        for sk in SKILLS:
            w.reset(sk)
            got = len(mv.vis_state(SimpleNamespace(world=w))["thvis"])
            assert got == n, "skill %d: the oracle reads %d thvis slots of %d" % (sk, got, n)
        other = len(set(mv.vis_slots) - set(mv.pdi) - set(mv.bdi))
        self.row("OK", "the oracle's thvis mirror reads every slot at every skill (MonsterViews.vis_state)", n, "",
                 "%d slot(s) neither pickup nor barrel (things.skill_absent)" % other if other else "")

    def feature_guard(self, flag, check, fn):
        """a per-map feature (config.MAP_CONFIG `flag`: E1M2's polish) run on this map whether or not it is on: a
        refusal is REFUSED when the flag is on, else a WARN for the day it is turned on"""
        on = bool(getattr(map_cfg(Config(), self.m), flag))
        try:
            note = fn() or ""
        except AssertionError as e:
            self.row("REFUSED" if on else "WARN", check, "", "",
                     "%s%s" % ("" if on else "when %s is turned on: " % flag, ("%s" % e).replace("\n", " ")[:240]))
            return
        self.row("OK", check, "on" if on else "off", "", note)

    def _feature_flags(self):
        """E1M2's polish (SECTOR_LIGHTS, SWITCH_TEX, AUTOMAP) runs model asserts only E1M2 (and E1M1's map page) has
        passed -- a new map turning a flag on hits them at emission; here, in seconds"""
        from doomfj import automap, lights, switches
        dst, _ds, msecs, _mc = self._machines()

        def lit():
            ths = lights.thinkers(self.secs, self.lds, self.sds)
            both = sorted({th.sector for th in ths} & (set(dst) | set(msecs)))
            assert not both, "animated light sectors %s are doors or movers (emit_wall_renderer refuses)" % both
            lsec = {th.sector for th in ths}
            over = []
            for i, ld in enumerate(self.lds):
                if ld.back in (0xFFFF, -1) or ld.back >= len(self.sds):
                    continue
                f, b = self.sds[ld.front].sector, self.sds[ld.back].sector
                ms = self._line_machines(f, b)
                if not isinstance(ms, str) and len(ms) + len({x for x in (f, b) if x in lsec}) > 2:
                    over.append(i)
            assert not over, "segs on more than two state cells (a machine and lights): linedefs %s" % over[:6]
            return "%d thinkers" % len(ths)
        self.feature_guard("SECTOR_LIGHTS", "animated lights (lights.thinkers; no light on a door / mover)", lit)
        self.feature_guard("SWITCH_TEX", "switch textures (switches.map_switches: one exit switch line)",
                           lambda: "%d switch lines" % len(switches.map_switches(self.secs, self.lds, self.sds,
                                                                                  self.verts)))
        c = map_cfg(Config(), self.m)
        pal = bytes(v for rgb in self.asset.playpal(0) for v in rgb)
        self.feature_guard("AUTOMAP", "the MAP page (automap.build + check: the map fits its page)",
                           lambda: "%d-unit scale" % automap.build(self.wad, self.m, pal, c.W, c.H).units)

    # M8 C6 (the plasma rifle): DOOM's state counts of the E1 monster types gamedata does not hold yet (info.c, the raise
    # states left out: only the Arch-vile enters them) -- the Baron with its BRUISERSHOT, the lost soul
    DOOM_NEW_STATES = {3003: 22 + 5, 3006: 16}

    def _state_byte(self):
        """M8 C6: THE STATE BYTE IS FULL. Every state cell is one byte (the schema's 8 bits, the fj's 2 nibbles): 246 states
        held 0..245 and the plasma rifle's 15 had no index left -- they took the unreachable RAISE states' as GHOSTS
        (gamedata.STATE_GHOSTS). A new monster type needs its states somewhere too: the free indices past the table and
        the raise indices no ghost holds yet, against what the map's missing types need (DOOM_NEW_STATES) -- OVER here
        is a decision (more ghosts, a per-domain alias, or a wider cell) before any emission"""
        from doomfj import gamedata as gd
        from doomfj.things import single_player
        free_tail = 255 - len(gd.STATE_NAMES)
        free_ghosts = sum(1 for n in gd.STATE_NAMES if "_RAISE" in n)
        need = {ty: k for ty, k in self.DOOM_NEW_STATES.items()
                if ty not in gd.THING_TYPES
                and any(t.type == ty and single_player(t) for t in self.wad.things(self.m))}
        n = sum(need.values())
        self.row("OK" if n <= free_tail + free_ghosts else "OVER", "the state byte: states the map's new types need",
                 n, "<= %d free (%d past the table, %d raise indices)" % (free_tail + free_ghosts, free_tail,
                                                                         free_ghosts),
                 "types %s (DOOM_NEW_STATES)" % sorted(need) if need else "")

    # measured, each from a build's own record (named); projected by segs, an ESTIMATE from two maps
    POOL_CAPACITY = 67_108_863                          # words: --pool-base 0x80000000 --span-bits 0x7fffffe0
    POOL_PER_SEG_SPREAD2 = 90_317_184 / 3650            # E1M2's census at the ship knobs, 134.6% (handoff-e1m2 8);
    #                                                     E1M1's 49,798,976 / 2,057 (blocked62) is 24,210: the larger
    POOL_PER_SEG_SPREAD1 = 0.826 * 67_108_863 / 3650    # E1M2 r3 at spread 1: 82.6% of the pool (ship-gate 5)
    RAM_GB_BUILT = 17.21                                # E1M2 r4's assembly: peak private 17.21 GB (ship-gate 5)
    RAM_GB_PER_SEG = RAM_GB_BUILT / 3650

    # M8 size (2026-10-19): the binary's WORDS by emitted region, measured exactly on blocked63 (E1M1) and e1m2_r4
    # (E1M2) -- every word of each .fjm attributed to the label before it (code), the wflip chains it starts, or its
    # table in the blocked pool -- and each region scaled by its own driver (branch m8-size; the tools: scratchpad/12m/fullattr.py). Per driver:
    # (main stream E1M1, pool E1M1, main stream E1M2, pool E1M2) words; "main stream" = code + wflip chains (below the
    # pool base), "pool" = the blocked tables' own words (the pool's padding comes on top: _span_estimate).
    SIZE_DRIVERS = {"const": (9378830, 6592392, 9422976, 6407492), "linedefs": (1212316, 867648, 2387656, 1576288),
                    "monsters": (1502636, 2342616, 3946660, 5639704), "nodes": (2417100, 224924, 3813834, 369242),
                    "sectors": (2678856, 831936, 6946742, 2377916), "segs": (1002846, 125142, 2263916, 685162),
                    "things": (1314594, 1633618, 1657296, 2128242), "vpb": (7807874, 0, 14380082, 0)}
    # the baked point location, assembled ALONE per map (plain words, inline): 49,922 a diagonal node + 5,722 an axis
    # node - 322,457 (fit over E1M1..E1M9, within 1.2%); 0.83 of it in a blocked build, 0.437 of that main stream.
    # PTLOC_SHARED: ~250K words in all. VPB_DIRECT: 2 + 2 (popcount(id) - 1) words a band-list id instead of ~35.7.
    PTLOC_BLOCKED, PTLOC_MAIN = 0.83, 0.437
    VPB_LISTS_PER_EST = 1.865          # band lists / (4 x viewz classes x plane pairs): E1M1 54,616, E1M2 134,328

    def _size_drivers(self):
        from doomfj.mapcompiler import bake_bsp
        from doomfj.reference_model import ReferenceModel
        from doomfj.things import single_player
        rm = ReferenceModel(Config())
        cmap = bake_bsp(self.wad, self.m)
        th = [t for t in self.wad.things(self.m) if single_player(t)]
        vz = len({rm.view_z(sc.floor_h) for sc in self.secs})
        pairs = len({(sc.ceil_h, sc.floor_h, sc.light, sc.ceil_tex.upper(), sc.floor_tex.upper())
                     for sc in self.secs})
        diag = sum(1 for n in cmap.nodes if n.dx and n.dy)
        return cmap, {"segs": len(self.wad.segs(self.m)), "linedefs": len(self.lds), "sectors": len(self.secs),
                      "things": len(th), "monsters": sum(1 for t in th if t.type in gd.MONSTER_DOOMEDNUMS),
                      "nodes": len(cmap.nodes), "vpb": round(self.VPB_LISTS_PER_EST * 4 * vz * pairs),
                      "diag": diag, "axis": len(cmap.nodes) - diag}

    # the two maps the drivers were measured on (their own counts, as _size_drivers computes them)
    SIZE_AT = {"E1M1": {"segs": 2057, "linedefs": 1175, "sectors": 182, "things": 269, "monsters": 53, "nodes": 681,
                        "vpb": 54428},
               "E1M2": {"segs": 3650, "linedefs": 2290, "sectors": 380, "things": 330, "monsters": 129, "nodes": 1103,
                        "vpb": 134989}}

    def size_estimate(self, cfg=None):
        """(main stream words, pool table words) of the map's game-tier blocked build -- an ESTIMATE (two built maps,
        one driver per region) under the map's config (PTLOC_SHARED, VPB_DIRECT)"""
        cfg = cfg or map_cfg(Config(), self.m)
        _cmap, d = self._size_drivers()
        a, b = self.SIZE_AT["E1M1"], self.SIZE_AT["E1M2"]
        main = pool = 0.0
        for name, (m1, p1, m2, p2) in self.SIZE_DRIVERS.items():
            f = 0.0 if name == "const" else (d[name] - a[name]) / (b[name] - a[name])
            main += max(0.0, m1 + (m2 - m1) * f)
            pool += max(0.0, p1 + (p2 - p1) * f)
        if cfg.VPB_DIRECT:
            ids = d["vpb"]
            main -= ids * 35.7 - sum(2 + 2 * max(0, bin(k).count("1") - 1) for k in range(ids))
            main -= 1 << max(1, (ids - 1).bit_length())            # the clean table: one op a padded id, gone
        if cfg.PTLOC_SHARED:
            main += 125_000
            pool += 125_000
        else:
            pt = self.PTLOC_BLOCKED * max(0, 49_922 * d["diag"] + 5_722 * d["axis"] - 322_457)
            main += pt * self.PTLOC_MAIN
            pool += pt * (1 - self.PTLOC_MAIN)
        return main, pool

    def _span_estimate(self):
        """the 2^27-word HARD limit (the owner, 2026-10-19). Two layouts of the same estimate: (a) the shipped knobs --
        the pool from --pool-base 0x80000000 (word 2^26), so the main stream must stay under 2^26 and the pool's span
        under 2^26 more; spread 1's plain pool spans ~1.87x its tables (E1M2 r4: 56.46M for 30.15M); (b) the pool base
        right after the main stream with BlockPool(pack=True) (build_blocked --pack-blocks, flipjump block-pack):
        ~1.11x at spread 1 (E1M2's census: 33.37M), ~2.1x at spread 2 (64.12M)"""
        main, pool = self.size_estimate()
        lim, half = 1 << 27, 1 << 26
        shipped = half + 1.87 * pool if main < half else None
        packed1, packed2 = main * 1.01 + 1.11 * pool, main * 1.01 + 2.13 * pool
        self.row("OK" if main < half else "WARN", "main stream: code + wflip chains (ESTIMATE by region drivers)",
                 "%.1fM words" % (main / 1e6), "< 2^26 (--pool-base 0x80000000)",
                 "" if main < half else "past the shipped pool base: move --pool-base above it (with --pack-blocks)")
        best = "spread 2 packed" if packed2 <= lim else "spread 1 packed" if packed1 <= lim else "none fits"
        self.row("OK" if packed1 <= 0.9 * lim else "WARN",
                 "address span (ESTIMATE): shipped knobs / packed at spread 1 / spread 2",
                 "%s / %.1f%% / %.1f%%" % ("n/a" if shipped is None else "%.1f%%" % (100 * shipped / lim),
                                          100 * packed1 / lim, 100 * packed2 / lim),
                 "<= 100% of 2^27 (WARN past 90%)", best)

    def _projection(self):
        """E1M2 (handoff-e1m2 7-8): the pool overflowed at spread 2 (134.6%) -- found by a build's PREFLIGHT -- and the
        assembly filled the machine (17.21 GB, 0.02 GB left). Both scale with the segs (E1M1 -> E1M2: segs x1.77, the
        pool x1.81): projected here, so a map that cannot fit, or cannot be assembled on this box, is known first"""
        n = len(self.wad.segs(self.m))
        p2, p1 = n * self.POOL_PER_SEG_SPREAD2, n * self.POOL_PER_SEG_SPREAD1
        cap = self.POOL_CAPACITY
        self.row("OK" if p1 <= cap else "WARN", "pool demand (ESTIMATE by segs from E1M1 / E1M2's builds)",
                 "spread 2 %.0f%%, spread 1 %.0f%%" % (100.0 * p2 / cap, 100.0 * p1 / cap), "<= 100%",
                 ("--spread %d" % (2 if p2 <= cap else 1)) if p1 <= cap else
                 "over the pool even at spread 1 (E1M2's lever): size work before any build")
        self._span_estimate()
        ram = n * self.RAM_GB_PER_SEG
        self.row("OK" if ram <= self.RAM_GB_BUILT else "WARN",
                 "assembly peak RAM (ESTIMATE by segs from E1M2's 17.21 GB)", "%.1f GB" % ram,
                 "<= %.2f GB (built here)" % self.RAM_GB_BUILT,
                 "" if ram <= self.RAM_GB_BUILT else "past anything this box has assembled: a probe first (rule 1)")

    def run(self):
        for name, fn in (("geometry", self.geometry), ("textures", self.textures), ("specials", self.specials),
                         ("things", self.things), ("doors/movers", self.doors_and_movers), ("world", self.world),
                         ("render caps", self.render_caps), ("weapon light", self.weapon_light),
                         ("lessons", self.lessons)):
            self.guard("section " + name, fn)
        return self

    def markdown(self):
        f = self.facts
        out = ["# Level survey: %s" % self.m, "",
               "Generated by `scripts/level_survey.py %s` (the model's own functions; no emission)." % self.m, "",
               "| linedefs | sectors | segs | subsectors | doors | lifts | monsters | barrels | pickups | secrets |",
               "|---|---|---|---|---|---|---|---|---|---|",
               "| %s |" % " | ".join(str(f.get(k, "?")) for k in ("linedefs", "sectors", "segs", "subsectors", "doors",
                                                                   "lifts", "monsters", "barrels", "pickups",
                                                                   "secrets")), ""]
        order = {"REFUSED": 0, "ERROR": 1, "OVER": 2, "WRONG": 3, "MISSING": 4, "WARN": 5, "INFO": 6, "OK": 7}
        bad = [r for r in self.rows if order[r[0]] <= 5]
        out += ["## Blockers and work (%d)" % len(bad), "", "| status | check | value | limit | note |",
                "|---|---|---|---|---|"]
        out += ["| %s |" % " | ".join(r) for r in sorted(bad, key=lambda r: order[r[0]])]
        out += ["", "## Everything checked", "", "| status | check | value | limit | note |", "|---|---|---|---|---|"]
        out += ["| %s |" % " | ".join(r) for r in self.rows]
        return "\n".join(out) + "\n"


def matrix(wad, asset, maps):
    """what each map needs: the unsupported line specials, sector specials and pickups, side by side -- the ORDER to
    build them in is the one that unblocks the most maps first"""
    svs = [Survey(wad, m, asset).run() for m in maps]
    need = {}
    for s in svs:
        for st, check, value, _lim, note in s.rows:
            if st not in ("REFUSED", "ERROR", "OVER", "MISSING", "WARN", "WRONG") or check == "World(strict=True) builds":
                continue                        # the plain World row: its MISSING thing rows say the same, per type
            if check.startswith("World(strict=True) without"):    # docs/level-lessons.md: this row WAS hidden too
                check, value = "World(strict=True) without the unknown thing types", note[:60]
            need.setdefault("%s: %s" % (st, check), {})[s.m] = value or "x"
    out = ["| need | %s | maps |" % " | ".join(maps), "|---|%s---|" % ("---|" * len(maps))]
    for check, per in sorted(need.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append("| %s | %s | %d |" % (check, " | ".join(per.get(m, "") for m in maps), len(per)))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--wad", default=str(ASSET_WAD))
    ap.add_argument("--matrix", nargs="+", metavar="MAP")
    ap.add_argument("--out")
    a = ap.parse_args()
    wad = WadFile.from_path(a.wad)
    text = matrix(wad, wad, a.matrix) if a.matrix else "".join(Survey(wad, m, wad).run().markdown() for m in a.maps)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:     # the text's own LFs on every platform
            f.write(text)
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
