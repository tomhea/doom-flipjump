"""M7 P3.2b review B1 -- the frames scratchpad/gp/b0_scenarios.py's `drive` reads, without a binary.

The chase branch of `drive` re-steps a mirror from `frames[0]["run_setup"]` and writes `fr["movers"]`; only
model_frames' FIRST frame carried `run_setup` and the selftest's T1 (gamespeed's DoorSim run) carried neither, so
`--selftest` raised KeyError at T1, and T5's slice (`frs[k0-2:k0+6]`) started on a frame without it. Now every frame
model_frames returns carries `run_setup`, T1's frames come from `doorsim_frames` (with the mirror's `mheights`, as
main's T1 has them), and `drive` refuses a frame list missing a key it reads (`missing_drive_keys`). These tests hold
all three -- and that DRIVE_READS names every key `drive` subscripts, so the check cannot fall behind the code.
"""
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SET_V5 = ROOT / "scratchpad/gp/scenarios/combat_scenarios_v5.json"


@pytest.fixture(scope="module")
def b0s():
    spec = importlib.util.spec_from_file_location("gp_b0_scenarios", ROOT / "scratchpad/gp/b0_scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def v5(b0s):
    """the v5 set with its sight rule in force (scenarios_v2's module global, restored after)"""
    doc = json.loads(SET_V5.read_text(encoding="ascii"))
    saved = b0s.S.SIGHT_RULE
    b0s.S.use_sight_rule(doc)
    yield doc
    b0s.S.SIGHT_RULE = saved


def _short(run, n=4):
    return dict(run, keys=run["keys"][:n], poses=run["poses"][:n])


def test_drive_reads_only_what_drive_reads_says(b0s):
    """every `fr["k"]` / `frames[0]["k"]` in drive's source is a DRIVE_READS key, or one drive guards with
    `fr.get("k")` first (post_doors)"""
    src = inspect.getsource(b0s.drive)
    read = set(re.findall(r'\bfr\["(\w+)"\]', src)) | set(re.findall(r'\bframes\[0\]\["(\w+)"\]', src))
    guarded = set(re.findall(r'\bfr\.get\("(\w+)"\)', src))
    assert "run_setup" in read and "movers" in guarded, "the patterns miss drive's reads: the check is vacuous"
    assert read <= set(b0s.DRIVE_READS) | guarded, sorted(read - set(b0s.DRIVE_READS) - guarded)


def test_model_frames_carry_everything_drive_reads_on_every_frame(b0s, v5):
    run = v5["runs"][0]
    frames = b0s.model_frames(_short(run))
    assert len(frames) == 4
    assert b0s.missing_drive_keys(frames) == []
    assert b0s.missing_drive_keys(frames[2:]) == [], "a slice that starts mid-run (the selftest's T5)"
    assert all(fr["run_setup"] == run["setup"] for fr in frames)


def test_doorsim_frames_carry_the_new_world_and_no_movers(b0s):
    w = b0s.S.new_world()
    frames = b0s.doorsim_frames([{"forward": True}, {"turn_left": True, "forward": True}, {}],
                                b0s.S.BinaryMirror(w))
    assert b0s.missing_drive_keys(frames) == []
    assert all(fr["movers"] is None for fr in frames)
    assert all(fr["mheights"] is not None for fr in frames), "T1's picture needs the mirror's mover heights (M7 P2b)"
    assert frames[0]["run_setup"]["pose"] == frames[0]["inj"]


def test_a_frame_without_run_setup_is_named(b0s, v5):
    """R9: the shape that crashed -- run_setup on the first frame alone -- is refused by name, mid-run"""
    frames = b0s.model_frames(_short(v5["runs"][0]))
    old = [dict(fr) for fr in frames]
    for fr in old[1:]:
        del fr["run_setup"]
    assert b0s.missing_drive_keys(old) == [(1, "run_setup"), (2, "run_setup"), (3, "run_setup")]
    assert b0s.missing_drive_keys(old[2:]) == [(0, "run_setup"), (1, "run_setup")]
    with pytest.raises(AssertionError, match="drive reads keys these frames lack"):
        b0s.drive(None, None, None, old[2:])
