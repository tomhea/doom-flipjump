"""`doomfj.build`'s WIRING -- the parts of the shipped build path that no gate can see fail.

Everything here is a property of the builder's BOOKKEEPING, not of the picture, and every one of
them is invisible to a passing build. That is the point: a wrong pixel gets caught by deg_gate in
twenty minutes, but a guard that never runs, a flag that never reaches the emitter and a stamp that
is never written all look exactly like success.

WHAT THIS FILE PINS, and what breaks in the shipped program if it stops holding:

  * THE DOOR STAMP IS REACHABLE, and round-trips. `build_wall_renderer` writes it inside
    `except Exception: print(...)` so that a stamp can never fail a build -- which means a stamp
    that is never written (wrong argument order, a renamed wad accessor) is invisible forever and
    every M2 gate silently degrades to "no stamp, cannot check". Nothing else proves the site is
    reachable from the entry point (the Feature Wiring Checklist), and nothing else proves the
    JSON round trip is type-clean: `stops()` returning tuples, or `geometry_stamp` keying stops by
    int, would make `compare_stamp` report every door on a binary that is byte-identical to the
    oracle. A guard that cries wolf is a guard the operator turns off.

  * THE QUANT GUARD ACTUALLY DISCRIMINATES. This is the 2026-09-11 failure named in
    `doors.geometry_stamp`'s docstring: a quant-11 oracle gated against a quant-12 binary, the gate
    blamed the renderer for 285 differing pixels, and the whole difference was a door ceiling of
    -120 vs -121. A `compare_stamp` that recomputed `live` at the STAMP's quant would agree with
    anything, silently.

  * THE TWO R4 ASSERTS CAN FIRE (R9 negative control). They are the only things standing between
    "the build printed metrics" and "the binary blew the 2**27 ceiling or silently paged" -- the
    size half of the M6 target. The game tier already shipped 45.6% over the w=32 ceiling once.

  * THE TIER REACHES THE BUILDER'S OWN LOCALS AND ITS OWN METRICS. CR-2026-08 (IN-3, A0.1) by
    name: three emit-shaping flags were absent from `metrics['features']`, so the divergence
    between the artifact shipped, the artifact certified and the artifact a human looked at was
    invisible to every gate log. `test_build_wall_renderer_setup.py` stops at what reaches the
    EMITTER -- which re-derives the flags from the tier string, so it cannot see a mis-bound local
    or a features dict that lies.

  * THE REGISTRY IS A REGISTRY. `tier_flags` reads rows with `TIERS[tier].get(flag, False)`, so a
    misspelled key in a row (`self_rest=True`) is SILENTLY DROPPED and the row means something
    other than it reads -- the exact "a typo builds a different program in silence" failure the
    registry replaced.

  * INCLUDE ORDER (R54). A macro-expansion label is named `f<file>:l<line>:...`, so inserting a
    file earlier in the list renumbers every label after it and the restore set stops resolving --
    measured once at 200 renamed labels and a refused loader, ~50 minutes into a build.

  * `write_program_files` ORDER IS THE CONTRACT. fj top-level labels are global, so reordering the
    parts moves every baked address constant while the program still assembles and still renders.

NOTHING HERE BUILDS. The emitter, the assembler, the interpreter and the span reader are stubbed,
so the whole file is milliseconds; the properties it pins are precisely the ones that live between
those stubs. The self_reset body (two full assembles by construction) is deliberately NOT covered
-- see `tests/host/test_selfreset.py` and `tests/host/test_restore_set_shipped.py`.
"""

import struct
import sys
from pathlib import Path

import pytest

from doomfj import build as B
from doomfj import doors as D
from doomfj.wad import WadFile
from doomfj.wall_renderer import TIERS, TIER_FLAGS, tier_flags, write_program_files

E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"
MAP = "E1M1"
# a real wad that EXISTS and carries no S_START..S_END -- the spriteless-path branch's premise
SPRITELESS_WAD = "tests/fixtures/test.wad"

