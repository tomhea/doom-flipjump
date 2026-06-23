"""H2 — the host-side LUT / dispatch-code generator (S5.1 / M5).

Two families of emitter:

1. **§3.4 data-table fallback** (`generate_lut_fj` / `generate_byte_lut_fj` and the canned
   sine/reciprocal wrappers, lifted from PR #1). These emit consecutive `hex.vec n, value` entries
   (read at runtime by `hex.read_table`) or packed-byte `;value*dw` ops (read by
   `hex.read_table_byte`). The canned wrappers draw their values from `tables.py` — the single source
   shared with the oracle (R6/D12). A table read is ~O(w) ops; the dispatch tables below are ~4@.

2. **Dispatch-CODE tables** (`generate_dispatch_table_fj`) and the **D3 +4-offset packed-byte
   deposit** (`generate_offset_deposit_table_fj`). These emit pad-aligned dispatch *code* modelled on
   the STL truth tables (`hex.or.init`): a `switch` whose entry `d`, when jumped to, **XORs the
   entry's compile-time value into a kept-zero `res`** (`stl.wflip_macro`, the #5 construction — NOT
   `hex.set` per entry, which would bake a table-dispatched `hex.zero` into every entry: ~32x the
   space, span-breaking on big tables — D4's measured trap) and then **cleans the jumped dispatch op
   from within the table** via the stock `hex.tables.clean_table_entry__table`, before returning to
   `hex.tables.ret`. The caller's `xor_zero` reads `res` out into `dst` (and re-zeros it — the zero is
   paid once, D4). Two emit modes (D4): **per-entry** (default — one dispatch, the handler flips the
   whole value) and **per-result-nibble** (override — one single-nibble table per result nibble).

Generated tables require `hex.init` (or `stl.startup_and_init_all`) to be present at runtime for the
shared `hex.tables.ret`/`res` machinery. flipjump parses `.fj` as UTF-8; emitted text is ASCII.
"""
from __future__ import annotations

from typing import List, Sequence

from doomfj.fixedpoint import encode_fixed_point
from doomfj.tables import (
    reciprocal_table, sine_table, tantoangle_table, viewangletox_table,
    xtoviewangle_table, finetangent_table,
)

__all__ = [
    "encode_fixed_point",
    "generate_lut_fj",
    "generate_byte_lut_fj",
    "generate_sine_lut_fj",
    "generate_reciprocal_lut_fj",
    "generate_dispatch_table_fj",
    "generate_offset_deposit_table_fj",
    "generate_trig_idioms_fj",
    "generate_tantoangle_lut_fj",
    "generate_finetangent_lut_fj",
    "generate_xtoviewangle_lut_fj",
    "generate_viewangletox_lut_fj",
]


def _next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def _nibble(value: int, p: int) -> int:
    return (value >> (4 * p)) & 0xF


# ---------------------------------------------------------------------------
# §3.4 data-table fallback (read by hex.read_table / hex.read_table_byte)
# ---------------------------------------------------------------------------

def generate_lut_fj(label: str, values: Sequence[int], entry_nibbles: int) -> str:
    """Emit a `.fj` data table: `label:` + one `hex.vec entry_nibbles, value` per entry. Entry k sits
    at `label + k*entry_nibbles*dw` — indexable with `hex.read_table entry_nibbles, dst, label, idx_n,
    idx`. `values` are raw (already-encoded) unsigned words; negatives must be encoded first."""
    max_value = (1 << (4 * entry_nibbles)) - 1
    lines: List[str] = [
        f'// LUT "{label}": {len(values)} entries of {entry_nibbles} nibbles (doomfj.lut_generator)',
        f"{label}:",
    ]
    for index, value in enumerate(values):
        if not 0 <= value <= max_value:
            raise ValueError(
                f"{label}[{index}] = {value} does not fit {entry_nibbles} nibbles"
                f" (encode negative values with encode_fixed_point first)"
            )
        lines.append(f"    hex.vec {entry_nibbles}, {hex(value)}")
    return "\n".join(lines) + "\n"


def generate_byte_lut_fj(label: str, values: Sequence[int]) -> str:
    """Emit a `.fj` packed-byte data table: `label:` + one `;value*dw` op per entry (the byte lives in
    the op's data bits). Entry k sits at `label + k*dw` — read with `hex.read_table_byte`. Half the
    size of a `hex.vec 2` table; right for colormaps / light tables."""
    lines: List[str] = [
        f'// byte LUT "{label}": {len(values)} packed-byte entries (doomfj.lut_generator)',
        f"{label}:",
    ]
    for index, value in enumerate(values):
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{label}[{index}] = {value} is not a byte (0..255)")
        lines.append(f"    ;{hex(value)} * dw")
    return "\n".join(lines) + "\n"


