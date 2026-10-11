"""rocket_pjsrc_diag.py -- P9 DIAGNOSTIC (not a gate): fight_gate's R rows with the ORACLE's pj_src export taking
projcode's convention for the player's rocket (a rocket's slot holds pj_src 0; a fireball's 1 + its shooter's slot).

    python scratchpad/gp/rocket_pjsrc_diag.py --fjm build/<new>.fjm --labels <its label table> --only R

The finding it isolates (2026-10-11, blocked54): monsters.MonsterPhase.proj_state exports every LIVE slot as
proj_src + 1, and combat._spawn_rocket stores proj_src 0 for the rocket -- so the oracle names the rocket "a fireball of
monster slot 0" (pj_src 1) where the fj stores 0 (projcode's documented convention; tests/fj/test_rocket_fj's R9 mutant
`src_fireball` is exactly the oracle's value). fight_gate R1/R2/R3 part on that cell alone at the rocket's first frame.
This wrapper patches ONLY that export (a rocket slot -> 0) and runs the same gate, so every OTHER cell, every pixel and
every palette is still held on every frame. It is evidence for the report, not a fix: the fix belongs in src/doomfj.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fight_gate as FG                                                      # noqa: E402
from doomfj import monsters as MS                                            # noqa: E402

_orig = MS.MonsterPhase.proj_state


def proj_state(self):
    out = _orig(self)
    ws = self.world.ws
    rocket = [bool(ws.proj_active[s]) and self.world._is_rocket(s) for s in range(len(ws.proj_src))]
    out["pj_src"] = tuple(0 if r else v for r, v in zip(rocket, out["pj_src"]))
    return out


MS.MonsterPhase.proj_state = proj_state

if __name__ == "__main__":
    sys.exit(FG.main(gate="FIGHT (pj_src DIAGNOSTIC: the rocket's slot exported as 0)"))
