import numpy as np

from .geometry import bounds
from .ftd_shapes import vertices


def preview(scene, offset=(0, 0, 0)):
    groups, blocks, block_ids, inventory = {}, [], {}, {}
    for part in scene.parts:
        properties = tuple(sorted(part.state.properties)) if part.state else ()
        identity = (part.identity, part.material, properties)
        if identity not in block_ids:
            block_ids[identity] = len(blocks)
            blocks.append({"name": part.identity, "material": part.material, "properties": dict(properties)})
        material_key = (part.identity, part.material)
        inventory[material_key] = inventory.get(material_key, 0) + 1
        key = (part.shape, part.transparent)
        group = groups.setdefault(
            key,
            {
                "shape": part.shape,
                "transparent": part.transparent,
                "matrices": [],
                "colors": [],
                "block_indices": [],
            },
        )
        group["block_indices"].append(block_ids[identity])
        hull_vertices = vertices(part.shape)
        if hull_vertices and "vertices" not in group:
            group["vertices"] = list(hull_vertices)
        matrix = part.transform.copy()
        matrix[:3, :3] = matrix[:3, :3] @ np.diag(part.size)
        matrix[:3, 3] += offset
        group["matrices"].extend(np.round(matrix.T.reshape(-1), 6).tolist())
        group["colors"].extend([round(float(c), 6) for c in part.color])
    low, high = bounds(scene)
    return {
        "groups": list(groups.values()),
        "blocks": blocks,
        "materials": [
            {"name": name, "material": material, "properties": {}, "count": count}
            for (name, material), count in sorted(inventory.items(), key=lambda item: (-item[1], item[0]))
        ],
        "count": len(scene.parts),
        "bounds": [(low + offset).tolist(), (high + offset).tolist()],
        "dimensions": np.round(high - low, 3).tolist(),
        "format": scene.format,
        "version": scene.version,
    }