def generate_reciprocal_lut_fj(label: str, count: int, fraction_bits: int, entry_nibbles: int) -> str:
    """Emit a reciprocal table (entry i = round(2^fraction_bits / i), entry 0 clamped). Values come
    from `tables.reciprocal_table` — the SSOT shared with the oracle (R6)."""
    return generate_lut_fj(label, reciprocal_table(count, fraction_bits, 4 * entry_nibbles),
                           entry_nibbles)


def generate_sine_lut_fj(label: str, count: int, fraction_bits: int, entry_nibbles: int) -> str:
    """Emit a sine table (entry k = sin(2*pi*k/count), two's-complement). Values come from
    `tables.sine_table` — the SSOT shared with the oracle (R6)."""
    return generate_lut_fj(label, sine_table(count, fraction_bits, 4 * entry_nibbles), entry_nibbles)


# ── projection LUTs the fj wall renderer reads (read_table data tables; the M12* tables, R6 SSOT) ──

def generate_tantoangle_lut_fj(label: str, slope_range: int = 2048) -> str:
    """tantoangle (R_PointToAngle: slope quotient -> BAM angle), slope_range+1 entries of 32-bit BAM
    (8 nibbles). Values from `tables.tantoangle_table` (all non-negative, < 2**32). Read once per wall."""
    return generate_lut_fj(label, tantoangle_table(slope_range), 8)


def generate_finetangent_lut_fj(label: str, trig_n: int) -> str:
    """finetangent (tan(angle-90°) as 16.16 two's-complement, 8 nibbles), trig_n entries. Values from
    `tables.finetangent_table` (already 32-bit two's-complement encoded). Read once per wall column."""
    return generate_lut_fj(label, finetangent_table(trig_n), 8)


def generate_xtoviewangle_lut_fj(label: str, view_w: int, trig_n: int) -> str:
    """xtoviewangle (screen column -> view-relative BAM angle), view_w+1 entries of 32-bit BAM (8
    nibbles). Values from `tables.xtoviewangle_table` (already 32-bit encoded). The wall-scale endpoints."""
    return generate_lut_fj(label, xtoviewangle_table(view_w, trig_n), 8)


def generate_viewangletox_lut_fj(label: str, view_w: int, trig_n: int, *, entry_nibbles: int = 8) -> str:
    """viewangletox (view-relative fine angle -> screen column), trig_n//2 entries. The columns are
    SIGNED ([-1, view_w+1] with off-screen sentinels), so they are encoded two's-complement in
    `entry_nibbles` (default 8 = uniform with the other projection LUTs). Values from
    `tables.viewangletox_table` (R6 SSOT). The fj angle->column lookup the wall x-range reads."""
    mask = (1 << (4 * entry_nibbles)) - 1
    values = [v & mask for v in viewangletox_table(view_w, trig_n)]
    return generate_lut_fj(label, values, entry_nibbles)


# ---------------------------------------------------------------------------
# Dispatch-CODE tables (per-entry / per-result-nibble, D4)
# ---------------------------------------------------------------------------

def _validate_values(label: str, values: Sequence[int], result_nibbles: int) -> int:
    if not values:
        raise ValueError(f"{label}: empty value list")
    max_value = (1 << (4 * result_nibbles)) - 1
    for i, v in enumerate(values):
        if not 0 <= v <= max_value:
            raise ValueError(f"{label}[{i}] = {v} does not fit {result_nibbles} nibbles")
    return _next_pow2(len(values))


def _lookup_macro(label: str, index_nibbles: int, result_nibbles: int, res: str) -> List[str]:
    """A `<label>.lookup dst, idx` macro: XOR the index into the dispatch op, jump through it, then
    read the kept-zero result `res` out into `dst` (`dst = table[idx]`; dst is zeroed first so a
    second call to the same dst is correct — #8)."""
    zero = f"hex.zero dst" if result_nibbles == 1 else f"hex.zero {result_nibbles}, dst"
    xz = (f"hex.xor_zero dst, {res}" if result_nibbles == 1
          else f"hex.xor_zero {result_nibbles}, dst, {res}")
    return [
        f"    def lookup dst, idx @ return < hex.tables.ret, {res}, .dsp {{",
        f"        rep({index_nibbles}, i) hex.xor .dsp + 4*i, idx + i*dw",
        "        wflip hex.tables.ret+w, return, .dsp",
        "      return:",
        "        wflip hex.tables.ret+w, return",
        f"        {zero}",
        f"        {xz}",
        "    }",
    ]


