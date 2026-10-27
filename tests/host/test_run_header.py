"""The game binary carries how `fj --run` runs it: the pc window and flat memory (flipjump's .fjm
run_flags / io_mode, 1.5.1 at 342a3b9). The play command is then just `fj --run build/<name>.fjm`."""
from pathlib import Path

from flipjump.fjm.fjm_consts import IO_MODE_PC, IO_MODE_STANDARD, RUN_FLAG_FLAT_MEMORY, FJMVersion
from flipjump.fjm.fjm_reader import read_fjm_header

from doomfj import build, selfreset


def test_a_standalone_binary_runs_in_the_pc_window_in_flat_memory():
    assert build.standalone_run_header(True) == {"run_flags": RUN_FLAG_FLAT_MEMORY, "io_mode": IO_MODE_PC}


def test_a_hosted_binary_keeps_the_defaults():
    assert build.standalone_run_header(False) == {"run_flags": 0, "io_mode": IO_MODE_STANDARD}


def test_capture_labels_writes_the_header(tmp_path):
    src = tmp_path / "loop.fj"
    src.write_text("loop: ;loop\n", encoding="utf-8")
    out = tmp_path / "loop.fjm"
    labels = selfreset.capture_labels([src], out, **build.standalone_run_header(True))
    header = read_fjm_header(out)
    assert (header.run_flags, header.io_mode) == (RUN_FLAG_FLAT_MEMORY, IO_MODE_PC)
    # A11: flipjump 1.6.0 writes .fjm version 4 (the segment table compressed too), and the header still reads
    assert header.version == FJMVersion.CompressedSegmentsVersion and header.span_words > 0, header
    assert any(name.endswith("loop") for name in labels)
    selfreset.capture_labels([src], out)  # the defaults
    header = read_fjm_header(out)
    assert (header.run_flags, header.io_mode) == (0, IO_MODE_STANDARD)
