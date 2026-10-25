"""Discrete FtD orientations must retain every original coordinate bit."""

import numpy as np
import pytest

from fromthecraft.detail import DETAIL_SAMPLES
from fromthecraft.geometry import SAMPLES, _local_samples, rotation

native = pytest.importorskip("fromthecraft._mesh_native")


@pytest.mark.parametrize("scale", [0.25, 0.5, 1, 2, 3, 4, 5])
def test_all_native_axis_orientations_keep_original_coordinate_bits(scale):
    assert hasattr(native, "axis_sample_points")
    rng = np.random.default_rng(1058)
    batch = np.asarray([[0, -1, 1], [-2048, 2048, -17], [17, 3, -5]], dtype=np.intp)
    size = np.array((1.0, 3.0, 4.0))
    for orientation in range(24):
        inverse = np.eye(4)
        inverse[:3, :3] = rotation(orientation)
        inverse[:3, 3] = rng.uniform(-512, 512, 3)
        points = (batch[:, None, :] + DETAIL_SAMPLES).reshape(-1, 3) / scale
        expected = (points @ inverse[:3, :3].T + inverse[:3, 3]) / size
        content = native.axis_sample_points(batch, DETAIL_SAMPLES, inverse, size, scale, np.ones(3))
        actual = np.frombuffer(content, dtype=np.float64).reshape(-1, 3)
        np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


@pytest.mark.parametrize("samples", [SAMPLES, DETAIL_SAMPLES])
def test_known_sampling_grids_dispatch_discrete_rotations_without_large_temporaries(monkeypatch, samples):
    assert hasattr(native, "axis_sample_points")
    calls = []
    transform = native.axis_sample_points

    def record(*args):
        calls.append(len(args[0]) * len(args[1]))
        return transform(*args)

    monkeypatch.setattr(native, "axis_sample_points", record)
    batch = np.asarray([[0, -1, 1], [-7, 5, 17]], dtype=np.intp)
    inverse = np.eye(4)
    inverse[:3, :3] = rotation(1)
    inverse[:3, 3] = (1.25, -4.5, 3.75)
    actual = _local_samples(batch, samples, inverse, (1, 2, 4), 3)
    expected = ((batch[:, None, :] + samples).reshape(-1, 3) / 3 @ inverse[:3, :3].T + inverse[:3, 3]) / (1, 2, 4)
    assert calls == [len(batch) * len(samples)]
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


@pytest.mark.parametrize("invalid", ["affine", "repeated_axis", "nonunit", "zero_sample", "tiny_sample", "scale"])
def test_axis_kernel_rejects_inputs_outside_its_exact_domain(invalid):
    assert hasattr(native, "axis_sample_points")
    inverse = np.eye(4)
    samples = SAMPLES.copy()
    scale = 3
    if invalid == "affine":
        inverse[0, 1] = 1
    elif invalid == "repeated_axis":
        inverse[0, :3] = inverse[1, :3]
    elif invalid == "nonunit":
        inverse[1, 1] = -2
    elif invalid == "zero_sample":
        samples[0, 0] = 0
    elif invalid == "tiny_sample":
        samples[0, 0] = np.nextafter(0.0, 1.0)
    else:
        scale = 0.3
    with pytest.raises(ValueError):
        native.axis_sample_points(np.zeros((1, 3), dtype=np.intp), samples, inverse, np.ones(3), scale, np.ones(3))


def test_unaligned_dimensions_keep_the_original_numpy_behavior():
    dimensions = np.ndarray((3,), dtype=np.float64, buffer=bytearray(25), offset=1)
    dimensions[:] = (1, 2, 4)
    inverse = np.eye(4)
    inverse[:3, :3] = rotation(1)
    batch = np.array([[1, 2, 3]], dtype=np.intp)
    expected = ((batch[:, None, :] + SAMPLES).reshape(-1, 3) / 3 @ inverse[:3, :3].T) / dimensions
    np.testing.assert_array_equal(
        _local_samples(batch, SAMPLES, inverse, dimensions, 3).view(np.uint64), expected.view(np.uint64)
    )
