"""cr r1: is generate_yslope_packed_lut_fj byte-identical to
generate_packed_lut_fj(label, yslope_table(...), 3) for the shipped config?
(The prerequisite check for the proposed one-line delegation.)"""
import sys
sys.path.insert(0, "src")

from doomfj.config import Config
from doomfj.lut_generator import generate_yslope_packed_lut_fj, generate_packed_lut_fj
from doomfj.tables import yslope_table

cfg = Config()
a = generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H)
b = generate_packed_lut_fj("yslope_packed", yslope_table(cfg.VIEW_W, cfg.VIEW_H), 3)

if a == b:
    print("OK: byte-identical -- delegation is safe")
else:
    la, lb = a.splitlines(), b.splitlines()
    print(f"DIFFER: {len(la)} vs {len(lb)} lines; "
          f"trailing-newline a={a.endswith(chr(10))} b={b.endswith(chr(10))}")
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            print(f"  first diff at line {i}: {x!r} vs {y!r}")
            break
    print("=> delegation would CHANGE emitted bytes; do NOT delegate")
