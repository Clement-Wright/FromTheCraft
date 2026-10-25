/* Exact sample locations and BVH from mesh_geometry.py; no fast-math or FMA
 * contraction. Open-surface queries near a numerical boundary ask Python to
 * repeat the original vector calculation for that entire BVH leaf batch. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <float.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

/* Outward-rounded IEEE-754 bounds certify whole packets against the literal
 * closed-ray predicate. Uncertain intervals retain every per-point operation. */
typedef struct { double lo, hi; } Interval;
static double adjacent(double value, int upward, int *valid) {
    if (!isfinite(value)) { *valid = 0; return value; }
    uint64_t bits;
    memcpy(&bits, &value, sizeof(bits));
    if (value == 0) bits = upward ? UINT64_C(1) : UINT64_C(0x8000000000000001);
    else if ((value > 0) == upward) bits++;
    else bits--;
    memcpy(&value, &bits, sizeof(value));
    if (!isfinite(value)) *valid = 0;
    return value;
}
static Interval widened(double lo, double hi, int *valid) {
    Interval result = {adjacent(lo, 0, valid), adjacent(hi, 1, valid)};
    return result;
}
static Interval iadd(Interval a, Interval b, int *valid) {
    return widened(a.lo + b.lo, a.hi + b.hi, valid);
}
static Interval isub(Interval a, Interval b, int *valid) {
    return widened(a.lo - b.hi, a.hi - b.lo, valid);
}
static Interval imul(Interval a, double b, int *valid) {
    return b >= 0 ? widened(a.lo * b, a.hi * b, valid) : widened(a.hi * b, a.lo * b, valid);
}
static Interval idiv(Interval a, double b, int *valid) {
    return b > 0 ? widened(a.lo / b, a.hi / b, valid) : widened(a.hi / b, a.lo / b, valid);
}
static int triangle_packet(const double *t, const double *low, const double *high) {
    if (sizeof(double) != sizeof(uint64_t) || DBL_MANT_DIG != 53 || DBL_MAX_EXP != 1024) return 0;
    for (int k = 0; k < 10; k++) if (!isfinite(t[k])) return 0;
    for (int k = 0; k < 3; k++) if (!isfinite(low[k]) || !isfinite(high[k])) return 0;
    if (fabs(t[9]) < 1e-14) return -1;
    int valid = 1;
    Interval y = {low[1], high[1]}, z = {low[2], high[2]};
    Interval ay = {t[1], t[1]}, az = {t[2], t[2]};
    Interval qy = isub(y, ay, &valid), qz = isub(z, az, &valid);
    Interval u = idiv(isub(imul(qy, t[8], &valid), imul(qz, t[7], &valid), &valid), t[9], &valid);
    if (!valid) return 0;
    if (u.hi < 0) return -1;
    Interval v = idiv(isub(imul(qz, t[4], &valid), imul(qy, t[5], &valid), &valid), t[9], &valid);
    if (!valid) return 0;
    if (v.hi < 0) return -1;
    Interval sum = iadd(u, v, &valid);
    if (!valid) return 0;
    if (sum.lo >= 1) return -1;
    Interval x = {t[0], t[0]};
    x = iadd(iadd(x, imul(u, t[3], &valid), &valid), imul(v, t[6], &valid), &valid);
    if (!valid) return 0;
    if (x.hi <= low[0]) return -1;
    if (u.lo >= 0 && v.lo >= 0 && sum.hi < 1 && x.lo > high[0]) return 1;
    return 0;
}

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

