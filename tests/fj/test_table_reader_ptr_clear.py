"""Z2's narrowed pointer clear in the three `fixed_point.fj` table readers, exercised RE-ENTRANTLY.

`read_table_packed` / `read_table` / `read_table_byte` all open the same way:

    .zero w/4 - idx_n, ptr + idx_n*dw     // Z2 (c65da95): was `.zero w/4, ptr`
    .mov idx_n, ptr, idx                  // the mov zeroes the low idx_n nibbles itself
    .mul_const w/4, ptr, ptr, <stride>
    .add w/4, ptr, table_address

so `ptr` ends a call holding an ENTRY ADDRESS, five or six nibbles wide, and the next call through
that same expansion has to wipe every nibble of it above `idx_n` before the index goes in. Narrow
that clear by one nibble and the pointer keeps a piece of the previous entry's address: the read
lands somewhere else in (or past) the table. `read_table_packed` alone is 9.3% of the program's
exact_xor calls (c65da95's census, not re-measured here) and `read_table` is called all over the
renderer, so those two sit under everything -- planes, projection, sprites, doors.
`read_table_byte` is the exception and it is worth being exact about: it has NO call site in
`src/fj` today (`src/doomfj/lut_generator.py:77` calls it the "data-table fallback"). It is here
because the Z2 clear and the mov under it are character-identical in all three readers -- only
`.mul_const`'s stride differs -- which is what makes read_table_byte's copy the one the negative
control can lift and still be lifting all three. `_setup_lines` asserts that (both lines appear
exactly three times), it does not assume it.

WHY THIS IS NOT THE CALL-TWICE THE OTHER FILES DO. `ptr` is a macro-LOCAL (`@ ptr`): writing the
same call twice in the source gives two expansions with two registers, each freshly zeroed by its
own `hex.vec`, and a narrowed clear is invisible. The dirty pointer only exists on a SECOND ENTRY
into ONE expansion -- which is the state the shipped renderer is permanently in, since every one of
these reads sits in a loop. So each case here is a two-iteration loop around a single expansion,
reading a LARGE index first and the entry under test second (R5 #8): the big index is what puts
non-zero bits into the nibble just above `idx_n`, and the small one is where they would show.

WHICH BIG INDEX, AND WHY TWO OF THEM. That nibble of the previous pointer is
`nibble[idx_n](big*stride + table_address)`, and `table_address` is whatever the assembler picked,
so a single big index could have it come out zero and separate nothing -- the test would pass with
the bug in place and say nothing about it. `_bigs` picks two indices whose `big*stride` differ by
more than one AT THAT NIBBLE, which no single addend can cancel for both, and the passes alternate
between them. The condition is ASSERTED, not assumed; what it buys is that a one-nibble narrowing
must change the output of these tests whatever address the table lands at.

WHICH idx_n, AND WHY THE STRIDE DECIDES THAT. In `src/fj` the readers are called with `idx_n` = 3
at 13 call sites, 2 at 5, and a macro parameter at 7 (`n_th` x2, `n_ln` x2, `n_bk`, `n_bl`,
`nlti`), so 3 is the common width -- and both readers that take it run at 3 below as well as at 2.
What decides whether a width is reachable is the ENTRY STRIDE, not the index: `_bigs` needs two
indices under COUNT whose `big*stride` differ by more than one at nibble `idx_n`, which takes
`(COUNT-1)*stride >= 2*16**idx_n`. At COUNT=32 with dw=64 that is any entry width at idx_n=2, and
five dw-slots or more at idx_n=3 (31*5*64 = 0x26C0, two nibble-3 units) -- which is why the idx_n=3
cases read WIDER entries, 5 nibbles and 5 bytes, than their idx_n=2 twins. `read_table_byte` cannot
join them: its stride is fixed at `dw`, so two indices would not differ at nibble 3 until the table
held 129 entries (31 reaches 0x7C0), and it has no call site in `src/fj` to justify assembling one.
What is NOT true is that a 32-entry index cannot dirty nibble 3 by itself -- index 31 at stride 256
puts a 1 there -- only that no two such indices differ there by more than one, so a single big index
would leave the separation to the table address, which is what the paragraph above refuses to depend
on. `_bigs` asserts its condition per stride and fails loudly rather than passing quietly. The
control's probe has no table and no `.add`, so its pointer is `idx*dw`, any index fits, and it runs
at 3 AND at 2.

Values come from `doomfj.lut_generator` -- the same three emitters the build bakes its tables with
(R6) -- and every entry of every table is read, so a pointer off by one entry is a wrong line.

The clear under test is the POINTER's and does not depend on how wide an ENTRY is, so entry width
is assembly cost and nothing else -- except at idx_n=3, where the width IS the stride, and 5 is the
least that lets the case separate at all.

THE NEGATIVE CONTROL is the last two tests. They lift the readers' three opening lines out of the
real file and run them as a macro that PUBLISHES the pointer instead of dereferencing it, so the
value is predictable host-side (`idx * dw`) and nothing jumps through a wrong address. One copy
keeps the clear as it stands and must land on the index alone on re-entry; the other has it
narrowed by a nibble and must NOT -- which is the failure the reader cases above would see as a
line of the wrong table entry. That the narrowed copy CAN separate is asserted there too (`kept`).

WHAT THAT STILL DOES NOT PROVE: the control mutates the lifted pointer setup, not a whole reader,
so the dereference path is only covered by the correct-value tests, and the narrowed form of a real
reader is never run (it would read outside its own table). And a narrowing is a structural question
as much as a behavioural one -- that each narrowed clear is completed by the mov that follows it,
on every path, is `tests/host/test_narrowed_clear_sites.py`.
"""
from pathlib import Path

