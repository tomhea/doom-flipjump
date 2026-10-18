"""M8 G13 (docs/episode-plan.md 11): the profiling / heat-list tools are map-generic -- each level gets its OWN pin-heat
list and hot-word list, and no tool reads E1M1's binary, census or lists as another map's.

  - doomfj.mapprofile.heat_list: the map's own list when it exists, else E1M1's (own=False, printed by the tools);
    control: a map whose own file exists gets it, never E1M1's;
  - profx/common: off E1M1 the default binary / label table REFUSE (control: E1M1 keeps blocked27's), the default
    census is the map's one-pass census, and a census of another map is refused (control: the same census passes on
    its own map);
  - poolmap.py --map E1Mn without --fjm refuses (it priced E1M1's binary with the other map's knobs before).
"""
from __future__ import annotations

import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROFX = ROOT / "scratchpad" / "12m" / "profx"
for q in (ROOT / "src", PROFX):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))


def test_heat_list_own_or_e1m1(monkeypatch, tmp_path):
    import doomfj.mapprofile as MP
    assert MP.heat_list("E1M1") == ("scratchpad/12m/heat_blocked27_p10.json.gz", True)
    assert MP.profile("E1M1").heat == MP.heat_list("E1M1")[0]
    assert MP.profile("E1M5").heat == "scratchpad/12m/heat_e1m5.json.gz"
    if not (ROOT / MP.profile("E1M5").heat).exists():
        assert MP.heat_list("E1M5") == ("scratchpad/12m/heat_blocked27_p10.json.gz", False)
    # control: the map's own list, once it exists, is the one used
    own = tmp_path / "heat_e1m5.json.gz"
    own.write_bytes(b"x")
    real = MP.profile
    monkeypatch.setattr(MP, "profile", lambda m=None: MP.MapProfile(**{**real(m).__dict__, "heat": str(own)}))
    assert MP.heat_list("E1M5") == (str(own), True)


def test_default_binary_refused_off_e1m1(monkeypatch):
    import common as C
    monkeypatch.delenv("PROFX_FJM", raising=False)
    monkeypatch.delenv("PROFX_LABELS_TSV", raising=False)
    monkeypatch.setenv("DOOMFJ_MAP", "E1M1")
    assert C.default_fjm().name == "doom_e1m1_blocked27.fjm"            # control: E1M1 unchanged
    assert C.default_labels().name == "blocked27.labels.tsv.gz"
    assert C.default_counts_cache().name == "_counts_game.json.gz"
    monkeypatch.setenv("DOOMFJ_MAP", "E1M4")
    with pytest.raises(SystemExit, match="E1M4"):
        C.default_fjm()
    with pytest.raises(SystemExit, match="E1M4"):
        C.default_labels()
    assert C.default_counts_cache().name == "_census_game_e1m4.json.gz"
    monkeypatch.setenv("PROFX_FJM", "build/doom_e1m4_x.fjm")
    assert C.default_fjm() == Path("build/doom_e1m4_x.fjm")


def test_census_of_another_map_refused(monkeypatch, tmp_path):
    import common as C
    p = tmp_path / "c.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump({"sig": {"map": "E1M2"}, "counts": {}}, fh)
    monkeypatch.setenv("DOOMFJ_MAP", "E1M2")
    assert C.check_census_map(p) == "E1M2"                               # control: its own map passes
    monkeypatch.setenv("DOOMFJ_MAP", "E1M3")
    with pytest.raises(SystemExit, match="E1M2's program, not E1M3's"):
        C.check_census_map(p)


def test_poolmap_needs_the_maps_binary():
    r = subprocess.run([sys.executable, str(ROOT / "scratchpad" / "12m" / "poolmap.py"), "--map", "E1M3"],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert r.returncode == 2 and "--fjm is required off E1M1" in r.stderr, r.stderr[-500:]
