"""C3: the game tier's emitted parts of a map, hashed per part -- from the source tree SRC (argv 1), so the base
commit's tree (git archive) and the working tree can be compared: rule 3 of docs/episode-agent-brief.md for E1M2.
    python parts_hash.py SRC MAP OUT.json      |  python parts_hash.py --cmp A.json B.json"""
import hashlib
import json
import sys
import time

if sys.argv[1] == "--cmp":
    a, b = (json.load(open(p)) for p in sys.argv[2:4])
    same = [k for k in a["parts"] if a["parts"][k] == b["parts"].get(k)]
    diff = sorted(set(a["parts"]) ^ set(b["parts"]) | {k for k in a["parts"] if a["parts"][k] != b["parts"].get(k)})
    print("%s: %d parts compared, %d SAME, %s" % (a["map"], len(a["parts"]), len(same), "DIFFER %s" % diff if diff
                                                  else "IDENTICAL"))
    sys.exit(1 if diff else 0)
src, m, out = sys.argv[1:4]
sys.path.insert(0, src)
from doomfj.config import Config, map_cfg                    # noqa: E402
from doomfj.wad import WadFile                                # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer, tier_cfg   # noqa: E402
import doomfj                                                 # noqa: E402
import os  # noqa: E402
assert os.path.normcase(os.path.abspath(doomfj.__file__)).startswith(os.path.normcase(os.path.abspath(src))), doomfj.__file__
assert __debug__
WAD = r"C:\Users\tomhe\Documents\doom-c-doors\assets\freedoom1.wad"
mw = WadFile.from_path(WAD)
t = time.time()
parts = emit_wall_renderer(mw, m, tier_cfg(map_cfg(Config(), m), "game"), sprite_wad=mw, tier="game", return_parts=True)
items = parts.items() if isinstance(parts, dict) else parts
res = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in items}
json.dump({"map": m, "src": doomfj.__file__, "parts": res}, open(out, "w"), indent=1)
print("emitted %s from %s in %.0f s: %s" % (m, doomfj.__file__, time.time() - t, {k: v[:12] for k, v in res.items()}))
