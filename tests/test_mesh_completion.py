"""Completion-driven jobs retain original masks and ordered work accounting."""

from concurrent.futures import Future, TimeoutError

import numpy as np
import pytest

from fromthecraft import mesh_geometry as mesh
from fromthecraft.model import Cancelled

pytest.importorskip("fromthecraft._mesh_native")


class PendingFirstBatch(Future):
    def result(self, timeout=None):
        if not self.done():
            raise TimeoutError("Controlled first sample batch is still pending")
        return super().result(timeout)


def test_finished_later_batches_refill_workers_before_the_first_batch_finishes():
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks > 32

    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), cancelled=cancelled)
    sampler.packet_size, sampler.native_threads = 128, 4
    points = np.zeros((8 * 32768 + 17, 3))
    first, submissions = PendingFirstBatch(), []

    class Pool:
        def submit(self, function, batch):
            index = len(submissions)
            submissions.append(len(batch))
            function.__self__.work = index + 1
            if index == 0:
                return first
            if index == 4:
                assert not first.done(), "The next job must start before the first one finishes"
                first.set_result(np.zeros(32768, dtype=bool))
            future = Future()
            future.set_result(np.full(len(batch), index % 2, dtype=bool))
            return future

    sampler.executor = Pool()
    try:
        answer = sampler.contains(points)
    except Cancelled:
        pytest.fail("Finished later batches left workers idle behind the first pending batch")
    np.testing.assert_array_equal(answer, np.arange(len(points)) // 32768 % 2 != 0)
    assert submissions == [32768] * 8 + [17]
    assert sampler.work == sum(range(1, 10))


def test_completed_later_batches_wait_for_source_order_before_charging_work():
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks > 32

    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]), cancelled=cancelled)
    sampler.packet_size, sampler.native_threads = 128, 4
    sampler.work = mesh.MAX_MESH_SAMPLE_WORK - 2
    starting_work = sampler.work
    first, submissions = PendingFirstBatch(), []

    class Pool:
        def submit(self, function, batch):
            index = len(submissions)
            submissions.append(index)
            function.__self__.work = index + 1
            if index == 0:
                return first
            if index == 4:
                assert sampler.work == starting_work, "Later work must wait for the first batch"
                first.set_result(np.zeros(32768, dtype=bool))
            future = Future()
            future.set_result(np.zeros(len(batch), dtype=bool))
            return future

    sampler.executor = Pool()
    with pytest.raises(ValueError, match="Decorative mesh sampling budget exceeded"):
        sampler.contains(np.zeros((8 * 32768, 3)))
    assert sampler.work == starting_work + 1 + 2


def test_ready_first_batch_budget_failure_precedes_a_later_worker_failure():
    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]))
    sampler.packet_size, sampler.native_threads = 128, 4
    sampler.work = mesh.MAX_MESH_SAMPLE_WORK - 1
    submissions = 0

    class Pool:
        def submit(self, function, batch):
            nonlocal submissions
            index = submissions
            submissions += 1
            function.__self__.work = 2
            future = Future()
            if index == 1:
                future.set_exception(ValueError("Later sample worker failed"))
            else:
                future.set_result(np.zeros(len(batch), dtype=bool))
            return future

    sampler.executor = Pool()
    with pytest.raises(ValueError, match="Decorative mesh sampling budget exceeded"):
        sampler.contains(np.zeros((4 * 32768, 3)))
    assert sampler.work == mesh.MAX_MESH_SAMPLE_WORK + 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_caller_interruption_during_completed_future_poll_is_propagated(interruption):
    class InterruptedResult(Future):
        interrupted = False

        def result(self, timeout=None):
            if not self.interrupted:
                self.interrupted = True
                raise interruption("Caller interrupted the completed-future poll")
            return super().result(timeout)

    class Pool:
        def submit(self, _function, batch):
            future = InterruptedResult()
            future.set_result(np.zeros(len(batch), dtype=bool))
            return future

    sampler = mesh.MeshSampler(np.eye(3), np.array([[0, 1, 2]]))
    sampler.packet_size, sampler.native_threads, sampler.executor = 128, 2, Pool()
    with pytest.raises(interruption, match="Caller interrupted"):
        sampler.contains(np.zeros((2 * 32768, 3)))
