
/* ==== FJPROFX (instrumented build only) ===================================================== */
static uint64_t* gx_self = NULL;
static uint64_t* gx_incl = NULL;
static uint8_t*  gx_map = NULL;
static uint64_t  gx_n = 0;
static uint64_t  gx_owner = 0;
static unsigned  gx_owner_obj = 0;
static uint64_t  gx_obj[256];
static uint64_t  gx_out = 0;
static uint64_t  gx_ops_io = 0;
static uint64_t  gx_outside = 0;
static uint32_t* gx_tr = NULL;
static uint64_t  gx_tr_lo = 0, gx_tr_n = 0, gx_total = 0;
#define GX_REC 258
static uint64_t* gx_log = NULL;
static uint64_t  gx_log_n = 0, gx_log_cap = 0;
/* phase markers: gx_mk[word] = marker id; each hit appends [id, ops-before-this-op, obj[0..31]] */
#define GX_MREC 34
static uint8_t*  gx_mk = NULL;
static uint64_t* gx_mlog = NULL;
static uint64_t  gx_mlog_n = 0, gx_mlog_cap = 0;
static void gx_mark_hit(unsigned id)
{
    uint64_t* r;
    if (gx_mlog_n + 1 > gx_mlog_cap) {
        uint64_t nc = gx_mlog_cap ? gx_mlog_cap * 2 : 65536;
        uint64_t* nl = (uint64_t*)realloc(gx_mlog, (size_t)(nc * GX_MREC) * sizeof(uint64_t));
        if (!nl) { fprintf(stderr, "FJPROFX mlog alloc FAILED\n"); exit(3); }
        gx_mlog = nl; gx_mlog_cap = nc;
    }
    r = gx_mlog + gx_mlog_n * GX_MREC;
    r[0] = id; r[1] = gx_total;
    memcpy(r + 2, gx_obj, 32 * sizeof(uint64_t));
    gx_mlog_n++;
}

static void gx_alloc(uint64_t flat_count)
{
    const char* mp;
    FILE* f;
    if (gx_self) return;                 /* once per process: runs ACCUMULATE */
    gx_n = flat_count;
    gx_self = (uint64_t*)calloc((size_t)gx_n, sizeof(uint64_t));
    gx_incl = (uint64_t*)calloc((size_t)gx_n, sizeof(uint64_t));
    gx_map = (uint8_t*)calloc((size_t)gx_n, 1);
    gx_mk = (uint8_t*)calloc((size_t)gx_n, 1);
    if (!gx_self || !gx_incl || !gx_map || !gx_mk) {
        fprintf(stderr, "FJPROFX alloc FAILED\n"); fflush(stderr);
        exit(3);
    }
    memset(gx_obj, 0, sizeof(gx_obj));
    {
        const char* tl = getenv("FJPROFX_TRACE_LO");
        const char* tn = getenv("FJPROFX_TRACE_N");
        if (tl && tl[0] && tn && tn[0]) {
            gx_tr_lo = strtoull(tl, NULL, 10); gx_tr_n = strtoull(tn, NULL, 10);
            gx_tr = (uint32_t*)calloc((size_t)gx_tr_n, 4);
            if (!gx_tr) { fprintf(stderr, "FJPROFX trace alloc FAILED\n"); exit(3); }
            fprintf(stderr, "FJPROFX trace: ops [%llu, +%llu)\n", (unsigned long long)gx_tr_lo, (unsigned long long)gx_tr_n);
        }
    }
    mp = getenv("FJPROFX_MAP");
    if (!mp || !mp[0]) { fprintf(stderr, "FJPROFX: no FJPROFX_MAP -- everything transparent\n"); return; }
    f = fopen(mp, "r");
    if (!f) { fprintf(stderr, "FJPROFX: cannot open map %s\n", mp); exit(3); }
    {
        unsigned long long lo, hi; unsigned id; uint64_t k, nr = 0, nw = 0;
        while (fscanf(f, "%llu %llu %u", &lo, &hi, &id) == 3) {
            if (hi > gx_n) hi = gx_n;
            for (k = lo; k < hi; k++) gx_map[k] = (uint8_t)id;
            nr++; nw += (hi > lo) ? (hi - lo) : 0;
        }
        fclose(f);
        fprintf(stderr, "FJPROFX map: %llu ranges, %llu opaque words of %llu\n",
                (unsigned long long)nr, (unsigned long long)nw, (unsigned long long)gx_n);
        fflush(stderr);
    }
    {
        const char* lp = getenv("FJPROFX_LABELS");
        uint32_t wv; uint64_t nl = 0, nset = 0;
        if (!lp || !lp[0]) { fprintf(stderr, "FJPROFX: no FJPROFX_LABELS\n"); exit(3); }
        f = fopen(lp, "rb");
        if (!f) { fprintf(stderr, "FJPROFX: cannot open labels %s\n", lp); exit(3); }
        while (fread(&wv, 4, 1, f) == 1) {
            nl++;
            if (wv < gx_n && (gx_map[wv] & 0x7Fu)) { gx_map[wv] |= 0x80u; nset++; }
        }
        fclose(f);
        fprintf(stderr, "FJPROFX labels: %llu read, %llu flagged in opaque code\n",
                (unsigned long long)nl, (unsigned long long)nset);
        fflush(stderr);
    }
    {
        const char* kp = getenv("FJPROFX_MARKS");
        unsigned long long wv2; unsigned id2; uint64_t nm = 0;
        if (kp && kp[0]) {
            f = fopen(kp, "r");
            if (!f) { fprintf(stderr, "FJPROFX: cannot open marks %s\n", kp); exit(3); }
            while (fscanf(f, "%llu %u", &wv2, &id2) == 2) {
                if (wv2 < gx_n) { gx_mk[wv2] = (uint8_t)id2; nm++; }
            }
            fclose(f);
        }
        fprintf(stderr, "FJPROFX marks: %llu\n", (unsigned long long)nm);
        fflush(stderr);
    }
}

