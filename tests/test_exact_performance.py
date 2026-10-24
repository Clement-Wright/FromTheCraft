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
