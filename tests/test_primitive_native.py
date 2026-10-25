"""Native primitive filters must fall back at ambiguous float64 boundaries."""

import numpy as np
import pytest

from fromthecraft import geometry
from fromthecraft.detail import DETAIL_SAMPLES
from fromthecraft.ftd_shapes import PLANES, planes
from primitive_reference import reference_contains

native = pytest.importorskip("fromthecraft._mesh_native")
SHAPES = tuple(PLANES) + (
    "box", "wedge", "curve", "corner", "stairs", "stairs_inner_left", "stairs_inner_right",
    "stairs_outer_left", "stairs_outer_right",
) + tuple(f"ftd_offset_{side}_{n}" for side in ("left", "right") for n in range(1, 5)) + (
    "ftd_transition_left_1_3", "ftd_transition_right_2_3", "ftd_transition_inverse_left_1_4",
    "ftd_transition_inverse_right_3_4",
) + tuple(f"copycat_slope_{n}" for n in range(1, 9))


@pytest.mark.parametrize("shape", SHAPES)
def test_native_primitive_predicates_match_frozen_numpy(shape):
    assert hasattr(native, "contains_primitive")
    points = np.random.default_rng(1841).uniform(-0.1, 1.1, (20000, 3))
    np.testing.assert_array_equal(geometry.contains(shape, points), reference_contains(shape, points))
    np.testing.assert_array_equal(geometry.contains(shape, DETAIL_SAMPLES), reference_contains(shape, DETAIL_SAMPLES))


def test_rounding_uncertainty_repeats_the_complete_original_numpy_batch(monkeypatch):
    assert hasattr(native, "contains_primitive")
    points = np.random.default_rng(1842).uniform(0.1, 0.9, (40000, 3))
    points[32767] = (0.25, 0.5, 0.5 + 1e-8)
    coefficients = np.array(planes("ftd_slope"), dtype=float)
    assert native.contains_primitive(points, coefficients, 0)[1]
    expected = reference_contains("ftd_slope", points)
    batches = []
    original = geometry._contains_numpy

    def fallback(shape, values, *args):
        batches.append(values)
        return original(shape, values, *args)

    monkeypatch.setattr(geometry, "_contains_numpy", fallback)
    np.testing.assert_array_equal(geometry.contains("ftd_slope", points), expected)
    assert len(batches) == 1 and batches[0] is points


@pytest.mark.parametrize("dtype", [np.float32, np.int64])
def test_other_numeric_types_keep_the_original_arithmetic(monkeypatch, dtype):
    assert hasattr(native, "contains_primitive")

    def unexpected(*_args):
        pytest.fail("Keep non-float64 arrays on the original path")

    monkeypatch.setattr(native, "contains_primitive", unexpected)
    points = np.asarray([[0, 0, 0], [1, 1, 1]], dtype=dtype)
    np.testing.assert_array_equal(geometry.contains("ftd_slope", points), reference_contains("ftd_slope", points))


def test_primitive_result_keeps_writable_boolean_array_behavior():
    assert hasattr(native, "contains_primitive")
    result = geometry.contains("wedge", np.array([[0.5, 0.25, 0.75]]))
    assert result.dtype == bool and result.flags.writeable
    result[0] = False


def test_unusual_plane_magnitudes_keep_the_original_numpy_path():
    shape = "ftd_offset_left_10000000000000"
    points = np.array([[0.1, 0.2, 0.3], [0.8, 0.9, 1.0]])
    np.testing.assert_array_equal(geometry.contains(shape, points), reference_contains(shape, points))


@pytest.mark.parametrize("invalid", ["mode", "coefficients", "oversize", "strides"])
def test_primitive_native_buffers_are_bounded_and_validated(invalid):
    assert hasattr(native, "contains_primitive")
    points, coefficients, mode = np.ones((4, 3)), np.empty((0, 4)), 0
    if invalid == "mode":
        mode = 9
    elif invalid == "coefficients":
        coefficients = np.array([[np.nan, 0, 0, 1]])
    elif invalid == "oversize":
        points = np.zeros((1_572_865, 3))
    else:
        points = points[::2]
    with pytest.raises((ValueError, BufferError)):
        native.contains_primitive(points, coefficients, mode)
