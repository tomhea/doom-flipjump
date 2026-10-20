"""M8 (the owner's rule: a recorded simplification is implemented when it costs <= +0.5% speed) -- THE SECTOR LIGHT
SPECIALS, one module both mirrors run: DOOM's p_lights.c thinkers, their levels, their tic and their level start. The
model (`world.World._lights_phase`, the render's `sector_lights`), every gate oracle and the emitter
(`doomfj.lightcode`, `wall_renderer`'s per-state light blocks) take their rules from here.

WHICH MAP: a per-map flag, `config.MAP_CONFIG[map]["SECTOR_LIGHTS"]` (E1M2's 1). Off (E1M1, every map not listed),
nothing here exists for the map: no thinker, no cell, no block -- E1M1's emission is unchanged and its lights stay
static as they always were.

THE THINKERS (P_SpawnSpecials' sector loop, in SECTOR ORDER -- the order they think and roll in):
   1  P_SpawnLightFlash                 "flash":  maxlight the sector's, minlight P_FindMinSurroundingLight; at the
                                                  end of its count it toggles -- to min for (P_Random & 7) + 1 tics,
                                                  to max for (P_Random & 64) + 1; the first count (P_Random & 64) + 1
   2  P_SpawnStrobeFlash FASTDARK       "strobe": min for 15 tics (35 for SLOWDARK), max for STROBEBRIGHT = 5;
   3  P_SpawnStrobeFlash SLOWDARK                 first count (P_Random & 7) + 1; minlight 0 when the surroundings
   4  P_SpawnStrobeFlash FASTDARK                 are as bright (special 4 keeps its damage: the nukage code reads
  12  P_SpawnStrobeFlash SLOWDARK sync            it); 12 / 13 in sync: first count 1, no roll
  13  P_SpawnStrobeFlash FASTDARK sync
   8  P_SpawnGlowingLight               "glow":   GLOWSPEED = 8 a tic down to minlight and back up to maxlight,
                                                  turning one step SHORT of each (T_Glow undoes the step that
                                                  reaches it): after leaving maxlight it never shows either bound
  17  P_SpawnFireFlicker                "fire":   every 4 tics amount = (P_Random & 3) * 16: light - amount below
                                                  minlight (= the min surrounding + 16) -> minlight, else
                                                  maxlight - amount

M8 C4 -- THE LIGHT SWITCHES (p_lights.c EV_LightTurnOn, `SWITCH_LIGHT_SPECIALS`: 138 SR "light to 255", E1M3's line
2024): every sector the line's tag names takes the line's light, at once, on a use press in the line's box (the SR
lift's box, `movers.use_line_boxes`). Each such sector is a thinker of kind "switch" -- two states, its stored light and
the bright one, no tic, no roll -- in the same table, cells and per-state render blocks as the animated ones. They exist
on EVERY map that has such a line, whatever its SECTOR_LIGHTS flag (`game_thinkers`): a switch that did nothing would
be a missing feature, not a static light. E1M1 and E1M2 have none (their thinkers unchanged). A sector both animated
and switched is refused (the animation would overwrite the switched light; no map has one).

A thinker whose light can never change (a glow between equal lights: E1M2's nine static glows) is NOT animated: no
cell, no roll, its sector static -- a pure filter, the same in both mirrors.

A STATE is an index into the thinker's `levels` (state 0 the stored light, so the map's sector list IS state 0, as a
door's or a mover's state 0 is its stored height). `count` is the tics to the next change -- a glow's is its
DIRECTION (0 down, 1 up). The RNG is a stream of its own (`rng.STREAM_LIGHT`, the `rng_lt` cell): the level start's
rolls in sector order, then one roll at each flash toggle and each fire flicker.

TEMPO: the thinkers run once per DOOM tic, inside the monsters' world (world.MONSTER_TICS_PER_FRAME = 2 a frame, after
the effects -- DOOM's thinker list runs them after the mobjs spawned before them), so they keep DOOM's timing
against the monsters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from doomfj import rng as R

GLOWSPEED = 8                 # p_spec.h
STROBEBRIGHT = 5
FASTDARK = 15
SLOWDARK = 35
FLASH_MAXTIME = 64            # P_SpawnLightFlash: maxtime / mintime (masks: P_Random() & time)
FLASH_MINTIME = 7
STROBE_FIRST_MASK = 7         # P_SpawnStrobeFlash: count = (P_Random() & 7) + 1 when not in sync
FIRE_COUNT = 4                # T_FireFlicker / P_SpawnFireFlicker
FIRE_STEP = 16                # amount = (P_Random() & 3) * 16; minlight = the min surrounding + 16
FIRE_MASK = 3
ML_TWOSIDED = 4

# M8 C4: line special -> the light its use sets (EV_LightTurnOn(line, bright), bright != 0)
SWITCH_LIGHT_SPECIALS = {138: 255}
# special -> (kind, darktime, in sync)   (the darktime and the sync are the strobes')
LIGHT_SPECIALS = {1: ("flash", 0, False), 2: ("strobe", FASTDARK, False), 3: ("strobe", SLOWDARK, False),
                  4: ("strobe", FASTDARK, False), 8: ("glow", 0, False), 12: ("strobe", SLOWDARK, True),
                  13: ("strobe", FASTDARK, True), 17: ("fire", 0, False)}
MAX_LEVELS = 16               # a state is one nibble (`ltst`: sim.jump16, the one-nibble state switch)
COUNT_NIBBLES = 2             # `ltct`: a flash's longest count is 65


def lights_on(mapname: str) -> bool:
    """the map's flag (config.MAP_CONFIG `SECTOR_LIGHTS`): its light specials animate"""
    from doomfj.config import Config, map_cfg
    return bool(map_cfg(Config(), mapname).SECTOR_LIGHTS)


