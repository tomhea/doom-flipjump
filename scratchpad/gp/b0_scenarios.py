"""b0_scenarios.py -- B0 of the combat scenario set (v2): blocked27 in TIC mode from each checkpoint.

    python scratchpad/gp/b0_scenarios.py [--file scratchpad/gp/scenarios/combat_scenarios_v2.json]
                                         [--pixel-every N] [--json OUT] [--proxy]
    python scratchpad/gp/b0_scenarios.py --selftest

WHAT IT RUNS. For each run of the set: the menu's 2 frames and enter, exactly as gamespeed composes
them, then the run's 100 game frames. The run is first REPLAYED on the model (scenarios_v2), which
must reproduce the file's frozen poses; that gives every frame's model pose before and after the
tic and the model's doors before it. At every game frame's start the probe (probe.py) writes:
  * THE POSE FROM WHICH blocked27's OWN TIC LANDS WHERE THE MODEL DID (`scenarios_v2.b0_injection`):
    the pre-tic angle, and the model's landing minus blocked27's forward/back step (the landing
    itself when the frame has no forward/back key). With no strafe and nothing in the way this is
    the model's pre-tic pose (v1's injection); it also absorbs strafe (blocked27 has none) and a
    step a solid thing refused (blocked27 walks through things);
  * THE MODEL'S DOORS before the tic, all four cells per door (state, dir, sub, wait): a door a
    monster opened in the model opens in blocked27 one frame later instead of never.
The frame's forward/back/turn/use keys arrive as real key events. Strafe, fire and the weapon keys
are not delivered: blocked27 reads none of them (its input discards other keycodes).

WHAT IT CHECKS, every frame. The expectation is `scenarios_v2.BinaryMirror` stepping the injected
pose and doors with the delivered keys (blocked27's rules: no strafe, no things, no key checks).
The binary's pose and door states at every present must equal it (state-exact) and its picture
must equal the game oracle's render of it (byte-exact on every --pixel-every'th frame and on every
frame the expectation parts from the model). A frame whose expectation parts from the model
(camera: the model's pose; doors: the model's door states) is COUNTED.

STRAFE. On a STRAFE-ONLY frame (strafe, no forward/back) blocked27 runs no collision tic: it does
not move. The frame is drawn from the model's landing, but the collision the gameplay binary will
run there is missing -- B0 UNDERCOUNTS those frames. `--proxy` measures the size: a second pass
gives every strafe-only frame a FORWARD step into the same landing (so blocked27 runs its collision
tic and lands on the same pose, drawing the same picture) and reports the exact difference.
  M7 P6+P7: the step is not neutral any more. It TOUCHES what lies at the landing (the normal run's strafe-only frame
does not move, so it takes nothing there: v6's aftermath takes a health bonus on frame 28, the barrel hall a dropped
shotgun on frame 48 -- the arms digit stays lit), and a wall, a step or a solid thing can REFUSE it (v6's spectre
corridor, frame 0: one step behind the landing is inside a wall, 128 units below -- try_move refuses all three
candidates and the frame is drawn from there). So a proxy run is judged against its OWN oracle, like the normal run
(`judge`), "picture identical to the normal run" is a recorded note with its cause (`proxy_note`), and every refused
step is listed: on those frames the delta is not the collision tic at the landing.

SETUP. A run's setup beyond the pose (v6: the aftermath's three corpses and two lying clips, `setup.corpses`) is
applied to the mirror with the set's own `inject_corpse` and POKED into the binary at the first game frame --
hurt_gate's frame-0 mechanism (`setup_cells`) plus the leaf lists that link the lying drops; the binary's own values
of those cells are read back first and must be the level start's. `--oracle-only` steps each such run once more
without its setup: it must part from the set (the R9 control).

WHAT B0 MEASURES: blocked27's cost of drawing the set's camera path frame by frame, with its own
door tic, player tic and collision (not on strafe-only frames), in ITS world: monsters at their
spawns in their spawn frames, every pickup present, no fireballs, corpses or effects. Per run,
(total - startup - menu) / 100 exactly; the binding statistic is gamespeed's (mean + p80) / 2 over
the runs; the per-frame maximum is the largest probe reading (+/- 2^18, probe.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import probe as P                                                            # noqa: E402
import scenarios_v2 as S                                                     # noqa: E402
from doomfj.monsters import loot_cells                                       # noqa: E402  (M7 P6)
from doomfj.world import player_loots                                        # noqa: E402  (M7 P6)

ROOT = P.ROOT
M32 = 0xFFFFFFFF
DRIVER = "scratchpad/gp/b0_scenarios.py"


class GameOracle(P.Oracle):
    """probe.Oracle with the GAME tier's picture keywords: `sky` (V2) and the `bbox_cull` wedge cull
    are retired into the default build, so the oracle draws them too -- deg_gate's set. MEASURED
    2026-09-26 (S4 v1): without `sky` the oracle differs from blocked27 on every frame that shows
    sky; probe.Oracle has had `sky` since a07e8b9, and `bbox_cull` moves no pixel."""
    RENDER_KW = dict(P.Oracle.RENDER_KW)       # = reference_model.GAME_RENDER_KW (PR #87)


def P_signed(v: int) -> int:
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def sha16(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def model_frames(run: dict, proxy: bool = False) -> list:
    """replay one run on the model; per frame: the injection, the delivered keys, the doors written,
    the expectation (the mirror), and the model's own landing and doors. The replay must reproduce
    the file's poses (the set's freeze)."""
    w = S.start_world(run["setup"])
    mirror = S.BinaryMirror(w)
    out = []
    for i, s in enumerate(run["keys"]):
        kd = S.str_to_keys(s)
        ws = w.ws
        pre = (ws.px, ws.py, ws.pangle)
        pre_doors = S.door_tuples(w)
        pre_movers = S.mover_state(w)                  # M7 P2b
        # M7 P5 (F2): the player's health, armor and armor type BEFORE the tic -- injected like the pose, so the
        # binary's bar and its monsters' damage start each frame from the frozen model's player
        pre_hurt = (ws.p_health, ws.p_armor, ws.p_armortype)
        assert ws.p_health > 0 and not ws.p_dead, "%s frame %d: the frozen model's player is dead" % (run["name"], i)
        w.tic(kd)
        post = (ws.px, ws.py, ws.pangle)
        if list(post) != list(run["poses"][i]):
            raise AssertionError("%s frame %d: the model no longer reproduces the set's pose (%s vs "
                                 "%s) -- the model or the file changed" % (run["name"], i, post,
                                                                           run["poses"][i]))
        inj, bkeys = S.b0_injection(w.rm, pre, post, kd, proxy=proxy)
        # M7 P4.2a: the TRIGGER is delivered too -- fire and the number keys -- so the binary shoots where the set's
        # player shoots, through its own picture's window, and every hit, pain and death is checked against the
        # mirror's (the injected pose carries the model's strafe; the weapon moves no pose)
        bkeys = dict(bkeys, **{k: True for k in ("fire", "w1", "w2", "w3", "w4") if kd.get(k)})
        out.append({"inj": inj, "keys": bkeys, "doors": pre_doors, "movers": pre_movers,
                    "exp": mirror.step(inj, bkeys, pre_doors, pre_movers), "post": post,
                    # M7 P2b: the movers' heights the binary draws this frame (the mirror's, after
                    # its move -- p2a_gate's rule); without them a lift in view parts the picture
                    "mheights": mirror.mp.heights(mirror.mstate),
                    "post_doors": tuple(ws.d_state),
                    "strafe_only": S.has_strafe(kd) and not (kd.get("forward") or kd.get("back")),
                    # M7 P3.2b: drive re-steps the mirror with the monsters from the run's setup -- on EVERY
                    # frame, since a caller may hand drive a slice that starts mid-run (the selftest's T5)
                    "run_setup": run["setup"], "hurt": pre_hurt,
                    "post_loot": loot_cells(w)})             # M7 P6: the frozen model's loot after the tic
    return out


# the frame keys `drive` reads by subscript (the others -- movers, mheights, post_doors, strafe_only -- by .get)
DRIVE_READS = ("inj", "keys", "doors", "exp", "post", "run_setup")


def missing_drive_keys(frames: list) -> list:
    """[(frame index, key)] of every DRIVE_READS key a frame lacks"""
    return [(i, k) for i, fr in enumerate(frames) for k in DRIVE_READS if k not in fr]


def doorsim_frames(keys: list, mirror) -> list:
    """gamespeed's recorded tic run as b0 frames (the selftest's T1): onewalk.DoorSim's pre-tic pose and doors
    injected, its keys delivered, `mirror` (a scenarios_v2.BinaryMirror) the expectation. DoorSim has no movers
    (`movers` None: the mirror keeps its own, its heights ride as `mheights`) and starts in the new
    world at its own start pose (`run_setup`)."""
    import onewalk
    dsim = onewalk.DoorSim()
    st = dsim.reset()
    setup = {"pose": (st.x, st.y, st.angle)}
    frames = []
    for kd in keys:
        pre = (st.x, st.y, st.angle)
        pre_doors = [tuple(dsim.ds[si]) for si in dsim.order]
        st = dsim.step(st, kd)
        bk = S.b0_keys(kd)
        exp = mirror.step(pre, bk, pre_doors)
        # M7 P2b: the route rides a lift (frames 31-73): the picture needs the mirror's mover heights
        frames.append({"inj": pre, "keys": bk, "doors": pre_doors, "movers": None, "exp": exp,
                       "post": (st.x, st.y, st.angle), "post_doors": tuple(dsim.ds[si][0] for si in dsim.order),
                       "mheights": mirror.mp.heights(mirror.mstate), "run_setup": setup})
    return frames


class _NoBinary:
    """M7 P6: `drive`'s stand-in for a binary run (`--oracle-only`): nothing presented, nothing measured"""
    frames, palettes, ops, seconds = [], [], 0, 0.0


