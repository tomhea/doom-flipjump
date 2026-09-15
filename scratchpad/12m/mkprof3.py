"""Instrument _fjcore.c for measurements 1d and 1e of the throughput plan. Never shipped.

Sections 7-9 of the plan rank levers by cache FOOTPRINT. Footprint is not time: an 8 MB reset
walk that the prefetcher streams through a 24 MB L3 may cost nothing, while a 0.3 MB leaf that
misses L2 on every dependent load may cost everything. Two builds, one generator:

    T  TIME BY OBJECT. Every 64 ops: record (word address of the op, rdtsc). Offline, each
       sample's tick delta is credited to the object its address falls in. Ranks objects by
       ms/frame -- the currency -- and gives ns/op per object, which is the cache level its
       dependent loads are served from. Overhead ~0.4 cycles/op, and rdtsc is not serialising.
       MUST run pinned, high priority, on a quiet machine (the runner checks; the run is 6 s).

    S  CACHE MODEL. Both streams (instruction fetch and flip target) through a simulated
       Golden Cove hierarchy for THIS machine -- L1D 48 KB 12-way, L2 1.25 MB 10-way, L3 24 MB
       12-way exclusive -- so every access is classified L1 / L2 / L3 / DRAM. Per-line counts of
       the ip-stream's L1 misses and L2 misses are dumped for the per-object join. On top, an
       LRU stack-distance histogram (bucketed Fenwick tree, error <= 16 lines) gives the
       what-if curve: hit rate versus cache size, so a footprint reduction can be priced BEFORE
       anyone builds it. Slow (minutes); timing is meaningless in this build.

Same discipline as mkprof2.py: the installed .pyd is never touched; the patched source builds in
a scratch dir and is loaded by path.

    python scratchpad/12m/mkprof3.py T <outdir>
    python scratchpad/12m/mkprof3.py S <outdir>
"""
import re
import sys
from pathlib import Path

SRC = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
MODE = sys.argv[1].upper()
assert MODE in ("T", "S"), MODE
OUT = Path(sys.argv[2]) / "_fjcore.c"
s = SRC.read_text(encoding="utf-8")


def sub1(old, new, what):
    global s
    assert s.count(old) == 1, "anchor %r: %d" % (what, s.count(old))
    s = s.replace(old, new, 1)


ANCHOR = "/* force-inline so run_flat_loop's literal width/ww arguments constant-fold per width */"

COMMON = r'''
#include <intrin.h>
#include <windows.h>
static void prof3_dump_u32(const char* envname, const uint32_t* arr, uint64_t unit, uint64_t n)
{
    const char* path = getenv(envname);
    FILE* f;
    uint64_t hdr[2];
    if (!path || !path[0] || !arr) return;
    f = fopen(path, "wb");
    if (!f) return;
    hdr[0] = unit; hdr[1] = n;
    fwrite(hdr, sizeof(uint64_t), 2, f);
    fwrite(arr, sizeof(uint32_t), (size_t)n, f);
    fclose(f);
    fprintf(stderr, "FJPROF3 wrote %s\n", path);
}
'''

