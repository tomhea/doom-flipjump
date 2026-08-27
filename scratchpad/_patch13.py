import pathlib

# ---- wall_renderer: wnoise2/3 tables + hotdata + gnrow2/gnrow3 globals
p = pathlib.Path(r'C:\Users\tomhe\Documents\doom-flipjump\src\doomfj\wall_renderer.py')
t = p.read_text(encoding='utf-8')
old = """    # M13-W1R: the randomized-wall walkers, baked from the oracle's own pattern tables (R6).
    w1rpat = (generate_w1r_walls_fj(rm.W1R_TIER_BOUNDS, rm.W1R_PATTERNS)
              if lines and w1r_flag else "")"""
new = """    # M13-W1R: the randomized-wall walkers, baked from the oracle's own pattern tables (R6).
    w1rpat = (generate_w1r_walls_fj(rm.W1R_TIER_BOUNDS, rm.W1R_PATTERNS)
              if lines and w1r_flag else "")
    # W1R-LOD: the fine (2-px) and coarse (8-px) column-group hashes, dispatch tables like
    # wnoise's -- far tiers mix wnoise2 into their pattern pick, the near tier uses wnoise3.
    wnoise2 = (generate_dispatch_table_fj(
        "wnoise2", [rm.wall_noise2(x) for x in range(cfg.VIEW_W + 1)],
        index_nibbles=2, result_nibbles=2) if lines and w1r_flag else "")
    wnoise3 = (generate_dispatch_table_fj(
        "wnoise3", [rm.wall_noise3(x) for x in range(cfg.VIEW_W + 1)],
        index_nibbles=2, result_nibbles=2) if lines and w1r_flag else "")"""
assert t.count(old) == 1, 'gen'
t = t.replace(old, new)

old = "tex, cm, ttang, sdrecip, srdisp, xtadisp, wnoise, w1rpat, skybands, skyoff, skypid,"
assert t.count(old) == 1, 'hotdata'
t = t.replace(old, "tex, cm, ttang, sdrecip, srdisp, xtadisp, wnoise, wnoise2, wnoise3, w1rpat, skybands, skyoff, skypid,")

old = '        "seg_w1rf: hex.vec 1",                         # W1R-FLAT: this wall stays one flat tone'
assert t.count(old) == 1, 'decl'
t = t.replace(old, old + '\n'
              '        "gnrow2: hex.vec 2",                           # W1R-LOD: the fine 2-px group key\n'
              '        "gnrow3: hex.vec 2",                           # ... and the coarse 8-px one')
p.write_text(t, encoding='utf-8')
print('wall_renderer ok')

# ---- frame_render: lookups + gated ditto compares + shadows/saves/cells
q = pathlib.Path(r'C:\Users\tomhe\Documents\doom-flipjump\src\fj\frame_render.fj')
s = q.read_text(encoding='utf-8')

old = "        rep(noise, k) wnoise.lookup gnrow, x    // V1: this column's grain row, before the ditto test"
assert s.count(old) == 1, 'lookup'
s = s.replace(old, old + "\n"
              "        rep(w1r, k) wnoise2.lookup gnrow2, x    // W1R-LOD: the fine + coarse group keys\n"
              "        rep(w1r, k) wnoise3.lookup gnrow3, x")

old = """        rep(noise, k) hex.cmp 2, gnrow, dgn, dfull, dschk, dfull
      dschk:"""
new = """        rep(noise, k) hex.cmp 2, gnrow, dgn, dfull, dg3c, dfull
      dg3c:
        // W1R-LOD: the coarse 8-px key is in every stacked pattern pick (the near tier)
        rep(w1r, k) hex.cmp 2, gnrow3, dgn3, dfull, dg2g, dfull
      dg2g:
        // ... the fine 2-px key matters only for FAR-tier walls (wlen < 16) or columns that
        // carry a boundary piece/face (faces pick their pattern by their own height): gate
        // the compare so near plain columns keep their 4-px ditto granularity
        rep(w1r, k) hex.mov 2, dwl, fstart
        rep(w1r, k) hex.sub 2, dwl, cexcl
        rep(w1r, k) hex.if0 2, dwl, dgfc
        rep(w1r, k) hex.cmp 2, dwl, cw16, dg2c, dgfc, dgfc
      dgfc:
        rep(w1r, k) hex.if0 1, ucnt, dgf2
        rep(w1r, k) .lines_jmp dg2c
      dgf2:
        rep(w1r, k) hex.if0 1, lcnt, dgf3
        rep(w1r, k) .lines_jmp dg2c
      dgf3:
        rep(w1r, k) hex.if0 1, ufl, dgf4
        rep(w1r, k) .lines_jmp dg2c
      dgf4:
        rep(w1r, k) hex.if0 1, lfl, dschk
      dg2c:
        rep(w1r, k) hex.cmp 2, gnrow2, dgn2, dfull, dschk, dfull
      dschk:"""
assert s.count(old) == 1, 'chain'
s = s.replace(old, new)

old = """        hex.mov 2, dgn, gnrow                   // V1: unconditional so `dgn` is never an UNUSED"""
new = """        hex.mov 2, dgn2, gnrow2                 // W1R-LOD: the two extra key shadows
        hex.mov 2, dgn3, gnrow3
        hex.mov 2, dgn, gnrow                   // V1: unconditional so `dgn` is never an UNUSED"""
assert s.count(old) == 1, 'saves'
s = s.replace(old, new)

old = """      gnrow: hex.vec 2                          // V1: this column's grain row
      dgn: hex.vec 2                            // ... and the previously emitted one"""
new = """      gnrow: hex.vec 2                          // V1: this column's grain row
      dgn: hex.vec 2                            // ... and the previously emitted one
      dgn2: hex.vec 2                           // W1R-LOD: the fine/coarse key shadows
      dgn3: hex.vec 2
      dwl: hex.vec 2                            // ... and the ditto-gate's wlen scratch
      cw16: hex.vec 2, 16"""
assert s.count(old) == 1, 'cells'
s = s.replace(old, new)

# labels + < additions on the leaf
old = "              dvl2, dvl3, dvl4, dvl5, dvl6, dvl7, dvl8, dvl9 " + chr(92)
new = ("              dvl2, dvl3, dvl4, dvl5, dvl6, dvl7, dvl8, dvl9, " + chr(92) + "\n"
       "              dg3c, dg2g, dgfc, dgf2, dgf3, dgf4, dg2c, dgn2, dgn3, dwl, cw16 " + chr(92))
assert s.count(old) == 1, 'labs'
s = s.replace(old, new)

old = ("              ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, u2cls, u2bp, " + chr(92) + "\n"
       "              lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, l2cls, l2bp, " + chr(92))
assert s.count(old) == 1, 'lt'
s = s.replace(old, old + "\n              gnrow2, gnrow3, " + chr(92))

q.write_text(s, encoding='utf-8')
print('frame_render ok')
