"""M8 (docs/episode-plan.md 8): `scripts/build_episode.py`, the final creator -- its registry against the RECORDED build
lines (docs/ship-gate.md 1b and 5), its plan, its judges against the real evidence logs, and its resume logic. Every
claim has a negative control: a mutated registry row, a mutated log, a changed input must each be caught."""
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHIP_GATE = ROOT / "docs" / "ship-gate.md"
EVIDENCE = ROOT / "docs" / "ship-evidence"


def _load():
    spec = importlib.util.spec_from_file_location("build_episode", ROOT / "scripts" / "build_episode.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_episode"] = mod             # dataclasses resolve the module by name
    spec.loader.exec_module(mod)
    return mod


BE = _load()


# ── the registry against the record ──────────────────────────────────────────────────────────────────────────────
def recorded_line(mapname: str) -> list:
    """the recorded build command's tokens from `scratchpad/12m/build_labeled.py` on: E1M1's is section 1b's line
    (its `<name>` = blocked65), E1M2's the first `emit_check.py E1M2 --then` line of section 5 (r4's)"""
    text = SHIP_GATE.read_text(encoding="utf-8")
    if mapname == "E1M1":
        sec = text[text.index("## 1b."):text.index("## 2.")]
        line = next(ln for ln in sec.splitlines() if ln.startswith("python scratchpad/12m/build_labeled.py"))
        line = line.replace("<name>", "blocked65")
    else:
        sec = text[text.index("## 5. E1M2"):]
        line = next(ln.strip() for ln in sec.splitlines() if "emit_check.py E1M2 --then" in ln)
    tok = shlex.split(line)
    return tok[tok.index("scratchpad/12m/build_labeled.py"):]


def registry_line(spec) -> list:
    return BE.build_args(spec, spec.recorded_out, spec.recorded_labels, spec.recorded_census)


@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
def test_registry_row_is_the_recorded_build_line(m):
    assert registry_line(BE.REGISTRY[m]) == recorded_line(m)


@pytest.mark.parametrize("m,change", [("E1M1", {"spread": 1}), ("E1M2", {"spread": 2}),
                                      ("E1M1", {"heat": "scratchpad/12m/heat_blocked27_p8a.json.gz"}),
                                      ("E1M2", {"wad": None}), ("E1M1", {"recorded_census": "x.json.gz"})])
def test_negative_control_a_drifted_row_is_caught(m, change):
    assert registry_line(dataclasses.replace(BE.REGISTRY[m], **change)) != recorded_line(m)


@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
def test_recorded_sha256_is_the_ship_gates(m):
    sha = BE.REGISTRY[m].recorded_sha256
    assert re.fullmatch(r"[0-9a-f]{64}", sha)
    assert sha in SHIP_GATE.read_text(encoding="utf-8")


def test_the_unshipped_levels_are_not_ready_placeholders():
    assert list(BE.REGISTRY) == BE.EPISODE == ["E1M%d" % i for i in range(1, 10)]
    for m in BE.EPISODE[2:]:
        s = BE.REGISTRY[m]
        if m in BE.LEVEL_SPREAD:                                               # M8 wave 1 + 2: in their pipeline
            assert s.ready and s.spread == BE.LEVEL_SPREAD[m]
            assert bool(s.recorded_sha256) == (m in BE.LEVEL_SHIPPED)          # a hash only once the level ships
            continue
        assert not s.ready and s.not_ready                                     # a reason is given
        assert s.spread is None and not s.recorded_sha256
    assert BE.REGISTRY["E1M1"].ready and BE.REGISTRY["E1M2"].ready


