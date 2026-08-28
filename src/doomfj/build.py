"""H6 build system. `build` is the M0 hello-world smoke build; `build_doom` (M10/R0) integrates the
full E1M1 table set into one flat `.fjm` and measures the real address-span vs the flat limit.

`build_doom` generates every currently-buildable table — finesine trig (M6), reciprocal (M4/M5),
colormap + per-texture/per-flat texel tables + palette (M8, textures downscaled by the shared D5 lever),
the +4-offset deposit table (M5), the framebuffer, and the map geometry streams (M7; BSP-as-code
deferred to M12) — assembles them with a minimal mainline, and asserts `storage_mode == flat` with
`span_words < flat_limit` (R4). The full-E1M1 span feeds the DESIGN §1.2/§1.3 ledgers (R0)."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

import flipjump as fj
from flipjump.fjm.fjm_reader import Reader

from doomfj.config import Config, FLAT_MAX_WORDS
from doomfj.harness import W, FJM_LZMA_FAST, assemble_fjm, run_fjm
from doomfj.lut_generator import (
    generate_dispatch_table_fj, generate_offset_deposit_table_fj, generate_trig_idioms_fj,
)
from doomfj.mapcompiler import bake_bsp, compile_geometry_streams
from doomfj.tables import reciprocal_table
from doomfj.texturecompiler import compile_colormap, compile_flat, compile_palette, compile_texture
from doomfj.wad import WadFile
from doomfj.wall_renderer import (STATE_WIRE, TIER, WALL_NOISE, emit_wall_renderer,
                                  write_program_files)

_SRC_FJ = Path("src/fj")
# the fixed include set the runtime wall renderer assembles against (before the emitted main)
_RENDERER_INCLUDES = ["fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj"]
# ... plus these two for raster_mode="lines" (the shipping tier): the packed-byte ceiling/floor BAND
# lists pass-1 builds, and the 0x0B column-stream present that replaces the framebuffer raster.
_LINES_INCLUDES = ["plane_bands.fj", "stream_render.fj"]
# B0 (2026-08-18): the player sim. ⚠ LAST in the list -- fj top-level labels are global, so the
# ordered file list is equivalent to its concatenation and the order is the contract (R54). This is
# the same position m14_gate.py and scripts/walk_e1m1.py put it in.
_SIM_INCLUDES = ["sim.fj"]
# M5: the standalone tier's keyboard poll. BEFORE sim.fj, which stays last (R54).
_STANDALONE_INCLUDES = ["input.fj"]
# M5: the labels the self-reset must NOT restore. A hosted frame is handed its whole world state
# every frame, so restoring everything is exactly right; a standalone binary has no host, so the
# player's position and the four held-key flags are the program's own memory and have to survive.
# Everything else about the frame is still residue and is still restored. `emit_reset_part` checks
# each of these exists and is actually in the set -- see its docstring for why a hole is safe HERE
# and nowhere else.
# M3: `mode` joins them -- a mode that reset every frame would flicker between the two pictures.
# M2-R4: `kb_u` joins them for exactly the reason the other four are here -- it is a HELD key
# flag, written only by the keyboard device's up/down events, so a reset that cleared it would make
# the use key un-hold itself every frame.
STANDALONE_PERSIST = ("viewx", "viewy", "viewangle",
                      "kb_f", "kb_b", "kb_l", "kb_r", "kb_u", "mode")
# M2-R4: ...and the doors' own memory, when the build has doors. A door is world state in exactly
# the sense the player's position is -- height, direction, the step counter, the open-wait -- so a
# reset that restored them would slam every door shut every frame while the picture showed it
# opening. `duse`/`dbox` are NOT here: they are rewritten from scratch every frame, so they are
# ordinary residue and the reset should clear them.
# ⚠ Conditional, because `emit_reset_part` refuses a persist name the build has no label for -- and
# rightly: naming cells a doors=False program never declares is a typo, not a no-op.
DOOR_PERSIST = ("dstate", "ddir", "dsub", "dwait")
# V4 needs sprite lumps and a cut-down map wad has none, so sprite art comes from a full wad.
DEFAULT_SPRITE_WAD = "assets/freedoom1.wad"


def _resolve_sprite_wad(map_wad, sprite_wad):
    """The wad V4 takes SPRITE art from: an already-loaded `WadFile`, a path, or the default —
    falling back to the map wad, and RAISING if nothing in reach carries an S_START..S_END block.
    Explicit failure, not a silent `things=False`: a feature that quietly does not run is the bug
    class this renderer has paid for twice (the V4 courtyard, both BSP prunes)."""
    def _has_sprites(w):
        return "S_START" in w.names() and "S_END" in w.names()

    if isinstance(sprite_wad, WadFile):
        if not _has_sprites(sprite_wad):
            raise ValueError("things=True: the given sprite_wad has no S_START..S_END lumps")
        return sprite_wad
    if sprite_wad is not None and Path(sprite_wad).exists():
        w = WadFile.from_path(str(sprite_wad))
        if not _has_sprites(w):
            # CR-2026-08: an existing-but-spriteless path raises exactly like a loaded WadFile
            # does -- silently substituting the map wad here was the one hole in the
            # "explicit failure" rule this docstring itself states.
            raise ValueError(
                f"things=True: {sprite_wad!r} exists but has no S_START..S_END lumps")
        return w
    if _has_sprites(map_wad):
        return map_wad
    raise ValueError(
        f"things=True needs sprite art: {sprite_wad!r} is absent or carries no sprite lumps, and "
        f"the map wad has none either. Pass sprite_wad=<a full wad> or build with things=False.")


def build(fj_src="src/fj/hello.fj", out_fjm="build/hello.fjm", metrics="build/metrics.json") -> dict:
    m = assemble_fjm([fj_src], out_fjm)
    term = run_fjm(out_fjm)
    m["op_counter"] = term.op_counter
    m["storage_mode"] = str(term.storage_mode)
    # R4 guard: the program MUST run on the flat path.
    assert m["storage_mode"] == "flat", f"R4: storage_mode is {m['storage_mode']!r}, not flat"
    Path(metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(metrics).write_text(json.dumps(m, indent=2))
    return m


def _safe(prefix: str, name: str) -> str:
    """A flipjump-legal label from a WAD lump name (e.g. 'A-YELLOW' -> 'tex_A_YELLOW')."""
    return f"{prefix}_" + re.sub(r"[^0-9A-Za-z_]", "_", name)


def _span_words(fjm_path: Path) -> int:
    """The assembled program's flat address-span in words = max(segment_start + segment_length).
    Compared against flat_max_words: storage_mode flips flat->hybrid when the limit drops below it."""
    return max(s.segment_start + s.segment_length for s in Reader(fjm_path).memory_segments)


def build_doom(wad_path, mapname="E1M1", *, cfg=None, out_fjm, generated_dir,
               texture_subset=None, flat_subset=None, lights=32, flat_max_words=None) -> dict:
    """Generate + assemble the E1M1 table set into one `.fjm`; return metrics incl. storage_mode,
    span_words, headroom, and per-category entry counts. Asserts flat + span < limit (R4).

    `texture_subset`/`flat_subset` (names) keep the committed test fast; pass None to integrate the
    whole level (the R0 measurement). `lights` is the colormap light-row count (32 = full)."""
    cfg = cfg or Config()
    wad = WadFile.from_path(wad_path)
    factor = cfg.TEXTURE_DOWNSCALE
    limit = flat_max_words or FLAT_MAX_WORDS
    gen = Path(generated_dir)
    gen.mkdir(parents=True, exist_ok=True)

    tex_names = texture_subset if texture_subset is not None else [d.name for d in wad.texture_defs()]
    flat_names = (flat_subset if flat_subset is not None
                  else [l.name for l in wad.lumps_between("F_START", "F_END")])

    entry_counts: dict[str, int] = {}

    # ── the mainline: hex/ptr/stack init + halt. Tables occupy span whether or not they're executed. ──
    main = "stl.startup_and_init_all\nstl.loop\n"

    # finesine (M6): the per-result-nibble trig table + read_sin/read_cos
    trig = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    entry_counts["finesine"] = cfg.TRIG_N

    # reciprocal / scale (M4 value kernel -> M5 dispatch): 16^3 distance buckets (kills the wall divide)
    recip_vals = reciprocal_table(cfg.TRIG_N, 16, 32)
    recip = generate_dispatch_table_fj("reciprocal", recip_vals, index_nibbles=3, result_nibbles=8)
    entry_counts["reciprocal"] = cfg.TRIG_N

    # colormap (M8): (light<<8 | colour) -> lit byte
    colormap = compile_colormap("colormap", wad, lights=lights, over_align=False)
    entry_counts["colormap"] = lights * 256

    # +4-offset deposit table (M5, D3)
    deposit = generate_offset_deposit_table_fj("deposit")
    entry_counts["deposit"] = 256

    # textures + flats (M8), downscaled by the shared D5 lever (factor)
    tex_parts, total_texels = [], 0
    defs = {d.name: d for d in wad.texture_defs()}
    for name in tex_names:
        tex_parts.append(compile_texture(_safe("tex", name), wad, name, downscale=factor))
        d = defs[name]
        total_texels += (d.width // factor) * (d.height // factor)
    for name in flat_names:
        tex_parts.append(compile_flat(_safe("flat", name), wad, name, downscale=factor))
        total_texels += (64 // factor) * (64 // factor)
    entry_counts["textures"] = total_texels
    entry_counts["texture_count"], entry_counts["flat_count"] = len(tex_names), len(flat_names)

    # palette device data (M8) + framebuffer (packed bytes) + map geometry streams (M7)
    palette = compile_palette("palette", wad)
    entry_counts["palette"] = cfg.NCOLORS
    framebuffer = f"framebuffer: hex.vec {2 * cfg.FB_SIZE}\n"   # FB_SIZE packed bytes (2 nibbles each)
    geometry = compile_geometry_streams(wad, mapname)

    # ── write the assemble list (mainline first = entry at addr 0) ──
    files = {
        "fj_consts.fj": cfg.emit_fj_consts(gen / "fj_consts.fj").read_text(encoding="utf-8"),
        "main.fj": main,
        "tables.fj": "\n".join([trig, recip, colormap, deposit]),
        "graphics.fj": "\n".join(tex_parts + [palette, framebuffer]),
        "map.fj": geometry,
    }
    paths = []
    for fname, text in files.items():
        p = gen / fname
        if fname != "fj_consts.fj":   # already written by emit_fj_consts
            p.write_text(text, encoding="utf-8")
        paths.append(p)

    out = Path(out_fjm)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False,
                lzma_fast=FJM_LZMA_FAST)
    assemble_seconds = round(time.perf_counter() - t, 3)
    term = fj.run(out, print_time=False, print_termination=False, flat_max_words=limit)

    span = _span_words(out)
    metrics = {
        "map": mapname,
        "downscale": factor,
        "storage_mode": str(term.storage_mode),
        "span_words": span,
        "flat_limit": limit,
        "headroom": round(limit / span, 3) if span else None,
        "fjm_bytes": out.stat().st_size,
        "assemble_seconds": assemble_seconds,
        "entry_counts": entry_counts,
    }
    # R4: no silent paged-mode fallback; the program must fit flat under the limit.
    assert metrics["storage_mode"] == "flat", f"R4: storage_mode {metrics['storage_mode']!r} != flat"
    assert span < limit, f"R4: span {span} >= flat limit {limit}"
    return metrics


# The M1 restore set SHIPS WITH THE PACKAGE. It is the default so the path is not re-typed at
# every call site (and so an installed copy uses the same one the tests do).
DEFAULT_RESTORE_SET = Path(__file__).resolve().parent / "data" / "m1_restore_set.json.gz"
# M5: the standalone tier is a DIFFERENT PROGRAM (a keyboard prologue instead of the wire, no magic
# byte, baked thing bindings), so it has its own set -- derived from the certified one by
# scratchpad/m5_setfile.py, never re-measured. Pairing a set with the wrong program is caught by the
# layout fingerprint, but loudly and 20 minutes in; resolving it by tier here means it cannot happen.
STANDALONE_RESTORE_SET = Path(__file__).resolve().parent / "data" / "m5_restore_set.json.gz"


def build_wall_renderer(wad_path, mapname="E1M1", *, cfg=None, out_fjm, generated_dir,
                        flat_max_words=None, sky=True,
                        steps=True, things=True, sprite_wad=DEFAULT_SPRITE_WAD,
                        stack_steps=True, bbox_cull=True, deg=True,
                        player_sim=True, collide=True,
                        moving_things=True, standalone=False, menu=False, menu_entries=None,
                        menu_selected=0,
                        sector_heights=None, doors=False,
                        self_reset=False, restore_set=DEFAULT_RESTORE_SET) -> dict:
    """M12rr — wire the OPTIMIZED runtime wall renderer into a shipped `.fjm` (replacing the M10 halt-only
    `build_doom` mainline for the renderer path). Emits the renderer via the SHARED
    `doomfj.wall_renderer.emit_wall_renderer` — the SAME emitter the byte-exact golden test renders through
    (R6 single source) — so every space optimization (M12oo pass-2 trampoline, M12pp/qq xor_by + xor-involution
    walk) ships here for free. Assembles against the renderer include set, then R0-gates: assert
    `storage_mode == flat` and `span < limit`. The renderer's fully-unrolled pass-2 + BSP walk push the span
    past the 2**23 default, so pass a RAISED `flat_max_words` (`config.RENDER_FLAT_MAX_WORDS`, 2**27
    since 2026-08-18 -- the M14 tier is 1.6% over 2**26) per DESIGN §1.2 (RAM-only cost). The
    viewpoint `(vx,vy,va)` is read from stdin at runtime; the gate run feeds an invalid byte so the input
    parser jumps to `bad:` and halts immediately (the span/storage_mode are load-time, so no full render is
    needed for the gate — the golden test does the byte-exact render).

    **The defaults are the SHIPPING tier**, i.e. what `scripts/walk_e1m1.py` puts on screen: the lines
    raster with W1R walls + FT1 floors + rung-3a `plane_near`, all four VISUAL FEATURES
    (V1 `wall_noise` grain, V2 `sky`, V3 `steps` faces, V4 `things` sprites) ON, and V5 `stack_steps`
    + the `bbox_cull` wedge subtree cull + the `deg` degradation package ON.

    ⚠ B0 (2026-08-18) — AND THE SHIPPED ARTIFACT NOW RUNS THE SIM. `state_wire="bin"`,
    `player_sim`, `collide` and `moving_things` default ON here because `scripts/walk_e1m1.py`
    turns them on, and A0.1's whole point is that the artifact shipped, the artifact certified and
    the artifact a human looks at are ONE program. Shipping a renderer while the walker ships a
    game would have re-created the divergence A0.1 just closed. The binary reads a BINARY wire
    (a decimal feed halts it after ~200 ops) and it is the M14 tier, ~68.2M span-words — which is
    why `config.RENDER_FLAT_MAX_WORDS` had to go to 2**27 (DESIGN §1.2).

    ⚠ CR-2026-08 (IN-3, A0.1) — THIS SENTENCE USED TO BE FALSE, which is why it is now spelled out
    flag by flag. `stack_steps`, `bbox_cull` and `deg` were never passed here at all and defaulted
    OFF in the emitter, and `wall_mode` was WPX where the walker uses W1R — so THREE entry points
    built THREE different renderers: the artifact shipped, the artifact certified by
    `scratchpad/deg_gate.py`, and the artifact a human actually looked at. Optimizing or certifying
    any one of them said little about the others. If you add an emit-shaping keyword, add it HERE
    and to the walker in the same commit, or the divergence comes straight back. Every one is byte-exact
    against the oracle (`tests/fj/test_visual_features.py`); before this they were emitter keywords that
    only the walker and that test ever passed, so the shipped binary rendered a strictly older picture
    than the project's own screenshots. The older tiers stay reachable by keyword
    (`raster_mode="framebuffer", floor_mode="textured", wall_mode="textured"` is the pre-lines build).

    ⚠ M5 `standalone=True` — THE NO-HOST TIER. Same renderer, same sim, but the frame reads the
    KEYBOARD device instead of a wire, the player start is baked into `viewx`/`viewy`/`viewangle`,
    the thing bindings and visibility bake instead of arriving per frame, nothing is echoed back,
    and the screen is initialized with the stock 8-byte command the plain `fj` CLI's device wants.
    With `self_reset=True` that is a complete game in one file: `fj <out> --io pc`. It needs its own
    restore set (resolved above) because the reset must LEAVE the view state and the held-key flags
    alone — `STANDALONE_PERSIST` — which is the one place a hole in that set is intended.

    ⚠ V4 needs SPRITE ART, and a cut-down map wad has no sprite lumps at all — hence `sprite_wad`,
    which defaults to `assets/freedoom1.wad` and falls back to the map wad when that file is absent.
    If neither carries sprites this RAISES rather than quietly dropping the feature: a silently
    not-running feature is exactly the class of bug that cost this repo the most (docs/opt-experiments.md).
    """
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    cfg = cfg or Config()
    wad = WadFile.from_path(wad_path)
    limit = flat_max_words or FLAT_MAX_WORDS
    gen = Path(generated_dir); gen.mkdir(parents=True, exist_ok=True)
    spr = _resolve_sprite_wad(wad, sprite_wad) if things else None

    parts = emit_wall_renderer(wad, mapname, cfg, sky=sky, steps=steps, things=things,
                               sprite_wad=spr, stack_steps=stack_steps, bbox_cull=bbox_cull,
                               deg=deg, player_sim=player_sim,
                               collide=collide, moving_things=moving_things,
                               standalone=standalone, menu=menu, menu_entries=menu_entries,
                               menu_selected=menu_selected,
                               sector_heights=sector_heights, doors=doors,
                               return_parts=True)
    consts = cfg.emit_fj_consts(gen / "fj_consts.fj")
    # The emitted program goes out as SEPARATE files: the huge machine-written regions (LUT and
    # dispatch tables, per-seg constant blocks, the BSP walk, the baked banks) no longer share a
    # file with the ~50-line program. ⚠ Order is load-bearing -- see write_program_files.
    prog = write_program_files(parts, gen, mapname)
    includes = (_RENDERER_INCLUDES + _LINES_INCLUDES
                + (_STANDALONE_INCLUDES if standalone else [])   # M5: kb.poll
                + (_SIM_INCLUDES if player_sim else []))   # B0: sim.fj LAST (R54)
    paths = [consts] + [_SRC_FJ / f for f in includes] + prog

    out = Path(out_fjm); out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    reset_info = None
    if self_reset:
        # M1 -- the program restores itself and LOOPS, so the host never reloads the image.
        # TWO PASSES, and the second is not a re-run: pass 1 exists only to learn where every cell
        # landed. The reset bakes those addresses (it must -- most of the dirty set is macro-local
        # scratch, which fj cannot name from outside its macro), is APPENDED as a new last part,
        # and patches the frame tail size-neutrally, so pass 2 has to place every restored cell at
        # the same address. That is ASSERTED below, not assumed: a reset writing shifted addresses
        # does not produce a wrong pixel, it produces a different program.
        assert restore_set, "self_reset=True requires restore_set (see docs/handoff-m1-reset.md)"
        if standalone and Path(restore_set) == DEFAULT_RESTORE_SET:
            restore_set = STANDALONE_RESTORE_SET      # the tier's own set, see its definition
        from doomfj import selfreset
        from doomfj.fastrun import FjmRunner, _fjcore
        # ⚠ m1_reset.fj goes LAST, AFTER the emitted parts -- not into `includes`. A macro-expansion
        # label is named `f<file>:l<line>:...`, so inserting a file anywhere earlier renumbers every
        # label in every file after it, and the restore set (which names labels) stops resolving.
        # Measured: adding it to the includes renamed 200 of the set's labels and the loader
        # refused, exactly as it should. A file that only holds a `def` emits no ops, so appending
        # it moves no address.
        paths = paths + [_SRC_FJ / "m1_reset.fj"]
        # M5/M2-R4: the labels the reset must leave alone -- computed ONCE and used both to build
        # the reset and to report it.
        _persist = ((STANDALONE_PERSIST + (DOOR_PERSIST if doors else ()))
                    if standalone else ())
        labels1 = selfreset.capture_labels(paths, out, lzma_fast=FJM_LZMA_FAST)
        r1 = FjmRunner(out, flat_max_words=limit)
        core1 = _fjcore.Memory(r1.width, flat_max_words=r1.flat_max_words)
        for _s, _n in r1._segments:
            core1.add_segment(_s, _n)
        for _st, _v in r1._runs:
            core1.set_words(_st, _v)
        # view_w/nss are the SECOND source the byte-array cell counts are checked against; the
        # first is each array's label extent in this build's own table. Both must agree, so a
        # resolution or map change cannot silently nibble-clear a byte cell (see selfreset.py).
        nss = len(bake_bsp(wad, mapname).subsectors)
        part, n_nib, n_byte = selfreset.emit_reset_part(
            gen, labels1, core1.get_word, restore_set, cfg.VIEW_W, nss, mapname,
            persist=_persist)
        # Snapshot pass 1's pristine words at the baked addresses BEFORE releasing the image -- the
        # value check below needs them and re-loading an 85M-word image to get them would not.
        # check_layout=False: emit_reset_part above already resolved this set against labels1 WITH
        # the fingerprint on, so re-checking it here would be redundant, not weaker. (CR round 9
        # noted the round-8 fix justified the OTHER opt-out and left this one bare -- the finding
        # was "correct but unjustified in the code", and a new bare site is the same defect.)
        _s1 = selfreset.load_restore_set(restore_set, labels1, check_layout=False)
        _v1 = {x: core1.get_word(x) for x in _s1}
        # A value check over an empty snapshot returns "no differences". Make that impossible to
        # confuse with a real clean result.
        assert _v1, "M1 self-reset: the pristine snapshot is empty -- the value check would be vacuous"
        pristine1 = _v1.get
        del core1, r1
        paths = paths + [part]
        labels2 = selfreset.capture_labels(paths, out, lzma_fast=FJM_LZMA_FAST)
        moved = selfreset.verify_labels_unchanged(labels1, labels2, restore_set)
        assert not moved, ("M1 self-reset REFUSED: %d baked addresses moved between passes, e.g. %s"
                           % (len(moved), sorted(moved)[:3]))

        # ...and that the VALUES at those addresses are the same in both assemblies. The reset bakes
        # `hex.set 1, addr, v` with v read from PASS 1; if pass 2 puts a different value there, the
        # reset restores the wrong one -- silently, and pixel-identically until that cell matters.
        # Addresses and values are two separate claims and only the first was ever checked (CR-8).
        r2 = FjmRunner(out, flat_max_words=limit)
        core2 = _fjcore.Memory(r2.width, flat_max_words=r2.flat_max_words)
        for _s, _n in r2._segments:
            core2.add_segment(_s, _n)
        for _st, _v in r2._runs:
            core2.set_words(_st, _v)
        bad = selfreset.verify_values_unchanged(restore_set, labels2, pristine1, core2.get_word)
        del core2, r2
        assert not bad, ("M1 self-reset REFUSED: %d baked cells hold a DIFFERENT pristine value in "
                         "pass 2, e.g. %s -- the reset would restore pass 1's value"
                         % (len(bad), bad[:3]))
        reset_info = {"nibble_cells": n_nib, "byte_cells": n_byte,
                      # ⚠ THE SAME TUPLE the reset was built from, not a second expression that
                      # says the same thing. It WAS a second expression, and the moment
                      # DOOR_PERSIST arrived the two disagreed: the binary persisted 13 labels and
                      # this reported 9, so the metrics file said the doors reset every frame while
                      # the program kept them. A number that describes the build has to come from
                      # the build.
                      "persisted_labels": list(_persist),
                      "restore_set": str(restore_set), "labels_moved_in_set": 0,
                      "values_changed_in_set": 0, "baked_cells_value_checked": len(_v1),
                      "view_w": cfg.VIEW_W, "subsectors": nss}
    else:
        fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False,
                    lzma_fast=FJM_LZMA_FAST)
    assemble_seconds = round(time.perf_counter() - t, 3)
    term = fj.run(out, io_device=FixedIO(b"q\n"), print_time=False, print_termination=False,
                  flat_max_words=limit)                    # 'q' is not a digit -> input parser -> bad: -> halt
    span = _span_words(out)
    metrics = {
        "map": mapname, "downscale": cfg.TEXTURE_DOWNSCALE,
        "storage_mode": str(term.storage_mode), "span_words": span, "flat_limit": limit,
        "headroom": round(limit / span, 3) if span else None,
        "fjm_bytes": out.stat().st_size, "assemble_seconds": assemble_seconds,
        # the tier string is a CONSTANT now: W1R walls, FT1 floors, the lines raster. It stays a
        # string because every gate log and metrics file in the repo prints it -- but it comes FROM
        # the emitter (R6), not from a copy of it living here.
        "tier": TIER,
        # CR-2026-08 (IN-3, A0.1): the metrics used to describe only FOUR of the emit-shaping flags,
        # so the three that had silently diverged (stack_steps/bbox_cull/deg) were invisible to every
        # consumer of metrics.json AND to the R4 gate below. A flag that shapes the picture is now
        # reported; add new ones here in the same commit that adds them to the signature.
        # `wall_noise` is a CONSTANT now (V1's grain is what the W1R wall is made of), but every
        # gate log and metrics file reads this key, so it keeps reporting.
        "features": {"wall_noise": WALL_NOISE, "sky": sky, "steps": steps, "things": things,
                     "stack_steps": stack_steps, "bbox_cull": bbox_cull, "deg": deg,
                     # B0: the sim half. Reported for the same reason as the rest -- a flag that
                     # shapes the artifact must be visible in metrics.json, or the next divergence
                     # is invisible again.
                     "player_sim": player_sim, "collide": collide,
                     # the wire is a CONSTANT now ("dec" retired with the flag), but every gate
                     # log and metrics file in the repo reads this key, so it keeps reporting.
                     "moving_things": moving_things, "state_wire": STATE_WIRE,
                     # M1: the program self-resets and loops -- one run renders many frames.
                     "self_reset": self_reset,
                     # M5: no host in the loop -- the keyboard device drives it and the view state
                     # survives the reset.
                     "standalone": standalone,
                     # M2: a door override MOVES PIXELS, so it belongs in the guard the same as any
                     # other picture-shaping input. Reported as a bool: the heights themselves are
                     # a per-sector dict, and what the guard needs to catch is a build that has
                     # them at all. (CR PR#78, R6.)
                     "sector_heights": bool(sector_heights),
                     # M2-R3: the runtime door. Picture-shaping and opt-in, so it belongs in
                     # the exact-equality features guard for the same reason sector_heights
                     # does -- a tier flag that can arrive unnoticed is the CR-2026-08 miss.
                     "doors": bool(doors),
                     # M3: the menu is a second frame producer chosen by a persisted cell
                     "menu": menu},
        "self_reset": reset_info,
    }
    assert metrics["storage_mode"] == "flat", f"R4: storage_mode {metrics['storage_mode']!r} != flat"
    assert span < limit, f"R4: span {span} >= flat limit {limit}"
    return metrics


def build_unroll_frame(wad_path, texname, *, cfg=None, light, width=None, count=None, step, frac0=0,
                       downscale=None, lights=None, out_fjm, generated_dir, run=True):
    """M11c (F5 / D2b — the D2 bake-off): assemble (+ optionally run) the FULL-UNROLL renderer —
    `rep(width, x) frame.column ... rep(count, row) frame.pixel ...` writing each pixel DIRECTLY into its
    hex.vec2 framebuffer cell (no deposit, §2.1). With `run=True` it also presents over the 0x06 register
    device and captures the frame headless (pixel_indices + per-frame sha256 + op_counter/per_pixel_ops).

    `run=False` assembles ONLY — returns assemble_seconds + fjm_bytes + span_words (the R-2/R-4 gate
    numbers) without executing. Executing a full 160x100 frame is ~24M ops through the headless
    interpreter (minutes); the gate needs only the ASSEMBLE time + span, and ops/frame is extrapolated
    from a small run's per_pixel_ops — so the full-scale measurement uses run=False.

    `width`/`count` default to the full viewport (VIEW_W x VIEW_H = the bake-off scale); pass smaller for
    the fast committed golden. The synthetic frame splats texcol = x % texwidth across the screen at a
    constant `light`/`step` (matching the oracle). The two per-pixel tables are over-aligned (§2.1)."""
    cfg = cfg or Config()
    factor = downscale if downscale is not None else cfg.TEXTURE_DOWNSCALE
    width = width if width is not None else cfg.VIEW_W
    count = count if count is not None else cfg.VIEW_H
    wad = WadFile.from_path(wad_path)
    defs = {d.name: d for d in wad.texture_defs()}
    texheight = defs[texname].height // factor
    texwidth = defs[texname].width // factor
    lights = lights if lights is not None else max(32, light + 1)
    gen = Path(generated_dir)
    gen.mkdir(parents=True, exist_ok=True)

    consts = cfg.emit_fj_consts(gen / "fj_consts.fj")
    # §2.1: over-align both very-hot per-pixel dispatch tables (texture + colormap).
    tex = compile_texture("tex", wad, texname, over_align=True, downscale=factor)
    cm = compile_colormap("cm", wad, lights=lights, over_align=True)
    palette = compile_palette("palette", wad)

    stride = cfg.W
    render = []
    for x in range(width):
        render.append(f"frame.setup_col {(x % texwidth) * texheight}, {light}, {step}, {frac0}")
        for row in range(count):
            render.append(f"frame.pixel framebuffer + {2 * (row * stride + x)}*dw")
    main = "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        *render,
        "present.set_palette palette",
        "present.update_screen_reg framebuffer",
        "stl.loop",
        "pixel_leaf:",                                # the shared per-pixel leaf (emitted ONCE)
        "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",   # register form: 2 ops/pixel (low, high nibble)
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {texheight - 1}",
        "pixel_ret: ;0",                             # the stl.fcall return-register (one op)
        tex, cm, palette,
    ])
    (gen / "main.fj").write_text(main, encoding="utf-8")

    paths = [consts, Path("src/fj/present.fj"), Path("src/fj/frame_render.fj"), gen / "main.fj"]
    out = Path(out_fjm)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False,
                lzma_fast=FJM_LZMA_FAST)
    assemble_seconds = round(time.perf_counter() - t, 3)

    pixels = width * count
    m = {
        "span_words": _span_words(out),
        "assemble_seconds": assemble_seconds,
        "fjm_bytes": out.stat().st_size,
        "width": width,
        "count": count,
        "pixels": pixels,
    }
    if not run:
        return m

    from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
    screen = InMemoryScreen()
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False)
    m.update({
        "storage_mode": str(term.storage_mode),
        "op_counter": term.op_counter,
        "per_pixel_ops": term.op_counter // pixels if pixels else 0,
        "pixel_indices": screen.pixel_indices,
        "frame_hash": screen.frame_hashes[-1][1] if screen.frame_hashes else None,
    })
    return m


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