# The tiers whose build path stops short of the self_reset two-pass assemble. Every test that runs
# `build_wall_renderer` to completion is scoped to these; `game`/`hosted-loop` would assemble the
# ~50M-word image twice by construction.
# ⚠ Read straight off the rows, NOT through `tier_flags`: this file tests `tier_flags`, and scoping
# its own tests with it turns a defect there into a collection error instead of a named failure.
RUNNABLE_TIERS = sorted(t for t in TIERS if not TIERS[t].get("self_reset", False))


@pytest.fixture(scope="module")
def level():
    w = WadFile.from_path(E1M1_WAD)
    return w.sectors(MAP), w.linedefs(MAP), w.sidedefs(MAP)


# ── the door stamp, as a pure round trip ───────────────────────────────────────────────────────

def test_a_written_stamp_reads_back_clean(tmp_path, level):
    """The JSON boundary is TYPE-CLEAN in both directions.

    `write_stamp` dumps `stops()` lists keyed by `str(si)`; `compare_stamp` compares them against
    freshly computed ones. If either side's type or key drifts, a correct binary is reported as
    disagreeing with the oracle that built it."""
    secs, lds, sds = level
    fjm = tmp_path / "doom_e1m1_menu.fjm"
    p = D.write_stamp(fjm, secs, lds, sds)
    assert p.is_file()
    stamp = D.read_stamp(fjm)
    assert stamp is not None
    assert stamp["stops"], "a stamp with no doors would make every comparison below vacuous"
    assert D.compare_stamp(stamp, secs, lds, sds) == []


def test_a_stamp_from_another_quant_is_reported_and_says_why(tmp_path, level):
    """The 2026-09-11 failure, made impossible to repeat.

    Quant 11 and the shipped DEFAULT_QUANT=12 differ by ONE UNIT on one door ceiling -- 285 pixels
    and hours of blaming the renderer. The first reported line must name `quant` and both values,
    not merely "door 7 stops differ": a report that does not say WHY sends the reader back to the
    renderer."""
    secs, lds, sds = level
    assert D.DEFAULT_QUANT != 11, "this test's premise is that 11 is NOT the process's quant"
    fjm = tmp_path / "old.fjm"
    D.write_stamp(fjm, secs, lds, sds, quant=11)
    bad = D.compare_stamp(D.read_stamp(fjm), secs, lds, sds)
    assert bad, "a quant-11 stamp compared clean against a quant-12 process"
    assert bad[0].startswith("quant:"), bad
    assert "11" in bad[0] and str(D.DEFAULT_QUANT) in bad[0], bad[0]
    # ...and the guard must not stop at the scalar keys: the stops it froze really do differ.
    assert any(line.startswith("door ") for line in bad[1:]), bad


def test_one_perturbed_door_reports_that_door_and_only_that_door(level):
    """An early `return bad` after the scalar keys, or a set-only comparison, passes any stamp with
    the right sector set -- which is every stamp from the same map at any quant whose stop COUNT
    happens to match."""
    secs, lds, sds = level
    stamp = D.geometry_stamp(secs, lds, sds)
    victim = sorted(stamp["stops"], key=int)[0]
    stamp["stops"][victim] = [h + 1 for h in stamp["stops"][victim]]
    bad = D.compare_stamp(stamp, secs, lds, sds)
    assert len(bad) == 1, bad
    assert bad[0].startswith("door %s stops:" % victim), bad[0]


def test_a_stamp_with_a_different_door_SET_is_reported_not_raised(level):
    """A stamp from a different map beside this binary must come back as a REPORT. Indexing
    `bs[si]` without the set check first would KeyError inside the gate, which reads as a crashed
    tool rather than as the mismatch it is."""
    secs, lds, sds = level
    stamp = D.geometry_stamp(secs, lds, sds)
    stamp["stops"].pop(sorted(stamp["stops"], key=int)[0])
    stamp["stops"]["9999"] = [0, 8]
    bad = D.compare_stamp(stamp, secs, lds, sds)          # must not raise
    assert any(line.startswith("door sectors differ") for line in bad), bad