static PyObject *sample_points_impl(PyObject *args, int axis_permutation, int table) {
    PyObject *objects[5], *answer = NULL;
    Py_buffer views[5] = {{0}};
    double scale;
    if (!PyArg_ParseTuple(args, table ? "OOOOdOp" : "OOOOdO", &objects[0], &objects[1],
                          &objects[2], &objects[3], &scale, &objects[4], &axis_permutation)) return NULL;
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
    int source_axis[3] = {0, 1, 2}, used_axes = 0;
    if (axis_permutation && !(scale == 0.25 || scale == 0.5 || scale == 1 ||
                              scale == 2 || scale == 3 || scale == 4 || scale == 5)) {
        PyErr_SetString(PyExc_ValueError, "Unsupported discrete-axis sample scale");
        goto cleanup;
    }
    for (int axis = 0; axis < 3; axis++) {
        if (!isfinite(size[axis]) || size[axis] <= 0 || !isfinite(span[axis]) ||
            !isfinite(matrix[axis * 4 + 3])) {
            PyErr_SetString(PyExc_ValueError, "Expected finite positive diagonal transform and size");
            goto cleanup;
        }
        int found = 0;
        for (int other = 0; other < 3; other++) {
            double coefficient = matrix[axis * 4 + other];
            if (axis_permutation) {
                if (coefficient != 0) {
                    if (found || (coefficient != 1 && coefficient != -1) || (used_axes & (1 << other))) {
                        PyErr_SetString(PyExc_ValueError, "Expected a signed unit-axis permutation");
                        goto cleanup;
                    }
                    found = 1;
                    source_axis[axis] = other;
                    used_axes |= 1 << other;
                }
            } else if ((axis == other && (!isfinite(coefficient) || coefficient <= 0)) ||
                       (axis != other && coefficient != 0)) {
                PyErr_SetString(PyExc_ValueError, "Expected a positive diagonal transform");
                goto cleanup;
            }
        }
        if (axis_permutation && !found) {
            PyErr_SetString(PyExc_ValueError, "Expected a signed unit-axis permutation");
            goto cleanup;
        }
    }
    for (Py_ssize_t i = 0; i < sample_count * 3; i++) {
        if (!isfinite(samples[i]) ||
            (axis_permutation && (samples[i] < 1e-6 || samples[i] > 1 - 1e-6))) {
            PyErr_SetString(PyExc_ValueError, "Expected finite sample coordinates");
            goto cleanup;
        }
    }
    Py_ssize_t point_count = cell_count * sample_count;
    answer = PyBytes_FromStringAndSize(NULL, point_count * 3 * (Py_ssize_t)sizeof(double));
    if (!answer) goto cleanup;
    double *output = (double *)PyBytes_AS_STRING(answer);
    /* The dense grids repeat at most 18 values on each axis. Reuse identical
     * scalar expressions within one cell, including their original rounding.
     * Bitwise keys distinguish signed zeros. No table survives this call. */
    unsigned char sample_map[8192 * 3];
    double unique[3][64];
    int counts[3] = {0, 0, 0};
    unsigned char slots[3][128] = {{0}};
    table = table && sizeof(double) == sizeof(uint64_t) && sample_count >= 64 && sample_count <= 8192;
    /* Prepared meshes and discrete axes have a single nonzero product. Each dot has
     * exactly one nonzero product; adding +0 preserves its zero sign before
     * translation. Strict floating point keeps every division and multiply
     * separate, matching the NumPy pipeline without its full-size temporaries. */
    Py_BEGIN_ALLOW_THREADS
    if (table) {
        for (Py_ssize_t sample = 0; sample < sample_count && table; sample++) {
            for (int axis = 0; axis < 3; axis++) {
                double value = samples[sample * 3 + source_axis[axis]];
                uint64_t hash;
                memcpy(&hash, &value, sizeof(hash));
                hash ^= hash >> 33;
                hash *= UINT64_C(0xff51afd7ed558ccd);
                hash ^= hash >> 33;
                unsigned int slot = (unsigned int)hash & 127;
                while (slots[axis][slot] && memcmp(&value, &unique[axis][slots[axis][slot] - 1], sizeof(double)))
                    slot = (slot + 1) & 127;
                int index = slots[axis][slot] ? slots[axis][slot] - 1 : counts[axis];
                if (index == 64) { table = 0; break; }
                if (index == counts[axis]) {
                    unique[axis][counts[axis]++] = value;
                    slots[axis][slot] = (unsigned char)(index + 1);
                }
                sample_map[sample * 3 + axis] = (unsigned char)index;
            }
        }
    }
    if (table) {
        for (Py_ssize_t cell = 0; cell < cell_count; cell++) {
            double values[3][64];
            for (int axis = 0; axis < 3; axis++) {
                int source = source_axis[axis];
                for (int i = 0; i < counts[axis]; i++) {
                    double value = (double)cells[cell * 3 + source] + unique[axis][i];
                    value /= scale;
                    value *= matrix[axis * 4 + source];
                    value += 0.0;
                    value += matrix[axis * 4 + 3];
                    value /= size[axis];
                    value *= span[axis];
                    values[axis][i] = value;
                }
            }
            for (Py_ssize_t sample = 0; sample < sample_count; sample++) {
                double *out = output + (cell * sample_count + sample) * 3;
                out[0] = values[0][sample_map[sample * 3]];
                out[1] = values[1][sample_map[sample * 3 + 1]];
                out[2] = values[2][sample_map[sample * 3 + 2]];
            }
        }
    } else {
    for (Py_ssize_t cell = 0; cell < cell_count; cell++) {
        for (Py_ssize_t sample = 0; sample < sample_count; sample++) {
            for (int axis = 0; axis < 3; axis++) {
                int source = source_axis[axis];
                double value = (double)cells[cell * 3 + source] + samples[sample * 3 + source];
                value /= scale;
                value *= matrix[axis * 4 + source];
                value += 0.0;
                value += matrix[axis * 4 + 3];
                value /= size[axis];
                value *= span[axis];
                output[(cell * sample_count + sample) * 3 + axis] = value;
            }
        }
    }
    }
    Py_END_ALLOW_THREADS
cleanup:
    for (int i = 0; i < 5; i++) if (views[i].obj) PyBuffer_Release(&views[i]);
    return answer;
}

