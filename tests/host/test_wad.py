from pathlib import Path

import pytest

from doomfj.wad import WadFile, Vertex, Linedef, Sidedef, Sector, Thing

FIXTURES = Path("tests/fixtures")
TEST_WAD = FIXTURES / "test.wad"
MAP = "MAP01"


@pytest.fixture(scope="module")
def wad():
    return WadFile.from_path(TEST_WAD)


def test_header(wad):
    assert wad.wad_type == "PWAD"
    assert len(wad) == 6


def test_lump_names_in_order(wad):
    assert wad.names() == ["MAP01", "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SECTORS"]


def test_vertexes(wad):
    assert wad.vertexes(MAP) == [Vertex(0, 0), Vertex(256, 0), Vertex(256, 256), Vertex(0, 256)]


def test_linedefs(wad):
    lds = wad.linedefs(MAP)
    assert len(lds) == 4
    assert lds[0] == Linedef(v1=0, v2=1, flags=1, special=0, tag=0, front=0, back=-1)
    assert all(ld.back == -1 for ld in lds)  # all one-sided


def test_sidedefs(wad):
    sds = wad.sidedefs(MAP)
    assert len(sds) == 4
    assert sds[0] == Sidedef(x_off=0, y_off=0, upper="-", lower="-", middle="STARTAN2", sector=0)


def test_sectors(wad):
    s = wad.sectors(MAP)
    assert len(s) == 1
    assert s[0] == Sector(floor_h=0, ceil_h=128, floor_tex="FLOOR4_8", ceil_tex="CEIL3_5",
                          light=160, special=0, tag=0)


def test_things(wad):
    t = wad.things(MAP)
    assert t == [Thing(x=128, y=128, angle=90, type=1, flags=7)]  # one player-1 start


def test_get_raw_lump(wad):
    assert wad.get_data("VERTEXES") == bytes(wad.get("VERTEXES").data)
    assert len(wad.get_data("VERTEXES")) == 4 * 4  # 4 vertexes * 4 bytes


def test_missing_lump_raises(wad):
    with pytest.raises(KeyError):
        wad.get("NOPE")


def test_bad_magic_rejected():
    with pytest.raises(ValueError):
        WadFile.from_bytes(b"XWAD" + b"\x00" * 8)


def test_fixture_is_reproducible():
    """The committed binary fixture is exactly what the builder emits (not opaque/tampered)."""
    from tests.fixtures.make_test_wad import build_test_wad
    assert TEST_WAD.read_bytes() == build_test_wad()
