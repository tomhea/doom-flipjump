/* =============================================================================================
 * ⚠⚠ WITHDRAWN -- THE CHAIN NUMBERS IN THIS FILE ARE WRONG. DO NOT QUOTE THEM. ⚠⚠
 *
 * The dependent chase here is built as `a[i] = random() & mask` and followed with `cur = a[cur]`.
 * That is a random FUNCTIONAL GRAPH, not a permutation: from any start it walks ~sqrt(N) steps
 * and then falls into a rho-cycle of length ~sqrt(N). For a 100M-slot array that cycle is a few
 * thousand nodes -- a few hundred KB -- so the chase sat in L2 NO MATTER HOW LARGE the array was.
 * It reported ~370 M/s at a 64 MB footprint, which is impossible for a serialized DRAM chase.
 *
 * That impossible number produced the "throughput is governed by page count" curve, which
 * predicted a ~4x win from huge pages. THE DIRECT EXPERIMENT REFUTED IT: real THP on the real
 * DOOM binary under WSL, alternated three times, measured 76.9 vs 75.5 M fj/s = +1.9%, noise.
 *
 * Replaced by `latprobe.c`, which builds ONE Sattolo cycle covering every selected slot exactly
 * once, so the footprint is genuinely resident. Its curve locates the real knee at the L2
 * boundary and matches the binary's measured throughput.
 *
 * Kept in the tree, annotated rather than deleted, because the failure mode is subtle, easy to
 * reproduce by accident, and cost this investigation a wrong diagnosis that was reported as a
 * conclusion before it was checked.
 * ============================================================================================= */

/* Is the DOOM binary TLB-bound rather than cache-bound? Decisive A/B.
 *
 * MEASURED on the real binary (instrumented _fjcore, 14 frames, 580,128,989 touches):
 *     distinct 64 B cache lines touched : 26.67 MB   <- FITS in this machine's 24 MB L3
 *     99% of touches within             : 14.07 MB   <- comfortably L3-resident
 *     distinct 4 KB pages touched       : 23,397     <- does NOT fit a ~2048-entry L2 TLB
 *
 * So the DATA is cache-resident while the PAGE MAPPINGS are not. If that is the real cost,
 * then touching the SAME number of cache lines should be much slower when those lines are
 * spread thinly over many pages than when they are packed densely -- with identical cache
 * footprint in both cases. That is the only difference this benchmark varies.
 *
 * DENSE  : L lines packed contiguously          -> L/64 pages
 * SPREAD : the same L lines at ~19 lines per 4 KB page, over a 768 MB range -> ~L/19 pages
 *
 * Same L, same bytes in cache, ~3.4x the page count. If SPREAD is much slower, the diagnosis
 * is the TLB and the cure is large pages (or a denser image), not a smaller array.
 *
 * cl /O2 tlbprobe.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>

static double now_sec(void)
{
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}

static uint64_t xs(uint64_t* s)
{
    uint64_t x = *s;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *s = x;
    return x;
}

/* Build an index list of `lines` distinct cache lines.
   dense=1: lines 0..L-1 of the arena.
   dense=0: `per_page` lines inside each 4 KB page, walking pages across the whole arena. */
static uint64_t* build_targets(uint64_t lines, int dense, uint64_t arena_words,
                               uint64_t per_page, uint64_t* out_pages)
{
    uint64_t* t = (uint64_t*)malloc((size_t)lines * sizeof(uint64_t));
    uint64_t i, produced = 0, page = 0, pages_used = 0;
    const uint64_t words_per_line = 8;      /* 64 B / 8 B */
    const uint64_t lines_per_page = 64;     /* 4096 / 64  */
    const uint64_t words_per_page = 512;
    if (!t)
        return NULL;
    if (dense) {
        for (i = 0; i < lines; i++)
            t[i] = (i * words_per_line) % arena_words;
        *out_pages = (lines + lines_per_page - 1) / lines_per_page;
        return t;
    }
    while (produced < lines) {
        uint64_t base = page * words_per_page;
        uint64_t k;
        if (base + words_per_page > arena_words) {
            page = 0;
            continue;
        }
        for (k = 0; k < per_page && produced < lines; k++)
            t[produced++] = base + k * words_per_line;
        page++;
        pages_used++;
    }
    *out_pages = pages_used;
    return t;
}

