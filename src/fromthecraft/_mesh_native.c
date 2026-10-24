/* Exact sample locations and BVH from mesh_geometry.py; no fast-math or FMA
 * contraction. Open-surface queries near a numerical boundary ask Python to
 * repeat the original vector calculation for that entire BVH leaf batch. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <float.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

static double dot3(const double *a, const double *b) {
    return (a[0] * b[0] + a[1] * b[1]) + a[2] * b[2];
}

static double surface_distance(const double *p, const double *t, double cutoff, double margin, int *uncertain) {
    const double *a = t, *ab = t + 3, *ac = t + 6, *normal = t + 9;
    double norm2 = t[12], aa = t[13], bb = t[14], cc = t[15], denominator = t[16];
    double q[3], projected[3];
    for (int k = 0; k < 3; k++) q[k] = p[k] - a[k];
    double nd = dot3(q, normal);
    double plane_distance = nd * nd / norm2;
    /* Distance to the whole plane is a lower bound on distance to its
     * triangle and edges. Reject only beyond the conservative rounding margin. */
    if (isfinite(plane_distance) && plane_distance > cutoff + margin) return plane_distance;
    for (int k = 0; k < 3; k++) projected[k] = q[k] - nd * normal[k] / norm2;
    double pab = dot3(projected, ab), pac = dot3(projected, ac);
    double u = (cc * pab - bb * pac) / denominator;
    double v = (aa * pac - bb * pab) / denominator;
    double branch_margin = 64 * DBL_EPSILON * (aa * cc + bb * bb) / denominator * (1 + fabs(u) + fabs(v));
    int branch_uncertain = !isfinite(u) || !isfinite(v) || !isfinite(branch_margin) ||
        fabs(u) <= branch_margin || fabs(v) <= branch_margin || fabs(u + v - 1) <= branch_margin;
    double distance = (u >= 0 && v >= 0 && u + v <= 1) ? plane_distance : INFINITY;
    double edge_distance = INFINITY;
    for (int edge = 0; edge < 3; edge++) {
        const double *start = t + 17 + edge * 7, *direction = start + 3;
        double length = start[6];
        if (length < 1e-20) continue;
        double delta[3], d[3];
        for (int k = 0; k < 3; k++) delta[k] = p[k] - start[k];
        double fraction = dot3(delta, direction) / length;
        if (fraction < 0) fraction = 0;
        if (fraction > 1) fraction = 1;
        for (int k = 0; k < 3; k++) d[k] = delta[k] - fraction * direction[k];
        double candidate = (d[0] * d[0] + d[1] * d[1]) + d[2] * d[2];
        if (candidate < edge_distance) edge_distance = candidate;
        if (candidate < distance) distance = candidate;
    }
    /* An edge-distance hit remains a hit on either side of a barycentric
     * seam. Keep the original fallback whenever that proof is not robust. */
    if (branch_uncertain && !(isfinite(edge_distance) && edge_distance < cutoff - margin)) {
        *uncertain = 1;
    }
    return distance;
}

static int array_buffer(PyObject *obj, Py_buffer *view, int ndim, Py_ssize_t width, int integer) {
    if (PyObject_GetBuffer(obj, view, PyBUF_C_CONTIGUOUS | PyBUF_FORMAT) < 0) return 0;
    int format_ok = integer
        ? (view->format && strchr("nlq", view->format[0]) && view->format[1] == '\0')
        : (view->format && strcmp(view->format, "d") == 0);
    Py_ssize_t itemsize = integer ? sizeof(Py_ssize_t) : sizeof(double);
    if (!format_ok || view->ndim != ndim || view->itemsize != itemsize ||
        (ndim == 2 && view->shape[1] != width) ||
        ((uintptr_t)view->buf % (uintptr_t)itemsize) != 0) {
        PyErr_SetString(PyExc_ValueError, "Expected a contiguous native double or index array of the required shape");
        return 0;
    }
    return 1;
}

