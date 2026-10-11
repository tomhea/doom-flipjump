"""P9: attribute deg_gate's op change (blocked53's 30,277,162 / 16,391,748 / 30,556,888 / 28,556,306 -> blocked54's
30,313,001 / 16,674,217 / 30,589,536 / 28,600,295, every viewpoint still BYTE-EXACT). Hypothesis: the five things P9
put on the map (the launcher #226 and its rockets #227-230, things.SINGLE_PLAYER_EXTRA) -- none is DRAWN at any of
the four viewpoints, but the renderer processes the things of the leaves it visits. Run deg_gate exactly as it is,
with that allow-list EMPTIED (the things back to multiplayer-only): if the op counts return to blocked53's, the change
is those five things; whatever remains is the rest of P9's visual-tier change (e.g. the rocket's sprite blocks)."""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import things  # noqa: E402

things.SINGLE_PLAYER_EXTRA = frozenset()
print("P9 attribution: things.SINGLE_PLAYER_EXTRA emptied (the launcher and its rockets multiplayer-only again)")
runpy.run_path(str(ROOT / "scratchpad" / "deg_gate.py"), run_name="__main__")