/* Program FLOW is followed with `gx_pos`: an op in opaque code is ACCEPTED as flow if it is
   LABELLED (a real program point: an entry, a return point, a table's `end`, a loop head) or
   within GX_NEAR words of the last accepted op (straight-line flow). An accepted op that flips
   (f != 0) becomes the OWNER. An unlabelled opaque op reached from far away is an assembler
   chain op living in some expansion's pad hole (a shared wflip tail), a computed table entry,
   or a data cell read from elsewhere -- it is charged to the owner like any other chain op;
   flipping ones are counted in gx_rej. Ops in transparent regions never move either. */
#define GX_NEAR 16
static uint64_t gx_rej = 0;
static uint64_t gx_pos = 0;
#define GX_OP(wa, fv, dwv) do { \
    if ((wa) < gx_n && gx_mk[(wa)]) gx_mark_hit(gx_mk[(wa)]); \
    if (gx_tr && gx_total - gx_tr_lo < gx_tr_n) gx_tr[gx_total - gx_tr_lo] = (uint32_t)(wa); \
    gx_total++; \
    if ((wa) < gx_n) { \
        const unsigned _m = gx_map[(wa)]; \
        gx_self[(wa)]++; \
        if (_m & 0x7Fu) { \
            const uint64_t _d = ((wa) > gx_pos) ? (wa) - gx_pos : gx_pos - (wa); \
            if ((_m & 0x80u) || _d <= GX_NEAR) { \
                gx_pos = (wa); \
                if (fv) { gx_owner = (wa); gx_owner_obj = _m & 0x7Fu; } \
            } else if (fv) gx_rej++; \
        } \
        gx_incl[gx_owner]++; \
        gx_obj[gx_owner_obj]++; \
    } else { gx_outside++; gx_obj[255]++; } \
    if ((fv) - (dwv) <= 1) gx_out++; \
} while (0)
/* ==== end FJPROFX state ===================================================================== */
