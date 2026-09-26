
static PyObject* fjcore_prof_mark(PyObject* module, PyObject* Py_UNUSED(args))
{
    uint64_t* r;
    (void)module;
    if (gx_log_n + 1 > gx_log_cap) {
        uint64_t nc = gx_log_cap ? gx_log_cap * 2 : 4096;
        uint64_t* nl = (uint64_t*)realloc(gx_log, (size_t)(nc * GX_REC) * sizeof(uint64_t));
        if (!nl) return PyErr_NoMemory();
        gx_log = nl; gx_log_cap = nc;
    }
    r = gx_log + gx_log_n * GX_REC;
    r[0] = gx_ops_io; r[1] = gx_out;
    memcpy(r + 2, gx_obj, sizeof(gx_obj));
    gx_log_n++;
    return PyLong_FromUnsignedLongLong(gx_ops_io);
}

static int gx_dump_sparse(const char* path, const uint64_t* arr)
{
    FILE* f = fopen(path, "wb");
    uint64_t i, nz = 0;
    if (!f) return -1;
    fwrite(&nz, sizeof(nz), 1, f);           /* patched below */
    for (i = 0; i < gx_n; i++) {
        if (arr[i]) {
            uint32_t w = (uint32_t)i;
            fwrite(&w, 4, 1, f); fwrite(&arr[i], 8, 1, f); nz++;
        }
    }
    fseek(f, 0, SEEK_SET); fwrite(&nz, sizeof(nz), 1, f);
    fclose(f);
    return 0;
}

static PyObject* fjcore_prof_dump(PyObject* module, PyObject* args)
{
    const char* prefix;
    char path[1024];
    FILE* f;
    (void)module;
    if (!PyArg_ParseTuple(args, "s", &prefix)) return NULL;
    if (!gx_self) { PyErr_SetString(PyExc_RuntimeError, "prof_dump: nothing allocated"); return NULL; }
    snprintf(path, sizeof(path), "%s.log.bin", prefix);
    f = fopen(path, "wb");
    if (!f) { PyErr_SetString(PyExc_OSError, path); return NULL; }
    { uint64_t hdr[5]; hdr[0] = gx_log_n; hdr[1] = GX_REC; hdr[2] = gx_outside; hdr[3] = gx_out; hdr[4] = gx_rej;
      fwrite(hdr, 8, 5, f); if (gx_log_n) fwrite(gx_log, 8, (size_t)(gx_log_n * GX_REC), f); fclose(f); }
    snprintf(path, sizeof(path), "%s.marks.bin", prefix);
    f = fopen(path, "wb");
    if (f) { uint64_t h2[2]; h2[0] = gx_mlog_n; h2[1] = GX_MREC; fwrite(h2, 8, 2, f);
             if (gx_mlog_n) fwrite(gx_mlog, 8, (size_t)(gx_mlog_n * GX_MREC), f); fclose(f); }
    if (gx_tr) {
        snprintf(path, sizeof(path), "%s.trace.bin", prefix);
        f = fopen(path, "wb");
        if (f) { fwrite(&gx_tr_lo, 8, 1, f); fwrite(&gx_tr_n, 8, 1, f); fwrite(gx_tr, 4, (size_t)gx_tr_n, f); fclose(f); }
    }
    snprintf(path, sizeof(path), "%s.self.bin", prefix);
    if (gx_dump_sparse(path, gx_self) < 0) { PyErr_SetString(PyExc_OSError, path); return NULL; }
    snprintf(path, sizeof(path), "%s.incl.bin", prefix);
    if (gx_dump_sparse(path, gx_incl) < 0) { PyErr_SetString(PyExc_OSError, path); return NULL; }
    return PyLong_FromUnsignedLongLong(gx_log_n);
}

static PyObject* fjcore_prof_reset(PyObject* module, PyObject* Py_UNUSED(args))
{
    (void)module;
    if (gx_self) { memset(gx_self, 0, (size_t)gx_n * 8); memset(gx_incl, 0, (size_t)gx_n * 8); }
    memset(gx_obj, 0, sizeof(gx_obj));
    gx_out = 0; gx_outside = 0; gx_rej = 0; gx_log_n = 0; gx_owner = 0; gx_owner_obj = 0; gx_pos = 0; gx_mlog_n = 0; gx_total = 0;
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    {"prof_mark", (PyCFunction)fjcore_prof_mark, METH_NOARGS, "FJPROFX: snapshot the per-object counters"},
    {"prof_dump", (PyCFunction)fjcore_prof_dump, METH_VARARGS, "FJPROFX: dump log + sparse histograms"},
    {"prof_reset", (PyCFunction)fjcore_prof_reset, METH_NOARGS, "FJPROFX: zero everything"},