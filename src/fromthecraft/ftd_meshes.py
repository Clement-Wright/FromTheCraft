"""Bounded local static mesh resolution through installed FtD definitions."""

import json
from functools import lru_cache
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .catalog import game_assets

MAX_VERTICES = 30_000
MAX_TRIANGLES = 10_000


def decode_obj(data):
    if len(data) > 8 * 1024**2:
        raise ValueError("Static OBJ exceeds 8 MiB")
    vertices, triangles, groups = [], [], 0
    for line in data.decode("utf-8-sig").splitlines():
        values = line.split("#", 1)[0].split()
        if not values:
            continue
        if values[0] in ("o", "g"):
            groups += 1
            if groups > 1 and triangles:
                raise ValueError("Multiple OBJ objects require a verified mesh cache")
        if values[0] == "v":
            if len(values) != 4 or len(vertices) >= MAX_VERTICES:
                raise ValueError("Unsupported or oversized OBJ vertices")
            x, y, z = map(float, values[1:])
            vertices.append((-x, y, z))  # verified Unity importer handedness
        elif values[0] == "f":
            if len(values) not in (4, 5):
                raise ValueError("Only triangular or quad OBJ faces are supported")
            face = [int(value.split("/")[0]) for value in values[1:]]
            face = [n - 1 if n > 0 else len(vertices) + n for n in face]
            triangles.append((face[0], face[2], face[1]))
            if len(face) == 4:
                triangles.append((face[0], face[3], face[2]))
            if len(triangles) > MAX_TRIANGLES:
                raise ValueError("Static OBJ exceeds triangle budget")
    vertices, triangles = np.asarray(vertices, dtype=float), np.asarray(triangles, dtype=np.int64)
    if (
        not len(vertices)
        or not len(triangles)
        or triangles.min() < 0
        or triangles.max() >= len(vertices)
        or not np.isfinite(vertices).all()
    ):
        raise ValueError("Invalid static OBJ geometry")
    areas = np.linalg.norm(
        np.cross(
            vertices[triangles[:, 1]] - vertices[triangles[:, 0]],
            vertices[triangles[:, 2]] - vertices[triangles[:, 0]],
        ),
        axis=1,
    )
    triangles = triangles[areas > 1e-12]
    if not len(triangles):
        raise ValueError("Referenced mesh is intentionally empty")
    return vertices, triangles


def decode_mesh_cache(data):
    if len(data) > 8 * 1024**2:
        raise ValueError("Static mesh cache exceeds 8 MiB")
    cursor, vertices, triangles = 0, None, []
    widths = {0: 12, 1: 12, 2: 13, 3: 8, 4: 20, 5: 64, 7: 4, 8: 24}
    while cursor < len(data):
        if cursor + 4 > len(data):
            raise ValueError("Truncated static mesh header")
        kind, count = data[cursor], int.from_bytes(data[cursor + 1 : cursor + 4], "little")
        cursor += 4
        width = 3 if kind >= 10 else widths.get(kind)
        if width is None or count > 100_000 or cursor + count * width > len(data):
            raise ValueError("Unsupported or oversized static mesh section")
        section = data[cursor : cursor + count * width]
        cursor += count * width
        if kind == 0:
            if vertices is not None or count > MAX_VERTICES:
                raise ValueError("Static mesh exceeds vertex budget")
            vertices = np.frombuffer(section, dtype="<f4").reshape(-1, 3).astype(float)
        elif kind >= 10:
            if count % 3 or len(triangles) + count // 3 > MAX_TRIANGLES:
                raise ValueError("Static mesh exceeds triangle budget")
            indices = np.frombuffer(section, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
            triangles.extend((indices @ np.array([1, 256, 65536])).reshape(-1, 3).tolist())
        elif kind in (4, 5):
            raise ValueError("Skinned static mesh is unsupported")
    triangles = np.asarray(triangles, dtype=np.int64)
    if (
        vertices is None
        or not len(vertices)
        or not len(triangles)
        or not np.isfinite(vertices).all()
        or np.max(np.abs(vertices)) > 2048
    ):
        raise ValueError("Invalid static mesh vertices")
    if triangles.min() < 0 or triangles.max() >= len(vertices):
        raise ValueError("Static mesh index outside vertex array")
    return vertices, triangles


@lru_cache(maxsize=2)
def _definitions(root):
    definitions = {}

    def read(file):
        try:
            if file.stat().st_size <= 1024**2:
                item = json.loads(file.read_bytes())
                return item["ComponentId"]["Guid"], (item, file.parent.parent / "Assets")
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="ftd-definitions") as workers:
        for pattern in (
            "Core_*/Items/*.item",
            "Core_*/ItemDup/*.itemduplicateandmodify",
            "Core_*/Objects/*.object",
            "Core_*/Meshes/*.mesh",
        ):
            files = sorted((Path(root) / "Mods").glob(pattern))[:20_000]
            for start in range(0, len(files), 256):
                # map yields in input order, including duplicate GUID overrides.
                for result in workers.map(read, files[start : start + 256]):
                    if result is not None:
                        definitions[result[0]] = result[1]
    return definitions


@lru_cache(maxsize=128)
def resolve_static_mesh(reference, root=None):
    """Return (vertices, indices, name) or (None, None, explicit reason)."""
    definitions = _definitions(str(root or game_assets()))

    def resolve(guid, seen=()):
        if guid in seen or len(seen) >= 16:
            raise ValueError("Cyclic mesh reference")
        if guid not in definitions:
            raise ValueError("Mesh reference is unavailable in the installed core definitions")
        entry, assets = definitions[guid]
        if "FilenameOrUrl" in entry:
            return entry, assets
        reference = entry.get("MeshReference", {})
        if reference.get("IsValidReference"):
            return resolve(reference["Reference"]["Guid"], seen + (guid,))
        parent = entry.get("IdToDuplicate", {}).get("Reference", {}).get("Guid")
        if parent:
            return resolve(parent, seen + (guid,))
        raise ValueError("Referenced renderer has no verified static mesh")

    try:
        entry, assets = resolve(reference)
        if entry.get("Source", 0) != 0:
            raise ValueError("Remote or procedural mesh sources are unsupported")
        filename = entry["FilenameOrUrl"]
        if not isinstance(filename, str) or not filename.endswith(".obj"):
            raise ValueError("Only verified local OBJ caches are supported")
        file = (assets / filename).with_suffix(".objbytes").resolve()
        if not file.is_relative_to(assets.resolve()):
            raise ValueError("Mesh path leaves its local assets folder")
        if not file.exists():
            file = file.with_suffix(".obj")
        if file.stat().st_size > 8 * 1024**2:
            raise ValueError("Static mesh cache exceeds 8 MiB")
        vertices, triangles = (decode_obj if file.suffix == ".obj" else decode_mesh_cache)(file.read_bytes())
        scaling = np.array([entry.get(a + "ImportScaleFactor", 1) for a in "XYZ"], dtype=float)
        offset = np.array([entry.get(a + "Offset", 0) for a in "XYZ"], dtype=float)
        vertices = vertices * scaling + offset
        if not np.isfinite(vertices).all() or np.max(np.abs(vertices)) > 2048:
            raise ValueError("Invalid imported mesh transform")
        return vertices, triangles, entry["ComponentId"]["Name"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, None, str(exc)