def test_a_missing_stamp_is_None_and_the_suffix_is_appended(tmp_path):
    """`scratchpad/m2_std_gate.py` branches on None to warn-and-continue, so a FileNotFoundError
    here makes every pre-stamp binary un-gateable.

    And the path APPENDS: a `with_suffix()`-style cleanup would give `doom_e1m1_menu.fjm` and
    `doom_e1m1_menu.fjm.bak` one shared stamp path, so one build's stamp would silently describe
    another's geometry -- the same class of cross that resolving the restore set by tier prevents.
    """
    assert D.read_stamp(tmp_path / "never_built.fjm") is None
    a = D.stamp_path(tmp_path / "doom_e1m1_menu.fjm")
    b = D.stamp_path(tmp_path / "doom_e1m1_menu.fjm.bak")
    assert a.name == "doom_e1m1_menu.fjm" + D.STAMP_SUFFIX
    assert a != b, "two binaries in one directory must not share a stamp path"


# ── the stub harness: build_wall_renderer without the build ────────────────────────────────────

class _Stop(Exception):
    """Raised from a stub to stop the builder at a known point."""


class _Term:
    def __init__(self, storage_mode="flat"):
        self.storage_mode = storage_mode


# part names chosen so their ALPHABETICAL order is not their emission order (see the
# write_program_files test) and so the include-order test has real emitted paths to look at.
FAKE_PARTS = [("zeta", "; zeta\n"), ("alpha", "; alpha\n"), ("mid", "; mid\n")]


def _stub(monkeypatch, *, span=1 << 20, storage_mode="flat", parts=None):
    """Stub the four expensive things and return the recorder dict.

    `emit_wall_renderer` (~7 min for a sprite tier), `fj.assemble`, `fj.run` and `_span_words` are
    everything in `build_wall_renderer` that costs; what is left between them is the wiring this
    file is about. `_resolve_sprite_wad` is stubbed too so a `things` tier does not depend on a
    20 MB asset wad being present on this machine."""
    rec = {}

    def fake_emit(wad, mapname, cfg, **k):
        rec["emit_kwargs"] = dict(k)
        rec["locals"] = dict(sys._getframe(1).f_locals)   # the caller's frame IS the builder's
        return list(FAKE_PARTS if parts is None else parts)

    def fake_assemble(paths, out, **k):
        rec["paths"] = list(paths)
        Path(out).write_bytes(b"fake fjm")

    def fake_run(out, **k):
        rec["ran"] = True
        return _Term(storage_mode)

    monkeypatch.setattr(B, "emit_wall_renderer", fake_emit)
    monkeypatch.setattr(B, "_span_words", lambda out: span)
    monkeypatch.setattr(B, "_resolve_sprite_wad", lambda mw, sw: mw)
    monkeypatch.setattr(B.fj, "assemble", fake_assemble)
    monkeypatch.setattr(B.fj, "run", fake_run)
    return rec


def _build(tmp_path, monkeypatch, tier="render", name=None, **kw):
    rec = _stub(monkeypatch, **kw)
    out = tmp_path / ((name or tier.replace("-", "_")) + ".fjm")
    m = B.build_wall_renderer(out, wad_path=E1M1_WAD, mapname=MAP, tier=tier)
    return out, m, rec


def test_the_door_stamp_is_written_by_the_shipped_entry_point(tmp_path, monkeypatch, level, capsys):
    """THE wiring check. The stamp site cannot fail a build by design, so only a test can tell
    "written" from "swallowed". Note the tier here has doors=False: the stamp is written
    UNCONDITIONALLY, which is what makes a gate able to trust it regardless of tier."""
    secs, lds, sds = level
    out, _m, _rec = _build(tmp_path, monkeypatch, tier="render")
    err = capsys.readouterr().out
    assert "door stamp not written" not in err, err
    stamp = D.read_stamp(out)
    assert stamp is not None, "build_wall_renderer wrote no stamp beside its binary"
    assert D.compare_stamp(stamp, secs, lds, sds) == []


