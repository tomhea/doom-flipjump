"""THE ONE-TIME CHECK of the one-pass reset (the owner, 2026-10-10): on the SAME source, the cells the new reset
restores and the values it restores them to must be EXACTLY the two-pass reset's.

    python scratchpad/onepass_check.py --gen <a two-pass build's generated dir> --labels <its label table>
                                       --tier game [--selftest]

The two-pass reset is the build's own `<map>_07_reset.fj` (numeric addresses, values read off pass 1's image).
Each of its cells is resolved to (label, cell offset) through the build's label table -- the label being the
nearest registered label at or below the address -- and its value read off the line. The one-pass reset is
`selfreset.emit_reset_part_by_label` run on a COPY of the same generated parts with the two-pass patch undone
(the frame tail back to `stl.loop`): its `plan` names (label, cell offset, value) directly. The two sets must be
equal. No assembly is needed: both sides are the same source's.

R9 (--selftest): the comparison must FAIL when one cell is dropped from the new plan, when one value is changed,
and when one byte cell is turned into a nibble cell.
"""
import argparse
import bisect
import gzip

import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import selfreset                                     # noqa: E402
from doomfj.harness import W                                     # noqa: E402

DW = 2 * W


def old_reset_cells(reset_fj: Path, labels: dict, names: set) -> dict:
    """{(label, cell): value or "byte"} of a two-pass reset part, resolved through `labels` (name -> bit
    address) onto the registered `names` -- the nearest registered label at or below each cell"""
    regs = sorted((labels[n], n) for n in names if n in labels)
    addrs = [a for a, _n in regs]

    def where(bit):
        i = bisect.bisect_right(addrs, bit) - 1
        assert i >= 0, "a reset cell below every registered label: %d" % bit
        base, name = regs[i]
        assert (bit - base) % DW == 0, "a reset cell off its label's cell grid: %d (%s + %d)" % (bit, name, bit - base)
        return name, (bit - base) // DW

    out = {}
    for line in reset_fj.read_text(encoding="utf-8").split("\n"):
        s = line.split("//")[0].strip()
        m = re.match(r"hex\.zero (\d+), (\d+)$", s)
        if m:
            n, a = int(m.group(1)), int(m.group(2))
            for k in range(n):
                out[where(a + k * DW)] = 0
            continue
        m = re.match(r"hex\.set 1, (\d+), (\d+)$", s)
        if m:
            out[where(int(m.group(1)))] = int(m.group(2))
            continue
        m = re.match(r"rep\((\d+), i\) m1\.zerobyte (\d+) \+ i\*dw$", s)
        if m:
            n, a = int(m.group(1)), int(m.group(2))
            for k in range(n):
                out[where(a + k * DW)] = "byte"
            continue
        assert not s or s.endswith(":") or s == ";__hot_end", "an unread reset line: %r" % line
    return out


def new_reset_cells(plan) -> dict:
    out = {}
    for name, cell, value in plan:
        assert (name, cell) not in out, "the new plan restores %s + %d twice" % (name, cell)
        out[(name, cell)] = value
    return out


def compare(old: dict, new: dict):
    """(ok, report lines)"""
    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))
    diff = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    rep = ["cells: two-pass %d, one-pass %d; only two-pass %d, only one-pass %d, value differs %d"
           % (len(old), len(new), len(only_old), len(only_new), len(diff))]
    rep += ["  only two-pass: %s = %r" % (k, old[k]) for k in only_old[:8]]
    rep += ["  only one-pass: %s = %r" % (k, new[k]) for k in only_new[:8]]
    rep += ["  value differs: %s two-pass %r one-pass %r" % (k, old[k], new[k]) for k in diff[:8]]
    return not (only_old or only_new or diff), rep


def run(gen: Path, labels_path: Path, tier: str):
    from doomfj.build import DEFAULT_RESTORE_SET, STANDALONE_RESTORE_SET, persist_labels
    from doomfj.config import Config
    from doomfj.wad import WadFile
    from doomfj.mapcompiler import bake_bsp
    from doomfj.wall_renderer import tier_cfg, tier_flags
    t = tier_flags(tier)
    set_path = STANDALONE_RESTORE_SET if t["standalone"] else DEFAULT_RESTORE_SET
    cfg = tier_cfg(Config(), tier)
    names = selfreset.registered_reset_names(set_path, cfg, t["standalone"])      # THE BUILD'S OWN REGISTRY
    persist = persist_labels(standalone=t["standalone"], doors=t["doors"], moving_things=t["moving_things"])
    labels = {}
    for line in gzip.open(labels_path, "rt", encoding="utf-8"):
        a, tab, v = line.rstrip("\n").partition("\t")
        if tab:
            labels.setdefault(a, int(v))
    nss = len(bake_bsp(WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad")), "E1M1").subsectors)
    old = old_reset_cells(gen / "e1m1_07_reset.fj", labels, names - set(persist))
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for f in gen.glob("e1m1_0[0-6]_*.fj"):
            shutil.copy(f, td / f.name)
        main = td / "e1m1_02_main.fj"
        txt = main.read_text(encoding="utf-8").split("\n")
        k = [i for i, s in enumerate(txt) if s.strip() == ";m1_reset"]
        assert len(k) == 1, "the two-pass main holds %d `;m1_reset` (the patched frame tail)" % len(k)
        txt[k[0]] = "stl.loop"                                  # undo the two-pass patch
        main.write_text("\n".join(txt), encoding="utf-8")
        files = sorted(td.glob("e1m1_0[0-6]_*.fj"))
        _part, n_nib, n_byte, plan = selfreset.emit_reset_part_by_label(
            td, files, names, cfg.VIEW_W, nss, "e1m1", persist=persist)
    return old, new_reset_cells(plan), (n_nib, n_byte, len(names), len(persist))


def selftest(old, new) -> bool:
    ok = compare(old, new)[0]
    print("baseline equal: %s" % ok)
    k0 = sorted(new)[len(new) // 2]
    m = dict(new)
    del m[k0]
    c1 = not compare(old, m)[0]
    print("C1 a cell dropped from the one-pass plan is caught: %s" % c1)
    k1 = next(k for k in sorted(new) if isinstance(new[k], int))
    m = dict(new)
    m[k1] = (new[k1] + 1) % 16
    c2 = not compare(old, m)[0]
    print("C2 a value changed is caught: %s" % c2)
    c3 = True
    k2 = next((k for k in sorted(new) if new[k] == "byte"), None)
    if k2 is not None:
        m = dict(new)
        m[k2] = 0
        c3 = not compare(old, m)[0]
        print("C3 a byte cell turned into a nibble cell is caught: %s" % c3)
    return ok and c1 and c2 and c3


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True, help="a TWO-PASS build's generated dir (its reset part included)")
    ap.add_argument("--labels", required=True, help="that build's label table (.tsv.gz)")
    ap.add_argument("--tier", default="game")
    ap.add_argument("--selftest", action="store_true", help="the R9 controls on the same data")
    a = ap.parse_args()
    old, new, info = run(Path(a.gen), Path(a.labels), a.tier)
    print("one-pass reset: %d nibble cells, %d byte cells; %d registered labels, %d persisted" % info)
    ok, rep = compare(old, new)
    print("\n".join(rep))
    if a.selftest:
        ok = selftest(old, new) and ok
    print("ONE-TIME CHECK %s" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)