def setup_fn(run_setup: dict):
    """M7 P6+P7 (v6's R0-aftermath): the part of a run's SETUP that is not the pose -- the set's CORPSES
    (`setup.corpses`: slot, type, map position, corpse state, drop) -- as a function of a monsters.MonsterPhase, or
    None when the setup has none. It is `scenarios_v2.inject_corpse`, the definition the set's own replay
    (`start_world`) runs, applied to the phase's world; the set's recorded type and corpse state are checked
    against the slot first. The pose is not here: b0 injects the pose every frame. A setup field b0 does not know
    is refused, so a new kind of setup cannot be dropped silently."""
    extra = sorted(set(run_setup) - {"pose", "corpses"})
    assert not extra, "a setup field b0 does not inject: %s" % extra
    corpses = list(run_setup.get("corpses") or ())
    if not corpses:
        return None

    def fn(ph):
        w = ph.world
        for c in corpses:
            assert w.mon_things[c["slot"]].type == c["type"], c
            assert S.corpse_state(w, c["slot"]) == c["state"], c
            S.inject_corpse(w, c["slot"], c["x"], c["y"], c["drop"] is not None)
    return fn


def setup_poke(orc, run_setup: dict, pmode=None):
    """(before, poke): the cells the run's setup moves from the level start -- hurt_gate's frame-0 poke
    (`setup_cells`, the ONE mechanism the gates use) with the leaf lists (a lying drop is linked in its corpse's
    leaf, as drop_link<k> links it) -- and their level-start values, which b0 reads back from the binary before it
    writes. ({}, {}) for a setup without corpses."""
    fn = setup_fn(run_setup)
    if fn is None:
        return {}, {}
    from types import SimpleNamespace
    import hurt_gate as H
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
    ca, cb = H.setup_cells(SimpleNamespace(orc=orc, dsim=orc), fn, mmode=MONSTER_MODE, pmode=pmode or PLAYER_MODE,
                           lists=True)
    poke = {k: v for k, v in cb.items() if ca.get(k) != v}
    return {k: ca[k] for k in poke}, poke


def setup_cell_specs(orc) -> dict:
    """the probe cells a setup poke may name, beyond b0's own: the monsters, the runtime-thing rows, `thvis` and the
    leaf lists (one byte per leaf / per row: the write_byte arrays sshead / thnext)"""
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE
    cells = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis)
    ph = MonsterPhase(orc.mw, orc.mapname, BOOT_SKILL, rm=orc.rm, mode=MONSTER_MODE, player=orc.player_mode)
    cells["sshead"] = P.Cell("sshead", "byte", count=len(orc._mv(ph.world).cmap.subsectors))
    cells["thnext"] = P.Cell("thnext", "byte", count=orc.nrt)
    return cells


