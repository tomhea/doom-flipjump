"""THE TRIPWIRE THE FLAG RETIREMENT NEEDED: no undefined names in the emitter package.

Deleting a dead branch can take a live name with it, and this repo's fast tests cannot see that:
nothing in `tests/host` calls `emit_wall_renderer`, and running it is ~10 MINUTES even on a
three-sector fixture (the texture/colormap banks scale with the ASSET wad, not the map). During the
flag retirement two edits did exactly this --

  * removing `_stream_mode_decls` swallowed three module constants that followed it
    (LINES_HALF_SLOTS, STEP_SLOT_STRIDE, STEP_COL_STRIDE), and
  * removing the framebuffer plane pass swallowed `plane_pass = []`, which sat between the two
    deleted blocks

-- and BOTH survived a full green `tests/host` run, to be found minutes later by a 10-minute
emission. An undefined name is a static fact; it should cost milliseconds to find, not minutes.

⚠ THIS IS A TRIPWIRE, NOT A PROOF. It says the module can run, never that it emits the right text.
The byte-for-byte guarantee is `scratchpad/cr/emit_baseline.py --check` against the frozen shipped
hashes. Never read a green run here as "the refactor was safe".
"""
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path("src/doomfj")
# `undefined name` is the one that breaks a build; the rest of pyflakes' output (unused imports,
# f-strings without placeholders) is style and is deliberately NOT failed on here.
FATAL = ("undefined name",)


@pytest.fixture(scope="module")
def report():
    try:
        import pyflakes  # noqa: F401
    except ImportError:                                   # pragma: no cover
        pytest.skip("pyflakes not installed")
    r = subprocess.run([sys.executable, "-m", "pyflakes", *sorted(str(p) for p in SRC.glob("*.py"))],
                       capture_output=True, text=True)
    return r.stdout.splitlines()


def test_no_undefined_names_anywhere_in_the_package(report):
    bad = [l for l in report if any(f in l.lower() for f in FATAL)]
    assert not bad, "undefined name(s) -- a deleted branch took a live name with it:\n" + \
                    "\n".join(bad)


def test_the_checker_actually_reports_undefined_names(tmp_path):
    """THE NEGATIVE CONTROL. A checker that silently stopped running (a renamed module, a changed
    output format, an exit code nobody reads) would leave this test green forever -- which is the
    exact shape of failure the tools in this repo are supposed to guard against."""
    pytest.importorskip("pyflakes")
    probe = tmp_path / "probe.py"
    probe.write_text("def f():\n    return a_name_that_does_not_exist\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(probe)],
                       capture_output=True, text=True)
    assert "undefined name" in r.stdout.lower(), r.stdout + r.stderr
