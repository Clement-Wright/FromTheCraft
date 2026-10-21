import numpy as np

from .geometry import bounds


def preview(scene, offset=(0, 0, 0)):
    groups = {}
    for part in scene.parts:
        key = (part.shape, part.transparent)
        group = groups.setdefault(
            key, {"shape": part.shape, "transparent": part.transparent, "matrices": [], "colors": []}
        )
        matrix = part.transform.copy()
        matrix[:3, :3] = matrix[:3, :3] @ np.diag(part.size)
        matrix[:3, 3] += offset
        group["matrices"].extend(np.round(matrix.T.reshape(-1), 6).tolist())
        group["colors"].extend([round(float(c), 6) for c in part.color])
    low, high = bounds(scene)
    return {
        "groups": list(groups.values()),
        "count": len(scene.parts),
        "bounds": [(low + offset).tolist(), (high + offset).tolist()],
        "dimensions": np.round(high - low, 3).tolist(),
        "format": scene.format,
        "version": scene.version,
    }