def _per_entry_table(label: str, values: Sequence[int], index_nibbles: int, result_nibbles: int,
                     pad: int, align: int) -> str:
    """Per-entry dispatch table (D4 default). One dispatch; the jumped entry flips the whole value
    into the kept-zero result, then the stock clean-table XORs the index back out of the dispatch op.

    1-nibble result: the value flip packs into the `switch` op itself (the `hex.or` shape, into the
    shared `hex.tables.res`). Wider results: `switch` jumps to a per-entry handler that flips every
    result nibble into a private kept-zero `res` vec (the shared res is only one nibble)."""
    lines = [f"// dispatch table \"{label}\": {len(values)} entries, per-entry mode, "
             f"{result_nibbles}-nibble result (doomfj.lut_generator)",
             f"ns {label} {{"]

    if result_nibbles == 1:
        res = "hex.tables.res"
        lines += _lookup_macro(label, index_nibbles, result_nibbles, res)
        lines += [
            "    def init @ switch, clean, end < hex.tables.res, hex.tables.ret > dsp {",
            "        ;end",
            "      dsp: ;switch",
            f"        pad {align}",
            "      switch:",
        ]
        for d in range(pad):
            v = _nibble(values[d], 0) if d < len(values) else 0
            lines.append(f"        stl.wflip_macro hex.tables.res+w, {hex(v)}*dw, clean+{d}*dw")
        lines += [
            "      clean:",
            f"        hex.tables.clean_table_entry__table {pad}, .dsp, hex.tables.ret",
            "      end:",
            "    }",
        ]
    else:
        res = ".res"
        hstride = result_nibbles + 1
        lines += _lookup_macro(label, index_nibbles, result_nibbles, res)
        lines += [
            "    def init @ switch, handlers, clean, end < hex.tables.ret > dsp, res {",
            "        ;end",
            f"      res: hex.vec {result_nibbles}",
            "      dsp: ;switch",
            f"        pad {align}",
            "      switch:",
        ]
        for d in range(pad):
            lines.append(f"        ;handlers + {d}*{hstride}*dw")
        lines.append("      handlers:")
        for d in range(pad):
            v = values[d] if d < len(values) else 0
            for p in range(result_nibbles):
                lines.append(f"        wflip .res+{p}*dw+w, {hex(_nibble(v, p))}*dw")
            lines.append(f"        ;clean + {d}*dw")
        lines += [
            "      clean:",
            f"        hex.tables.clean_table_entry__table {pad}, .dsp, hex.tables.ret",
            "      end:",
            "    }",
        ]
    lines += [f"}}", f"{label}.init", ""]
    return "\n".join(lines)


def _per_result_nibble_table(label: str, values: Sequence[int], index_nibbles: int,
                             result_nibbles: int, pad: int, align: int) -> str:
    """Per-result-nibble dispatch table (D4 override): `result_nibbles` independent single-nibble
    tables (table p holds nibble p of every value). One dispatch per result nibble — cheaper span on
    wide *cold* tables, more dispatches per lookup. Each sub-table is the `hex.or` packed shape."""
    lines = [f"// dispatch table \"{label}\": {len(values)} entries, per-result-nibble mode, "
             f"{result_nibbles} nibbles (doomfj.lut_generator)",
             f"ns {label} {{"]
    # lookup: dispatch each nibble-table into the shared res, read out into dst+p*dw
    rets = ", ".join(f"ret{p}" for p in range(result_nibbles))
    dsps = ", ".join(f".dsp{p}" for p in range(result_nibbles))
    lines += [
        f"    def lookup dst, idx @ {rets} < hex.tables.ret, hex.tables.res, {dsps} {{",
    ]
    for p in range(result_nibbles):
        lines += [
            f"        rep({index_nibbles}, i) hex.xor .dsp{p} + 4*i, idx + i*dw",
            f"        wflip hex.tables.ret+w, ret{p}, .dsp{p}",
            f"      ret{p}:",
            f"        wflip hex.tables.ret+w, ret{p}",
            f"        hex.zero dst+{p}*dw",
            f"        hex.xor_zero dst+{p}*dw, hex.tables.res",
        ]
    lines.append("    }")
    # one init per nibble table, declaring all dsp{p} as outputs
    outs = ", ".join(f"dsp{p}" for p in range(result_nibbles))
    locals_ = ", ".join(f"switch{p}, clean{p}" for p in range(result_nibbles))
    lines += [
        f"    def init @ {locals_}, end < hex.tables.res, hex.tables.ret > {outs} {{",
        "        ;end",
    ]
    for p in range(result_nibbles):
        lines += [
            f"      dsp{p}: ;switch{p}",
            f"        pad {align}",
            f"      switch{p}:",
        ]
        for d in range(pad):
            v = _nibble(values[d], p) if d < len(values) else 0
            lines.append(f"        stl.wflip_macro hex.tables.res+w, {hex(v)}*dw, clean{p}+{d}*dw")
        lines += [
            f"      clean{p}:",
            f"        hex.tables.clean_table_entry__table {pad}, .dsp{p}, hex.tables.ret",
        ]
    lines += ["      end:", "    }", "}", f"{label}.init", ""]
    return "\n".join(lines)