# ---------------------------------------------------------------------------------------------
T_STATE = COMMON + r'''
/* ==== FJPROF3T: time by object (instrumented build only) ==================================== */
static uint32_t* g_t_ip = NULL;    /* word address of the op at each sample */
static uint64_t* g_t_tsc = NULL;   /* rdtsc at each sample */
static uint64_t g_t_n = 0, g_t_cap = 0;
#define P3_SAMPLE_EVERY 64
#define P3_TICK(wa) do { if ((ops & (P3_SAMPLE_EVERY - 1)) == 0 && g_t_n < g_t_cap) { \
        g_t_ip[g_t_n] = (uint32_t)(wa); g_t_tsc[g_t_n] = __rdtsc(); g_t_n++; } } while (0)

static void prof3_alloc(uint64_t flat_count, int cell_bytes)
{
    (void)flat_count; (void)cell_bytes;
    free(g_t_ip); free(g_t_tsc);
    g_t_cap = 24u * 1024u * 1024u;   /* 24M samples = 1.5G ops at 64 ops/sample */
    g_t_ip = (uint32_t*)malloc((size_t)g_t_cap * sizeof(uint32_t));
    g_t_tsc = (uint64_t*)malloc((size_t)g_t_cap * sizeof(uint64_t));
    g_t_n = 0;
}

static void prof3_report(void)
{
    /* TSC rate against the wall clock: rdtsc counts at a constant rate, not the core clock */
    LARGE_INTEGER qf, q0, q1;
    uint64_t t0, t1;
    double tsc_hz;
    QueryPerformanceFrequency(&qf);
    QueryPerformanceCounter(&q0); t0 = __rdtsc();
    Sleep(300);
    QueryPerformanceCounter(&q1); t1 = __rdtsc();
    tsc_hz = (double)(t1 - t0) * (double)qf.QuadPart / (double)(q1.QuadPart - q0.QuadPart);
    fprintf(stderr, "FJPROF3T samples=%llu every=%d tsc_hz=%.0f span_ticks=%llu\n",
            (unsigned long long)g_t_n, P3_SAMPLE_EVERY, tsc_hz,
            (unsigned long long)(g_t_n ? g_t_tsc[g_t_n - 1] - g_t_tsc[0] : 0));
    fflush(stderr);
    {
        const char* path = getenv("FJPROF_DUMP_TIME");
        FILE* f;
        if (path && path[0] && g_t_n) {
            f = fopen(path, "wb");
            if (f) {
                uint64_t hdr[3];
                hdr[0] = g_t_n; hdr[1] = P3_SAMPLE_EVERY; hdr[2] = (uint64_t)tsc_hz;
                fwrite(hdr, sizeof(uint64_t), 3, f);
                fwrite(g_t_ip, sizeof(uint32_t), (size_t)g_t_n, f);
                fwrite(g_t_tsc, sizeof(uint64_t), (size_t)g_t_n, f);
                fclose(f);
                fprintf(stderr, "FJPROF3 wrote %s\n", path);
            }
        }
    }
}
#define P3_ACCESS_IP(wa) ((void)0)
#define P3_ACCESS_FL(wa) ((void)0)
/* ==== end FJPROF3T ======================================================================== */
'''