def drive(gb, table, orc, frames: list, *, pixel_every: int = 5, override=None, pmode=None,
          inject_setup: bool = True) -> dict:
    """one run through the binary: inject and deliver per `frames`; check against the expectation
    (`override`: a list of (pose, doors) to check against instead).
    M7 P6: `gb` None (`--oracle-only`) steps the expectation alone -- the mirror, its monsters, its pictures for
    the seen flags -- and reports its partings (camera, doors, loot) and deaths; `pmode` the player mode (default
    wall_renderer's).
    M7 P6+P7: the run's SETUP beyond the pose (`setup_fn`: v6's aftermath corpses) is applied to the mirror's
    monsters and POKED into the binary at the first game frame's start (`setup_poke`), after the binary's own
    values of those cells are read back and checked against the level start's (`setup_pre`: the names that
    differed -- a non-empty list FAILS the run). `inject_setup` False drops the setup on both sides (the R9
    control: the aftermath then parts from the set)."""
    gaps = missing_drive_keys(frames)
    assert not gaps, "drive reads keys these frames lack, e.g. %s" % gaps[:4]
    import gamespeed as GS
    import m2_std_gate as gate
    mf = gate.MENU_FRAMES
    sfn = setup_fn(frames[0]["run_setup"]) if inject_setup and frames else None
    before, poke = setup_poke(orc, frames[0]["run_setup"], pmode) if sfn is not None and gb is not None else ({}, {})
    cells = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift)
    if poke:
        cells = {**cells, **{k: c for k, c in setup_cell_specs(orc).items() if k in poke}}
    p = P.Probe(cells, table, gb.width) if gb is not None else None
    if p is not None:
        missing = sorted(k for k in poke if k not in p.cells)
        assert not missing, "the setup moves cells the probe cannot write: %s" % missing
    setup_pre = []
    per_frame = [{} for _ in range(mf)] + [fr["keys"] for fr in frames]
    events = GS.events_for(per_frame)
    readback = {}

    def start(pr, f):
        if f < mf:
            return
        fr = frames[f - mf]
        vals = {"viewx": fr["inj"][0], "viewy": fr["inj"][1], "viewangle": fr["inj"][2]}
        if fr["doors"] is not None:
            d = fr["doors"]
            vals.update({"dstate": tuple(t[0] for t in d), "ddir": tuple(t[1] for t in d),
                         "dsub": tuple(t[2] for t in d), "dwait": tuple(t[3] for t in d)})
        if fr.get("movers") is not None:               # M7 P2b: the model's movers, likewise
            lifts, req, sw = fr["movers"]
            vals.update({"lstate": tuple(t[0] for t in lifts), "ldir": tuple(t[1] for t in lifts),
                         "lsub": tuple(t[2] for t in lifts), "lwait": tuple(t[3] for t in lifts),
                         "lreq": tuple(int(si in req) for si in orc.lift_order), "fswitch": sw})
        if inject_hurt and fr.get("hurt") is not None:   # M7 P5: the frozen model's pre-tic health / armor
            hp, ar, at = fr["hurt"]
            vals.update({"p_hp": hp & 0xFFF, "p_ar": ar, "p_at": at})
        if f == mf and poke:                            # M7 P6+P7: the setup, once, at the first game frame
            got = pr.read_cells(sorted(poke))
            setup_pre.extend(k for k in sorted(poke) if got[k] != before[k])
            vals.update(poke)
        pr.write_cells(vals)

    def present(pr, f):
        if f >= mf:
            readback[f - mf] = pr.read_cells(["viewx", "viewy", "viewangle", "dstate", "mode"])
    # M7 P5: a binary with hurtcode's cells takes the frozen model's player each frame (`hurt`); one without them
    # (a binary before P5: the probe dropped the optional group) is not injected, and neither is its mirror
    inject_hurt = p is None or "p_hp" in p.cells
    if gb is not None:
        p.on_frame_start(start)
        p.on_present(present)
        r = gb.run(len(per_frame), events, p, pre_run=lambda pr: pr.verify_known(orc.known_pristine()))
        ops_f = p.frame_ops()[mf:mf + len(frames)]
    else:
        r, ops_f = _NoBinary(), []
    state_ok, pix_ok, pix_frames = [], [], []
    # M7 P5: the menu frames' palettes (PLAYPAL 0), then one per game frame (below); the frames whose mirror died
    pal_ok = [i < len(r.palettes) and r.palettes[i] == orc.palette_sha(0) for i in range(mf)]
    dead = []
    cam = door = 0
    cam_frames, trace = [], []  # M7 P6+P7: the frames whose pose parts from the model; per frame what was expected
    refusers = {}               # M7 P6+P7: frame -> what refused the move there (chase mirrors)
    loot_part = 0               # M7 P6: frames whose loot cells differ from the frozen model's (recorded, not judged)
    # M7 P3.1: the binary's monsters live IDLE from its boot image (the model's own phase, a tic per
    # world frame after the player); B0 injects the player, doors and movers, not them, so the
    # picture it expects is the static set's world with those monsters' views (docs/gp-monsters.md 5)
    mph = None
    if table is None or "mon_state" in table.addrs:
        from doomfj.monsters import MonsterPhase
        from doomfj.wall_renderer import BOOT_SKILL
        from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
        # M7 P4.1: the player's weapon too. b0 delivers `scenarios_v2.B0_KEYS` -- since M7 P4.2a (ae16682) the
        # TRIGGER too, fire and the number keys (model_frames' `bkeys`); never strafe: the model's strafe reaches the
        # binary through the injected pose -- and the mirror steps the same keys (issue #119 item 8: this comment
        # said "no fire, no number keys" after the delivery had changed)
        mph = MonsterPhase(orc.mw, orc.mapname, BOOT_SKILL, rm=orc.rm, mode=MONSTER_MODE, player=pmode or PLAYER_MODE)
        if sfn is not None:
            sfn(mph)                                     # M7 P6+P7: the set's corpses, as the binary is poked
    loot = mph is not None and player_loots(mph.world.player)     # M7 P6: removals, barrels by state, the card
    # M7 P3.2a: a monster that can wake reads the seen flags of the LAST picture, which the binary marks on every
    # frame -- so the model's picture (and its seen flags) is taken on every frame too, whatever `pixel_every`
    seen_every = mph is not None and mph.world.monsters != "idle"
    # M7 P3.2b: monsters that MOVE press the monster doors (`dreq`, which b0 does not inject: it persists into the
    # binary's next door tic) and hold closing doors open -- so the expectation is the mirror RE-STEPPED here with
    # them: each frame's door tic gets their boxes, and their presses join the mirror's pending requests. (Their
    # lift triggers need nothing: b0 writes the lifts, `lreq` included, at every frame start.)
    chase = mph is not None and mph.world.monsters not in ("idle", "wake") and override is None
    cm = S.BinaryMirror(S.start_world(frames[0]["run_setup"])) if chase and frames else None
    for f, fr in enumerate(frames):
        mheights = fr.get("mheights")
        # M7 P4.1 / P4.2a: the weapon tics FIRST, as the binary's does -- after the doors, before the player's move and
        # the monsters' tic -- at the frame's injected (pre-move) pose: a shot that hits lands before the monster acts
        _boxes = mph.boxes() if mph is not None else ()   # the door tic precedes the weapon (and its kills)
        if mph is not None and inject_hurt and fr.get("hurt") is not None:   # M7 P5: as `start` writes them
            mph.world.ws.p_health, mph.world.ws.p_armor, mph.world.ws.p_armortype = fr["hurt"]
        if mph is not None and not chase:
            mph.weapon(fr["keys"], fr["inj"][0] & M32, fr["inj"][1] & M32, fr["inj"][2])
        if chase:
            # M7 P6: the mirror runs the weapon and the move itself (`BinaryMirror.step(mph=)`): nukage, then the
            # weapon, then the model's move once the player loots -- the binary's order
            epose, edoors = cm.step(fr["inj"], fr["keys"], fr["doors"], fr.get("movers"), others=_boxes, mph=mph)
            if tuple(epose[:2]) != tuple(fr["post"][:2]):   # M7 P6+P7: the move fell short -- what refused it
                refusers[f] = ("a solid thing" if mph.world._solid_thing_at(fr["post"][0], fr["post"][1]) is not None
                               else "a wall or step (try_move)")
            if player_loots(mph.world.player):
                loot_part += loot_cells(mph.world) != fr.get("post_loot", loot_cells(mph.world))
            cm.state, cm.mstate = mph.frame(cm.state, cm.mstate, epose[0] & 0xFFFFFFFF, epose[1] & 0xFFFFFFFF,
                                            epose[2])
            mheights = cm.mp.heights(cm.mstate)
        else:
            if mph is not None:
                _ep = override[f][0] if override is not None else fr["exp"][0]
                mph.tic(_ep[0] & 0xFFFFFFFF, _ep[1] & 0xFFFFFFFF, _ep[2])
            epose, edoors = override[f] if override is not None else fr["exp"]
        # M7 P5: no B0 frame may reach a death -- the injected health is the frozen model's, so a mirror whose
        # monsters killed the player inside one frame describes a run the set never made
        if mph is not None and mph.world.ws.p_dead:
            dead.append(f)
        # M7 P5: the palette this present showed: the mirror's damage flash (combat.palette_index)
        pal_ok.append(mf + f < len(r.palettes)
                      and r.palettes[mf + f] == orc.palette_sha(mph.palette() if mph is not None else 0))
        got = readback.get(f)
        state_ok.append(got is not None and got["mode"] == 0 and (
            got["viewx"], got["viewy"], got["viewangle"], got["dstate"]) == (
            P_signed(epose[0]), P_signed(epose[1]), epose[2] & M32, tuple(edoors)))
        c_part = (P_signed(epose[0]), P_signed(epose[1]), epose[2] & M32) != (
            P_signed(fr["post"][0]), P_signed(fr["post"][1]), fr["post"][2] & M32)
        d_part = fr.get("post_doors") is not None and tuple(edoors) != tuple(fr["post_doors"])
        cam += c_part
        door += d_part
        if c_part:
            cam_frames.append(f)
        check = f % pixel_every == 0 or c_part or d_part or seen_every
        # M7 P3.2a: the monsters' seen flags come from EVERY picture, checked or not (and a monster that can
        # wake makes every picture a checked one: `seen_every`)
        if check or mph is not None:
            _seen = set()
            want = orc.render(P_signed(epose[0]), P_signed(epose[1]), epose[2], tuple(edoors),
                              movers=mheights,
                              views=orc.monster_views(mph, P_signed(epose[0]), P_signed(epose[1]))
                              if mph is not None else None, seen_out=_seen,
                              positions=orc.monster_positions(mph) if mph is not None else None,
                              screen_kw=mph.screen_kw() if mph is not None else None,
                              aim_things=orc._mv(mph.world).aim_things(mph) if mph is not None else None,
                              aim_out=(_aim := [0] * 17),
                              mobiles=mph.mobiles() if mph is not None else None,     # M7 P5
                              removed=orc.monster_removed(mph) if loot else None,    # M7 P6
                              barrel_views=orc.monster_barrel_views(mph) if loot else None,
                              card=(cm.state[3] if cm is not None else 0) if loot else None)
            if mph is not None:
                mph.set_aim(_aim)                        # M7 P4.2a: the window, for the next frame's weapon
            if mph is not None:
                mph.set_seen(orc._mviews.slots_of(_seen))
            if check and gb is not None:
                pix_ok.append(r.frames[mf + f] == want)
                pix_frames.append(f)
        else:
            want = None
        # M7 P6+P7: what this frame expected -- the proxy's note compares two runs' traces frame by frame
        trace.append({"pose": (P_signed(epose[0]), P_signed(epose[1]), epose[2] & M32), "doors": tuple(edoors),
                      "picture": hashlib.sha256(want).hexdigest()[:16] if want is not None else None,
                      "bar": mph.screen_kw() if mph is not None else None,
                      "loot": loot_cells(mph.world) if loot else None,
                      "taken": tuple((i, mph.world.pickup_things[i].type, mph.world.pickup_things[i].x,
                                      mph.world.pickup_things[i].y) for i in mph.taken()[0]) if loot else None})
    return {"ops_total": r.ops, "frame_ops": ops_f, "state_ok": state_ok, "pix_ok": pix_ok,
            "pix_frames": pix_frames, "cam_parts": cam, "door_parts": door, "pal_ok": pal_ok, "dead": dead,
            "loot_parts": loot_part, "cam_frames": cam_frames, "trace": trace, "refusers": refusers,
            "setup_poked": sorted(poke), "setup_pre": setup_pre,
            "presented": len(r.frames), "seconds": r.seconds, "frames": r.frames[mf:]}


