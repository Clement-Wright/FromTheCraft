"""Repeated transforms must reuse checks without merging source identities."""

import numpy as np
import pytest

from fromthecraft.geometry import rotation, voxelize
from fromthecraft.model import Part, Scene
from voxel_reference import reference_voxelize


def repeated_parts(shape="box", dtype=np.float64):
    parts = []
    for index in range(48):
        transform = np.eye(4, dtype=dtype)
        transform[:3, :3] = rotation(index % 24)
        transform[:3, 3] = (index * 3, 0, 0)
        parts.append(Part(str(index), shape, (1, 1, 1), transform, "Metal", (0.3, 0.4, 0.5)))
    return Scene(parts, "blueprint")


def signature(result):
    cells, origin = result
    return origin, [(position, part.identity, part.shape, part.state) for position, part in cells.items()]


def test_repeated_transform_alignment_checks_are_reused(monkeypatch):
    scene = repeated_parts()
    expected = signature(reference_voxelize(scene))
    original = np.allclose
    checks = 0

    def counted(left, right, *args, **kwargs):
        nonlocal checks
        if np.size(left) == 9:
            checks += 1
        return original(left, right, *args, **kwargs)

    monkeypatch.setattr(np, "allclose", counted)
    assert signature(voxelize(scene)) == expected
    assert checks == 24, "Check each repeated rotation once per conversion"
    assert signature(voxelize(scene)) == expected
    assert checks == 48, "Do not retain source transforms after a conversion finishes"


def test_non_boxes_skip_unused_grid_boundary_check(monkeypatch):
    scene = repeated_parts("wedge")
    expected = signature(reference_voxelize(scene))
    original = np.allclose
    grid_checks = 0

    def counted(left, right, *args, **kwargs):
        nonlocal grid_checks
        if np.shape(left) == (8, 3):
            grid_checks += 1
        return original(left, right, *args, **kwargs)

    monkeypatch.setattr(np, "allclose", counted)
    assert signature(voxelize(scene)) == expected
    assert grid_checks == 0, "Only boxes use the grid-boundary sampling bypass"


@pytest.mark.parametrize("scale", [0.25, 0.5, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("dtype", [np.float64, np.float32])
def test_reused_alignment_keeps_all_orientations_and_scale_results(scale, dtype):
    scene = repeated_parts(dtype=dtype)
    assert signature(voxelize(scene, scale)) == signature(reference_voxelize(scene, scale))


def test_alignment_cache_reads_current_transform_values():
    scene = repeated_parts()
    voxelize(scene)
    scene.parts[24].transform[0, 0] += 0.03
    scene.parts[25].transform[1, 3] += 0.125
    assert signature(voxelize(scene)) == signature(reference_voxelize(scene))
