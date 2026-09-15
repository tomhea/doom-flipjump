"""Host-side pins for `doomfj.fastrun.FjmRunner` -- the loader/runner underneath EVERY measurement
this repo quotes (build.py's --validate path, scratchpad/bench.py, scratchpad/12m/frames.py, the
walkers) -- driven by hand-forged .fjm files, so the properties are checked in seconds instead of
only by the ~30-minute tests/fj suite (test_lines_render.py::test_fjm_runner_matches_flipjump_run
is the only other place any of this is checked, and it assembles a renderer to do it).

WHAT BREAKS IN THE SHIPPED PROGRAM IF THESE STOP HOLDING:

* `run()` mirrors `flipjump.run` -- same op count AND same output bytes.  FjmRunner exists only to
  skip the per-frame reload; the moment it runs a different memory image, every op-count and
  byte-exactness gate in this repo is measuring something other than what `fj --run` ships.
* The per-frame restore really restores.  FlipJump programs self-modify (every `wflip`, and this
  renderer's whole `xor_by` per-seg constant machinery), so a second run on a dirty image is a
  DIFFERENT PROGRAM.  `test_reusing_a_dirty_core_changes_the_bytes_not_the_op_count` is the R9
  negative control: the forged program run twice on one un-reset core returns the SAME op count and
  DIFFERENT bytes -- the failure is invisible to an op-count gate, which is exactly why the restore
  needs a test of its own.
* `attach_memory` happens AFTER the restore, with a fresh NativeDeviceMemory carrying the FILE's
  width.  ScreenIO/StreamScreen read pixels through that adapter: attaching before the restore (or
  keeping a stale adapter) hands the present layer last frame's memory -- a torn frame at an
  identical op count -- and a wrong width mis-decodes every packed data-byte.
* `.native` is a reporting flag, never a behavioural one (the class docstring's "callers never need
  to branch on it").  The fallback must keep `flat_max_words` and must stay SILENT: the gates parse
  stdout, and `flipjump.run` prints a termination summary unless told not to.
* The contiguous-run coalescing is the only real logic in the module.  It must reproduce
  `fjm_reader.Reader.memory` exactly AND stay maximal: a degenerate one-run-per-word coalescer is
  byte-identical and op-count-identical, so only the run SHAPE catches it -- and that is ~6.36M
  `set_words` calls per frame on E1M1, i.e. the cost the class exists to remove.
* `_segments` / `_runs` / `width` / `flat_max_words` are a CROSS-FILE contract (CLAUDE.md rule 5):
  tests/fj/test_m1_reset.py's `run_clear` reaches into all four to build its own core.
* CR-2026-08: `self._mem.memory = {}` must run on BOTH paths.  It used to sit inside the
  `if self.native:` block, leaking the parsed int->int dict (~350 MB on E1M1) for the whole session
  whenever the fallback was taken -- invisible in any output, fatal on the memory-bound box that
  CLAUDE.md rule 1 is about.

COST: every program here is a hand-forged .fjm of a few dozen words, so nothing assembles and
nothing builds.  The flat window is pinned to TEST_FLAT_WORDS on every runner that is actually RUN
-- never the config default, which is 2^27 words and would allocate a 1 GB flat image per core.
"""
from pathlib import Path

import pytest

import flipjump as fj
from flipjump.fjm import fjm_reader, fjm_writer
from flipjump.fjm.fjm_consts import FJMVersion
from flipjump.interpreter.fjm_run import IOReadOnEOF
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from flipjump.utils.exceptions import FlipJumpReadFjmException

import doomfj.fastrun as fastrun
from doomfj.config import RENDER_FLAT_MAX_WORDS
from doomfj.fastrun import FjmRunner

# Flat windows for the forged programs. TEST_FLAT is above every address they use (so the native
# core freezes); TINY_FLAT is below FAR_WORD (so the same file is paged and freeze() refuses).
TEST_FLAT_WORDS = 1 << 16
TINY_FLAT_WORDS = 1 << 12
FAR_WORD = 50_000