import pytest

import flipjump as fj

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_byte_lut_fj, generate_lut_fj, generate_packed_lut_fj

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")

COUNT = 32          # every entry is read, so keep the table small enough to assemble quickly
BYTE_IDX_N = 2      # the only width read_table_byte's fixed `dw` stride reaches (see the header)
DW = 2 * W          # stl/runlib.fj: `dw = 2 * w`, the stride read_table_byte multiplies the index by
PTR_MASK = (1 << W) - 1                 # `ptr` is a hex.vec w/4, so the stride multiply wraps there
# the pointer setup all three readers open with. Only `.mul_const`'s stride differs between them
# (`dw` / `n*dw` / `nb*dw`); the Z2 clear and the mov under it are character-identical in all three.
SETUP = (".zero w/4 - idx_n, ptr + idx_n*dw", ".mov idx_n, ptr, idx",
         ".mul_const w/4, ptr, ptr, dw")


def _bigs(stride, idx_n):
    """the two first-pass indices the passes alternate between, as a list of COUNT of them.

    A narrowed clear leaves nibble `idx_n` of the previous call's pointer -- `big*stride +
    table_address` -- in place. Adding the (assembler-chosen) table address moves that nibble by its
    own digit plus at most one carry, so two `big*stride` that differ by more than one there cannot
    both come out zero: at least one of the two passes dirties the nibble whatever the address is."""
    def hi(b):
        return (b * stride) >> (4 * idx_n)

    second = [b for b in range(COUNT) if (hi(COUNT - 1) - hi(b)) % 16 not in (0, 1, 15)]
    assert second, (f"no two indices under {COUNT} differ above nibble {idx_n} at stride {stride}: "
                    f"this test would only separate if the table address happened to help")
    return [COUNT - 1 if k % 2 == 0 else second[-1] for k in range(COUNT)]


def _sources(tmp_path):
    """the files these programs assemble with: the generated constants first (one source with the
    shipped build, R6), then fixed_point.fj for the three readers under test."""
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), FIXED_POINT_FJ.resolve()]


