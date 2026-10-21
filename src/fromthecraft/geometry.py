from itertools import product
from dataclasses import replace
from collections import deque

import numpy as np

from .ftd_shapes import planes
from .model import MAX_AXIS, MAX_PARTS, MAX_VOLUME, Cancelled, Scene

# FtD's 24 discrete orientations, forward and up. Right = up cross forward.
FORWARD = (
    [(0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0)]
    + [(0, -1, 0)] * 4
    + [(0, 1, 0)] * 4
    + [
        (0, 0, 1),
        (1, 0, 0),
        (0, 0, -1),
        (-1, 0, 0),
        (0, 0, 1),
        (0, 0, -1),
        (0, 0, 1),
        (0, 0, -1),
        (1, 0, 0),
        (-1, 0, 0),
        (1, 0, 0),
        (-1, 0, 0),
    ]
)
UP = (
    [(0, 1, 0)] * 4
    + [(0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0)] * 2
    + [(0, -1, 0)] * 4
    + [(1, 0, 0), (1, 0, 0), (-1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, 1), (0, 0, -1), (0, 0, -1)]
)


def rotation(index: int) -> np.ndarray:
    if not 0 <= index < 24:
        raise ValueError(f"Invalid FtD block rotation: {index}")
    f, u = np.array(FORWARD[index]), np.array(UP[index])
    return np.column_stack((np.cross(u, f), u, f)).astype(float)


