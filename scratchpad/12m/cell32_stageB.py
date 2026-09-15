"""STAGE B: template the hot loop on the CELL SIZE, still pinned to 8 bytes.

Stage A made the cell size a field and routed every cold site through accessors. The hot loop
cannot use an accessor -- a per-op branch on `m->cell_bytes` would cost more than the change
saves -- so it gets the same treatment `width`/`ww` already get: an extra parameter passed as a
LITERAL from the dispatch, which the compiler constant-folds, producing one specialised loop per
(width, cell) pair from one piece of source.

Still pinned to 8 bytes, so this stage must be bit-identical too. Only stage C flips the choice.

Also converts the generic (ring-debug) loop's raw `uint64_t* op_flat_jump` into an INDEX. A raw
pointer into the array has a type that changes with the cell size; an index does not, and that
lane is the debugger's, not the hot path, so it can afford the accessor.
"""
from pathlib import Path

SRC = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = SRC.read_text(encoding="utf-8")


def sub1(old, new, what):
    global s
    assert s.count(old) == 1, "anchor %r not unique (%d)" % (what, s.count(old))
    s = s.replace(old, new, 1)


# ── 1. the hot loop takes the cell size as a folded literal ────────────────────────────────────
sub1("""                                               PyObject* eof_exception_type, uint64_t start_ip, uint64_t* ops_out,
                                               double* paused_seconds_out, const uint64_t width, const uint64_t ww)""",
     """                                               PyObject* eof_exception_type, uint64_t start_ip, uint64_t* ops_out,
                                               double* paused_seconds_out, const uint64_t width, const uint64_t ww,
                                               const int cell32)""",
     "impl signature")

sub1("""    uint64_t* const flat = self->flat;
    const uint64_t flat_count = self->flat_count;""",
     """    /* exactly one of these is the live view of `self->flat`; `cell32` is a literal at every
       call site, so the compiler folds the dead one and every branch below away. */
    uint32_t* const flat32 = (uint32_t*)self->flat;
    uint64_t* const flat64 = (uint64_t*)self->flat;
    const uint64_t flat_count = self->flat_count;""",
     "flat views")

sub1("            f = flat[word_address];",
     "            f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];",
     "read flip word")
sub1("            flip_value = flat[flip_word_address];",
     "            flip_value = cell32 ? (uint64_t)flat32[flip_word_address]\n"
     "                                : flat64[flip_word_address];",
     "read flip target")
sub1("            flat[flip_word_address] = flip_value ^ (1ull << (f & bit_mask));",
     """            {
                const uint64_t flipped = flip_value ^ (1ull << (f & bit_mask));
                if (cell32) {
                    flat32[flip_word_address] = (uint32_t)flipped;
                } else {
                    flat64[flip_word_address] = flipped;
                }
            }""",
     "write flip target")
sub1("            j = flat[word_address + 1];",
     "            j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];",
     "read jump word")

# ── 2. the dispatch supplies the literal. cell32 is only ever 1 at w<=32, which stage C enforces
#      by setting cell_bytes; here it is read from the object so the two cannot disagree.
OLD_DISPATCH = """    switch (self->w) {
        case 64:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 64, 6);
        case 32:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 32, 5);
        case 16:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 16, 4);
        case 8:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 8, 3);
        default:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, (uint64_t)self->w, (uint64_t)self->ww);
    }"""
NEW_DISPATCH = """    const int c32 = (self->cell_bytes == 4);
    switch (self->w) {
        case 64:
            /* w=64 words cannot fit a 4-byte cell; mem_decide_storage never selects it, and the
               dispatch does not offer it, so the impossible instantiation is never generated. */
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 64, 6, 0);
        case 32:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 32, 5, 1)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 32, 5, 0);
        case 16:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 16, 4, 1)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 16, 4, 0);
        case 8:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 8, 3, 1)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 8, 3, 0);
        default:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, (uint64_t)self->w, (uint64_t)self->ww, 0);
    }"""
sub1(OLD_DISPATCH, NEW_DISPATCH, "dispatch")

# ── 3. the generic loop: a raw pointer into the array becomes an index ──────────────────────────
sub1("""    uint64_t* const flat = self->flat; /* non-NULL only in the with_ring clone */""",
     """    /* NO raw view of the array here: its element type changes with cell_bytes, and this lane
       is the debugger's ring mode rather than the hot path, so it reads through the accessor. */
    const int has_flat = (self->flat != NULL);""",
     "generic flat decl")
sub1("""    uint64_t* op_flat_jump = NULL;""",
     """#define OP_FLAT_JUMP_NONE UINT64_MAX
    uint64_t op_flat_jump = OP_FLAT_JUMP_NONE; /* INDEX of the jump word, not a pointer */""",
     "op_flat_jump decl")
sub1("""                op_flat_jump = NULL;""", """                op_flat_jump = OP_FLAT_JUMP_NONE;""",
     "op_flat_jump reset")
sub1("""            if (with_ring && op_flat_jump) {
                j = *op_flat_jump;
                if (flat_is_garbage(self, j) && flat_garbage_check(self, (uint64_t)(op_flat_jump - flat), &j) < 0) {""",
     """            if (with_ring && op_flat_jump != OP_FLAT_JUMP_NONE) {
                j = flat_load(self, op_flat_jump);
                if (flat_is_garbage(self, j) && flat_garbage_check(self, op_flat_jump, &j) < 0) {""",
     "op_flat_jump use")
sub1("""        f = flat[word_address];
        if (flat_is_garbage(self, f) && flat_garbage_check(self, word_address, &f) < 0) {
            goto memory_or_python_error;
        }
        op_flat_jump = flat + word_address + 1;""",
     """        f = flat_load(self, word_address);
        if (flat_is_garbage(self, f) && flat_garbage_check(self, word_address, &f) < 0) {
            goto memory_or_python_error;
        }
        op_flat_jump = word_address + 1;""",
     "flat lane")

SRC.write_text(s, encoding="utf-8")
print("stage B applied")
