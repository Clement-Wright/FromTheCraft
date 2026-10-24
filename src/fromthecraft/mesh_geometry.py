"""Bounded triangle sampling: closed solids and deliberate thin surfaces."""

from dataclasses import replace
from functools import lru_cache
from concurrent.futures import TimeoutError

import numpy as np
from collections import OrderedDict
from copy import copy
from os import cpu_count

from .model import Cancelled

try:
    from . import _mesh_native
except ImportError:
    _mesh_native = None

# Large decorative meshes can exceed the original limits even at 1x scale.
# These bound cumulative work; temporary arrays remain batched independently.
MAX_SURFACE_SEEDS = 200_000_000
MAX_MESH_SAMPLE_WORK = 20_000_000_000


def native_worker_count():
    return max(1, min(8, cpu_count() or 1))


def _cross3(a, b):
    """The original cross-product arithmetic for the fixed three-component case."""
    return np.array(
        [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    )


@lru_cache(maxsize=64)
def _seed_template(divisions, offset_count):
    # Preserve row/offset/point order and the original divisions exactly. Only
    # common, bounded templates are cached; large triangles keep the row path.
    u, v, offsets = [], [], []
    for row in range(divisions + 1):
        along = np.arange(divisions - row + 1) / divisions
        for offset in range(offset_count):
            u.extend([row / divisions] * len(along))
            v.extend(along)
            offsets.extend([offset] * len(along))
    return np.asarray(u), np.asarray(v), np.asarray(offsets, dtype=np.intp)


def is_closed(vertices, indices):
    _, welded = np.unique(np.round(vertices, 7), axis=0, return_inverse=True)
    faces = welded[indices]
    valid = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    faces = faces[valid]
    if len(faces) < 4:
        return False
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    _, counts = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def _surface_seed_rows(part, scale, cancelled=None):
    vertices, indices = part.mesh[:2]
    emitted = 0
    for triangle in vertices[indices]:
        if cancelled and cancelled():
            raise Cancelled("Conversion cancelled")
        a, b, c = triangle
        edges = np.array([b - a, c - a, c - b]) @ part.transform[:3, :3].T
        divisions = max(1, int(np.ceil(np.linalg.norm(edges, axis=1).max() * scale * 4)))
        offsets = [np.zeros(3)]
        if not part.mesh[2]:
            normal = _cross3(edges[0], edges[1])
            length = np.linalg.norm(normal)
            if length > 1e-12:
                delta = np.linalg.solve(part.transform[:3, :3], normal / length * part.mesh[3] * 0.4999)
                offsets.extend((delta, -delta))
        count = (divisions + 1) * (divisions + 2) // 2 * len(offsets)
        emitted += count
        if emitted > MAX_SURFACE_SEEDS:
            raise ValueError("Decorative surface seed budget exceeded; choose a smaller scale")
        if divisions <= 128:
            u, v, selected = _seed_template(divisions, len(offsets))
            deltas = np.asarray(offsets)
            for start in range(0, len(u), 4096):
                if cancelled and cancelled():
                    raise Cancelled("Conversion cancelled")
                batch = slice(start, start + 4096)
                points = a + (b - a) * u[batch, None] + v[batch, None] * (c - a)
                yield np.clip(points + deltas[selected[batch]], 1e-5, 1 - 1e-5)
            continue
        for row in range(divisions + 1):
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            v = np.arange(divisions - row + 1) / divisions
            points = a + (b - a) * (row / divisions) + v[:, None] * (c - a)
            for delta in offsets:
                yield np.clip(points + delta, 1e-5, 1 - 1e-5)


def surface_seed_batches(part, scale, cancelled=None):
    """Keep original seed order and transform batch boundaries without Python rows."""
    buffer = np.empty((4096, 3))
    used = 0
    for row in _surface_seed_rows(part, scale, cancelled):
        start = 0
        while start < len(row):
            count = min(len(row) - start, len(buffer) - used)
            buffer[used : used + count] = row[start : start + count]
            used += count
            start += count
            if used == len(buffer):
                yield buffer
                buffer = np.empty((4096, 3))
                used = 0
    if used:
        yield buffer[:used]


def surface_seeds(part, scale, cancelled=None):
    for row in _surface_seed_rows(part, scale, cancelled):
        yield from row


class MeshSamplerCache:
    """Per-voxelization exact geometry reuse; no work/cancellation state is shared."""

    def __init__(self, max_bytes=32 * 1024**2):
        self.entries = OrderedDict()
        self.bytes, self.max_bytes = 0, max_bytes

    def get(self, vertices, indices, thickness, cancelled, closed):
        key = (
            vertices.dtype.str,
            vertices.shape,
            vertices.tobytes(),
            indices.dtype.str,
            indices.shape,
            indices.tobytes(),
            thickness,
            closed,
        )
        entry = self.entries.pop(key, None)
        if entry is None:
            sampler = MeshSampler(vertices, indices, thickness, cancelled, closed)
            # Conservative allowance for Python triangle/edge arrays, tree,
            # coefficients and exact key bytes. Oversize meshes are not cached.
            weight = len(key[2]) + len(key[5]) + len(indices) * 4096 + 4096
        else:
            original, weight = entry
            sampler = copy(original)
            sampler.cancelled, sampler.work, sampler.executor = cancelled, 0, None
        if weight <= self.max_bytes:
            while self.entries and self.bytes + (weight if entry is None else 0) > self.max_bytes:
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= removed
            self.entries[key] = sampler, weight
            if entry is None:
                self.bytes += weight
        return sampler


class MeshSampler:
    def __init__(self, vertices, indices, thickness=0.125, cancelled=None, closed=None):
        self.closed = is_closed(vertices, indices) if closed is None else closed
        self.radius = thickness / 2
        self.cancelled, self.work = cancelled, 0
        self.triangles = np.asarray(vertices)[indices].astype(float)
        if self.closed:
            # Sheared coordinates cast an oblique ray and avoid regular grid seams.
            self.triangles[:, :, 1] -= self.triangles[:, :, 0] * 0.1732050807568877
            self.triangles[:, :, 2] -= self.triangles[:, :, 0] * 0.3178372451957823
        self.low, self.high = self.triangles.min(1), self.triangles.max(1)
        self.tree = self._tree(np.arange(len(indices)))
        self.geometry = {}
        self.native_data = None
        self.native_leaves = {}
        self.executor = None
        self.native_threads = 4

    def _native_query(self, points, arrays, closed):
        if self.executor is None or len(points) < 8192 or (closed and len(self.triangles) < 48):
            return _mesh_native.contains(points, *arrays, closed, self.radius)
        step = (len(points) + self.native_threads - 1) // self.native_threads
        futures = [
            self.executor.submit(
                _mesh_native.contains, points[start : start + step], *arrays, closed, self.radius
            )
            for start in range(0, len(points), step)
        ]
        answers = []
        for future in futures:
            while True:
                if self.cancelled and self.cancelled():
                    raise Cancelled("Conversion cancelled")
                try:
                    answer = future.result(timeout=0.05)
                    if answer[2]:
                        for pending in futures:
                            pending.cancel()
                        return b"", 0, True
                    answers.append(answer)
                    break
                except TimeoutError:
                    continue
        # A numerical ambiguity in any slice repeats the COMPLETE original
        # NumPy leaf batch, preserving its BLAS sizes and floating-point bits.
        return (
            b"".join(answer[0] for answer in answers),
            sum(answer[1] for answer in answers),
            any(answer[2] for answer in answers),
        )

    def _native_arrays(self):
        if self.native_data is None:
            bounds, nodes, indices = [], [], []

            def flatten(tree):
                low, high, left, right = tree
                index = len(nodes)
                bounds.append((low, high))
                nodes.append(None)
                if right is None:
                    nodes[index] = (-1, -1, len(indices), len(left))
                    indices.extend(left)
                else:
                    nodes[index] = (flatten(left), flatten(right), 0, 0)
                return index

            flatten(self.tree)
            coefficients = np.zeros((len(self.triangles), 10 if self.closed else 38))
            for i in range(len(self.triangles)):
                if i % 256 == 0 and self.cancelled and self.cancelled():
                    raise Cancelled("Conversion cancelled")
                data = self._triangle(i)
                if data is None:
                    continue
                row = coefficients[i]
                row[:3], row[3:6], row[6:9] = data[:3]
                if self.closed:
                    row[9] = data[3]
                else:
                    a, ab, ac, normal, norm2, aa, bb, cc, denominator, edges = data
                    row[9:12] = normal
                    row[12:17] = norm2, aa, bb, cc, denominator
                    for edge, (start, direction, length) in enumerate(edges):
                        offset = 17 + 7 * edge
                        row[offset : offset + 3] = start
                        row[offset + 3 : offset + 6] = direction
                        row[offset + 6] = length
            self.native_data = (
                coefficients,
                np.asarray(bounds).reshape(-1, 6),
                np.asarray(nodes, dtype=np.intp),
                np.asarray(indices, dtype=np.intp),
            )
        return self.native_data

    def _triangle(self, index):
        if index not in self.geometry:
            a, b, c = self.triangles[index]
            ab, ac = b - a, c - a
            if self.closed:
                denominator = ab[1] * ac[2] - ab[2] * ac[1]
                data = None if abs(denominator) < 1e-14 else (a, ab, ac, denominator)
            else:
                normal = _cross3(ab, ac)
                norm2 = normal @ normal
                aa, bb, cc = ab @ ab, ab @ ac, ac @ ac
                denominator = aa * cc - bb * bb
                edges = tuple(
                    (start, end - start, (end - start) @ (end - start))
                    for start, end in ((a, b), (b, c), (c, a))
                )
                data = (a, ab, ac, normal, norm2, aa, bb, cc, denominator, edges)
                if norm2 < 1e-20 or denominator <= 1e-20:
                    data = None
            self.geometry[index] = data
        return self.geometry[index]

    def _tree(self, ids):
        low, high = self.low[ids].min(0), self.high[ids].max(0)
        if len(ids) <= 12:
            return low, high, ids, None
        axis = int(np.argmax(np.ptp((self.low[ids] + self.high[ids]) / 2, axis=0)))
        order = ids[np.argsort(self.low[ids, axis] + self.high[ids, axis])]
        middle = len(order) // 2
        return low, high, self._tree(order[:middle]), self._tree(order[middle:])

    def contains(self, points):
        points = np.asarray(points)
        # Closed meshes shear their query coordinates. Open meshes only read
        # them, so their already contiguous batch can stay shared and immutable.
        if self.closed or not points.flags.c_contiguous:
            points = points.copy()
        if self.closed:
            points[:, 1] -= points[:, 0] * 0.1732050807568877
            points[:, 2] -= points[:, 0] * 0.3178372451957823
            points[:, 1:] += (1e-10, 3.14159e-10)
        result = np.zeros(len(points), dtype=np.int32)

        def visit(node, candidates, native=True):
            if self.cancelled and self.cancelled():
                raise Cancelled("Conversion cancelled")
            low, high, left, right = node
            p = points[candidates]
            if self.closed:
                keep = (p[:, 0] <= high[0]) & np.all((p[:, 1:] >= low[1:]) & (p[:, 1:] <= high[1:]), axis=1)
            else:
                keep = np.all((p >= low - self.radius) & (p <= high + self.radius), axis=1) & (
                    result[candidates] == 0
                )
            candidates = candidates[keep]
            if not len(candidates):
                return
            if right is not None:
                visit(left, candidates, native)
                visit(right, candidates, native)
                return
            self.work += len(candidates) * len(left)
            if self.work > MAX_MESH_SAMPLE_WORK:
                raise ValueError(
                    "Decorative mesh sampling budget exceeded; choose a smaller scale or structure-only mode"
                )
            p = points[candidates]
            if native and not self.closed and _mesh_native is not None and points.dtype == np.float64:
                key = id(left)
                if key not in self.native_leaves:
                    self.native_leaves[key] = (
                        np.asarray((low, high)).reshape(1, 6),
                        np.asarray([[-1, -1, 0, len(left)]], dtype=np.intp),
                        left,
                    )
                occupied, _, uncertain = self._native_query(
                    p, (self._native_arrays()[0], *self.native_leaves[key]), False
                )
                if not uncertain:
                    result[candidates] |= np.frombuffer(occupied, dtype=np.uint8)
                    return
            for index in left:
                data = self._triangle(index)
                if data is None:
                    continue
                if self.closed:
                    a, ab, ac, denominator = data
                    q = p - a
                    u = (q[:, 1] * ac[2] - q[:, 2] * ac[1]) / denominator
                    v = (ab[1] * q[:, 2] - ab[2] * q[:, 1]) / denominator
                    hit = (u >= 0) & (v >= 0) & (u + v < 1) & (a[0] + u * ab[0] + v * ac[0] > p[:, 0])
                    result[candidates] += hit
                else:
                    a, ab, ac, normal, norm2, aa, bb, cc, denominator, edges = data
                    q = p - a
                    normal_distance = q @ normal
                    projected = q - normal_distance[:, None] * normal / norm2
                    u = (cc * (projected @ ab) - bb * (projected @ ac)) / denominator
                    v = (aa * (projected @ ac) - bb * (projected @ ab)) / denominator
                    distance = np.where(
                        (u >= 0) & (v >= 0) & (u + v <= 1), normal_distance**2 / norm2, np.inf
                    )
                    for start, edge, length in edges:
                        if length < 1e-20:
                            continue
                        t = np.clip(((p - start) @ edge) / length, 0, 1)
                        d = p - start - t[:, None] * edge
                        distance = np.minimum(distance, np.sum(d * d, axis=1))
                    result[candidates] |= distance <= self.radius**2 + 1e-12

        # Bound temporary vectors independently of the caller's sampling batch.
        for start in range(0, len(points), 32768):
            if self.cancelled and self.cancelled():
                raise Cancelled("Conversion cancelled")
            if _mesh_native is not None and points.dtype == np.float64 and points.flags.c_contiguous:
                occupied, work, uncertain = self._native_query(
                    points[start : start + 32768], self._native_arrays(), self.closed
                )
                if not uncertain:
                    self.work += work
                    if self.work > MAX_MESH_SAMPLE_WORK:
                        raise ValueError(
                            "Decorative mesh sampling budget exceeded; choose a smaller scale or structure-only mode"
                        )
                    result[start : start + 32768] = np.frombuffer(occupied, dtype=np.uint8)
                    continue
                # Preserve original BLAS rounding for the complete original
                # batch, rather than recalculating a differently sized subset.
            # A one-leaf whole-tree attempt already established uncertainty;
            # do not repeat that identical native call before NumPy fallback.
            visit(self.tree, np.arange(start, min(len(points), start + 32768)), self.tree[3] is not None)
        return (result % 2 != 0) if self.closed else (result != 0)


def prepare_meshes(scene, mode, thickness, scale):
    if mode == "structure":
        return replace(scene, parts=[p for p in scene.parts if not p.decoration])
    notices = scene.notices.copy()
    replaced = (
        {
            p.source_record.host_id
            for p in scene.parts
            if p.decoration and p.replaces_host and p.source_record and p.source_record.host_id
        }
        if mode == "appearance"
        else set()
    )
    if mode == "appearance":
        replaced.update(
            r.host_id
            for r in scene.source_records
            if r.hide_host and r.geometry_status in {"resolved", "empty"} and r.host_id
        )
    parts = []
    topology = {}
    for part in scene.parts:
        if part.source_record and part.source_record.id in replaced:
            continue
        if not part.mesh:
            parts.append(part)
            continue
        vertices, indices = part.mesh[:2]
        key = id(vertices)
        if key not in topology:
            topology[key] = is_closed(vertices, indices)
        closed = topology[key]
        world = vertices @ part.transform[:3, :3].T + part.transform[:3, 3]
        radius = 0 if closed else thickness / (2 * scale)
        low, high = world.min(0) - radius, world.max(0) + radius
        span = np.maximum(high - low, 1e-8)
        transform = np.eye(4)
        transform[:3, :3] = np.diag(span)
        transform[:3, 3] = low
        parts.append(
            replace(
                part,
                transform=transform,
                mesh=((world - low) / span, indices, closed, thickness / scale, span),
            )
        )
        if not closed:
            notices[
                f"Open decoration surfaces use {thickness:g}-cell thickness; record {part.source_record.id if part.source_record else part.identity}"
            ] += 1
        if np.min(span) * scale < 1:
            notices["Sub-block decorative detail uses a finite sampled approximation"] += 1
    if mode == "appearance":
        notices[
            "Appearance-focused conversion removes hosts only for verified HideOriginalMesh attachments; physical occupancy changes"
        ] += 1
    return replace(scene, parts=parts, notices=notices)
