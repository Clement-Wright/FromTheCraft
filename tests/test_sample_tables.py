"""Repeated coordinate arithmetic may be reused only with identical float bits."""

import numpy as np
import pytest

from fromthecraft.detail import DETAIL_SAMPLES
from fromthecraft.geometry import _local_samples, rotation

native = pytest.importorskip("fromthecraft._mesh_native")


@pytest.mark.parametrize("scale", [0.25, 0.5, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("axes", [False, True])
def test_table_samples_match_original_scalar_kernels(scale, axes):
    rng = np.random.default_rng(8147)
    cells = rng.integers(-2048, 2048, (3, 3), dtype=np.intp)
    size, span = np.array([0.03125, 1.372, 4.173]), np.array([2.1, 0.127, 4.175])
    inverse = np.eye(4)
    inverse[:3, 3] = [-234.109712, -0.0, 149.784741]
    if axes:
        transforms = [rotation(i) for i in range(24)]
        original = native.axis_sample_points
    else:
        transforms = [np.diag([0.003451, 1.0000073, 189234.019])]
        original = native.sample_points
    for matrix in transforms:
        inverse[:3, :3] = matrix
        expected = original(cells, DETAIL_SAMPLES, inverse, size, scale, span)
        actual = native.table_sample_points(cells, DETAIL_SAMPLES, inverse, size, scale, span, axes)
        assert actual == expected


@pytest.mark.parametrize("grid", ["zero", "64", "65", "8192", "8193", "empty"])
def test_table_limits_and_zero_signs_preserve_original_bytes(grid):
    samples = np.tile([[-0.0, 0.25, 0.75], [0.0, 0.5, 0.25]], (256, 1))
    if grid == "empty":
        samples = np.empty((0, 3))
    elif grid != "zero":
        count = int(grid)
        samples = np.arange(count * 3, dtype=np.float64).reshape(count, 3) / (count * 3)
    cells = np.array([[0, -1, 1], [-2048, 2048, -17]], dtype=np.intp)
    args = (cells, samples, np.eye(4), np.ones(3), 3, np.ones(3))
    assert native.table_sample_points(*args, False) == native.sample_points(*args)


def test_maximum_table_grid_with_exactly_64_unique_coordinates():
    values = np.arange(64, dtype=np.float64) / 64
    samples = np.tile(np.column_stack((values, values[::-1], np.roll(values, 17))), (128, 1))
    cells = np.array([[0, -1, 1], [-2048, 2048, -17]], dtype=np.intp)
    inverse = np.diag([0.17431, 1.71241, 7.11319, 1.0])
    inverse[:3, 3] = (-12.174, 3.719, -91.737)
    args = (cells, samples, inverse, np.ones(3), 3, np.array([1.713, 0.021, 4.1]))
    assert native.table_sample_points(*args, False) == native.sample_points(*args)


def test_dense_grids_use_table_kernel_and_older_native_binary_still_works(monkeypatch):
    calls = []
    transform = native.table_sample_points

    def record(*args):
        calls.append(args[-1])
        return transform(*args)

    monkeypatch.setattr(native, "table_sample_points", record)
    cells = np.tile(np.array([[0, -1, 1], [-7, 5, 17]], dtype=np.intp), (8, 1))
    inverse = np.eye(4)
    inverse[:3, :3] = rotation(1)
    actual = _local_samples(cells, DETAIL_SAMPLES, inverse, (1, 2, 4), 3)
    assert calls == [True]
    monkeypatch.delattr(native, "table_sample_points")
    expected = _local_samples(cells, DETAIL_SAMPLES, inverse, (1, 2, 4), 3)
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


def test_small_batches_keep_the_direct_transform(monkeypatch):
    def unexpected(*args):
        pytest.fail("Table preparation costs more than it saves on small batches")

    monkeypatch.setattr(native, "table_sample_points", unexpected)
    cells = np.array([[0, -1, 1]], dtype=np.intp)
    args = (cells, DETAIL_SAMPLES, np.eye(4), np.ones(3), 3, np.ones(3))
    actual = _local_samples(*args)
    assert actual.tobytes() == native.sample_points(*args)


@pytest.mark.parametrize("invalid", ["affine", "zero_size", "nan", "oversize", "endian", "axes"])
def test_table_kernel_retains_original_input_validation(invalid):
    cells = np.zeros((1, 3), dtype=np.intp)
    samples, inverse, size, span = DETAIL_SAMPLES.copy(), np.eye(4), np.ones(3), np.ones(3)
    axes = False
    if invalid == "affine":
        inverse[0, 1] = 1
    elif invalid == "zero_size":
        size[0] = 0
    elif invalid == "nan":
        samples[0, 0] = np.nan
    elif invalid == "oversize":
        cells = np.zeros((280, 3), dtype=np.intp)
    elif invalid == "endian":
        samples = samples.astype(">f8")
    else:
        axes = True
        inverse[1, 1] = -2
    with pytest.raises((ValueError, BufferError)):
        native.table_sample_points(cells, samples, inverse, size, 3, span, axes)
