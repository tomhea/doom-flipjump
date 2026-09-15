"""Build an INSTRUMENTED copy of _fjcore that histograms which pages the program touches.

WHY. The memprobe micro-benchmark showed the fj access pattern runs at 330 M/s when its working
set is cache-resident and 25-50 M/s when it is not, with the cliff at this machine's 24 MB L3.
The DOOM binary measures ~125 M/s -- far better than a uniformly-random 768 MB walk (25.8 M/s),
so its accesses are already clustered. The question that decides what is achievable is therefore
NOT "how big is the array" but "HOW BIG IS THE HOT SET" -- how much of that 768 MB the program
actually touches, and how concentrated the touches are.

That is a runtime property; no amount of reading the emitter can produce it. So: instrument the
two hot-loop touches (the instruction word at `ip` and the flip target), count per 4 KB page, and
report the working-set curve -- how many megabytes cover 50/80/90/99% of all touches.

The instrumented build is written to a scratch directory and loaded by file path, so the installed
`flipjump/interpreter/_fjcore.pyd` that every gate depends on is NEVER touched.
"""
import re
import shutil
import sys
from pathlib import Path

SRC = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".") / "_fjcore.c"

s = SRC.read_text(encoding="utf-8")

# ── 1. the profiling state + the dump, injected after the includes ────────────────────────────
ANCHOR = "/* force-inline so run_flat_loop's literal width/ww arguments constant-fold per width */"
PROF = r'''
/* ==== FJPROF: page-touch histogram (instrumented build only, never shipped) ============== */
#include <stdlib.h>
static uint32_t* g_prof = NULL;
static uint64_t  g_prof_pages = 0;
static uint64_t  g_prof_touches = 0;
/* GRANULARITY. 512 words = a 4 KB page; 8 words = a 64 B CACHE LINE. The page view
   OVERSTATES the working set -- a page counts in full when one word in it is touched --
   and it is the cache-line count that predicts what halving the element size buys, since
   untouched holes never enter the cache at all. Set FJPROF_WORDS_PER_UNIT to pick. */
static uint64_t g_prof_unit = 512ull;
static uint64_t g_prof_unit_bytes = 4096ull;
#define PROF_WORDS_PER_PAGE g_prof_unit
#define PROF_HIT(wa) do { if (g_prof) { uint64_t _p = (wa) / PROF_WORDS_PER_PAGE; \
    if (_p < g_prof_pages) { g_prof[_p]++; g_prof_touches++; } } } while (0)

static int prof_cmp_desc(const void* a, const void* b)
{
    uint32_t x = *(const uint32_t*)a, y = *(const uint32_t*)b;
    return (x < y) ? 1 : ((x > y) ? -1 : 0);
}

static void prof_report(void)
{
    uint64_t i, touched = 0;
    uint32_t* sorted;
    double cum;
    const double pct[] = {0.50, 0.80, 0.90, 0.95, 0.99, 1.00};
    const char* names[] = {"50%", "80%", "90%", "95%", "99%", "100%"};
    int k;
    if (!g_prof || !g_prof_touches) {
        fprintf(stderr, "FJPROF: nothing recorded\n");
        return;
    }
    for (i = 0; i < g_prof_pages; i++) {
        if (g_prof[i]) touched++;
    }
    sorted = (uint32_t*)malloc((size_t)g_prof_pages * sizeof(uint32_t));
    if (!sorted) return;
    memcpy(sorted, g_prof, (size_t)g_prof_pages * sizeof(uint32_t));
    qsort(sorted, (size_t)g_prof_pages, sizeof(uint32_t), prof_cmp_desc);

    fprintf(stderr, "\nFJPROF ==================================================================\n");
    fprintf(stderr, "FJPROF flat array : %llu pages of 4 KB = %.1f MB\n",
            (unsigned long long)g_prof_pages, g_prof_pages * 4096.0 / (1024*1024));
    fprintf(stderr, "FJPROF touches    : %llu\n", (unsigned long long)g_prof_touches);
    fprintf(stderr, "FJPROF pages EVER touched: %llu = %.1f MB (%.1f%% of the array)\n",
            (unsigned long long)touched, touched * 4096.0 / (1024*1024),
            100.0 * touched / (double)g_prof_pages);
    fprintf(stderr, "FJPROF --- working-set curve: MB of 4 KB pages covering N%% of all touches --\n");
    for (k = 0; k < 6; k++) {
        uint64_t need = (uint64_t)(pct[k] * (double)g_prof_touches);
        uint64_t acc = 0, n = 0;
        for (i = 0; i < g_prof_pages && acc < need; i++) {
            acc += sorted[i];
            n++;
        }
        cum = n * (double)g_prof_unit_bytes / (1024*1024);
        fprintf(stderr, "FJPROF   %-5s of touches live in %8llu pages = %8.2f MB\n",
                names[k], (unsigned long long)n, cum);
    }
    fprintf(stderr, "FJPROF ==================================================================\n");
    fflush(stderr);
    free(sorted);
    {   /* Dump the raw per-unit counts so ONE run answers every granularity question offline:
           page utilisation, 2 MB-region occupancy, contiguity, and WHERE the sparse regions
           are. Re-running the game per granularity costs minutes each and the run-to-run
           variance makes the results hard to compare anyway. */
        const char* dump = getenv("FJPROF_DUMP");
        if (dump && dump[0]) {
            FILE* f = fopen(dump, "wb");
            if (f) {
                uint64_t hdr[2];
                hdr[0] = g_prof_unit;
                hdr[1] = g_prof_pages;
                fwrite(hdr, sizeof(uint64_t), 2, f);
                fwrite(g_prof, sizeof(uint32_t), (size_t)g_prof_pages, f);
                fclose(f);
                fprintf(stderr, "FJPROF wrote %s (%llu units of %llu words each)\n", dump,
                        (unsigned long long)g_prof_pages, (unsigned long long)g_prof_unit);
                fflush(stderr);
            }
        }
    }
}
/* ==== end FJPROF ========================================================================= */

'''
assert s.count(ANCHOR) == 1, "anchor for prof state not found"
s = s.replace(ANCHOR, PROF + ANCHOR, 1)

