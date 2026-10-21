from collections import Counter

import numpy as np

from .geometry import voxelize
from .ftd import read_blueprint, write_blueprint
from .minecraft import read_litematic, read_structure, write_litematic, write_structure
from .model import Result
from .palettes import mc_target


def convert(scene, output, scale=1, preference="balanced", progress=None, cancelled=None):
    if scale not in (1,2):
        raise ValueError("Scale must be 1 or 2")
    if preference not in {"balanced", "material", "color"}:
        raise ValueError("Unknown material preference")
    if output not in ({"nbt", "litematic"} if scene.format == "blueprint" else {"blueprint"}):
        raise ValueError("Choose a format in the other game")
    cells, offset = voxelize(scene, scale)
    if not cells:
        raise ValueError("No structural blocks remain after skipped blocks")
    notices = Counter(scene.notices)
    if output == "blueprint":
        content = write_blueprint(cells)
        notices["FtD output schema targets reference version 3.8.5.11; in-game acceptance is unverified"] += 1
        return Result(content, read_blueprint(content), output, offset, notices)
    states = {p: mc_target(part, preference) for p,part in cells.items()}
    size = tuple(np.max(list(cells), axis=0)+1)
    writer,reader = (write_structure,read_structure) if output == "nbt" else (write_litematic,read_litematic)
    content = writer(states, size)
    return Result(content, reader(content), output, offset, notices)


def read_file(content, suffix):
    readers = {"blueprint": read_blueprint, "nbt": read_structure, "litematic": read_litematic}
    reader = readers.get(suffix.lower().lstrip("."))
    if reader is None:
        raise ValueError("Open an FtD .blueprint, Minecraft .nbt, or .litematic file")
    return reader(content)
