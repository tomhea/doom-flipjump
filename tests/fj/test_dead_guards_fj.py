"""M7 P7 (doomfj.lootcode, P5's follow-up F3): THE DEAD PLAYER'S GUARDS on the real flipjump engine, record by record
in ONE image against the model's own code.

THE DOORS (`test_the_doors_*`): `doorcode.door_tic_lines(..., contact=, passes=, dead="p_dd0")` -- every E1M1 door, the
very text the emitter splices -- against `World._doors_phase`: each record stands the player in a door's use box or
on its contact edges, the door at rest, opening, open and waiting, or CLOSING at and around its pass step, use held
or not, the card owned or not, the player alive or DEAD (dead at the tic's start: p_dd0, and p_dead / p_health <= 0
in the model). A dead player presses no door and holds no closing door open (World._doors_phase's `alive`,
World.door_touched's `player_alive`). R9: the guards gone (dead=None).

THE USE LINES (`test_the_use_lines_*`): `lootcode.use_guard()` around `wall_renderer.exit_lines` with
`movercode.use_line_lines` (the SR lifts and the floor switch, on a press that misses the exit) -- against the model's
alive branch (`if use: if not p_usedown: p_usedown = 1; _use_lines` else p_usedown = 0) and its dead branch (nothing:
`_death_think` never touches p_usedown). R9: the guard gone.
"""
import random
import re

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import lootcode as L
from doomfj.doorcode import WAIT_NIBBLES, door_decls, door_tic_lines
from doomfj.doors import CLOSING, OPENING, door_stay, in_use_box_fixed, touches_door
from doomfj.movers import FLOOR_SWITCH_SPECIALS, LIFT_USE_SPECIALS, use_line_boxes
from doomfj.harness import W
from doomfj.world import KEYS, TicEvents, World

M32 = 0xFFFFFFFF


def _world():
    w = World(skill=gd.SK_HARD, monsters="idle", player="fire")
    for m in range(w.layout.nmon):                   # no monster touches a door here (the player's guard is the subject)
        w.ws.mon_active[m] = 0
    return w


def _run(tmp, name, text, feed, nrows):
    src = tmp / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode().split("\n")[:nrows]


# ---- the doors ------------------------------------------------------------------------------------------------------
N_DOORS = 600


def _door_records(w):
    rnd = random.Random(0x7D)
    out = []
    order = w.door_order
    for r in range(N_DOORS):
        d = rnd.randrange(len(order))
        si = order[d]
        n, p = w.door_nstates[si], w.door_pass[si]
        box = w.door_boxes.get(si)
        (x0, y0, x1, y1), lines = w._door_contact[si]
        if box is not None and rnd.random() < 0.5:
            bx0, by0, bx1, by1 = box
            pos = ((rnd.randint(bx0, bx1) << 16) + rnd.choice((0, 0x8000)), (rnd.randint(by0, by1) << 16))
        else:
            pos = ((rnd.randint(x0 - 20, x1 + 20) << 16) + rnd.choice((0, 1, 0xFFFF)),
                   (rnd.randint(y0 - 20, y1 + 20) << 16) + rnd.choice((0, 1)))
        kind = rnd.choice(("closing", "closing", "idle", "open", "opening"))
        if door_stay(w.door_kind[si]) and kind in ("closing", "open"):
            kind = "opening"                    # an open-stay door never closes nor waits: no such state is reached
        if kind == "closing":
            st = (rnd.choice((max(0, p - 1), p, p, min(n - 1, p + 1), n - 1)), CLOSING, 1, 0)
        elif kind == "idle":
            st = (0, 0, 0, 0)
        elif kind == "open":
            st = (n - 1, 0, 0, rnd.choice((1, 2, 50)))
        else:
            st = (rnd.randrange(n - 1), OPENING, rnd.choice((1, 2)), 0)    # (at the top it is idle already)
        out.append({"d": d, "st": st, "pos": pos, "use": rnd.random() < 0.7, "dead": int(rnd.random() < 0.5),
                    "card": rnd.choice((0, 1))})
    return out


def _door_expected(w, recs):
    ws = w.ws
    rows = []
    for rec in recs:
        for d in range(len(w.door_order)):
            ws.d_state[d] = ws.d_dir[d] = ws.d_sub[d] = ws.d_wait[d] = ws.d_monreq[d] = 0
        ws.d_state[rec["d"]], ws.d_dir[rec["d"]], ws.d_sub[rec["d"]], ws.d_wait[rec["d"]] = rec["st"]
        ws.px, ws.py = rec["pos"]
        ws.p_dead, ws.p_health = rec["dead"], 0 if rec["dead"] else 100
        ws.p_cards[gd.IT_BLUECARD] = rec["card"]
        keys = dict.fromkeys(KEYS, False)
        keys["use"] = rec["use"]
        w._doors_phase(keys, TicEvents(0))
        rows.append(" ".join("%x%x%x%02x" % (ws.d_state[d], ws.d_dir[d], ws.d_sub[d], ws.d_wait[d])
                             for d in range(len(w.door_order))))
    return rows


