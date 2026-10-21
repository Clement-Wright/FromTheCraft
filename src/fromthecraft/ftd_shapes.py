"""Native convex hull families, in normalized Unity mesh coordinates.

Halfspaces use ax + by + cz <= d. The same planes drive sampling and the
preview vertices. Definitions were checked against locally installed mesh
caches, whose importer negates the source OBJ X coordinate.
"""

import re
from functools import lru_cache
from itertools import combinations

import numpy as np


PLANES = {
    "ftd_slope": ((0, 1, 1, 1),),
    "ftd_wedge": ((2, 0, 1, 2), (-2, 0, 1, 0)),
    "ftd_corner_left": ((1, 1, 1, 1),),
    "ftd_corner_right": ((-1, 1, 1, 0),),
    "ftd_corner_inverted_left": ((1, 1, 1, 2),),
    "ftd_corner_inverted_right": ((-1, 1, 1, 1),),
    "ftd_diagonal": ((-1, 1, 0, 0),),
    "ftd_diagonal_mirrored": ((1, 1, 0, 1),),
    "ftd_square_left": ((0, 1, 1, 1), (1, 1, 0, 1)),
    "ftd_square_right": ((0, 1, 1, 1), (-1, 1, 0, 0)),
    "ftd_backed_left": ((0, 1, 1, 1), (1, 0, 1, 1)),
    "ftd_backed_right": ((0, 1, 1, 1), (-1, 0, 1, 0)),
    "ftd_wedge_front": ((-1, 0.5, 0.5, 0), (1, 0.5, 0.5, 1)),
    "ftd_wedge_back": ((-1, 0.5, 0.5, 0.5), (1, 0.5, 0.5, 1.5)),
}
CUBE = ((-1, 0, 0, 0), (1, 0, 0, 1), (0, -1, 0, 0), (0, 1, 0, 1), (0, 0, -1, 0), (0, 0, 1, 1))


def native_shape(entry):
    if "MeshName" not in entry and "NativeShape" in entry:
        return entry["NativeShape"]
    # Some game display names reference the wrong side or length; use the resolved mesh.
    name = entry.get("MeshName", entry["Name"]).lower()
    side = "left" if "left" in name else "right" if "right" in name else None
    transition = re.search(r"(\d+)m\s+to\s+(\d+)m.*slope (inverse )?transition", name)
    if transition and side:
        a, b = int(transition[1]), int(transition[2])
        if 0 < a < b <= 4:
            inverse = "inverse_" if transition[3] else ""
            return f"ftd_transition_{inverse}{side}_{a}_{b}"
    if "offset slope" in name and side:
        length = re.search(r"(\d+)m", name)
        if length and 1 <= int(length[1]) <= 4:
            return f"ftd_offset_{side}_{length[1]}"
    if "beam slope" in name:
        return "ftd_diagonal_mirrored" if "mirrored" in name else "ftd_diagonal"
    if "corner" in name and side:
        if "square backed" in name:
            return "ftd_backed_" + side
        if "square" in name:
            return "ftd_square_" + side
        if "inverted" in name:
            return "ftd_corner_inverted_" + side
        if "triangle" in name:
            return "ftd_corner_" + side
    compact = re.sub(r"[^a-z]", "", name)
    if "wedgefront" in compact or ("wedge" in name and "front" in name):
        return "ftd_wedge_front"
    if "wedgeback" in compact or ("wedge" in name and "back" in name):
        return "ftd_wedge_back"
    if "wedge" in name:
        return "ftd_wedge"
    if "down slope" in name:
        return "ftd_slope"
    return None


@lru_cache(maxsize=128)
def planes(shape):
    if shape in PLANES:
        return PLANES[shape]
    if shape.startswith("ftd_transition_"):
        *family, a, b = shape.split("_")
        ratio = int(a) / int(b)
        right, inverse = "right" in family, "inverse" in family
        if inverse:
            diagonal = ((1 - ratio), 1, 1, 2 - ratio) if right else (-(1 - ratio), 1, 1, 1)
            return ((0, ratio, 1, 1), diagonal)
        diagonal = (-(1 - ratio), ratio, 1, ratio) if right else ((1 - ratio), ratio, 1, 1)
        return ((0, 1, 1, 1), diagonal)
    if shape.startswith("ftd_offset_"):
        _, _, side, n = shape.split("_")
        n = int(n)
        return ((-1, n, n + 1, n),) if side == "right" else ((1, n, n + 1, n + 1),)
    return ()


@lru_cache(maxsize=128)
def vertices(shape):
    clipping = planes(shape)
    if not clipping:
        return ()
    constraints = np.asarray(CUBE + clipping, dtype=float)
    points = set()
    for triple in combinations(constraints, 3):
        system = np.asarray(triple)
        if abs(np.linalg.det(system[:, :3])) < 1e-8:
            continue
        point = np.linalg.solve(system[:, :3], system[:, 3])
        if np.all(constraints[:, :3] @ point <= constraints[:, 3] + 1e-8):
            points.add(tuple(np.round(point, 8)))
    return tuple(float(n) for point in sorted(points) for n in point)