def min_surrounding_light(secs, lds, sds, si: int, max_: int) -> int:
    """P_FindMinSurroundingLight(sector, max): the least light of the sectors across the sector's TWO-SIDED lines
    (getNextSector: a line without ML_TWOSIDED has no next sector), never above `max_`"""
    out = max_
    for ld in lds:
        if ld.back < 0 or not ld.flags & ML_TWOSIDED:
            continue
        f, b = sds[ld.front].sector, sds[ld.back].sector
        if f != si and b != si:
            continue
        out = min(out, secs[b if f == si else f].light)
    return out


@dataclass(frozen=True)
class LightThinker:
    sector: int
    special: int
    kind: str                 # "flash" | "strobe" | "glow" | "fire" | M8 C4 "switch" (EV_LightTurnOn)
    maxlight: int
    minlight: int
    levels: Tuple[int, ...]   # the light of each state; state 0 the stored light (= maxlight)
    darktime: int = 0         # the strobes'
    sync: bool = False        # the strobes': 12 / 13

    def state_of(self, light: int) -> int:
        assert light in self.levels, ("sector %d: light %d is not one of its states %r"
                                      % (self.sector, light, self.levels))
        return self.levels.index(light)


def _glow_levels(mx: int, mn: int) -> Tuple[int, ...]:
    """maxlight, then every GLOWSPEED step down that T_Glow keeps (each strictly above minlight)"""
    out = [mx]
    while out[-1] - GLOWSPEED > mn:
        out.append(out[-1] - GLOWSPEED)
    return tuple(out)


def _fire_next(light: int, mx: int, mn: int, amount: int) -> int:
    """T_FireFlicker's new light"""
    return mn if light - amount < mn else mx - amount


def _fire_levels(mx: int, mn: int) -> Tuple[int, ...]:
    """maxlight, then every other light T_FireFlicker can reach from it, brightest first"""
    seen, todo = {mx}, [mx]
    while todo:
        cur = todo.pop()
        for k in range(FIRE_MASK + 1):
            nxt = _fire_next(cur, mx, mn, k * FIRE_STEP)
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return (mx,) + tuple(sorted(seen - {mx}, reverse=True))