def _run(tmp_path, name, body, data, expected: bytes):
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [*_sources(tmp_path), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != host table"


def _values(nibbles):
    """COUNT distinct entries, so a read that lands on the wrong one shows up in the output rather
    than agreeing by accident (an odd multiplier keeps them distinct at every width)."""
    mask = (1 << (4 * nibbles)) - 1
    return [(0x9E3779B1 * (k + 1)) & mask for k in range(COUNT)]


def _reentrant(tag, k, big, call, res_n, idx_n):
    """ONE expansion of `call`, entered twice: index `big`, then index k.

    `ph` is the pass flag -- 0 on the way in, so the first pass falls through, sets it and jumps
    back; on the second pass `if1` leaves the loop. The whole point is that `call` is written once:
    a second call site would get its own freshly-zeroed macro-local `ptr`."""
    lp, fin = f"{tag}_lp{k}", f"{tag}_fin{k}"
    return [f"hex.set {idx_n}, {tag}_i, {big}",
            f"hex.zero 1, {tag}_ph",
            f"{lp}:",
            call,
            f"hex.print_as_digit {res_n}, {tag}_d, 0", "stl.output 10",
            f"hex.if1 1, {tag}_ph, {fin}",
            f"hex.inc 1, {tag}_ph",
            f"hex.set {idx_n}, {tag}_i, {k}",
            f";{lp}",
            f"{fin}:"]


def _body(tag, call, res_n, bigs, idx_n):
    return [line for k in range(COUNT)
            for line in _reentrant(tag, k, bigs[k], call, res_n, idx_n)]


def _registers(tag, res_n, idx_n):
    return [f"{tag}_i: hex.vec {idx_n}", f"{tag}_ph: hex.vec 1", f"{tag}_d: hex.vec {res_n}"]


def _expected(values, res_n, bigs):
    return b"".join(f"{values[bigs[k]]:0{res_n}x}\n{values[k]:0{res_n}x}\n".encode()
                    for k in range(COUNT))


# `n` / `nbytes` is the entry width in dw-slots as well as in nibbles/bytes, so it IS `.mul_const`'s
# stride over dw. Any width separates at idx_n=2; at idx_n=3 -- the width `src/fj` asks for at 13 of
# its 25 call sites -- it takes at least 5 (see the header; `_bigs` asserts it, per stride).
@pytest.mark.parametrize("idx_n, n", [(2, 4), (3, 5)], ids=["idx_n2", "idx_n3"])
def test_read_table_every_entry_after_a_large_index_through_one_expansion(tmp_path, idx_n, n):
    res_n, values = n, _values(n)
    bigs = _bigs(n * DW, idx_n)                 # entry stride: n*dw
    call = f"hex.read_table {n}, rt_d, rt_tbl, {idx_n}, rt_i"
    data = _registers("rt", res_n, idx_n) + [generate_lut_fj("rt_tbl", values, n)]
    _run(tmp_path, f"read_table_ptr{idx_n}", _body("rt", call, res_n, bigs, idx_n), data,
         _expected(values, res_n, bigs))


@pytest.mark.parametrize("idx_n, nbytes", [(2, 2), (3, 5)], ids=["idx_n2", "idx_n3"])
def test_read_table_packed_every_entry_after_a_large_index_through_one_expansion(tmp_path, idx_n,
                                                                                nbytes):
    res_n, values = 2 * nbytes, _values(2 * nbytes)
    bigs = _bigs(nbytes * DW, idx_n)            # entry stride: nb*dw
    call = f"hex.read_table_packed {nbytes}, rp_d, rp_tbl, {idx_n}, rp_i"
    data = _registers("rp", res_n, idx_n) + [generate_packed_lut_fj("rp_tbl", values, nbytes)]
    _run(tmp_path, f"read_table_packed_ptr{idx_n}", _body("rp", call, res_n, bigs, idx_n), data,
         _expected(values, res_n, bigs))


def test_read_table_byte_every_entry_after_a_large_index_through_one_expansion(tmp_path):
    """No idx_n=3 row: `read_table_byte`'s stride is not a parameter, it is `dw`, so `_bigs` would
    need a 129-entry table to separate at nibble 3 -- and it has no call site in `src/fj` at any
    width. It is here for the clear it shares character for character with the other two."""
    res_n, values = 2, _values(2)
    bigs = _bigs(DW, BYTE_IDX_N)                # entry stride: dw
    call = f"hex.read_table_byte rb_d, rb_tbl, {BYTE_IDX_N}, rb_i"
    data = _registers("rb", res_n, BYTE_IDX_N) + [generate_byte_lut_fj("rb_tbl", values)]
    _run(tmp_path, "read_table_byte_ptr", _body("rb", call, res_n, bigs, BYTE_IDX_N), data,
         _expected(values, res_n, bigs))


# -- the negative control: the same pointer setup, publishing `ptr` instead of dereferencing it --

def _setup_lines():
    """the three lines taken OUT of the real file, after checking they are still exactly SETUP.

    So the probe below cannot quietly become a stale copy: change the readers' opening and this
    goes red on the match rather than on a value, which says which of the two moved."""
    lines = [ln.strip() for ln in FIXED_POINT_FJ.read_text(encoding="utf-8").split("\n")]
    hits = [i for i in range(len(lines) - 2) if tuple(lines[i:i + 3]) == SETUP]
    assert hits, f"read_table_byte no longer opens with {SETUP}"
    for line in SETUP[:2]:      # the clear and its mov; SETUP[2]'s stride differs per reader
        assert lines.count(line) == 3, (f"{line!r} appears {lines.count(line)} times in "
                                        f"{FIXED_POINT_FJ}, not once per table reader -- the three "
                                        f"openings have diverged, so lifting one no longer stands "
                                        f"for the other two")
    return lines[hits[0]:hits[0] + 3]


def _probe(name, setup):
    """`read_table_byte`'s opening, stopped one line early: with no `.add table_address` and no
    read, the pointer is `idx * dw` and nothing dereferences it, so a dirty high nibble shows up as
    a number instead of a jump into whatever address it happens to name."""
    return "\n".join(["ns hex {", f"    def {name} dst, idx_n, idx @ ptr, end {{"]
                     + [f"        {ln}" for ln in setup]
                     + ["        .mov w/4, dst, ptr", "        ;end",
                        "      ptr: .vec w/4", "      end:", "    }", "}"])


def _probe_big(idx_n):
    """the widest index that fits `idx_n` nibbles. No table means no bound on it, so the probe
    dirties the nibble above the index at any idx_n -- which is what the readers cannot do."""
    return (1 << (4 * idx_n)) - 1


def _probe_body(tag, name, idx_n):
    big = _probe_big(idx_n)
    return [line for k in range(COUNT)
            for line in _reentrant(tag, k, big, f"hex.{name} {tag}_d, {idx_n}, {tag}_i", W // 4,
                                   idx_n)]


@pytest.mark.parametrize("idx_n", [3, 2], ids=["idx_n3", "idx_n2"])
def test_the_pointer_lands_on_the_index_alone_when_the_expansion_is_re_entered(tmp_path, idx_n):
    setup = _setup_lines()
    big = _probe_big(idx_n)
    expected = b"".join(f"{big * DW & PTR_MASK:0{W // 4}x}\n{k * DW & PTR_MASK:0{W // 4}x}\n".encode()
                        for k in range(COUNT))
    _run(tmp_path, f"ptr_probe{idx_n}", _probe_body("pp", f"ptr_probe{idx_n}", idx_n),
         _registers("pp", W // 4, idx_n) + [_probe(f"ptr_probe{idx_n}", setup)], expected)


@pytest.mark.parametrize("idx_n", [3, 2], ids=["idx_n3", "idx_n2"])
def test_the_same_probe_with_the_clear_narrowed_by_one_nibble_keeps_the_previous_index(tmp_path,
                                                                                      idx_n):
    """THE CONTROL. Move the clear up one nibble and the nibble it no longer reaches still holds
    the last call's pointer, so the second entry computes from `kept | idx` instead of `idx`. If
    this ever matched the un-narrowed expectation the test above would have no teeth."""
    setup = _setup_lines()
    setup[0] = setup[0].replace("w/4 - idx_n,", "w/4 - idx_n - 1,").replace("+ idx_n*dw",
                                                                            "+ (idx_n+1)*dw")
    assert setup[0] != SETUP[0]
    big = _probe_big(idx_n)
    kept = (big * DW) & (0xF << (4 * idx_n))    # the one nibble the narrowed clear leaves behind
    assert kept, "the control only separates if the first pass dirties the nibble it spares"
    expected = b"".join(
        f"{big * DW & PTR_MASK:0{W // 4}x}\n{(kept | k) * DW & PTR_MASK:0{W // 4}x}\n".encode()
        for k in range(COUNT))
    _run(tmp_path, f"ptr_probe_narrow{idx_n}", _probe_body("pn", f"ptr_probe_narrow{idx_n}", idx_n),
         _registers("pn", W // 4, idx_n) + [_probe(f"ptr_probe_narrow{idx_n}", setup)], expected)
