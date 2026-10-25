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

static PyObject *sample_points(PyObject *self, PyObject *args) {
    PyObject *objects[5], *answer = NULL;
    Py_buffer views[5] = {{0}};
    double scale;
    if (!PyArg_ParseTuple(args, "OOOOdO", &objects[0], &objects[1], &objects[2], &objects[3],
                          &scale, &objects[4])) return NULL;
    if (!array_buffer(objects[0], &views[0], 2, 3, 1) ||
        !array_buffer(objects[1], &views[1], 2, 3, 0) ||
        !array_buffer(objects[2], &views[2], 2, 4, 0) ||
        !array_buffer(objects[3], &views[3], 1, 0, 0) ||
        !array_buffer(objects[4], &views[4], 1, 0, 0)) goto cleanup;
    Py_ssize_t cell_count = views[0].shape[0], sample_count = views[1].shape[0];
    if (views[2].shape[0] != 4 || views[3].shape[0] != 3 || views[4].shape[0] != 3 ||
        !isfinite(scale) || scale <= 0 || sample_count > 1572864 ||
        (sample_count && cell_count > 1572864 / sample_count)) {
        PyErr_SetString(PyExc_ValueError, "Invalid diagonal sample transform dimensions or scale");
        goto cleanup;
    }
    const Py_ssize_t *cells = views[0].buf;
    const double *samples = views[1].buf, *matrix = views[2].buf;
    const double *size = views[3].buf, *span = views[4].buf;
    for (int axis = 0; axis < 3; axis++) {
        if (!isfinite(size[axis]) || size[axis] <= 0 || !isfinite(span[axis]) ||
            !isfinite(matrix[axis * 4 + 3]) || !isfinite(matrix[axis * 5]) || matrix[axis * 5] <= 0) {
            PyErr_SetString(PyExc_ValueError, "Expected finite positive diagonal transform and size");
            goto cleanup;
        }
        for (int other = 0; other < 3; other++) {
            if (axis != other && matrix[axis * 4 + other] != 0) {
                PyErr_SetString(PyExc_ValueError, "Expected a diagonal transform");
                goto cleanup;
            }
        }
    }
    for (Py_ssize_t i = 0; i < sample_count * 3; i++) {
        if (!isfinite(samples[i])) {
            PyErr_SetString(PyExc_ValueError, "Expected finite sample coordinates");
            goto cleanup;
        }
    }
    Py_ssize_t point_count = cell_count * sample_count;
    answer = PyBytes_FromStringAndSize(NULL, point_count * 3 * (Py_ssize_t)sizeof(double));
    if (!answer) goto cleanup;
    double *output = (double *)PyBytes_AS_STRING(answer);
    /* Prepared meshes have a positive diagonal inverse. Each matrix dot has
     * exactly one nonzero product; adding +0 preserves its zero sign before
     * translation. Strict floating point keeps every division and multiply
     * separate, matching the NumPy pipeline without its full-size temporaries. */
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t cell = 0; cell < cell_count; cell++) {
        for (Py_ssize_t sample = 0; sample < sample_count; sample++) {
            for (int axis = 0; axis < 3; axis++) {
                double value = (double)cells[cell * 3 + axis] + samples[sample * 3 + axis];
                value /= scale;
                value *= matrix[axis * 5];
                value += 0.0;
                value += matrix[axis * 4 + 3];
                value /= size[axis];
                value *= span[axis];
                output[(cell * sample_count + sample) * 3 + axis] = value;
            }
        }
    }
    Py_END_ALLOW_THREADS
cleanup:
    for (int i = 0; i < 5; i++) if (views[i].obj) PyBuffer_Release(&views[i]);
    return answer;
}

