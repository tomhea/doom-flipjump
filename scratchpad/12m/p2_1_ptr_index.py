"""P2-1 probe: where does hex.ptr_index's cost sit, and can a proven-narrow index buy any of it?

The stl macro is

    def ptr_index dst, ptr, index {
        .mov w/4, dst, index
        .shl_hex w/4, dst
        rep(8-#w, i) .shr_bit w/4, dst
        .shl_hex w/4, dst
        .add w/4, dst, ptr
    }

-- eight nibbles wide throughout, because an address is w bits wide. But when the INDEX is
provably narrow the shift stage does not need to be: `frame.step_shade` builds
sh_idx = (cls << 8) | h with cls and h each two nibbles, so sh_idx < 16^4 and after the net
five-bit left shift it is still under 16^6. Only the final add has to span the whole address.

This prices the stl macro, each of its stages, and a doom-local variant whose shift stage runs at
width 6, over index values that span the real range. Nothing is shipped from this file -- it
decides whether the idea is worth a gate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, show                                        # noqa: E402
ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "src/fj/fixed_point.fj"]   # frame_render.fj needs emitter constants;
# the two chain macros it defines are copied verbatim into the prelude instead.

CHAIN = """
ns ch {
    def dance_boundary dst_prev, dst_next, src_next, jumper, prev, next \
            < hex.tables.ret, hex.tables.res {
        hex.xor_zero dst_prev, hex.tables.res
        hex.xor jumper,   dst_next
        hex.xor jumper+4, src_next
        wflip hex.tables.ret+w, prev^next, jumper
    }
    def add8_chain dst, src @ rcc0, r0, r1, r2, r3, r4, r5, r6, r7, rcc1 \
            < hex.tables.ret, hex.tables.res, hex.add.dst {
        wflip hex.tables.ret+w, rcc0, hex.add.dst
      rcc0:
        hex.zero hex.tables.res
        hex.xor hex.add.dst,   dst
        hex.xor hex.add.dst+4, src
        wflip hex.tables.ret+w, rcc0^r0, hex.add.dst
      r0:
        .dance_boundary dst+0*dw, dst+1*dw, src+1*dw, hex.add.dst, r0, r1
      r1:
        .dance_boundary dst+1*dw, dst+2*dw, src+2*dw, hex.add.dst, r1, r2
      r2:
        .dance_boundary dst+2*dw, dst+3*dw, src+3*dw, hex.add.dst, r2, r3
      r3:
        .dance_boundary dst+3*dw, dst+4*dw, src+4*dw, hex.add.dst, r3, r4
      r4:
        .dance_boundary dst+4*dw, dst+5*dw, src+5*dw, hex.add.dst, r4, r5
      r5:
        .dance_boundary dst+5*dw, dst+6*dw, src+6*dw, hex.add.dst, r5, r6
      r6:
        .dance_boundary dst+6*dw, dst+7*dw, src+7*dw, hex.add.dst, r6, r7
      r7:
        hex.xor_zero dst+7*dw, hex.tables.res
        wflip hex.tables.ret+w, r7^rcc1, hex.add.dst
      rcc1:
        wflip hex.tables.ret+w, rcc1
        hex.zero hex.tables.res
    }
}
"""

PRELUDE = CHAIN + """
ns pi {
    def full dst, ptr, index {
        hex.mov w/4, dst, index
        hex.shl_hex w/4, dst
        rep(8-#w, i) hex.shr_bit w/4, dst
        hex.shl_hex w/4, dst
        hex.add w/4, dst, ptr
    }
    def stage_mov dst, index {
        hex.mov w/4, dst, index
    }
    def stage_shifts dst {
        hex.shl_hex w/4, dst
        rep(8-#w, i) hex.shr_bit w/4, dst
        hex.shl_hex w/4, dst
    }
    def stage_add dst, ptr {
        hex.add w/4, dst, ptr
    }
    def narrow dst, ptr, index {
        hex.mov w/4, dst, index
        hex.shl_hex 6, dst
        rep(8-#w, i) hex.shr_bit 6, dst
        hex.shl_hex 6, dst
        hex.add w/4, dst, ptr
    }
    // the chained add, the repo's own cheaper hex.add 8
    def chained dst, ptr, index {
        hex.mov w/4, dst, index
        hex.shl_hex w/4, dst
        rep(8-#w, i) hex.shr_bit w/4, dst
        hex.shl_hex w/4, dst
        ch.add8_chain dst, ptr
    }
    // both levers at once
    def both dst, ptr, index {
        hex.mov w/4, dst, index
        hex.shl_hex 6, dst
        rep(8-#w, i) hex.shr_bit 6, dst
        hex.shl_hex 6, dst
        ch.add8_chain dst, ptr
    }
}
"""

DATA = ["base: hex.vec 8, 0x00A1B2C0",
        "i_small: hex.vec 8, 0x00000042",     # h alone
        "i_mid:   hex.vec 8, 0x00001F64",     # (cls<<8)|h, the real shape
        "i_big:   hex.vec 8, 0x0000FFFF",     # the widest a 4-nibble index gets
        "d1: hex.vec 8", "d2: hex.vec 8"]

print("=== P2-1 probe: hex.ptr_index, stage by stage ===")
print("")
print("STAGES (index = 0x00001F64, the (cls<<8)|h shape step_shade builds)")
show(["pi.stage_mov d1, i_mid"], DATA, PRELUDE, files=FILES, label="mov w/4, dst, index")
show(["pi.stage_mov d1, i_mid", "pi.stage_shifts d1"], DATA, PRELUDE,
     label="  + the three shift ops")
show(["pi.stage_mov d1, i_mid", "pi.stage_shifts d1", "pi.stage_add d1, base"], DATA, PRELUDE,
     label="  + add w/4, dst, ptr  (= the whole macro)")
print("")
print("VALUE CHECK -- the narrow variant must produce the SAME pointer for every index")
bad = 0
for name in ("i_small", "i_mid", "i_big"):
    rows = compare([("stl", ["pi.full d1, base, %s" % name]),
                    ("narrow", ["pi.narrow d1, base, %s" % name]),
                    ("both", ["pi.both d1, base, %s" % name])],
                   data=DATA, prelude=PRELUDE, files=FILES, quiet=True,
                   printer=["hex.print_as_digit 8, d1, 1"])
    o, n, b = rows[0][3], rows[1][3], rows[2][3]
    ok = o == n == b
    bad += 0 if ok else 1
    print("  %-10s stl=%s narrow=%s both=%s  %s" % (name, o, n, b, "ok" if ok else "!! DIFFER"))
print("")
print("value check: %s" % ("identical on all three" if not bad else "!! %d DIFFER" % bad))
print("")
print("COST, stl vs narrow (index = 0x00001F64)")
compare([("stl ptr_index", ["pi.full d1, base, i_mid"]),
         ("narrow shifts", ["pi.narrow d1, base, i_mid"]),
         ("chained add", ["pi.chained d1, base, i_mid"]),
         ("both", ["pi.both d1, base, i_mid"])], data=DATA, prelude=PRELUDE, files=FILES)