OUT_BYTE = 0x41                     # b'A'; FixedIO assembles output LSB-first, and bit 0 is set,
                                    # which is the bit the self-modifying program toggles
SELF_MOD_OUT_WORD = 6               # the first output op's FLIP word -- word 4 holds the toggler

native_only = pytest.mark.skipif(
    not (fastrun._fjcore is not None and fastrun.is_native_engine_active()),
    reason="no native engine here: FjmRunner takes the fj.run fallback, so there is no core to pin",
)


# --------------------------------------------------------------------------- forging .fjm files

def _forge(width: int, byte: int = OUT_BYTE, self_modifying: bool = False):
    """A minimal runnable FlipJump program, as a word list: emit one `byte`, then halt by looping.

    The FlipJump memory map fixes the first four words, so code starts at word 4:
      words 0,1  the first op -- execution starts at bit address 0
      word 2     the output bits (2w emits a 0, 2w+1 emits a 1)
      word 3     the input bit (3w + #w); an op whose ip lands within 2w of it READS input, which
                 is why nothing executable may sit below word 4
    `self_modifying=True` prepends one op that flips bit 0 of the FIRST output op's flip word,
    turning 2w into 2w+1. So the program emits `byte` only from a PRISTINE image: run it again
    without restoring and that bit is already set, so the low output bit comes out inverted --
    at an identical op count.
    """
    w = width
    out_bit = (2 * w, 2 * w + 1)
    bits = [(byte >> i) & 1 for i in range(8)]              # the wire order FixedIO assembles
    assert not self_modifying or bits[0] == 1, "the toggled bit must be 1 on a pristine image"

    mod = 1 if self_modifying else 0
    op_word = [4 + 2 * i for i in range(mod + 8 + 1)]       # ...+1 for the halt op
    scratch = op_word[-1] + 2                               # a word no op reads: flip it harmlessly
    assert not self_modifying or op_word[mod] == SELF_MOD_OUT_WORD

    words = {0: scratch * w, 1: op_word[0] * w, 2: 0, 3: 0}
    if self_modifying:
        words[op_word[0]] = op_word[mod] * w                # flip bit 0 of the first output op
        words[op_word[0] + 1] = op_word[mod] * w            # ...then run it
    for i, bit in enumerate(bits):
        here = op_word[mod + i]
        # the toggled op is STORED as "emit 0" and flipped to "emit 1" just before it executes
        words[here] = out_bit[0] if (self_modifying and i == 0) else out_bit[bit]
        words[here + 1] = op_word[mod + i + 1] * w
    halt = op_word[-1]
    words[halt] = scratch * w        # a flip outside [ip, ip+2w) makes the self-jump a clean halt
    words[halt + 1] = halt * w

    data = [words.get(i, 0) for i in range(scratch + 1)]
    if len(data) % 2:
        data.append(0)               # a segment's data must be a whole number of (flip, jump) ops
    return data


def _write_fjm(path: Path, width: int, segments) -> Path:
    """Write a .fjm from (segment_start, segment_length, data_words) triples, in file order.

    NormalVersion keeps the jump words literal -- the relative-jump versions rewrite them on the
    way out and back -- so the forged word list IS what fjm_reader.Reader hands back."""
    writer = fjm_writer.Writer(Path(path), width, FJMVersion.NormalVersion)
    for start, length, data in segments:
        data = list(data)
        writer.add_segment(start, length, writer.add_data(data), len(data))
    writer.write_to_file()
    return Path(path)


def _hello_fjm(tmp_path, width: int = 32, self_modifying: bool = False, name: str = "hello") -> Path:
    data = _forge(width, self_modifying=self_modifying)
    return _write_fjm(tmp_path / f"{name}{width}.fjm", width, [(0, len(data), data)])


# The multi-segment fixture's shape, kept next to the reason each part is there.
GAP_START = 100          # a detached data segment, so the coalescer must break the run here
PAD_START = 200
PAD_WORDS = 1400         # 1398 zero-pad words -- past the Reader's 1000-word dict threshold, so
                         # they live in zeros_boundaries and NEVER in Reader.memory