static PyObject *contains(PyObject *self, PyObject *args) {
    PyObject *objects[5], *result = NULL, *answer = NULL;
    Py_buffer views[5] = {{0}};
    Py_ssize_t *stack = NULL, *parents = NULL;
    int closed, uncertain = 0, packet_size = 0;
    double radius = 0;
    if (!PyArg_ParseTuple(args, "OOOOOp|di", &objects[0], &objects[1], &objects[2],
                          &objects[3], &objects[4], &closed, &radius, &packet_size)) return NULL;
    if (!array_buffer(objects[0], &views[0], 2, 3, 0) ||
        !array_buffer(objects[1], &views[1], 2, closed ? 10 : 38, 0) ||
        !array_buffer(objects[2], &views[2], 2, 6, 0) ||
        !array_buffer(objects[3], &views[3], 2, 4, 1) ||
        !array_buffer(objects[4], &views[4], 1, 0, 1)) goto cleanup;
    Py_ssize_t point_count = views[0].shape[0], triangle_count = views[1].shape[0];
    Py_ssize_t node_count = views[2].shape[0], index_count = views[4].shape[0];
    if (point_count > 32768 || node_count < 1 || node_count > 100000 ||
        views[3].shape[0] != node_count || !isfinite(radius) || radius < 0 ||
        packet_size < 0 || packet_size > 32768) {
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
            if (packet_size) {
                for (int child = 0; child < 2; child++) {
                    const double *parent_bounds = bounds + i * 6;
                    const double *child_bounds = bounds + node[child] * 6;
                    for (int axis = 0; axis < 3; axis++) {
                        if (!(child_bounds[axis] >= parent_bounds[axis] &&
                              child_bounds[axis + 3] <= parent_bounds[axis + 3])) {
                            PyErr_SetString(PyExc_ValueError, "Packet child bounds must be within parent bounds");
                            goto cleanup;
                        }
                    }
                }
            }
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
    Py_ssize_t packet_step = packet_size ? packet_size : (point_count ? point_count : 1);
    /* The parent-count buffer is no longer needed after tree validation. */
    Py_ssize_t *leaves = parents;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t first = 0; first < point_count; first += packet_step) {
        Py_ssize_t end = first + packet_step < point_count ? first + packet_step : point_count;
        Py_ssize_t leaf_count = 0;
        if (packet_size) {
            double minimum[3] = {INFINITY, INFINITY, INFINITY};
            double maximum[3] = {-INFINITY, -INFINITY, -INFINITY};
            for (Py_ssize_t i = first; i < end; i++) {
                for (int axis = 0; axis < 3; axis++) {
                    double value = points[i * 3 + axis];
                    if (value < minimum[axis]) minimum[axis] = value;
                    if (value > maximum[axis]) maximum[axis] = value;
                }
            }
            Py_ssize_t pending = 1;
            stack[0] = 0;
            while (pending) {
                Py_ssize_t index = stack[--pending];
                const double *low = bounds + index * 6, *high = low + 3;
                const Py_ssize_t *node = nodes + index * 4;
                int keep = closed
                    ? minimum[0] <= high[0] && maximum[1] >= low[1] && minimum[1] <= high[1] &&
                      maximum[2] >= low[2] && minimum[2] <= high[2]
                    : maximum[0] >= low[0] - radius && minimum[0] <= high[0] + radius &&
                      maximum[1] >= low[1] - radius && minimum[1] <= high[1] + radius &&
                      maximum[2] >= low[2] - radius && minimum[2] <= high[2] + radius;
                if (!keep) continue;
                if (node[0] == -1) leaves[leaf_count++] = index;
                else {
                    stack[pending++] = node[1];
                    stack[pending++] = node[0];
                }
            }
            if (!leaf_count) continue;
        }
        for (Py_ssize_t i = first; i < end; i++) {
        const double *p = points + i * 3;
        Py_ssize_t pending = 1, cursor = 0;
        stack[0] = 0;
        unsigned int hits = 0;
        while (packet_size ? cursor < leaf_count : pending) {
            Py_ssize_t node_index = packet_size ? leaves[cursor++] : stack[--pending];
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
    {"sample_points", sample_points, METH_VARARGS, "Fuse bounded positive diagonal sample transforms."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_mesh_native", NULL, -1, methods};
PyMODINIT_FUNC PyInit__mesh_native(void) {
    PyObject *result = PyModule_Create(&module);
    if (result && PyModule_AddIntConstant(result, "PACKET_QUERIES", 1) < 0) {
        Py_DECREF(result);
        return NULL;
    }
    return result;
}
