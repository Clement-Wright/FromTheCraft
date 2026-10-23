"""Visible slope hulls, derived from pinned Copycats+ 3.0.4 model transforms.

The mod renders a plane y = low + (high-low)*z, then flips/rotates about
the block center. Collision shapes are stepped and are not the visible hull.
"""

import numpy as np

from .copycats import SMOOTH


def smooth_geometry(state):
    if state.name not in SMOOTH:
        return None
    props = dict(state.properties)
    turns = {"south": 0, "west": 1, "north": 2, "east": 3}[props.get("facing", "north")]
    rotation = np.eye(3)
    if state.name == "copycats:copycat_vertical_slope":
        rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    elif props.get("half", "bottom") == "top":
        rotation[1, 1] = -1
    yaw = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]])
    for _ in range(turns):
        rotation = yaw @ rotation
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = 0.5 - rotation @ np.full(3, 0.5)
    layer = props.get("layers", "4") if state.name.endswith("slope_layer") else "4"
    return "copycat_slope_" + layer, transform
