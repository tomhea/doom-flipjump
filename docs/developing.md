# Developing

This page is for people who want to build the program or change the toolchain. To *play*, the
[README](../README.md) is enough.

## Setup

```bash
git clone https://github.com/tomhea/doom-flipjump && cd doom-flipjump
pip install -e ".[dev]"            # flipjump[io], pillow, pytest; Python 3.10 to 3.13
bash scripts/fetch_freedoom.sh     # the Freedoom WADs into assets/ (gitignored, ~28 MB each)
```

The game build needs flipjump **1.5.1** (the native engine, the 0x0B screen device, the blocking
pass). Until 1.5.1 is on PyPI, install it from its branch:

```bash
pip install "flipjump[io] @ git+https://github.com/tomhea/flipjump@1.5.1"
```

## Smoke test, tests

```bash
bash scripts/build.sh              # assembles src/fj/hello.fj -> build/hello.fjm, runs it, writes build/metrics.json
bash scripts/test.sh               # pytest; exits non-zero on any failure
python -m pytest tests/host -q     # host logic, minutes; check the "N deselected" line
python -m pytest tests/host -m slow   # the shipped build path, excluded by default
```

The FlipJump harnesses under `tests/fj` run real programs through the interpreter and are what CI
runs, in sharded jobs. Each one is a tiny FlipJump program plus the Python that expects its exact
output, with a mutant that must fail.

## Building the game

The exact build line of the shipped binary, its hashes and the gate it passed are in
[ship-gate.md](ship-gate.md), section 1b. Two warnings before you run it:

- **One heavy build at a time.** The assembler peaks near 10 GB of RAM; two builds at once have
  killed each other silently.
- **It takes a while.** Emission is several minutes, assembly several more, and the blocking pass
  that places the lookup tables needs the counts cache named in the build line.

## Flat vs. paged storage

The interpreter runs the program in **flat** storage: the whole address span is one contiguous
array, 8 bytes per word of span. The game's span is about 119 million words. A release `doom.fjm`
carries the flat-memory flag and the pc io mode in its header (flipjump 1.5.1's `run_flags` and
`io_mode`, set at assembly), so `fj --run doom.fjm` allocates the flat window by itself. A file
assembled without those fields needs `fj --run file.fjm --io pc --flat-max-words 134217728`; with a
smaller limit the interpreter falls back to paged storage, which is correct but much slower. The
default limit is 2^23 words, also settable with the `FLIPJUMP_FLAT_MAX_WORDS` environment variable.

## Where to read

- [CLAUDE.md](../CLAUDE.md): the working rules of the repo, including the five that prevent real damage.
- [DESIGN.md](../DESIGN.md): the architecture, the memory map, the per-frame pipeline.
- [cr-rules.md](cr-rules.md): the review contract, rules R1 to R9.
- [ship-gate.md](ship-gate.md): the standing numbers, their provenance, and the gate a new binary must pass.
- `handoff-*.md`: one per milestone, the record of what was built and why.
- [launch-plan.md](launch-plan.md): the publication checklist.
