"""The accelerated kernel must agree with the original, including its tolerances."""

import numpy as np
import pytest

_mesh_native = pytest.importorskip("fromthecraft._mesh_native")


def test_native_kernel_rejects_invalid_buffers_instead_of_reading_past_them():
    with pytest.raises((ValueError, BufferError)):
        _mesh_native.contains(np.zeros((2, 3)), np.zeros((1, 10)), np.zeros((1, 6)),
                              np.zeros((1, 4), dtype=np.intp), np.zeros(1, dtype=np.intp), True)


@pytest.mark.parametrize("closed", [False, True])
def test_native_and_numpy_paths_give_identical_results_without_boundary_fallback(monkeypatch, closed):
    from fromthecraft.mesh_geometry import MeshSampler
    from mesh_reference import ReferenceMeshSampler

    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    indices = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    points = np.random.default_rng(18).uniform(-0.2, 1.2, (40000, 3))
    native_calls, fallbacks = 0, 0
    real = _mesh_native.contains

    def counted(*args):
        nonlocal native_calls, fallbacks
        answer = real(*args)
        native_calls += 1
        fallbacks += bool(answer[2])
        return answer

    monkeypatch.setattr(_mesh_native, "contains", counted)
    actual = MeshSampler(vertices, indices, closed=closed).contains(points)
    expected = ReferenceMeshSampler(vertices, indices, closed=closed).contains(points)
    np.testing.assert_array_equal(actual, expected)
    assert native_calls > 0
    assert fallbacks == 0


def test_open_surface_boundary_uses_original_rounding_for_the_complete_leaf_batch(monkeypatch):
    from fromthecraft.mesh_geometry import MeshSampler
    from mesh_reference import ReferenceMeshSampler

    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
    # The second triangle keeps this point inside the original leaf bounds.
    # A single zero-height triangle would reject it at the BVH's radius test.
    vertices = np.concatenate((vertices, vertices + (0, 0, 1)))
    indices = np.array([[0, 1, 2], [3, 4, 5]])
    cutoff = np.sqrt(0.0625**2 + 1e-12)
    points = np.array([[0.25, 0.25, z] for z in (cutoff, np.nextafter(cutoff, 0),
                                                np.nextafter(cutoff, 1))])
    real = _mesh_native.contains
    fallbacks = 0

    def counted(*args):
        nonlocal fallbacks
        answer = real(*args)
        fallbacks += bool(answer[2])
        return answer

    monkeypatch.setattr(_mesh_native, "contains", counted)
    actual = MeshSampler(vertices, indices).contains(points)
    expected = ReferenceMeshSampler(vertices, indices).contains(points)
    np.testing.assert_array_equal(actual, expected)
    assert fallbacks == 1


def test_non_contiguous_and_wrong_endian_arrays_are_rejected():
    args = (np.zeros((1, 10)), np.zeros((1, 6)), np.array([[-1, -1, 0, 1]], dtype=np.intp),
            np.array([0], dtype=np.intp), True)
    with pytest.raises((ValueError, BufferError)):
        _mesh_native.contains(np.zeros((2, 6))[:, ::2], *args)
    with pytest.raises((ValueError, BufferError)):
        _mesh_native.contains(np.zeros((2, 3), dtype=">f8"), *args)


def test_triangle_footprint_boundary_is_checked_with_original_vector_arithmetic():
    from fromthecraft.mesh_geometry import MeshSampler

    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
    sampler = MeshSampler(vertices, np.array([[0, 1, 2]]), closed=False)
    points = np.array([[0., 0.25, 0.01], [0.5, 0.5, 0.01]])
    _, _, uncertain = _mesh_native.contains(points, *sampler._native_arrays(), False, 0.0625)
    assert uncertain


@pytest.mark.parametrize("indices", [[-1], [1]])
def test_out_of_range_triangle_indices_are_rejected(indices):
    with pytest.raises(ValueError):
        _mesh_native.contains(np.zeros((1, 3)), np.zeros((1, 10)), np.zeros((1, 6)),
                              np.array([[-1, -1, 0, 1]], dtype=np.intp), np.array(indices, dtype=np.intp), True)
