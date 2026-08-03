import pathlib

p = pathlib.Path(r'C:\Users\tomhe\Documents\doom-flipjump\src\fj\stream_render.fj')
t = p.read_text(encoding='utf-8')

# 1. emit_col_lines: zlo/vhi set unconditionally in the prologue (the splices' full window)
old = """        rep(noise, k) .wpx_grain_col gnrow, cmidx
        hex.set 2, ccy, centery"""
new = """        rep(noise, k) .wpx_grain_col gnrow, cmidx
        hex.set 2, ccy, centery
        hex.zero 2, zlo                          // the full-column window bounds -- the stacked
        hex.set 2, vhi, viewh                    // splices take [rlo, rhi) even on this path"""
assert t.count(old) == 1, 'prologue'
t = t.replace(old, new)
old = """        rep(things, k) hex.zero 2, zlo
        rep(things, k) hex.set 2, vhi, viewh
"""
assert t.count(old) == 1, 'sprpath-sets'
t = t.replace(old, '')

# 2. main-path splice calls: drop the reg args, add the window
old = ("        rep(stack, k) .steps_splice_c ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, "
       "u2cls, u2bp, ctake, w1r, gnrow, cmidx, cbufa, cbufd, ccy")
new = "        rep(stack, k) .steps_splice_c ctake, zlo, vhi, w1r, gnrow, cmidx, cbufa, cbufd, ccy"
assert t.count(old) == 1, 'call-c'
t = t.replace(old, new)
old = ("        rep(stack, k) .steps_splice_f lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, "
       "l2cls, l2bp, fstart, viewh, w1r, gnrow, cmidx, fbufa, fbufd, ccy")
new = "        rep(stack, k) .steps_splice_f fstart, viewh, zlo, vhi, w1r, gnrow, cmidx, fbufa, fbufd, ccy"
assert t.count(old) == 1, 'call-f'
t = t.replace(old, new)

# 3. emit_region: stack param + windowed splices for its ceiling/floor pieces
old = "    def emit_region lo, hi, viewh, w2s, wpx, w1r, wpxstride, eabl, noise, ascode, ctake, fstart, wall_lit, wall_lit2,"
new = "    def emit_region lo, hi, viewh, w2s, wpx, w1r, stack, wpxstride, eabl, noise, ascode, ctake, fstart, wall_lit, wall_lit2,"
assert t.count(old) == 1, 'region-def'
t = t.replace(old, new)
for oldc in ["rep(things, k) .emit_region zlo, ssy1, viewh, w2s, wpx, w1r, wpxstride",
             "rep(things, k) .emit_region ssy2, vhi, viewh, w2s, wpx, w1r, wpxstride",
             "rep(things, k) .emit_region zlo, sm1, viewh, w2s, wpx, w1r, wpxstride",
             "rep(things, k) .emit_region ssy2b, ssy1, viewh, w2s, wpx, w1r, wpxstride",
             "rep(things, k) .emit_region ssy2, ssy1b, viewh, w2s, wpx, w1r, wpxstride",
             "rep(things, k) .emit_region sm2, vhi, viewh, w2s, wpx, w1r, wpxstride"]:
    assert t.count(oldc) == 1, oldc[:70]
    t = t.replace(oldc, oldc.replace("w1r, wpxstride", "w1r, stack, wpxstride"))

# ... its ceiling piece
old = """      ch2:
        rep((1-eabl/2)*(1-ascode), k) .half_walk cbufa, cbufd, qlo, qbound, ptr, ccy, qwalk, qret
        rep(ascode, k) .half_walk_code cbufa, cbufd, qlo, qbound, ccy"""
new = """      ch2:
        rep((1-eabl/2)*(1-ascode), k) .half_walk cbufa, cbufd, qlo, qbound, ptr, ccy, qwalk, qret
        rep(ascode*(1-stack), k) .half_walk_code cbufa, cbufd, qlo, qbound, ccy
        // V5-SPR: the stacked ceiling prefix, windowed to this region -- faces and the
        // regions behind boundaries now show under/around sprites instead of being cut
        rep(stack, k) .steps_splice_c ctake, lo, hi, w1r, gnrow, cmidx, cbufa, cbufd, ccy"""
assert t.count(old) == 1, 'region-ceiling'
t = t.replace(old, new)

# ... its floor piece
old = """      cf4:
        rep((1-eabl/2)*(1-ascode), k) .half_walk fbufa, fbufd, qlo, qbound, ptr, ccy, qwalk, qret
        rep(ascode, k) .half_walk_code fbufa, fbufd, qlo, qbound, ccy
        ;end"""
new = """      cf4:
        rep((1-eabl/2)*(1-ascode), k) .half_walk fbufa, fbufd, qlo, qbound, ptr, ccy, qwalk, qret
        rep(ascode*(1-stack), k) .half_walk_code fbufa, fbufd, qlo, qbound, ccy
        rep(stack, k) .steps_splice_f fstart, viewh, lo, hi, w1r, gnrow, cmidx, fbufa, fbufd, ccy
        ;end"""
assert t.count(old) == 1, 'region-floor'
t = t.replace(old, new)

p.write_text(t, encoding='utf-8')
print('stream_render call sites ok')

# 4. oracle: paint pieces on sprite columns too (stack builds), sprites painted after
q = pathlib.Path(r'C:\Users\tomhe\Documents\doom-flipjump\src\doomfj\reference_model.py')
s = q.read_text(encoding='utf-8')
old = """                for x in range(cfg.VIEW_W):
                    if sfrag[x] is not None:
                        # V4: ONE overlay per column, and the sprite wins. A column already carries
                        # its ceiling/wall/floor as three windows; splicing a face AND a sprite into
                        # it would mean composing five, and the sprite is in front of the face
                        # anyway (it was recorded into an unclaimed column by a nearer subsector).
                        continue"""
new = """                for x in range(cfg.VIEW_W):
                    if sfrag[x] is not None and not stack_steps:
                        # V4: ONE overlay per column, and the sprite wins (the legacy tier's
                        # trade). V5-SPR paints the pieces UNDER the sprite instead -- the fj
                        # emit_region routes its region windows through the stacked splices, so
                        # walls and ledges no longer look cut where a sprite overlaps them.
                        continue"""
assert s.count(old) == 1, 'oracle-skip'
s = s.replace(old, new)
q.write_text(s, encoding='utf-8')
print('oracle ok')
