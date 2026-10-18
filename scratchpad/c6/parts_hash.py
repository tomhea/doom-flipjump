"""M8 C6: a map's game-tier EMISSION, part by part, as SHA-256 -- the identity proof for a map a change must not move
(E1M2 here; E1M1 has scratchpad/cr/emit_baseline.py). Run it once on the base tree (PYTHONPATH at that tree's src) and
once on the change, then compare the two JSON files:

    PYTHONPATH=<base>/src python scratchpad/c6/parts_hash.py E1M2 --out base.json
    PYTHONPATH=src        python scratchpad/c6/parts_hash.py E1M2 --out new.json
    python scratchpad/c6/parts_hash.py --compare base.json new.json

`--powers` emits the map with a partial invisibility and a radiation suit added beside the player start (the C6
wiring on a map that emits today: every asserted rule and every label the power text names must be declared).
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def emit(mapname, powers=False):
    from doomfj.config import Config, map_cfg
    from doomfj.mapprofile import profile
    from doomfj.wad import Thing, WadFile
    from doomfj.wall_renderer import emit_wall_renderer, tier_cfg
    mw = WadFile.from_path(str(ROOT / profile(mapname).wad))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    if powers:
        base = mw

        class _W:
            def __getattr__(self, n):
                return getattr(base, n)

            def things(self, m):
                out = list(base.things(m))
                if m == mapname:
                    st = next(t for t in out if t.type == 1)
                    out += [Thing(st.x + 64, st.y, 0, 2024, 7), Thing(st.x + 64, st.y + 48, 0, 2025, 7)]
                return out
        mw = _W()
    cfg = tier_cfg(map_cfg(Config(), mapname), "game")
    parts = emit_wall_renderer(mw, mapname, cfg, sprite_wad=art, tier="game", return_parts=True)
    return list(parts.items() if isinstance(parts, dict) else parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--powers", action="store_true")
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        x, y = (json.loads(Path(p).read_text()) for p in a.compare)
        same = sorted(k for k in x if y.get(k) == x[k])
        diff = sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
        print("compared %d parts: SAME %s DIFFERENT %s" % (len(set(x) | set(y)), same, diff))
        return 1 if diff else 0
    assert __debug__, "asserts ON"
    t = time.time()
    parts = emit(a.map, a.powers)
    out = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in parts}
    print("emitted %s in %.0f s: %s" % (a.map, time.time() - t, {k: (len(v), out[k][:16]) for k, v in parts}))
    if a.powers:
        text = "\n".join(v for _k, v in parts)
        defined = set(re.findall(r"^\s*([A-Za-z_][\w.]*):", text, re.M))
        from doomfj import powercode as PC
        names = ["p_inv", "p_rad", "pw_c128", "md_jit", "mm_shjret", "pw_shm", "pw_lk", "mm_shj", "shj", "shm", "sutr",
                 "playpal13", "pal_new", "mt_pl", "mm_rng", "nk_dmg", "rng_pl", "hsd_on", "hsd_off", "nk_suit"]
        missing = [n for n in names if n not in defined and ("ns %s {" % n) not in text and ("def %s " % n) not in text]
        uses = {n: text.count(n) for n in ("stl.fcall mm_shj", "hex.add 4, md_sp, md_jit", "shm.lookup",
                                           "sutr.lookup", "hex.dec 3, p_inv", "hex.dec 3, p_rad",
                                           "hex.set 1, pal_new, 13", "hex.set 3, p_inv, 2100",
                                           "hex.set 3, p_rad, 2100", "hex.zero 3, p_inv", "hsd_on:")}
        print("power labels missing:", missing, "\nuses:", uses)
        from doomfj import build
        assert PC.map_persist is not None and build is not None
        assert not missing
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
