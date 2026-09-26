"""S3a -- DOOM's random number table, behind the smallest interface the gameplay model needs.

THE TABLE is `rndtable` from Chocolate Doom's `src/doom/m_random.c` at commit
895f581c5d91497bdda0516612da803fe5843e28 (2026-09-08):
    https://raw.githubusercontent.com/chocolate-doom/chocolate-doom/895f581c5d91497bdda0516612da803fe5843e28/src/doom/m_random.c
It was cross-checked value for value against id Software's own release,
    https://raw.githubusercontent.com/id-Software/DOOM/master/linuxdoom-1.10/m_random.c
(two independent fetches, identical 256 values), and `RNDTABLE_SHA256` pins it: a test recomputes it.

THE INTERFACE (owner decision D10, docs/plan-gameplay.md section 11): DOOM's table stays unless a P0
probe finds another generator a medium-or-better speedup in fj. So nothing outside this module may
index `RNDTABLE` directly. Callers hold an opaque per-stream STATE (today: DOOM's `prndindex`, one
byte) and go through:

    p_random(state)                -> (value, next_state)   DOOM's P_Random
    p_subrandom(state)             -> (value, next_state)   Chocolate's P_SubRandom = r1 - r2
    outcome_table(f)               -> [f(v) for each table slot]   the per-call-site composition
    p_random_outcome(state, table) -> (table[slot], next_state)

A different generator later replaces these and `STATE_BITS`; callers do not change.

WHY `outcome_table`. fj has no cheap multiply or modulo (plan section 4 rule 3), so a call site such
as `damage = ((P_Random() % 5) + 1) * 3` is baked at emit time into a 256-entry dispatch table
`outcome[i] = f(rndtable[i])`, and the runtime call is one index increment plus ONE dispatch. The
table is indexed by the POST-increment state, because DOOM increments before it reads:
    P_Random: prndindex = (prndindex + 1) & 0xff; return rndtable[prndindex];
so `p_random_outcome(s, outcome_table(f))` is exactly `f(p_random(s)[0])` -- a test proves it for
every state.

STREAMS. DOOM has one global `prndindex`. The model gives each consumer its own stream (the world,
the player's weapons, effects, and one per monster slot), so a change in how often one monster rolls
cannot shift every other monster's decisions -- which is what makes a divergence between the two
mirrors localisable to one stream. `stream_seed(k)` spreads the streams' starting states.
"""
from __future__ import annotations

import hashlib
from typing import Callable, List, Sequence, Tuple

# Chocolate Doom m_random.c, `static const unsigned char rndtable[256]`, in source order.
RNDTABLE: Tuple[int, ...] = (
    0, 8, 109, 220, 222, 241, 149, 107, 75, 248, 254, 140, 16, 66,
    74, 21, 211, 47, 80, 242, 154, 27, 205, 128, 161, 89, 77, 36,
    95, 110, 85, 48, 212, 140, 211, 249, 22, 79, 200, 50, 28, 188,
    52, 140, 202, 120, 68, 145, 62, 70, 184, 190, 91, 197, 152, 224,
    149, 104, 25, 178, 252, 182, 202, 182, 141, 197, 4, 81, 181, 242,
    145, 42, 39, 227, 156, 198, 225, 193, 219, 93, 122, 175, 249, 0,
    175, 143, 70, 239, 46, 246, 163, 53, 163, 109, 168, 135, 2, 235,
    25, 92, 20, 145, 138, 77, 69, 166, 78, 176, 173, 212, 166, 113,
    94, 161, 41, 50, 239, 49, 111, 164, 70, 60, 2, 37, 171, 75,
    136, 156, 11, 56, 42, 146, 138, 229, 73, 146, 77, 61, 98, 196,
    135, 106, 63, 197, 195, 86, 96, 203, 113, 101, 170, 247, 181, 113,
    80, 250, 108, 7, 255, 237, 129, 226, 79, 107, 112, 166, 103, 241,
    24, 223, 239, 120, 198, 58, 60, 82, 128, 3, 184, 66, 143, 224,
    145, 224, 81, 206, 163, 45, 63, 90, 168, 114, 59, 33, 159, 95,
    28, 139, 123, 98, 125, 196, 15, 70, 194, 253, 54, 14, 109, 226,
    71, 17, 161, 93, 186, 87, 244, 138, 20, 52, 123, 251, 26, 36,
    17, 46, 52, 231, 232, 76, 31, 221, 84, 37, 216, 165, 212, 106,
    197, 242, 98, 43, 39, 175, 254, 145, 190, 84, 118, 222, 187, 136,
    120, 163, 236, 249,
)

