import pathlib

p = pathlib.Path(r'C:\Users\tomhe\Documents\doom-flipjump\scratchpad\test_w1r_fj.py')
t = p.read_text(encoding='utf-8')

t = t.replace("CASES = [  # (ctake, fstart, gnrow, wall_lit)  -- full-wall walk cases",
              "CASES = [  # (ctake, fstart, x_column, wall_lit)  -- full-wall walk cases")
t = t.replace("WCASES = [  # (ctake, fstart, wlo, whi, gnrow, wall_lit) -- windowed cases",
              "WCASES = [  # (ctake, fstart, wlo, whi, x_column, wall_lit) -- windowed cases")

old = """def mirror_walk(ctake, fstart, gnrow, wl):
    wl2 = (wl + 0x30) & 0xFF                     # a distinct second colour per case
    out = bytearray()
    for rel, row, alt in ReferenceModel.w1r_runs(fstart - ctake, gnrow):"""
new = """def mirror_walk(ctake, fstart, xcol, wl):
    wl2 = (wl + 0x30) & 0xFF                     # a distinct second colour per case
    out = bytearray()
    for rel, row, alt in ReferenceModel.w1r_runs(fstart - ctake, xcol):"""
assert t.count(old) == 1
t = t.replace(old, new)

old = """def mirror_win(ctake, fstart, wlo, whi, gnrow, wl):
    out = bytearray()
    if wlo >= whi:
        return out
    wl2 = (wl + 0x30) & 0xFF
    for rel, row, alt in ReferenceModel.w1r_runs(fstart - ctake, gnrow):"""
new = """def mirror_win(ctake, fstart, wlo, whi, xcol, wl):
    out = bytearray()
    if wlo >= whi:
        return out
    wl2 = (wl + 0x30) & 0xFF
    for rel, row, alt in ReferenceModel.w1r_runs(fstart - ctake, xcol):"""
assert t.count(old) == 1
t = t.replace(old, new)

old = """    for (ct, fs, gn, wl) in CASES:
        drive += [f"hex.set 2, wlen_r, {fs - ct}", f"hex.set 2, ctake_r, {ct}",
                  f"hex.set 2, fstart_r, {fs}", f"hex.set 2, gnrow_r, {gn}",
                  f"hex.set 2, wlit_r, {wl}","""
new = """    for (ct, fs, xc, wl) in CASES:
        drive += [f"hex.set 2, wlen_r, {fs - ct}", f"hex.set 2, ctake_r, {ct}",
                  f"hex.set 2, fstart_r, {fs}",
                  f"hex.set 2, gnrow_r, {ReferenceModel.wall_noise(xc)}",
                  f"hex.set 2, gnrow2, {ReferenceModel.wall_noise2(xc)}",
                  f"hex.set 2, gnrow3, {ReferenceModel.wall_noise3(xc)}",
                  f"hex.set 2, wlit_r, {wl}","""
assert t.count(old) == 1, 'drive1'
t = t.replace(old, new)

old = """    for (ct, fs, lo, hi, gn, wl) in WCASES:
        drive += [f"hex.set 2, ctake_r, {ct}", f"hex.set 2, fstart_r, {fs}",
                  f"hex.set 2, wlo_r, {lo}", f"hex.set 2, whi_r, {hi}",
                  f"hex.set 2, gnrow_r, {gn}", f"hex.set 2, wlit_r, {wl}","""
new = """    for (ct, fs, lo, hi, xc, wl) in WCASES:
        drive += [f"hex.set 2, ctake_r, {ct}", f"hex.set 2, fstart_r, {fs}",
                  f"hex.set 2, wlo_r, {lo}", f"hex.set 2, whi_r, {hi}",
                  f"hex.set 2, gnrow_r, {ReferenceModel.wall_noise(xc)}",
                  f"hex.set 2, gnrow2, {ReferenceModel.wall_noise2(xc)}",
                  f"hex.set 2, gnrow3, {ReferenceModel.wall_noise3(xc)}",
                  f"hex.set 2, wlit_r, {wl}","""
assert t.count(old) == 1, 'drive2'
t = t.replace(old, new)

old = '"gnrow_r: hex.vec 2", "wlit_r: hex.vec 2", "wlit2_r: hex.vec 2", "cmidx_r: hex.vec 4",'
new = ('"gnrow_r: hex.vec 2", "gnrow2: hex.vec 2", "gnrow3: hex.vec 2", '
       '"wlit_r: hex.vec 2", "wlit2_r: hex.vec 2", "cmidx_r: hex.vec 4",')
assert t.count(old) == 1, 'decls'
t = t.replace(old, new)

old = """    expected = bytearray()
    for (ct, fs, gn, wl) in CASES:
        expected += mirror_walk(ct, fs, gn, wl) + b"\\xFA\\xF5"
    for (ct, fs, lo, hi, gn, wl) in WCASES:
        expected += mirror_win(ct, fs, lo, hi, gn, wl) + b"\\xFA\\xF5\""""
new = """    expected = bytearray()
    for (ct, fs, xc, wl) in CASES:
        expected += mirror_walk(ct, fs, xc, wl) + b"\\xFA\\xF5"
    for (ct, fs, lo, hi, xc, wl) in WCASES:
        expected += mirror_win(ct, fs, lo, hi, xc, wl) + b"\\xFA\\xF5\""""
assert t.count(old) == 1, 'expected'
t = t.replace(old, new)

p.write_text(t, encoding='utf-8')
print('unit test ok')