def all_thinkers(secs, lds, sds) -> List[LightThinker]:
    """every light thinker P_SpawnSpecials spawns, in sector order (the static ones too)"""
    out = []
    for si, s in enumerate(secs):
        spec = LIGHT_SPECIALS.get(s.special)
        if spec is None:
            continue
        kind, dark, sync = spec
        mx = s.light
        mn = min_surrounding_light(secs, lds, sds, si, mx)
        if kind == "flash":
            levels = (mx, mn)
        elif kind == "strobe":
            if mn == mx:
                mn = 0                             # P_SpawnStrobeFlash: "if (minlight == maxlight) minlight = 0"
            levels = (mx, mn)
        elif kind == "glow":
            levels = _glow_levels(mx, mn)
        else:
            mn = mn + FIRE_STEP
            levels = _fire_levels(mx, mn)
        out.append(LightThinker(si, s.special, kind, mx, mn, levels, dark, sync))
    return out


def thinkers(secs, lds, sds) -> List[LightThinker]:
    """the ANIMATED thinkers (a light that can change), in sector order -- the cells' order"""
    out = [th for th in all_thinkers(secs, lds, sds) if len(set(th.levels)) > 1]
    for th in out:
        assert len(th.levels) == len(set(th.levels)), ("sector %d: repeated light states %r" % (th.sector, th.levels))
        assert len(th.levels) <= MAX_LEVELS, ("sector %d: %d light states past a nibble" % (th.sector, len(th.levels)))
        assert all(0 <= v < 256 for v in th.levels), th
    return out


def switch_thinkers(secs, lds) -> List[LightThinker]:
    """M8 C4: a "switch" thinker for every sector a light-switch line (SWITCH_LIGHT_SPECIALS) tags whose light the line
    changes, in sector order: levels (stored, bright). Two lines setting one sector different lights are refused."""
    bright: Dict[int, int] = {}
    for ld in lds:
        b = SWITCH_LIGHT_SPECIALS.get(ld.special)
        if b is None or not ld.tag:
            continue
        for si, s in enumerate(secs):
            if s.tag == ld.tag:
                assert bright.setdefault(si, b) == b, ("sector %d: two light switches set it %d and %d"
                                                       % (si, bright[si], b))
    return [LightThinker(si, secs[si].special, "switch", b, secs[si].light, (secs[si].light, b))
            for si, b in sorted(bright.items()) if b != secs[si].light]


def game_thinkers(secs, lds, sds, animate: bool) -> List[LightThinker]:
    """M8 C4: the map's thinkers in sector order -- the animated ones when `animate` (its SECTOR_LIGHTS flag), and the
    light switches' always. THE ONE LIST the model (`map_thinkers`) and the emitter take"""
    sw = switch_thinkers(secs, lds)
    out = (thinkers(secs, lds, sds) if animate else []) + sw
    assert len({th.sector for th in out}) == len(out), (
        "M8 C4: sectors %s are animated and switched" % sorted({th.sector for th in sw} & {th.sector for th in out
                                                                                            if th.kind != "switch"}))
    for th in sw:
        assert th.levels[1] < 256 and th.levels[0] != th.levels[1], th
    return sorted(out, key=lambda th: th.sector)


def light_switch_uses(secs, lds, verts, ths) -> list:
    """M8 C4: `[(box, (thinker index, ...))]`, one per light-switch line in linedef order: the use box (the doors'
    proximity box, `movers.use_line_boxes`) and the switch thinkers its tag names"""
    from doomfj.movers import use_line_boxes
    idx = {th.sector: k for k, th in enumerate(ths) if th.kind == "switch"}
    out = []
    for tag, box in use_line_boxes(secs, lds, verts, frozenset(SWITCH_LIGHT_SPECIALS)):
        ks = tuple(idx[si] for si, s in enumerate(secs) if s.tag == tag and si in idx)
        if ks:
            out.append((box, ks))
    return out


def map_thinkers(map_wad, mapname: str) -> List[LightThinker]:
    """the map's thinkers (`game_thinkers`): the animated ones when its flag is on, and its light switches'"""
    return game_thinkers(map_wad.sectors(mapname), map_wad.linedefs(mapname), map_wad.sidedefs(mapname),
                         lights_on(mapname))


