"""M8 C10: A MAP WITH NO BARREL (E1M5, E1M8) is a supported case -- barrelcode asserted one. Proven on E1M1 WITHOUT its
22 barrels (tests/fixtures/map_variants.no_barrels: only its THINGS lump differs), the map every gate knows, and on the
survey of the real E1M5 / E1M8:

- the model: no barrel field has a cell (Layout.nbarrel 0), the final modes' world runs (the player fires, monsters
  fight) and no barrel event happens; check_model_rules accepts the empty set;
- the fj package (barrelcode.barrel_parts): no per-barrel stub (bp<b>_, bdm<b>, dmb<b>), no chain, every barrel cell a
  single dead slot (hex.vec 2 / 1 at 0: bar_st 0 = removed), NEW GAME sets no barrel cell; the shared leaves the
  rocket's blast and the drops use (bl_leaf, bd_leaf, dr_link ...) all still there;
- the survey: E1M5 / E1M8 show barrels 0 as INFO, not REFUSED.
CONTROL (R9): the old rule (barrels >= 1) re-imposed refuses the barrel-less world.
"""
import importlib.util
from pathlib import Path

import pytest

from doomfj import barrelcode as BC
from doomfj import gamedata as gd
from doomfj.wad import WadFile
from doomfj.world import KEYS, World
from tests.fixtures.map_variants import no_barrels

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"


@pytest.fixture(scope="module")
def w0():
    return World(no_barrels(WadFile.from_path(FIX), "E1M1"), "E1M1", player="final", monsters="final")


def test_the_world_has_no_barrel(w0):
    assert w0.barrel_things == [] and w0.layout.nbarrel == 0
    assert all(f.count == 0 for f in w0.schema if f.name.startswith("bar_"))
    w1 = World(WadFile.from_path(FIX), "E1M1", player="final", monsters="final")
    assert len(w1.barrel_things) == 22
    # the same fields; only the barrel ones (and the per-slot id widths they feed) change their counts
    assert [f.name for f in w0.schema] == [f.name for f in w1.schema]


def test_the_final_world_runs_without_barrels(w0):
    for f in range(150):
        k = dict.fromkeys(KEYS, False)
        k["forward"] = f % 4 != 0
        k["turn_left"] = f % 9 == 0
        k["fire"] = f % 3 == 0
        ev = w0.tic(k)
        assert not getattr(ev, "barrel_events", None)


def test_the_barrel_package_is_degenerate(w0):
    BC.check_model_rules(w0, (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD))
    n = w0.layout.nmon
    parts = BC.barrel_parts(w0, nt=60, slot_rt=list(range(n)), boot_skill=gd.SK_MEDIUM,
                            skills=(gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD), knock=True, fight=True, rockets=True)
    text = "\n".join(parts["lines"])
    for stub in ("bp0_", "bdm0:", "dmb0:", "bl_ls0:"):
        assert stub not in text, stub
    for leaf in ("bar_phase:", "bar_next:", "bd_leaf:", "bl_leaf:", "bl_dist:", "dmb_leaf:", "dr_link:", "dr_take:"):
        assert leaf in text, leaf
    assert parts["nbar"] == 0
    decls = {d.split(":")[0]: d for d in parts["decls"]}
    assert decls["bar_st"] == "bar_st: hex.vec 2, 0" and decls["bar_ti"] == "bar_ti: hex.vec 1, 0"
    assert decls["bar_hp"] == "bar_hp: hex.vec 2, 0" and decls["bar_src"] == "bar_src: hex.vec 2, 0"
    for block in parts["restart"]:
        assert not any(ln.strip().startswith(("hex.set 0,", "hex.zero 0,")) for ln in block), block
        assert not any(" bar_st," in ln or " bar_ti," in ln or " bar_hp," in ln for ln in block), block


def test_control_the_old_rule_refuses_the_barrel_less_world(w0, monkeypatch):
    real = BC.check_model_rules

    def old(w, skills=()):
        assert 0 < len(w.barrel_things) <= 255
        return real(w, skills)
    monkeypatch.setattr(BC, "check_model_rules", old)
    with pytest.raises(AssertionError):
        BC.barrel_parts(w0, nt=60, slot_rt=list(range(w0.layout.nmon)), boot_skill=gd.SK_MEDIUM)


@pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")
@pytest.mark.parametrize("m", ["E1M5", "E1M8"])
def test_the_survey_reports_no_barrel_as_supported(m):
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts" / "level_survey.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    wad = ls.WadFile.from_path(str(ART))
    rows = ls.Survey(wad, m, wad).run().rows
    (r,) = [r for r in rows if r[1].startswith("barrels (barrelcode")]
    assert r[0] == "INFO" and r[2] == "0", r
    assert not [r for r in rows if "barrel" in r[1] and r[0] in ("REFUSED", "ERROR")], rows