/* fj-like: a dependent fetch (next index) plus an independent RMW, over the target set */
static double bench(uint64_t* a, uint64_t* targets, uint64_t lines, uint64_t iters)
{
    uint64_t s = 0x9E3779B97F4A7C15ull, i;
    double t0, dt;
    /* wire each target's word to point at another target (dependent chain) */
    for (i = 0; i < lines; i++)
        a[targets[i]] = targets[xs(&s) % lines];
    {
        uint64_t cur = targets[0], k;
        t0 = now_sec();
        for (k = 0; k < iters; k++) {
            uint64_t nxt = a[cur];              /* dependent load */
            a[targets[k % lines] + 1] ^= 1ull;  /* independent RMW, same target set */
            cur = nxt;
        }
        dt = now_sec() - t0;
        if (cur == 0xFFFFFFFFFFFFFFFFull)
            printf("");
    }
    return dt;
}

int main(void)
{
    const uint64_t ARENA_MB = 768;
    uint64_t arena_words = ARENA_MB * 1024ull * 1024ull / 8ull;
    uint64_t iters = 60ull * 1000ull * 1000ull;
    /* the measured set: 26.67 MB of lines = 436,884 lines, over 23,397 pages -> 18.7 per page */
    uint64_t lines = 436884;
    uint64_t* a = (uint64_t*)VirtualAlloc(NULL, (size_t)arena_words * 8, MEM_RESERVE | MEM_COMMIT,
                                          PAGE_READWRITE);
    if (!a) {
        printf("alloc failed\n");
        return 1;
    }
    memset(a, 0, (size_t)arena_words * 8);

    printf("arena %llu MB; target set = %llu cache lines = %.2f MB (the DOOM binary's measured set)\n\n",
           (unsigned long long)ARENA_MB, (unsigned long long)lines, lines * 64.0 / (1024 * 1024));
    printf("%-34s %10s %12s %14s\n", "layout", "pages", "MB in cache", "M ops/s");

    {
        uint64_t pages = 0;
        uint64_t* t = build_targets(lines, 1, arena_words, 0, &pages);
        double d = bench(a, t, lines, iters);
        printf("%-34s %10llu %12.2f %14.1f\n", "DENSE (packed, 64 lines/page)",
               (unsigned long long)pages, lines * 64.0 / (1024 * 1024), iters / d / 1e6);
        free(t);
        fflush(stdout);
    }
    {
        uint64_t pages = 0;
        uint64_t* t = build_targets(lines, 0, arena_words, 19, &pages);
        double d = bench(a, t, lines, iters);
        printf("%-34s %10llu %12.2f %14.1f\n", "SPREAD (19 lines/page, as measured)",
               (unsigned long long)pages, lines * 64.0 / (1024 * 1024), iters / d / 1e6);
        free(t);
        fflush(stdout);
    }
    {
        uint64_t pages = 0;
        uint64_t* t = build_targets(lines, 0, arena_words, 4, &pages);
        double d = bench(a, t, lines, iters);
        printf("%-34s %10llu %12.2f %14.1f\n", "SPREAD x5 (4 lines/page)",
               (unsigned long long)pages, lines * 64.0 / (1024 * 1024), iters / d / 1e6);
        free(t);
        fflush(stdout);
    }
    {   /* the uint32 change: same LOGICAL words, half the lines */
        uint64_t pages = 0;
        uint64_t half = lines / 2;
        uint64_t* t = build_targets(half, 0, arena_words, 19, &pages);
        double d = bench(a, t, half, iters);
        printf("%-34s %10llu %12.2f %14.1f\n", "SPREAD, HALF the lines (u32)",
               (unsigned long long)pages, half * 64.0 / (1024 * 1024), iters / d / 1e6);
        free(t);
        fflush(stdout);
    }
    {   /* BOTH cures: dense AND half the lines -- what u32 storage plus a compacted image buys */
        uint64_t pages = 0;
        uint64_t half = lines / 2;
        uint64_t* t = build_targets(half, 1, arena_words, 0, &pages);
        double d = bench(a, t, half, iters);
        printf("%-34s %10llu %12.2f %14.1f\n", "DENSE + HALF (u32 + compacted)",
               (unsigned long long)pages, half * 64.0 / (1024 * 1024), iters / d / 1e6);
        free(t);
        fflush(stdout);
    }
    {   /* the ceiling: a working set small enough that its pages fit the L2 TLB (~2048) */
        uint64_t pages = 0;
        uint64_t tiny_set = 131072;         /* 8 MB of lines. NOT named `small`: windows.h
                                            (rpcndr.h) #defines `small` as `char`. */
        uint64_t* t = build_targets(tiny_set, 1, arena_words, 0, &pages);
        double d = bench(a, t, tiny_set, iters);
        printf("%-34s %10llu %12.2f %14.1f\n", "CEILING: 8 MB dense (TLB-resident)",
               (unsigned long long)pages, tiny_set * 64.0 / (1024 * 1024), iters / d / 1e6);
        free(t);
        fflush(stdout);
    }
    VirtualFree(a, 0, MEM_RELEASE);
    return 0;
}