def test_the_R4_span_assert_can_fire(tmp_path, monkeypatch):
    """R9 negative control for the size half of the M6 target: span == limit is already too big
    (the check is strict), and an assert comparing the wrong local would never say so."""
    with pytest.raises(AssertionError, match="R4"):
        _build(tmp_path, monkeypatch, span=B.RENDER_FLAT_MAX_WORDS)


def test_the_R4_flat_assert_can_fire(tmp_path, monkeypatch):
    """R9 negative control for the other half: a paged binary must refuse, not print metrics."""
    with pytest.raises(AssertionError, match="R4"):
        _build(tmp_path, monkeypatch, storage_mode="hybrid")


def test_the_builder_passes_its_own_R4_gates_when_it_should(tmp_path, monkeypatch):
    """...and the control's control: the same harness one word under the limit must PASS, or the
    two tests above would be green for the wrong reason."""
    _out, m, _rec = _build(tmp_path, monkeypatch, span=B.RENDER_FLAT_MAX_WORDS - 1)
    assert m["storage_mode"] == "flat" and m["span_words"] == B.RENDER_FLAT_MAX_WORDS - 1


def test_metrics_features_mirror_the_tier(tmp_path, monkeypatch):
    """CR-2026-08 (IN-3, A0.1): a flag added to TIERS but not to `metrics['features']` re-opens the
    hole where the shipped artifact and the artifact the log describes were different programs.
    Scoped to the tiers that do not self_reset -- the other two assemble twice."""
    for tier in RUNNABLE_TIERS:
        _out, m, _rec = _build(tmp_path, monkeypatch, tier=tier)
        got = {f: m["features"][f] for f in TIER_FLAGS if f in m["features"]}
        assert got == tier_flags(tier), (tier, got)
        assert m["self_reset"] is None, (
            "%s does not self_reset, so reset_info must stay None" % tier)


def test_every_tier_flag_is_bound_in_the_builders_own_frame(tmp_path, monkeypatch):
    """The three-line tuple unpack (`moving_things, menu, doors = ...`) is copy/paste, and a ninth
    flag added to the registry that the builder never unpacks is a feature that quietly does not
    run -- this repo's most expensive bug class. The setup test stops at the EMITTER, which
    re-derives the flags from the tier string and so cannot see a mis-bound local."""
    for tier in sorted(TIERS):
        rec = _stub(monkeypatch)
        try:
            B.build_wall_renderer(tmp_path / "frame.fjm", wad_path=E1M1_WAD, mapname=MAP,
                                  tier=tier)
        except Exception:
            pass          # a self_reset tier walks on past the emitter; we only want the locals
        loc = rec["locals"]
        missing = [f for f in TIER_FLAGS if f not in loc]
        assert not missing, ("%s: the builder never unpacked %s" % (tier, missing))
        assert {f: loc[f] for f in TIER_FLAGS} == tier_flags(tier), tier


def test_two_binaries_in_one_directory_get_two_generated_dirs(tmp_path, monkeypatch):
    """The existing test pins one path -> one dir, which stays green if the derivation collapses to
    a constant `generated/`. That collapse makes two builds in the same tree overwrite each other's
    ~4.8M lines of emitted .fj -- adjacent builds clobbering each other is already this repo's most
    expensive failure mode (Rule 1)."""
    seen = []

    def fake_emit(*a, **k):
        seen.append(sys._getframe(1).f_locals["gen"])
        raise _Stop()

    monkeypatch.setattr(B, "emit_wall_renderer", fake_emit)
    for stem in ("doom_e1m1_menu", "doom_e1m1_std"):
        with pytest.raises(_Stop):
            B.build_wall_renderer(tmp_path / (stem + ".fjm"), wad_path=E1M1_WAD, tier="render")
        assert stem in seen[-1].name, seen[-1]
    assert seen[0] != seen[1], seen


