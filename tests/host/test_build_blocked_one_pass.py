"""ONE PASS (2/2): scratchpad/12m/build_blocked.py `--one-pass-blocks` drives flipjump's (one-pass) BlockPool
(flipjump #369) -- held on a small stl program through the driver's own main(), its build_wall_renderer standing in:

  (1) ONE assembly: no counting assembly runs (the driver's fj.assemble is reached once), and the pool deferred tables
      (a vacuous run would pass (2) with nothing blocked);
  (2) the program it builds prints what the same program without a pool prints;
  (3) `--counts-cache` receives the census, equal to what a plain BlockPool's assembly of the program reports;
  (4) the flags that need a counting assembly or a counts cache to read are refused, and so is a build without the
      flag (flipjump's BlockPool has no two-pass mode); `--record-sites` records every table and exits;
  (6) a pool with a block for every group pins words, and the collapse alarm stays silent; R9: a span too small for
      any block is called out ("PINNING COLLAPSED"), which the one-pass reset's builds never printed (#130).
"""
import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                           # noqa: E402
from flipjump.assembler.preprocessor import BlockPool                           # noqa: E402

POOL_BASE = 1 << 26                  # above everything the program reaches
XOR = """
stl.startup_and_init_all
    hex.set 4, a, 0x1234
    hex.set 4, b, 0x5678
    rep(24, i) hex.xor 4, a, b
    hex.print_uint 4, a, 1, 1
    stl.loop
a: hex.vec 4
b: hex.vec 4
"""