def quaternion(values) -> np.ndarray:
    x, y, z, w = np.asarray(values, dtype=float)
    length = np.linalg.norm([x, y, z, w])
    if not np.isfinite(length) or length < 1e-8:
        raise ValueError("Invalid construct quaternion")
    x, y, z, w = np.array([x, y, z, w]) / length
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def bounds(scene: Scene, scale=1):
    if not scene.parts:
        return np.zeros(3), np.zeros(3)
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    for part in scene.parts:
        corners = np.array(list(product(*[(0, n) for n in part.size])))
        points = (corners @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
        low, high = np.minimum(low, points.min(0)), np.maximum(high, points.max(0))
    return low, high


def checked_size(size):
    if len(size) != 3 or any(int(n) != n or n <= 0 or n > MAX_AXIS for n in size):
        raise ValueError(f"Dimensions must be 1–{MAX_AXIS} cells on each axis")
    if int(np.prod(size, dtype=np.int64)) > MAX_VOLUME:
        raise ValueError(f"Structure exceeds the {MAX_VOLUME:,}-cell bounding-volume limit")
    return tuple(int(n) for n in size)


def contains(shape, points):
    x, y, z = points.T
    inside = np.all((points >= -1e-8) & (points <= 1 + 1e-8), axis=1)
    clipping = planes(shape)
    if clipping:
        coefficients = np.asarray(clipping)
        inside &= np.all(points @ coefficients[:, :3].T <= coefficients[:, 3] + 1e-8, axis=1)
    elif shape == "wedge":
        inside &= y <= z + 1e-8
    elif shape == "curve":
        inside &= y * y + (1 - z) ** 2 <= 1 + 1e-8
    elif shape == "corner":
        inside &= (y <= z + 1e-8) & (y <= x + 1e-8)
    elif shape.startswith("stairs"):
        high = z >= 0.5
        if "inner_left" in shape:
            high |= x >= 0.5
        elif "inner_right" in shape:
            high |= x <= 0.5
        elif "outer_left" in shape:
            high &= x >= 0.5
        elif "outer_right" in shape:
            high &= x <= 0.5
        inside &= (y < 0.5) | high
    return inside


SAMPLES = np.array(list(product((0.25, 0.75), repeat=3)))


def cell_shape(mask):
    if mask.all():
        return "box"
    for axis in (1, 0, 2):
        bottom = SAMPLES[:, axis] < 0.5
        prefix = "slab_" if axis == 1 else f"slab_{'xyz'[axis]}_"
        if np.array_equal(mask, bottom):
            return prefix + "bottom"
        if np.array_equal(mask, ~bottom):
            return prefix + "top"
    bottom = SAMPLES[:, 1] < 0.5
    for facing, axis, positive in (
        ("south", 2, True),
        ("north", 2, False),
        ("east", 0, True),
        ("west", 0, False),
    ):
        high = (SAMPLES[:, axis] > 0.5) if positive else (SAMPLES[:, axis] < 0.5)
        for half, base in (("bottom", bottom), ("top", ~bottom)):
            if np.array_equal(mask, base | high):
                return f"step_{facing}_{half}"
    return "box"


def voxelize(scene: Scene, scale=1, progress=None, cancelled=None):
    cells = {}
    low, high = bounds(scene, scale)
    origin = np.floor(low + 1e-6).astype(int)
    checked_size(np.maximum(1, np.ceil(high - 1e-6).astype(int) - origin))
    for index, part in enumerate(scene.parts):
        if index % 64 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(index / max(1, len(scene.parts)) * 0.75)
        corners = np.array(list(product(*[(0, n) for n in part.size])))
        world = (corners @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
        pmin, pmax = np.floor(world.min(0) + 1e-7).astype(int), np.ceil(world.max(0) - 1e-7).astype(int)
        if int(np.prod(pmax - pmin)) > MAX_PARTS:
            raise ValueError("One part's sampled footprint is too large; choose a smaller scale")
        candidates = np.array(list(product(*[range(a, b) for a, b in zip(pmin, pmax)])))
        if len(candidates) == 0:
            continue
        # Boxes on integer grid boundaries need no occupancy samples.
        aligned = np.allclose(part.transform[:3, :3], np.round(part.transform[:3, :3]))
        grid_box = np.allclose(world, np.round(world), rtol=0, atol=1e-7)
        if part.shape == "box" and aligned and grid_box:
            masks = np.ones((len(candidates), 8), dtype=bool)
        else:
            inv = np.linalg.inv(part.transform)
            points = (candidates[:, None, :] + SAMPLES).reshape(-1, 3) / scale
            local = (points @ inv[:3, :3].T + inv[:3, 3]) / part.size
            masks = contains(part.shape, local).reshape(-1, 8)
        for position, mask in zip(candidates, masks):
            if mask.any():
                shape = cell_shape(mask) if aligned else "box"
                cells.setdefault(
                    tuple(position - origin), replace(part, shape=shape) if shape != part.shape else part
                )
        # Forward sampling protects small features that fall between target sample centers.
        if not aligned or min(part.size) * scale < 0.5 or part.shape != "box":
            axes = [
                np.r_[
                    1e-4,
                    (np.arange(max(1, int(np.ceil(n * scale * 2)))) + 0.5)
                    / max(1, int(np.ceil(n * scale * 2))),
                    1 - 1e-4,
                ]
                for n in part.size
            ]
            seeds = np.array(list(product(*axes)))
            seeds = seeds[contains(part.shape, seeds)] * part.size
            world_seeds = (seeds @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
            positions = np.floor(world_seeds + 1e-7).astype(int)
            seed_masks = {}
            octants = ((world_seeds - positions >= 0.5).astype(int) @ [4, 2, 1]).tolist()
            for position, octant in zip(positions, octants):
                key = tuple(position - origin)
                if key not in cells:
                    seed_masks[key] = seed_masks.get(key, 0) | (1 << octant)
            for position, mask in seed_masks.items():
                occupied = np.asarray([bool(mask & (1 << bit)) for bit in range(8)])
                shape = cell_shape(occupied) if aligned else "box"
                cells[position] = replace(part, shape=shape)
        if len(cells) > MAX_PARTS:
            raise ValueError(
                f"Output exceeds {MAX_PARTS:,} occupied cells; choose a smaller scale or structure"
            )
    if cancelled and cancelled():
        raise Cancelled("Conversion cancelled")
    return cells, tuple(float(n) for n in origin)


def hollow_cells(cells, thickness=1, cancelled=None, progress=None):
    """Keep cells within the requested face-neighbor distance of exterior air."""
    if thickness not in (1, 2, 3, 4):
        raise ValueError("Shell thickness must be 1, 2, 3, or 4 cells")
    if cancelled and cancelled():
        raise Cancelled("Conversion cancelled")
    if not cells:
        return {}
    positions = np.asarray(list(cells), dtype=np.intp)
    size = positions.max(0) + 1
    checked_size(size)
    # Scan air along the longest axis, so long narrow structures need fewer spans.
    order = np.argsort(-size)
    points = positions[:, order] + 1
    solid = np.zeros(tuple(size[order] + 2), dtype=bool, order="F")
    solid[tuple(points.T)] = True
    outside = np.zeros_like(solid)
    pending = deque([(0, 0, 0)])
    spans = 0
    while pending:
        x, y, z = pending.popleft()
        if outside[x, y, z] or solid[x, y, z]:
            continue
        if spans % 128 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(0.78)
        clear = ~(solid[:, y, z] | outside[:, y, z])
        before = np.flatnonzero(~clear[:x])
        after = np.flatnonzero(~clear[x + 1 :])
        left = int(before[-1] + 1) if len(before) else 0
        right = int(x + 1 + after[0]) if len(after) else len(clear)
        outside[left:right, y, z] = True
        for ny, nz in ((y - 1, z), (y + 1, z), (y, z - 1), (y, z + 1)):
            if not (0 <= ny < solid.shape[1] and 0 <= nz < solid.shape[2]):
                continue
            free = ~(solid[left:right, ny, nz] | outside[left:right, ny, nz])
            starts = np.flatnonzero(free & ~np.r_[False, free[:-1]])
            pending.extend((left + int(start), ny, nz) for start in starts)
        spans += 1
    # Expand through grid cells after finding exterior air; sealed cavities stay sealed.
    for _ in range(thickness):
        if cancelled and cancelled():
            raise Cancelled("Conversion cancelled")
        grown = outside.copy()
        for axis in range(3):
            lower, upper = [slice(None)] * 3, [slice(None)] * 3
            lower[axis], upper[axis] = slice(None, -1), slice(1, None)
            grown[tuple(lower)] |= outside[tuple(upper)]
            grown[tuple(upper)] |= outside[tuple(lower)]
        outside = grown
    keep = outside[tuple(points.T)]
    if progress:
        progress(0.88)
    return {position: part for (position, part), retained in zip(cells.items(), keep) if retained}
