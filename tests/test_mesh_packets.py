"""Coherent packets prune only shared empty BVH branches, never sample points."""

import numpy as np
import pytest

native = pytest.importorskip("fromthecraft._mesh_native")


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("packet", [32, 128, 512])
def test_packet_queries_keep_scalar_bits_work_and_uncertainty(closed, packet):
    from fromthecraft.mesh_geometry import MeshSampler

    rng = np.random.default_rng(752)
    vertices = rng.uniform(-1, 2, (300, 3))
    sampler = MeshSampler(vertices, np.arange(300).reshape(-1, 3), closed=closed)
    points = rng.uniform(-2, 3, (32768, 3))
    arrays = sampler._native_arrays()
    expected = native.contains(points, *arrays, closed, sampler.radius)
    actual = native.contains(points, *arrays, closed, sampler.radius, packet)
    assert actual == expected


@pytest.mark.parametrize("closed", [False, True])
def test_coherent_empty_and_surface_packets_retain_original_leaf_order(closed):
    from fromthecraft.mesh_geometry import MeshSampler

    rng = np.random.default_rng(529)
    vertices = rng.random((180, 3))
    sampler = MeshSampler(vertices, np.arange(180).reshape(-1, 3), closed=closed)
    a = np.array(
        [
            (x, y, z)
            for x in np.linspace(-2, 3, 32)
            for y in np.linspace(-2, 3, 32)
            for z in np.linspace(-2, 3, 32)
        ]
    )
    expected = native.contains(a, *sampler._native_arrays(), closed, sampler.radius)
    assert native.contains(a, *sampler._native_arrays(), closed, sampler.radius, 128) == expected


def test_packet_boundary_ambiguity_still_requests_the_original_numpy_batch():
    from fromthecraft.mesh_geometry import MeshSampler

    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    vertices = np.concatenate((vertices, vertices + (0, 0, 1)))
    sampler = MeshSampler(vertices, np.array([[0, 1, 2], [3, 4, 5]]), closed=False)
    cutoff = np.sqrt(sampler.radius**2 + 1e-12)
    points = np.tile((0.25, 0.25, cutoff), (32768, 1))
    expected = native.contains(points, *sampler._native_arrays(), False, sampler.radius)
    assert expected[2]
    assert native.contains(points, *sampler._native_arrays(), False, sampler.radius, 128) == expected


@pytest.mark.parametrize("packet", [-1, 32769])
def test_invalid_packet_width_is_rejected(packet):
    from fromthecraft.mesh_geometry import MeshSampler

    sampler = MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False)
    with pytest.raises(ValueError):
        native.contains(np.ones((1, 3)), *sampler._native_arrays(), False, 0.0625, packet)