def _driver(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scratchpad/12m/build_blocked.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(fjm: Path) -> bytes:
    from flipjump.interpreter import fjm_run
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    io = FixedIO(b"")
    fjm_run.run(fjm, io_device=io, print_time=False)
    return io.get_output(allow_incomplete_output=True)


def _build(tmp_path, monkeypatch, capsys, *flags, name="d"):
    """the driver's main() on XOR: (exit code, printed lines, the .fjm, the calls that reached fj.assemble)"""
    mod = _driver("build_blocked_" + name)
    src = tmp_path / "xor.fj"
    src.write_text(XOR)
    calls = []
    real = fj.assemble

    def counted(*a, **k):
        calls.append(type(k.get("table_pool")).__name__)
        return real(*a, **k)

    def fake_build(out_fjm, **_kw):              # build_wall_renderer's stand-in: one fj.assemble of XOR, as build.py
        fj.assemble([src], Path(out_fjm), memory_width=mod.W, print_time=False)
        return {"fjm": str(out_fjm)}

    monkeypatch.setattr(fj, "assemble", counted)     # main() captures it as the REAL assemble
    monkeypatch.setattr(mod, "build_wall_renderer", fake_build)
    monkeypatch.setattr(mod, "pin_state_veto", lambda *a, **k: set())   # the tiny program has no doom cells
    out = tmp_path / ("%s.fjm" % name)
    monkeypatch.setattr(sys, "argv", ["build_blocked.py", "game", "--out", str(out), "--pool-base", hex(POOL_BASE),
                                      "--pin-state-cells", "--width-buckets", "--merge-aliases", *flags])
    try:
        rc = mod.main()                          # --out is absolute, so the driver's ROOT / out is out
    except SystemExit as exc:
        rc = exc.code
    cap = capsys.readouterr()
    return rc, cap.out.splitlines() + cap.err.splitlines(), out, calls


def test_one_assembly_builds_a_program_that_prints_what_the_unpooled_one_prints(tmp_path, monkeypatch, capsys):
    rc, lines, out, calls = _build(tmp_path, monkeypatch, capsys, "--one-pass-blocks")
    assert rc == 0, lines[-5:]
    assert calls == ["BlockPool"], calls                       # (1) ONE assembly, through the one-pass pool
    one = [ln for ln in lines if ln.strip().startswith("one pass:")]
    assert len(one) == 1, lines
    deferred = int(one[0].split("one pass:")[1].split("tables deferred")[0].replace(",", ""))
    assert deferred > 0, one[0]                                # the pool took tables: (2) is not vacuous
    plain = tmp_path / "plain.fjm"
    src = tmp_path / "plain.fj"
    src.write_text(XOR)
    fj.assemble([src], plain, memory_width=32, print_time=False)
    assert _run(out) == _run(plain) != b""                     # (2)


def test_the_census_goes_to_the_counts_cache(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "census.json.gz"
    rc, lines, _out, _calls = _build(tmp_path, monkeypatch, capsys, "--one-pass-blocks", "--counts-cache", str(cache))
    assert rc == 0, lines[-5:]
    with gzip.open(cache, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    # (3) what a plain pool's assembly of the program reports (the stl declares the tables a pool moves)
    mod = _driver("build_blocked_census")
    plain = BlockPool(mod.W, POOL_BASE)
    src = tmp_path / "count.fj"
    src.write_text(XOR)
    fj.assemble([src], tmp_path / "count.fjm", memory_width=mod.W, print_time=False, table_pool=plain)
    census = plain.census()
    assert blob["counts"] == census.counts and blob["counts"], (blob["counts"], census.counts)
    assert {g: int(w) for g, w in blob["widths"].items()} == census.widths


@pytest.mark.parametrize("flag", [["--counts-trust"], ["--preflight-only"]])
def test_the_flags_that_need_a_counting_assembly_are_refused(tmp_path, monkeypatch, capsys, flag):
    rc, lines, _out, calls = _build(tmp_path, monkeypatch, capsys, "--one-pass-blocks", *flag)
    assert rc == 2 and calls == []                             # (4) argparse's error, before any assembly
    assert any("has no counting assembly" in ln and flag[0] in ln for ln in lines), lines


def test_without_the_flag_the_driver_refuses(tmp_path, monkeypatch, capsys):
    rc, lines, _out, calls = _build(tmp_path, monkeypatch, capsys, name="two")
    assert rc == 2 and calls == [] and any("one-pass only" in ln for ln in lines), lines   # (4)


def test_record_sites_records_every_table_in_one_assembly(tmp_path, monkeypatch, capsys):
    sites = tmp_path / "sites.json.gz"
    rc, lines, _out, calls = _build(tmp_path, monkeypatch, capsys, "--one-pass-blocks", "--record-sites", str(sites))
    assert rc == 0 and calls == ["SiteRecorder"], (calls, lines[-5:])
    with gzip.open(sites, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    deferred = int([ln for ln in lines if "one pass:" in ln][0].split("one pass:")[1].split("tables")[0]
                   .replace(",", ""))
    assert blob["tables"] == sum(len(v) for v in blob["groups"].values()) == deferred > 0   # (4) every table
    assert all(path.endswith(")") for v in blob["groups"].values() for path, _ops, _align in v)


def test_the_pins_are_reported_and_a_collapse_is_called_out(tmp_path, monkeypatch, capsys):
    rc, lines, _out, _calls = _build(tmp_path, monkeypatch, capsys, "--one-pass-blocks")
    pins = [ln for ln in lines if ln.strip().startswith("pins:")]
    assert rc == 0 and pins and not any("PINNING COLLAPSED" in ln for ln in lines), lines
    assert int(pins[-1].split("pins:")[1].split("words")[0].replace(",", "")) > 0
    # R9: the assembler's pin map comes back EMPTY while the groups hold their blocks (the collapse's shape: blocks
    # placed, almost nothing pinned) -- the alarm must say so
    from flipjump.assembler import assembler as asm
    monkeypatch.setattr(asm, "resolve_pinned", lambda exprs, labels, reserved_below=1024, exclude=None: ({}, 0))
    rc, lines, _out, _calls = _build(tmp_path, monkeypatch, capsys, "--one-pass-blocks", name="lost")
    assert rc == 0 and any("PINNING COLLAPSED: 0 pinned words" in ln for ln in lines), lines[-8:]