# ---------------------------------------------------------------------------------------------
S_STATE = COMMON + r'''
/* ==== FJPROF3S: cache model + stack distance (instrumented build only) ===================== */
/* i7-12700H P-core (Golden Cove): L1D 48 KB 12-way (64 sets), L2 1.25 MB 10-way (2048 sets),
   L3 24 MB 12-way (32768 sets) modelled EXCLUSIVE of L2 (victims of L2 go to L3, an L3 hit is
   promoted back). Line = 64 B. Set index = low bits of the line number (no slice hashing). */
#define P3_L1_SETS 64u
#define P3_L1_WAYS 12u
#define P3_L2_SETS 2048u
#define P3_L2_WAYS 10u
#define P3_L3_SETS 32768u
#define P3_L3_WAYS 12u
#define P3_EMPTY 0xFFFFFFFFu
static uint32_t g_l1[P3_L1_SETS * P3_L1_WAYS];
static uint32_t g_l2[P3_L2_SETS * P3_L2_WAYS];
static uint32_t g_l3[P3_L3_SETS * P3_L3_WAYS];
static uint64_t g_hit[2][4];        /* [stream: 0 ip, 1 flip][level: 0 L1, 1 L2, 2 L3, 3 DRAM] */
static uint32_t* g_l1miss = NULL;   /* per line: ip-stream accesses not served by L1 */
static uint32_t* g_l2miss = NULL;   /* per line: ip-stream accesses not served by L1 or L2 */
static uint64_t g_lines = 0;
static int g_lshift = 4;

/* MRU-first set: returns 1 on hit (and moves the line to MRU); on miss inserts at MRU and
   writes the evicted line (or P3_EMPTY) to *victim. */
static inline int p3_set_touch(uint32_t* set, unsigned ways, uint32_t line, uint32_t* victim)
{
    unsigned i;
    for (i = 0; i < ways; i++) {
        if (set[i] == line) {
            for (; i > 0; i--) set[i] = set[i - 1];
            set[0] = line;
            *victim = P3_EMPTY;
            return 1;
        }
    }
    *victim = set[ways - 1];
    for (i = ways - 1; i > 0; i--) set[i] = set[i - 1];
    set[0] = line;
    return 0;
}
static inline int p3_set_remove(uint32_t* set, unsigned ways, uint32_t line)
{
    unsigned i;
    for (i = 0; i < ways; i++) {
        if (set[i] == line) {
            for (; i + 1 < ways; i++) set[i] = set[i + 1];
            set[ways - 1] = P3_EMPTY;
            return 1;
        }
    }
    return 0;
}
static inline void p3_l3_insert(uint32_t line)
{
    uint32_t v;
    if (line == P3_EMPTY) return;
    (void)p3_set_touch(&g_l3[(line % P3_L3_SETS) * P3_L3_WAYS], P3_L3_WAYS, line, &v);
}
/* returns the level that served the access: 0 L1, 1 L2, 2 L3, 3 DRAM */
static inline int p3_cache_access(uint32_t line)
{
    uint32_t v1, v2;
    if (p3_set_touch(&g_l1[(line % P3_L1_SETS) * P3_L1_WAYS], P3_L1_WAYS, line, &v1)) return 0;
    if (p3_set_touch(&g_l2[(line % P3_L2_SETS) * P3_L2_WAYS], P3_L2_WAYS, line, &v2)) return 1;
    /* L2 miss: look in L3 first (a hit is promoted out of it), THEN the L2 victim goes to L3
       (exclusive) -- the other order could evict the line being looked up. */
    {
        int in_l3 = p3_set_remove(&g_l3[(line % P3_L3_SETS) * P3_L3_WAYS], P3_L3_WAYS, line);
        p3_l3_insert(v2);
        return in_l3 ? 2 : 3;
    }
}

/* stack distance: last[line] = access index of its previous access; a Fenwick tree over
   buckets of P3_BUCKET accesses counts, per bucket, how many lines have their LAST access
   there. distance = lines seen before now - lines whose last access is <= last[line].
   The bucketing under-counts by at most P3_BUCKET-1 lines. */
#define P3_BUCKET 16u
static uint32_t* g_last = NULL;     /* per line: 1 + access index of the last access; 0 = never */
static int32_t* g_fen = NULL;       /* Fenwick over buckets, 1-based */
static uint64_t g_fen_n = 0;        /* number of buckets */
static uint64_t g_acc = 0;          /* accesses so far (both streams) */
static uint64_t g_seen = 0;         /* distinct lines seen */
static int32_t g_cur_cnt = 0;       /* lines whose last access is in the current (unflushed) bucket */
static uint64_t g_cur_bucket = 0;
static uint64_t g_sd_hist[2][40];   /* [stream][floor(log2(d+1))]; [.][39] = cold */
static uint64_t g_sd_thr[2][4];     /* [stream][d < 768, < 20480, < 393216, >=] */
static int g_fen_overflow = 0;
/* TLB model, 4 KB pages: page = word address >> (12 - log2(cell bytes)). */
#define P3_DTLB_SETS 16u
#define P3_DTLB_WAYS 6u
#define P3_STLB_SETS 128u
#define P3_STLB_WAYS 16u
static uint32_t g_dtlb[P3_DTLB_SETS * P3_DTLB_WAYS];
static uint32_t g_stlb[P3_STLB_SETS * P3_STLB_WAYS];
static uint64_t g_tlb[2][3];        /* [stream][0 DTLB hit, 1 STLB hit, 2 page walk] */
static uint32_t* g_dtlbmiss = NULL; /* per line: ip-stream accesses that missed the L1 DTLB */
static uint32_t* g_stlbmiss = NULL; /* per line: ip-stream accesses that walked */
static int g_pshift = 10;           /* words per page: 1024 at 4-byte cells, 512 at 8 */
/* MODIFY-THEN-EXECUTE: a flip that lands in the words of an op fetched d ops later puts a
   store->load forward on the dependent chain (d=1) or trains the memory-disambiguation
   predictor to block every later fetch behind the flip store (any small d). Ring of the last
   16 flip targets; at each fetch the smallest d in 1..16 is histogrammed. self_j = the op
   flips its OWN jump word (the engine re-reads j after the flip for exactly this case). */
static uint32_t g_ring_w[16];
static uint64_t g_ring_t[16];
static unsigned g_ring_i = 0;
static uint64_t g_op_idx = 0, g_cur_wa = 0;
static uint64_t g_mte[17], g_self_f = 0, g_self_j = 0;

static inline void p3_fen_add(uint64_t b, int32_t v)   /* b is 0-based bucket */
{
    for (b += 1; b <= g_fen_n; b += b & (~b + 1)) g_fen[b] += v;
}
static inline int64_t p3_fen_prefix(uint64_t b)          /* sum of buckets 0..b */
{
    int64_t r = 0;
    for (b += 1; b > 0; b -= b & (~b + 1)) r += g_fen[b];
    return r;
}
static inline void p3_stack_access(uint32_t line, int stream)
{
    uint64_t now = g_acc++;
    uint64_t nb = now / P3_BUCKET;
    uint32_t prev = g_last[line];
    if (nb != g_cur_bucket) {
        if (g_cur_bucket < g_fen_n) p3_fen_add(g_cur_bucket, g_cur_cnt);
        else g_fen_overflow = 1;
        g_cur_cnt = 0;
        g_cur_bucket = nb;
    }
    if (prev == 0) {
        g_sd_hist[stream][39]++;
        g_sd_thr[stream][3]++;
        g_seen++;
    } else {
        uint64_t pt = (uint64_t)prev - 1;
        uint64_t pb = pt / P3_BUCKET;
        int64_t upto, d;
        unsigned bin;
        if (pb == nb) { upto = p3_fen_prefix(pb) + g_cur_cnt; g_cur_cnt--; }
        else { upto = p3_fen_prefix(pb); p3_fen_add(pb, -1); }
        d = (int64_t)g_seen - upto;       /* distinct lines with last access in (pt, now) */
        if (d < 0) d = 0;
        bin = 0;
        while ((d + 1) >> (bin + 1)) bin++;
        if (bin > 38) bin = 38;
        g_sd_hist[stream][bin]++;
        g_sd_thr[stream][d < 768 ? 0 : d < 20480 ? 1 : d < 393216 ? 2 : 3]++;
    }
    g_cur_cnt++;
    g_last[line] = (uint32_t)(now + 1);
}

static int p3_tlb_access(uint64_t wa)
{
    uint32_t page = (uint32_t)(wa >> g_pshift);
    uint32_t v;
    if (p3_set_touch(&g_dtlb[(page % P3_DTLB_SETS) * P3_DTLB_WAYS], P3_DTLB_WAYS, page, &v)) return 0;
    if (p3_set_touch(&g_stlb[(page % P3_STLB_SETS) * P3_STLB_WAYS], P3_STLB_WAYS, page, &v)) return 1;
    return 2;
}

static void p3_access(uint64_t wa, int stream)
{
    uint32_t line = (uint32_t)(wa >> g_lshift);
    int lvl;
    {
        int t = p3_tlb_access(wa);
        g_tlb[stream][t]++;
        if (stream == 0 && line < g_lines) {
            if (t >= 1) g_dtlbmiss[line]++;
            if (t >= 2) g_stlbmiss[line]++;
        }
    }
    if (stream == 0) {
        unsigned k;
        uint64_t best = 0;
        for (k = 0; k < 16; k++) {
            if (g_ring_w[k] == (uint32_t)wa || g_ring_w[k] == (uint32_t)wa + 1u) {
                uint64_t d = g_op_idx - g_ring_t[k];
                if (d >= 1 && d <= 16 && (best == 0 || d < best)) best = d;
            }
        }
        g_mte[best]++;
        g_cur_wa = wa;
        g_op_idx++;
    } else {
        if (wa == g_cur_wa) g_self_f++;
        if (wa == g_cur_wa + 1) g_self_j++;
        g_ring_w[g_ring_i] = (uint32_t)wa;
        g_ring_t[g_ring_i] = g_op_idx - 1;
        g_ring_i = (g_ring_i + 1) & 15u;
    }
    if (line >= g_lines) return;
    lvl = p3_cache_access(line);
    g_hit[stream][lvl]++;
    if (stream == 0) {
        if (lvl >= 1) g_l1miss[line]++;
        if (lvl >= 2) g_l2miss[line]++;
    }
    p3_stack_access(line, stream);
}
#define P3_ACCESS_IP(wa) p3_access((wa), 0)
#define P3_ACCESS_FL(wa) p3_access((wa), 1)
#define P3_TICK(wa) ((void)0)

static void prof3_alloc(uint64_t flat_count, int cell_bytes)
{
    uint64_t maxacc = 1200000000ull;
    const char* e = getenv("FJPROF3_MAXACC");
    if (e && e[0]) maxacc = strtoull(e, NULL, 10);
    g_lshift = (cell_bytes == 4) ? 4 : 3;
    g_lines = (flat_count >> g_lshift) + 1;
    free(g_l1miss); free(g_l2miss); free(g_last); free(g_fen);
    g_l1miss = (uint32_t*)calloc((size_t)g_lines, sizeof(uint32_t));
    g_l2miss = (uint32_t*)calloc((size_t)g_lines, sizeof(uint32_t));
    g_last = (uint32_t*)calloc((size_t)g_lines, sizeof(uint32_t));
    g_fen_n = maxacc / P3_BUCKET + 2;
    g_fen = (int32_t*)calloc((size_t)g_fen_n + 1, sizeof(int32_t));
    memset(g_l1, 0xFF, sizeof(g_l1)); memset(g_l2, 0xFF, sizeof(g_l2)); memset(g_l3, 0xFF, sizeof(g_l3));
    memset(g_hit, 0, sizeof(g_hit)); memset(g_sd_hist, 0, sizeof(g_sd_hist)); memset(g_sd_thr, 0, sizeof(g_sd_thr));
    g_acc = g_seen = 0; g_cur_cnt = 0; g_cur_bucket = 0; g_fen_overflow = 0;
    g_pshift = (cell_bytes == 4) ? 10 : 9;
    free(g_dtlbmiss); free(g_stlbmiss);
    g_dtlbmiss = (uint32_t*)calloc((size_t)g_lines, sizeof(uint32_t));
    g_stlbmiss = (uint32_t*)calloc((size_t)g_lines, sizeof(uint32_t));
    memset(g_dtlb, 0xFF, sizeof(g_dtlb)); memset(g_stlb, 0xFF, sizeof(g_stlb)); memset(g_tlb, 0, sizeof(g_tlb));
    memset(g_ring_w, 0xFF, sizeof(g_ring_w)); memset(g_ring_t, 0, sizeof(g_ring_t)); g_ring_i = 0;
    g_op_idx = 0; g_cur_wa = 0; memset(g_mte, 0, sizeof(g_mte)); g_self_f = g_self_j = 0;
    fprintf(stderr, "FJPROF3S alloc: lines=%llu lshift=%d fen_buckets=%llu (%.0f MB)\n",
            (unsigned long long)g_lines, g_lshift, (unsigned long long)g_fen_n,
            (double)g_fen_n * 4.0 / 1048576.0);
}

static void prof3_report(void)
{
    static const char* SN[2] = {"IP", "FLIP"};
    int st, k;
    for (st = 0; st < 2; st++) {
        uint64_t tot = g_hit[st][0] + g_hit[st][1] + g_hit[st][2] + g_hit[st][3];
        fprintf(stderr, "FJPROF3S CACHE %-4s total=%llu L1=%llu (%.2f%%) L2=%llu (%.2f%%) L3=%llu (%.2f%%) DRAM=%llu (%.2f%%)\n",
                SN[st], (unsigned long long)tot,
                (unsigned long long)g_hit[st][0], tot ? 100.0 * g_hit[st][0] / tot : 0.0,
                (unsigned long long)g_hit[st][1], tot ? 100.0 * g_hit[st][1] / tot : 0.0,
                (unsigned long long)g_hit[st][2], tot ? 100.0 * g_hit[st][2] / tot : 0.0,
                (unsigned long long)g_hit[st][3], tot ? 100.0 * g_hit[st][3] / tot : 0.0);
    }
    for (st = 0; st < 2; st++) {
        fprintf(stderr, "FJPROF3S STACKTHR %-4s lt768=%llu lt20480=%llu lt393216=%llu ge=%llu\n", SN[st],
                (unsigned long long)g_sd_thr[st][0], (unsigned long long)g_sd_thr[st][1],
                (unsigned long long)g_sd_thr[st][2], (unsigned long long)g_sd_thr[st][3]);
        fprintf(stderr, "FJPROF3S STACKHIST %-4s", SN[st]);
        for (k = 0; k < 40; k++) fprintf(stderr, " %llu", (unsigned long long)g_sd_hist[st][k]);
        fprintf(stderr, "\n");
    }
    for (st = 0; st < 2; st++) {
        uint64_t tt = g_tlb[st][0] + g_tlb[st][1] + g_tlb[st][2];
        fprintf(stderr, "FJPROF3S TLB %-4s total=%llu DTLB=%llu (%.2f%%) STLB=%llu (%.2f%%) WALK=%llu (%.3f%%)\n", SN[st],
                (unsigned long long)tt, (unsigned long long)g_tlb[st][0], tt ? 100.0 * g_tlb[st][0] / tt : 0.0,
                (unsigned long long)g_tlb[st][1], tt ? 100.0 * g_tlb[st][1] / tt : 0.0,
                (unsigned long long)g_tlb[st][2], tt ? 100.0 * g_tlb[st][2] / tt : 0.0);
    }
    fprintf(stderr, "FJPROF3S MTE ops=%llu self_f=%llu self_j=%llu none=%llu", (unsigned long long)g_op_idx,
            (unsigned long long)g_self_f, (unsigned long long)g_self_j, (unsigned long long)g_mte[0]);
    for (k = 1; k <= 16; k++) fprintf(stderr, " d%d=%llu", k, (unsigned long long)g_mte[k]);
    fprintf(stderr, "\n");
    fprintf(stderr, "FJPROF3S accesses=%llu distinct_lines=%llu fen_overflow=%d\n",
            (unsigned long long)g_acc, (unsigned long long)g_seen, g_fen_overflow);
    fflush(stderr);
    prof3_dump_u32("FJPROF_DUMP_L1MISS", g_l1miss, 1ull << g_lshift, g_lines);
    prof3_dump_u32("FJPROF_DUMP_L2MISS", g_l2miss, 1ull << g_lshift, g_lines);
    prof3_dump_u32("FJPROF_DUMP_DTLBMISS", g_dtlbmiss, 1ull << g_lshift, g_lines);
    prof3_dump_u32("FJPROF_DUMP_STLBMISS", g_stlbmiss, 1ull << g_lshift, g_lines);
}
/* ==== end FJPROF3S ======================================================================== */
'''

