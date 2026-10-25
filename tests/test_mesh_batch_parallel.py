"""Parallel jobs retain complete original fallback batches and bounded storage."""

import threading
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np
import pytest

from fromthecraft import mesh_geometry as mesh
from fromthecraft.model import Cancelled

native = pytest.importorskip("fromthecraft._mesh_native")


@pytest.mark.parametrize("closed", [False, True])
def test_large_optimized_queries_schedule_whole_fallback_batches(monkeypatch, closed):
    rng = np.random.default_rng(1093)
    vertices = rng.random((180, 3))
    faces = np.arange(180).reshape(-1, 3)
    points = rng.uniform(-0.1, 1.1, (8 * 32768 + 517, 3))
    points.flags.writeable = False
    original = points.copy()
    serial = mesh.MeshSampler(vertices, faces, closed=closed)
    serial.packet_size = 128
    expected = serial.contains(points)
    query_sizes, thread_ids = [], set()
    query = native.contains

    def record(batch, *args):
        query_sizes.append(len(batch))
        thread_ids.add(threading.get_ident())
        return query(batch, *args)

    monkeypatch.setattr(native, "contains", record)
    parallel = mesh.MeshSampler(vertices, faces, closed=closed)
    parallel.packet_size, parallel.native_threads = 128, 4
    with ThreadPoolExecutor(max_workers=4) as workers:
        parallel.executor = workers
        actual = parallel.contains(points)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(points, original)
    assert parallel.work == serial.work
    assert sorted(query_sizes) == [517] + [32768] * 8
    assert len(thread_ids) > 1


def test_coarse_jobs_preserve_original_numpy_boundary_batches(monkeypatch):
    from mesh_reference import ReferenceMeshSampler

    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    vertices = np.concatenate((vertices, vertices + (0, 0, 1)))
    faces = np.array([[0, 1, 2], [3, 4, 5]])
    cutoff = np.sqrt(0.0625**2 + 1e-12)
    points = np.tile((0.25, 0.25, cutoff), (4 * 32768 + 7, 1))
    reference = ReferenceMeshSampler(vertices, faces, closed=False)
    expected = reference.contains(points)
    sizes, uncertain = [], []
    query = native.contains

    def record(batch, *args):
        sizes.append(len(batch))
        answer = query(batch, *args)
        uncertain.append(answer[2])
        return answer

    monkeypatch.setattr(native, "contains", record)
    sampler = mesh.MeshSampler(vertices, faces, closed=False)
    sampler.packet_size, sampler.native_threads = 128, 4
    with ThreadPoolExecutor(max_workers=4) as workers:
        sampler.executor = workers
        actual = sampler.contains(points)
    np.testing.assert_array_equal(actual, expected)
    assert sampler.work == reference.work
    assert all(uncertain)
    assert sorted(sizes) == [7] + [32768] * 4


def test_pending_coarse_jobs_are_bounded_and_cancel_returns_promptly(monkeypatch):
    started, cancelled, release, returned = (threading.Event() for _ in range(4))
    query_sizes, errors = [], []
    submissions = []

    class RecordingPool(ThreadPoolExecutor):
        def submit(self, fn, *args, **kwargs):
            submissions.append(len(args[0]) if len(args) else None)
            return super().submit(fn, *args, **kwargs)

    def blocked(points, *args):
        query_sizes.append(len(points))
        started.set()
        release.wait(5)
        return bytes(len(points)), 0, False

    monkeypatch.setattr(native, "contains", blocked)
    points = np.tile((4.0, 4.0, 4.0), (32 * 32768, 1))
    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False, cancelled=cancelled.is_set)
    sampler.packet_size, sampler.native_threads = 128, 4
    pool = RecordingPool(max_workers=4)
    sampler.executor = pool

    def run():
        try:
            sampler.contains(points)
        except Exception as error:
            errors.append(error)
        finally:
            returned.set()

    conversion = threading.Thread(target=run)
    conversion.start()
    try:
        assert started.wait(5)
        cancelled.set()
        prompt = returned.wait(0.5)
    finally:
        release.set()
        conversion.join(5)
        pool.shutdown(wait=True, cancel_futures=True)
    assert prompt, "Cancellation cannot wait for running sample batches"
    assert len(errors) == 1 and isinstance(errors[0], Cancelled)
    assert len(submissions) <= sampler.native_threads, "Keep only one job per worker in flight"
    assert query_sizes and all(size == 32768 for size in query_sizes)