# ── the plan ─────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
def test_plan_follows_the_contract_and_rule_1(m, tmp_path):
    steps = BE.plan_map(BE.REGISTRY[m], tmp_path)
    assert [s.name for s in steps] == BE.STEP_ORDER
    run = BE.HeavyRunner("creator")
    for s in steps:
        assert s.env == {"DOOMFJ_MAP": m}
        if not s.heavy:
            assert s.name == "sha256"
            continue
        cmd = run.command(s, "x.log")
        k = cmd.index("--")
        assert cmd[1] == str(BE.HEAVY_PY) and cmd[2] == "creator" and cmd[3:5] == ["--prio", "8"]
        assert ("--build" in cmd[:k]) == (s.name == "build")
        assert cmd[k + 1] == sys.executable and "-O" not in cmd and "-OO" not in cmd
    gs = next(s for s in steps if s.name == "gamespeed")
    assert gs.argv[:4] == ["scratchpad/12m/gamespeed.py", "--map", m, "--fjm"]
    tr = next(s for s in steps if s.name == "gamespeed_trail")
    assert ("--record" in tr.argv) == BE.REGISTRY[m].trail_record
    b0 = next(s for s in steps if s.name == "b0")
    assert BE.REGISTRY[m].combat_set in b0.argv and (ROOT / BE.REGISTRY[m].combat_set).exists()
    for t in BE.REGISTRY[m].feature_tests:
        assert (ROOT / t).exists(), t


def test_outputs_never_overwrite_the_recorded_binary(tmp_path):
    for m in ("E1M1", "E1M2"):
        o = BE.outputs(BE.REGISTRY[m], ROOT / "build" / "episode")
        assert o["fjm"] != BE.REGISTRY[m].recorded_out and o["census"] != BE.REGISTRY[m].recorded_census
        assert o["generated"] == "build/episode/generated_doom_%s" % m.lower()


def test_msframe_against_the_maps_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(BE, "BASELINES", tmp_path)
    s = next(s for s in BE.plan_map(BE.REGISTRY["E1M2"], tmp_path) if s.name == "msframe")
    assert "--against" not in s.argv and "no saved baseline" in s.note            # control: no baseline, no compare
    (tmp_path / "shipped_e1m2.json").write_text(json.dumps({"binary": "nowhere/x.fjm"}))
    s = next(s for s in BE.plan_map(BE.REGISTRY["E1M2"], tmp_path) if s.name == "msframe")
    assert s.argv[-4:-2] == ["--against", "shipped_e1m2"] and "not on disk" in s.note


# ── the judges, on the real evidence logs ────────────────────────────────────────────────────────────────────────
LOGS = [("p2a", "p2a_gate"), ("m2_std", "m2_std_gate"), ("m3", "m3_gate"), ("hurt", "hurt_gate"),
        ("fight", "fight_gate"), ("die", "die_gate"), ("gamespeed_trail", "gamespeed_trail"),
        ("gamespeed", "gamespeed"), ("msframe", "msframe"), ("build", "build")]


def _judge(name, m, rc, text, **change):
    spec = dataclasses.replace(BE.REGISTRY[m], **change)
    st = next(s for s in BE.plan_map(spec, ROOT / "build" / "episode") if s.name == name)
    return BE.judge(st, spec, rc, text)


def _log(m, part):
    stem = "blocked63" if m == "E1M1" else "e1m2_r4"
    if part == "b0":
        part = "b0_v10" if m == "E1M1" else "b0"
    return (EVIDENCE / ("%s_%s.log" % (stem, part))).read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
@pytest.mark.parametrize("name,part", LOGS + [("b0", "b0")])
def test_judges_pass_the_shipped_evidence(m, name, part):
    rc = 2 if (m, name) == ("E1M2", "gamespeed") else 0            # E1M2's size is OVER 43% -- waived in its row
    status, met, why = _judge(name, m, rc, _log(m, part))
    assert status == "PASS", (name, why)
    if name == "gamespeed":
        assert met["size_pct"] == {"E1M1": 38.98, "E1M2": 62.19}[m]
    if name == "b0":
        assert met["b0_binding"] == {"E1M1": 16_255_310, "E1M2": 20_058_861}[m]


@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
@pytest.mark.parametrize("name,part", LOGS + [("b0", "b0")])
def test_negative_control_a_failed_or_silent_step_fails(m, name, part):
    text = _log(m, part)
    assert _judge(name, m, 1, text)[0] == "FAIL"                     # the return code alone fails it
    cut = re.sub(r"(?m)^(P2A GATE|HURT GATE|FIGHT GATE|DIE GATE|M2 STANDALONE GATE:|M3 GATE:|TRAIL .*:|B0) (PASS|OK)",
                 r"\1 FAIL", text)
    cut = re.sub(r"done in \d+s", "died", cut)
    cut = re.sub(r"(?m)^SPEED\s+BINDING.*$", "", cut)
    cut = re.sub(r"(?m)^\s*(change|A)\s+median.*$", "", cut)
    assert _judge(name, m, 0, cut)[0] == "FAIL", name                # rc 0 without its PASS line is no pass


