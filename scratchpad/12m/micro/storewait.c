/* Does the flip STORE block the dependent instruction fetch? A pair-chase shaped like the engine
   at 4-byte cells: pair p = (f, j); the op flips bit (f&31) of word (f>>5), then jumps to j.
     V0  chase only                     j = a[p+1]; p = j
     V1  engine order, never aliases    f = a[p]; a[f>>5] ^= bit; j = a[p+1]; p = j
     V2  engine order, 1/32 ops flip bit 30 of the NEXT op's j word (d=1 alias; bit 30 is masked
         off by the chase, so the path is unchanged -- only the predictor sees it)
     V3  loads before the store + register fixups, never aliases
     V4  the same, 1/32 d=1 aliases
   Working sets: 16 KB (L1) and 512 KB (L2). Prints ns/op; the ratios are the result. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>
#include <intrin.h>

static uint32_t rnd_state = 12345;
static uint32_t rnd(void) { rnd_state = rnd_state * 1664525u + 1013904223u; return rnd_state >> 8; }

static double tsc_hz(void)
{
    LARGE_INTEGER qf, q0, q1; uint64_t t0, t1;
    QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&q0); t0 = __rdtsc();
    Sleep(200); QueryPerformanceCounter(&q1); t1 = __rdtsc();
    return (double)(t1 - t0) * (double)qf.QuadPart / (double)(q1.QuadPart - q0.QuadPart);
}

/* a: 2N chase words + 4096 data words. Sattolo cycle over pairs. */
static uint32_t* build(uint32_t N, int alias_every, uint32_t* next_of)
{
    uint32_t* perm = (uint32_t*)malloc(N * sizeof(uint32_t));
    uint32_t* a = (uint32_t*)_aligned_malloc((2 * (size_t)N + 4096) * sizeof(uint32_t), 64);
    uint32_t i;
    for (i = 0; i < N; i++) perm[i] = i;
    for (i = N - 1; i > 0; i--) { uint32_t k = rnd() % i; uint32_t t = perm[i]; perm[i] = perm[k]; perm[k] = t; }
    for (i = 0; i < N; i++) next_of[perm[i]] = perm[(i + 1) % N];
    for (i = 0; i < N; i++) {
        uint32_t nxt = next_of[i];
        uint32_t data_word = 2 * N + (i & 4095);
        a[2 * i + 1] = 2 * nxt;                       /* j: word index of the next pair */
        if (alias_every && (i % alias_every) == 0)
            a[2 * i] = ((2 * nxt + 1) << 5) | 30;     /* flip bit 30 of the next pair's j word */
        else
            a[2 * i] = (data_word << 5) | (i & 31);   /* flip a data word */
    }
    memset(a + 2 * N, 0, 4096 * sizeof(uint32_t));
    free(perm);
    return a;
}

#define MASKJ(x) ((x) & 0x3FFFFFFFu)

static uint64_t run(int variant, uint32_t* a, uint64_t ops)
{
    uint32_t p = 0, f, j, t, fv, nv, np, nf, nj;
    uint64_t i, acc = 0;
    switch (variant) {
    case 0:
        for (i = 0; i < ops; i++) { j = a[p + 1]; p = MASKJ(j); }
        break;
    case 1: case 2:
        for (i = 0; i < ops; i++) {
            f = a[p]; t = f >> 5; fv = a[t]; nv = fv ^ (1u << (f & 31)); a[t] = nv;
            j = a[p + 1]; p = MASKJ(j);
        }
        break;
    case 3: case 4:
        f = a[p]; j = a[p + 1];
        for (i = 0; i < ops; i++) {
            np = MASKJ(j);
            nf = a[np]; nj = a[np + 1];                 /* the next pair, loaded BEFORE this op's store */
            t = f >> 5; fv = a[t]; nv = fv ^ (1u << (f & 31)); a[t] = nv;
            if (t == p + 1) { np = MASKJ(nv); nf = a[np]; nj = a[np + 1]; }   /* own jump word: rare */
            else if (t == np) nf = nv;                  /* d=1 fixups in registers */
            else if (t == np + 1) nj = nv;
            f = nf; j = nj; p = np;
        }
        break;
    }
    acc += p;
    return acc;
}

int main(int argc, char** argv)
{
    static const char* NAME[5] = {"V0 chase only", "V1 engine order, no alias", "V2 engine order, d=1 alias 1/32",
                                  "V3 loads-first + fixups, no alias", "V4 loads-first + fixups, d=1 alias 1/32"};
    static const uint32_t SIZES[2] = {2048u, 65536u};   /* pairs: 16 KB, 512 KB */
    double hz = tsc_hz();
    uint64_t ops = (argc > 1) ? strtoull(argv[1], NULL, 10) : (1ull << 26);
    int cpu = (argc > 2) ? atoi(argv[2]) : 2, v, sz, rep;
    SetThreadAffinityMask(GetCurrentThread(), (DWORD_PTR)1 << cpu);
    SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);
    printf("tsc %.3f GHz, cpu %d, %llu ops per run, 3 reps each (min reported)\n", hz / 1e9, cpu, (unsigned long long)ops);
    for (sz = 0; sz < 2; sz++) {
        uint32_t N = SIZES[sz];
        uint32_t* next_of = (uint32_t*)malloc(N * sizeof(uint32_t));
        printf("--- working set %u pairs = %u KB ---\n", N, N * 8 / 1024);
        for (v = 0; v < 5; v++) {
            int alias = (v == 2 || v == 4) ? 32 : 0;
            uint32_t* a = build(N, alias, next_of);
            double best = 1e300;
            uint64_t acc = 0;
            for (rep = 0; rep < 3; rep++) {
                uint64_t t0 = __rdtsc();
                acc += run(v, a, ops);
                { double ns = (double)(__rdtsc() - t0) / hz * 1e9 / (double)ops; if (ns < best) best = ns; }
            }
            printf("  %-42s %7.3f ns/op   (acc %llu)\n", NAME[v], best, (unsigned long long)(acc & 1));
            _aligned_free(a);
        }
        free(next_of);
    }
    return 0;
}