static PyObject *sample_points(PyObject *self, PyObject *args) {
    return sample_points_impl(args, 0, 0);
}

static PyObject *axis_sample_points(PyObject *self, PyObject *args) {
    return sample_points_impl(args, 1, 0);
}

static PyObject *table_sample_points(PyObject *self, PyObject *args) {
    return sample_points_impl(args, 0, 1);
}

static PyObject *contains_primitive(PyObject *self, PyObject *args) {
    PyObject *objects[2], *output = NULL, *answer = NULL;
    Py_buffer views[2] = {{0}};
    int mode, uncertain = 0;
    if (!PyArg_ParseTuple(args, "OOi", &objects[0], &objects[1], &mode)) return NULL;
    if (!array_buffer(objects[0], &views[0], 2, 3, 0) ||
        !array_buffer(objects[1], &views[1], 2, 4, 0)) goto cleanup;
    Py_ssize_t count = views[0].shape[0], plane_count = views[1].shape[0];
    if (count > 1572864 || plane_count > 64 || mode < 0 || mode > 8) {
        PyErr_SetString(PyExc_ValueError, "Invalid primitive sampling size or mode");
        goto cleanup;
    }
    const double *points = views[0].buf, *coefficients = views[1].buf;
    for (Py_ssize_t i = 0; i < plane_count * 4; i++) {
        if (!isfinite(coefficients[i]) || fabs(coefficients[i]) > 1e12) {
            PyErr_SetString(PyExc_ValueError, "Expected bounded finite primitive planes");
            goto cleanup;
        }
    }
    output = PyBytes_FromStringAndSize(NULL, count);
    if (!output) goto cleanup;
    unsigned char *occupied = (unsigned char *)PyBytes_AS_STRING(output);
    const double upper = 1 + 1e-8;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t i = 0; i < count; i++) {
        const double *p = points + i * 3;
        int hit = p[0] >= -1e-8 && p[0] <= upper && p[1] >= -1e-8 && p[1] <= upper &&
                  p[2] >= -1e-8 && p[2] <= upper;
        if (hit && plane_count) {
            for (Py_ssize_t j = 0; j < plane_count; j++) {
                const double *plane = coefficients + j * 4;
                double value = dot3(p, plane), limit = plane[3] + 1e-8;
                /* Two differently grouped three-term dots differ by less
                 * than this bound, including BLAS FMA and subnormal rounding.
                 * Near the threshold Python repeats the COMPLETE old batch. */
                double magnitude = fabs(p[0] * plane[0]) + fabs(p[1] * plane[1]) +
                                   fabs(p[2] * plane[2]) + fabs(limit) + 1;
                if (fabs(value - limit) <= 64 * DBL_EPSILON * magnitude) uncertain = 1;
                if (value > limit) { hit = 0; break; }
            }
        } else if (hit) {
            if (mode == 1) hit = p[1] <= p[2] + 1e-8;
            else if (mode == 2) {
                double z = 1 - p[2], a = p[1] * p[1], b = z * z, value = a + b;
                if (fabs(value - upper) <= 64 * DBL_EPSILON * (a + b + 2)) uncertain = 1;
                hit = value <= upper;
            } else if (mode == 3) hit = p[1] <= p[2] + 1e-8 && p[1] <= p[0] + 1e-8;
            else if (mode >= 4) {
                int high = p[2] >= 0.5;
                if (mode == 5) high |= p[0] >= 0.5;
                else if (mode == 6) high |= p[0] <= 0.5;
                else if (mode == 7) high &= p[0] >= 0.5;
                else if (mode == 8) high &= p[0] <= 0.5;
                hit = p[1] < 0.5 || high;
            }
        }
        occupied[i] = (unsigned char)hit;
    }
    Py_END_ALLOW_THREADS
    answer = Py_BuildValue("Ni", output, uncertain);
    output = NULL;