def test_negative_control_caps():
    gs = _log("E1M2", "gamespeed")
    assert _judge("gamespeed", "E1M2", 2, gs, size_cap_pct=43.0)[0] == "FAIL"     # the waiver is the row's, not luck
    over = re.sub(r"(B0 BINDING \(mean \+ p80\)/2 over 11 runs: )[\d,]+", r"\g<1>22,000,001", _log("E1M2", "b0"))
    assert _judge("b0", "E1M2", 0, over)[0] == "FAIL"                             # CAP-22
    slow = _log("E1M1", "msframe").replace("VERDICT: NOT SEPARATED", "VERDICT: B SLOWER")
    assert _judge("msframe", "E1M1", 0, slow)[0] == "FAIL"
    assert _judge("emit_check", "E1M1", 0, "emit_check E1M1 (asserts OFF -- refused)\nEMITTED in 3 s")[0] == "FAIL"
    assert _judge("emit_check", "E1M1", 0, "emit_check E1M1 tier game (asserts ON)\nEMITTED in 3 s: {}")[0] == "PASS"
    assert _judge("feature_tests", "E1M1", 0, "18 passed in 2.49s")[0] == "PASS"
    assert _judge("feature_tests", "E1M1", 1, "1 failed, 17 passed")[0] == "FAIL"


# ── resume ───────────────────────────────────────────────────────────────────────────────────────────────────────
PASS_TEXT = {"emit_check": "asserts ON\nEMITTED in 1 s\n", "build": "done in 1s\n", "p2a": "P2A GATE PASS\n",
             "m2_std": "M2 STANDALONE GATE: PASS\n", "m3": "M3 GATE: PASS\n", "hurt": "HURT GATE PASS\n",
             "fight": "FIGHT GATE PASS\n", "die": "DIE GATE PASS\n",
             "b0": "B0 BINDING (mean + p80)/2 over 11 runs: 16,255,310 ops/frame\nB0 OK\n",
             "gamespeed_trail": "TRAIL         x: PASS\n",
             "gamespeed": "SPEED  BINDING (mean+p80)/2: 16,892,755 ops/frame   (target <= 22,000,000)  PASS\n"
                          "SIZE   words              : 52,323,960 = 38.98% of 2^27   (target <= 43%)  PASS\n",
             "playthrough": "LEVEL COMPLETE\n", "feature_tests": "4 passed in 1s\n",
             "msframe": "  base     median    68.7 ms/frame\n  change   median    68.4 ms/frame\n"
                        "  VERDICT: NOT SEPARATED\n"}


class FakeRunner(BE.HeavyRunner):
    """stands in for heavy.py: writes the step's PASS log; the build writes a binary whose bytes follow its flags"""

    def __init__(self, out_dir, fail=()):
        super().__init__("test")
        self.out_dir, self.fail, self.ran = out_dir, set(fail), []

    def run(self, step, log):
        self.ran.append((step.map, step.name))
        p = BE.ROOT / log
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(PASS_TEXT[step.name], encoding="utf-8")
        if step.name == "build":
            o = BE.outputs(BE.REGISTRY[step.map], self.out_dir)
            (BE.ROOT / o["fjm"]).write_bytes(fake_fjm(step.map, step.argv))
            (BE.ROOT / o["labels"]).write_bytes(b"labels")
            gen = BE.ROOT / o["generated"]
            gen.mkdir(parents=True, exist_ok=True)
            (gen / "e1m1_02_main.fj").write_text("program")
        return 1 if step.name in self.fail else 0


def fake_fjm(m, argv) -> bytes:
    return ("fjm %s spread %s" % (m, argv[argv.index("--spread") + 1])).encode()