# ── 2. allocate the histogram alongside the flat array ────────────────────────────────────────
A2 = """    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);"""
B2 = """    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);
    {
        const char* pu = getenv("FJPROF_WORDS_PER_UNIT");
        g_prof_unit = (pu && atoi(pu) > 0) ? (uint64_t)atoi(pu) : 512ull;
        g_prof_unit_bytes = g_prof_unit * 8ull;
    }
    g_prof_pages = (low_max_end + PROF_WORDS_PER_PAGE - 1) / PROF_WORDS_PER_PAGE;
    free(g_prof);
    g_prof = (uint32_t*)calloc((size_t)g_prof_pages, sizeof(uint32_t));
    g_prof_touches = 0;"""
assert s.count(A2) == 1, "anchor for prof alloc not found"
s = s.replace(A2, B2, 1)

# ── 3. the two hot-loop touches ───────────────────────────────────────────────────────────────
A3 = """            word_address = ip >> ww;
            if (word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }"""
B3 = """            word_address = ip >> ww;
            PROF_HIT(word_address);
            if (word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }"""
assert s.count(A3) == 1, "anchor for ip touch not found"
s = s.replace(A3, B3, 1)

A4 = """            flip_word_address = f >> ww;
            if (flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }"""
B4 = """            flip_word_address = f >> ww;
            PROF_HIT(flip_word_address);
            if (flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }"""
assert s.count(A4) == 1, "anchor for flip touch not found"
s = s.replace(A4, B4, 1)

# ── 4. report when the run ends. BOTH return paths: the run() dispatcher has a FLAT fast path
#      with its own build_run_result (the one the DOOM binary actually takes) and a separate
#      generic-loop path. Instrumenting only the generic one printed nothing at all.
A5 = """        return build_run_result(self, loop_cause, loop_ops, last_ops_ring, last_ops_length, loop_ring_writes,
                                loop_paused);"""
B5 = """        prof_report();
        return build_run_result(self, loop_cause, loop_ops, last_ops_ring, last_ops_length, loop_ring_writes,
                                loop_paused);"""
assert s.count(A5) == 1, "anchor for generic prof report not found"
s = s.replace(A5, B5, 1)

A6 = """        return build_run_result(self, fast_cause, fast_ops, NULL, 0, 0, fast_paused);"""
B6 = """        prof_report();
        return build_run_result(self, fast_cause, fast_ops, NULL, 0, 0, fast_paused);"""
assert s.count(A6) == 1, "anchor for FLAT prof report not found"
s = s.replace(A6, B6, 1)

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(s, encoding="utf-8")
print("wrote instrumented %s (%d bytes)" % (OUT, len(s)))
