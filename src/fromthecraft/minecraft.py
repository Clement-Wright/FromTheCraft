import gzip
import io

import nbtlib as nbt

from .geometry import checked_size
from .model import DATA_VERSION, State


def write_structure(cells: dict, size) -> bytes:
    checked_size(size)
    palette, indices, blocks = [], {}, []
    for position, state in sorted(cells.items()):
        if state not in indices:
            indices[state] = len(palette)
            entry = nbt.Compound({"Name": nbt.String(state.name)})
            if state.properties:
                entry["Properties"] = nbt.Compound({k: nbt.String(v) for k,v in state.properties})
            palette.append(entry)
        blocks.append(nbt.Compound({"pos": nbt.List[nbt.Int](position), "state": nbt.Int(indices[state])}))
    root = nbt.File({"DataVersion": nbt.Int(DATA_VERSION), "size": nbt.List[nbt.Int](size),
                     "palette": nbt.List[nbt.Compound](palette), "blocks": nbt.List[nbt.Compound](blocks),
                     "entities": nbt.List[nbt.Compound]()})
    stream = io.BytesIO()
    root.write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)


def read_structure(content: bytes):
    import numpy as np
    from .model import Part, Scene

    root = nbt.File.parse(io.BytesIO(gzip.decompress(content)))
    if int(root["DataVersion"]) != DATA_VERSION:
        raise ValueError("Expected Minecraft Java 1.21.1 (data version 3955)")
    checked_size(root["size"])
    parts = []
    for block in root["blocks"]:
        state = root["palette"][int(block["state"])]
        name = str(state["Name"])
        if name in {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}:
            continue
        transform = np.eye(4)
        transform[:3,3] = list(block["pos"])
        parts.append(Part(name, "box", (1,1,1), transform, "Metal", (.5,.5,.5),
                          "glass" in name, State(name, tuple(sorted((str(k),str(v)) for k,v in state.get("Properties", {}).items())))))
    return Scene(parts, "nbt", version=str(DATA_VERSION))
