/* What does a DEPENDENT memory chase actually cost at each footprint on this cpu?
 *
 * ⚠ THIS REPLACES THE CHAIN ROWS OF memprobe.c AND tlbprobe.c, WHICH WERE WRONG.
 * Both built their chain as `a[i] = random() & mask` and then followed `cur = a[cur]`. That is a
 * random FUNCTIONAL GRAPH, not a permutation: from any start it walks ~sqrt(N) steps and then
 * falls into a rho-cycle whose length is also ~sqrt(N). For a 100M-element array that cycle is a
 * few thousand nodes -- a few hundred KB -- so the benchmark sat in L2 no matter how large the
 * array was. It reported ~370 M/s at a 64 MB footprint, which is physically impossible for a
 * serialized DRAM chase, and that impossible number is what produced the "page count drives
 * throughput" curve that predicted a 4x win from huge pages. The direct experiment -- real THP
 * on the real binary, alternated three times -- measured +1.9%, i.e. nothing.
 *
 * THE FIX: build ONE cycle that visits every selected slot exactly once (Sattolo's algorithm),
 * so the chase cannot escape into a small subset and the footprint is genuinely resident.
 *
 * The fj hot loop per op is: one dependent fetch of the instruction pair (they share a line),
 * then an independent read-modify-write at a scattered address. So `chain` bounds the part that
 * cannot be overlapped, and `fjlike` adds the independent RMW on top.
 *
 * cl /O2 latprobe.c      (Windows)
 * gcc -O2 -o latprobe latprobe.c   (Linux)
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#if defined(_WIN32)
#include <windows.h>
static double now_sec(void)
{
    LARGE_INTEGER f, t;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}
static void* big_alloc(size_t bytes)
{
    return VirtualAlloc(NULL, bytes, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
}
static void big_free(void* p, size_t bytes) { (void)bytes; VirtualFree(p, 0, MEM_RELEASE); }
#else
#include <time.h>
#include <sys/mman.h>
static double now_sec(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}
static void* big_alloc(size_t bytes)
{
    void* p = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    return (p == MAP_FAILED) ? NULL : p;
}
static void big_free(void* p, size_t bytes) { munmap(p, bytes); }
#endif

static uint64_t xs(uint64_t* s)
{
    uint64_t x = *s;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *s = x;
    return x;
}

/* Sattolo: a uniformly random cyclic permutation of idx[0..n-1] -- ONE cycle of length n.
   This is the difference between measuring the footprint and measuring a rho-cycle. */
static void sattolo(uint64_t* idx, uint64_t n, uint64_t* seed)
{
    uint64_t i;
    for (i = n - 1; i > 0; i--) {
        uint64_t j = xs(seed) % i;           /* strictly less than i => single cycle */
        uint64_t t = idx[i];
        idx[i] = idx[j];
        idx[j] = t;
    }
}

/* build the cycle over `lines` distinct cache lines inside the arena, then chase it */
static double bench_chain(uint64_t* a, uint64_t arena_words, uint64_t lines, uint64_t iters,
                          uint64_t stride_words)
{
    uint64_t* idx = (uint64_t*)malloc((size_t)lines * sizeof(uint64_t));
    uint64_t seed = 0x9E3779B97F4A7C15ull, i, cur;
    double t0, dt;
    if (!idx)
        return -1.0;
    for (i = 0; i < lines; i++)
        idx[i] = (i * stride_words) % arena_words;
    sattolo(idx, lines, &seed);
    /* a[p] = next slot: following it visits every slot once per lap */
    for (i = 0; i < lines; i++)
        a[idx[i]] = idx[(i + 1) % lines];
    cur = idx[0];
    t0 = now_sec();
    for (i = 0; i < iters; i++)
        cur = a[cur];
    dt = now_sec() - t0;
    if (cur == 0xFFFFFFFFFFFFFFFFull)
        printf("");
    free(idx);
    return dt;
}

int main(int argc, char** argv)
{
    const uint64_t MB = 1024ull * 1024ull;
    uint64_t arena_mb = (argc > 1) ? strtoull(argv[1], NULL, 10) : 1024;
    uint64_t arena_words = arena_mb * MB / 8;
    uint64_t iters = 20ull * 1000ull * 1000ull;
    uint64_t* a = (uint64_t*)big_alloc((size_t)arena_words * 8);
    /* footprints spanning L1 (48K) -> L2 (1.25M) -> L3 (24M) -> DRAM */
    /* fine around 0.7-4 MB: the DOOM binary's hot set is 2.67 MB (90% of all touches),
       and halving it (4-byte cells) or shrinking it further is the remaining lever. */
    const double set_mb[] = {0.03, 0.25, 0.5, 0.67, 1.0, 1.33, 1.75, 2.0, 2.67,
                             3.0, 4.0, 6.0, 14.0, 26.67};
    int k;
    if (!a) {
        printf("alloc failed\n");
        return 1;
    }
    memset(a, 0, (size_t)arena_words * 8);
    printf("arena %llu MB; DEPENDENT chase over ONE Sattolo cycle (no rho-cycle escape)\n\n",
           (unsigned long long)arena_mb);
    printf("%14s %12s %12s %12s\n", "footprint MB", "lines", "ns/access", "M access/s");
    for (k = 0; k < (int)(sizeof(set_mb) / sizeof(set_mb[0])); k++) {
        uint64_t lines = (uint64_t)(set_mb[k] * MB / 64.0);
        double d;
        if (lines < 2 || lines * 8 > arena_words)
            continue;
        /* stride 8 words = 64 B: one line each, packed densely from the arena base */
        d = bench_chain(a, arena_words, lines, iters, 8);
        if (d < 0)
            continue;
        printf("%14.2f %12llu %12.2f %12.1f\n", set_mb[k], (unsigned long long)lines,
               d / iters * 1e9, iters / d / 1e6);
        fflush(stdout);
    }
    big_free(a, (size_t)arena_words * 8);
    return 0;
}
