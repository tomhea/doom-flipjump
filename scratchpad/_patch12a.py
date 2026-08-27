import pathlib

BS = chr(92)
p = pathlib.Path(r'C:\Users\tomhe\Documents\doom-flipjump\src\fj\frame_render.fj')
t = p.read_text(encoding='utf-8')

old_at = ("              ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, u2cls, u2bp, " + BS + "\n"
          "              lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, l2cls, l2bp, " + BS + "\n"
          "              ducnt, du1y1, du1y2, du1cls, du1bp, du2y1, du2y2, du2cls, du2bp, " + BS)
new_at = "              ducnt, du1y1, du1y2, du1cls, du1bp, du2y1, du2y2, du2cls, du2bp, " + BS
assert t.count(old_at) == 1, 'at'
t = t.replace(old_at, new_at)

old_lt = "              seg_lit, seg_lit2, seg_wstrip, wstripbase, " + BS
new_lt = ("              seg_lit, seg_lit2, seg_wstrip, wstripbase, " + BS + "\n"
          "              ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, u2cls, u2bp, " + BS + "\n"
          "              lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, l2cls, l2bp, " + BS)
assert t.count(old_lt) == 1, 'lt'
t = t.replace(old_lt, new_lt)

old_cells = "\n".join([
    "      ucnt: hex.vec 2                           // V5: the stacked boundary pieces (RAW slot",
    "      u1y1: hex.vec 2                           // bytes; counts in the low nibbles)",
] + [f"      {n}: hex.vec 2" for n in
     ("u1y2", "u1cls", "u1bp", "u2y1", "u2y2", "u2cls", "u2bp",
      "lcnt", "l1y1", "l1y2", "l1cls", "l1bp", "l2y1", "l2y2", "l2cls", "l2bp")]) + "\n"
assert t.count(old_cells) == 1, 'cells'
t = t.replace(old_cells, '')

old_call = ('slrb, ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, u2cls, u2bp, '
            'lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, l2cls, l2bp, seg_lit, seg_lit2')
assert t.count(old_call) == 1, 'call'
t = t.replace(old_call, 'slrb, seg_lit, seg_lit2')

old_l2 = ("    def lines_steps_load2 ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, u2cls, u2bp, " + BS + "\n"
          "            lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, l2cls, l2bp, x " + BS + "\n"
          "            @ u1rd, l0rd, l1rd, l2rd, sfb, sfp, sbb, sbp, sidx, stv2, end " + BS + "\n"
          "            < sfflag, sfslot {")
new_l2 = ("    def lines_steps_load2 x " + BS + "\n"
          "            @ u1rd, l0rd, l1rd, l2rd, sfb, sfp, sbb, sbp, sidx, stv2, end " + BS + "\n"
          "            < sfflag, sfslot, ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, u2cls, u2bp, " + BS + "\n"
          "              lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, l2cls, l2bp {")
assert t.count(old_l2) == 1, 'l2def'
t = t.replace(old_l2, new_l2)

old_l2call = ('.lines_steps_load2 ucnt, u1y1, u1y2, u1cls, u1bp, u2y1, u2y2, u2cls, u2bp, '
              'lcnt, l1y1, l1y2, l1cls, l1bp, l2y1, l2y2, l2cls, l2bp, x')
assert t.count(old_l2call) == 1, 'l2call'
t = t.replace(old_l2call, '.lines_steps_load2 x')

p.write_text(t, encoding='utf-8')
print('frame_render refactor ok')