def generate_dispatch_table_fj(label: str, values: Sequence[int], *, index_nibbles: int,
                               result_nibbles: int, mode: str = "per_entry",
                               over_align: bool = False) -> str:
    """Emit a dispatch-CODE LUT (`label`) plus a `<label>.lookup dst, idx` macro and a `<label>.init`
    call. `values` are raw unsigned `result_nibbles`-wide words; `idx` is a `index_nibbles`-wide hex.

    mode (D4): "per_entry" (default; one dispatch, the handler flips the whole value) or
    "per_result_nibble" (one single-nibble table per result nibble). `over_align` pads the hot table
    to 2x (the top alignment bit stays 0 — saves ~1 op/lookup; §2.1)."""
    pad = _validate_values(label, values, result_nibbles)
    if 4 * index_nibbles < max(1, (pad - 1).bit_length()):
        raise ValueError(
            f"{label}: index_nibbles={index_nibbles} too narrow for {pad}-entry table")
    align = pad * 2 if over_align else pad  # over-align: pad the address to 2x (top bit stays 0, �2.1)
    if mode == "per_entry":
        return _per_entry_table(label, values, index_nibbles, result_nibbles, pad, align)
    if mode == "per_result_nibble":
        return _per_result_nibble_table(label, values, index_nibbles, result_nibbles, pad, align)
    raise ValueError(f"{label}: unknown mode {mode!r} (per_entry | per_result_nibble)")


# ---------------------------------------------------------------------------
# D3 +4-offset packed-byte deposit
# ---------------------------------------------------------------------------