cleanup:
    Py_XDECREF(output);
    for (int i = 0; i < 2; i++) if (views[i].obj) PyBuffer_Release(&views[i]);
    return answer;
}

static PyObject *contains(PyObject *self, PyObject *args) {
    PyObject *objects[5], *result = NULL, *answer = NULL;
    Py_buffer views[5] = {{0}};
    Py_ssize_t *stack = NULL, *parents = NULL;
    signed char *triangle_flags = NULL;
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
    if (closed && packet_size) {
        triangle_flags = PyMem_Malloc(index_count ? (size_t)index_count : 1);
        if (!triangle_flags) { PyErr_NoMemory(); goto cleanup; }
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
            if (closed) {
                for (Py_ssize_t leaf = 0; leaf < leaf_count; leaf++) {
                    const Py_ssize_t *node = nodes + leaves[leaf] * 4;
                    for (Py_ssize_t j = node[2]; j < node[2] + node[3]; j++) {
                        triangle_flags[j] = (signed char)triangle_packet(triangles + indices[j] * 10, minimum, maximum);
                    }
                }
            }
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
                    if (packet_size && triangle_flags[j]) {
                        if (triangle_flags[j] > 0) hits++;
                        continue;
                    }
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
    PyMem_Free(triangle_flags);
    for (int i = 0; i < 5; i++) if (views[i].obj) PyBuffer_Release(&views[i]);
    return answer;
}

static PyMethodDef methods[] = {
    {"contains", contains, METH_VARARGS, "Classify a bounded batch using the original mesh tree."},
    {"sample_points", sample_points, METH_VARARGS, "Fuse bounded positive diagonal sample transforms."},
    {"axis_sample_points", axis_sample_points, METH_VARARGS, "Fuse bounded discrete-axis sample transforms."},
    {"table_sample_points", table_sample_points, METH_VARARGS, "Reuse bit-identical repeated sample coordinates."},
    {"contains_primitive", contains_primitive, METH_VARARGS, "Filter exact primitive samples with conservative fallback."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_mesh_native", NULL, -1, methods};
PyMODINIT_FUNC PyInit__mesh_native(void) {
    PyObject *result = PyModule_Create(&module);
    if (result && (PyModule_AddIntConstant(result, "PACKET_QUERIES", 1) < 0 ||
                   PyModule_AddIntConstant(result, "INTERVAL_PACKETS", 1) < 0)) {
        Py_DECREF(result);
        return NULL;
    }
    return result;
}