def summarize(res, base_ops, n):
    fo = sorted(res["frame_ops"])
    pct = lambda q: fo[min(len(fo) - 1, -(-int(q * 100) * len(fo) // 100) - 1)]   # noqa: E731
    return {"avg_exact": (res["ops_total"] - base_ops) / n, "p50": pct(0.5), "p80": pct(0.8),
            "max": fo[-1]}


def b0(doc_path: Path, fjm: Path, labels: Path, pixel_every: int, out_json, proxy: bool) -> int:
    import gamespeed as GS
    import m2_std_gate as gate
    doc = json.loads(Path(doc_path).read_text(encoding="ascii"))
    S.use_sight_rule(doc)          # M7 P3.2: the set names its sight rule (v5: "seen"); its replay runs under it
    t0 = time.time()
    runs = [(run["name"], model_frames(run), model_frames(run, proxy=True) if proxy else None)
            for run in doc["runs"]]
    print("  model replays: %d runs reproduce the set's poses (%.0f s, outside the lock)"
          % (len(runs), time.time() - t0), flush=True)
    orc = GameOracle()
    assert list(orc.door_order) == list(S.new_world().door_order), "door order differs"
    names = {c.label for c in P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon).values()}
    if any(setup_fn(run["setup"]) for run in doc["runs"]):          # M7 P6+P7: the aftermath's poke
        names |= {c.label for c in setup_cell_specs(orc).values()}
    with P.binary_lock("S4v2-b0"):
        table = P.LabelTable.load(labels, names)
        gb = P.GameBinary(fjm)
        base = gb.run(gate.MENU_FRAMES).ops           # startup + the menu frames, EXACT
        print("b0_scenarios: %s sha256 %s | set %s (%d runs, keys %s) | startup+menu %s ops (exact)"
              % (fjm.name, gb.sha[:16], Path(doc_path).name, len(runs), S.keys_sha(doc),
                 format(base, ",")), flush=True)
        results = []
        for name, frames, pframes in runs:
            res = drive(gb, table, orc, frames, pixel_every=pixel_every)
            res["name"] = name
            res["strafe_only"] = sum(fr["strafe_only"] for fr in frames)
            if pframes is not None:
                rp = drive(gb, table, orc, pframes, pixel_every=pixel_every)
                res["proxy"] = rp
                res["proxy_same_picture"] = rp["frames"] == res["frames"]
                res["proxy_note"] = proxy_note(res, rp, frames, pframes)
            results.append(res)
    print("  %-20s %12s %11s %11s %11s  %-9s %-9s %3s %3s %4s"
          % ("run", "avg (exact)", "p50 +-2^18", "p80", "max", "state", "pixels", "cam", "dr",
             "sonl"))
    avgs, allf, rows = [], [], []
    for res in results:
        s = summarize(res, base, len(res["frame_ops"]))
        avgs.append(s["avg_exact"])
        allf += [(v, res["name"]) for v in res["frame_ops"]]
        rows.append({"name": res["name"], **s, "state_ok": sum(res["state_ok"]),
                     "state_n": len(res["state_ok"]), "pix_ok": sum(res["pix_ok"]),
                     "pix_n": len(res["pix_ok"]), "cam_parts": res["cam_parts"],
                     "door_parts": res["door_parts"], "strafe_only_frames": res["strafe_only"],
                     "seconds": res["seconds"], "frame_ops": res["frame_ops"]})
        print("  %-20s %12s %11s %11s %11s  %3d/%-5d %3d/%-5d %3d %3d %4d"
              % (res["name"], format(int(round(s["avg_exact"])), ","), format(s["p50"], ","),
                 format(s["p80"], ","), format(s["max"], ","), sum(res["state_ok"]),
                 len(res["state_ok"]), sum(res["pix_ok"]), len(res["pix_ok"]), res["cam_parts"],
                 res["door_parts"], res["strafe_only"]))
    mean, p80 = sum(avgs) / len(avgs), GS.percentile_run(avgs)
    binding = GS.binding_speed(avgs)
    p80_name = next(r["name"] for r in rows if r["avg_exact"] == p80)
    fmax = max(allf)
    print("  B0 BINDING (mean + p80)/2 over %d runs: %s ops/frame   (mean %s, p80 run %s = %s)"
          % (len(avgs), format(int(round(binding)), ","), format(int(round(mean)), ","),
             p80_name, format(int(round(p80)), ",")))
    print("  per-frame maximum: %s ops (+/- 2^18) in %s; run averages %s .. %s; headroom to 22M: %s"
          % (format(fmax[0], ","), fmax[1], format(int(min(avgs)), ","), format(int(max(avgs)), ","),
             format(int(round(22_000_000 - binding)), ",")))
    under = None
    if proxy:
        pavgs, per = [], {}
        print("  STRAFE UNDERCOUNT (--proxy: each strafe-only frame given a forward step into the "
              "same landing):")
        for res in results:
            rp = res["proxy"]
            d = rp["ops_total"] - res["ops_total"]
            pavgs.append((rp["ops_total"] - base) / len(rp["frame_ops"]))
            note = res["proxy_note"]
            per[res["name"]] = {"delta_total": d, "strafe_only_frames": res["strafe_only"],
                                "per_strafe_only_frame": d / res["strafe_only"] if res["strafe_only"] else None,
                                "state_ok": sum(rp["state_ok"]), "pix_ok": sum(rp["pix_ok"]),
                                "pix_n": len(rp["pix_ok"]), "same_picture": res["proxy_same_picture"],
                                "refused": note["refused"], "note": note["text"], "avg_exact_proxy": pavgs[-1]}
            print("    %-20s +%s ops over %d strafe-only frames = %s per frame; against its own oracle: state "
                  "%d/%d pixels %d/%d; picture identical to the normal run: %s%s"
                  % (res["name"], format(d, ","), res["strafe_only"],
                     format(int(round(d / res["strafe_only"])), ",") if res["strafe_only"] else "-",
                     sum(rp["state_ok"]), len(rp["state_ok"]), sum(rp["pix_ok"]), len(rp["pix_ok"]),
                     res["proxy_same_picture"], "" if res["proxy_same_picture"] else " (NOTE, not a failure)"))
            if not res["proxy_same_picture"] or note["refused"]:
                print("      note: %s" % note["text"])
            if note["refused"]:
                print("      !! %d proxy step(s) REFUSED at frames %s: there the proxy ran a refused move from one "
                      "step short of the landing and drew that pose -- not the collision tic at the landing; this "
                      "run's delta is not the strafe's price on those frames" % (len(note["refused"]),
                                                                               note["refused"][:8]))
        pb = GS.binding_speed(pavgs)
        tot_d = sum(v["delta_total"] for v in per.values())
        tot_n = sum(v["strafe_only_frames"] for v in per.values())
        print("    binding with the collision tic on strafe-only frames: %s (B0 + %s); %s ops per "
              "strafe-only frame over %d frames"
              % (format(int(round(pb)), ","), format(int(round(pb - binding)), ","),
                 format(int(round(tot_d / tot_n)), ",") if tot_n else "-", tot_n))
        refused = sum(len(v["refused"]) for v in per.values())
        if refused:
            print("    !! %d strafe-only frame(s) priced by a REFUSED proxy step (listed above): the delta over them "
                  "is not the strafe's collision tic" % refused)
            # issue #123 L4 (RECORDED, not a failure): on v6 the one refusal is R2-spectre-corridor frame 0 -- 1 of
            # 324 strafe-only frames, one step behind the landing inside a wall
            print("    note: a RECORDED deviation of the proxy (issue #123 L4; v6: R2-spectre-corridor frame 0, 1 of 324 "
                  "strafe-only frames) -- a refused proxy frame is priced from one step short, never judged")
        under = {"binding_proxy": pb, "mean_proxy": sum(pavgs) / len(pavgs),
                 "p80_proxy": GS.percentile_run(pavgs), "delta_binding": pb - binding,
                 "strafe_only_frames": tot_n, "delta_total": tot_d, "refused_steps": refused,
                 "per_strafe_only_frame": tot_d / tot_n if tot_n else None, "per_run": per,
                 "method": "each strafe-only frame injected one FORWARD step behind the model's "
                           "landing with forward delivered: the binary runs its collision tic into "
                           "the same pose; the difference is exact. Since P6 the step is not neutral: "
                           "it touches what lies at the landing (a pickup the normal run's still frame "
                           "never takes) and a solid thing can refuse it -- so each proxy run is judged "
                           "against its OWN oracle, and 'same picture' is a recorded note"}
    bad = judge(results, proxy)
    if out_json:
        cmd = "python scratchpad/gp/b0_scenarios.py --file %s --pixel-every %d%s --json %s" % (
            Path(doc_path).as_posix(), pixel_every, " --proxy" if proxy else "", Path(out_json).as_posix())
        Path(out_json).write_text(json.dumps({
            "fjm": str(fjm), "sha256": gb.sha, "labels": str(labels),
            "labels_sha256": hashlib.sha256(Path(labels).read_bytes()).hexdigest(),
            "set": str(doc_path), "keys_sha": S.keys_sha(doc), "driver_sha16": sha16(HERE / "b0_scenarios.py"),
            "command": cmd, "base_ops": base, "binding": binding, "mean": mean, "p80_run": p80,
            "p80_run_name": p80_name, "frame_max": fmax[0], "frame_max_run": fmax[1],
            "runs": rows, "strafe_undercount": under}, indent=1), encoding="ascii")
    if bad:
        print("  !! state or pixel mismatches in %s -- these numbers describe a wrong run" % bad)
    print("B0 %s" % ("OK" if not bad else "FAIL"))
    return 1 if bad else 0


def run_ok(r: dict) -> list:
    """the reasons one drive result is WRONG (empty: right): state and pixels against its own expectation on
    every frame, every frame presented, every palette, no mirror death, the setup's cells as the level start had
    them before the poke"""
    out = []
    if not (all(r["state_ok"]) and all(r["pix_ok"]) and r["presented"] == len(r["state_ok"]) + 2):
        out.append("")
    if not all(r["pal_ok"]):
        out.append("(palette)")
    if r["dead"]:
        out.append("(dead at %s)" % r["dead"][:3])
    if r.get("setup_pre"):
        out.append("(setup: %s held other values before the poke)" % r["setup_pre"][:4])
    return out


def judge(results: list, proxy: bool) -> list:
    """the runs that FAIL b0, by name. M7 P6+P7 (the coordinator's decision, 2026-10-06): a --proxy run is a COST
    measurement and is judged like the normal run -- against its OWN oracle (`run_ok`); whether it draws the
    normal run's pictures is a recorded note (`proxy_note`), not a failure: since P6 the proxy's forward step
    touches what lies at the landing and a solid thing can refuse it"""
    bad = [r["name"] + why for r in results for why in run_ok(r)]
    if proxy:
        bad += [r["name"] + "(proxy)" + why for r in results for why in run_ok(r["proxy"])]
    return bad


def proxy_note(res: dict, rp: dict, frames: list, pframes: list) -> dict:
    """why a proxy run's expectation parts from the normal run's (the two traces, frame by frame): `refused` the
    strafe-only frames whose proxy step did not reach the model's landing (a thing or a wall refused the forward
    step: the pose drawn is one step short), and the FIRST frame the two expectations part with its cause -- a
    refused step, a pickup the proxy's step touched (the loot cells part: the normal run's strafe-only frame does
    not move, so it touches nothing), the bar, or the picture alone"""
    refused = [f for f in rp["cam_frames"] if pframes[f]["strafe_only"] and f not in res["cam_frames"]]
    ta, tb = res["trace"], rp["trace"]
    differ = [f for f in range(min(len(ta), len(tb))) if ta[f] != tb[f]]
    pic = [f for f in differ if ta[f]["picture"] != tb[f]["picture"]]
    if not differ:
        return {"refused": refused, "first": None, "cause": None, "differ": 0,
                "text": "the proxy expected the normal run's every frame"}
    f = differ[0]
    a, b = ta[f], tb[f]
    if f in refused:
        cause = "a REFUSED step, by %s (pose %s, the model's landing %s)" % (
            rp.get("refusers", {}).get(f, "?"), b["pose"], a["pose"])
    elif a["pose"] != b["pose"]:
        cause = "the pose (%s vs %s)" % (b["pose"], a["pose"])
    elif a["taken"] != b["taken"] or a["loot"] != b["loot"]:
        ks = sorted(k for k in a["loot"] if a["loot"][k] != b["loot"][k])
        va, vb = (a["bar"] or {}).get("values", {}), (b["bar"] or {}).get("values", {})
        drops = [k for k, (x, y) in enumerate(zip(a["loot"]["mdrop"], b["loot"]["mdrop"])) if x == 1 and y == 2]
        what = (["item %d (type %d at %d, %d)" % t for t in sorted(set(b["taken"]) - set(a["taken"]))]
                + ["the DROP of dropper %d" % k for k in drops])
        cause = ("a PICKUP the proxy's step touched at the landing -- %s; the normal run's strafe-only frame does "
                 "not move, so it never takes it (%s)") % (
                    ", ".join(what) or "nothing taken",
                    ", ".join(["%s %s -> %s" % (k, a["loot"][k], b["loot"][k]) for k in ks if k != "mdrop"]
                              + ["bar %s %s -> %s" % (k, va[k], vb.get(k)) for k in sorted(va) if va[k] != vb.get(k)]))
    elif a["bar"] != b["bar"]:
        ks = sorted(k for k in a["bar"] if a["bar"][k] != b["bar"].get(k))
        cause = "the bar (%s)" % ", ".join("%s %s -> %s" % (k, a["bar"][k], b["bar"].get(k)) for k in ks)
    else:
        cause = "the picture alone (the monsters or effects part)"
    so = "a strafe-only frame" if pframes[f]["strafe_only"] else "not a strafe-only frame"
    return {"refused": refused, "first": f, "cause": cause, "differ": len(differ),
            "text": "the expectations part first at frame %d (%s): %s; %d frames' expectations differ, %d pictures"
                    % (f, so, cause, len(differ), len(pic))}


def selftest(fjm: Path, labels: Path, doc_path: Path) -> int:
    """R9 for the driver: its composition IS gamespeed's (a recorded run reproduces to the op, with
    every door written each frame), its state and pixel checks have teeth, a door write takes
    effect, and the strafe proxy changes the ops and not the picture.
    M7 P6+P7: T7 a run's SETUP poke (v6's aftermath corpses) takes effect and a binary not poked is rejected (SKIPPED
    on a set without a setup); T8 a proxy run is judged against its own oracle, and a broken one FAILS `judge`."""
    global setup_poke
    import m2_std_gate as gate
    import b0 as B
    fails = []

    def check(name, cond, detail=""):
        print("  %-78s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    w = S.new_world()
    mirror = S.BinaryMirror(w)
    # T1: gamespeed run 0 as frames: DoorSim's pre-tic pose and doors injected, its keys delivered
    import gamespeed as GS
    keys = GS.script(B.RECORDED_TIC_RUN)
    frames = doorsim_frames(keys, mirror)
    doc = json.loads(Path(doc_path).read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    runs = {r["name"]: r for r in doc["runs"]}
    court = model_frames(runs["R0-courtyard"])[:6]
    nw, nwp = model_frames(runs["R0-northwest"])[:30], model_frames(runs["R0-northwest"], proxy=True)[:30]
    aft_run = next((r for r in doc["runs"] if setup_fn(r["setup"]) is not None), None)
    aftf = model_frames(aft_run)[:6] if aft_run is not None else None
    orc = GameOracle()
    # T5's window: the first frame of the aftermath run (then the west hall's) from which opening a
    # still-shut door changes the picture, and the door
    from doomfj.doors import IDLE, WAIT

    def open_state(ed, only=None):
        return tuple(w.door_nstates[si] - 1 if (only is None or d == only) else ed[d]
                     for d, si in enumerate(w.door_order))
    found = None
    for rname in ("R0-aftermath", "R0-west-hall", "R0-imp-court"):
        frs = model_frames(runs[rname])
        for k in range(2, len(frs) - 6):
            (ex, ey, ea), ed = frs[k]["exp"]
            shut = orc.render(P_signed(ex), P_signed(ey), ea, tuple(ed))
            if orc.render(P_signed(ex), P_signed(ey), ea, open_state(ed)) == shut:
                continue
            door = next((d for d in range(len(ed)) if not ed[d] and orc.render(
                P_signed(ex), P_signed(ey), ea, open_state(ed, d)) != shut), None)
            if door is not None:
                found = (rname, k, door, frs[k - 2:k + 6])
                break
        if found:
            break
    rname, k0, door, aft = found
    si = w.door_order[door]
    opened = []
    for k, fr in enumerate(aft):
        fr2 = dict(fr)
        if k >= 2:
            ds = [tuple(t) for t in fr["doors"]]
            ds[door] = (w.door_nstates[si] - 1, IDLE, 0, WAIT)
            fr2["doors"] = ds
            fr2["exp"] = mirror.step(fr["inj"], fr["keys"], ds, fr.get("movers"))
            fr2["post_doors"] = None
        opened.append(fr2)
    names = {c.label for c in P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon).values()}
    if aftf is not None:
        names |= {c.label for c in setup_cell_specs(orc).values()}
    with P.binary_lock("S4v2-b0-selftest"):
        table = P.LabelTable.load(labels, names)
        gb = P.GameBinary(fjm)
        r1 = drive(gb, table, orc, frames, pixel_every=10)
        # the recorded total and calibration belong to ONE binary (probe.RECORDED_SHA16): on any other they are
        # SKIPPED by name, never passed
        recorded = gb.sha.startswith(P.RECORDED_SHA16)
        if recorded:
            check("T1 gamespeed run %d, every door written each frame, reproduces the recorded total"
                  % B.RECORDED_TIC_RUN, r1["ops_total"] == B.RECORDED_TIC_OPS,
                  "%s vs %s" % (format(r1["ops_total"], ","), format(B.RECORDED_TIC_OPS, ",")))
        else:
            print("  T1 recorded total: SKIPPED -- recorded for sha256 %s..., this is %s (%s ops)"
                  % (P.RECORDED_SHA16, gb.sha[:16], format(r1["ops_total"], ",")), flush=True)
        check("T1 ... state-exact and byte-exact against the mirror, which never parts from DoorSim",
              all(r1["state_ok"]) and all(r1["pix_ok"]) and r1["cam_parts"] == 0 and r1["door_parts"] == 0,
              "state %d/%d pixels %d/%d parts %d/%d" % (sum(r1["state_ok"]), len(r1["state_ok"]),
                                                        sum(r1["pix_ok"]), len(r1["pix_ok"]),
                                                        r1["cam_parts"], r1["door_parts"]))
        bent = [((p[0], p[1], (p[2] + (640 << 16)) & M32), d) for p, d in (fr["exp"] for fr in frames)]
        r2 = drive(gb, table, orc, frames, pixel_every=50, override=bent)
        check("T2 an expectation one turn off FAILS the state check on every frame",
              not any(r2["state_ok"]), "%d/%d accepted" % (sum(r2["state_ok"]), len(r2["state_ok"])))
        menu = gb.run(gate.MENU_FRAMES).ops
        if recorded:
            check("T3 startup + menu measured through this driver = the recorded calibration",
                  menu == P.RECORDED_CALIBRATION, "%s" % format(menu, ","))
        else:
            print("  T3 recorded calibration: SKIPPED -- recorded for sha256 %s... (%s ops here)"
                  % (P.RECORDED_SHA16, format(menu, ",")), flush=True)
        good = drive(gb, table, orc, court, pixel_every=1)
        plain = drive(gb, table, P.Oracle(), court, pixel_every=1)
        check("T4 the game oracle passes the courtyard's sky frames, state- and pixel-exact",
              all(good["pix_ok"]) and all(good["state_ok"]), "%d/%d" % (sum(good["pix_ok"]),
                                                                      len(good["pix_ok"])))
        nosky = type("NoSky", (GameOracle,), {"RENDER_KW": dict(GameOracle.RENDER_KW, sky=False)})()
        bad = drive(gb, table, nosky, court, pixel_every=1)
        check("T4 negative: an oracle WITHOUT sky is rejected on the same frames",
              not any(bad["pix_ok"]), "%d/%d accepted (probe.Oracle today: %d/%d)" % (
                  sum(bad["pix_ok"]), len(bad["pix_ok"]), sum(plain["pix_ok"]), len(plain["pix_ok"])))
        base_a = drive(gb, table, orc, aft, pixel_every=1)
        door_a = drive(gb, table, orc, opened, pixel_every=1)
        check("T5 a door written open takes effect: state- and pixel-exact against the mirror",
              all(door_a["state_ok"]) and all(door_a["pix_ok"]),
              "%s frames %d..%d, door %d (sector %d) from frame %d: state %d/%d pixels %d/%d" % (
                  rname, k0 - 2, k0 + 5, door, si, k0, sum(door_a["state_ok"]), len(door_a["state_ok"]), sum(door_a["pix_ok"]),
                  len(door_a["pix_ok"])))
        check("T5 ... the write frame's picture differs from the unwritten run's, the two before it"
              " do not", door_a["frames"][2] != base_a["frames"][2]
              and door_a["frames"][:2] == base_a["frames"][:2] and all(base_a["state_ok"]),
              "%d/%d frames differ" % (sum(door_a["frames"][k] != base_a["frames"][k]
                                          for k in range(len(aft))), len(aft)))
        a = drive(gb, table, orc, nw, pixel_every=1)
        b = drive(gb, table, orc, nwp, pixel_every=1)
        so = sum(fr["strafe_only"] for fr in nw)
        check("T6 the strafe proxy draws the same pictures, state-exact",
              a["frames"] == b["frames"] and all(b["state_ok"]) and all(a["state_ok"]),
              "%d strafe-only frames of %d" % (so, len(nw)))
        check("T6 ... and costs more ops (the collision tic it adds)",
              so > 0 and b["ops_total"] > a["ops_total"],
              "+%s ops" % format(b["ops_total"] - a["ops_total"], ","))
        # T7 (M7 P6+P7): the aftermath's SETUP -- three corpses, two clips lying -- poked at the first game frame:
        # the binary held the level start's values first, and then draws and steps what the mirror does
        if aftf is None:
            print("  T7 the setup poke: SKIPPED -- the set %s has no run with a setup (v6's R0-aftermath has)"
                  % Path(doc_path).name, flush=True)
        else:
            a7 = drive(gb, table, orc, aftf, pixel_every=1)
            check("T7 the aftermath's corpses poked: the level start's values read back, then state- and pixel-exact",
                  not a7["setup_pre"] and all(a7["state_ok"]) and all(a7["pix_ok"]) and bool(a7["setup_poked"]),
                  "poked %s; before-poke mismatches %s; state %d/%d pixels %d/%d" % (
                      a7["setup_poked"], a7["setup_pre"], sum(a7["state_ok"]), len(a7["state_ok"]),
                      sum(a7["pix_ok"]), len(a7["pix_ok"])))
            real = setup_poke
            setup_poke = lambda *_a, **_k: ({}, {})        # noqa: E731 -- the mirror keeps the corpses, the binary not
            try:
                n7 = drive(gb, table, orc, aftf, pixel_every=1)
            finally:
                setup_poke = real
            check("T7 negative: the same mirror against a binary NOT poked is rejected on the first frame",
                  not n7["pix_ok"][0] or not n7["state_ok"][0],
                  "frame 0: state %s pixels %s" % (n7["state_ok"][0], n7["pix_ok"][0]))
        # T8 (M7 P6+P7, GAP 1): a proxy run is judged against its OWN oracle -- the northwest proxy passes `judge`, and
        # the same proxy run against an expectation one turn off FAILS it as "(proxy)"
        bentp = [((q[0], q[1], (q[2] + (640 << 16)) & M32), d) for q, d in (fr["exp"] for fr in nwp)]
        bp = drive(gb, table, orc, nwp, pixel_every=50, override=bentp)
        check("T8 the proxy judged against its own oracle passes; a broken own oracle FAILS it",
              judge([dict(a, name="T8", proxy=b)], True) == []
              and judge([dict(a, name="T8", proxy=bp)], True) == ["T8(proxy)"],
              "%s / %s" % (judge([dict(a, name="T8", proxy=b)], True), judge([dict(a, name="T8", proxy=bp)], True)))
    print("")
    print("B0_SCENARIOS SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                                          "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def oracle_only(doc_path: Path, pmode=None, proxy: bool = False, only=None) -> int:
    """M7 P6 (`--oracle-only`): every run REPLAYED on the frozen model (`model_frames` -- it refuses a run whose
    poses no longer reproduce: the freeze), then its expectation stepped with no binary (`drive(None, ...)`): the
    camera, door and loot partings it would count, and any death of the mirror (a death FAILS, as in b0).
    M7 P6+P7: a run with a SETUP (v6's aftermath corpses) prints the cells b0 pokes for it, and is stepped a second
    time WITHOUT the setup -- the R9 control: that run must part from the set (camera or doors), else the setup
    is invisible to b0 and the run FAILS as vacuous. `proxy`: each run's proxy pass too, with its own partings,
    its refused steps and why its expectation parts from the normal run's (`proxy_note`). `only`: run names that
    start with it"""
    doc = json.loads(Path(doc_path).read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    orc = GameOracle()
    if pmode:
        orc.player_mode = pmode
    from doomfj.wall_renderer import PLAYER_MODE
    runs = [r for r in doc["runs"] if not only or r["name"].startswith(only)]
    print("b0_scenarios --oracle-only: set %s (%d runs, keys %s), PLAYER_MODE %s%s"
          % (Path(doc_path).name, len(runs), S.keys_sha(doc), pmode or PLAYER_MODE, ", --proxy" if proxy else ""),
          flush=True)
    bad, rows = [], []
    for run in runs:
        frames = model_frames(run)                     # raises if the frozen model no longer reproduces the set
        res = drive(None, None, orc, frames, pmode=pmode)
        so = sum(fr["strafe_only"] for fr in frames)
        print("  %-20s %3d frames reproduce the set's poses; mirror partings: camera %d, doors %d, loot %d; "
              "deaths %s" % (run["name"], len(frames), res["cam_parts"], res["door_parts"], res["loot_parts"],
                             res["dead"][:3] or 0), flush=True)
        if res["dead"]:
            bad.append(run["name"])
        row = {"name": run["name"], "cam": res["cam_parts"], "dr": res["door_parts"], "loot": res["loot_parts"],
               "dead": len(res["dead"]), "sonl": so}
        if setup_fn(run["setup"]) is not None:
            _before, poke = setup_poke(orc, run["setup"], pmode)
            print("    setup: %d corpses; b0 pokes at the first game frame %s" % (len(run["setup"]["corpses"]),
                                                                           ", ".join(sorted(poke))), flush=True)
            ctl = drive(None, None, orc, frames, pmode=pmode, inject_setup=False)
            seen = ctl["cam_parts"] + ctl["door_parts"] > 0
            print("    CONTROL without the setup: camera %d, doors %d, loot %d -- %s"
                  % (ctl["cam_parts"], ctl["door_parts"], ctl["loot_parts"],
                     "parts from the set (the setup is visible to b0)" if seen
                     else "NEVER parts: the setup is invisible to b0, VACUOUS, FAIL"), flush=True)
            if not seen:
                bad.append(run["name"] + "(control)")
            row["control"] = (ctl["cam_parts"], ctl["door_parts"])
        if proxy:
            pframes = model_frames(run, proxy=True)
            rp = drive(None, None, orc, pframes, pmode=pmode)
            note = proxy_note(res, rp, frames, pframes)
            print("    proxy: partings camera %d (refused steps %d at %s), doors %d, loot %d; deaths %s; %s"
                  % (rp["cam_parts"], len(note["refused"]), note["refused"][:6], rp["door_parts"], rp["loot_parts"],
                     rp["dead"][:3] or 0, note["text"]), flush=True)
            if rp["dead"]:
                bad.append(run["name"] + "(proxy)")
            row.update({"p_cam": rp["cam_parts"], "p_dr": rp["door_parts"], "p_refused": len(note["refused"]),
                        "p_first": note["first"]})
        rows.append(row)
    print("  %-20s %4s %4s %5s %4s %5s %9s%s" % ("run", "cam", "dr", "loot", "dead", "sonl", "control",
                                                "   p_cam p_dr refused first-part" if proxy else ""))
    for r in rows:
        print("  %-20s %4d %4d %5d %4d %5d %9s%s" % (
            r["name"], r["cam"], r["dr"], r["loot"], r["dead"], r["sonl"],
            "%d/%d" % r["control"] if "control" in r else "-",
            "   %5d %4d %7d %10s" % (r["p_cam"], r["p_dr"], r["p_refused"],
                                     "-" if r["p_first"] is None else r["p_first"]) if proxy else ""))
    print("B0 ORACLE-ONLY %s" % ("OK -- the frozen poses reproduce, no mirror dies, every setup is visible" if not bad
                                 else "FAIL: %s" % bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=str(S.SCEN_FILE))
    ap.add_argument("--fjm", default=str(P.DEFAULT_FJM))
    ap.add_argument("--labels", default=str(P.DEFAULT_LABELS))
    ap.add_argument("--pixel-every", type=int, default=5)
    ap.add_argument("--json", default=None)
    ap.add_argument("--proxy", action="store_true", help="also measure the strafe undercount")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--oracle-only", action="store_true",
                    help="M7 P6: replay the set on the frozen model and step the mirror, no binary")
    ap.add_argument("--player-mode", help="--oracle-only: the mirror's player mode (default wall_renderer's)")
    ap.add_argument("--only", help="--oracle-only: the runs whose names start with this")
    a = ap.parse_args()
    if a.oracle_only:
        return oracle_only(Path(a.file), a.player_mode, a.proxy, a.only)
    if a.selftest:
        import gamespeed as GS
        t = time.time()
        GS.script(0)                                     # plan gamespeed's routes outside the lock
        print("  (gamespeed routes planned in %.0f s, outside the lock)" % (time.time() - t))
        return selftest(Path(a.fjm), Path(a.labels), Path(a.file))
    return b0(Path(a.file), Path(a.fjm), Path(a.labels), a.pixel_every,
              Path(a.json) if a.json else None, a.proxy)


if __name__ == "__main__":
    sys.exit(main())