def _multi_segment_fjm(tmp_path, width: int = 32):
    """A .fjm with an address GAP and a big zero-padded segment. Returns (path, expected blocks),
    the blocks being the contiguous (start, length) runs the coalescer is supposed to find."""
    program = _forge(width)
    gap_data = [1, 2, 3, 4, 5, 6, 7, 8]
    pad_data = [9, 10]
    path = _write_fjm(tmp_path / "multi.fjm", width,
                      [(0, len(program), program),
                       (GAP_START, len(gap_data), gap_data),
                       (PAD_START, PAD_WORDS, pad_data)])
    return path, [(0, len(program)), (GAP_START, len(gap_data)), (PAD_START, len(pad_data))]


# --------------------------------------------------------------------------- driving them

def _run(runner) -> tuple:
    io = FixedIO(b"")
    ops = runner.run(io)
    return ops, io.get_output()


def _reference(path: Path, flat_max_words: int = TEST_FLAT_WORDS) -> tuple:
    """What `flipjump.run` -- the one-shot API FjmRunner replaces -- makes of the same file."""
    io = FixedIO(b"")
    stats = fj.run(path, io_device=io, print_time=False, print_termination=False,
                   flat_max_words=flat_max_words)
    return stats.op_counter, io.get_output()


# --------------------------------------------------------------------------- the mirror

def test_run_mirrors_flipjump_run(tmp_path):
    """The module docstring's central claim: "Output is byte-identical to flipjump.run" -- and the
    op count with it, since op counts are this repo's currency.

    Everything that silently changes the image handed to the native core lands here: a wrong
    `width`, runs shifted by a word, a lost segment. None of them raises; they just run a
    different program."""
    path = _hello_fjm(tmp_path)
    want_ops, want_out = _reference(path)
    assert (want_ops, want_out) == (10, bytes([OUT_BYTE])), "the reference itself must not be empty"

    assert _run(FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)) == (want_ops, want_out)


def test_width_comes_from_the_file_not_a_baked_32(tmp_path):
    """`width` feeds both `_fjcore.Memory(...)` and `NativeDeviceMemory(core, width)` -- the latter
    is how the present layer decodes packed data-bytes. A baked 32 does not raise on a w=16 file,
    it runs a mis-decoded program to completion, so the w=16 leg RUNNING CORRECTLY is the pin."""
    for width in (16, 32):
        path = _hello_fjm(tmp_path, width=width)
        runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
        assert runner.width == width == fjm_reader.Reader(path).memory_width
        assert _run(runner) == _reference(path), f"w={width} ran a different program"


# --------------------------------------------------------------------------- the per-frame restore

def test_repeated_runs_of_a_self_modifying_program_are_identical(tmp_path):
    """One FjmRunner, three runs, all equal to a fresh `flipjump.run`. This is the whole reason the
    class may not cache a dirty image: the renderer self-modifies, so without the restore run N+1
    renders a different frame. See the negative control below for proof this can fail."""
    path = _hello_fjm(tmp_path, self_modifying=True, name="selfmod")
    want = _reference(path)
    assert want[1] == bytes([OUT_BYTE]), "the fixture must emit the pristine byte"

    runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
    for attempt in range(3):
        assert _run(runner) == want, f"run {attempt} diverged"