def test_the_include_order_is_R54(tmp_path, monkeypatch):
    """fj_consts first (it defines the constants every later file reads), the emitted program parts
    LAST, and `sim.fj` last of the fixed includes. R54: a file inserted earlier renumbers every
    macro-expansion label after it and the restore set stops resolving."""
    for tier in RUNNABLE_TIERS:
        _out, _m, rec = _build(tmp_path, monkeypatch, tier=tier)
        names = [Path(p).name for p in rec["paths"]]
        assert names[0] == "fj_consts.fj", names
        prog = [n for n in names if n.startswith(MAP.lower() + "_")]
        assert len(prog) == len(FAKE_PARTS), names
        assert names[-len(prog):] == prog, ("emitted parts must come last", names)
        fixed = names[1:-len(prog)]
        if tier_flags(tier)["player_sim"]:
            assert fixed[-1] == "sim.fj", (tier, fixed)
        else:
            assert "sim.fj" not in fixed, (tier, fixed)
        # only the no-host tier polls the keyboard, and no runnable tier is standalone today --
        # so this arm is the guard that a hosted tier never quietly acquires input.fj.
        assert ("input.fj" in fixed) == tier_flags(tier)["standalone"], (tier, fixed)


def test_the_standalone_tier_puts_input_before_sim_and_the_reset_last(tmp_path, monkeypatch):
    """The `game` tier's path list, caught at `selfreset.capture_labels` -- the first thing the
    self_reset branch does, and before `bake_bsp`. R54 again: `m1_reset.fj` goes AFTER the emitted
    parts (a file that only holds a `def` emits no ops, so appending it moves no address), and
    `input.fj` goes before `sim.fj`, which stays last of the fixed includes."""
    from doomfj import selfreset

    _stub(monkeypatch)
    monkeypatch.setattr(selfreset, "capture_labels",
                        lambda paths, out, **k: (_ for _ in ()).throw(_Stop(list(paths))))
    with pytest.raises(_Stop) as e:
        B.build_wall_renderer(tmp_path / "game.fjm", wad_path=E1M1_WAD, mapname=MAP, tier="game")
    names = [Path(p).name for p in e.value.args[0]]
    assert names[0] == "fj_consts.fj", names
    assert names[-1] == "m1_reset.fj", names
    assert "input.fj" in names and names.index("input.fj") < names.index("sim.fj"), names
    prog = [n for n in names if n.startswith(MAP.lower() + "_")]
    assert names.index("sim.fj") < names.index(prog[0]), (
        "sim.fj must be last of the FIXED includes, before the emitted parts", names)


# ── the registry, and the parts writer ─────────────────────────────────────────────────────────

def test_no_row_carries_a_key_the_registry_does_not_know(tmp_path):
    """`tier_flags` reads rows with `.get(flag, False)`, so `self_rest=True` in a row is silently
    dropped and the row means something other than it reads. Verified clean today, so this is a
    green guard, not a new failure."""
    for tier, row in TIERS.items():
        extra = sorted(set(row) - set(TIER_FLAGS))
        assert not extra, (
            "tier %r carries %s, which tier_flags DROPS -- a row is only as real as TIER_FLAGS"
            % (tier, extra))


def test_no_two_tiers_are_the_same_program():
    """Two names for one program makes a measurement tier silently identical to the tier it is
    being priced against -- and the whole point of the measurement tiers is to price a difference."""
    seen = {}
    for tier in sorted(TIERS):
        key = frozenset(f for f, v in tier_flags(tier).items() if v)
        assert key not in seen, ("%s and %s are the same program" % (seen.get(key), tier))
        seen[key] = tier


def test_a_self_resetting_tier_with_doors_or_a_menu_is_standalone():
    """`_persist` is `(STANDALONE_PERSIST + DOOR_PERSIST) if standalone else ()`, so a
    doors+self_reset tier that is NOT standalone restores the door cells and the `mode` cell every
    frame: every door re-shuts on every frame and the menu flickers between two pictures, while the
    program still renders and still passes a one-frame check. True of all nine rows today; this
    catches the tenth."""
    for tier in sorted(TIERS):
        f = tier_flags(tier)
        if f["self_reset"] and (f["doors"] or f["menu"]):
            assert f["standalone"], (
                "%s persists nothing across its reset, so its doors/menu state dies every frame"
                % tier)


