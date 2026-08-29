"""M14.5 — is the SHIPPED (non-moving) renderer emission-identical after the split? No assemble.

`subsector_action` is shared with the renderer `build.py` ships, and handoff-m14_5.md section 7b.5
requires that path to come back byte-exact AND op-identical. A full `m14_basegate.py --rebuild` is
~70 minutes; this answers the same question in one emit, because on a static build the split is
inert BY CONSTRUCTION -- `moving_things=False` means every drawable thing is baked, there is no
runtime list, no `thvis`, and the record body keeps its old name -- so the emitted TEXT must be
character-identical to the pre-M14.5 emitter's.

⚠ It proves EMISSION identity, not that the assembler agrees; that is exactly what emit_hash.py is
for elsewhere in this repo, and identical text cannot assemble differently.

⚠ RUN IT ON A TREE WHOSE SPRITE SET MATCHES THE BASELINE. Restoring DROPPED_SPRITE_TYPES changes
the static picture deliberately, and this control is about the STRUCTURE, not the sprite set.

    git stash                                  # if the sprite-set flip is uncommitted
    python scratchpad/m145_static_hash.py      # prints the hash for the CURRENT tree
    git checkout <pre-M14.5 sha> -- src/doomfj && python scratchpad/m145_static_hash.py
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer                       # noqa: E402

# `--cut27` restores the 27M package's sprite set, so a tree that has since restored every sprite
# can be compared against a pre-M14.5 tree on the SAME PICTURE. Without it the two differ for a
# deliberate reason and the comparison says nothing about the structural change.
if "--cut27" in sys.argv:
    keep = set(RM.MONSTER_TYPES) | set(RM.SPRITE_KEEP_EXTRA)
    RM.THING_SPRITE = {k: v for k, v in RM.THING_SPRITE_ALL.items() if k in keep}
    print(f"27M cut applied: {len(RM.THING_SPRITE)} sprite classes")

mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))

# the shipped tier, as m14_basegate builds it: things ON, moving_things OFF
parts = emit_wall_renderer(mw, "E1M1", Config(), return_parts=True, things=True, sprite_wad=art)
text = "".join(t for _n, t in parts) if isinstance(parts, list) else parts
print(f"static emission: {hashlib.sha256(text.encode()).hexdigest()}  {len(text):,} chars")