@native_only
def test_reusing_a_dirty_core_changes_the_bytes_not_the_op_count(tmp_path):
    """R9 negative control for the test above: prove the forged program can tell a restored image
    from a dirty one -- AND that the failure is invisible to an op-count gate.

    It doubles as the pin on the cross-file contract tests/fj/test_m1_reset.py::run_clear depends
    on (CLAUDE.md rule 5): `_segments` + `_runs` + `width` + `flat_max_words` must be enough, on
    their own, to rebuild a core that runs the program."""
    path = _hello_fjm(tmp_path, self_modifying=True, name="selfmod")
    want = _reference(path)

    runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
    core = fastrun._fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg_start, seg_len in runner._segments:
        core.add_segment(seg_start, seg_len)
    for start, vals in runner._runs:
        core.set_words(start, vals)

    got = []
    for _ in range(2):                       # deliberately NOT restoring between the two
        io = FixedIO(b"")
        io.attach_memory(NativeDeviceMemory(core, runner.width))
        _cause, ops, _err, _last, _paused = core.run(
            io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
        got.append((ops, io.get_output()))

    assert got[0] == want, "rebuilding from _segments/_runs must reproduce the program"
    assert got[1][0] == got[0][0], "the drift is meant to be invisible to op counts"
    assert got[1][1] != got[0][1], \
        "the fixture does not self-modify, so the restore test above proves nothing"


@native_only
def test_attach_memory_is_fresh_after_the_restore_on_every_run(tmp_path):
    """The device adapter is handed over once per run, AFTER the image is restored, and carries the
    runner's width. A ScreenIO reading through an adapter attached before the reset would see last
    frame's memory -- with the op count unchanged, so no op-count gate would notice."""
    path = _hello_fjm(tmp_path, self_modifying=True, name="selfmod")
    pristine_word = 2 * 32                   # what SELF_MOD_OUT_WORD holds before the program runs

    class _Spy(FixedIO):
        def __init__(self):
            super().__init__(b"")
            self.attached = []

        def attach_memory(self, device_memory):
            self.attached.append((type(device_memory), device_memory.memory_width,
                                  device_memory.read_word(SELF_MOD_OUT_WORD)))

    runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
    for attempt in range(2):
        spy = _Spy()
        runner.run(spy)
        assert spy.attached == [(NativeDeviceMemory, runner.width, pristine_word)], \
            f"run {attempt}: adapter attached late, stale, or at the wrong width"
        assert spy.get_output() == bytes([OUT_BYTE])


# --------------------------------------------------------------------------- .native is cosmetic

def test_fallback_path_matches_native_and_prints_nothing(tmp_path, monkeypatch, capsys):
    """With the native engine reported absent, `run()` must still return the same op count and the
    same bytes -- `.native` is a reporting flag, never a behavioural one.

    The silence half pins `print_time=False, print_termination=False`: `flipjump.run` defaults to
    printing a termination summary, and this repo's gates parse stdout.

    The window half pins that each runner hands `fj.run` ITS OWN `flat_max_words`. Nothing
    observable can prove that one: too small a window only makes the engine page, which is
    byte-identical, op-count-identical and (on the 2^27-word game image) ~0.5 s/frame slower, and a
    forged program of a few dozen words fits every window anyway. So the forwarded kwarg is
    RECORDED instead, through a spy that still delegates to the real `flipjump.run` -- and two
    runners with different windows are driven, so a dropped `flat_max_words=` and one frozen at a
    constant both show up. R9: `flat_max_words=self.flat_max_words` could be deleted from the
    `fj.run` call and every test in this file still passed before this spy existed. (The native
    leg needs no spy: the same file freezes or pages purely by this value, which is what
    test_a_paged_image_rebuilds_every_run_and_caches_no_core turns into behaviour.)"""
    path = _hello_fjm(tmp_path)
    want = _reference(path)
    assert _run(FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)) == want

    monkeypatch.setattr(fastrun, "is_native_engine_active", lambda: False)

    class _SpyFj:
        """Stands in for the `flipjump` module, recording what FjmRunner asks `run` for.

        It DELEGATES rather than fakes, so the op count, the bytes and the silence below are all
        still the real engine's -- the spy only adds a record of the kwargs."""

        def __init__(self):
            self.calls = []

        def run(self, *args, **kwargs):
            self.calls.append(kwargs)
            return fj.run(*args, **kwargs)

    spy = _SpyFj()
    monkeypatch.setattr(fastrun, "fj", spy)

    runners = [FjmRunner(path, flat_max_words=TEST_FLAT_WORDS),
               FjmRunner(path, flat_max_words=TINY_FLAT_WORDS)]
    assert [r.native for r in runners] == [False, False]

    capsys.readouterr()                      # discard anything the native leg above may have said
    got = [_run(runner) for runner in runners for _ in range(2)]
    captured = capsys.readouterr()

    assert got == [want] * 4
    assert (captured.out, captured.err) == ("", ""), \
        "the fallback must not print into a gate's stdout"
    assert [call.get("flat_max_words") for call in spy.calls] == \
        [TEST_FLAT_WORDS, TEST_FLAT_WORDS, TINY_FLAT_WORDS, TINY_FLAT_WORDS], \
        "every fallback run must carry its own runner's flat window into fj.run"