TABLE_SIZE = 256
# The per-stream state is DOOM's table index. The schema (world.py) declares every stream cell at
# this width, so a generator change moves exactly one number.
STATE_BITS = 8
STATE_MASK = (1 << STATE_BITS) - 1

# sha256 over the 256 table bytes, and their plain sum -- both recomputed by tests/host/test_gp_rng.py
RNDTABLE_SHA256 = "908b529108dcbcd3fe82907cd646e08b12404a893eda2165fe58dadd709a413f"
RNDTABLE_SUM = 32986


def table_sha256(table: Sequence[int]) -> str:
    """The checksum `RNDTABLE_SHA256` pins, for any candidate table (the test's negative control
    mutates one entry and requires the digest to move)."""
    return hashlib.sha256(bytes(table)).hexdigest()


def verify_rndtable(table: Sequence[int] = RNDTABLE) -> List[str]:
    """[] when `table` is DOOM's rndtable, else one line per failed check."""
    bad = []
    if len(table) != TABLE_SIZE:
        bad.append("length %d, want %d" % (len(table), TABLE_SIZE))
    if any(not 0 <= v <= 255 for v in table):
        bad.append("a value outside 0..255")
    if not bad:
        if sum(table) != RNDTABLE_SUM:
            bad.append("sum %d, want %d" % (sum(table), RNDTABLE_SUM))
        if table_sha256(table) != RNDTABLE_SHA256:
            bad.append("sha256 %s, want %s" % (table_sha256(table), RNDTABLE_SHA256))
    return bad


def p_random(state: int) -> Tuple[int, int]:
    """DOOM's P_Random for one stream: pre-increment, then read. Returns (value 0..255, next state).
    From a fresh stream (state 0) the first value is rndtable[1] = 8, exactly as in DOOM."""
    nxt = (state + 1) & STATE_MASK
    return RNDTABLE[nxt], nxt


def p_subrandom(state: int) -> Tuple[int, int]:
    """Chocolate Doom's P_SubRandom: `r = P_Random(); return r - P_Random();` -- two calls, the FIRST
    minus the SECOND (vanilla wrote `P_Random() - P_Random()` and left the order to the compiler;
    Chocolate pins it). Range -255..255."""
    a, state = p_random(state)
    b, state = p_random(state)
    return a - b, state


def outcome_table(f: Callable[[int], int]) -> List[int]:
    """The per-call-site composition: slot i holds f(rndtable[i]). Index it with the POST-increment
    state (see the module docstring), i.e. through `p_random_outcome`."""
    return [f(v) for v in RNDTABLE]


def p_random_outcome(state: int, table: Sequence[int]) -> Tuple[int, int]:
    """One call site's outcome: advance the stream once and read the baked outcome. Equal to
    `f(p_random(state)[0])` for `table = outcome_table(f)`, by construction and by test."""
    nxt = (state + 1) & STATE_MASK
    return table[nxt], nxt


# ---- streams ----------------------------------------------------------------------------------
# Stream numbers: 0 = world (level-start rolls, barrels), 1 = player (weapon spread and damage),
# 2 = effects (puffs, blood, fireball impacts), 3 + slot = monster `slot`.
STREAM_WORLD, STREAM_PLAYER, STREAM_FX, STREAM_MONSTER0 = 0, 1, 2, 3
# Odd, so `k * STRIDE` mod 256 is distinct for all 256 streams: no two streams start in lockstep.
STREAM_SEED_STRIDE = 37


def stream_seed(stream: int) -> int:
    """The starting state of stream `stream`. Stream 0 starts where DOOM starts (M_ClearRandom sets
    prndindex = 0 at every level start)."""
    return (stream * STREAM_SEED_STRIDE) & STATE_MASK
