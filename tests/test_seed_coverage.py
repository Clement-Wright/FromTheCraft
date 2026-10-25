"""Skip redundant forward samples only when their entire destination is covered."""

import numpy as np
import pytest

from fromthecraft.geometry import voxelize
from fromthecraft.mesh_geometry import prepare_meshes
from fromthecraft.model import Part, Scene


def tiny_mesh(position=(0.15, 0.15, 0.15), size=0.7):
    transform = np.diag([size, size, size, 1.0])
    transform[:3, 3] = position
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    indices = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    return Part(
        "mesh",
        "mesh",
        (1, 1, 1),
        transform,
        "Stone",
        (0.1, 0.8, 0.2),
        mesh=(vertices, indices),
        decoration=True,
    )


@pytest.mark.parametrize("extreme", [False, True])
def test_covered_mesh_needs_no_forward_seeds(monkeypatch, extreme):
    import fromthecraft.mesh_geometry as mesh

    scene = prepare_meshes(Scene([tiny_mesh()], "blueprint"), "decorations", 0.125, 1)
    original, calls = mesh.surface_seed_batches, []

    def track(*args):
        calls.append(True)
        yield from original(*args)

    monkeypatch.setattr(mesh, "surface_seed_batches", track)
    cells, _ = voxelize(scene, detailed=True, extreme=extreme)
    assert list(cells) == [(0, 0, 0)]
    assert not calls, "All forward seeds would be ignored in the already sampled cell"


@pytest.mark.parametrize("scale", [0.25, 0.5, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("extreme", [False, True])
def test_seed_coverage_shortcut_matches_forced_original(monkeypatch, scale, extreme):
    import fromthecraft.geometry as geometry

    first = tiny_mesh(position=(-1.0 / scale + 2e-9, 0.15, -0.8))
    second = tiny_mesh(position=(-0.125, 0.15, -0.8), size=0.01)
    second.color = (1, 0, 0)
    scene = prepare_meshes(Scene([first, second], "blueprint"), "decorations", 0.125, scale)
    actual, actual_offset = voxelize(scene, scale, detailed=True, extreme=extreme)
    monkeypatch.setattr(geometry, "_mesh_seeds_covered", lambda *_args: False)
    expected, expected_offset = voxelize(scene, scale, detailed=True, extreme=extreme)
    assert actual_offset == expected_offset
    assert list(actual) == list(expected)
    for key, result in actual.items():
        reference = expected[key]
        assert (result.shape, result.state, result.detail_surface) == (
            reference.shape,
            reference.state,
            reference.detail_surface,
        )
        assert [(id(owner), mask) for owner, mask in result.detail_sources] == [
            (id(owner), mask) for owner, mask in reference.detail_sources
        ]


def test_coverage_includes_seed_rounding_and_both_sides_of_a_grid_boundary():
    from fromthecraft.geometry import _mesh_seeds_covered

    part = tiny_mesh(position=(0.99999995, 0.2, 0.2), size=0.00001)
    part.mesh = (*part.mesh, True, 0.125, np.ones(3))
    assert not _mesh_seeds_covered(part, 1, np.zeros(3, dtype=int), {(0, 0, 0)})
    assert _mesh_seeds_covered(part, 1, np.zeros(3, dtype=int), {(0, 0, 0), (1, 0, 0)})


def test_coverage_proof_is_bounded_so_cancellation_is_not_delayed():
    from fromthecraft.geometry import _mesh_seeds_covered

    class ManyCovered:
        def __len__(self):
            return 10_000_000

        def __contains__(self, _key):
            pytest.fail("Large proofs must keep the original cancellable seed batches")

    part = tiny_mesh()
    part.transform = np.diag([200.0, 200.0, 2.0, 1.0])
    assert not _mesh_seeds_covered(part, 1, np.zeros(3, dtype=int), ManyCovered())
