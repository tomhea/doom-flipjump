"""M8 (CR of #146, R3): `mapprofile.take_map_arg` -- the one place a tool's `--map E1Mn` becomes the process's map.

  * `--map e1m2` and `--map=E1M2` select E1M2: ACTIVE and DOOMFJ_MAP set, the flag removed from argv (or kept with
    keep=True, for a tool whose own parser takes --map);
  * no flag leaves the active map alone;
  * CONTROL: a `probe` already imported on another map is REFUSED, not half-applied.
"""
import os
import sys
import types

import pytest

from doomfj import mapprofile as MP


@pytest.fixture
def clean(monkeypatch):
    monkeypatch.setattr(MP, "ACTIVE", "E1M1")
    monkeypatch.delenv("DOOMFJ_MAP", raising=False)
    for name in ("probe", "gamespeed"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    return monkeypatch


@pytest.mark.parametrize("argv", [["tool", "--map", "e1m2", "--x"], ["tool", "--map=E1M2", "--x"]])
def test_the_flag_selects_the_map_and_is_removed(clean, argv):
    assert MP.take_map_arg(argv) == "E1M2"
    assert MP.ACTIVE == "E1M2" and os.environ["DOOMFJ_MAP"] == "E1M2"
    assert argv == ["tool", "--x"]


def test_keep_leaves_the_flag_for_the_tools_own_parser(clean):
    argv = ["tool", "--map", "E1M2"]
    assert MP.take_map_arg(argv, keep=True) == "E1M2"
    assert argv == ["tool", "--map", "E1M2"]


def test_no_flag_keeps_the_active_map(clean):
    argv = ["tool", "--fjm", "x.fjm"]
    assert MP.take_map_arg(argv) == "E1M1"
    assert argv == ["tool", "--fjm", "x.fjm"] and MP.ACTIVE == "E1M1"


def test_control_probe_imported_on_another_map_is_refused(clean):
    clean.setitem(sys.modules, "probe", types.SimpleNamespace(DEFAULT_MAP="E1M1"))
    with pytest.raises(SystemExit, match="imported on E1M1 first"):
        MP.take_map_arg(["tool", "--map", "E1M2"])
    assert MP.ACTIVE == "E1M1"
