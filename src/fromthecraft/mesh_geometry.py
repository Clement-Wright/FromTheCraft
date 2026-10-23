"""Bounded triangle sampling: closed solids and deliberate thin surfaces."""

from dataclasses import replace

import numpy as np

from .model import Cancelled


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
            if self.work > 200_000_000:
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