def level_start(ths: Sequence[LightThinker]) -> Tuple[List[int], List[int], int]:
    """(states, counts, rng): every thinker at its stored light, and P_SpawnSpecials' first counts rolled in sector
    order on the light stream -- a flash (P_Random & 64) + 1, an unsynced strobe (P_Random & 7) + 1; a synced strobe
    1, a glow 0 (going down), a fire 4. The same at every skill and every restart"""
    rng = R.stream_seed(R.STREAM_LIGHT)
    counts = []
    for th in ths:
        if th.kind == "flash":
            v, rng = R.p_random(rng)
            counts.append((v & FLASH_MAXTIME) + 1)
        elif th.kind == "strobe":
            if th.sync:
                counts.append(1)
            else:
                v, rng = R.p_random(rng)
                counts.append((v & STROBE_FIRST_MASK) + 1)
        elif th.kind in ("glow", "switch"):
            counts.append(0)
        else:
            counts.append(FIRE_COUNT)
    return [0] * len(ths), counts, rng


def tic(th: LightThinker, state: int, count: int, rng: int) -> Tuple[int, int, int]:
    """ONE tic of thinker `th` -- T_LightFlash / T_StrobeFlash / T_Glow / T_FireFlicker on its light VALUE, line for
    line -> (state, count, rng)"""
    if th.kind == "switch":                             # M8 C4: no thinker -- the use press sets it
        return state, count, rng
    light = th.levels[state]
    if th.kind == "glow":
        if count == 0:                                  # direction -1
            light -= GLOWSPEED
            if light <= th.minlight:
                light += GLOWSPEED
                count = 1
        else:                                           # direction 1
            light += GLOWSPEED
            if light >= th.maxlight:
                light -= GLOWSPEED
                count = 0
        return th.state_of(light), count, rng
    count -= 1
    if count:
        return state, count, rng
    if th.kind == "strobe":
        if light == th.minlight:
            light, count = th.maxlight, STROBEBRIGHT
        else:
            light, count = th.minlight, th.darktime
    elif th.kind == "flash":
        v, rng = R.p_random(rng)
        if light == th.maxlight:
            light, count = th.minlight, (v & FLASH_MINTIME) + 1
        else:
            light, count = th.maxlight, (v & FLASH_MAXTIME) + 1
    else:
        v, rng = R.p_random(rng)
        light = _fire_next(light, th.maxlight, th.minlight, (v & FIRE_MASK) * FIRE_STEP)
        count = FIRE_COUNT
    return th.state_of(light), count, rng


def tic_all(ths: Sequence[LightThinker], states: List[int], counts: List[int], rng: int) -> int:
    """one tic of every thinker in sector order, IN PLACE on `states` / `counts` -> the stream's new state"""
    for k, th in enumerate(ths):
        states[k], counts[k], rng = tic(th, states[k], counts[k], rng)
    return rng


def lights_of(ths: Sequence[LightThinker], states: Sequence[int]) -> Dict[int, int]:
    """{sector: light} of every animated sector at `states` -- the render's `sector_lights` (EVERY animated sector, at
    state 0 too: its keys are what the render's marking rule reads)"""
    return {th.sector: th.levels[states[k]] for k, th in enumerate(ths)}


def apply_sector_lights(secs, sector_lights):
    """THE light override (the doors' `apply_sector_heights` twin): `secs` with each listed sector's light replaced;
    the list itself back, unchanged, when there is none"""
    if not sector_lights:
        return secs
    import dataclasses
    out = list(secs)
    for si, light in sector_lights.items():
        if out[si].light != light:
            out[si] = dataclasses.replace(out[si], light=light)
    return out


def state_secs(secs, th: LightThinker) -> list:
    """the map's sector list at each of `th`'s states (state 0: the stored light) -- the emitter's per-state fan-out"""
    return [apply_sector_lights(secs, {th.sector: v}) for v in th.levels]


def flash_count_values(time_mask: int) -> List[int]:
    """the outcome table (rng.outcome_table) of a flash's next count: (P_Random() & time) + 1"""
    return R.outcome_table(lambda v: (v & time_mask) + 1)


def fire_state_values(th: LightThinker, state: int) -> List[int]:
    """the outcome table of a fire's flicker from `state`: the state its light goes to"""
    return R.outcome_table(lambda v: th.state_of(_fire_next(th.levels[state], th.maxlight, th.minlight,
                                                            (v & FIRE_MASK) * FIRE_STEP)))
