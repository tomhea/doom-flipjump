"""Lever 2, item 1: the standalone tier bakes its per-leaf thing lists and stops rebuilding them.

`sim.bind_things` is 24.96% of every game frame's ops on b26 (106.26M of 421M over 14 frames,
handoff-throughput-plan 13.5 / 14.1). In the STANDALONE tier it is a pure function of constants:
nothing moves a thing (C4), `thss_rt` is already baked at the spawn binding, so every frame it
walks all 75 runtime things down the clean path and prepends each to its leaf's list -- producing
the same `sshead`/`thnext` contents every time. Those contents are computed here at emit time and
baked into the two arrays (same cell count, same `;v * dw` cell shape, so no address moves), and
the per-frame call is dropped. The hosted tier, where the host moves things and marks them dirty,
is untouched.
"""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/doom-flipjump/src/doomfj/wall_renderer.py")
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:90])
    s = s.replace(old, new)


# 1. the helper, next to _moving_thing_tables
rep("""def _moving_thing_tables(rm, cmap, lds, sds, secs, map_wad, mapname, sprite_wad,
""", """def baked_thing_lists(binds, nss):
    \"\"\"The per-leaf thing lists exactly as `sim.bind_things` leaves them, computed at emit time.

    `binds[t]` is thing t's subsector. bind_things walks t = nthings-1 .. 0 and PREPENDS each thing
    to its leaf's linked list (`thnext[t] = sshead[ss]; sshead[ss] = t + 1`), so a leaf's traversal
    is ASCENDING by index and the lists store t + 1 with 0 meaning empty / end -- the encoding
    `sim.thing_pass` reads. Returns (sshead, thnext) as lists of byte values.

    Baking this is exact ONLY where the input is constant: the standalone tier, whose things never
    move and whose `thss_rt` is baked at the spawn binding (M5). The hosted tier re-binds at
    runtime and must keep calling the macro. tests/host/test_things_more.py holds the macro's
    reference model and the equivalence check.
    \"\"\"
    head = [0] * nss
    nxt = [0] * len(binds)
    for t in range(len(binds) - 1, -1, -1):
        ss = binds[t]
        nxt[t] = head[ss]
        head[ss] = t + 1
    assert max(head, default=0) <= 0xFF and max(nxt, default=0) <= 0xFF, "the byte lists overflow"
    return head, nxt


def _moving_thing_tables(rm, cmap, lds, sds, secs, map_wad, mapname, sprite_wad,
""")

# 2. the declarations: baked in the standalone tier, zero-filled hex.vec elsewhere
rep("""                   + ([f"sshead: hex.vec {2 * _MT_NSS}",
                       f"thnext: hex.vec {2 * _MT_NT}"]
                      # M5: the hosted tier is fed last frame's binding; standalone bakes the
                      # SPAWN one, so bind_things finds every thing clean and still builds the
                      # per-leaf lists it is really there for.
                      + ([NLJ.join(["thss_rt:"]
                                   + [f"    hex.vec 16, {ss}" for ss in _MT_BINDS])]
                         if standalone else [f"thss_rt: hex.vec {16 * _MT_NT}"])
                      if moving_things else []))
""", """                   + ((
                       # STANDALONE: the lists are BAKED, finished, in the state bind_things left
                       # them (baked_thing_lists), and the per-frame rebuild is gone from pass 1.
                       # Same cell count as the hex.vec form (2*n cells, the second half the
                       # unreachable padding) and the same `;v * dw` cell shape, so nothing moves;
                       # a byte cell with v > 15 is what `hex.vec` cannot express, which is why
                       # these are written out like pclm/sfflag above rather than as hex.vec.
                       # The reset must then leave sshead alone: it is not in the standalone
                       # restore set (a cell the frame never dirties is not residue), and
                       # selfreset skips a byte array the set does not carry.
                       [f"sshead:{NLJ}" + NLJ.join(f";{v} * dw" for v in
                                                    _MT_LISTS[0] + [0] * _MT_NSS),
                        f"thnext:{NLJ}" + NLJ.join(f";{v} * dw" for v in
                                                    _MT_LISTS[1] + [0] * _MT_NT)]
                       if standalone else
                       [f"sshead: hex.vec {2 * _MT_NSS}",
                        f"thnext: hex.vec {2 * _MT_NT}"])
                      # M5: the hosted tier is fed last frame's binding; standalone bakes the
                      # SPAWN one (and, since the lists bake too, never reads it at runtime --
                      # it stays for the restore set's sake and as the record of the binding).
                      + ([NLJ.join(["thss_rt:"]
                                   + [f"    hex.vec 16, {ss}" for ss in _MT_BINDS])]
                         if standalone else [f"thss_rt: hex.vec {16 * _MT_NT}"])
                      if moving_things else []))
""")

# 3. the lists themselves, computed once where _MT_BINDS is
rep("""    _MT_NTH = _index_nibbles(max(1, _MT_NT))          # the row index's width, as check_line's is
""", """    _MT_NTH = _index_nibbles(max(1, _MT_NT))          # the row index's width, as check_line's is
    _MT_LISTS = baked_thing_lists(_MT_BINDS, _MT_NSS) if moving_things else ([], [])
""")

