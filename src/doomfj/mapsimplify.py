"""E1M1-lite: simplify a DOOM map's RENDER cost while keeping its layout and play.

The frame's op cost is population x price (fj-cost-model): total segs (walk skeleton), one-sided
segs (the per-frame wedge cull), marking two-sided boundaries (plane_near attribution), step-face
boundaries (V3 scale setups) and things reached (V4 projections). Every pass here shrinks one of
those populations; none of them moves a wall the player would miss.

Passes, in order:
  1. FLATTEN decorative sector boundaries — union-find over two-sided lines whose sectors differ
     by <= (floor_tol, ceil_tol, light_tol). The GROUP's total floor/ceil range is capped by the
     same tolerance, so a staircase of 16-unit risers can NEVER transitively collapse into one
     unreachable 128-unit cliff. Sectors with a special or tag are untouchable (nukage damage,
     doors, lifts, secrets, exits), as is any line with a special or the impassable flag.
  2. DELETE boundary lines interior to a merged group (same sector both sides, no special, not
     blocking, no see-through middle texture) — their segs, marking cost and step faces vanish.
  3. ABSORB micro-sectors (tiny boundary length, no special/tag) into their dominant neighbour
     under a larger tolerance — computer trim, door-side dressing, light insets.
  4. DECIMATE degree-2 vertices: two chained lines with the same sector pair and no special merge
     into one when the direction change is under `angle_tol` (texture unification is an accepted
     visual compromise; the dominant-by-length sidedef textures win).
  5. THIN things: keep ALL monsters, starts, weapons, keys; drop small decor; thin dense
     bonus/decor clusters. Landmarks (trees, tall techno pillars) stay.

Output feeds nodebuilder.rebuild_wad. Nothing here touches NODES/SEGS — the node builder redoes
those from the simplified geometry.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

# thing taxonomy (doom1/freedoom shared type ids)
MONSTERS = {3004, 9, 3001, 3002, 58, 3005, 3003, 16, 7, 68, 64, 3006, 65, 66, 67, 69, 71, 84}
WEAPONS = {2001, 2002, 2003, 2004, 2005, 2006, 82}
KEYS = {5, 6, 13, 38, 39, 40}
STARTS = {1, 2, 3, 4, 11, 14}
BIG_PICKUPS = {2011, 2012, 2013, 2018, 2019, 2022, 2023, 2024, 2025, 2026, 8, 2046, 17,
               2002, 2045, 2007, 2008, 2010, 2047, 2048, 2049}   # ammo stays: it is the game
LANDMARK_DECOR = {30, 32, 33, 37, 41, 42, 48, 2028, 85}   # pillars, techno columns, lamps
CORPSE_DECOR = {10, 12, 15, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 49, 50, 51,
                52, 53, 59, 60, 61, 62, 63}                # gore: 1-4 px sprites, pure cost
SMALL_DECOR = {31, 34, 36, 57, 79, 80, 81}
BONUSES = {2014, 2015}                                     # health/armour bonus (come in strings)
THIN_3 = {47, 2035}                                        # stalagmites, barrels: keep 1 in 3
THIN_2 = {43, 54}                                          # trees: keep every other


@dataclass
class SimplifyStats:
    sector_groups: int = 0
    sectors_flattened: int = 0
    lines_deleted: int = 0
    micro_absorbed: int = 0
    verts_decimated: int = 0
    things_dropped: int = 0
    sector_map: list = field(default_factory=list)   # original sector idx -> lite sector idx
    notes: list = field(default_factory=list)


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb
        return rb


def _line_len(verts, ld):
    (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
    return math.hypot(x2 - x1, y2 - y1)


def simplify(verts, linedefs, sidedefs, sectors, things, *,
             floor_tol=24, ceil_tol=32, light_tol=32,
             micro_len=200, micro_floor_tol=32, micro_ceil_tol=48, micro_light_tol=64,
             angle_tol_deg=40.0, dev_tol=12.0,
             thin_things=True) -> tuple:
    """Returns (verts, linedefs, sidedefs, sectors, things, SimplifyStats). Inputs are the wad
    dataclass lists; outputs are same-shaped (linedefs/sidedefs/sectors as `replace`d copies)."""
    st = SimplifyStats()
    verts = list(verts)
    lds = list(linedefs)
    sds = list(sidedefs)
    secs = list(sectors)

    # canonicalize duplicate vertices FIRST: E1M1 carries same-coordinate vertex twins, and an
    # index-keyed degree count then sees 2 lines at a T-junction that really has 3 — decimating
    # such a vertex straightens two of the walls into a chord while the third still hangs on the
    # twin, opening a sliver gap (measured: an unclaimed all-black column at the courtyard).
    canon = {}
    vmap = {}
    for i, (x, y) in enumerate(verts):
        vmap[i] = canon.setdefault((x, y), i)
    lds = [replace(ld, v1=vmap[ld.v1], v2=vmap[ld.v2]) for ld in lds]

    protected = [s.special != 0 or s.tag != 0 for s in secs]
    # a sector a DOOR/LIFT line acts on (via tag, or the direct back-sector idiom for local doors)
    for ld in lds:
        if ld.special and ld.back != -1 and ld.tag == 0:
            protected[sds[ld.back].sector] = True          # DR-style door: acts on its back sector

    weight = Counter()
    for ld in lds:
        L = _line_len(verts, ld)
        for sd in (ld.front, ld.back):
            if sd != -1:
                weight[sds[sd].sector] += L

    # ── pass 1: tolerance flattening with group range caps ──
    uf = _UF(len(secs))
    lo_f = {i: secs[i].floor_h for i in range(len(secs))}
    hi_f = dict(lo_f)
    lo_c = {i: secs[i].ceil_h for i in range(len(secs))}
    hi_c = dict(lo_c)
    lo_l = {i: secs[i].light for i in range(len(secs))}
    hi_l = dict(lo_l)

    def try_union(a, b, ftol, ctol, ltol):
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            return True
        if max(hi_f[ra], hi_f[rb]) - min(lo_f[ra], lo_f[rb]) > ftol:
            return False
        if max(hi_c[ra], hi_c[rb]) - min(lo_c[ra], lo_c[rb]) > ctol:
            return False
        if max(hi_l[ra], hi_l[rb]) - min(lo_l[ra], lo_l[rb]) > ltol:
            return False
        r = uf.union(ra, rb)
        o = ra if r == rb else rb
        lo_f[r], hi_f[r] = min(lo_f[r], lo_f[o]), max(hi_f[r], hi_f[o])
        lo_c[r], hi_c[r] = min(lo_c[r], lo_c[o]), max(hi_c[r], hi_c[o])
        lo_l[r], hi_l[r] = min(lo_l[r], lo_l[o]), max(hi_l[r], hi_l[o])
        return True

    edges = []
    for li, ld in enumerate(lds):
        if ld.back == -1 or ld.special or ld.tag or (ld.flags & 1):
            continue
        a, b = sds[ld.front].sector, sds[ld.back].sector
        if a == b or protected[a] or protected[b]:
            continue
        sa, sb = secs[a], secs[b]
        d = (abs(sa.floor_h - sb.floor_h) + abs(sa.ceil_h - sb.ceil_h)
             + abs(sa.light - sb.light) / 4)
        edges.append((d, a, b))
    edges.sort()
    for d, a, b in edges:
        sa, sb = secs[a], secs[b]
        if abs(sa.floor_h - sb.floor_h) > floor_tol or abs(sa.ceil_h - sb.ceil_h) > ceil_tol \
           or abs(sa.light - sb.light) > light_tol:
            continue
        try_union(a, b, floor_tol, ceil_tol, light_tol)

    # ── pass 3 (same union structure): micro-sector absorb, bigger tolerance ──
    neigh = defaultdict(Counter)
    for ld in lds:
        if ld.back == -1 or ld.special or ld.tag:
            continue
        a, b = sds[ld.front].sector, sds[ld.back].sector
        L = _line_len(verts, ld)
        neigh[a][b] += L
        neigh[b][a] += L
    for i, s in enumerate(secs):
        if protected[i] or weight[i] > micro_len or not neigh[i]:
            continue
        tgt = max(neigh[i], key=neigh[i].get)
        if protected[tgt]:
            continue
        if try_union(i, tgt, micro_floor_tol, micro_ceil_tol, micro_light_tol):
            st.micro_absorbed += 1

    groups = defaultdict(list)
    for i in range(len(secs)):
        groups[uf.find(i)].append(i)

    # representative properties: the heaviest member wins the whole group's look
    newsec = list(secs)
    for members in groups.values():
        if len(members) == 1:
            continue
        rep = max(members, key=lambda i: weight[i])
        r = secs[rep]
        for i in members:
            newsec[i] = replace(secs[i], floor_h=r.floor_h, ceil_h=r.ceil_h,
                                floor_tex=r.floor_tex, ceil_tex=r.ceil_tex, light=r.light)
        st.sectors_flattened += len(members) - 1
        st.sector_groups += 1
    secs = newsec
    smap = {i: uf.find(i) for i in range(len(secs))}       # canonical sector per original

    # ── pass 2: delete interior boundary lines ──
    keep = []
    for ld in lds:
        if ld.back != -1 and not ld.special and not (ld.flags & 1):
            a, b = sds[ld.front].sector, sds[ld.back].sector
            if smap[a] == smap[b] and sds[ld.front].middle == '-' and sds[ld.back].middle == '-':
                st.lines_deleted += 1
                continue
        keep.append(ld)
    lds = keep

    # rewrite sidedef sector refs to the group representative
    sds = [replace(sd, sector=smap[sd.sector]) for sd in sds]

    # ── pass 4: degree-2 vertex decimation ──
    # `absorbed[k]` = the original vertices a (possibly repeatedly) merged line has swallowed;
    # every merge re-checks ALL of them against the new chord, so iterated merging cannot drift
    # past dev_tol the way an immediate-chord-only check does.
    absorbed = defaultdict(list)

    def _decimate(lds):
        removed = 0
        adj = defaultdict(list)
        for i, ld in enumerate(lds):
            adj[ld.v1].append(i)
            adj[ld.v2].append(i)
        dead = set()
        cos_tol = math.cos(math.radians(angle_tol_deg))
        for v, ls in adj.items():
            if len(ls) != 2:
                continue
            i, j = ls
            if i in dead or j in dead or i == j:
                continue
            a, b = lds[i], lds[j]
            # `adj` is a snapshot: an earlier merge may have moved a line's endpoint OFF this
            # vertex. Without this guard the a0/b0 fallback picks a vertex the line no longer
            # touches and the "merge" DELETES a real wall span (measured: a 32-unit connector
            # vanished and left an unclaimed all-black column at the courtyard).
            if v not in (a.v1, a.v2) or v not in (b.v1, b.v2):
                continue
            if a.special or b.special or a.tag or b.tag or a.flags != b.flags:
                continue

            def pair(ld):
                f = sds[ld.front].sector if ld.front != -1 else -1
                bk = sds[ld.back].sector if ld.back != -1 else -1
                return f, bk
            pa, pb = pair(a), pair(b)
            same = pa == pb
            flipped = pa == (pb[1], pb[0])
            if not (same or flipped):
                continue
            # orient both away from the shared vertex consistently: a: a0 -> v, b: v -> b0
            a0 = a.v2 if a.v1 == v else a.v1
            b0 = b.v2 if b.v1 == v else b.v1
            if a0 == b0:
                continue
            (ax, ay), (vx_, vy_), (bx, by) = verts[a0], verts[v], verts[b0]
            d1 = (vx_ - ax, vy_ - ay)
            d2 = (bx - vx_, by - vy_)
            n1, n2 = math.hypot(*d1), math.hypot(*d2)
            if n1 == 0 or n2 == 0:
                continue
            dot = (d1[0] * d2[0] + d1[1] * d2[1]) / (n1 * n2)
            # SAGITTA cap, not just angle: the merged line a0->b0 must pass within `dev_tol`
            # units of the removed vertex, or the wall visibly MOVES (a 25-degree bend across a
            # 200-unit chain displaces the wall ~40 units — measured as phantom floor-to-ceiling
            # stripes in the courtyard render).
            mdx, mdy = bx - ax, by - ay
            mlen = math.hypot(mdx, mdy)
            if mlen == 0:
                continue
            drift = [(vx_, vy_)] + absorbed[i] + absorbed[j]
            if any(abs(mdx * (qy - ay) - mdy * (qx - ax)) / mlen > dev_tol
                   for qx, qy in drift):
                continue
            # `a` may run a0->v or v->a0; the sector-pair orientation decides which replacement
            # keeps the front side facing the same sector. Merge only the clean continuation case.
            a_fwd = (a.v2 == v)
            b_fwd = (b.v1 == v)
            if not (a_fwd and b_fwd and same):
                # try the both-reversed continuation (b: b0->v then a: v->a0)
                if (b.v2 == v and a.v1 == v and same) and dot > cos_tol:
                    lds[j] = replace(b, v2=a.v2)
                    absorbed[j] = drift
                    dead.add(i)
                    removed += 1
                continue
            if dot <= cos_tol:
                continue
            # textures: longer line's sidedefs win (already in place on `a`—extend a to b's end)
            if n1 >= n2:
                lds[i] = replace(a, v2=b.v2)
                absorbed[i] = drift
                dead.add(j)
            else:
                lds[j] = replace(b, v1=a.v1)
                absorbed[j] = drift
                dead.add(i)
            removed += 1
        # indices shift when dead lines drop out — remap the absorbed-vertex ledger with them
        keep_idx = [k for k in range(len(lds)) if k not in dead]
        new_abs = {nk: absorbed[ok] for nk, ok in enumerate(keep_idx) if absorbed.get(ok)}
        absorbed.clear()
        absorbed.update(new_abs)
        return [lds[k] for k in keep_idx], removed

    total_removed = 1
    while total_removed:
        lds, total_removed = _decimate(lds)
        st.verts_decimated += total_removed

    # ── pass 5: thing thinning ──
    if thin_things:
        # SPATIAL thinning: a thinned-class thing is dropped only when a KEPT thing of the same
        # class already stands within `radius` — dense strings and clusters thin out, an isolated
        # landmark (THE tree at the tree viewpoint) always survives.
        out, kept_at = [], defaultdict(list)

        def spaced(cls, x, y, radius):
            for kx, ky in kept_at[cls]:
                if (kx - x) * (kx - x) + (ky - y) * (ky - y) < radius * radius:
                    return False
            kept_at[cls].append((x, y))
            return True

        for t in things:
            tt = t.type
            if tt in MONSTERS or tt in WEAPONS or tt in KEYS or tt in STARTS \
               or tt in BIG_PICKUPS or tt in LANDMARK_DECOR:
                out.append(t)
            elif tt in BONUSES:
                if spaced(("bonus", tt), t.x, t.y, 96):
                    out.append(t)
            elif tt in THIN_2:
                if spaced(("t2", tt), t.x, t.y, 192):
                    out.append(t)
            elif tt in THIN_3:
                if spaced(("t3", tt), t.x, t.y, 256):
                    out.append(t)
            elif tt in SMALL_DECOR or tt in CORPSE_DECOR:
                continue                                    # gone: candles, gore, tiny dressing
            else:
                out.append(t)                               # unknown types: keep (safe default)
        st.things_dropped = len(things) - len(out)
        things = out

    # ── compact: drop orphan sidedefs and vertices, remap indices ──
    used_sd = sorted({x for ld in lds for x in (ld.front, ld.back) if x != -1})
    sd_map = {o: i for i, o in enumerate(used_sd)}
    sds = [sds[o] for o in used_sd]
    lds = [replace(ld, front=sd_map.get(ld.front, -1), back=sd_map.get(ld.back, -1))
           for ld in lds]
    used_v = sorted({x for ld in lds for x in (ld.v1, ld.v2)})
    v_map = {o: i for i, o in enumerate(used_v)}
    verts = [verts[o] for o in used_v]
    lds = [replace(ld, v1=v_map[ld.v1], v2=v_map[ld.v2]) for ld in lds]
    # sectors keep their indices (some now unreferenced — harmless, but compact anyway)
    used_sec = sorted({sd.sector for sd in sds})
    sec_map = {o: i for i, o in enumerate(used_sec)}
    secs = [secs[o] for o in used_sec]
    sds = [replace(sd, sector=sec_map[sd.sector]) for sd in sds]
    # original -> lite sector index (via the group representative; -1 if the rep lost every line)
    st.sector_map = [sec_map.get(smap[i], -1) for i in range(len(newsec))]

    return verts, lds, sds, secs, things, st
