"""Combine the bake-off PNGs (scripts/bakeoff_planes.py output) into labeled contact sheets for a
quick owner look, instead of 29 separate files."""
from pathlib import Path
from PIL import Image, ImageDraw

SRC = Path("scratchpad/bakeoff")
LABEL_H = 22


def strip(names, cols_title, out_name, viewpoint="spawn"):
    imgs = []
    for tag in names:
        p = SRC / f"{tag}_freedoom_e1m1_{viewpoint}.png"
        imgs.append((tag, Image.open(p)))
    w, h = imgs[0][1].size
    sheet = Image.new("RGB", (w * len(imgs), h + LABEL_H), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    for i, (tag, img) in enumerate(imgs):
        sheet.paste(img, (i * w, LABEL_H))
        draw.text((i * w + 6, 4), tag, fill=(255, 255, 0))
    sheet.save(SRC / out_name)
    print(f"wrote {out_name} ({sheet.size})")


strip(["T", "F", "P1", "P2", "P3"], "floor", "contact_floors_spawn.png", "spawn")
strip(["T", "F", "P1", "P2", "P3"], "floor", "contact_floors_rot45.png", "rot45")
strip(["T", "W1", "W2"], "wall", "contact_walls_spawn.png", "spawn")
strip(["T", "W1", "W2"], "wall", "contact_walls_rot45.png", "rot45")
