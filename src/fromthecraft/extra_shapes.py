"""Additional static boxes derived from Copycats+ 3.0.4 CCShapes dimensions.

Source: https://github.com/copycats-plus/copycats/blob/9f808ac0b437817696c50f2e8b57f590b1196094/common/src/main/java/com/copycatsplus/copycats/CCShapes.java
No mod models, textures or source assets are bundled here.
"""

from itertools import product
import numpy as np


def turn(box, facing="south", top=False):
    points = np.array(list(product(*zip(box[:3], box[3:]))))
    if top:
        points[:, 1] = 1 - points[:, 1]
    for _ in range({"south": 0, "west": 1, "north": 2, "east": 3}[facing]):
        points[:, 0], points[:, 2] = 1 - points[:, 2].copy(), points[:, 0].copy()
    return tuple(np.r_[points.min(0), points.max(0)])


def boxes(state):
    p = dict(state.properties)
    family = state.name.removeprefix("copycats:copycat_")
    facing, top = p.get("facing", "north"), p.get("half", "bottom") == "top"
    if family == "beam":
        axis = "xyz".index(p.get("axis", "y"))
        low, high = [0.25] * 3, [0.75] * 3
        low[axis], high[axis] = 0, 1
        return ((None, tuple(low + high)),)
    if family == "board":
        result = []
        for side in ("up", "down", "north", "south", "east", "west"):
            if p.get(side, "false") != "true":
                continue
            axis = {"east": 0, "west": 0, "up": 1, "down": 1, "south": 2, "north": 2}[side]
            box = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
            box[axis], box[axis + 3] = (15 / 16, 1) if side in ("east", "up", "south") else (0, 1 / 16)
            result.append((side, tuple(box)))
        return tuple(result)
    if family == "vertical_step":
        return ((None, turn((0.5, 0, 0.5, 1, 1, 1), facing)),)
    if family in ("slice", "vertical_slice", "corner_slice"):
        n = int(p.get("layers", "1")) / 8
        box = {
            "slice": (0, 0, 1 - n, 1, n, 1),
            "vertical_slice": (1 - n, 0, 1 - n, 1, 1, 1),
            "corner_slice": (1 - n, 0, 1 - n, 1, n, 1),
        }[family]
        return ((None, turn(box, p.get("facing", "south"), top)),)
    result = []
    for slot in ("negative_layers", "positive_layers"):
        n = int(p.get(slot, "0")) / 8
        if not n:
            continue
        positive = slot == "positive_layers"
        if family == "half_layer":
            box = (0, 0, 0.5 if positive else 0, 1, n, 1 if positive else 0.5)
            result.append((slot, turn(box, "east" if p.get("axis", "x") == "x" else "south", top)))
        elif family == "vertical_half_layer":
            box = (0.5 if positive else 0, 0, 1 - n, 1 if positive else 0.5, 1, 1)
            result.append((slot, turn(box, facing)))
        elif family == "stacked_half_layer":
            box = (0, 0.5 if positive else 0, 1 - n, 1, 1 if positive else 0.5, 1)
            result.append((slot, turn(box, facing)))
    return tuple(result)
