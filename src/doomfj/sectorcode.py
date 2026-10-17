"""M8 L1 (docs/handoff-e1m2.md section 4 (B)): the SECTOR ID's width in fj, ONE place.

A sector id is `World.sec_nibbles` nibbles wide -- 2 on E1M1 (182 sectors), 3 on E1M2 (380) -- derived from the map,
never configured. Every cell that holds one (`msec`, `psec`, `mt_ms`, `mm_sec`, `nz_sec`, `sc_sec`, `lfsec`'s result,
the `rj<s>` rows' index) is declared at that width, and every jump on one goes through `sector_dispatch`, so a
definition and its call sites cannot drift apart. At 2 nibbles both helpers emit EXACTLY the text the emitters wrote
before they existed (E1M1's program is byte-identical; scratchpad/cr/emit_baseline.py)."""
from typing import Callable, List, Optional, Sequence


def msec_cell(m: int, nib: int) -> str:
    """slot m's cell in `msec` (one sector id per monster slot, `nib` nibbles each)"""
    return "msec + %d*dw" % (nib * m)


def msec_value(secs: Sequence[int], nib: int) -> int:
    """the packed initial value of `msec` (slot m's sector at nibble nib*m)"""
    assert all(0 <= s < 16 ** nib for s in secs), (nib, list(secs))
    return sum(s << (4 * nib * m) for m, s in enumerate(secs))


def sector_dispatch(prefix: str, cell: str, target: Callable[[int], Optional[str]], miss: str, nsec: int,
                    nib: int) -> List[str]:
    """jump to `target(s)` for the sector s in the `nib`-nibble `cell` -- a `sim.jump16` per nibble, the top nibble
    first; `target(s)` None, or s >= nsec, goes to `miss`. A node exists only where some sector below it has a target.
    The node above the leaves for the sectors 16v..16v+15 is `<prefix>h<v>`; at 3 nibbles the top level's nodes (the
    sectors 256v..256v+255) are `<prefix>hh<v>`. The first line has no label (the caller's own precedes it)."""
    assert nib >= 2 and 0 < nsec <= 16 ** nib, (nsec, nib)
    leaf = [target(s) for s in range(nsec)]

    def live(level: int, v: int) -> bool:
        lo = v * 16 ** level
        return any(leaf[s] is not None for s in range(lo, min(nsec, lo + 16 ** level)))

    def lab(level: int, v: int) -> str:
        return "%s%s%d" % (prefix, "h" * level, v)

    def at(k: int) -> str:
        return cell if k == 0 else "%s + %d*dw" % (cell, k)

    def entry(level: int, v: int) -> str:
        if level == 0:
            return leaf[v] if v < nsec and leaf[v] is not None else miss
        return lab(level, v) if live(level, v) else miss

    out = ["    sim.jump16 %s, %s" % (at(nib - 1), ", ".join(entry(nib - 1, d) for d in range(16)))]
    for level in range(nib - 1, 0, -1):
        for v in range(-(-nsec // 16 ** level)):
            if live(level, v):
                out += ["  %s:" % lab(level, v), "    sim.jump16 %s, %s" % (
                    at(level - 1), ", ".join(entry(level - 1, 16 * v + d) for d in range(16)))]
    return out
