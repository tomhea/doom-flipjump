/* What does the fj hot loop's memory pattern actually cost on THIS cpu, at THIS footprint?
 *
 * run_flat_loop_impl does, per op:
 *     f = flat[ip>>ww];  j = flat[(ip>>ww)+1];       <- one cache line, DEPENDENT (ip = j next)
 *     flat[f>>ww] ^= 1ull << (f & mask);             <- random RMW, INDEPENDENT of the chain
 *
 * So there are two separate memory effects and they have different cures:
 *   CHAIN   - a dependent pointer chase. Its cost is pure latency; MLP cannot hide it.
 *   SCATTER - an independent read-modify-write. Its cost is bandwidth + TLB, and the core can
 *             overlap many of them.
 *
 * This measures each at several footprints, with 4 KB pages and (if the privilege is available)
 * 2 MB large pages, so the engine's 768 MB array can be priced against a hypothetical smaller
 * or better-paged one WITHOUT guessing.
 *
 * cl /O2 /FeMEMPROBE.exe memprobe.c
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

/* ask Windows for SeLockMemoryPrivilege -- large pages need it, and it is normally granted
   only to an administrator whose account also holds "Lock pages in memory" in the local
   policy. Failure here is expected on a stock machine and is reported, not fatal. */
static int enable_lock_memory_privilege(void)
{
    HANDLE token;
    TOKEN_PRIVILEGES tp;
    LUID luid;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &token))
        return 0;
    if (!LookupPrivilegeValueA(NULL, "SeLockMemoryPrivilege", &luid)) {
        CloseHandle(token);
        return 0;
    }
    tp.PrivilegeCount = 1;
    tp.Privileges[0].Luid = luid;
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
    AdjustTokenPrivileges(token, FALSE, &tp, sizeof(tp), NULL, NULL);
    int ok = (GetLastError() == ERROR_SUCCESS);
    CloseHandle(token);
    return ok;
}

static uint64_t* alloc_pages(size_t bytes, int large, size_t* actual)
{
    if (large) {
        size_t lp = GetLargePageMinimum();
        if (!lp)
            return NULL;
        size_t rounded = ((bytes + lp - 1) / lp) * lp;
        void* p = VirtualAlloc(NULL, rounded, MEM_RESERVE | MEM_COMMIT | MEM_LARGE_PAGES,
                               PAGE_READWRITE);
        if (!p)
            return NULL;
        *actual = rounded;
        return (uint64_t*)p;
    }
    void* p = VirtualAlloc(NULL, bytes, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    *actual = bytes;
    return (uint64_t*)p;
}

/* xorshift -- cheap, and the point is the MEMORY cost, not the rng */
static FORCEINLINE uint64_t xs(uint64_t* s)
{
    uint64_t x = *s;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *s = x;
    return x;
}

/* CHAIN: each load's address depends on the previous load's value. Pure latency. */
static double bench_chain(uint64_t* a, size_t words, uint64_t iters)
{
    uint64_t mask = words - 1; /* words is a power of two */
    uint64_t s = 0x243F6A8885A308D3ull;
    /* build a random permutation-ish cycle: a[i] holds the next index */
    for (size_t i = 0; i < words; i++)
        a[i] = xs(&s) & mask;
    uint64_t idx = 0;
    double t0 = now_sec();
    for (uint64_t k = 0; k < iters; k++)
        idx = a[idx];
    double dt = now_sec() - t0;
    if (idx == 0xFFFFFFFFFFFFFFFFull)
        printf("");
    return dt;
}

/* SCATTER: independent random read-modify-write, exactly the flip. */
static double bench_scatter(uint64_t* a, size_t words, uint64_t iters)
{
    uint64_t mask = words - 1;
    uint64_t s = 0x13198A2E03707344ull;
    memset(a, 0, words * sizeof(uint64_t));
    double t0 = now_sec();
    for (uint64_t k = 0; k < iters; k++) {
        uint64_t i = xs(&s) & mask;
        a[i] ^= 1ull << (i & 63);
    }
    double dt = now_sec() - t0;
    return dt;
}

/* BOTH, in the engine's proportion: one dependent line-local fetch + one random RMW per op. */
static double bench_fjlike(uint64_t* a, size_t words, uint64_t iters)
{
    uint64_t mask = words - 1;
    uint64_t s = 0x2E0F4C1B7A99D311ull;
    for (size_t i = 0; i < words; i++)
        a[i] = xs(&s) & mask;
    uint64_t ip = 0;
    double t0 = now_sec();
    for (uint64_t k = 0; k < iters; k++) {
        uint64_t f = a[ip];
        uint64_t j = a[(ip + 1) & mask];
        uint64_t t = f & mask;
        a[t] ^= 1ull << (f & 63);
        ip = j & mask;
    }
    double dt = now_sec() - t0;
    if (ip == 0xFFFFFFFFFFFFFFFFull)
        printf("");
    return dt;
}

int main(void)
{
    int have_large = enable_lock_memory_privilege();
    size_t lpmin = GetLargePageMinimum();
    printf("large-page privilege: %s   GetLargePageMinimum = %llu bytes\n",
           have_large ? "GRANTED" : "DENIED (stock machine: needs admin + 'Lock pages in memory')",
           (unsigned long long)lpmin);

    /* footprints that matter: the engine's 768 MB, a uint32 halving, a compacted image,
       and a cache-resident control that should reproduce the loop benchmark's speed */
    const size_t MB = 1024 * 1024;
    size_t sizes[] = { 8 * MB, 64 * MB, 256 * MB, 512 * MB, 1024 * MB };
    const char* labels[] = { "8 MB (L2/L3-resident)", "64 MB", "256 MB (compact+u32)",
                             "512 MB (u32 of today)", "1024 MB (~today's 768 MB)" };
    uint64_t iters = 40ull * 1000ull * 1000ull;

    for (int large = 0; large <= (have_large ? 1 : 0); large++) {
        printf("\n=== %s pages ===\n", large ? "2 MB LARGE" : "4 KB normal");
        printf("%-26s %14s %14s %14s\n", "footprint", "chain M/s", "scatter M/s", "fj-like M/s");
        for (int i = 0; i < (int)(sizeof(sizes) / sizeof(sizes[0])); i++) {
            size_t actual = 0;
            uint64_t* a = alloc_pages(sizes[i], large, &actual);
            if (!a) {
                printf("%-26s   (alloc failed)\n", labels[i]);
                continue;
            }
            size_t words = actual / sizeof(uint64_t);
            /* round down to a power of two so the mask is exact */
            size_t p2 = 1;
            while (p2 * 2 <= words)
                p2 *= 2;
            words = p2;

            double c = bench_chain(a, words, iters / 8);
            double s = bench_scatter(a, words, iters);
            double f = bench_fjlike(a, words, iters);
            printf("%-26s %14.1f %14.1f %14.1f\n", labels[i],
                   (iters / 8) / c / 1e6, iters / s / 1e6, iters / f / 1e6);
            fflush(stdout);
            VirtualFree(a, 0, MEM_RELEASE);
        }
    }
    return 0;
}
