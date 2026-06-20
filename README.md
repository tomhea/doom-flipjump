# DOOM on FlipJump

DOOM, compiled to a single self-modifying [FlipJump](https://esolangs.org/wiki/FlipJump)
program. This repo holds the **host toolchain** (WAD/LUT/map/texture compilers, a reference
model, the build, and a probe harness) that generates and assembles the `.fjm`.

See [`DESIGN.md`](DESIGN.md) for the full design and the milestone ladder (§10). The project
is built as a ladder of small, CR-reviewed milestones — see [`docs/cr-rules.md`](docs/cr-rules.md).

## Setup

```bash
pip install -e ".[dev]"      # flipjump[io] + pillow + pytest; Python 3.10–3.13
```

## Build

```bash
bash scripts/build.sh        # assembles src/fj/hello.fj -> build/hello.fjm, runs it,
                             # writes build/metrics.json (storage_mode, op_counter, fjm_bytes, assemble_seconds)
```

## Test

```bash
bash scripts/test.sh         # pytest; exits non-zero on any failure
```

## Flat vs. paged (`--flat-max-words`)

FlipJump runs in **flat** storage mode: the whole program/RAM span is one contiguous array.
The build **asserts `storage_mode == flat`** (CR rule R4) — a silent fall-back to paged mode
would mean the span outgrew the flat limit. The default flat limit is `2²³` span-words (≈64 MB
at `w=32`); when the address span grows (textures, framebuffer, levels — see `DESIGN.md` §1.2/§3.3)
raise it via `flat_max_words=` (harness) / `--flat-max-words` / `FLIPJUMP_FLAT_MAX_WORDS`.

M0 ships no game logic — it only proves the TDD/build/probe pipeline end-to-end.
