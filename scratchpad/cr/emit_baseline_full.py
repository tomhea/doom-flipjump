"""emit_baseline --check at the PRE-P8a modes ("full" / "full", GAME_RENDER_KW without the D3 keys): P8a's kill
criterion 6 -- package 0's hooks and every fix since are inert there. The game tier's constants are switched for
this process only (wall_renderer reads MONSTER_MODE / PLAYER_MODE at call time)."""
import sys
sys.argv = ["emit_baseline.py", "--check"]
sys.path[:0] = ["scratchpad/cr", "src", "."]
from doomfj import wall_renderer as WR
from doomfj import reference_model as RM
WR.MONSTER_MODE = WR.PLAYER_MODE = "full"
RM.GAME_RENDER_KW["rt_rank"] = RM.GAME_RENDER_KW["exempt_barrels"] = False
print("modes: MONSTER_MODE %r PLAYER_MODE %r, GAME_RENDER_KW rt_rank %r exempt_barrels %r"
      % (WR.MONSTER_MODE, WR.PLAYER_MODE, RM.GAME_RENDER_KW["rt_rank"], RM.GAME_RENDER_KW["exempt_barrels"]), flush=True)
import emit_baseline
sys.exit(emit_baseline.main())