def _door_program(w, recs, dead="p_dd0"):
    order = w.door_order
    nd = len(order)
    assert nd <= 16
    tic = door_tic_lines(order, w.door_nstates, w.door_boxes, w.door_kind, contact=w._door_contact,
                         passes=w.door_pass, dead=dead)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 1, rbyte", "hex.mov 1, duse, rbyte", "hex.mov 1, p_dd0, rbyte + dw",   # use; the tic-start death
            "hex.input 1, rbyte", "hex.mov 1, pcard, rbyte",
            f"hex.zero {nd}, dstate", f"hex.zero {nd}, ddir", f"hex.zero {nd}, dsub",
            f"hex.zero {WAIT_NIBBLES * nd}, dwait", f"hex.zero {nd}, dreq",
            # the target door: its slot, then state | dir << 4, sub, wait
            "hex.input 1, rbyte", "hex.input 1, rbyte2", "hex.input 1, rbyte3", "hex.input 1, rbyte4"]
    for d in range(nd):
        body += [f"hex.if_flags rbyte, {1 << d:#06x}, dt{d}_n, dt{d}_y",
                 f"dt{d}_y:", f"hex.mov 1, dstate + {d}*dw, rbyte2", f"hex.mov 1, ddir + {d}*dw, rbyte2 + dw",
                 f"hex.mov 1, dsub + {d}*dw, rbyte3", f"hex.mov 2, dwait + {WAIT_NIBBLES * d}*dw, rbyte4",
                 ";dt_done", f"dt{d}_n:"]
    body += ["dt_done:"] + tic
    body += [x for d in range(nd) for x in (f"hex.print_as_digit 1, dstate + {d}*dw, 0",
                                            f"hex.print_as_digit 1, ddir + {d}*dw, 0",
                                            f"hex.print_as_digit 1, dsub + {d}*dw, 0",
                                            f"hex.print_as_digit 2, dwait + {WAIT_NIBBLES * d}*dw, 0",
                                            "stl.output 32" if d + 1 < nd else "stl.output 10")]
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2", "rbyte2: hex.vec 2",
             "rbyte3: hex.vec 2", "rbyte4: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8", "p_dd0: hex.vec 1",
             *door_decls(nd, max(1, len(w.walk_triggers)))]
    feed = b""
    for rec in recs:
        s, dr, sub, wt = rec["st"]
        feed += (bytes([1]) + (rec["pos"][0] & M32).to_bytes(4, "little") + (rec["pos"][1] & M32).to_bytes(4, "little")
                 + bytes([int(rec["use"]) | rec["dead"] << 4, rec["card"], rec["d"], s | dr << 4, sub, wt]))
    return "\n".join(body) + "\n", feed


def test_the_door_records_reach_their_paths():
    """a live player's press and his hold of a closing door, each refused when dead"""
    w = _world()
    recs = _door_records(w)
    seen = dict(press=0, press_dead=0, hold=0, hold_dead=0)
    for rec in recs:
        d = rec["d"]
        si = w.door_order[d]
        ws = w.ws
        ws.px, ws.py = rec["pos"]
        box = w.door_boxes.get(si)


        inbox = box is not None and in_use_box_fixed(box, *rec["pos"]) and rec["use"] and \
            (w.door_cards.get(si) is None or rec["card"]) and rec["st"][1] != OPENING
        touch = rec["st"][1] == CLOSING and rec["st"][0] >= w.door_pass[si] and \
            touches_door(w._door_contact[si], rec["pos"][0], rec["pos"][1], 16 << 16)
        key = ("press" if inbox else "hold" if touch else None)
        if key:
            seen[key + ("_dead" if rec["dead"] else "")] += 1
    assert all(v >= 10 for v in seen.values()), seen


def test_the_doors_follow_the_model(tmp_path):
    w = _world()
    recs = _door_records(w)
    text, feed = _door_program(w, recs)
    got = _run(tmp_path, "doors", text, feed, len(recs))
    want = _door_expected(_world(), recs)
    bad = next((k for k, (g, x) in enumerate(zip(got, want)) if g != x), None)
    assert len(got) == len(want) and bad is None, (bad, recs[bad] if bad is not None else None,
                                                   got[bad] if bad is not None else None,
                                                   want[bad] if bad is not None else None)


def test_the_door_guards_control_is_caught(tmp_path):
    w = _world()
    recs = _door_records(w)
    text, feed = _door_program(w, recs, dead=None)
    got = _run(tmp_path, "doors_mut", text, feed, len(recs))
    assert got != _door_expected(_world(), recs), "the doors without the dead guards went unnoticed"


# ---- the use lines --------------------------------------------------------------------------------------------------
N_USE = 500


def _use_boxes(w):

    v = w.cmap.vertexes
    return (w.exit_boxes, use_line_boxes(w.secs, w.lds, v, LIFT_USE_SPECIALS),
            [b for _t, b in use_line_boxes(w.secs, w.lds, v, FLOOR_SWITCH_SPECIALS)])


