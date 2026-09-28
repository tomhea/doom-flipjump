"""M7 P1.5 -- the restore-set re-key and a label whose span changed (scratchpad/ca_remap_set.py).

P1.5 took the multiplayer-only things out of the image, and the runtime things' arrays
(`thpos_rt`, `thss_rt`) shrank from 75 things to 68; the re-key refused its own output, since the
old offsets ran past the new end. It now reads the table the set was keyed on and holds an array
the set held WHOLE whole at its new span -- shrunk, or grown, where the new words would otherwise
be a hole that hangs the next frame -- and refuses a label held in part whose span changed.

The script's --selftest carries the cases and the negative controls; it runs in a subprocess
because the script puts src/ on sys.path.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_re_key_holds_whole_arrays_whole_and_refuses_the_rest():
    r = subprocess.run([sys.executable, str(ROOT / "scratchpad" / "ca_remap_set.py"), "--selftest"],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    for case in ("C1", "C2", "C3", "C4", "C5", "C6"):
        assert "PASS  %s " % case in r.stdout, "%s did not pass:\n%s" % (case, r.stdout)
