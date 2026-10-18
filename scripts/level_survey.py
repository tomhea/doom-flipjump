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
        out[s] = "doors (walk-over %s, per line, by tag)" % doors.WALK_DOOR_KINDS[s]
    for s, (_k, once) in doors.SWITCH_DOOR_KINDS.items():
        out[s] = "doors (%s switch, by tag)" % ("S1" if once else "SR")
    for s in movers.LIFT_WALK_SPECIALS | movers.LIFT_USE_SPECIALS:
        out[s] = "movers (lift)"
    for s in movers.FLOOR_SWITCH_SPECIALS:
        out[s] = "movers (floor switch, instant; a group per tag)"
    for s, (trig, rule, sub) in movers.FLOOR_SPECIALS.items():      # M8 F1.3: every one-shot floor mover
        if s not in movers.FLOOR_SWITCH_SPECIALS:
            out[s] = "movers (%s1 floor group per tag: %s, %s)" % (trig, rule, "a stop every %d frames" % sub)
    for s in movers.LIFT_FAST_SPECIALS:
        out[s] = "movers (blazing lift: stride %d)" % movers.LIFT_FAST_STRIDE
    from doomfj import teleport
    for s in teleport.TELEPORT_SPECIALS:
        out[s] = "teleport (M8 L4: player and monsters; no telefrag, no fog)"
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
                st = "OK" if model and fj else "MISSING"
                self.row(st, label + " (pickup)", n, "", "model %s, fj give %s" % ("yes" if model else "NO",
                                                                                   "yes" if fj else "NO"))
            else:
                self.row("OK", label + (" (solid decor)" if tt.solid else " (decor)"), n)

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
        # a CLOSING door some box fits inside needs the centre-inside test, which doorcode does not run
        refused = [si for si, (area, _) in geo.items() if area and area[0] == "poly" and area[2]
                   and not doors.door_stay(kinds[si])]
        if refused:
            self.row("REFUSED", "closing doors a box fits inside (doorcode: no centre-inside test)", refused, "", "")
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
            if k.endswith("(one cell)"):    # M8 L1 / F1.3: one cell moves both -- read through it everywhere
                note = "one machine: rendered and read by collision / sight / noise / missiles"
            elif "door" in k:
                note = "the renderer refuses a door beside another dynamic sector"
            else:
                note = ("renderer: the pair switch (its gate: the 'dynamic segs' row); collision / sight / noise / "
                        "missiles: the readers' own rows below (collision.mover_line_states, monstersight.line_states)")
            self.row("WARN", "lines between two dynamic sectors: %s" % k, n, "",
                     "%s -- linedefs %s" % (note, [x[0] for x in lines if x[3] == k][:8]))

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
                return
            self.row("INFO", "the counts below exclude the unknown thing types", sorted(unknown))
        else:
            self.row("OK", "World(strict=True) builds")
        self.facts["_world"] = w
        self.monster_extensions(w)                          # M8 C8: the lost soul, the extension rows, the pain bits
        nmon, nbar = len(w.mon_things), len(w.barrel_things)
        self.facts.update(monsters=nmon, barrels=nbar, pickups=len(w.pickup_things), secrets=len(w.secret_sectors),
                          sound_nodes=getattr(w, "nsound", "?"))
        self.cap("monster slots + barrels (dm_id/sp_sid, 2 nibbles)", nmon + nbar, 254)
        from doomfj.world import aim_bits
        self.cap("monsters + barrels -> aim_sid (world.aim_bits: the fj byte)", nmon + nbar, 0xFF,
                 "aim_sid %d bits" % aim_bits(w.layout))
        self.row("OK" if nbar else "REFUSED", "barrels >= 1 (barrelcode asserts one)", nbar)
        from doomfj.statcode import count_digits
        self.cap("monsters on LEVEL COMPLETE (an 8-bit cell; statcode.count_digits)", nmon, 0xFF,
                 "%d digits a count" % count_digits(w))
        from doomfj import statcode
        items = sum(1 for t in w.pickup_things if statcode.counts_item(t.type))
        self.cap("COUNTITEM pickups on LEVEL COMPLETE (an 8-bit cell)", items, 0xFF)
        self.cap("secret sectors on LEVEL COMPLETE (p_secretcount 4 bits, 1 digit)", len(w.secret_sectors), 9)
        self.cap("pickups (pkxyz index, 2 nibbles)", len(w.pickup_things), 256, strict_less=True)
        self.guard("statcode.check_world", lambda: statcode.check_world(w) if hasattr(statcode, "check_world") else None)
        from doomfj import barrelcode
        self.guard("barrels: level start the same on every skill (barrelcode.check_model_rules)",
                   lambda: barrelcode.check_model_rules(w, (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)) if nbar else None)
        # M8 F1.3 (docs/f1-big-map-widths.md 9): an item on a mover's floor touches at the live floor (pk_mbox) and
        # renders runtime (things.mover_leaves); a door's floor never moves
        moving = [(t.type, w.pickup_sector[i]) for i, t in enumerate(w.pickup_things) if w.pickup_on_mover[i]]
        self.row("INFO", "pickups on a mover floor (lootcode.pk_mbox: the live floor)", len(moving), "",
                 "" if not moving else "(type, sector) %s" % moving[:8])
        from doomfj.monstermove import static_blockers
        _things, var = static_blockers(w)
        # M8 F1.2: a solid decoration some skill lacks is a `mc_don` presence flag, set at NEW GAME (monstermove.mc_don_restart)
        self.row("OK", "solid decorations some skill lacks (monstercode: mc_don at NEW GAME)",
                 len(var), "", "" if not var else "mc_don flags for decor_solid indices %s" % var[:10])

    def monster_extensions(self, w):
        """M8 C8 (doomfj.lostsoul / soulcode; the lessons of the lost soul): the monster-domain extension rows' alias
        codes (gamedata.MON_ALIAS_POOL: a new monster's states take weapon states' codes -- a later monster can run out
        of them), damagecode's pain classes (one nibble of dmrnd: at most 4 painchances on a map), and a map's souls --
        their 16.16 heights (soulcode.check_model_rules) and a teleport line beside them (EV_Teleport's z: the model's,
        not yet the fj's)"""
        self.cap("monster-domain extension state rows (gamedata.MON_ALIAS_POOL's codes)", len(gd.EXT_STATE_NAMES),
                 len(gd.MON_ALIAS_POOL))
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
        self.cap("drawable things, every skill (1-byte fragment slot id)", len(draw), 256, strict_less=True)
        from doomfj.things import LIST_MAX_THINGS
        self.cap("runtime things (byte thing lists, LIST_MAX_THINGS)", nt, LIST_MAX_THINGS,
                 "plus mobiles and drops: the next row")
        # F1 item 12 (docs/f1-big-map-widths.md 0.3): the lists hold the runtime things, the fireball and effect pools
        # and every monster drop -- the sum monstercode / LIST_MAX_THINGS bound
        def ids():
            from doomfj.barrelcode import droppers
            from doomfj.things import LIST_MAX_THINGS
            from doomfj.world import FIREBALL_POOL, FX_POOL, World
            w = self.facts.get("_world") or World(self.wad, self.m, monsters="idle")
            n = nt + FIREBALL_POOL + FX_POOL + len(droppers(w))
            self.cap("runtime ids: things + pools + drops (byte lists, F1 item 12)", n, LIST_MAX_THINGS)
        self.guard("runtime ids: things + pools + drops (byte lists, F1 item 12)", ids)
        self.guard("marking segs < DEG_PNEAR", lambda: self._marking(WR, cmap))
        pid_lo = len({((s.ceil_h, s.light & 0xFF, s.ceil_tex.upper()), (s.floor_h, s.light & 0xFF, s.floor_tex.upper()))
                      for s in self.secs})
        cfg = map_cfg(Config(), self.m)
        # docs/level-lessons.md: E1M2's plane ids (376 > 255) were found by an emission; the measured real/estimate
        # ratios are 1.46 (E1M1) and 1.25 (E1M2), so x1.5 past the cap makes this a WARN, not a footnote
        self.row("WARN" if pid_lo * 1.5 >= 16 ** cfg.PID_NIBBLES else "INFO",
                 "plane pairs (ESTIMATE, no direction; measured: m4_bands.py)", pid_lo,
                 "< %d" % 16 ** cfg.PID_NIBBLES,
                 "E1M1 est 152 -> 222 real; E1M2 329 -> 411. PID_NIBBLES %d for this map%s"
                 % (cfg.PID_NIBBLES, "" if pid_lo * 1.5 < 256 else ": likely needs 3 (MAP_CONFIG)"))

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
        self.cap("marking two-sided segs (n_tsv 3 nibbles)", marking, WR.DEG_PNEAR, strict_less=True)

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
        """CR of #148 (#149 item 1): `doors.LEGACY_NEIGHBOUR_MAPS` picks E1M1's legacy door rule by a (sectors,
        linedefs, sidedefs) fingerprint, not by the map's name -- another map that matches it silently takes it"""
        from doomfj import doors
        legacy = (len(self.secs), len(self.lds), len(self.sds)) in doors.LEGACY_NEIGHBOUR_MAPS
        if self.m.upper() == "E1M1" or not legacy:
            self.row("OK", "door neighbour rule (doors.door_neighbours)",
                     "legacy (E1M1 family)" if legacy else "DOOM's two-sided")
        else:
            self.row("WRONG", "door neighbour rule (doors.door_neighbours)", "legacy", "two-sided",
                     "%s matches E1M1's size fingerprint: its doors open by the legacy rule" % self.m)

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
                                    nfs=movers.fswitch_nibbles(groups))
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
            self.facts["_machines"] = (dst, dsecs, movers.mover_secs(mtab, secs),
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
        if hit and door is not None:
            return "a door (%d) and a mover %s on one seg" % (door, list(hit))
        if len(hit) == 2 and mcell[hit[0]] == mcell[hit[1]] and msecs[hit[0]] == msecs[hit[1]]:
            hit = hit[:1]                                       # one machine (a floor group's sectors)
        if door is not None:
            return [(door, dsecs[:len(dst[door])])]
        return [(m, msecs[m]) for m in hit]

    @staticmethod
    def shut_gate(st, dims):
        """emit_wall_renderer's `_seg_dual_cell` on a dynamic seg's shut pattern `st` (one bool per state, the first
        machine's state major) over machines of `dims` states: "never" (a marking seg), "every" (the solid path,
        `_seg_closed_moving`: the CR of #146's lines), the index of the machine whose state 0 is EXACTLY the shut set
        (the one-op `hex.if0` gate), or None -- the emitter refuses it"""
        st = list(st)
        if not any(st):
            return "never"
        if all(st):
            return "every"
        if not st[0]:
            return None
        if len(dims) == 1:
            return 0 if st == [True] + [False] * (len(st) - 1) else None
        na, nb = dims
        if st == [ia == 0 for ia in range(na) for ib in range(nb)]:
            return 0
        if st == [ib == 0 for ia in range(na) for ib in range(nb)]:
            return 1
        return None

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

    # measured, each from a build's own record (named); projected by segs, an ESTIMATE from two maps
    POOL_CAPACITY = 67_108_863                          # words: --pool-base 0x80000000 --span-bits 0x7fffffe0
    POOL_PER_SEG_SPREAD2 = 90_317_184 / 3650            # E1M2's census at the ship knobs, 134.6% (handoff-e1m2 8);
    #                                                     E1M1's 49,798,976 / 2,057 (blocked62) is 24,210: the larger
    POOL_PER_SEG_SPREAD1 = 0.826 * 67_108_863 / 3650    # E1M2 r3 at spread 1: 82.6% of the pool (ship-gate 5)
    RAM_GB_BUILT = 17.21                                # E1M2 r4's assembly: peak private 17.21 GB (ship-gate 5)
    RAM_GB_PER_SEG = RAM_GB_BUILT / 3650

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
        ram = n * self.RAM_GB_PER_SEG
        self.row("OK" if ram <= self.RAM_GB_BUILT else "WARN",
                 "assembly peak RAM (ESTIMATE by segs from E1M2's 17.21 GB)", "%.1f GB" % ram,
                 "<= %.2f GB (built here)" % self.RAM_GB_BUILT,
                 "" if ram <= self.RAM_GB_BUILT else "past anything this box has assembled: a probe first (rule 1)")

    def run(self):
        for name, fn in (("geometry", self.geometry), ("textures", self.textures), ("specials", self.specials),
                         ("things", self.things), ("doors/movers", self.doors_and_movers), ("world", self.world),
                         ("render caps", self.render_caps), ("lessons", self.lessons)):
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
