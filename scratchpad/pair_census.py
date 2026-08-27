"""How much STREAM does a frame emit, and how much of it repeats the previous column?

The emit half's cost scales with (columns walked) x (pairs per column). This decodes the real 0x0B
stream out of an already-built binary -- no rebuild -- and reports pairs per frame plus the DITTO
fraction: columns byte-identical to their left neighbour, which a "repeat previous column" opcode
would collapse to one byte. Ditto is LOSSLESS (same picture, shorter stream), which is what makes
it worth more than any budget knob.

    python scratchpad/pair_census.py <path-to.fjm>
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.reference_model import spawn_state                            # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

cfg = Config()
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
sp = spawn_state(mw, "E1M1")
VPS = [(_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle, "spawn"),
       (1400, 1200, 0, "courtyard"), (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")]


class CountScreen(StreamScreen):
    """StreamScreen + a per-column tally of the pairs the renderer emitted into it."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.pairs_by_col: dict = {}

    def _handle_collines_byte(self, byte: int) -> None:
        if self._cl_active and self._cl_x is not None and self._cl_pend is not None:
            self.pairs_by_col[self._cl_x] = self.pairs_by_col.get(self._cl_x, 0) + 1
        super()._handle_collines_byte(byte)


r = FjmRunner(Path(sys.argv[1]))
print(f"{'viewpoint':11s} {'ops':>12s} {'cols':>5s} {'pairs':>6s} {'pairs/col':>9s} "
      f"{'ditto cols':>10s} {'pairs saved':>11s}")
for vx, vy, va, tag in VPS:
    scr = CountScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    ops = r.run(scr)
    px = list(scr.pixel_indices)
    W, H = cfg.VIEW_W, cfg.VIEW_H
    cols = [bytes(px[y * W + x] for y in range(H)) for x in range(W)]
    ditto = [x for x in range(1, W) if cols[x] == cols[x - 1]]
    saved = sum(scr.pairs_by_col.get(x, 0) for x in ditto)
    tot = sum(scr.pairs_by_col.values())
    print(f"{tag:11s} {ops:12,} {len(scr.pairs_by_col):5d} {tot:6d} "
          f"{tot / max(1, len(scr.pairs_by_col)):9.1f} {len(ditto):10d} "
          f"{saved:6d} ({100 * saved / max(1, tot):.0f}%)")
