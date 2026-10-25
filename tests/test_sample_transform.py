"""Fused mesh coordinates retain the original float64 arithmetic and ordering."""

import numpy as np
import pytest

from fromthecraft.geometry import _local_samples


@pytest.mark.parametrize("scale", [0.25, 0.5, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("span", [None, (0.03125, 1.125, 4.173)])
def test_native_diagonal_samples_keep_every_original_float_bit(scale, span):
    native = pytest.importorskip("fromthecraft._mesh_native")
    from fromthecraft.detail import DETAIL_SAMPLES

    rng = np.random.default_rng(415)
    inverse = np.eye(4)
    inverse[:3, :3] = np.diag([0.003451, 1.0000073, 189234.019])
    inverse[:3, 3] = [-234.109712, -0.0, 149.784741]
    size = np.array([0.03125, 1.372, 4.173])
    batch = rng.integers(-2048, 2048, (7, 3))
    points = (batch[:, None, :] + DETAIL_SAMPLES).reshape(-1, 3) / scale
    expected = (points @ inverse[:3, :3].T + inverse[:3, 3]) / size
    if span is not None:
        expected *= span
    content = native.sample_points(
        batch, DETAIL_SAMPLES, inverse, size, scale, np.asarray(span if span else (1.0, 1.0, 1.0))
    )
    actual = np.frombuffer(content, dtype=np.float64).reshape(-1, 3)
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


def test_diagonal_dispatch_fuses_the_large_intermediate(monkeypatch):
    import fromthecraft.mesh_geometry as mesh

    native = pytest.importorskip("fromthecraft._mesh_native")
    calls = []
    real = native.sample_points

    def track(*args):
        calls.append(len(args[0]) * len(args[1]))
        return real(*args)

    monkeypatch.setattr(native, "sample_points", track)
    batch = np.array([[0, -1, 2], [-4, 5, 0]], dtype=np.intp)
    samples = np.array([[-0.0, 0.25, 0.75], [0.75, 0.5, 0.25]])
    inverse = np.diag([0.125, 7.0, 1.001, 1.0])
    actual = _local_samples(batch, samples, inverse, (1, 1, 1), 2, (8.0, 0.125, 3.0))
    assert calls == [4], "Prepared mesh transforms need no second full points array or BLAS dispatch"
    monkeypatch.setattr(mesh, "_mesh_native", None)
    expected = _local_samples(batch, samples, inverse, (1, 1, 1), 2, (8.0, 0.125, 3.0))
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


@pytest.mark.parametrize("kind", ["affine", "negative", "float32", "strided"])
def test_non_mesh_transforms_retain_numpy_path(monkeypatch, kind):
    native = pytest.importorskip("fromthecraft._mesh_native")

    def unexpected(*_args):
        pytest.fail("Keep the original general affine and unusual-array path")

    monkeypatch.setattr(native, "sample_points", unexpected, raising=False)
    inverse = np.eye(4)
    if kind == "affine":
        inverse[0, 1] = 0.174
    elif kind == "negative":
        inverse[1, 1] = -1
    elif kind == "float32":
        inverse = inverse.astype(np.float32)
    batch = np.arange(12).reshape(4, 3)
    if kind == "strided":
        batch = batch[::2]
    samples = np.array([[0.25, 0.75, 0.5]])
    expected = ((batch[:, None, :] + samples).reshape(-1, 3) / 3) @ inverse[:3, :3].T + inverse[:3, 3]
    actual = _local_samples(batch, samples, inverse, (1, 1, 1), 3)
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


@pytest.mark.parametrize("invalid", ["affine", "zero_size", "nan", "oversize", "endian"])
def test_native_sample_transform_rejects_invalid_buffers(invalid):
    native = pytest.importorskip("fromthecraft._mesh_native")
    batch = np.zeros((1, 3), dtype=np.intp)
    samples, inverse, size, span = np.zeros((1, 3)), np.eye(4), np.ones(3), np.ones(3)
    if invalid == "affine":
        inverse[0, 1] = 1
    elif invalid == "zero_size":
        size[0] = 0
    elif invalid == "nan":
        samples[0, 0] = np.nan
    elif invalid == "oversize":
        batch = np.zeros((1_572_865, 3), dtype=np.intp)
    else:
        samples = samples.astype(">f8")
    with pytest.raises((ValueError, BufferError)):
        native.sample_points(batch, samples, inverse, size, 2, span)


def test_strided_dimensions_and_broadcast_span_keep_original_behavior():
    batch = np.array([[1, 2, 3]], dtype=np.intp)
    samples = np.array([[0.25, 0.5, 0.75]])
    inverse = np.diag([0.123, 1.312, 2.412, 1.0])
    size = np.array([1.0, 0.0, 2.0, 0.0, 3.0, 0.0])[::2]
    for span in (np.array([2.0, 0.0, 3.0, 0.0, 4.0, 0.0])[::2], np.array([[2.0, 3.0, 4.0]])):
        points = (batch[:, None, :] + samples).reshape(-1, 3) / 3
        expected = (points @ inverse[:3, :3].T + inverse[:3, 3]) / size * span
        actual = _local_samples(batch, samples, inverse, size, 3, span)
        np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))