def test_tier_flags_hands_out_a_fresh_dict():
    """A `return TIERS[tier]` simplification lets one caller's mutation leak into every later
    lookup in the same process -- and the M4 nine-level path resolves several tiers per process."""
    a = tier_flags("game")
    a["things"] = "mutated"
    assert tier_flags("game")["things"] is True
    assert TIERS["game"]["things"] is True


def test_write_program_files_keeps_emission_order(tmp_path):
    """ORDER IS THE CONTRACT: fj top-level labels are global, so the ordered files are equivalent
    to their concatenation, and every baked address constant depends on that layout. A sorted() or
    globbed list still assembles and still renders -- byte-differently."""
    parts = [("zeta", "a\n"), ("alpha", "b\n"), ("mid", "c\n")]   # alpha order != emission order
    paths = write_program_files(parts, tmp_path / "gen", "E1M1")
    assert len(paths) == len(parts)
    for i, (name, text) in enumerate(parts):
        assert paths[i].name == "e1m1_%02d_%s.fj" % (i, name), [p.name for p in paths]
        assert paths[i].read_text(encoding="utf-8") == text
    # the property the order exists FOR: concatenating the files reproduces the program.
    assert "".join(p.read_text(encoding="utf-8") for p in paths) == "".join(t for _n, t in parts)


# ── _resolve_sprite_wad: the branches no test executes ─────────────────────────────────────────

def _sprite_pwad(path):
    """A minimal PWAD carrying an S_START..S_END block. No fixture wad has sprite lumps (all six
    checked), and the branches below are about the PRESENCE of that block, not about its art."""
    lumps = [("S_START", b""), ("POSSA1", b"\x00" * 4), ("S_END", b"")]
    body, entries, off = b"", [], 12
    for name, data in lumps:
        entries.append((off, len(data), name))
        body += data
        off += len(data)
    directory = b"".join(struct.pack("<ii8s", o, s, n.encode("ascii").ljust(8, b"\x00"))
                         for o, s, n in entries)
    path.write_bytes(b"PWAD" + struct.pack("<ii", len(lumps), 12 + len(body)) + body + directory)
    return path


def test_an_existing_but_spriteless_PATH_raises_and_names_itself(tmp_path):
    """CR-2026-08, the hole called out in `_resolve_sprite_wad`'s own comment: this used to fall
    back to the map wad, i.e. `things=True` shipped with an EMPTY sprite bank -- a feature that
    quietly does not run. Its siblings (a spriteless WadFile object, nothing in reach) are covered
    by test_e1m1_integration; this branch is not."""
    mapwad = WadFile.from_path(_sprite_pwad(tmp_path / "sprites.wad"))   # map wad HAS sprites...
    with pytest.raises(ValueError) as e:
        B._resolve_sprite_wad(mapwad, SPRITELESS_WAD)                    # ...so no silent fallback
    assert SPRITELESS_WAD.split("/")[-1] in str(e.value), str(e.value)
    assert "S_START" in str(e.value), str(e.value)


def test_a_sprite_carrying_WadFile_is_returned_as_itself(tmp_path):
    """Identity, not a reload: reordering the branches so the map wad won over an explicitly passed
    WadFile would move every sprite pixel and nothing would notice."""
    spr = WadFile.from_path(_sprite_pwad(tmp_path / "sprites.wad"))
    # ⚠ the map wad must ALSO carry sprites, or this is green for the wrong reason: a reordered
    # branch that prefers the map wad still falls through to the explicit one whenever the map has
    # no art, and every fixture map wad here has none. MEASURED -- with a spriteless map wad, the
    # reordering defect passed this test.
    sprite_carrying_map = WadFile.from_path(_sprite_pwad(tmp_path / "mapwad.wad"))
    assert B._resolve_sprite_wad(sprite_carrying_map, spr) is spr
    assert B._resolve_sprite_wad(WadFile.from_path(SPRITELESS_WAD), spr) is spr


