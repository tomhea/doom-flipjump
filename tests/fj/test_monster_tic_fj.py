"""M7 P3.1: the monster tic (monstercode.mon_tic_lines) run on the real flipjump engine for N frames against the
model's own monster phase in idle mode (doomfj.monsters.MonsterPhase) -- every slot's state and tics after every
frame. The start is the model's hard level start with pokes: mid-cycle tics, a corpse (tics forever), an inactive
slot. R9: the same run with one mstate entry mutated must fail."""
import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.monsters import MonsterPhase

FRAMES = 36


def _start():
    ph = MonsterPhase(mode="idle")
    ws, n = ph.world.ws, ph.world.layout.nmon
    act = [k for k in range(n) if ws.mon_active[k]]
    ws.mon_tics[act[0]] = 1                                         # steps on the first frame
    ws.mon_tics[act[1]] = 7                                         # mid-cycle
    info = ph.world.mon_info[act[2]]
    corpse = gd.STATES[info.deathstate]
    while corpse.tics >= 0:                                          # walk the death chain to its forever state
        corpse = gd.STATES[corpse.next]
    ws.mon_state[act[2]] = gd.STATE_INDEX[corpse.name]
    ws.mon_tics[act[2]] = 15
    ws.mon_active[act[3]] = 0                                        # not spawned: never touched
    return ph


@pytest.fixture(scope="module")
def start():
    return _start()


def _expected(ph) -> bytes:
    ws, n = ph.world.ws, ph.world.layout.nmon
    out = []
    for _ in range(FRAMES):
        ph.tic()
        out += ["%02x%x" % (ws.mon_state[m], ws.mon_tics[m]) for m in range(n)]
        out.append("\n")
    return "".join(out).encode()


def _program(ph, values, table_values) -> str:
    ws, n, schema = ph.world.ws, ph.world.layout.nmon, ph.world.schema
    init = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS}
    body = ["stl.startup_and_init_all", "hex.set 2, frames, %d" % FRAMES, "loop:"]
    body += MC.mon_tic_lines(schema, n)
    for m in range(n):
        body += ["hex.print_as_digit 2, mon_state + %d*dw, 0" % (2 * m),
                 "hex.print_as_digit 1, mon_tics + %d*dw, 0" % m]
    body += ["stl.output 10", "hex.dec 2, frames", "hex.if0 2, frames, end", ";loop", "end:", "stl.loop"]
    data = ["frames: hex.vec 2"] + MC.monster_decls(schema, n, init) + MC.MT_DECLS
    data.append(generate_dispatch_table_fj("mstate", table_values, index_nibbles=2, result_nibbles=6))
    return "\n".join(body + data) + "\n"


def _run(tmp_path, name, prog, expected) -> bool:
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    return fj.assemble_and_run_test_output([p.resolve()], b"", expected, memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_tic_follows_the_model(tmp_path, start):
    prog = _program(start, None, MC.state_table_values())
    assert _run(tmp_path, "mtic", prog, _expected(_start())), "the fj tic parted from the model's idle phase"


def test_control_a_mutated_state_row_is_caught(tmp_path, start):
    vals = MC.state_table_values()
    k = gd.STATE_INDEX[gd.MOBJINFO["MT_TROOP"].spawnstate]
    vals[k] ^= 1 << 8                                   # the imp's first stand state: tics off by one
    assert not _run(tmp_path, "mtic_mut", _program(start, None, vals), _expected(_start())), (
        "a mutated tics entry passed: the comparison is vacuous")
