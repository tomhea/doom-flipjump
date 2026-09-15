/* What does a TLB miss cost on THIS machine, on a dependent chase, with 4 KB pages?
   K lines in a Sattolo cycle, either PACKED (contiguous 64 B lines: K/64 pages) or SPARSE (one
   line per page at a set-spreading offset: K pages). Same number of lines -> same cache
   behaviour; only the page count differs. sparse - packed = the TLB cost per hop at K pages.
   Golden Cove: L1 DTLB 96 entries (384 KB reach), STLB 2048 (8 MB reach); beyond that, page walks. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>
#include <intrin.h>

static uint32_t rnd_state = 777;
static uint32_t rnd(void) { rnd_state = rnd_state * 1664525u + 1013904223u; return rnd_state >> 8; }

static double tsc_hz(void)
{
    LARGE_INTEGER qf, q0, q1; uint64_t t0, t1;
    QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&q0); t0 = __rdtsc();
    Sleep(200); QueryPerformanceCounter(&q1); t1 = __rdtsc();
    return (double)(t1 - t0) * (double)qf.QuadPart / (double)(q1.QuadPart - q0.QuadPart);
}

static double chase(uint8_t* base, uint32_t K, int sparse, uint64_t hops, double hz)
{
    uint32_t* perm = (uint32_t*)malloc(K * sizeof(uint32_t));
    uint64_t* addr = (uint64_t*)malloc(K * sizeof(uint64_t));
    uint32_t i;
    uint64_t t0, cur;
    double best = 1e300;
    int rep;
    for (i = 0; i < K; i++) {
        uint64_t off = sparse ? ((uint64_t)i * 4096u + (((uint64_t)i * 37u * 64u) & 4095u & ~63u))
                              : ((uint64_t)i * 64u);
        addr[i] = (uint64_t)(base + off);
    }
    for (i = 0; i < K; i++) perm[i] = i;
    for (i = K - 1; i > 0; i--) { uint32_t k = rnd() % i; uint32_t t = perm[i]; perm[i] = perm[k]; perm[k] = t; }
    for (i = 0; i < K; i++) *(uint64_t*)addr[perm[i]] = addr[perm[(i + 1) % K]];
    for (rep = 0; rep < 3; rep++) {
        uint64_t h;
        cur = addr[0];
        for (h = 0; h < K; h++) cur = *(uint64_t*)cur;      /* warm */
        t0 = __rdtsc();
        for (h = 0; h < hops; h++) cur = *(uint64_t*)cur;
        { double ns = (double)(__rdtsc() - t0) / hz * 1e9 / (double)hops; if (ns < best) best = ns; }
    }
    free(perm); free(addr);
    return best + (cur == 1 ? 1e-9 : 0.0);
}

int main(int argc, char** argv)
{
    static const uint32_t KS[8] = {32u, 64u, 512u, 1024u, 2048u, 4096u, 16384u, 65536u};
    double hz = tsc_hz();
    uint64_t hops = (argc > 1) ? strtoull(argv[1], NULL, 10) : (1ull << 24);
    int cpu = (argc > 2) ? atoi(argv[2]) : 2, k;
    size_t bytes = 65536ull * 4096ull + 65536ull;
    uint8_t* base;
    SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)1 << cpu);
    SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);
    base = (uint8_t*)VirtualAlloc(NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!base) { printf("VirtualAlloc failed\n"); return 1; }
    memset(base, 0, bytes);   /* map every page with 4 KB pages, as the engine's flat array is */
    printf("tsc %.3f GHz, cpu %d, %llu hops per run, 3 reps (min). 4 KB pages.\n", hz / 1e9, cpu, (unsigned long long)hops);
    printf("%8s %9s %10s %10s %10s\n", "lines", "pages(sp)", "packed ns", "sparse ns", "TLB ns/hop");
    for (k = 0; k < 8; k++) {
        double p = chase(base, KS[k], 0, hops, hz);
        double s = chase(base, KS[k], 1, hops, hz);
        printf("%8u %9u %10.2f %10.2f %10.2f%s\n", KS[k], KS[k], p, s, s - p,
               KS[k] <= 96 ? "   <- fits L1 DTLB" : KS[k] <= 2048 ? "   <- STLB reach" : "   <- page walks");
    }
    VirtualFree(base, 0, MEM_RELEASE);
    return 0;
}
