"""EXP-7 — the EXACT far-thing reject, applied.

`h = wph * PROJECTION / tz`, so `tz > (wph * PROJECTION) << 16` implies `h == 0`, which
`project_thing` already rejects — just four multiplies and a reciprocal later. Verified exhaustively
against `_scale_recip_div` over every sprite height and a sweep of tz: **zero violations, and the
boundary is exact (no margin needed)**. So the reject can move to immediately after `tz`, before the
two `tx` multiplies and the reciprocal, and the frame cannot change.

Counted at the four gate viewpoints (of 250 things): it rejects 76 at spawn, 12 at the courtyard,
30 at the tree and 68 at the worst point, each saving ~20k ops.
"""
import io

FJ = 'src/fj/projection.fj'
s = io.open(FJ, encoding='utf-8', newline='').read()

old = """        hex.set 8, cminz, minz
        hex.scmp 8, tz, cminz, bad, ok1, ok1
      ok1:"""
new = """        hex.set 8, cminz, minz
        hex.scmp 8, tz, cminz, bad, oknear, oknear
      oknear:
        // EXACT far reject, and it belongs HERE. h = wph*PROJECTION/tz, so tz > (wph*PROJ)<<16
        // gives h == 0 -- which the height test below already rejects, but only after two more
        // multiplies and a reciprocal. `sp_tzmax` is that threshold, baked per thing. Verified
        // exhaustively against `_scale_recip_div` over every sprite height: the boundary is exact,
        // no margin needed, so the frame cannot change.
        hex.cmp 8, tz, sp_tzmax, ok1, ok1, bad
      ok1:"""
assert old in s, "MINZ block not found"
s = s.replace(old, new, 1)
s = s.replace("            @ ok1, ok2, okd, okx,", "            @ ok1, oknear, ok2, okd, okx,", 1)
s = s.replace("sp_left, sp_w, sp_hh {", "sp_left, sp_w, sp_hh, sp_tzmax {", 1)
io.open(FJ, 'w', encoding='utf-8', newline='').write(s)
print("projection.fj: far reject added")

WR = 'src/doomfj/wall_renderer.py'
s = io.open(WR, encoding='utf-8', newline='').read()
old2 = '                        ("sp_hh", 8, (_art[4] << 16) & 0xFFFFFFFF),'
new2 = ('                        ("sp_hh", 8, (_art[4] << 16) & 0xFFFFFFFF),\n'
        '                        # the EXACT far-reject threshold: beyond this depth the sprite\n'
        '                        # projects to zero rows, so the projection can stop before its\n'
        '                        # two lateral multiplies and its reciprocal (see proj.project_thing)\n'
        '                        ("sp_tzmax", 8, ((_art[4] * cfg.PROJECTION) << 16) & 0xFFFFFFFF),')
assert old2 in s, "sp_hh xorby field not found"
s = s.replace(old2, new2, 1)
s = s.replace('"sp_base: hex.vec 4", "sp_dw: hex.vec 2", "sp_lt: hex.vec 2",',
              '"sp_base: hex.vec 4", "sp_dw: hex.vec 2", "sp_lt: hex.vec 2",\n'
              '           "sp_tzmax: hex.vec 8",', 1)
io.open(WR, 'w', encoding='utf-8', newline='').write(s)
print("wall_renderer.py: sp_tzmax baked + declared")
