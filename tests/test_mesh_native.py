"""The accelerated kernel must agree with the original, including its tolerances."""

import numpy as np
import pytest

_mesh_native = pytest.importorskip("fromthecraft._mesh_native")


def test_native_attempt_stops_when_full_numpy_fallback_is_inevitable():
    from fromthecraft.mesh_geometry import MeshSampler

    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    sampler = MeshSampler(vertices, np.array([[0, 1, 2]]), closed=False)
    points = np.zeros((5000, 3))
    result, work, uncertain = _mesh_native.contains(points, *sampler._native_arrays(), False, 0.0625)
    assert uncertain
    assert len(result) == len(points)
    assert work <= 1, "Discard the native attempt as soon as original NumPy fallback is required"


def test_voxelize_cancellation_does_not_wait_for_running_native_chunks(monkeypatch):
    import threading

    from fromthecraft.geometry import voxelize
    from fromthecraft.model import Cancelled, Part, Scene

    started, release, returned = (threading.Event() for _ in range(3))
    errors = []

    def blocked(points, *args):
        started.set()
        release.wait(5)
        return bytes(len(points)), 0, False

    monkeypatch.setattr(_mesh_native, "contains", blocked)
    vertices = np.random.default_rng(92).random((180, 3))
    part = Part(
        "mesh",
        "mesh",
        (1, 1, 1),
        np.diag([4.0, 4.0, 4.0, 1.0]),
        "Metal",
        (1, 1, 1),
        mesh=(vertices, np.arange(180).reshape(-1, 3), True, 0.125, np.ones(3)),
    )

    def convert():
        try:
            voxelize(Scene([part], "ftd"), detailed=True, cancelled=started.is_set)
        except Exception as error:
            errors.append(error)
        finally:
            returned.set()

    conversion = threading.Thread(target=convert)
    conversion.start()
    try:
        assert started.wait(5), "Exercise cancellation while native chunks are running"
        prompt = returned.wait(0.5)
    finally:
        release.set()
        conversion.join(5)
    assert prompt, "Cancel must return before blocked native workers finish"
    assert len(errors) == 1 and isinstance(errors[0], Cancelled)


@pytest.mark.parametrize("closed", [True, False])
def test_parallel_native_queries_keep_original_bits_and_budget(monkeypatch, closed):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from fromthecraft.mesh_geometry import MeshSampler

    rng = np.random.default_rng(602)
    vertices = rng.random((180, 3))
    indices = np.arange(180).reshape(-1, 3)
    points = rng.uniform(-0.1, 1.1, (40000, 3))
    serial = MeshSampler(vertices, indices, closed=closed)
    expected = serial.contains(points)
    thread_ids = set()
    real = _mesh_native.contains

    def track(*args):
        thread_ids.add(threading.get_ident())
        return real(*args)

    monkeypatch.setattr(_mesh_native, "contains", track)
    parallel = MeshSampler(vertices, indices, closed=closed)
    with ThreadPoolExecutor(max_workers=4) as workers:
        parallel.executor = workers
        actual = parallel.contains(points)
    np.testing.assert_array_equal(actual, expected)
    assert parallel.work == serial.work
    assert len(thread_ids) > 1, "Use multiple native workers for a dense mesh query"


def test_native_kernel_rejects_invalid_buffers_instead_of_reading_past_them():
    with pytest.raises((ValueError, BufferError)):
        _mesh_native.contains(
            np.zeros((2, 3)),
            np.zeros((1, 10)),
            np.zeros((1, 6)),
            np.zeros((1, 4), dtype=np.intp),
            np.zeros(1, dtype=np.intp),
            True,
        )


@pytest.mark.parametrize("closed", [False, True])
def test_native_and_numpy_paths_give_identical_results_without_boundary_fallback(monkeypatch, closed):
    from fromthecraft.mesh_geometry import MeshSampler
    from mesh_reference import ReferenceMeshSampler

    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
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

    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    # The second triangle keeps this point inside the original leaf bounds.
    # A single zero-height triangle would reject it at the BVH's radius test.
    vertices = np.concatenate((vertices, vertices + (0, 0, 1)))
    indices = np.array([[0, 1, 2], [3, 4, 5]])
    cutoff = np.sqrt(0.0625**2 + 1e-12)
    points = np.array([[0.25, 0.25, z] for z in (cutoff, np.nextafter(cutoff, 0), np.nextafter(cutoff, 1))])
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
    args = (
        np.zeros((1, 10)),
        np.zeros((1, 6)),
        np.array([[-1, -1, 0, 1]], dtype=np.intp),
        np.array([0], dtype=np.intp),
        True,
    )
    with pytest.raises((ValueError, BufferError)):
        _mesh_native.contains(np.zeros((2, 6))[:, ::2], *args)
    with pytest.raises((ValueError, BufferError)):
        _mesh_native.contains(np.zeros((2, 3), dtype=">f8"), *args)


def test_triangle_footprint_boundary_is_checked_with_original_vector_arithmetic():
    from fromthecraft.mesh_geometry import MeshSampler

    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    sampler = MeshSampler(vertices, np.array([[0, 1, 2]]), closed=False)
    points = np.array([[0.0, 0.25, 0.01], [0.5, 0.5, 0.01]])
    _, _, uncertain = _mesh_native.contains(points, *sampler._native_arrays(), False, 0.0625)
    assert uncertain


def test_proven_open_surface_hit_can_skip_irrelevant_ill_conditioned_triangles():
    from fromthecraft.mesh_geometry import MeshSampler
    from mesh_reference import ReferenceMeshSampler

    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 1e-7, 0.0],
        ]
    )
    indices = np.array([[0, 1, 2], [3, 4, 5]])
    points = np.array([[0.25, 0.25, 0.01], [0.3, 0.2, 0.01]])
    sampler = MeshSampler(vertices, indices, closed=False)
    expected = ReferenceMeshSampler(vertices, indices, closed=False).contains(points)
    actual, work, uncertain = _mesh_native.contains(points, *sampler._native_arrays(), False, 0.0625)
    np.testing.assert_array_equal(np.frombuffer(actual, dtype=np.uint8).astype(bool), expected)
    assert work == len(points) * 2, "Keep the same work-budget accounting"
    assert not uncertain, "An already proven hit needs no fallback for a later triangle"


def test_points_far_from_triangle_planes_need_no_barycentric_boundary_fallback():
    from fromthecraft.mesh_geometry import MeshSampler
    from mesh_reference import ReferenceMeshSampler

    vertices = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0]]
    )
    indices = np.array([[0, 1, 2], [3, 4, 5]])
    points = np.array([[0.0, 0.25, 0.5], [0.5, 0.5, 0.5]])
    sampler = MeshSampler(vertices, indices, closed=False)
    expected = ReferenceMeshSampler(vertices, indices, closed=False).contains(points)
    actual, _, uncertain = _mesh_native.contains(points, *sampler._native_arrays(), False, 0.0625)
    np.testing.assert_array_equal(np.frombuffer(actual, dtype=np.uint8).astype(bool), expected)
    assert not uncertain


@pytest.mark.parametrize("indices", [[-1], [1]])
def test_out_of_range_triangle_indices_are_rejected(indices):
    with pytest.raises(ValueError):
        _mesh_native.contains(
            np.zeros((1, 3)),
            np.zeros((1, 10)),
            np.zeros((1, 6)),
            np.array([[-1, -1, 0, 1]], dtype=np.intp),
            np.array(indices, dtype=np.intp),
            True,
        )
