"""Upscale choices preserve geometry, ordered sampling and sparse storage."""

import subprocess
import sys
import pickle
from dataclasses import fields

import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.minecraft import read_structure
from fromthecraft.model import Part, Scene


def test_per_cell_parts_use_bounded_storage_and_roundtrip_cached_state():
    part = Part("wall", "box", (4, 1, 1), np.eye(4), "Stone", (1, 1, 1))
    footprint = sys.getsizeof(part) + (sys.getsizeof(part.__dict__) if hasattr(part, "__dict__") else 0)
    assert footprint < 250, "Millions of per-cell attribute dictionaries consume avoidable memory"
    restored = pickle.loads(pickle.dumps(part))
    assert restored.identity == part.identity
    np.testing.assert_array_equal(restored.transform, part.transform)
    legacy = Part.__new__(Part)
    legacy.__setstate__(
        {field.name: getattr(part, field.name) for field in fields(part) if field.name != "detail_sources"}
    )
    assert legacy.identity == part.identity
    np.testing.assert_array_equal(legacy.transform, part.transform)
    assert legacy.detail_sources == ()


def test_voxel_keys_reuse_python_integer_storage_without_changing_order():
    from fromthecraft.geometry import voxelize

    source = Scene([Part("wall", "box", (3, 1, 3), np.eye(4), "Stone", (1, 1, 1))], "blueprint")
    cells, _ = voxelize(source, extreme=True)
    assert all(type(axis) is int for cell in cells for axis in cell)
    assert list(cells) == [(x, 0, z) for x in range(3) for z in range(3)]
    assert len({id(part.detail_sources) for part in cells.values()}) == 1


@pytest.mark.parametrize("scale", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("span", [None, 0.03125, 4.173, (0.03125, 1.125, 4.173)])
def test_bounded_local_sample_transform_preserves_every_float_bit(scale, span):
    from fromthecraft.geometry import _local_samples
    from fromthecraft.detail import DETAIL_SAMPLES

    rng = np.random.default_rng(946)
    batch = rng.integers(-2048, 2048, (7, 3))
    inverse = rng.normal(size=(4, 4))
    size = (0.03, 1.234, 61.37)
    points = (batch[:, None, :] + DETAIL_SAMPLES).reshape(-1, 3) / scale
    expected = (points @ inverse[:3, :3].T + inverse[:3, 3]) / size
    if span is not None:
        expected = expected * span
    actual = _local_samples(batch, DETAIL_SAMPLES, inverse, size, scale, span)
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64))


@pytest.mark.parametrize("exterior", [False, True])
def test_sealed_interior_decorations_do_not_repeat_invisible_sampling(monkeypatch, exterior):
    from dataclasses import replace
    import fromthecraft.geometry as geometry

    host = Part("hull", "box", (3, 3, 3), np.eye(4), "Stone", (0.95, 0.95, 0.95))
    transform = np.eye(4)
    transform[:3, 3] = (1.5, 2.5 if exterior else 1.5, 1.5)
    accent = replace(
        host, identity="decal", size=(0.5,) * 3, transform=transform, color=(0.1, 0.8, 0.8), decoration=True
    )
    options = dict(mods=("copycats",), extreme_detail=True, preference="color", decoration_mode="decorations")
    reference = convert(Scene([host], "blueprint"), "nbt", **options)
    calls, contains = [], geometry.contains

    def sampled(shape, points):
        calls.append(len(points))
        return contains(shape, points)

    monkeypatch.setattr(geometry, "contains", sampled)
    result = convert(Scene([host, accent], "blueprint"), "nbt", **options)
    if exterior:
        assert calls
        assert result.content != reference.content
        assert any(part.color[1] > part.color[0] + 0.1 for part in result.scene.parts)
    else:
        assert result.content == reference.content
        assert not calls, "An already sealed full cell cannot reveal buried decoration paint"


