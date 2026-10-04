"""M7 P4.2b -- the player's NOISE in fj (docs/gp-combat.md section 1, the model's "hit" mode): P_NoiseAlert's flood,
`World.noise_alert`, and what A_Look reads of it (`World._a_look`'s sound branch, monstercode.p32a_slot `hear`).

THE MODEL. The level's sectors fold into SOUND NODES (`World.sector_node`, `World.nsound`): every connected group of
static sectors whose shared two-sided lines have an opening is one node, and every door, lift and floor-switch sector
is a node of its own. The only edges left between nodes are the two-sided lines with a DYNAMIC sector on one side
(`World._sound_door_edges`); such an edge carries sound when the opening across it is open (> 0) at this tic's
heights. A shot floods from the player's node through the open edges and every node it reaches hears it
(`snd_alert`, persisted, never cleared before NEW GAME).

THE FJ. `nz_leaf` (fcall'd through `nz_ret` at the weapon's fire point, weaponcode `noise=True`):
  * THE LOCATION: the player's sector at the tic's pose -- the weapon runs before the move, as the model's player
    phase does -- by the point location every thing uses (`ptloc_walk` on the integer `viewx` / `viewy`, then
    `lfsec`), into `nz_sec`. (`psec`, the monsters' copy, is the POST-move sector: it is not touched.)
  * THE SEED (`nz_flood`, the harness' entry): the scratch set `nz_r` (one nibble a node, 0 or 1) is zeroed and the
    player's node set -- a two-nibble jump on `nz_sec` to that node's stub.
  * THE RELAXATION: one block per EDGE (a pair of nodes: a static one and a dynamic one -- asserted: no line has two
    dynamic sides, so each edge's opening is a function of ONE state cell). Exactly one end reached and the edge
    open -> the other end is reached and `nz_ch` is set. The open test is `hex.if_flags` on the dynamic sector's
    state cell (`dstate` / `lstate` / `fswitch`, one nibble) with the mask of the states whose opening is > 0 --
    computed at emit time from the model's own height rules (`monstersight.closed_states`); a never-open edge is
    not emitted and an always-open one has no test. The pass repeats while it changed something: each changing
    pass reaches a new node, so it runs at most `nsound` times.
  * THE OR: every reached node's `snd_alert` set. The scratch is what keeps an older alert from seeding this one
    (P_NoiseAlert floods from the player alone, through today's doors).
`nz_heard` (fcall'd through `nz_hret`, A_Look): `nz_h` = `snd_alert` of the node of the sector in `mt_ms`.

THE CELLS. Persisted (`PERSIST`): `snd_alert` (one nibble a node; level start 0) and `mon_ambush` (one nibble a slot,
monstercode: MTF_AMBUSH at level start, cleared by A_FaceTarget). Scratch (`noise_decls`): `nz_r`, `nz_sec`,
`nz_ch`, `nz_h`, `nz_amb` and the two fcall registers.
"""
from typing import Dict, List, Tuple

# the persisted cells the noise adds (build.MONSTER_PERSIST must carry them in a tier whose player mode is "hit" or
# "full": a reset that restored them would forget every alert and every ambush cleared, each frame)
PERSIST = ("snd_alert", "mon_ambush")
NOISE_PLAYER_MODES = ("hit", "full")     # world.PLAYER_MODES whose shot floods the sound (combat._p_noise)


def sound_edges(w) -> List[Tuple[int, int, str, int, int]]:
    """the flood's edges, one per pair of nodes the model's door edges join: (static node, dynamic node, the dynamic
    sector's state cell, its number of states, the mask of the states at which an opening joins them). Edges whose
    mask is 0 (never open) are dropped. Sorted by (static node, dynamic node)."""
    from doomfj.monstersight import closed_states
    dyn = set(w.door_order) | set(w.mover_order)
    groups: Dict[Tuple[int, int], list] = {}
    for a, b in w._sound_door_edges:
        sides = [s for s in (a, b) if s in dyn]
        assert len(sides) == 1, ("a sound edge between two dynamic sectors (%d, %d): its opening needs both "
                                 "states, which the one-cell open test cannot read" % (a, b))
        s = sides[0]
        o = b if s == a else a
        cell, n, hts = closed_states(w, s)
        assert n <= 16, (s, n)
        mask = 0
        for k in range(n):
            f1, c1 = hts[k].get(s, (w.secs[s].floor_h, w.secs[s].ceil_h))
            f2, c2 = w.secs[o].floor_h, w.secs[o].ceil_h             # o is static: its stored heights
            assert o not in hts[k], (o, s, k)
            if min(c1, c2) - max(f1, f2) > 0:
                mask |= 1 << k
        key = (w.sector_node[o], w.sector_node[s])
        assert key[0] != key[1]
        g = groups.setdefault(key, [cell, n, 0])
        assert g[:2] == [cell, n], "an edge read through two state cells"
        g[2] |= mask
    return [(a, b, cell, n, mask) for (a, b), (cell, n, mask) in sorted(groups.items()) if mask]


