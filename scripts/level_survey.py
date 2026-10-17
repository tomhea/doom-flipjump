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
    for s in doors.BLAZE_DOOR_SPECIALS:
        out[s] = "doors (blaze)"
    for s in doors.WALKOVER_SPECIALS:
        out[s] = "doors (walk-over, by tag)"
    for s in movers.LIFT_WALK_SPECIALS | movers.LIFT_USE_SPECIALS:
        out[s] = "movers (lift)"
    for s in movers.FLOOR_SWITCH_SPECIALS:
        out[s] = "movers (floor switch; ONE shared fswitch cell)"
    return out


def fj_gives(kind):
    """does the fj loot code have a give routine for this pickup kind? (asks lootcode.give_lines itself)"""
    from doomfj import lootcode
    try:
        lootcode.give_lines(kind)
        return True
    except (KeyError, AssertionError, ValueError, NotImplementedError):
        return False


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
            self.row("WARN", "doors with slanted sides", slanted, "", "model OK (M8 L0); doorcode refuses 'd' lines")
        self.guard("walk-over triggers (one axis-aligned segment, one door)",
                   lambda: doors.walkover_triggers(secs, lds, sds, self.verts))
        lifts = {}
        self.guard("lift states", lambda: lifts.update(movers.lift_states(secs, lds, sds)))
        sw = {}
        self.guard("floor-switch sectors", lambda: sw.update(movers.switch_sectors(secs, lds, sds)))
        self.facts.update(lifts=len(lifts), switch_sectors=len(sw))
        if len({ld.tag for ld in lds if ld.special in movers.FLOOR_SWITCH_SPECIALS}) > 1:
            self.row("WRONG", "floor switches with different tags", "", "",
                     "movercode has ONE fswitch cell: they fire together")
        dyn = {si: "door" for si in st}
        dyn.update({si: "lift" for si in lifts})
        dyn.update({si: "switch" for si in sw})
        pairs = Counter()
        lines = []
        for i, ld in enumerate(lds):
            if ld.back in (0xFFFF, -1) or ld.back >= len(sds):
                continue
            a, b = sds[ld.front].sector, sds[ld.back].sector
            if a in dyn and b in dyn and a != b:
                k = "-".join(sorted((dyn[a], dyn[b])))
                pairs[k] += 1
                lines.append((i, a, b, k))
        for k, n in sorted(pairs.items()):
            renderer = "renderer OK (M8 L1 pair switch)" if "door" not in k else "renderer REFUSES"
            self.row("WARN", "lines between two dynamic sectors: %s" % k, n, "",
                     "%s; collision/monstersight/noisecode refuse -- linedefs %s"
                     % (renderer, [x[0] for x in lines if x[3] == k][:8]))

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
        dyn = set(w.door_order) | set(w.mover_order)
        moving = [(t.type, sec) for t in w.pickup_things
                  for sec in [w.leaf_sector[w.rm.point_in_subsector(w.cmap, t.x, t.y)]] if sec in dyn]
        self.row("OK" if not moving else "REFUSED", "pickups on a door or mover floor (lootcode: static z)",
                 len(moving), "0", "" if not moving else "(type, sector) %s" % moving[:6])
        from doomfj.monstermove import static_blockers
        _things, var = static_blockers(w)
        self.row("OK" if not var else "REFUSED", "solid decorations some skill lacks (monstercode: mc_don at NEW GAME)",
                 len(var), "0", "" if not var else "decor_solid indices %s" % var[:10])

    def render_caps(self):
        from doomfj import wall_renderer as WR
        from doomfj.mapcompiler import bake_bsp
        from doomfj.reference_model import ReferenceModel
        from doomfj.things import baked_thing_mask, drawable_things
        rm = ReferenceModel(Config())
        cmap = bake_bsp(self.wad, self.m)
        draw, draw_idx = drawable_things(rm, self.wad.things(self.m), self.asset, {})
        baked = baked_thing_mask(rm, cmap, draw, WR.MONSTER_TYPES)
        nt = len({i for i, b in zip(draw_idx, baked) if not b})
        self.cap("drawable things, every skill (1-byte fragment slot id)", len(draw), 256, strict_less=True)
        self.cap("runtime things (byte thing lists, LIST_MAX_THINGS)", nt, 254,
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
        self.row("INFO", "plane pairs (ESTIMATE, no direction; measured: m4_bands.py)", pid_lo,
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
        marking = sum(1 for seg in cmap.segs if self.lds[seg.linedef].back != -1
                      and any(WR.seg_marks_in(self.lds, self.sds, seg, v) for v in variants))
        self.cap("marking two-sided segs (n_tsv 3 nibbles)", marking, WR.DEG_PNEAR, strict_less=True)

    def run(self):
        for name, fn in (("geometry", self.geometry), ("textures", self.textures), ("specials", self.specials),
                         ("things", self.things), ("doors/movers", self.doors_and_movers), ("world", self.world),
                         ("render caps", self.render_caps)):
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
        for st, check, value, _, _ in s.rows:
            if st in ("REFUSED", "ERROR", "OVER", "MISSING", "WARN", "WRONG") and not check.startswith("World(strict"):
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
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
