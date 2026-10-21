from itertools import product

import numpy as np

from .model import MAX_AXIS, MAX_VOLUME, Scene

# FtD's 24 discrete orientations, forward and up. Right = up cross forward.
FORWARD = [(0,0,1),(1,0,0),(0,0,-1),(-1,0,0)] + [(0,-1,0)]*4 + [(0,1,0)]*4 + [(0,0,1),(1,0,0),(0,0,-1),(-1,0,0),(0,0,1),(0,0,-1),(0,0,1),(0,0,-1),(1,0,0),(-1,0,0),(1,0,0),(-1,0,0)]
UP = [(0,1,0)]*4 + [(0,0,1),(1,0,0),(0,0,-1),(-1,0,0)]*2 + [(0,-1,0)]*4 + [(1,0,0),(1,0,0),(-1,0,0),(-1,0,0),(0,0,1),(0,0,1),(0,0,-1),(0,0,-1)]


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
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


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


def voxelize(scene: Scene, scale=1):
    cells = {}
    low, high = bounds(scene, scale)
    origin = np.floor(low + 1e-6).astype(int)
    checked_size(np.maximum(1, np.ceil(high-1e-6).astype(int)-origin))
    for part in scene.parts:
        for p in product(*[range(int(n)) for n in part.size]):
            center = part.transform[:3, :3] @ (np.array(p)+0.5) + part.transform[:3, 3]
            cell = tuple(np.floor(center*scale+1e-6).astype(int)-origin)
            cells.setdefault(cell, part)
    return cells, tuple(float(n) for n in origin)