# --------------------------------------------------------------------------- the coalescer

@native_only
def test_runs_reconstruct_the_reader_memory_exactly(tmp_path):
    """Expanding `_runs` back to {address: word} must equal `fjm_reader.Reader(path).memory`.

    This is the assertion that bites: a dropped tail run (the trailing `if start is not None`) or an
    off-by-one in `nxt` can still yield the right op count, because the core zero-fills whatever the
    segment covers. The zero-padded segment is here on purpose -- the Reader keeps those words in
    `zeros_boundaries`, never in `memory`, so they must come from `core.add_segment` instead."""
    path, _blocks = _multi_segment_fjm(tmp_path)
    runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)

    fresh = fjm_reader.Reader(path)
    assert fresh.zeros_boundaries, "fixture no longer exercises the zeros_boundaries case"
    assert fresh.memory, "fixture parsed to nothing, so the mirror below would be vacuous"

    rebuilt = {start + i: value
               for start, vals in runner._runs
               for i, value in enumerate(vals)}
    assert rebuilt == fresh.memory


@native_only
def test_runs_are_maximal_disjoint_and_ascending(tmp_path):
    """A coalescer that degenerates to one run per word produces byte-identical output at an
    identical op count, so ONLY the run SHAPE catches it -- and one-run-per-word is exactly the cost
    this class exists to remove (~6.36M set_words calls per frame on E1M1)."""
    path, blocks = _multi_segment_fjm(tmp_path)
    runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)

    assert [(start, len(vals)) for start, vals in runner._runs] == blocks
    for (start, vals), (next_start, _) in zip(runner._runs, runner._runs[1:]):
        assert start + len(vals) < next_start, "runs must be disjoint, ascending and maximal"


@native_only
def test_segments_mirror_the_reader_memory_segments(tmp_path):
    """`_segments` is (segment_start, segment_length) pairs in FILE order, one per segment -- the
    tuple shape tests/fj/test_m1_reset.py::run_clear feeds straight into `core.add_segment`. A
    dropped or reordered segment leaves the program garbage-reading mid-frame."""
    path, blocks = _multi_segment_fjm(tmp_path)
    runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)

    fresh = fjm_reader.Reader(path)
    assert runner._segments == [(s.segment_start, s.segment_length) for s in fresh.memory_segments]
    assert len(runner._segments) == len(blocks)
    assert _run(runner) == _reference(path), "the mirrored segments must still run the program"


# --------------------------------------------------------------------------- freeze / rebuild

@native_only
def test_a_paged_image_rebuilds_every_run_and_caches_no_core(tmp_path):
    """The `except RuntimeError: pass` branch -- what keeps FjmRunner correct for a paged image.
    The SAME file takes both branches purely by `flat_max_words`, which makes this a behavioural
    pin on that value reaching the engine.

    A refactor that moved `self._runs = []` out of the try, or cached a half-frozen core, would
    leave the rebuild path with an empty word list: a garbage program on every paged run."""
    data = _forge(32, self_modifying=True)
    path = _write_fjm(tmp_path / "paged.fjm", 32,
                      [(0, len(data), data), (FAR_WORD, 2, [0, 0])])
    want = _reference(path)

    paged = FjmRunner(path, flat_max_words=TINY_FLAT_WORDS)
    assert [_run(paged) for _ in range(2)] == [want, want]
    assert not hasattr(paged, "_core"), "a core that could not freeze must not be cached"
    assert paged._runs, "the rebuild path still needs the word runs"

    frozen = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
    assert [_run(frozen) for _ in range(2)] == [want, want]
    assert hasattr(frozen, "_core") and frozen._runs == [], \
        "a flat image must freeze, and the frozen image supersedes the python-int runs"