# 4. pass 1: no per-frame rebuild in the standalone tier
rep("""        *([f"sim.bind_things thpos_rt, thss_rt, {_MT_NT}"] if (moving_things and standalone) else
          [f"rep({_MT_NT}, i) hex.input 8, thpos_rt + i*16*dw",
""", """        # STANDALONE: no bind_things call at all. Its per-frame work was a pure function of the
        # baked spawn bindings -- 24.96% of the frame's ops on b26 (handoff-throughput-plan 14) to
        # rebuild lists that never change -- so the lists are baked finished (see _hot_arrays).
        *([] if (moving_things and standalone) else
          [f"rep({_MT_NT}, i) hex.input 8, thpos_rt + i*16*dw",
""")
p.write_text(s, encoding="utf-8")
print("wall_renderer: baked thing lists, no standalone bind_things")

# ---- selfreset: a byte array the set does not carry is skipped, not asserted -------------------
p = Path(r"C:/Users/tomhe/Documents/doom-flipjump/src/doomfj/selfreset.py")
s = p.read_text(encoding="utf-8")
rep("""    byte_words, byte_bases, declared_words = set(), [], set()
    for name, n in byte_arrays(bits, words_sorted, view_w, nss):
        base = bits[name] // W
        byte_bases.append((name, bits[name], n))
        declared_words.update(range(base, _extent(words_sorted, base)))
        for k in range(n):
            byte_words.add(base + 2 * k)
            byte_words.add(base + 2 * k + 1)
    missing = byte_words - wset
    assert not missing, ("self-reset: %d byte-array words are outside the restore set -- "
                         "the byte arrays disagree with it" % len(missing))
""", """    byte_words, byte_bases, declared_words = set(), [], set()
    for name, n in byte_arrays(bits, words_sorted, view_w, nss):
        base = bits[name] // W
        mine = set()
        for k in range(n):
            mine.add(base + 2 * k)
            mine.add(base + 2 * k + 1)
        if not (mine & wset):
            # A byte array the set does not carry AT ALL is one the frame never dirties -- the
            # standalone tier's `sshead`, baked finished once the per-frame bind was dropped
            # (wall_renderer.baked_thing_lists). Restoring it would ZERO the baked lists, so it is
            # left alone. Partial coverage is still the disagreement it always was (below).
            print("self-reset: byte array %r is not in the restore set: left untouched (never dirtied)"
                  % name)
            continue
        byte_bases.append((name, bits[name], n))
        declared_words.update(range(base, _extent(words_sorted, base)))
        byte_words |= mine
    missing = byte_words - wset
    assert not missing, ("self-reset: %d byte-array words are outside the restore set -- "
                         "the byte arrays disagree with it" % len(missing))
""")
p.write_text(s, encoding="utf-8")
print("selfreset: clean byte arrays are skipped")

# ---- m5_setfile.py: the closed list of labels the standalone set may lack ----------------------
p = Path(r"C:/Users/tomhe/Documents/doom-flipjump/scratchpad/m5_setfile.py")
s = p.read_text(encoding="utf-8")
rep("""EXPECTED_GONE = frozenset({"wmagic"})
""", """# ...and `sshead`, since the per-frame bind was dropped from the standalone tier: its lists are
# baked finished and the frame never dirties them, so restoring (zeroing) them would be the bug.
EXPECTED_GONE = frozenset({"wmagic", "sshead"})
""")
p.write_text(s, encoding="utf-8")
print("m5_setfile: sshead may be gone")

# ---- the shipped-set test pins the new difference ----------------------------------------------
p = Path(r"C:/Users/tomhe/Documents/doom-flipjump/tests/host/test_restore_set_shipped.py")
s = p.read_text(encoding="utf-8")
rep("""    hosted = {e[0] for e in _load(SETS["hosted"])["entries"]}
    standalone = {e[0] for e in _load(SETS["standalone"])["entries"]}
    assert hosted - standalone == {"wmagic"}, (
        "the standalone set drops %s; only 'wmagic' may go" % sorted(hosted - standalone))
""", """    hosted = {e[0] for e in _load(SETS["hosted"])["entries"]}
    standalone = {e[0] for e in _load(SETS["standalone"])["entries"]}
    # ...and `sshead` (2026-09-13): the standalone tier bakes its per-leaf thing lists finished
    # and no longer calls sim.bind_things, so the frame never dirties sshead -- and a reset that
    # zeroed it would destroy the baked lists. wall_renderer.baked_thing_lists is the source.
    assert hosted - standalone == {"wmagic", "sshead"}, (
        "the standalone set drops %s; only 'wmagic' and 'sshead' may go" % sorted(hosted - standalone))
""")
p.write_text(s, encoding="utf-8")
print("test_restore_set_shipped: sshead pinned as standalone-only drop")