def _node_dispatch(prefix: str, cell: str, node_of: List[int], target, miss: str) -> List[str]:
    """jump to `target(node)` for the node of the sector in the 2-nibble `cell` (a jump on the high nibble, then on
    the low); a sector past the table goes to `miss`"""
    nsec = len(node_of)
    his = (nsec + 15) // 16
    assert his <= 16, nsec
    out = ["    sim.jump16 %s + 1*dw, %s" % (cell, ", ".join("%s_h%d" % (prefix, h) if h < his else miss
                                                          for h in range(16)))]
    for h in range(his):
        out += ["  %s_h%d:" % (prefix, h), "    sim.jump16 %s, %s" % (cell, ", ".join(
            target(node_of[16 * h + l]) if 16 * h + l < nsec else miss for l in range(16)))]
    return out


def noise_leaf_lines(w) -> List[str]:
    """`nz_leaf` (locate, then the flood) and `nz_flood` (the flood from the sector in `nz_sec`), one fcall register
    `nz_ret`; and `nz_heard`. Needs `ptloc_walk`, `lfsec`, `viewx` / `viewy`, the state cells and `snd_alert`."""
    n = w.nsound
    node_of = list(w.sector_node)
    assert max(node_of) < n
    out = ["// M7 P4.2b (doomfj.noisecode): P_NoiseAlert -- the player's node, the flood through the open edges",
           "nz_leaf:",
           "    hex.zero 10, ptx", "    hex.mov 4, ptx, viewx + 4*dw", "    hex.sign_extend 10, 4, ptx",
           "    hex.zero 10, pty", "    hex.mov 4, pty, viewy + 4*dw", "    hex.sign_extend 10, 4, pty",
           "    stl.fcall ptloc_walk, ptloc_ret",
           "    lfsec.lookup nz_sec, ptss",
           "nz_flood:",
           "    hex.zero %d, nz_r" % n]
    out += _node_dispatch("nz_sd", "nz_sec", node_of, lambda k: "nz_s%d" % k, "nz_pass")
    for k in range(n):
        out += ["  nz_s%d:" % k, "    hex.xor_by nz_r + %d*dw, 1" % k, "    ;nz_pass"]
    out += ["nz_pass:", "    hex.zero 1, nz_ch"]
    for j, (a, b, cell, ns, mask) in enumerate(sound_edges(w)):
        L = "nz_e%d" % j
        full = mask == (1 << ns) - 1
        ra, rb = "nz_r + %d*dw" % a, "nz_r + %d*dw" % b
        test = (lambda yes: ["    ;%s" % yes]) if full else (
            lambda yes: ["    hex.if_flags %s, %#06x, %sx, %s" % (cell, mask, L, yes)])
        out += ["  %s:" % L,
                "    hex.if1 1, %s, %sa" % (ra, L),
                "    hex.if0 1, %s, %sx" % (rb, L),                     # neither end reached
                *test("%ssa" % L),
                "  %ssa:" % L, "    hex.xor_by %s, 1" % ra, "    ;%sc" % L,
                "  %sa:" % L,
                "    hex.if1 1, %s, %sx" % (rb, L),                     # both ends reached
                *test("%ssb" % L),
                "  %ssb:" % L, "    hex.xor_by %s, 1" % rb,
                "  %sc:" % L, "    hex.set 1, nz_ch, 1",
                "  %sx:" % L]
    out += ["    hex.if1 1, nz_ch, nz_pass"]                                  # changed: another pass
    for k in range(n):
        out += ["    hex.if0 1, nz_r + %d*dw, nz_o%d" % (k, k), "    hex.set 1, snd_alert + %d*dw, 1" % k,
                "  nz_o%d:" % k]
    out += ["    stl.fret nz_ret"]
    # nz_heard: nz_h = snd_alert[node(mt_ms)]
    out += ["nz_heard:"]
    out += _node_dispatch("nz_hd", "mt_ms", node_of, lambda k: "nz_hn%d" % k, "nz_hno")
    for k in range(n):
        out += ["  nz_hn%d:" % k, "    hex.mov 1, nz_h, snd_alert + %d*dw" % k, "    stl.fret nz_hret"]
    out += ["  nz_hno:", "    hex.zero 1, nz_h", "    stl.fret nz_hret"]
    return out


def noise_decls(w) -> List[str]:
    """the flood's scratch and registers, and `snd_alert` at the level start (no node has heard a shot)"""
    n = w.nsound
    return ["snd_alert: hex.vec %d, 0" % n, "nz_r: hex.vec %d" % n, "nz_sec: hex.vec 2", "nz_ch: hex.vec 1",
            "nz_h: hex.vec 1", "nz_amb: hex.vec 1", "nz_ret: hex.vec w/4", "nz_hret: hex.vec w/4"]


def noise_restart_lines(w) -> List[str]:
    """NEW GAME: no node has heard a shot (the model's level start, every skill)"""
    return ["    hex.zero %d, snd_alert" % w.nsound]


def ambush_decl(nmon: int, values: List[int]) -> str:
    """`mon_ambush` per slot (one nibble each) at the values given (the boot skill's level start)"""
    assert len(values) == nmon and all(v in (0, 1) for v in values), values
    return "mon_ambush: hex.vec %d, %d" % (nmon, sum(v << (4 * m) for m, v in enumerate(values)))