@native_only
def test_an_engine_without_freeze_still_runs_correctly(tmp_path):
    """The stated compatibility claim: "Older engines without freeze() fall back to the rebuild
    path, so this stays correct on a stock flipjump install." That is the `hasattr(core, "freeze")`
    guard -- a different branch from the paged case above, which reaches the rebuild path through
    the RuntimeError instead."""
    class _NoFreezeCore:
        """Forwards to a real core, except that it has no `freeze` attribute."""

        def __init__(self, real):
            object.__setattr__(self, "_real", real)

        def __getattr__(self, name):
            if name == "freeze":
                raise AttributeError(name)
            return getattr(object.__getattribute__(self, "_real"), name)

    class _NoFreezeEngine:
        def __init__(self, real):
            self._real = real

        def Memory(self, memory_width, flat_max_words=0):
            return _NoFreezeCore(self._real.Memory(memory_width, flat_max_words=flat_max_words))

    path = _hello_fjm(tmp_path, self_modifying=True, name="selfmod")
    want = _reference(path)
    runner = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)

    real_engine = fastrun._fjcore
    try:
        fastrun._fjcore = _NoFreezeEngine(real_engine)
        assert [_run(runner) for _ in range(2)] == [want, want]
    finally:
        fastrun._fjcore = real_engine
    assert not hasattr(runner, "_core")
    assert runner._runs, "without freeze() the runs are the only copy of the program"


def test_flat_max_words_defaults_to_the_render_ssot(tmp_path):
    """R6 SSOT: config.py's own comment records that `1 << 26` used to be copy-pasted into
    fastrun.py. A stale literal silently pages the 2^27-word game image -- byte-identical output,
    identical op counts, ~0.5 s/frame lost. (The behavioural half, that the stored value is the one
    the engine gets, is test_a_paged_image_rebuilds_every_run_and_caches_no_core.)

    Constructed only, never run: the default window is 2^27 words = a 1 GB flat image."""
    runner = FjmRunner(_hello_fjm(tmp_path))
    assert runner.flat_max_words == RENDER_FLAT_MAX_WORDS


# ----------------------------------------------------------------- construction-time obligations

def test_parsed_memory_dict_is_released_on_both_paths(tmp_path, monkeypatch):
    """THE named regression, CR-2026-08: the `self._mem.memory = {}` release used to sit inside the
    `if self.native:` block, so every fallback construction kept the parsed int->int dict (~350 MB
    on E1M1) alive for the session. Invisible in any output; fatal on the box rule 1 is about."""
    path = _hello_fjm(tmp_path)
    assert fjm_reader.Reader(path).memory, "the fixture must have words to leak in the first place"

    native = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
    assert native._mem.memory == {}

    monkeypatch.setattr(fastrun, "is_native_engine_active", lambda: False)
    fallback = FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
    assert fallback.native is False
    assert fallback._mem.memory == {}


@pytest.mark.parametrize("kind, expected", [("missing", FileNotFoundError),
                                            ("garbage", FlipJumpReadFjmException)])
def test_a_bad_fjm_path_fails_loudly_at_construction(tmp_path, kind, expected):
    """A gate pointed at a stale or absent build path must say so, not half-build a runner that
    raises a TypeError/AttributeError somewhere downstream."""
    if kind == "missing":
        path = tmp_path / "not-built-yet.fjm"
    else:
        path = tmp_path / "garbage.fjm"
        path.write_text("this is not an fjm")
    with pytest.raises(expected):
        FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)


def test_a_program_without_a_first_op_is_rejected_at_construction(tmp_path):
    """`assert_runnable` is called explicitly in __init__ (fj.run calls its own). Dropping it turns
    "this build has no entry op" into "run garbage from address 0" -- the failure mode the
    flipjump-side message was written for -- and turns it up at RUN time, not load time."""
    data = _forge(32)
    path = _write_fjm(tmp_path / "noentry.fjm", 32, [(4, len(data), data)])
    with pytest.raises(FlipJumpReadFjmException):
        FjmRunner(path, flat_max_words=TEST_FLAT_WORDS)
