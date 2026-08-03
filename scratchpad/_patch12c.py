import pathlib

p = pathlib.Path(r'C:\Users\tomhe\Documents\doom-flipjump\src\fj\stream_render.fj')
t = p.read_text(encoding='utf-8')

# splice_c: region qlo after each piece clamps to the window start rl2 -- a sub-window qlo
# emits sub-cursor pairs, and the 0x0B device REWINDS its cursor on those (it does not drop
# them), letting the next pair repaint rows another piece already painted (the V5-SPR 381-px
# divergence: below-sprite regions repainting sprite rows).
old = """        frame.lines_pid_ids u1bp, rba, rbd, rda, rdd
        hex.mov 2, qlo, u1y2
        hex.inc 2, qlo                          // region 1 starts at the STORED end + 1
        hex.mov 2, qbound, cend"""
new = """        frame.lines_pid_ids u1bp, rba, rbd, rda, rdd
        hex.mov 2, qlo, u1y2
        hex.inc 2, qlo                          // region 1 starts at the STORED end + 1 --
        hex.cmp 2, qlo, rl2, cq1, cq1e, cq1e    // clamped to the window start: a sub-window
      cq1:                                      // qlo would emit SUB-CURSOR pairs, and the
        hex.mov 2, qlo, rl2                     // device REWINDS on those (no silent drop!)
      cq1e:
        hex.mov 2, qbound, cend"""
assert t.count(old) == 1, 'c-q1'
t = t.replace(old, new)

old = """        frame.lines_pid_ids u2bp, rba, rbd, rda, rdd
        hex.mov 2, qlo, u2y2
        hex.inc 2, qlo
        hex.mov 2, qbound, cend"""
new = """        frame.lines_pid_ids u2bp, rba, rbd, rda, rdd
        hex.mov 2, qlo, u2y2
        hex.inc 2, qlo
        hex.cmp 2, qlo, rl2, cq2, cq2e, cq2e
      cq2:
        hex.mov 2, qlo, rl2
      cq2e:
        hex.mov 2, qbound, cend"""
assert t.count(old) == 1, 'c-q2'
t = t.replace(old, new)

old = "            @ conly, ce1, ce2, cgo, cw0, cg0, cg0e, cb1a, cb1b, cg1, cg1e, cp2, cg2, cdone,"
new = ("            @ conly, ce1, ce2, cgo, cw0, cg0, cg0e, cb1a, cb1b, cg1, cg1e, cp2, cg2, "
       "cq1, cq1e, cq2, cq2e, cdone,")
assert t.count(old) == 1, 'c-labs'
t = t.replace(old, new)

# splice_f: same clamps vs flo
old = """        .steps_face l2y1, l2y2, l2cls, qfs, vh2, flo, fend, w1r, gnrow, cmidx
        hex.mov 2, qlo, l2y2
        hex.inc 2, qlo                          // the middle region starts at piece 2's end + 1
      fp1:"""
new = """        .steps_face l2y1, l2y2, l2cls, qfs, vh2, flo, fend, w1r, gnrow, cmidx
        hex.mov 2, qlo, l2y2
        hex.inc 2, qlo                          // the middle region starts at piece 2's end + 1
        hex.cmp 2, qlo, flo, fq2, fq2e, fq2e    // ... clamped to the window start (see cq1)
      fq2:
        hex.mov 2, qlo, flo
      fq2e:
      fp1:"""
assert t.count(old) == 1, 'f-q2'
t = t.replace(old, new)

old = """        .steps_face l1y1, l1y2, l1cls, qfs, vh2, flo, fend, w1r, gnrow, cmidx
        hex.mov 2, qlo, l1y2
        hex.inc 2, qlo
        hex.mov 2, qbound, fend"""
new = """        .steps_face l1y1, l1y2, l1cls, qfs, vh2, flo, fend, w1r, gnrow, cmidx
        hex.mov 2, qlo, l1y2
        hex.inc 2, qlo
        hex.cmp 2, qlo, flo, fq1, fq1e, fq1e
      fq1:
        hex.mov 2, qlo, flo
      fq1e:
        hex.mov 2, qbound, fend"""
assert t.count(old) == 1, 'f-q1'
t = t.replace(old, new)

old = "            @ fonly, fe1, fe2, fl1, fl2, fb2a, fb2b, fg2, fg2e, fb1a, fb1b, fg1, fg1e, fg0,"
new = ("            @ fonly, fe1, fe2, fl1, fl2, fb2a, fb2b, fg2, fg2e, fb1a, fb1b, fg1, fg1e, fg0, "
       "fq1, fq1e, fq2, fq2e,")
assert t.count(old) == 1, 'f-labs'
t = t.replace(old, new)

p.write_text(t, encoding='utf-8')
print('cursor-rewind clamps applied')
