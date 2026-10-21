from collections import Counter

import numpy as np

from .geometry import voxelize
from .minecraft import read_structure, write_structure
from .model import Result, State


def convert(scene, output, scale=1, preference="balanced", progress=None, cancelled=None):
    if scale not in (1,2):
        raise ValueError("Scale must be 1 or 2")
    if output != "nbt" or scene.format != "blueprint":
        raise ValueError("This conversion direction is not available")
    cells, offset = voxelize(scene, scale)
    if not cells:
        raise ValueError("No structural blocks remain after skipped blocks")
    palette = {"Wood": "minecraft:oak_planks", "Glass": "minecraft:glass", "Stone": "minecraft:stone"}
    states = {p: State(palette.get(part.material, "minecraft:iron_block")) for p,part in cells.items()}
    size = tuple(np.max(list(cells), axis=0)+1)
    content = write_structure(states, size)
    return Result(content, read_structure(content), output, offset, Counter(scene.notices))