@pytest.fixture
def episode(tmp_path, monkeypatch):
    """E1M1 alone, its recorded sha256 the fake build's, no playthrough script, plenty of disk"""
    out = tmp_path / "episode"
    spec = BE.REGISTRY["E1M1"]
    sha = hashlib.sha256(fake_fjm("E1M1", BE.build_args(spec, "o", "l", "c"))).hexdigest()
    monkeypatch.setitem(BE.REGISTRY, "E1M1", dataclasses.replace(spec, recorded_sha256=sha))
    monkeypatch.setattr(BE, "PLAYTHROUGH", str(tmp_path / "no_playthrough_gate.py"))
    monkeypatch.setattr(BE, "free_disk_gb", lambda: 100.0)
    return out


def _run(out, runner, src="src-A", **kw):
    ctx = BE.Context(src=src, engine="fj-test", out_dir=out)
    return BE.run_episode(["E1M1"], ctx, runner, out=lambda *a: None, **kw)


def _statuses(rep):
    return {k: v["status"] for k, v in rep["maps"]["E1M1"]["steps"].items()}


HEAVY_STEPS = [s for s in BE.STEP_ORDER if s not in ("sha256", "playthrough")]


def test_first_run_passes_and_the_rerun_skips(episode):
    r1 = FakeRunner(episode)
    rep = _run(episode, r1)
    st = _statuses(rep)
    assert [n for _, n in r1.ran] == HEAVY_STEPS
    assert st.pop("playthrough") == "MISSING" and set(st.values()) == {"PASS"}, st
    assert rep["maps"]["E1M1"]["steps"]["sha256"]["metrics"]["identical"] is True
    assert rep["maps"]["E1M1"]["summary"]["warnings"] == ["playthrough"]
    md = (episode / "report.md").read_text(encoding="utf-8")
    assert "WARNING" in md and "playthrough" in md and json.loads((episode / "report.json").read_text())
    assert not (BE.ROOT / BE.outputs(BE.REGISTRY["E1M1"], episode)["generated"]).exists()     # G8: cleaned
    assert (BE.ROOT / BE.outputs(BE.REGISTRY["E1M1"], episode)["fjm"]).exists()               # ... the binary kept
    r2 = FakeRunner(episode)
    rep2 = _run(episode, r2)
    assert r2.ran == [] and all(v.get("skipped") for k, v in rep2["maps"]["E1M1"]["steps"].items()
                                if k != "playthrough")


def test_negative_control_a_changed_source_reruns_every_step(episode):
    _run(episode, FakeRunner(episode))
    r = FakeRunner(episode)
    _run(episode, r, src="src-B")
    assert [n for _, n in r.ran] == HEAVY_STEPS


def test_a_changed_flag_reruns_the_build_and_what_its_bytes_reach(episode, monkeypatch):
    _run(episode, FakeRunner(episode))
    spec = BE.REGISTRY["E1M1"]
    monkeypatch.setitem(BE.REGISTRY, "E1M1", dataclasses.replace(spec, spread=1))     # different bytes
    r = FakeRunner(episode)
    rep = _run(episode, r)
    # emit_check takes no spread, and the tests/fj feature tests never read the binary: both keep their pass
    assert [n for _, n in r.ran] == [s for s in HEAVY_STEPS if s not in ("emit_check", "feature_tests")]
    assert _statuses(rep)["sha256"] == "FAIL"                                          # NOT byte-identical
    monkeypatch.setitem(BE.REGISTRY, "E1M1", dataclasses.replace(spec, spread=1, heat="x"))   # same bytes
    r = FakeRunner(episode)
    _run(episode, r)
    assert [n for _, n in r.ran] == ["build"]          # the gates judged these exact bytes already; sha256 re-checks
    # ... except sha256, which is local and FAILED last time: it ran again (not via the runner)


def test_a_failed_step_reruns_and_a_failed_build_blocks(episode):
    _run(episode, FakeRunner(episode, fail={"p2a"}))
    r = FakeRunner(episode)
    rep = _run(episode, r)
    assert [n for _, n in r.ran] == ["p2a"] and _statuses(rep)["p2a"] == "PASS"
    r = FakeRunner(episode, fail={"build"})
    rep = _run(episode, r, src="src-C")
    st = _statuses(rep)
    assert [n for _, n in r.ran] == ["emit_check", "build"] and st["build"] == "FAIL"
    assert all(st[s] == "NOT RUN" for s in BE.STEP_ORDER[2:]), st
    assert rep["verdict"] == "FAIL"