@pytest.mark.parametrize("scale", [3, 5])
def test_new_integer_scales_expand_a_cube_without_changing_material(scale):
    scene = Scene([Part("cube", "box", (1, 1, 1), np.eye(4), "Metal", (0.5,) * 3)], "blueprint")
    result = convert(scene, "nbt", scale=scale)
    assert len(result.scene.parts) == scale**3
    reference = convert(scene, "nbt", scale=1)
    assert {part.state.name for part in result.scene.parts} == {reference.scene.parts[0].state.name}
    assert {tuple(part.transform[:3, 3]) for part in result.scene.parts} == {
        (x, y, z) for x in range(scale) for y in range(scale) for z in range(scale)
    }


@pytest.mark.parametrize("scale", [3, 5])
def test_cli_accepts_the_new_integer_scales(tmp_path, scale):
    destination = tmp_path / "scaled.nbt"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fromthecraft",
            "convert",
            "tests/fixtures/asymmetric.blueprint",
            str(destination),
            "--scale",
            str(scale),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert read_structure(destination.read_bytes()).parts


def test_sparse_export_never_allocates_a_dense_bounding_box(monkeypatch):
    from fromthecraft import litematic_output, minecraft
    from fromthecraft.model import State
    import exact_reference

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    cells = {(1, 1, 1): State("minecraft:stone"), (127, 31, 127): State("minecraft:glass")}
    expected = exact_reference.write_litematic(cells, (128, 32, 128))
    allocations, original = [], np.zeros

    def track(shape, *args, **kwargs):
        allocations.append(shape)
        return original(shape, *args, **kwargs)

    monkeypatch.setattr(litematic_output.np, "zeros", track)
    assert minecraft.write_litematic(cells, (128, 32, 128)) == expected
    assert not any(
        isinstance(shape, tuple) and len(shape) == 3 and np.prod(shape) > 1 for shape in allocations
    )


def test_full_wall_masks_share_storage_without_spreading_later_overlays():
    from dataclasses import replace
    from fromthecraft.geometry import voxelize

    wall = Part("wall", "box", (4, 1, 1), np.eye(4), "Metal", (0.5, 0.5, 0.5))
    cells, _ = voxelize(Scene([wall], "blueprint"), extreme=True)
    assert len({id(part.detail_sources[0][1]) for part in cells.values()}) == 1
    transform = np.eye(4)
    transform[0, 3] = 1
    overlay = replace(
        wall, identity="accent", size=(1, 1, 1), transform=transform, color=(0.1, 0.8, 0.8), decoration=True
    )
    overlaid, _ = voxelize(Scene([wall, overlay], "blueprint"), extreme=True)
    assert len(overlaid[(1, 0, 0)].detail_sources) == 2
    assert all(len(overlaid[(x, 0, 0)].detail_sources) == 1 for x in (0, 2, 3))


@pytest.mark.parametrize("batch_size", [1, 7, 279])
def test_candidate_batches_keep_the_original_negative_coordinate_order(batch_size):
    from fromthecraft.geometry import candidate_batches, cell_candidates

    low, high = np.array([-4, -2, 3]), np.array([3, 4, 11])
    batches = list(candidate_batches(low, high, batch_size))
    assert max(map(len, batches)) <= batch_size
    np.testing.assert_array_equal(np.concatenate(batches), cell_candidates(low, high))
    assert list(candidate_batches(high, low, batch_size)) == []


@pytest.mark.parametrize("offset", [0, -5000, 5000])
def test_fine_seed_deduplication_preserves_masks_and_lexicographic_order(monkeypatch, offset):
    from fromthecraft.extreme import merge_fine_seeds

    rng = np.random.default_rng(542)
    positions = rng.integers(0, 24, (4096, 3)) + offset
    fractions = rng.uniform(0, 1, (4096, 3))
    indices = np.clip((fractions * 16).astype(int), 0, 15) @ [256, 16, 1]
    expected = {}
    for x, y, z, index in np.unique(np.column_stack((positions, indices)), axis=0):
        key = (x, y, z)
        expected[key] = expected.get(key, 0) | 1 << int(index)
    dimensions, original = [], np.unique

    def tracked(values, *args, **kwargs):
        dimensions.append(values.ndim)
        return original(values, *args, **kwargs)

    monkeypatch.setattr(np, "unique", tracked)
    actual = {}
    merge_fine_seeds(actual, positions, fractions, set())
    assert list(actual.items()) == list(expected.items())
    assert dimensions == ([1] if offset == 0 else [2])
