"""build_episode.py -- M8's FINAL CREATOR (docs/episode-plan.md 8): build and verify E1M1..E1M9, ONE HEAVY JOB AT A TIME.

    python scripts/build_episode.py                          # every map (a NOT READY one is reported, not run)
    python scripts/build_episode.py --maps E1M1 E1M2         # a subset
    python scripts/build_episode.py --dry-run                # the full plan of commands; runs nothing, writes nothing
    python scripts/build_episode.py --steps p2a m3           # only these steps (the others keep their recorded state)
    python scripts/build_episode.py --force                  # re-run passed steps too

PER MAP, in the per-level contract's order (docs/episode-plan.md 4): `scripts/emit_check.py` (asserts ON), the fast
build with the map's RECORDED flags (docs/ship-gate.md 1b / 5), the sha256 against the recorded one (a byte-identical
rebuild check when a hash is recorded), the gates (p2a, m2_std, m3, hurt, fight, die, B0 on the map's combat set,
gamespeed_trail, gamespeed), the playthrough gate (`scratchpad/gp/playthrough_gate.py`; OPTIONAL while it does not
exist -- a loud WARNING in the report), the map's own tests/fj feature tests, and msframe against the map's baseline.

THE REGISTRY (`REGISTRY`, below) is the one place a map's recorded build lives: its spread, census, labels, wad, heat
list, output, sha256, baseline, combat set, size cap and the gate commands derived from them. A map whose level has
not shipped is a placeholder marked NOT READY (its derived commands are shown by --dry-run, never run). When a level
ships, fill its row from docs/ship-gate.md and set `ready=True`; tests/host/test_build_episode.py holds E1M1's and
E1M2's rows against the recorded command lines in docs/ship-gate.md, so a row cannot drift from the record silently.

RULE 1. Every heavy step runs through `scripts/heavy.py <name> --prio 8 [--build] --log <file> -- <cmd>` -- the same
lock protocol (HEAVY.lock, O_EXCL, the priority queue, the RAM floor) every agent uses, at the integrator's priority 8
(docs/episode-plan.md 11, G2); the build step marks its lock `--build`, so other agents' `--light` work waits while it
assembles (G1). The lock is taken and released PER STEP, so the creator never holds it across a two-day run, and
nothing it runs overlaps anything else's heavy job. Do NOT wrap this script in heavy.py itself (it would wait forever
for the lock its parent holds): it refuses to start that way.

DISK (G8). A build REFUSES to start under 15 GB free on the drive the repo lives on (C:), and says how much is free;
after every build the map's generated program directory (`<out-dir>/generated_doom_<map>`, ~0.3-0.5 GB) is removed --
the .fjm, its label table and its census are kept.

THE ESTIMATE (G12). The plan's time comes from MEASURED step times: the step's own last run on this map (state.json),
else the same step measured on another map, else a constant marked "guess" -- the report says which, per step.

RESUMABLE. `<out-dir>/state.json` records every step's result under a KEY: the step's command and environment, the
source-tree hash (git: the tracked files under SRC_PATHSPECS, worktree edits included), the installed flipjump's
identity, the content hashes of the step's input files (wad, heat list, combat set), and -- for every step after the
build -- the built binary's sha256. A PASSED step whose key is unchanged is skipped; any changed input re-runs it
(the host tests' negative control). A failed, missing or never-run step always runs. `--force` re-runs everything.

OUTPUT: `<out-dir>/report.md` and `<out-dir>/report.json` (pass / fail per map per step, sizes, ms/frame, bindings,
hashes, wall times), rewritten after every step; each step's log in `<out-dir>/logs/`.

Never run with `python -O` (a skipped guard costs an assembly): refused, as is PYTHONOPTIMIZE in the environment.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import heavy  # noqa: E402  -- the lock protocol lives there and only there (LOCK, the RAM floor, O_EXCL)

from doomfj.mapprofile import profile  # noqa: E402

HEAVY_PY = ROOT / "scripts" / "heavy.py"
BASELINES = ROOT / "scratchpad" / "12m" / "msframe_baselines"      # msframe.BASELINES
EPISODE = ["E1M%d" % i for i in range(1, 10)]
PLAYTHROUGH = "scratchpad/gp/playthrough_gate.py"
ASSET_WAD = "assets/freedoom1.wad"
CAP_22 = 22_000_000                     # the owner's binding metric (gamespeed.SPEED_TARGET; B0's CAP-22)
PRIO = 8                                # the integrator's builds and gates (docs/episode-plan.md 11, G2)
MIN_DISK_GB = 15.0                      # a build refuses to start under this much free disk (G8)

# the source tree a result depends on (git pathspecs; tracked files, worktree edits included). The creator itself is
# excluded: its registry reaches every key through the commands, and editing its report code must not re-run a build.
SRC_PATHSPECS = ["src", "scripts", "scenarios", "tests/fj", "tests/fixtures", "scratchpad/*.py",
                 "scratchpad/gp/scenarios", ":(exclude)scripts/build_episode.py"]

# section 1b's line, shared by every map (the spread and the per-map paths go around it)
POOL_FLAGS = ["--pool-base", "0x80000000", "--span-bits", "0x7fffffe0", "--pin-state-cells", "--merge-aliases"]
BLOCK_FLAGS = ["--spread-min-count", "256", "--max-slot-ops", "512", "--pin-broken", "--width-buckets",
               "--one-pass-blocks"]
HEAT_P10 = "scratchpad/12m/heat_blocked27_p10.json.gz"

# the contract's order (docs/episode-plan.md 4); BLOCKING steps stop the map when they fail
STEP_ORDER = ["emit_check", "build", "sha256", "p2a", "m2_std", "m3", "hurt", "fight", "die", "b0",
              "gamespeed_trail", "gamespeed", "playthrough", "feature_tests", "msframe"]
BLOCKING = {"emit_check", "build"}
# rough minutes per step (read off the blocked63 / e1m2_r4 evidence logs): the plan's LAST resort, printed as "guess";
# a step measured by this creator (state.json) replaces it (G12)
EST_MIN = {"emit_check": 12, "build": 45, "sha256": 0, "p2a": 6, "m2_std": 12, "m3": 8, "hurt": 5, "fight": 30,
           "die": 5, "b0": 45, "gamespeed_trail": 15, "gamespeed": 20, "playthrough": 30, "feature_tests": 10,
           "msframe": 15}


@dataclass(frozen=True)
class MapSpec:
    map: str
    ready: bool
    not_ready: str = ""                 # why (a NOT READY row is a placeholder)
    wad: str | None = None              # None: build_blocked's default (E1M1's fixture) -- the recorded line has none
    spread: int | None = None           # 2 when the pool fits, else 1 (E1M2: 1); None = not decided yet
    heat: str = HEAT_P10
    combat_set: str = ""
    baseline: str = ""                  # msframe's saved baseline (mapprofile: shipped / shipped_<map>)
    size_cap_pct: float | None = 43.0   # gamespeed's size target; None = waived by the owner (size_note says so)
    size_note: str = ""
    trail_record: bool = False          # gamespeed_trail --record (writes scenarios/<map>/gamespeed.json)
    feature_tests: tuple = ()
    playthrough_skill: str | None = None
    build_min: int = 45
    # the RECORD (docs/ship-gate.md): what the creator's build must reproduce
    recorded_out: str = ""
    recorded_labels: str = ""
    recorded_census: str = ""
    recorded_sha256: str = ""           # full 64 hex; "" = none recorded (a new level: no rebuild check)
    recorded_ref: str = ""              # where the record lives


REGISTRY: dict[str, MapSpec] = {
    "E1M1": MapSpec(
        map="E1M1", ready=True, wad=None, spread=2, heat="scratchpad/12m/heat_e1m1_adopt.json.gz",
        combat_set="scratchpad/gp/scenarios/combat_scenarios_v10.json", baseline="shipped",
        size_cap_pct=43.0, trail_record=False,     # E1M1's trail record is gamespeed.BINARY_ENDS (no scenarios/e1m1)
        feature_tests=("tests/fj/test_key_latch.py", "tests/fj/test_keyboard_input.py",
                       "tests/fj/test_menu_screens.py", "tests/fj/test_skill_menu.py"),
        build_min=45,
        recorded_out="build/doom_e1m1_blocked65.fjm",
        recorded_labels="scratchpad/12m/atlas/blocked65.labels.tsv.gz",
        recorded_census="scratchpad/12m/_census_game.json.gz",
        recorded_sha256="3a2c9564adbfcb07a1378b6c0045ca2291246c4100abcafad68bae4af3815d3b",
        recorded_ref="docs/ship-gate.md 1 + 1b (blocked65, ship #2, 2026-10-28)"),
    "E1M2": MapSpec(
        map="E1M2", ready=True, wad="tests/fixtures/freedoom_e1m2.wad", spread=1,
        combat_set="scratchpad/gp/scenarios/combat_scenarios_e1m2_v1.json", baseline="shipped_e1m2",
        size_cap_pct=None, size_note="62.19% of 2^27 at r4 -- the owner: \"Size is ok\" (docs/ship-gate.md 5)",
        trail_record=True,
        feature_tests=("tests/fj/test_automap_fj.py", "tests/fj/test_change_sector_e1m2_fj.py",
                       "tests/fj/test_doors_e1m2_fj.py", "tests/fj/test_lights_fj.py",
                       "tests/fj/test_switch_tex_fj.py", "tests/fj/test_wall_scroll_fj.py",
                       "tests/fj/test_telefrag_fj.py", "tests/fj/test_teleport_fj.py",
                       "tests/fj/test_fog_pool_fj.py"),
        build_min=120,
        recorded_out="build/doom_e1m2_r4.fjm",
        recorded_labels="scratchpad/12m/atlas/e1m2_r4.labels.tsv.gz",
        recorded_census="scratchpad/12m/_census_game_e1m2_r4.json.gz",
        recorded_sha256="9a112139f3d35db3f71a9b2c0fb57a9e383b342fd2d42e776e072b97fbb57f45",
        recorded_ref="docs/ship-gate.md 5 (r4, 2026-10-18)"),
}
# M8 wave 1 + 2 (2026-10-29): the levels in their pipeline -- built and gated by this creator, NO recorded binary yet
# (no rebuild check until docs/ship-gate.md holds their block). Spread 2 where the pool fits (the small maps: E1M5 and
# E1M8 at 0.53 / 0.49 of E1M2's segs), else 1 (E1M3 / E1M4 / E1M9 used 79.6 / 83.5 / 77.6% of 2^27 at spread 1);
# size above 43% is the owner's (2026-10-24: "above 43% size is OK").
LEVEL_SPREAD = {"E1M3": 1, "E1M4": 1, "E1M5": 2, "E1M8": 2, "E1M9": 1}
for _m, _spread in LEVEL_SPREAD.items():
    _p = profile(_m)
    REGISTRY[_m] = MapSpec(
        map=_m, ready=True, wad=_p.wad, spread=_spread,
        combat_set="scratchpad/gp/scenarios/combat_scenarios_%s_v1.json" % _m.lower(), baseline=_p.baseline,
        size_cap_pct=None, size_note="the owner 2026-10-24: above 43% of 2^27 is OK", trail_record=True,
        playthrough_skill="easy", build_min=15, recorded_census=_p.census,
        recorded_ref="none yet: the level is in its pipeline (docs/episode-plan.md 4)")
for _m in [m for m in EPISODE[2:] if m not in LEVEL_SPREAD]:   # E1M6, E1M7: placeholders until their level ships
    _p = profile(_m)
    REGISTRY[_m] = MapSpec(
        map=_m, ready=False,
        not_ready="its level has not shipped (docs/episode-plan.md 4); fill this row from its docs/ship-gate.md block "
                  "(spread, census, labels, sha256, combat set, feature tests) and set ready=True",
        wad=_p.wad, spread=None, combat_set="scratchpad/gp/scenarios/combat_scenarios_%s_v1.json" % _m.lower(),
        baseline=_p.baseline, trail_record=True, recorded_census=_p.census)


# ── the plan ─────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Step:
    map: str
    name: str
    argv: list                          # the python script and its arguments (the interpreter is prepended)
    env: dict = field(default_factory=dict)
    heavy: bool = True                  # through heavy.py; False = computed in this process (sha256)
    build: bool = False                 # heavy.py --build (other agents' --light work waits) + the disk floor
    needs_fjm: bool = False             # its key includes the built binary's sha256
    inputs: tuple = ()                  # files whose CONTENT is part of the key
    optional: str | None = None         # a script that may not exist yet: MISSING is a WARNING, not a FAIL
    est_min: int = 0
    note: str = ""


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    return p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p)


def outputs(spec: MapSpec, out_dir: Path) -> dict:
    """the creator's own outputs for a map, all under <out-dir>: never the recorded binary's path (a rebuild must not
    overwrite the shipped binary that msframe's baseline names), the label table beside its binary, and the census in
    its own file (the one-pass build WRITES it; it is compared with the recorded one, never written over it)"""
    lo, rel = spec.map.lower(), _rel(out_dir)
    return {"fjm": "%s/doom_%s.fjm" % (rel, lo),
            "labels": "%s/doom_%s.labels.tsv.gz" % (rel, lo),
            "census": "%s/census_%s.json.gz" % (rel, lo),
            "logs": "%s/logs" % rel,
            "generated": "%s/generated_doom_%s" % (rel, lo)}    # build.py: out_fjm.parent / ("generated_" + stem)


def build_args(spec: MapSpec, out: str, labels: str, census: str) -> list:
    """section 1b's line for this map, in the recorded order"""
    where = [] if spec.wad is None else ["--wad", spec.wad, "--map", spec.map]
    spread = ["--spread", str(spec.spread if spec.spread is not None else "<2 or 1: decide at the level's build>")]
    return (["scratchpad/12m/build_labeled.py", "--labels", labels, "--", "game"] + where + ["--out", out]
            + POOL_FLAGS + spread + BLOCK_FLAGS + ["--counts-cache", census, "--pin-heat", spec.heat])


def plan_map(spec: MapSpec, out_dir: Path) -> list[Step]:
    o = outputs(spec, out_dir)
    m, fjm, lab, logs = spec.map, o["fjm"], o["labels"], o["logs"]
    env = {"DOOMFJ_MAP": m}
    bin_args = ["--fjm", fjm, "--labels", lab]
    wad = spec.wad or "tests/fixtures/freedoom_e1m1.wad"
    S = []

    def add(name, argv, **kw):
        S.append(Step(m, name, argv, dict(env), est_min=kw.pop("est_min", EST_MIN[name]), **kw))

    add("emit_check", ["scripts/emit_check.py", m, "--json", "%s/%s_emit_check.json" % (logs, m)],
        inputs=(wad, ASSET_WAD))
    add("build", build_args(spec, fjm, lab, o["census"]), inputs=(wad, ASSET_WAD, spec.heat), est_min=spec.build_min,
        build=True)
    add("sha256", [], heavy=False, needs_fjm=True, note="recorded %s" % (spec.recorded_sha256[:16] or "none"))
    add("p2a", ["scratchpad/gp/p2a_gate.py"] + bin_args, needs_fjm=True, inputs=(ASSET_WAD,))
    add("m2_std", ["scratchpad/m2_std_gate.py", "--map", m] + bin_args, needs_fjm=True, inputs=(ASSET_WAD,))
    add("m3", ["scratchpad/m3_gate.py", "--map", m] + bin_args, needs_fjm=True, inputs=(ASSET_WAD,))
    for g in ("hurt", "fight", "die"):
        add(g, ["scratchpad/gp/%s_gate.py" % g] + bin_args, needs_fjm=True, inputs=(ASSET_WAD,))
    add("b0", ["scratchpad/gp/b0_scenarios.py", "--file", spec.combat_set] + bin_args
        + ["--pixel-every", "1", "--proxy", "--json", "%s/%s_b0.json" % (logs, m)],
        needs_fjm=True, inputs=(spec.combat_set, ASSET_WAD))
    add("gamespeed_trail", ["scratchpad/12m/gamespeed_trail.py", "--map", m] + bin_args
        + (["--record"] if spec.trail_record else []), needs_fjm=True, inputs=(ASSET_WAD,))
    add("gamespeed", ["scratchpad/12m/gamespeed.py", "--map", m, "--fjm", fjm], needs_fjm=True, inputs=(ASSET_WAD,),
        note="size cap %s" % ("%.0f%%" % spec.size_cap_pct if spec.size_cap_pct is not None
                              else "WAIVED: " + spec.size_note))
    add("playthrough", [PLAYTHROUGH, "--map", m] + bin_args
        + (["--skill", spec.playthrough_skill] if spec.playthrough_skill else []),
        needs_fjm=True, inputs=(ASSET_WAD,), optional=PLAYTHROUGH)
    if spec.feature_tests:
        add("feature_tests", ["-m", "pytest", "-q", "-p", "no:cacheprovider"] + list(spec.feature_tests))
    base = BASELINES / ("%s.json" % spec.baseline)
    ms = ["scratchpad/12m/msframe.py", "--map", m, "--a", fjm]
    if spec.baseline and base.exists():
        try:
            bb = json.loads(base.read_text(encoding="utf-8")).get("binary", "")
        except ValueError:
            bb = ""
        warn = ("" if bb and (ROOT / bb).exists() else
                "WARNING: the baseline's binary %s is not on disk -- msframe --against refuses until it is" % bb)
        add("msframe", ms + ["--against", spec.baseline, "--note", "build_episode %s" % m], needs_fjm=True,
            note=warn)
    else:
        add("msframe", ms + ["--note", "build_episode %s (no baseline)" % m], needs_fjm=True,
            note="WARNING: no saved baseline '%s' -- measured alone, not compared" % spec.baseline)
    return S


# ── the judges: a step passes on its return code AND its own PASS line (a gate that printed nothing passed nothing) ─
def _num(s: str) -> int:
    return int(s.replace(",", ""))


MARKERS = {"p2a": r"^P2A GATE PASS", "hurt": r"^HURT GATE PASS", "fight": r"^FIGHT GATE PASS",
           "die": r"^DIE GATE PASS", "m2_std": r"^M2 STANDALONE GATE: PASS", "m3": r"^M3 GATE: PASS",
           "gamespeed_trail": r"^TRAIL\s.*: PASS", "emit_check": r"^EMITTED in ", "build": r"done in \d+s"}


def judge(step: Step, spec: MapSpec, rc: int, text: str) -> tuple[str, dict, str]:
    """-> (PASS | FAIL, metrics, why)"""
    met: dict = {}
    n = step.name
    if n in MARKERS:
        found = re.search(MARKERS[n], text, re.M) is not None
        if n == "emit_check" and "asserts ON" not in text:
            return "FAIL", met, "emit_check did not run with asserts ON"
        if n == "build":
            t = re.search(r"done in (\d+)s", text)
            if t:
                met["build_s"] = int(t.group(1))
        return ("PASS", met, "") if rc == 0 and found else (
            "FAIL", met, "rc %d, PASS line %s" % (rc, "found" if found else "MISSING"))
    if n == "b0":
        b = re.search(r"B0 BINDING \(mean \+ p80\)/2 over (\d+) runs: ([\d,]+)", text)
        if b:
            met["b0_runs"], met["b0_binding"] = int(b.group(1)), _num(b.group(2))
        if rc != 0 or not re.search(r"^B0 OK", text, re.M):
            return "FAIL", met, "rc %d or no 'B0 OK'" % rc
        if not b:
            return "FAIL", met, "no B0 BINDING line"
        if met["b0_binding"] > CAP_22:
            return "FAIL", met, "CAP-22: binding %s > %s" % (met["b0_binding"], CAP_22)
        return "PASS", met, ""
    if n == "gamespeed":
        sp = re.search(r"SPEED\s+BINDING \(mean\+p80\)/2:\s+([\d,]+) ops/frame.*?\b(PASS|OVER)", text)
        sz = re.search(r"SIZE\s+words\s*:\s*([\d,]+) = ([\d.]+)% of 2\^27", text)
        if sp:
            met["binding"] = _num(sp.group(1))
        if sz:
            met["size_words"], met["size_pct"] = _num(sz.group(1)), float(sz.group(2))
        if rc not in (0, 2) or not sp or not sz:      # 2 = a target OVER: judged below against THIS map's caps
            return "FAIL", met, "rc %d or no SPEED / SIZE line" % rc
        if sp.group(2) != "PASS" or met["binding"] > CAP_22:
            return "FAIL", met, "speed binding %s OVER" % met["binding"]
        if spec.size_cap_pct is not None and met["size_pct"] > spec.size_cap_pct:
            return "FAIL", met, "size %.2f%% > %.0f%%" % (met["size_pct"], spec.size_cap_pct)
        return "PASS", met, ("" if spec.size_cap_pct is not None else "size cap waived: " + spec.size_note)
    if n == "msframe":
        for arm, v in re.findall(r"^\s*(base|change|A)\s+median\s+([\d.]+) ms/frame", text, re.M):
            met[{"base": "base_ms", "change": "ms_frame", "A": "ms_frame"}[arm]] = float(v)
        v = re.search(r"VERDICT: (B FASTER|B SLOWER|NOT SEPARATED)", text)
        y = re.search(r"yardstick median ([\d.]+)G", text)
        if v:
            met["verdict"] = v.group(1)
        if y:
            met["yardstick_g"] = float(y.group(1))
        if rc != 0 or "ms_frame" not in met:
            return "FAIL", met, "rc %d or no median line" % rc
        if met.get("verdict") == "B SLOWER":
            return "FAIL", met, "B SLOWER against the baseline (a class S binary that is slower does not ship)"
        why = ("yardstick %.2fG < 3.5G: the box was not quiet" % met["yardstick_g"]
               if met.get("yardstick_g", 9.0) < 3.5 else "")
        return "PASS", met, why
    if n == "feature_tests":
        p = re.search(r"(\d+) passed", text)
        if p:
            met["passed"] = int(p.group(1))
        bad = re.search(r"\d+ (failed|errors?)\b", text)
        return ("PASS", met, "") if rc == 0 and p and not bad else ("FAIL", met, "rc %d" % rc)
    # playthrough (its documented contract: the return code)
    return ("PASS", met, "") if rc == 0 else ("FAIL", met, "rc %d" % rc)


# ── the inputs a result depends on ───────────────────────────────────────────────────────────────────────────────
def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def source_hash() -> str:
    """the tracked files under SRC_PATHSPECS as git sees them (index blobs) plus the bytes of every one edited in the
    worktree since -- so an uncommitted edit changes the hash too"""
    h = hashlib.sha256(_git("ls-files", "-s", "--", *SRC_PATHSPECS).encode())
    for rel in sorted(_git("diff", "--name-only", "--", *SRC_PATHSPECS).split()):
        p = ROOT / rel
        h.update(("\n%s " % rel).encode() + (file_sha(p).encode() if p.exists() else b"deleted"))
    return h.hexdigest()


def engine_id() -> str:
    """the installed flipjump: its checkout's HEAD (+ a digest of its edits), else its version"""
    spec = importlib.util.find_spec("flipjump")
    if spec is None or not spec.origin:
        return "flipjump: not installed"
    d = Path(spec.origin).parent
    try:
        head = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(d), "diff", "HEAD"], capture_output=True, check=True).stdout
        return "flipjump %s%s" % (head, "+" + hashlib.sha256(dirty).hexdigest()[:16] if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        from importlib.metadata import version
        return "flipjump %s at %s" % (version("flipjump"), d)


_SHA: dict = {}


def file_sha(p: Path) -> str:
    """content sha256 of a file (cached per (path, size, mtime) for one process)"""
    p = Path(p)
    st = p.stat()
    k = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    if k not in _SHA:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _SHA[k] = h.hexdigest()
    return _SHA[k]


def gz_content_sha(p: Path) -> str:
    """a census's CONTENT (the gzip header carries a timestamp)"""
    with gzip.open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@dataclass
class Context:
    src: str
    engine: str
    out_dir: Path


def step_key(step: Step, ctx: Context, spec: MapSpec) -> str:
    ins = {}
    for rel in step.inputs:
        p = ROOT / rel
        ins[rel] = file_sha(p) if p.exists() else "absent"
    fjm = ROOT / outputs(spec, ctx.out_dir)["fjm"]
    doc = {"map": step.map, "step": step.name, "argv": step.argv, "env": step.env, "src": ctx.src,
           "engine": ctx.engine, "inputs": ins,
           "fjm": (file_sha(fjm) if fjm.exists() else "absent") if step.needs_fjm else None,
           "recorded": spec.recorded_sha256 if step.name == "sha256" else None,
           "optional_present": (ROOT / step.optional).exists() if step.optional else None}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


# ── running ──────────────────────────────────────────────────────────────────────────────────────────────────────
class HeavyRunner:
    """every heavy step through scripts/heavy.py (the lock taken and released per step)"""

    def __init__(self, name: str, prio: int = PRIO):
        self.name, self.prio = name, prio

    def command(self, step: Step, log: str) -> list:
        return ([sys.executable, str(HEAVY_PY), self.name, "--prio", str(self.prio)] + (["--build"] if step.build else [])
                + ["--log", log, "--", sys.executable, *step.argv])

    def run(self, step: Step, log: str) -> int:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONOPTIMIZE"}
        env.update(step.env)
        return subprocess.call(self.command(step, log), cwd=ROOT, env=env)


def show(cmd: list, env: dict) -> str:
    def one(c):
        if c == sys.executable:
            return "python"
        p = Path(c)
        return _rel(p) if p.is_absolute() else c
    return " ".join(["%s=%s" % kv for kv in sorted(env.items())] + [shlex.quote(one(c)) for c in cmd])


def local_sha256(spec: MapSpec, ctx: Context) -> tuple[str, dict, str]:
    o = outputs(spec, ctx.out_dir)
    fjm = ROOT / o["fjm"]
    if not fjm.exists():
        return "FAIL", {}, "no binary at %s" % o["fjm"]
    met = {"sha256": file_sha(fjm), "bytes": fjm.stat().st_size, "recorded_sha256": spec.recorded_sha256 or None}
    cen = ROOT / o["census"]
    rec = ROOT / spec.recorded_census if spec.recorded_census else None
    if cen.exists() and rec is not None and rec.exists():
        met["census_identical"] = gz_content_sha(cen) == gz_content_sha(rec)     # information, not a verdict
    if not (ROOT / o["labels"]).exists():
        return "FAIL", met, "no label table at %s" % o["labels"]
    if not spec.recorded_sha256:
        return "PASS", met, "no recorded sha256: a NEW binary, not a rebuild check"
    met["identical"] = met["sha256"] == spec.recorded_sha256
    return ("PASS", met, "BYTE-IDENTICAL to the record") if met["identical"] else (
        "FAIL", met, "NOT byte-identical: %s != recorded %s" % (met["sha256"][:16], spec.recorded_sha256[:16]))


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def estimate(st: Step, state: dict) -> tuple[float, str]:
    """G12: (minutes, source) -- this map's measured run of the step, else the step measured on other maps (their
    mean), else the evidence-log constant, marked "guess". Only runs that got to the end (rc known) are measurements."""
    def measured(e):
        return bool(e) and e.get("rc") is not None and e.get("wall_s") is not None
    own = state.get(st.map, {}).get(st.name)
    if measured(own):
        return own["wall_s"] / 60, "measured"
    other = [(m, e[st.name]["wall_s"]) for m, e in sorted(state.items()) if m != st.map and measured(e.get(st.name))]
    if other:
        return sum(w for _, w in other) / len(other) / 60, "measured on %s" % "/".join(m for m, _ in other)
    return float(st.est_min), "guess"


def decide(step: Step, key: str, state: dict, force: bool) -> str:
    """RUN or SKIP: a step is skipped only when it PASSED under exactly this key"""
    prev = state.get(step.map, {}).get(step.name)
    if not force and prev and prev.get("status") == "PASS" and prev.get("key") == key:
        return "SKIP"
    return "RUN"


def run_episode(maps: list, ctx: Context, runner, *, force=False, steps=None, dry_run=False, out=print) -> dict:
    """the creator's loop. Returns the report document (also written to <out-dir>/report.{md,json} unless dry_run)."""
    state_path = ctx.out_dir / "state.json"
    state = load_state(state_path)
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "src": ctx.src, "engine": ctx.engine,
              "dry_run": dry_run, "disk_free_gb": round(free_disk_gb(), 1), "maps": {}}
    total_est, guessed, total_all = 0.0, 0.0, 0.0
    for m in maps:
        spec = REGISTRY[m]
        mrep = {"ready": spec.ready, "not_ready": spec.not_ready, "steps": {}, "recorded_ref": spec.recorded_ref}
        report["maps"][m] = mrep
        out("\n== %s%s" % (m, "" if spec.ready else "   NOT READY -- " + spec.not_ready))
        blocked = None
        for st in plan_map(spec, ctx.out_dir):
            if steps and st.name not in steps:
                continue
            key = step_key(st, ctx, spec)
            log_rel = "%s/%s_%s.log" % (outputs(spec, ctx.out_dir)["logs"], m, st.name)
            missing = bool(st.optional) and not (ROOT / st.optional).exists()
            if not spec.ready:
                verdict = "NOT READY"
            elif blocked:
                verdict = "NOT RUN"
            elif missing:
                verdict = "MISSING"
            else:
                verdict = decide(st, key, state, force)
            est, src = estimate(st, state)
            total_all += est
            if verdict == "RUN":
                total_est += est
                guessed += est if src == "guess" else 0
            cmd = show(runner.command(st, log_rel), st.env) if st.heavy else "(in this process) sha256 of the binary"
            out("  [%-9s] %-15s ~%4.0f min (%s)  key %s%s" % (verdict, st.name, est, src, key[:12],
                                                             ("  -- " + st.note) if st.note else ""))
            out("      %s%s" % ("# " if not spec.ready else "", cmd))
            if missing:
                out("      WARNING: %s does not exist yet -- the playthrough gate is NOT RUN (optional until it lands)"
                    % st.optional)
            entry = {"key": key, "command": cmd, "log": log_rel if st.heavy else None, "planned": verdict,
                     "est_min": round(est, 1), "est_source": src}
            if verdict == "SKIP":
                entry.update({k: v for k, v in state[m][st.name].items() if k != "key"})
                entry["skipped"] = True
            elif dry_run or verdict != "RUN":
                entry["status"] = verdict
                if verdict == "MISSING":
                    entry["why"] = "WARNING: %s is missing -- optional until it lands" % st.optional
                if verdict == "NOT RUN":
                    entry["why"] = "blocked by %s" % blocked
            else:
                entry.update(execute(st, spec, ctx, runner, log_rel))
                state.setdefault(m, {})[st.name] = {k: entry[k] for k in (
                    "key", "status", "rc", "metrics", "why", "wall_s", "finished", "log", "command")}
                save_json(state_path, state)
                out("      -> %s%s (%.0f s)" % (entry["status"], (" -- " + entry["why"]) if entry["why"] else "",
                                                 entry["wall_s"]))
                if entry["status"] != "PASS" and st.name in BLOCKING:
                    blocked = st.name
            mrep["steps"][st.name] = entry
            if not dry_run and verdict == "RUN":
                write_report(report, ctx)
        mrep["summary"] = summarize(m, mrep)
    report["est_min_to_run"], report["est_min_guessed"] = round(total_est, 1), round(guessed, 1)
    report["est_min_every_step"] = round(total_all, 1)
    report["verdict"] = episode_verdict(report)
    out("\n%splan: ~%.0f min (%.1f h) of steps to run; %.0f min of it a GUESS (steps never measured by this creator)"
        % ("DRY RUN -- " if dry_run else "", total_est, total_est / 60, guessed))
    out("every step of these maps from scratch (NOT READY ones included): ~%.1f h" % (total_all / 60))
    out("EPISODE: %s" % report["verdict"])
    if not dry_run:
        write_report(report, ctx)
    return report


