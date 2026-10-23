"""Frozen pre-optimization sampler for exact occupancy regression checks."""

import numpy as np
from fromthecraft.model import Cancelled
from fromthecraft.mesh_geometry import is_closed, MAX_MESH_SAMPLE_WORK, MAX_SURFACE_SEEDS


class ReferenceMeshSampler:
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

    def _tree(self, ids):
        low, high = self.low[ids].min(0), self.high[ids].max(0)
        if len(ids) <= 12:
            return low, high, ids, None
        axis = int(np.argmax(np.ptp((self.low[ids] + self.high[ids]) / 2, axis=0)))
        order = ids[np.argsort(self.low[ids, axis] + self.high[ids, axis])]
        middle = len(order) // 2
        return low, high, self._tree(order[:middle]), self._tree(order[middle:])

    def contains(self, points):
        points = np.asarray(points).copy()
        if self.closed:
            points[:, 1] -= points[:, 0] * 0.1732050807568877
            points[:, 2] -= points[:, 0] * 0.3178372451957823
            points[:, 1:] += (1e-10, 3.14159e-10)
        result = np.zeros(len(points), dtype=np.int32)

        def visit(node, candidates):
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
                visit(left, candidates)
                visit(right, candidates)
                return
            self.work += len(candidates) * len(left)
            if self.work > MAX_MESH_SAMPLE_WORK:
                raise ValueError(
                    "Decorative mesh sampling budget exceeded; choose a smaller scale or structure-only mode"
                )
            p = points[candidates]
            for index in left:
                a, b, c = self.triangles[index]
                ab, ac = b - a, c - a
                if self.closed:
                    denominator = ab[1] * ac[2] - ab[2] * ac[1]
                    if abs(denominator) < 1e-14:
                        continue
                    q = p - a
                    u = (q[:, 1] * ac[2] - q[:, 2] * ac[1]) / denominator
                    v = (ab[1] * q[:, 2] - ab[2] * q[:, 1]) / denominator
                    hit = (u >= 0) & (v >= 0) & (u + v < 1) & (a[0] + u * ab[0] + v * ac[0] > p[:, 0])
                    result[candidates] += hit
                else:
                    normal = np.cross(ab, ac)
                    norm2 = normal @ normal
                    if norm2 < 1e-20:
                        continue
                    q = p - a
                    normal_distance = q @ normal
                    projected = q - normal_distance[:, None] * normal / norm2
                    aa, bb, cc = ab @ ab, ab @ ac, ac @ ac
                    denominator = aa * cc - bb * bb
                    if denominator <= 1e-20:
                        continue
                    u = (cc * (projected @ ab) - bb * (projected @ ac)) / denominator
                    v = (aa * (projected @ ac) - bb * (projected @ ab)) / denominator
                    distance = np.where(
                        (u >= 0) & (v >= 0) & (u + v <= 1), normal_distance**2 / norm2, np.inf
                    )
                    for start, end in ((a, b), (b, c), (c, a)):
                        edge = end - start
                        length = edge @ edge
                        if length < 1e-20:
                            continue
                        t = np.clip(((p - start) @ edge) / length, 0, 1)
                        d = p - start - t[:, None] * edge
                        distance = np.minimum(distance, np.sum(d * d, axis=1))
                    result[candidates] |= distance <= self.radius**2 + 1e-12

        # Bound temporary vectors independently of the caller's sampling batch.
        for start in range(0, len(points), 32768):
            visit(self.tree, np.arange(start, min(len(points), start + 32768)))
        return (result % 2 != 0) if self.closed else (result != 0)



def reference_surface_seeds(part, scale, cancelled=None):
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
            normal = np.cross(edges[0], edges[1])
            length = np.linalg.norm(normal)
            if length > 1e-12:
                delta = np.linalg.solve(part.transform[:3, :3], normal / length * part.mesh[3] * 0.4999)
                offsets.extend((delta, -delta))
        count = (divisions + 1) * (divisions + 2) // 2 * len(offsets)
        emitted += count
        if emitted > MAX_SURFACE_SEEDS:
            raise ValueError("Decorative surface seed budget exceeded; choose a smaller scale")
        for row in range(divisions + 1):
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            v = np.arange(divisions - row + 1) / divisions
            points = a + (b - a) * (row / divisions) + v[:, None] * (c - a)
            for delta in offsets:
                yield from np.clip(points + delta, 1e-5, 1 - 1e-5)

