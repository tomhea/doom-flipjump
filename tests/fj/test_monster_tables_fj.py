"""M7 P3.0: the monster tables (doomfj.monstercode) assembled and run on the real flipjump engine -- every
entry looked up twice and printed, against the Python source each table is generated from. The R9 control: the
same run with ONE entry of the emitted table mutated must fail, so the comparison can see a wrong entry."""
import pytest

import flipjump as fj

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj

TABLES = {
    "mstate": (MC.state_table_values, 2, 6),
    "mturn": (MC.turn_table_values, 2, 1),
    "mopp": (MC.opposite_values, 1, 1),
    "mrnd": (MC.rnd_values, 2, 4),
}


def _run(tmp_path, name, label, values, idx_n, res_n, emitted_values=None) -> bool:
    body, data = [], []
    for k in range(len(values)):
        for _ in range(2):
            body += [f"{label}.lookup rdst, idx{k}", f"hex.print_as_digit {res_n}, rdst, 0", "stl.output 10"]
        data.append(f"idx{k}: hex.vec {idx_n}, {k}")
    data.append(f"rdst: hex.vec {res_n}")
    expected = "".join(f"{v:0{res_n}x}\n" * 2 for v in values).encode()
    table = generate_dispatch_table_fj(label, emitted_values if emitted_values is not None else values,
                                       index_nibbles=idx_n, result_nibbles=res_n)
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data + [table]) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    return fj.assemble_and_run_test_output([p.resolve()], b"", expected, memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


@pytest.mark.parametrize("label", sorted(TABLES))
def test_every_entry_equals_its_python_source(tmp_path, label):
    src, idx_n, res_n = TABLES[label]
    assert _run(tmp_path, label, label, src(), idx_n, res_n), f"{label}: fj lookups != the Python source"


def test_the_emitted_tables_are_the_ones_p30_emits():
    text = "\n".join(MC.p30_tables_fj())
    for label, (src, idx_n, res_n) in TABLES.items():
        assert generate_dispatch_table_fj(label, src(), index_nibbles=idx_n, result_nibbles=res_n) in text, label


def test_control_a_mutated_entry_is_caught(tmp_path):
    """R9: the zombieman's see state's tics off by one in the EMITTED table -- the run must fail"""
    src, idx_n, res_n = TABLES["mstate"]
    vals = src()
    k = gd.STATE_INDEX[gd.MOBJINFO["MT_POSSESSED"].seestate]
    bad = list(vals)
    bad[k] ^= 1 << 8
    assert not _run(tmp_path, "mstate_mut", "mstate", vals, idx_n, res_n, emitted_values=bad), (
        "a mutated mstate entry passed: the comparison is vacuous")
