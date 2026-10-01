from pathlib import Path
"""M7 P3.0: doomfj.monstercode's tables hold the model's rules -- each checked against the model's own source
(gamedata's states, world.turn_toward, gamedata.OPPOSITE, rng's outcome composition), with a mutation of the
packing caught."""
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import rng as R
from doomfj.world import turn_toward


def _unpack(v):
    return {name: (v >> (4 * nib)) & (16 ** w - 1) for name, nib, w in MC.STATE_FIELDS}


def test_every_monster_state_row_is_gamedata():
    vals = MC.state_table_values()
    groups = MC.view_groups()
    for s in MC.monster_states():
        st, row = gd.STATES[s], _unpack(vals[gd.STATE_INDEX[s]])
        assert gd.STATE_NAMES[row["next"]] == st.next, s
        assert row["tics"] == (15 if st.tics < 0 else st.tics), s
        act = MC.MON_ACTIONS[row["action"]]
        assert act == (None if st.action in MC.SOUND_ACTIONS else st.action), s
        assert groups[row["view"]] == (st.sprite, st.frame & gd.FF_FRAMEMASK), s


def test_non_monster_states_read_zero_and_the_counts():
    vals = MC.state_table_values()
    mon = {gd.STATE_INDEX[s] for s in MC.monster_states()}
    assert all(v == 0 for i, v in enumerate(vals) if i not in mon)
    assert len(mon) == 127 and len(MC.view_groups()) == 77
    # every finite tic count fits below the forever value, and no reachable state has 0 tics forever
    assert all(0 <= gd.STATES[s].tics < MC.TICS_FOREVER or gd.STATES[s].tics < 0 for s in MC.monster_states())


def test_every_monster_action_has_an_id():
    for s in MC.monster_states():
        a = gd.STATES[s].action
        assert a is None or a in MC.SOUND_ACTIONS or a in MC.MON_ACTIONS, (s, a)


def test_turn_and_opposite_are_the_models():
    t = MC.turn_table_values()
    for d in range(9):
        for f in range(8):
            assert t[(d << 4) | f] == (turn_toward(f, d) if d < 8 else f)
    assert MC.opposite_values() == list(gd.OPPOSITE)


def test_rnd_outcomes_are_the_call_sites():
    tbl = MC.rnd_values()
    for state in range(256):
        v, nxt = R.p_random(state)
        o, nxt2 = R.p_random_outcome(state, tbl)
        assert nxt == nxt2
        assert o & 0xFF == v and (o >> 8) & 1 == (v > 200) and (o >> 9) & 1 == (v & 1) and (o >> 12) == (v & 15)


def test_control_a_packing_mutation_is_caught(monkeypatch):
    """R9: tics packed one nibble off must fail the row check above"""
    monkeypatch.setattr(MC, "STATE_FIELDS", (("next", 0, 2), ("tics", 3, 1), ("action", 2, 1), ("view", 4, 2)))
    vals = MC.state_table_values()
    monkeypatch.undo()
    with pytest.raises(AssertionError):
        for s in MC.monster_states():
            st, row = gd.STATES[s], _unpack(vals[gd.STATE_INDEX[s]])
            assert row["tics"] == (15 if st.tics < 0 else st.tics), s
            assert MC.MON_ACTIONS[row["action"]] == (None if st.action in MC.SOUND_ACTIONS else st.action), s


def test_the_seen_flags_are_never_pinned():
    """M7 P3.2a: `thseen` is written through a POINTER (frame.rec_seen_mark), so `--pin-state-cells` must leave it
    canonical -- a pinned cell rests at its reader table's base, which a pointer access takes for the value (blocked42
    looped forever on it). The pin veto is selfreset.POINTER_READ_CELLS; the fj harnesses build without pinning, so
    only this list keeps the bug out of the shipped build."""
    from doomfj.selfreset import POINTER_READ_CELLS
    src = (Path(__file__).resolve().parents[2] / "src/fj/frame_render.fj").read_text(encoding="utf-8")
    assert "hex.write_hex sa" in src, "the mark no longer writes through `sa`: re-point this test"
    assert "thseen" in POINTER_READ_CELLS
