"""M7 P3.2b "chase" (docs/gp-monsters.md 8.4): the fj a monster's move needs besides its collision cells
(`collision.monster_cells_fj`) -- each piece a generator the emitter calls and a tests/fj harness runs alone.

Piece 2, THE SEED: P_CheckPosition starts its opening from the sector under the candidate position -- the model's
`secs_c[leaf_sector[leaf]]` (every door at its OPEN height, each mover at its present state). The fj finds the leaf
with the baked point location every thing already uses (`ptloc_walk`, on the integer position in ptx / pty) and
jumps on it (`ptss`, three nibbles) to that leaf's stub, which sets `cp_seedf` / `cp_seedc` -- or, in a mover's
leaf, jumps on the mover's state cell to that state's heights. The leaf itself stays in `ptss` for the relink.
"""
from doomfj.mapcompiler import seg_sector

M32 = 0xFFFFFFFF


def leaf_sector_index(cmap, lds, sds, s: int) -> int:
    """the sector subsector `s` lies in -- its first seg's (the model's `leaf_sector`, the emitter's `_leaf_mover`)"""
    seg = cmap.segs[cmap.subsectors[s].firstseg]
    ld = lds[seg.linedef]
    return sds[ld.front if seg.side == 0 else ld.back].sector


def monster_seed_fj(cmap, lds, sds, secs_open, msecs: dict, mcell: dict, *, label: str = "ms_seed") -> list:
    """`<label>_leaf`: from `ptss` (the leaf `ptloc_walk` found) to `cp_seedf` / `cp_seedc`, returning through
    `<label>_ret`. `secs_open`: the map with every door open (the player's seeds' `_dsecs_open`); `msecs` /
    `mcell`: each mover's per-state sector lists and state cell (the emitter's `_msecs` / `_mcell`)."""
    n = len(cmap.subsectors)
    assert all(ss.numsegs for ss in cmap.subsectors), "a seg-less leaf has no sector to seed from"
    assert n <= 16 ** 3, "the leaf jump reads three nibbles of ptss"
    L = label
    out = [f"{L}_leaf:"]

    def jump(prefix: int, depth: int) -> list:
        """sim.jump16 on ptss nibble 2 - depth, into the sixteen next levels (or the leaves' stubs)"""
        nib = 2 - depth
        targets = []
        for d in range(16):
            p = (prefix << 4) | d
            lo = p << (4 * nib)
            targets.append((f"{L}_j{depth + 1}_{p:x}" if depth < 2 else f"{L}_s{p}") if lo < n else f"{L}_none")
        return [f"    sim.jump16 ptss + {nib}*dw, " + ", ".join(targets)]

    out += jump(0, 0)
    for depth in (1, 2):
        for p in range(16 ** depth):
            if p << (4 * (3 - depth)) < n:
                out += [f"  {L}_j{depth}_{p:x}:"] + jump(p, depth)

    def heights(sec) -> list:
        return [f"    hex.set 8, cp_seedf, {sec.floor_h & M32}", f"    hex.set 8, cp_seedc, {sec.ceil_h & M32}"]

    for s in range(n):
        si = leaf_sector_index(cmap, lds, sds, s)
        seg = cmap.segs[cmap.subsectors[s].firstseg]
        out.append(f"  {L}_s{s}:")
        if si in msecs:                                       # a mover's leaf: its state's heights
            labs = [f"{L}_s{s}_m{k}" for k in range(len(msecs[si]))]
            out.append(f"    sim.jump16 {mcell[si]}, " + ", ".join(labs + [labs[-1]] * (16 - len(labs))))
            for k, sv in enumerate(msecs[si]):
                out += [f"  {labs[k]}:", *heights(seg_sector(lds, sds, sv, seg)), f"    stl.fret {L}_ret"]
        else:
            out += heights(seg_sector(lds, sds, secs_open, seg)) + [f"    stl.fret {L}_ret"]
    out += [f"  {L}_none:", f"    stl.fret {L}_ret"]
    return out


def monster_seed_decls(label: str = "ms_seed") -> list:
    return [f"{label}_ret: hex.vec w/4"]
