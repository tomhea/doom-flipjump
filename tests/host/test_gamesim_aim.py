"""#134 -- gamespeed's GameSim (the model the speed tours, gamespeed_trail and the scripted plans step) AIMS AS THE BINARY
DOES: with the window its picture recorded (`combat.window_aim`, written by `sight.SeenHook(aim=True)` from the same
render that marks the seen monsters), not the model default `aim_geometric`.

The fixture is the BINARY's own trail (blocked58, identical to blocked57 there), read through the probe at every
present: game frames 0..79 of `scratchpad/gp/p12_diverge_keys.json` -- a fight fired while strafing left, whose pistol
shot resolved at frame 69 MISSES monster 23 in the binary (its health stays 45). The model must reproduce every frame:
pose, the player's health, every monster's health.

CONTROL (R9): the same GameSim aiming with `aim_geometric` hits monster 23 at frame 69 (35) and parts from the binary
there -- the trail check bites on exactly the bug it guards."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "host" / "data" / "aim134_binary_trail.json"


def _trail(geometric: bool):
    sys.path[:0] = [str(ROOT / "scratchpad" / "12m"), str(ROOT / "scratchpad")]
    import gamespeed as GS
    from doomfj.world import KEYS, World
    sim = GS.GameSim()
    if geometric:
        sim.w.aim = World.aim_geometric
    w = sim.w
    data = json.loads(FIXTURE.read_text(encoding="ascii"))
    out = []
    for kd in data["keys"]:
        w.tic({k: bool(kd.get(k)) for k in KEYS})
        ws = w.ws
        out.append([ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, ws.pangle & 0xFFFFFFFF, ws.p_health % 4096,
                    [h % 4096 for h in ws.mon_health]])
    return out, data["binary"]


def _first_part(model, binary):
    return next((f for f, (m, b) in enumerate(zip(model, binary)) if m != b), None)


def test_gamesim_aims_with_the_pictures_window():
    model, binary = _trail(geometric=False)
    assert len(model) == len(binary) == 80
    assert binary[69][4][23] == 45, "the fixture's premise: the binary's shot at frame 69 misses monster 23"
    assert _first_part(model, binary) is None, "GameSim parts from the binary at frame %s" % _first_part(model, binary)


def test_control_the_geometric_aim_parts_at_frame_69():
    model, binary = _trail(geometric=True)
    assert _first_part(model, binary) == 69, _first_part(model, binary)
    assert model[69][4][23] == 35
