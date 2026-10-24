"""Operation-count regressions paired with exact reference output checks."""

from pathlib import Path
import json
import threading

import numpy as np

from fromthecraft.ftd import read_blueprint, write_blueprint
from fromthecraft.geometry import rotation
from fromthecraft.model import Part
from exact_reference import write_blueprint as reference_blueprint


def paint_cells(count=512):
    colors = [tuple(((i * a) % 31) / 31 + (i % 2) * 1e-8 for a in (3, 7, 13)) for i in range(35)]
    return {
        (i, 0, 0): Part("test", "box", (1, 1, 1), np.eye(4), "Metal", colors[i % len(colors)])
        for i in range(count)
    }


def test_blueprint_import_reuses_discrete_rotations_without_shared_mutation(monkeypatch):
    import fromthecraft.geometry as geometry

    content = reference_blueprint(paint_cells(80))
    calls = 0
    cross = np.cross

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return cross(*args, **kwargs)

    monkeypatch.setattr(geometry.np, "cross", counted)
    scene = read_blueprint(content)
    assert len(scene.parts) == 80
    assert calls <= 24, "Do not reconstruct a rotation for every footprint cell"
    for index in range(24):
        expected = np.column_stack(
            (cross(geometry.UP[index], geometry.FORWARD[index]), geometry.UP[index], geometry.FORWARD[index])
        ).astype(float)
        assert np.array_equal(rotation(index), expected)
        modified = rotation(index)
        modified[:] = 123
        assert np.array_equal(rotation(index), expected)


def test_reverse_paint_search_is_cached_by_raw_color_and_palette_version(monkeypatch):
    cells = paint_cells()
    expected = reference_blueprint(cells)
    original = np.linalg.norm
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(np.linalg, "norm", counted)
    assert write_blueprint(cells) == expected
    assert calls < 2200, "Repeated colors must not repeat every nearest-paint calculation"


def test_definition_reads_overlap_but_duplicate_guid_precedence_stays_sorted(tmp_path, monkeypatch):
    from fromthecraft.ftd_meshes import _definitions

    directory = tmp_path / "Mods/Core_Test/Items"
    directory.mkdir(parents=True)
    for i in range(16):
        (directory / f"{i:02}.item").write_text(json.dumps({"ComponentId": {"Guid": "same", "Name": str(i)}}))
    reader = Path.read_bytes
    lock, overlap = threading.Lock(), threading.Event()
    active = peak = 0

    def tracked(path):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active > 1:
                overlap.set()
        overlap.wait(0.02)
        try:
            return reader(path)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(Path, "read_bytes", tracked)
    _definitions.cache_clear()
    try:
        result = _definitions(str(tmp_path))
        assert result["same"][0]["ComponentId"]["Name"] == "15"
        assert peak > 1, "Independent definition reads should overlap"
    finally:
        _definitions.cache_clear()


def test_voxel_masks_are_packed_by_batch_with_exact_placement_order(monkeypatch):
    from fromthecraft.geometry import voxelize
    from fromthecraft.model import Scene
    from voxel_reference import reference_voxelize

    transform = np.eye(4)
    transform[0, 3] = 0.25
    source = Scene([Part("wall", "box", (32, 1, 1), transform, "Metal", (0.2, 0.3, 0.4))], "blueprint")
    expected, offset = reference_voxelize(source, detailed=True)
    calls, original = 0, np.packbits

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(np, "packbits", counted)
    actual, actual_offset = voxelize(source, detailed=True)
    assert actual_offset == offset
    assert [(key, value.shape, value.state) for key, value in actual.items()] == [
        (key, value.shape, value.state) for key, value in expected.items()
    ]
    assert calls <= 2, "Pack all rows of a sampling batch together"


def test_numeric_candidate_generation_matches_product_including_empty_ranges():
    from itertools import product
    import fromthecraft.geometry as geometry

    assert hasattr(geometry, "cell_candidates")
    for low, high in [((-2, 0, 3), (2, 3, 5)), ((0, -1, 0), (1, 0, 4)), ((0, 0, 0), (0, 2, 1))]:
        expected = np.array(list(product(*(range(a, b) for a, b in zip(low, high)))), dtype=int).reshape(
            -1, 3
        )
        assert np.array_equal(geometry.cell_candidates(np.array(low), np.array(high)), expected)


def test_acceleration_cache_reuses_only_exact_geometry_with_independent_state():
    import fromthecraft.mesh_geometry as mesh
    from fromthecraft.model import Cancelled
    import pytest

    assert hasattr(mesh, "MeshSamplerCache")
    cache = mesh.MeshSamplerCache()
    vertices, indices = np.eye(3), np.array([[0, 1, 2]])
    first = cache.get(vertices, indices, 0.125, None, False)
    expected = first.contains([[1 / 3, 1 / 3, 1 / 3]])
    second = cache.get(vertices.copy(), indices.copy(), 0.125, None, False)
    assert second is not first and second.tree is first.tree
    assert second.work == 0 and first.work > 0
    assert second.contains([[1 / 3, 1 / 3, 1 / 3]]).tolist() == expected.tolist()
    assert second.work == first.work
    cancelled = cache.get(vertices, indices, 0.125, lambda: True, False)
    with pytest.raises(Cancelled):
        cancelled.contains([[0.0, 0.0, 0.0]])
    vertices[0, 0] += 0.01
    assert cache.get(vertices, indices, 0.125, None, False).tree is not first.tree
    assert cache.get(vertices, indices, 0.25, None, False).radius == 0.125
    tiny = mesh.MeshSamplerCache(max_bytes=1)
    a = tiny.get(vertices, indices, 0.125, None, False)
    assert tiny.get(vertices, indices, 0.125, None, False).tree is not a.tree
