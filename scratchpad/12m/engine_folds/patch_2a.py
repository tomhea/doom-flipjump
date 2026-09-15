"""2a, done properly IN THE ENGINE: read the jump word BEFORE the flip's store.

Section 10.5 killed "2a" on a microbenchmark (`micro/storewait.c`: engine order vs bare chase
+0.02 ns at L1). Section 12 then measured the loop's branches and its layout to be worth nothing,
which leaves the per-op MEMORY CHAIN as the only place the time can be -- and this is the one edit
that shortens it. The measurement-process doc says a synthetic curve is not a measurement, so the
idea is re-tested here on the real engine and the real game rather than on a chase.

THE POINT. Per op the loop stores to flat[f >> ww] and then loads flat[(ip >> ww) + 1]. Both
addresses are computed at run time, so the COMPILER may not reorder them: the jump-word load --
which is the whole ip -> ip dependence chain -- is emitted after the store, and only the hardware's
memory-disambiguation predictor can issue it early. Every mispredict is a pipeline flush, and 4.1%
of the game's ops (measured, section 10.5) really do flip their own jump word, so the predictor is
being trained against by the program itself.

THE EDIT. Load the jump word BEFORE the store, and handle the one case where the store changes it
in a REGISTER: if the flip targeted word_address + 1 then the new jump word is exactly `flipped`,
which is already in hand. No re-load, no memory dependence, same values.
  - The load moves only across the flip's STORE, never across an IO callback or a cold path: it
    sits after both IO tests, after the flip's span check and after the flip target's sentinel
    check, so every path that can write memory behind our back (`cold_output`, `cold_input`,
    `cold_flip_out_of_span`'s mem_flip_bit, `cold_flip_garbage`) is taken BEFORE the hoisted load.
    `after_flip` -- the return label of the out-of-span flip -- keeps the original post-store read.
  - The jump word's own span check moves with it (it depends on ip, not on the store).
  - Unaligned ops park word_address at (uint64_t)-2, so word_address + 1 = -1 fails the span check
    and takes cold_jump_word_slow exactly as before, and can never equal flip_word_address.
  - The sentinel test is applied to the FINAL j, as before.
"""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:90])
    s = s.replace(old, new)


rep("""        flip_value_ready:
            {
                const uint64_t flipped = flip_value ^ (1ull << (f & bit_mask));
                if (cell32) {
                    flat32[flip_word_address] = (uint32_t)flipped;
                } else {
                    flat64[flip_word_address] = flipped;
                }
            }
        after_flip:

            /* read jump word (after the flip - the flip may modify it). word_address is
               (uint64_t)-2 for unaligned ops, so they take the slow read too. */
            if (word_address + 1 >= flat_count) {
                goto cold_jump_word_slow;
            }
            j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];
            if (cell32 ? (j == (uint64_t)FLAT_GARBAGE_MAGIC32)
                       : (width <= 32 ? ((j & GARBAGE_SENTINEL) != 0)
                                      : (j == FLAT_GARBAGE_MAGIC))) {
                goto cold_jump_word_garbage;
            }
        jump_word_ready:
""", """        flip_value_ready:
            {
                /* 2a: READ THE JUMP WORD BEFORE THE FLIP'S STORE. The jump word IS the ip -> ip
                   dependence chain; behind the store it can only issue on a memory-disambiguation
                   prediction, and the program mistrains that predictor (4.1% of the game's ops
                   flip their own jump word). Read first, then patch in a REGISTER: when the flip
                   targeted word_address + 1 the new jump word is exactly `flipped`.
                   Safe because every path that can write memory behind our back (both IO
                   callbacks, the out-of-span flip, the garbage re-check) is taken above this
                   point; `after_flip` keeps the original post-store read for the one that
                   returns here. */
                const uint64_t flipped = flip_value ^ (1ull << (f & bit_mask));
                const int jump_in_span = (word_address + 1 < flat_count);
                if (jump_in_span) {
                    j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];
                }
                if (cell32) {
                    flat32[flip_word_address] = (uint32_t)flipped;
                } else {
                    flat64[flip_word_address] = flipped;
                }
                if (!jump_in_span) {
                    goto cold_jump_word_slow; /* after the store, exactly as before */
                }
                if (flip_word_address == word_address + 1) {
                    j = flipped; /* the flip rewrote the jump word: no re-load, it is in hand */
                }
            }
            if (cell32 ? (j == (uint64_t)FLAT_GARBAGE_MAGIC32)
                       : (width <= 32 ? ((j & GARBAGE_SENTINEL) != 0)
                                      : (j == FLAT_GARBAGE_MAGIC))) {
                goto cold_jump_word_garbage;
            }
            goto jump_word_ready;

        after_flip:
            /* the out-of-span flip returns here: its mem_flip_bit may have written ANY word, so
               this path re-reads the jump word AFTER the store, as the loop always did */
            if (word_address + 1 >= flat_count) {
                goto cold_jump_word_slow;
            }
            j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];
            if (cell32 ? (j == (uint64_t)FLAT_GARBAGE_MAGIC32)
                       : (width <= 32 ? ((j & GARBAGE_SENTINEL) != 0)
                                      : (j == FLAT_GARBAGE_MAGIC))) {
                goto cold_jump_word_garbage;
            }
        jump_word_ready:
""")
p.write_text(s, encoding="utf-8")
print("2a written")
