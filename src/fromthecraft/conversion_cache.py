"""One bounded geometry stage per open source, keyed by its conversion edits."""

from sys import getsizeof
from threading import Lock


class GeometryCache:
    def __init__(self, max_bytes=256 * 1024**2, max_cells=150_000):
        self.max_bytes, self.max_cells = max_bytes, max_cells
        self._lock, self._key, self._value = Lock(), None, None

    def get(self, key):
        with self._lock:
            if key == self._key and self._value is not None:
                scene, cells, offset = self._value
                return scene, cells.copy(), offset
        return None

    def put(self, key, scene, cells, offset, cancelled=None):
        if len(cells) > self.max_cells:
            return
        weight = getsizeof(cells)
        for index, (position, part) in enumerate(cells.items()):
            if index % 256 == 0 and cancelled and cancelled():
                return
            weight += (
                getsizeof(position)
                + getsizeof(part)
                + getsizeof(part.__dict__)
                + part.transform.nbytes
                + getsizeof(part.detail_sources)
            )
            weight += sum(
                getsizeof(mask) + getsizeof(pair) for pair in part.detail_sources for mask in [pair[1]]
            )
            if weight > self.max_bytes:
                return
        # Prepared decorative arrays can outlive the source's original local
        # meshes. Count each retained mesh once, independently of its placements.
        seen = set()
        for part in scene.parts:
            weight += getsizeof(part) + getsizeof(part.__dict__)
            if part.mesh:
                for array in part.mesh:
                    if hasattr(array, "nbytes") and id(array) not in seen:
                        seen.add(id(array))
                        weight += array.nbytes
        if weight > self.max_bytes or cancelled and cancelled():
            return
        with self._lock:
            self._key, self._value = key, (scene, cells.copy(), offset)
