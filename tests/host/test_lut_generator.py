"""Host-side tests for the M5 LUT/dispatch emitter (H2, src/doomfj/lut_generator.py).

Two layers:
- §3.4 data-table fallback (lifted from PR #1) — emitted-value byte-exactness pinned to hand-computed
  references; the canned sine/reciprocal emitters draw their values from tables.py (R6 SSOT).
- dispatch-CODE + deposit emitters — structural / validation checks (behavioural byte-exactness lives
  in tests/fj/test_dispatch_tables.py, which assembles + runs them on the real engine).
"""
import math

import pytest

from doomfj.fixedpoint import encode_fixed_point as fp_encode
from doomfj.tables import reciprocal_table, sine_table
from doomfj.lut_generator import (
    encode_fixed_point,
    generate_byte_lut_fj,
    generate_dispatch_table_fj,
    generate_lut_fj,
    generate_offset_deposit_table_fj,
    generate_reciprocal_lut_fj,
    generate_sine_lut_fj,
    generate_trig_idioms_fj,
)


# ---------- §3.4 data-table fallback (re-homed from PR #1) ----------

class TestEncodeFixedPoint:
    def test_reexports_fixedpoint_ssot(self) -> None:
        # R6: encode_fixed_point is the one in fixedpoint.py, not a private copy
        assert encode_fixed_point is fp_encode

    def test_positive_value(self) -> None:
        assert encode_fixed_point(1.0, fraction_bits=16, total_bits=32) == 0x10000
        assert encode_fixed_point(1.5, fraction_bits=16, total_bits=32) == 0x18000

    def test_negative_value_is_twos_complement(self) -> None:
        assert encode_fixed_point(-1.0, fraction_bits=16, total_bits=32) == 0xFFFF0000
        assert encode_fixed_point(-0.5, fraction_bits=16, total_bits=32) == 0xFFFF8000

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            encode_fixed_point(40000.0, fraction_bits=16, total_bits=32)


class TestGenerateLutFj:
    def test_emits_label_and_entries(self) -> None:
        fj_source = generate_lut_fj("my_table", [0x12, 0x3456, 0], entry_nibbles=4)
        assert "my_table:" in fj_source
        assert fj_source.count("hex.vec 4,") == 3
        assert "hex.vec 4, 0x12" in fj_source
        assert "hex.vec 4, 0x3456" in fj_source

    def test_value_must_fit_entry(self) -> None:
        with pytest.raises(ValueError):
            generate_lut_fj("t", [0x12345], entry_nibbles=4)

    def test_negative_values_rejected_encode_first(self) -> None:
        with pytest.raises(ValueError):
            generate_lut_fj("t", [-1], entry_nibbles=4)


class TestGenerateByteLutFj:
    def test_emits_packed_byte_ops(self) -> None:
        fj_source = generate_byte_lut_fj("colormap", [0, 0x41, 255])
        assert "colormap:" in fj_source
        assert fj_source.count("* dw") == 3
        assert ";0x41 * dw" in fj_source
        assert ";0xff * dw" in fj_source

    def test_non_byte_values_rejected(self) -> None:
        with pytest.raises(ValueError):
            generate_byte_lut_fj("t", [256])


class TestCannedGeneratorsUseTablesSSOT:
    def test_reciprocal_lut_values_match_tables(self) -> None:
        # R6: emitter draws values from tables.reciprocal_table (shared with the oracle)
        fj_source = generate_reciprocal_lut_fj("recip", count=4, fraction_bits=16, entry_nibbles=8)
        assert "recip:" in fj_source
        for v in reciprocal_table(4, 16, 32):
            assert f"hex.vec 8, {hex(v)}" in fj_source

    def test_sine_lut_values_match_tables(self) -> None:
        fj_source = generate_sine_lut_fj("finesine", count=8, fraction_bits=16, entry_nibbles=8)
        for v in sine_table(8, 16, 32):
            assert f"hex.vec 8, {hex(v)}" in fj_source
        # sin(6/8 * 2pi) is negative -> two's-complement encoded
        assert sine_table(8, 16, 32)[6] > 0x80000000


# ---------- dispatch-CODE + deposit emitters (structural) ----------

class TestGenerateDispatchTableFj:
    def test_per_entry_emits_table_and_lookup(self) -> None:
        src = generate_dispatch_table_fj("d1", [1, 2, 3, 4], index_nibbles=1, result_nibbles=1,
                                         mode="per_entry")
        assert "ns d1" in src
        assert "def lookup" in src
        assert "def init" in src
        assert "d1.init" in src
        # #5 construction: XOR value into kept-zero res, NOT hex.set per entry (D4 trap)
        assert "hex.set" not in src
        assert "clean_table_entry__table" in src

    def test_per_result_nibble_mode(self) -> None:
        src = generate_dispatch_table_fj("d2", [0xABCD, 0x1234], index_nibbles=1, result_nibbles=4,
                                         mode="per_result_nibble")
        assert "def lookup" in src
        assert "hex.set" not in src

    def test_over_align_doubles_pad(self) -> None:
        plain = generate_dispatch_table_fj("d3", list(range(16)), index_nibbles=1, result_nibbles=1)
        over = generate_dispatch_table_fj("d3", list(range(16)), index_nibbles=1, result_nibbles=1,
                                          over_align=True)
        assert "pad 16" in plain
        assert "pad 32" in over

    def test_value_too_wide_rejected(self) -> None:
        with pytest.raises(ValueError):
            generate_dispatch_table_fj("d", [0x1FF], index_nibbles=1, result_nibbles=2)

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            generate_dispatch_table_fj("d", [1, 2], index_nibbles=1, result_nibbles=1, mode="bogus")


class TestGenerateOffsetDepositTableFj:
    def test_emits_deposit_and_readback(self) -> None:
        src = generate_offset_deposit_table_fj("dep")
        assert "def deposit" in src
        assert "def readback" in src
        assert "dep.init" in src
        # +4-offset high-nibble flip target (D3) and no per-entry hex.set (D4 trap)
        assert "+4+w" in src or "+ 4 + w" in src or "acc+4" in src
        assert "hex.set" not in src


class TestGenerateTrigIdiomsFj:
    def test_emits_table_and_read_macros(self) -> None:
        src = generate_trig_idioms_fj("fs", 4096, 16)
        assert "def read_sin" in src
        assert "def read_cos" in src
        assert "fs.init" in src
        # cosine offset = count/4 = 1024 = 0x400, on a 3-nibble index (count=16^3)
        assert "hex.add_constant 3, ctmp, 0x400" in src
        # trig is the canonical per-result-nibble override site (D4); R6 byte-exactness vs
        # tables.sine_table is proven in tests/fj/test_lut_access.py
        assert "per-result-nibble" in src
        assert "hex.set" not in src

    def test_count_must_be_power_of_16(self) -> None:
        with pytest.raises(ValueError):
            generate_trig_idioms_fj("fs", 2048, 16)  # 2^11, not 16^k
