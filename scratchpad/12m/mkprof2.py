"""Instrument _fjcore.c for measurements 1a and 1c of the throughput plan. Never shipped.

1a  SPLIT THE TRACE BY ACCESS TYPE. Every op touches memory twice: the instruction pair at `ip`
    (the DEPENDENT chain -- the next ip is the value just loaded) and the flip target (off the
    critical path). `mkprof.py` histogrammed both into one array, so it is unknown whether the
    chain lives in a small, packable instruction stream or is spread across everything. Two
    arrays now: FJPROF_DUMP gets the ip-stream, FJPROF_DUMP_FLIP gets the flip targets.

1c  JUMP-DISTANCE CENSUS. What fraction of ops fall through (j == ip + 2w)? That decides whether
    the hardware prefetcher already covers the instruction stream, whether turning the ip=j data
    dependency into a predictable branch (plan 5.1) can pay, and whether block execution (2b)
    is viable at all. Counted per op at the jump-word site: fall-through, loop (j == ip), near
    (within +-64 words), far.

Written as its own generator rather than more string surgery on mkprof.py, which the plan
already flags as fragile. Same discipline: the installed .pyd is never touched; the patched
source builds into a scratch dir and is loaded by path.

    python scratchpad/12m/mkprof2.py <outdir>
"""
import re
import sys
from pathlib import Path

SRC = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
OUT = Path(sys.argv[1]) / "_fjcore.c"
s = SRC.read_text(encoding="utf-8")


def sub1(old, new, what):
    global s
    assert s.count(old) == 1, "anchor %r: %d" % (what, s.count(old))
    s = s.replace(old, new, 1)


ANCHOR = "/* force-inline so run_flat_loop's literal width/ww arguments constant-fold per width */"
sub1(ANCHOR, r'''
/* ==== FJPROF2: split access census + jump-distance census (instrumented build only) ======== */
static uint32_t* g_ip = NULL;      /* touches at the instruction pair: the dependent chain */
static uint32_t* g_fl = NULL;      /* touches at the flip target: off the critical path */
static uint64_t g_units = 0, g_unit = 8;          /* 8 words = one 64 B cache line */
static uint64_t g_ip_t = 0, g_fl_t = 0;
static uint64_t g_j_fall = 0, g_j_loop = 0, g_j_near = 0, g_j_far = 0;
#define HIT_IP(wa) do { if (g_ip) { uint64_t _p = (wa) / g_unit; if (_p < g_units) { g_ip[_p]++; g_ip_t++; } } } while (0)
#define HIT_FL(wa) do { if (g_fl) { uint64_t _p = (wa) / g_unit; if (_p < g_units) { g_fl[_p]++; g_fl_t++; } } } while (0)

static void prof2_dump(const char* envname, uint32_t* arr)
{
    const char* path = getenv(envname);
    FILE* f;
    uint64_t hdr[2];
    if (!path || !path[0] || !arr) return;
    f = fopen(path, "wb");
    if (!f) return;
    hdr[0] = g_unit; hdr[1] = g_units;
    fwrite(hdr, sizeof(uint64_t), 2, f);
    fwrite(arr, sizeof(uint32_t), (size_t)g_units, f);
    fclose(f);
    fprintf(stderr, "FJPROF2 wrote %s\n", path);
}

static void prof2_report(void)
{
    uint64_t tot = g_j_fall + g_j_loop + g_j_near + g_j_far;
    fprintf(stderr, "FJPROF2 touches: ip-stream %llu, flip-target %llu\n",
            (unsigned long long)g_ip_t, (unsigned long long)g_fl_t);
    fprintf(stderr, "FJPROF2 JUMPS total=%llu fallthrough=%llu (%.2f%%) loop=%llu (%.2f%%) near=%llu (%.2f%%) far=%llu (%.2f%%)\n",
            (unsigned long long)tot,
            (unsigned long long)g_j_fall, tot ? 100.0 * g_j_fall / tot : 0.0,
            (unsigned long long)g_j_loop, tot ? 100.0 * g_j_loop / tot : 0.0,
            (unsigned long long)g_j_near, tot ? 100.0 * g_j_near / tot : 0.0,
            (unsigned long long)g_j_far,  tot ? 100.0 * g_j_far  / tot : 0.0);
    fflush(stderr);
    prof2_dump("FJPROF_DUMP", g_ip);
    prof2_dump("FJPROF_DUMP_FLIP", g_fl);
}
/* ==== end FJPROF2 ========================================================================= */

''' + ANCHOR, "prof state")

sub1("""    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);""",
     """    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);
    g_units = (low_max_end + g_unit - 1) / g_unit;
    free(g_ip); free(g_fl);
    g_ip = (uint32_t*)calloc((size_t)g_units, sizeof(uint32_t));
    g_fl = (uint32_t*)calloc((size_t)g_units, sizeof(uint32_t));
    g_ip_t = g_fl_t = 0; g_j_fall = g_j_loop = g_j_near = g_j_far = 0;""",
     "alloc")

sub1("""            word_address = ip >> ww;
            if (word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }""",
     """            word_address = ip >> ww;
            HIT_IP(word_address);
            if (word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }""", "ip hit")

sub1("""            flip_word_address = f >> ww;
            if (flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }""",
     """            flip_word_address = f >> ww;
            HIT_FL(flip_word_address);
            if (flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }""", "flip hit")

# the jump census: first `jump_word_ready:` + `ops++;` in the file is the FLAT loop's
s, n = re.subn(r'(jump_word_ready:\s*\n\s*)ops\+\+;',
               r'''\1{
                int64_t _d = (int64_t)j - (int64_t)ip;
                if (j == ip) g_j_loop++;
                else if (_d == (int64_t)(2 * width)) g_j_fall++;
                else if (_d > -(int64_t)(64 * width) && _d < (int64_t)(64 * width)) g_j_near++;
                else g_j_far++;
            }
            ops++;''', s, count=1)
assert n == 1, "jump anchor"

sub1("""        return build_run_result(self, fast_cause, fast_ops, NULL, 0, 0, fast_paused);""",
     """        prof2_report();
        return build_run_result(self, fast_cause, fast_ops, NULL, 0, 0, fast_paused);""",
     "flat return")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(s, encoding="utf-8")
print("wrote %s" % OUT)
