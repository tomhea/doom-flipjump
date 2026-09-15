"""fold (c): the input test joins the head branch (sentinel | output | input): one branch, and the
cold block handles the three in the old order. Applies on top of fold (b)."""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:90])
    s = s.replace(old, new)


rep("""            /* ONE branch for "f is the sentinel" and "f is an output op" (fold b): both rare, and
               the cold block tells them apart in the old order - sentinel first, then output
               (which a sentinel-valued f can never be). The bitwise | keeps it one branch. */
            if (FLAT_IS_SENTINEL(f) | (f - dw <= 1)) {
                goto cold_flip_word;
            }
        after_output:
            /* input when in_lo_exclusive < ip <= in_addr - one unsigned compare */
            if (ip - in_lo_exclusive - 1 < dw) {
                goto cold_input;
            }
        after_input:
""", """            /* ONE branch for "f is the sentinel", "f is an output op" (f is dw or dw+1) and "ip is
               the input op" (in_lo_exclusive < ip <= in_addr) - folds b and c: all three are rare,
               and the cold block tells them apart in the old order - sentinel, output, input. The
               bitwise | keeps it one branch. */
            if (FLAT_IS_SENTINEL(f) | (f - dw <= 1) | (ip - in_lo_exclusive - 1 < dw)) {
                goto cold_flip_word;
            }
        after_input:
""")

rep("""    cold_flip_word_resolved:
        if (f - dw <= 1) {
            /* output. time the callback as paused, exactly like the input callback below - so
               the reported run-time is net fj-compute, excluding the IO device's writes */
            double io_start = monotonic_seconds();
            PyObject* result = PyObject_CallFunctionObjArgs(write_bit, (f == dw + 1) ? Py_True : Py_False, NULL);
            *paused_seconds_out += monotonic_seconds() - io_start;
            if (!result) {
                goto done;
            }
            Py_DECREF(result);
        }
        goto after_output;

    cold_input:
    {
        PyObject* result;
        int bit_value;
        double io_start = monotonic_seconds();
        result = PyObject_CallNoArgs(read_bit);
        *paused_seconds_out += monotonic_seconds() - io_start;
        if (!result) {
            if (PyErr_ExceptionMatches(eof_exception_type)) {
                PyErr_Clear();
                cause = TERM_EOF;
                goto done;
            }
            goto done;
        }
        bit_value = PyObject_IsTrue(result);
        Py_DECREF(result);
        if (bit_value < 0) {
            goto done;
        }
        if (mem_write_bit(self, in_addr, bit_value) < 0) {
            goto memory_error;
        }
        goto after_input;
    }
""", """    cold_flip_word_resolved:
        if (f - dw <= 1) {
            /* output. time the callback as paused, exactly like the input callback below - so
               the reported run-time is net fj-compute, excluding the IO device's writes */
            double io_start = monotonic_seconds();
            PyObject* result = PyObject_CallFunctionObjArgs(write_bit, (f == dw + 1) ? Py_True : Py_False, NULL);
            *paused_seconds_out += monotonic_seconds() - io_start;
            if (!result) {
                goto done;
            }
            Py_DECREF(result);
        }
        if (ip - in_lo_exclusive - 1 < dw) {
            /* input: the bit lands at in_addr before this op flips */
            PyObject* result;
            int bit_value;
            double io_start = monotonic_seconds();
            result = PyObject_CallNoArgs(read_bit);
            *paused_seconds_out += monotonic_seconds() - io_start;
            if (!result) {
                if (PyErr_ExceptionMatches(eof_exception_type)) {
                    PyErr_Clear();
                    cause = TERM_EOF;
                    goto done;
                }
                goto done;
            }
            bit_value = PyObject_IsTrue(result);
            Py_DECREF(result);
            if (bit_value < 0) {
                goto done;
            }
            if (mem_write_bit(self, in_addr, bit_value) < 0) {
                goto memory_error;
            }
        }
        goto after_input;
""")

p.write_text(s, encoding="utf-8")
print("fold (c) written")