def test_force_and_dry_run(episode):
    _run(episode, FakeRunner(episode))
    r = FakeRunner(episode)
    _run(episode, r, force=True)
    assert [n for _, n in r.ran] == HEAVY_STEPS
    state = (episode / "state.json").read_bytes()
    r = FakeRunner(episode)
    rep = _run(episode, r, src="src-D", dry_run=True)
    assert r.ran == [] and (episode / "state.json").read_bytes() == state
    assert {v["planned"] for k, v in rep["maps"]["E1M1"]["steps"].items() if k != "playthrough"} == {"RUN"}


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(BE, "free_disk_gb", lambda: 100.0)
    out = tmp_path / "fresh"
    r = FakeRunner(out)
    rep = BE.run_episode(BE.EPISODE, BE.Context("s", "e", out), r, dry_run=True, out=lambda *a: None)
    assert r.ran == [] and not out.exists()
    assert {m for m, v in rep["maps"].items() if not v["ready"]} == set(BE.EPISODE[2:]) - set(BE.LEVEL_SPREAD)


def test_the_playthrough_gate_runs_once_it_exists(episode, monkeypatch, tmp_path):
    script = tmp_path / "playthrough_gate.py"
    script.write_text("")
    monkeypatch.setattr(BE, "PLAYTHROUGH", str(script))
    r = FakeRunner(episode)
    rep = _run(episode, r)
    assert ("E1M1", "playthrough") in r.ran and _statuses(rep)["playthrough"] == "PASS"


def test_steps_filter(episode):
    r = FakeRunner(episode)
    rep = _run(episode, r, steps={"emit_check", "m3"})
    assert [n for _, n in r.ran] == ["emit_check", "m3"] and set(rep["maps"]["E1M1"]["steps"]) == {"emit_check", "m3"}


def test_disk_floor_refuses_the_build(episode, monkeypatch):
    monkeypatch.setattr(BE, "free_disk_gb", lambda: 14.9)
    r = FakeRunner(episode)
    rep = _run(episode, r)
    b = rep["maps"]["E1M1"]["steps"]["build"]
    assert [n for _, n in r.ran] == ["emit_check"] and b["status"] == "FAIL" and "14.9 GB free" in b["why"]


def test_estimate_comes_from_measured_times():
    st = BE.plan_map(BE.REGISTRY["E1M2"], ROOT / "build" / "episode")[1]           # E1M2's build
    assert BE.estimate(st, {}) == (120.0, "guess")
    other = {"E1M1": {"build": {"rc": 0, "wall_s": 2600.0}}}
    assert BE.estimate(st, other) == (2600.0 / 60, "measured on E1M1")
    own = dict(other, E1M2={"build": {"rc": 0, "wall_s": 7181.0}})
    assert BE.estimate(st, own) == (7181.0 / 60, "measured")
    refused = {"E1M2": {"build": {"rc": None, "wall_s": 0.0}}}                       # a refusal is no measurement
    assert BE.estimate(st, refused) == (120.0, "guess")


# ── the guards ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_python_O_is_refused():
    script = str(ROOT / "scripts" / "build_episode.py")
    for argv, env in (([sys.executable, "-O", script, "--dry-run", "--maps", "E1M1"], None),
                      ([sys.executable, script, "--dry-run", "--maps", "E1M1"], dict(os.environ, PYTHONOPTIMIZE="1"))):
        p = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
        assert p.returncode == 2 and "REFUSED" in p.stderr, (p.returncode, p.stderr[-300:])


def test_refuses_to_run_under_its_own_parents_lock(tmp_path, monkeypatch):
    lock = tmp_path / "HEAVY.lock"
    monkeypatch.setattr(BE.heavy, "LOCK", str(lock))
    assert BE.refuse_nested_lock() is None
    lock.write_text("BUILD integ prio 8 pid %d since now: python x\n" % os.getppid())
    assert "REFUSED" in BE.refuse_nested_lock()
    lock.write_text("BUILD integ prio 8 pid %d since now: python x\n" % (os.getppid() + 100000))
    assert BE.refuse_nested_lock() is None                                           # someone else's lock: just wait