static PyObject *contains(PyObject *self, PyObject *args) {
    PyObject *objects[5], *result = NULL, *answer = NULL;
    Py_buffer views[5] = {{0}};
    Py_ssize_t *stack = NULL, *parents = NULL;
    int closed, uncertain = 0;
    double radius = 0;
    if (!PyArg_ParseTuple(args, "OOOOOp|d", &objects[0], &objects[1], &objects[2],
                          &objects[3], &objects[4], &closed, &radius)) return NULL;
    if (!array_buffer(objects[0], &views[0], 2, 3, 0) ||
        !array_buffer(objects[1], &views[1], 2, closed ? 10 : 38, 0) ||
        !array_buffer(objects[2], &views[2], 2, 6, 0) ||
        !array_buffer(objects[3], &views[3], 2, 4, 1) ||
        !array_buffer(objects[4], &views[4], 1, 0, 1)) goto cleanup;
    Py_ssize_t point_count = views[0].shape[0], triangle_count = views[1].shape[0];
    Py_ssize_t node_count = views[2].shape[0], index_count = views[4].shape[0];
    if (point_count > 32768 || node_count < 1 || node_count > 100000 ||
        views[3].shape[0] != node_count || !isfinite(radius) || radius < 0) {
        PyErr_SetString(PyExc_ValueError, "Invalid native sampling batch or tree size");
        goto cleanup;
    }
    const double *points = views[0].buf, *triangles = views[1].buf, *bounds = views[2].buf;
    const Py_ssize_t *nodes = views[3].buf, *indices = views[4].buf;
    stack = PyMem_Malloc((size_t)node_count * sizeof(Py_ssize_t));
    parents = PyMem_Calloc((size_t)node_count, sizeof(Py_ssize_t));
    if (!stack || !parents) { PyErr_NoMemory(); goto cleanup; }
    for (Py_ssize_t i = 0; i < index_count; i++) {
        if (indices[i] < 0 || indices[i] >= triangle_count) {
            PyErr_SetString(PyExc_ValueError, "Triangle index outside native coefficient array");
            goto cleanup;
        }
    }
    for (Py_ssize_t i = 0; i < node_count; i++) {
        const Py_ssize_t *node = nodes + i * 4;
        if (node[0] == -1 && node[1] == -1) {
            if (node[2] < 0 || node[3] < 0 || node[2] > index_count || node[3] > index_count - node[2]) {
                PyErr_SetString(PyExc_ValueError, "Native leaf range outside index array");
                goto cleanup;
            }
        } else {
            if (node[0] <= i || node[1] <= i || node[0] >= node_count || node[1] >= node_count) {
                PyErr_SetString(PyExc_ValueError, "Invalid native tree child");
                goto cleanup;
            }
            parents[node[0]]++;
            parents[node[1]]++;
        }
        if (i && parents[i] != 1) {
            PyErr_SetString(PyExc_ValueError, "Native tree nodes must have exactly one parent");
            goto cleanup;
        }
    }
    result = PyBytes_FromStringAndSize(NULL, point_count);
    if (!result) goto cleanup;
    unsigned char *occupied = (unsigned char *)PyBytes_AS_STRING(result);
    memset(occupied, 0, (size_t)point_count);
    unsigned long long work = 0;
    double cutoff = radius * radius + 1e-12;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t i = 0; i < point_count; i++) {
        const double *p = points + i * 3;
        Py_ssize_t pending = 1;
        stack[0] = 0;
        unsigned int hits = 0;
        while (pending) {
            Py_ssize_t node_index = stack[--pending];
            const Py_ssize_t *node = nodes + node_index * 4;
            const double *low = bounds + node_index * 6, *high = low + 3;
            int keep = closed
                ? p[0] <= high[0] && p[1] >= low[1] && p[1] <= high[1] && p[2] >= low[2] && p[2] <= high[2]
                : !hits && p[0] >= low[0] - radius && p[0] <= high[0] + radius &&
                  p[1] >= low[1] - radius && p[1] <= high[1] + radius &&
                  p[2] >= low[2] - radius && p[2] <= high[2] + radius;
            if (!keep) continue;
            if (node[0] != -1) {
                stack[pending++] = node[1];
                stack[pending++] = node[0];
                continue;
            }
            work += (unsigned long long)node[3];
            for (Py_ssize_t j = node[2]; j < node[2] + node[3]; j++) {
                const double *t = triangles + indices[j] * (closed ? 10 : 38);
                if (closed) {
                    double denominator = t[9];
                    if (fabs(denominator) < 1e-14) continue;
                    double qy = p[1] - t[1], qz = p[2] - t[2];
                    double u = (qy * t[8] - qz * t[7]) / denominator;
                    double v = (t[4] * qz - t[5] * qy) / denominator;
                    if (u >= 0 && v >= 0 && u + v < 1 && t[0] + u * t[3] + v * t[6] > p[0]) hits++;
                } else {
                    if (t[12] < 1e-20 || t[16] <= 1e-20) continue;
                    /* BLAS can contract dot products differently. Re-evaluate
                     * an entire original batch when that could affect a bit. */
                    double magnitude = 1;
                    for (int k = 0; k < 3; k++) {
                        magnitude += p[k] * p[k] + t[k] * t[k] + t[k + 3] * t[k + 3] + t[k + 6] * t[k + 6];
                    }
                    double margin = 512 * DBL_EPSILON * magnitude;
                    int triangle_uncertain = 0;
                    double distance = surface_distance(p, t, cutoff, margin, &triangle_uncertain);
                    if (!isfinite(distance) || fabs(distance - cutoff) <= margin ||
                        t[16] <= 1e-10 * t[13] * t[15]) triangle_uncertain = 1;
                    uncertain |= triangle_uncertain;
                    /* The caller discards this entire attempt and repeats
                     * the original NumPy batch once ambiguity is reported. */
                    if (uncertain) goto classified;
                    if (distance <= cutoff) {
                        hits = 1;
                        /* A robust hit proves this union query. Later triangles
                         * cannot change it; keep the original leaf work count. */
                        if (!triangle_uncertain) break;
                    }
                }
            }
        }
        occupied[i] = closed ? (unsigned char)(hits % 2) : (unsigned char)(hits != 0);
    }
classified:
    Py_END_ALLOW_THREADS
    answer = Py_BuildValue("OKi", result, work, uncertain);
cleanup:
    Py_XDECREF(result);
    PyMem_Free(stack);
    PyMem_Free(parents);
    for (int i = 0; i < 5; i++) if (views[i].obj) PyBuffer_Release(&views[i]);
    return answer;
}

static PyMethodDef methods[] = {
    {"contains", contains, METH_VARARGS, "Classify a bounded batch using the original mesh tree."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_mesh_native", NULL, -1, methods};
PyMODINIT_FUNC PyInit__mesh_native(void) { return PyModule_Create(&module); }