def _use_records(w):
    rnd = random.Random(0x7E)
    ex, sr, sw = _use_boxes(w)
    boxes = list(ex) + [b for _t, b in sr] + list(sw)
    out = []
    for r in range(N_USE):
        x0, y0, x1, y1 = rnd.choice(boxes)
        pos = ((rnd.randint(x0 - 8, x1 + 8) << 16) + rnd.choice((0, 0x8000)), rnd.randint(y0 - 8, y1 + 8) << 16)
        out.append({"pos": pos, "use": rnd.random() < 0.7, "usedn": rnd.choice((0, 0, 1)),
                    "dead": int(rnd.random() < 0.5), "fsw": rnd.choice((0, 0, 1))})
    return out


def _use_expected(w, recs):
    ws = w.ws
    rows = []
    for rec in recs:
        ws.px, ws.py = rec["pos"]
        ws.p_usedown, ws.g_leveldone, ws.f_switch = rec["usedn"], 0, rec["fsw"]
        for k in range(len(w.lift_order)):
            ws.l_req[k] = 0
        ws.p_dead, ws.p_health = rec["dead"], 0 if rec["dead"] else 100
        w._door_phase_scene()
        if not rec["dead"]:                               # combat._player_phase's alive branch, its use half
            if rec["use"]:
                if not ws.p_usedown:
                    ws.p_usedown = 1
                    w._use_lines(TicEvents(0))
            else:
                ws.p_usedown = 0
        rows.append("%x%x%x%s" % (ws.g_leveldone, ws.p_usedown, ws.f_switch,
                                  "".join("%x" % ws.l_req[k] for k in range(len(w.lift_order)))))
    return rows


def _use_program(w, recs, guard=True):
    from doomfj.movercode import use_line_lines
    from doomfj.wall_renderer import exit_lines
    ex, sr, sw = _use_boxes(w)
    nl = len(w.lift_order)
    pre, post = L.use_guard() if guard else ([], [])
    lines = pre + exit_lines(ex, use_line_lines(sr, sw, w.lift_of_tag)) + post
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rbyte",
            "hex.mov 1, duse, rbyte", "hex.mov 1, p_dd0, rbyte + dw",
            "hex.input 1, rbyte", "hex.mov 1, pusedn, rbyte", "hex.mov 1, fswitch, rbyte + dw",
            "hex.zero 1, lvdone", f"hex.zero {max(1, nl)}, lreq", *lines,
            "hex.print_as_digit 1, lvdone, 0", "hex.print_as_digit 1, pusedn, 0", "hex.print_as_digit 1, fswitch, 0",
            *[f"hex.print_as_digit 1, lreq + {k}*dw, 0" for k in range(nl)], "stl.output 10",
            ";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2", "viewx: hex.vec 8",
            "viewy: hex.vec 8", "p_dd0: hex.vec 1", "duse: hex.vec 1", "dbox: hex.vec 8", "pusedn: hex.vec 1",
            "lvdone: hex.vec 1", "mode: hex.vec 1", "menu_scr: hex.vec 1", f"lreq: hex.vec {max(1, nl)}",
            "fswitch: hex.vec 1"]
    feed = b""
    for rec in recs:
        feed += (bytes([1]) + (rec["pos"][0] & M32).to_bytes(4, "little") + (rec["pos"][1] & M32).to_bytes(4, "little")
                 + bytes([int(rec["use"]) | rec["dead"] << 4, rec["usedn"] | rec["fsw"] << 4]))
    return "\n".join(body) + "\n", feed


def test_the_use_records_reach_their_paths():
    """the exit, an SR lift and the switch pressed alive; the same presses dead; use released (usedown cleared)"""
    w = _world()
    recs = _use_records(w)
    rows = _use_expected(w, recs)
    alive = [(r, x) for r, x in zip(recs, rows) if not r["dead"]]
    assert sum(x[0] == "1" for _r, x in alive) >= 10
    assert sum(x[2] == "1" and not r["fsw"] for r, x in alive) >= 5
    assert sum("1" in x[3:] for _r, x in alive) >= 5
    assert sum(r["dead"] and r["use"] and not r["usedn"] for r in recs) >= 50


def test_the_use_lines_follow_the_model(tmp_path):
    w = _world()
    recs = _use_records(w)
    text, feed = _use_program(w, recs)
    got = _run(tmp_path, "uselines", text, feed, len(recs))
    want = _use_expected(_world(), recs)
    bad = next((k for k, (g, x) in enumerate(zip(got, want)) if g != x), None)
    assert len(got) == len(want) and bad is None, (bad, recs[bad] if bad is not None else None)


def test_the_use_guard_control_is_caught(tmp_path):
    w = _world()
    recs = _use_records(w)
    text, feed = _use_program(w, recs, guard=False)
    assert _run(tmp_path, "uselines_mut", text, feed, len(recs)) != _use_expected(_world(), recs)