def test_coarse_work_still_enforces_the_cumulative_mesh_budget(monkeypatch):
    def work(points, *args):
        return bytes(len(points)), len(points), False

    monkeypatch.setattr(native, "contains", work)
    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False)
    sampler.packet_size, sampler.native_threads = 128, 4
    sampler.work = mesh.MAX_MESH_SAMPLE_WORK - 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        sampler.executor = pool
        with pytest.raises(ValueError, match="Decorative mesh sampling budget exceeded"):
            sampler.contains(np.zeros((8 * 32768, 3)))


def test_completed_worker_timeout_is_propagated_instead_of_waiting_forever():
    checks = 0

    def cancel_guard():
        nonlocal checks
        checks += 1
        return checks > 16

    class FailedPool:
        def submit(self, *_args, **_kwargs):
            future = Future()
            future.set_exception(TimeoutError("sample worker failed"))
            return future

    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False, cancelled=cancel_guard)
    sampler.packet_size, sampler.native_threads, sampler.executor = 128, 4, FailedPool()
    with pytest.raises(TimeoutError, match="sample worker failed"):
        sampler.contains(np.zeros((8 * 32768, 3)))


def test_worker_finishing_after_a_poll_timeout_still_returns_its_result():
    class FinishesAfterPoll(Future):
        def __init__(self, count):
            super().__init__()
            self.count = count

        def result(self, timeout=None):
            if not self.done():
                self.set_result(np.zeros(self.count, dtype=bool))
                raise TimeoutError("poll timed out before completion")
            return super().result(timeout)

    class FinishingPool:
        def submit(self, _fn, points):
            return FinishesAfterPoll(len(points))

    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False)
    sampler.packet_size, sampler.native_threads, sampler.executor = 128, 4, FinishingPool()
    assert not sampler.contains(np.zeros((8 * 32768, 3))).any()


def test_later_failed_job_is_not_hidden_behind_a_running_first_job():
    checks = 0

    def cancel_guard():
        nonlocal checks
        checks += 1
        return checks > 16

    class LaterFailurePool:
        def __init__(self):
            self.submissions = 0

        def submit(self, *_args, **_kwargs):
            self.submissions += 1
            future = Future()
            if self.submissions == 2:
                future.set_exception(ValueError("later sample worker failed"))
            return future

    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False, cancelled=cancel_guard)
    sampler.packet_size, sampler.native_threads, sampler.executor = 128, 4, LaterFailurePool()
    with pytest.raises(ValueError, match="later sample worker failed"):
        sampler.contains(np.zeros((8 * 32768, 3)))


def test_coarse_jobs_keep_cancellation_callbacks_on_the_calling_thread():
    caller = threading.get_ident()
    callbacks = []

    def cancelled():
        callbacks.append(threading.get_ident())
        return False

    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False, cancelled=cancelled)
    sampler.packet_size, sampler.native_threads = 128, 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        sampler.executor = pool
        assert not sampler.contains(np.full((8 * 32768, 3), 4.0)).any()
    assert callbacks and set(callbacks) == {caller}


@pytest.mark.parametrize("native_enabled", [False, True])
def test_general_numpy_inputs_keep_the_serial_fallback(monkeypatch, native_enabled):
    if not native_enabled:
        monkeypatch.setattr(mesh, "_mesh_native", None)
    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), closed=False)
    sampler.packet_size, sampler.native_threads = 128, 4

    class NoJobs:
        def submit(self, *_args, **_kwargs):
            pytest.fail("Unsupported native inputs must keep the original NumPy path")

    sampler.executor = NoJobs()
    result = sampler.contains(np.full((8 * 32768, 3), 4, dtype=np.float32))
    assert not result.any()