def generate_offset_deposit_table_fj(label: str) -> str:
    """Emit the D3 packed-byte deposit machinery: deposit a runtime byte (a register-form `hex.vec 2`)
    into a kept-zero **packed-byte** accumulator `acc` (one op, both nibbles) via two nibble
    dispatches — **low nibble** at `acc+dbit` (stock clean-table) + **high nibble** at `acc+dbit+4`
    (the +4-offset variant). The framebuffer pixel is one packed byte the device reads, written
    pointer-free by D2(b)'s fixed-address stores; this is the per-pixel deposit primitive (~2
    dispatches/px). `acc` is held at zero between deposits (the consumer re-zeros it after reading).

    Provides:
      - `<label>.deposit value`   — deposit the byte in register-hex `value[:2]` into `acc`.
      - `<label>.readback dst`    — consume `acc` (jump THROUGH the packed byte as an 8-bit dispatch,
        the way a device/consumer reads it) into a register-form `dst[:2]`, re-zeroing `acc`. This is
        the in-program verification consumer; the production present path is the screen device (M11a).
    """
    L: List[str] = [f"// +4-offset packed-byte deposit \"{label}\" (D3, doomfj.lut_generator)",
                    f"ns {label} {{",
                    "    reg: hex.vec 2",
                    # deposit: low nibble -> acc[dbit..], high nibble -> acc[dbit+4..] (+4 offset)
                    "    def deposit value < .dsp_lo, .dsp_hi {",
                    "        .dispatch .dsp_lo, value + 0*dw",
                    "        .dispatch .dsp_hi, value + 1*dw",
                    "    }",
                    "    def dispatch dsp, nib @ return < hex.tables.ret {",
                    "        hex.xor dsp, nib",
                    "        wflip hex.tables.ret+w, return, dsp",
                    "      return:",
                    "        wflip hex.tables.ret+w, return",
                    "    }",
                    # readback: jump through the packed acc into the demux, get dst = the byte (reg form)
                    "    def readback dst @ return < hex.tables.ret, .acc, .reg {",
                    "        wflip hex.tables.ret+w, return, .acc",
                    "      return:",
                    "        wflip hex.tables.ret+w, return",
                    "        hex.zero 2, dst",
                    "        hex.xor_zero 2, dst, .reg",
                    "    }",
                    "    def init @ switch_lo, switch_hi, demux_switch, demux_handlers, "
                    "clean_lo, clean_hi, demux_clean, end \\",
                    "            < hex.tables.ret, .reg > acc, dsp_lo, dsp_hi {",
                    "        ;end",
                    "      acc: ;demux_switch",       # packed-byte target AND demux dispatch op
                    "      dsp_lo: ;switch_lo",
                    "      dsp_hi: ;switch_hi",
                    "        pad 16",
                    "      switch_lo:"]
    for d in range(16):  # identity: flip nibble d into acc low nibble (offset 0)
        L.append(f"        stl.wflip_macro .acc+w,   {hex(d)}*dw, clean_lo+{d}*dw")
    L += ["      clean_lo:",
          "        hex.tables.clean_table_entry__table 16, .dsp_lo, hex.tables.ret",
          "        pad 16",
          "      switch_hi:"]
    for d in range(16):  # identity: flip nibble d into acc HIGH nibble (the +4 offset)
        L.append(f"        stl.wflip_macro .acc+4+w, {hex(d)}*dw, clean_hi+{d}*dw")
    L += ["      clean_hi:",
          "        hex.tables.clean_table_entry__table 16, .dsp_hi, hex.tables.ret",
          "        pad 256",
          "      demux_switch:"]
    for v in range(256):  # demux: byte v -> handler that sets reg = v (register form)
        L.append(f"        ;demux_handlers + {v}*3*dw")
    L.append("      demux_handlers:")
    for v in range(256):
        L.append(f"        wflip .reg+0*dw+w, {hex(v & 0xF)}*dw")
        L.append(f"        wflip .reg+1*dw+w, {hex((v >> 4) & 0xF)}*dw")
        L.append(f"        ;demux_clean + {v}*dw")
    L += ["      demux_clean:",
          "        hex.tables.clean_table_entry__table 256, .acc, hex.tables.ret",
          "      end:",
          "    }",
          "}",
          f"{label}.init",
          ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# F3 — trig access idioms (read_sin / read_cos via the shared sine table, #9)
# ---------------------------------------------------------------------------

def generate_trig_idioms_fj(label: str, count: int, fraction_bits: int, *, result_nibbles: int = 8,
                            mode: str = "per_result_nibble", over_align: bool = False) -> str:
    """Emit the finesine dispatch table (`label`, values from `tables.sine_table` — R6 SSOT) plus the
    F3 trig idioms `read_sin dst, idx` / `read_cos dst, idx`. `idx` is the angle's top nibbles (the
    16^k-sized table is indexed with no sub-nibble shift, §2.1). Cosine SHARES the sine table:
    cos = sin((idx + count/4) mod count) — a single `hex.add_constant` of `count/4` on the k-nibble
    index, wrapping mod 16^k = count (#9; a separate cosine LUT is not worth the span).

    `count` must be a power of 16 (16^k) so the +count/4 wrap is a plain k-nibble add. Trig is
    per-column (~160x/frame) ⇒ `per_result_nibble` is the canonical mode (D4: span over speed)."""
    k = 0
    c = count
    while c > 1:
        if c % 16:
            raise ValueError(f"{label}: count={count} must be a power of 16 (16^k) for trig (§2.1)")
        c //= 16
        k += 1
    index_nibbles = max(1, k)
    offset = count // 4  # +N/4 (the cosine quarter-turn)

    values = sine_table(count, fraction_bits, 4 * result_nibbles)
    table = generate_dispatch_table_fj(label, values, index_nibbles=index_nibbles,
                                       result_nibbles=result_nibbles, mode=mode,
                                       over_align=over_align)
    # reopen the table's namespace with the read idioms (read_sin is the bare lookup; read_cos adds
    # the shared-table quarter-turn offset, mod count via the k-nibble add).
    idioms = [
        f"// F3 trig idioms for \"{label}\" (read_sin / read_cos, cosine shares the table, #9)",
        f"ns {label} {{",
        "    def read_sin dst, idx {",
        "        .lookup dst, idx",
        "    }",
        f"    def read_cos dst, idx @ ctmp, after {{",
        "        ;after",
        f"      ctmp: hex.vec {index_nibbles}",
        "      after:",
        f"        hex.mov {index_nibbles}, ctmp, idx",
        f"        hex.add_constant {index_nibbles}, ctmp, {hex(offset)}",
        "        .lookup dst, ctmp",
        "    }",
        "}",
        "",
    ]
    return table + "\n".join(idioms)