sub1(ANCHOR, (T_STATE if MODE == "T" else S_STATE) + "\n" + ANCHOR, "prof state")

sub1("""    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);""",
     """    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);
    prof3_alloc(low_max_end, m->cell_bytes);""",
     "alloc")

sub1("""            word_address = ip >> ww;
            if (word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }""",
     """            word_address = ip >> ww;
            P3_ACCESS_IP(word_address);
            if (word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }""", "ip hit")

sub1("""            flip_word_address = f >> ww;
            if (flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }""",
     """            flip_word_address = f >> ww;
            P3_ACCESS_FL(flip_word_address);
            if (flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }""", "flip hit")

# the sample point: first `jump_word_ready:` + `ops++;` in the file is the FLAT loop's
s, n = re.subn(r'(jump_word_ready:\s*\n\s*)ops\+\+;', r'\1P3_TICK(word_address);\n            ops++;', s, count=1)
assert n == 1, "tick anchor"

sub1("""        return build_run_result(self, fast_cause, fast_ops, NULL, 0, 0, fast_paused);""",
     """        prof3_report();
        return build_run_result(self, fast_cause, fast_ops, NULL, 0, 0, fast_paused);""",
     "flat return")

# the cell_bytes decision must precede the alloc anchor (it does: lines ~781-793); assert it
assert s.index("m->cell_bytes = (force64") < s.index("prof3_alloc(low_max_end"), "cell_bytes decided after alloc"

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(s, encoding="utf-8")
print("wrote %s (mode %s)" % (OUT, MODE))
