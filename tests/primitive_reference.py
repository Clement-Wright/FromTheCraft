"""Frozen pre-native primitive predicates, including NumPy's original dot sizes."""

import numpy as np

from fromthecraft.ftd_shapes import planes


def reference_contains(shape, points):
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
