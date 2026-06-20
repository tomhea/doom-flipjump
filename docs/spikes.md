# Spikes

Throwaway de-risking experiments (sN- branches, not merged). One section per spike.

## Spike Su — full-column-unroll assemble-time / size scaling (before R0; D2b / R-2 / R-3)

**Question (D2b):** is unrolling the renderer to one static op per pixel (~16,000 ops for a full
160x100 frame) feasible on assemble *time* (R-2) and `.fjm` *size* / flat *span* (R-3), before the R0
memory map (M10) commits to a full-unroll layout?

**Method:** `rep(N) <1-op stub>` for N=100..16000, at `w=32`, measuring assemble seconds + `.fjm` bytes
+ storage_mode. Two stub variants: *fixed-address* (the spec placeholder; same target each op) and
*distinct-address* (`fb+i*dw`, growing wflip constants — closer to the real per-pixel addresses). Code
was throwaway (gitignored `build/spike_unroll.py`, not committed).

**Result (flipjump 1.5.0, native engine):**

| N | fixed assemble_s | fixed .fjm B | distinct assemble_s | distinct .fjm B | storage |
|---|---|---|---|---|---|
| 100 | ~0.04 | 105 | ~0.04 | 268 | flat |
| 1000 | 0.06 | 136 | 0.06 | 821 | flat |
| 4000 | 0.07 | 166 | 0.11 | 2376 | flat |
| 8000 | 0.08 | 177 | 0.17 | 4249 | flat |
| **16000** | **0.11** | 188 | **0.34** | 7805 | **flat** |

**Finding:** the unroll mechanism is **cheap and linear**. A full 16,000-op frame assembles in **~0.34s**
(distinct-address, ~21 us/stub) and stays **flat**. The fixed-address variant compresses to near-nothing
(all-identical ops). Headroom is large: even if the *real* deposit stub is ~10-50x fatter than this 1-op
placeholder (texture-sample + colormap + multi-nibble deposit), assemble time stays in the low seconds
and `.fjm` size in the tens-to-hundreds of KB — comfortably inside R-2/R-3. **D2b full-unroll is
mechanically viable**; the open question is the *per-stub* cost, not whether unrolling scales.

**Caveat (§10.4 gap #10):** this measures the *mechanism* with a placeholder. The real (fatter) deposit
stub's per-stub assemble/size/ops cost is still measured for real at **M11c** (the D2 b-vs-a bake-off),
where the pre-committed decision rule applies. Spike not merged; this finding is the only artifact.
