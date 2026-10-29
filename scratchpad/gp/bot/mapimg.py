"""mapimg.py MAP SKILL X0 Y0 X1 Y1 OUT.png -- the map's lines, the skill's monsters (red: hitscan, orange: imp, magenta:
demon, blue: other), items (green: health, cyan: weapons/ammo), the start, and the route's leg paths (yellow)"""
import sys
sys.path[:0] = ["src", "scripts"]
from PIL import Image, ImageDraw
import level_route as LR
m, sk = sys.argv[1].upper(), sys.argv[2]
x0, y0, x1, y1 = (int(v) for v in sys.argv[3:7])
out = sys.argv[7]
lv = LR.Level(m, None, sk)
r = LR.plan(m, sk)
S = 900 / max(x1 - x0, y1 - y0)
W, H = int((x1 - x0) * S), int((y1 - y0) * S)
im = Image.new("RGB", (W, H), (0, 0, 0)); d = ImageDraw.Draw(im)
to = lambda x, y: ((x - x0) * S, (y1 - y) * S)
for ld in lv.lds:
    a, b = LR._xy(lv.cmap.vertexes[ld.v1]), LR._xy(lv.cmap.vertexes[ld.v2])
    two = ld.back not in (-1, 0xFFFF)
    d.line([to(*a), to(*b)], fill=(255, 200, 0) if ld.special else (90, 90, 90) if two else (220, 220, 220), width=1)
for si, s in enumerate(lv.secs):
    pass
for g in r.get("legs", []):
    pts = [to(*p) for p in g["path"] if p[0] != "teleport"]
    if len(pts) > 1:
        d.line(pts, fill=(255, 255, 0), width=2)
col = {3004: (255, 0, 0), 9: (255, 0, 0), 65: (255, 0, 0), 3001: (255, 140, 0), 3002: (255, 0, 255), 58: (255, 0, 255)}
for t in lv.things:
    x, y = to(t.x, t.y)
    if t.type in col or t.type in (3003, 3005, 3006):
        c = col.get(t.type, (80, 120, 255)); d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=c)
    elif t.type in (2011, 2012, 2013, 2014):
        d.rectangle([x - 3, y - 3, x + 3, y + 3], fill=(0, 255, 0))
    elif t.type in (2001, 2002, 2003, 2005, 2007, 2008, 2048, 2049, 2018, 2019, 8):
        d.rectangle([x - 3, y - 3, x + 3, y + 3], fill=(0, 255, 255))
sx, sy = to(*lv.start[:2]); d.ellipse([sx - 6, sy - 6, sx + 6, sy + 6], outline=(255, 255, 255), width=2)
im.save(out); print("wrote", out, r.get("ok"))
