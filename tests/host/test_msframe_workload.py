"""M8 (gates-ready): msframe's timed walk per map. E1M1's spawn faces a long corridor; E1M3..E1M9's spawns meet a wall
within 5-17 frames, so "hold forward from spawn" would time one stuck view. `msframe.py --map M --plan-script` writes
gamespeed's steered route 0 as the map's workload (a DRAFT, promoted to scenarios/<map>/msframe.json); a map with the
file is timed on it, a map without it (E1M1, E1M2: their baselines) keeps hold-forward, the baseline records which.

Controls (R9): hold-forward on E1M3 is stuck (the route must beat it, or the planner proves nothing); a binary named for
another map is refused while one named for the map (and an unnamed one) pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad" / "12m"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))


def test_shipped_maps_keep_hold_forward():
    import msframe as MF
    for m in ("E1M1", "E1M2"):
        assert MF.workload(m) == (None, "forward"), m


def test_workload_file_is_used_and_tagged(monkeypatch, tmp_path):
    import doomfj.mapprofile as MP
    import msframe as MF
    (tmp_path / MF.WORKLOAD_FILE).write_text(json.dumps({"keys": [["forward"]] * 3}), encoding="ascii")
    monkeypatch.setattr(MP, "scenario_dir", lambda m=None: tmp_path)
    p, tag = MF.workload("E1M3")
    assert p == tmp_path / MF.WORKLOAD_FILE and tag.startswith("script ") and len(tag) == len("script ") + 16


def test_plan_script_moves_where_hold_forward_is_stuck(tmp_path):
    out = tmp_path / "w.json"
    r = subprocess.run([sys.executable, str(ROOT / "scratchpad" / "12m" / "msframe.py"), "--map", "E1M3",
                        "--frames", "60", "--plan-script", str(out)], capture_output=True, text=True, cwd=str(ROOT),
                       timeout=900)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    doc = json.loads(out.read_text(encoding="ascii"))
    assert doc["map"] == "E1M3" and len(doc["keys"]) == 60
    assert doc["moved_frames_hold_forward"] < 20, doc["moved_frames_hold_forward"]       # control: forward is stuck
    assert doc["moved_frames_route"] >= 45, doc["moved_frames_route"]


def test_binary_of_another_map_refused(monkeypatch):
    """mapprofile.check_binary (msframe, gamespeed, probe.GameBinary -- every gate's binary): a binary NAMED for another
    map is refused before it loads; one named for the map, or naming none, passes (the control)"""
    import pytest
    from doomfj.mapprofile import binary_map, check_binary
    assert binary_map("build/doom_e1m2_r4.fjm") == "E1M2" and binary_map("build/blocked62.fjm") is None
    check_binary("build/doom_e1m2_r4.fjm", "E1M2")
    check_binary("build/blocked62.fjm", "E1M5")
    with pytest.raises(SystemExit, match="named for E1M1"):
        check_binary("build/doom_e1m1_blocked62.fjm", "E1M5")
    sys.path.insert(0, str(ROOT / "scratchpad" / "gp"))
    import probe as P
    monkeypatch.setattr(P, "_ORACLE_MAPS", {("tests/fixtures/freedoom_e1m5.wad", "E1M5")})
    with pytest.raises(SystemExit, match="measures E1M5"):
        P.GameBinary(ROOT / "build" / "doom_e1m1_blocked62.fjm")       # refused before any file is read