def free_disk_gb() -> float:
    """free space on the drive the repo (and build/) lives on"""
    return shutil.disk_usage(ROOT.anchor or ROOT).free / 2 ** 30


def clean_generated(spec: MapSpec, ctx: Context) -> str:
    """G8: remove the map's generated program directory after its build -- only that directory, only by its own
    name; the .fjm, the label table and the census live elsewhere and are kept"""
    o = outputs(spec, ctx.out_dir)
    gen = ROOT / o["generated"]
    assert gen.name == "generated_doom_%s" % spec.map.lower() and gen.parent == (ROOT / o["fjm"]).parent, gen
    if not gen.is_dir():
        return "no generated dir"
    n = sum(f.stat().st_size for f in gen.rglob("*") if f.is_file())
    shutil.rmtree(gen)
    return "removed %s (%.2f GB)" % (_rel(gen), n / 2 ** 30)


def execute(st: Step, spec: MapSpec, ctx: Context, runner, log_rel: str) -> dict:
    t0 = time.time()
    if st.build:
        free = free_disk_gb()
        if free < MIN_DISK_GB:
            return {"key": step_key(st, ctx, spec), "status": "FAIL", "rc": None,
                    "metrics": {"disk_free_gb": round(free, 1)},
                    "why": "REFUSED to start: %.1f GB free on %s < %.0f GB (G8)" % (free, ROOT.anchor, MIN_DISK_GB),
                    "wall_s": 0.0, "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
    if st.heavy:
        log = ROOT / log_rel
        log.parent.mkdir(parents=True, exist_ok=True)
        rc = runner.run(st, log_rel)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        status, met, why = judge(st, spec, rc, text)
        if st.build:
            met["disk_free_gb"] = round(free, 1)
            met["cleaned"] = clean_generated(spec, ctx)
    else:
        rc = 0
        status, met, why = local_sha256(spec, ctx)
    # the key names the binary the step actually judged (the build just wrote it; a gate read it)
    return {"key": step_key(st, ctx, spec), "status": status, "rc": rc, "metrics": met, "why": why,
            "wall_s": round(time.time() - t0, 1), "finished": time.strftime("%Y-%m-%d %H:%M:%S")}


def summarize(m: str, mrep: dict) -> dict:
    st = mrep["steps"]

    def met(s):
        return (st.get(s) or {}).get("metrics") or {}
    stat = [v.get("status") for v in st.values()]
    if not mrep["ready"]:
        status = "NOT READY"
    elif "FAIL" in stat:
        status = "FAIL"
    elif stat and all(s == "PASS" for s in stat):
        status = "PASS"
    else:
        status = "INCOMPLETE"
    return {"status": status, "sha256": met("sha256").get("sha256"), "identical": met("sha256").get("identical"),
            "size_pct": met("gamespeed").get("size_pct"), "binding": met("gamespeed").get("binding"),
            "b0_binding": met("b0").get("b0_binding"), "ms_frame": met("msframe").get("ms_frame"),
            "base_ms": met("msframe").get("base_ms"), "verdict": met("msframe").get("verdict"),
            "wall_s": round(sum((v.get("wall_s") or 0) for v in st.values()), 1),
            "warnings": [k for k, v in st.items() if v.get("status") == "MISSING"]}


def episode_verdict(report: dict) -> str:
    if report["dry_run"]:
        return "DRY RUN (nothing run)"
    s = [v.get("summary", {}).get("status") for v in report["maps"].values()]
    if "FAIL" in s:
        return "FAIL"
    if "INCOMPLETE" in s:
        return "INCOMPLETE"
    if "NOT READY" in s:
        return "PASS for the ready maps; %d NOT READY" % s.count("NOT READY")
    return "PASS"


def write_report(report: dict, ctx: Context) -> None:
    for m, mrep in report["maps"].items():
        mrep["summary"] = summarize(m, mrep)
    save_json(ctx.out_dir / "report.json", report)

    def f(v, fmt="%s"):
        return "-" if v is None else fmt % v
    L = ["# The episode build (scripts/build_episode.py)", "",
         "started %s; source %s; %s; %.1f GB free on disk at the start" % (
             report["started"], report["src"][:16], report["engine"], report["disk_free_gb"]), ""]
    if "est_min_to_run" in report:
        L += ["plan at the start: ~%.1f h of steps to run, %.1f h of it a guess (never measured here)" % (
            report["est_min_to_run"] / 60, report["est_min_guessed"] / 60), ""]
    if "verdict" in report:
        L += ["**EPISODE: %s**" % report["verdict"], ""]
    L += ["| map | status | sha256 | byte-identical | size % of 2^27 | binding | B0 binding | ms/frame | wall |",
          "|---|---|---|---|---|---|---|---|---|"]
    for m, mrep in report["maps"].items():
        s = mrep["summary"]
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            m, s["status"], f(s["sha256"] and s["sha256"][:16]), f(s["identical"]), f(s["size_pct"], "%.2f"),
            f(s["binding"], "%d"), f(s["b0_binding"], "%d"), f(s["ms_frame"], "%.1f"),
            f(s["wall_s"] and round(s["wall_s"] / 60), "%s min")))
    warn = [(m, k) for m, mrep in report["maps"].items() for k in mrep["summary"]["warnings"]]
    if warn:
        L += ["", "**WARNING -- steps NOT RUN because their script is missing (optional until it lands): %s**"
              % ", ".join("%s %s" % w for w in warn)]
    for m, mrep in report["maps"].items():
        L += ["", "## %s%s" % (m, "" if mrep["ready"] else " -- NOT READY: " + mrep["not_ready"])]
        if mrep.get("recorded_ref"):
            L.append("record: %s" % mrep["recorded_ref"])
        if not mrep["ready"]:
            continue
        L += ["", "| step | status | wall | estimate | metrics / why | log |", "|---|---|---|---|---|---|"]
        for k, v in mrep["steps"].items():
            met = ", ".join("%s=%s" % kv for kv in sorted((v.get("metrics") or {}).items()))
            why = v.get("why") or ""
            L.append("| %s | %s%s | %s | %s | %s | %s |" % (
                k, v.get("status"), " (skipped: passed, inputs unchanged)" if v.get("skipped") else "",
                f(v.get("wall_s"), "%.0f s"), "%s min (%s)" % (v.get("est_min"), v.get("est_source")),
                "; ".join(x for x in (met, why) if x), v.get("log") or ""))
    (ctx.out_dir / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ── the guards ───────────────────────────────────────────────────────────────────────────────────────────────────
def refuse_optimized() -> str | None:
    if not __debug__ or sys.flags.optimize:
        return "REFUSED: build_episode runs with asserts ON -- never `python -O` (a skipped guard costs an assembly)"
    if os.environ.get("PYTHONOPTIMIZE"):
        return "REFUSED: PYTHONOPTIMIZE is set -- every step would run with asserts OFF; unset it"
    return None


def refuse_nested_lock() -> str | None:
    """run under heavy.py, every step would wait forever for the lock our own parent holds"""
    try:
        held = Path(heavy.LOCK).read_text()
    except OSError:
        return None
    m = re.search(r"pid (\d+)", held)
    if m and int(m.group(1)) == os.getppid():
        return ("REFUSED: run under heavy.py (%s) -- build_episode takes the lock itself, per step; run it directly"
                % held.strip())
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--maps", nargs="+", default=EPISODE, type=str.upper, choices=EPISODE, metavar="E1Mn")
    ap.add_argument("--steps", nargs="+", choices=STEP_ORDER, help="only these steps (the rest keep their state)")
    ap.add_argument("--force", action="store_true", help="re-run steps that passed under the same inputs")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; run nothing, write nothing")
    ap.add_argument("--out-dir", default="build/episode")
    ap.add_argument("--name", default="creator", help="the name heavy.py writes into the lock")
    ap.add_argument("--prio", type=int, default=PRIO, help="heavy.py's priority (the integrator's: 8)")
    a = ap.parse_args(argv)
    for why in (refuse_optimized(), None if a.dry_run else refuse_nested_lock()):
        if why:
            print(why, file=sys.stderr)
            return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    ctx = Context(src=source_hash(), engine=engine_id(), out_dir=out_dir)
    print("build_episode: maps %s; source %s; %s; out %s%s" % (" ".join(a.maps), ctx.src[:16], ctx.engine,
                                                              _rel(out_dir), "  (DRY RUN)" if a.dry_run else ""))
    rep = run_episode([m for m in EPISODE if m in a.maps], ctx, HeavyRunner(a.name, a.prio), force=a.force,
                      steps=set(a.steps) if a.steps else None, dry_run=a.dry_run)
    if a.dry_run:
        return 0
    print("report: %s" % _rel(out_dir / "report.md"))
    v = rep["verdict"]
    return 0 if v == "PASS" else (3 if v.startswith("PASS for the ready") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
