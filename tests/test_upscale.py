"""Upscale choices preserve geometry, ordered sampling and sparse storage."""

import subprocess
import sys

import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.minecraft import read_structure
from fromthecraft.model import Part, Scene


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
