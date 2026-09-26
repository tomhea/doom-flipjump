"""The hot-site pads must fit the blocking pass's slot, or the shipped build silently un-blocks them.

HOT_PAD / HOTTER_PAD are the pads of the 91 hot `sparse_` sites in frame_render.fj. Under the
assembler's blocking pass a table's pad IS its slot width, and a slot wider than the build's
`--max-slot-ops` is `declined_too_wide`: the table stays inline and pays A ^ base on a pinned word.
At 1024 / 4096 that was all 988 of these tables, 945,807 ops/frame (handoff throughput-plan 15);
at 16 they block and blocked27 measured x1.085 (docs/ship-gate.md section 1). Nothing else notices a
regression: every byte-exact gate stays green, because a declined table computes the same pixels.

The limit is read from the RECORDED shipped build command (docs/ship-gate.md 1b), not restated here,
and poolmap.py's SHIP_GATE knobs are required to agree with it, so neither can drift alone.
"""
import re
from pathlib import Path

from doomfj.config import Config

ROOT = Path(__file__).resolve().parents[2]


def _shipped_max_slot_ops():
    text = (ROOT / "docs/ship-gate.md").read_text(encoding="utf-8")
    cmds = [line for line in text.splitlines()
            if line.startswith("python scratchpad/12m/build_labeled.py") and " game " in line]
    assert cmds, "docs/ship-gate.md 1b no longer records the build_labeled.py game command"
    limits = {int(m) for c in cmds for m in re.findall(r"--max-slot-ops (\d+)", c)}
    assert len(limits) == 1, f"the recorded build commands disagree on --max-slot-ops: {limits}"
    return limits.pop()


def test_poolmap_knobs_match_the_recorded_build_command():
    src = (ROOT / "scratchpad/12m/poolmap.py").read_text(encoding="utf-8")
    m = re.search(r"SHIP_GATE = dict\([^)]*max_slot_ops=(\d+)", src, re.S)
    assert m, "poolmap.py's SHIP_GATE no longer names max_slot_ops"
    assert int(m.group(1)) == _shipped_max_slot_ops()


def test_hot_pads_fit_the_shipped_slot_width():
    limit = _shipped_max_slot_ops()
    cfg = Config()
    too_wide = {name: pad for name, pad in (("HOT_PAD", cfg.HOT_PAD), ("HOTTER_PAD", cfg.HOTTER_PAD))
                if pad > limit}
    assert not too_wide, (f"{too_wide} exceed --max-slot-ops {limit}: under blocking these hot "
                          f"tables are declined_too_wide and run inline (handoff throughput-plan 15)")