def test_an_absent_sprite_path_falls_back_to_a_sprite_carrying_map_wad(tmp_path):
    """The second path `build_wall_renderer`'s docstring promises, and the one the shipped `game`
    build takes whenever `assets/freedoom1.wad` is missing."""
    mapwad = WadFile.from_path(_sprite_pwad(tmp_path / "sprites.wad"))
    assert B._resolve_sprite_wad(mapwad, str(tmp_path / "no_such_file.wad")) is mapwad
    assert B._resolve_sprite_wad(mapwad, None) is mapwad


# -- the guard that would have caught a test rotting behind a marker --------------------------
#
# tests/host/test_e1m1_integration.py::test_build_wall_renderer_e1m1_flat asserts EXACT equality on
# `metrics["features"]` -- deliberately, so a new picture-shaping flag cannot arrive unnoticed. It
# costs a ~30-minute build and is excluded by default, and it had been impossible to pass for some
# time: it called `build_wall_renderer` with the pre-retirement positional signature, and its
# expected dict still listed `sector_heights`, a key that retired INTO `doors`.
#
# A guard that only runs when someone remembers `-m slow` is not a guard. These two run in
# milliseconds, statically, and fail the moment the two halves drift again.

import ast as _ast
import re as _re
from pathlib import Path as _Path

_BUILD_PY = _Path(__file__).resolve().parents[2] / "src" / "doomfj" / "build.py"
_SLOW_TEST = _Path(__file__).resolve().parent / "test_e1m1_integration.py"


def _features_keys_built():
    """The keys `build_wall_renderer` actually puts in metrics['features'], read from its AST.

    Static on purpose: reading them for real means assembling a ~42M-character program."""
    tree = _ast.parse(_BUILD_PY.read_text(encoding="utf-8"))
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, _ast.Constant) and k.value == "features"
                    and isinstance(v, _ast.Dict)):
                return {kk.value for kk in v.keys
                        if isinstance(kk, _ast.Constant) and isinstance(kk.value, str)}
    raise AssertionError("no literal 'features' dict found in build.py -- this guard is blind now")


def _features_keys_asserted():
    """The keys the slow test's exact-equality guard expects."""
    src = _SLOW_TEST.read_text(encoding="utf-8")
    i = src.index('assert m["features"] ==')
    j = src.index("}, m", i)
    return set(_re.findall(r'"([a-z_]+)"\s*:', src[i:j]))


def test_the_slow_tiers_feature_guard_matches_what_build_actually_reports():
    """The exact-equality features guard must name exactly the keys build.py constructs.

    Drift either way is a real defect: a key build.py reports and the guard omits is a
    picture-shaping flag that can change unnoticed -- the thing the guard exists to prevent; a key
    the guard expects and build.py no longer reports makes the guard unpassable, so the 30-minute
    run it gates is dead weight. Both had happened."""
    built, asserted = _features_keys_built(), _features_keys_asserted()
    assert built == asserted, (
        "metrics['features'] keys and the slow test's expected dict disagree.\n"
        "  build.py reports but the guard omits : %s\n"
        "  the guard expects but build.py lacks : %s"
        % (sorted(built - asserted), sorted(asserted - built)))


def test_the_slow_integration_test_can_actually_call_build_wall_renderer():
    """It could not, for several milestones: the signature became keyword-only and the call kept
    passing the wad and map name positionally. `slow` is excluded by default, so a TypeError that
    would have been instant never ran. Bind the call's arguments against the real signature -- no
    build, just `Signature.bind`, which raises exactly as the call would."""
    import inspect

    from doomfj.build import build_wall_renderer

    src = _SLOW_TEST.read_text(encoding="utf-8")
    m = _re.search(r"m = build_wall_renderer\((?P<args>(?:[^()]|\([^()]*\))*)\)", src)
    assert m, "the slow test no longer calls build_wall_renderer in a form this guard can read"
    call = _ast.parse("f(%s)" % m.group("args").replace("\n", " ")).body[0].value
    kwargs = {kw.arg: None for kw in call.keywords}
    args = [None] * len(call.args)
    inspect.signature(build_wall_renderer).bind(*args, **kwargs)   # raises TypeError if it rotted
