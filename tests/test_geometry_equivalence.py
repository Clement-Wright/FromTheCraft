"""Performance work must preserve export bytes, geometry and first-owner mapping."""

from dataclasses import replace
from itertools import product

import numpy as np
import pytest

from fromthecraft.compatibility import MODS
from fromthecraft.convert import convert
from fromthecraft.geometry import quaternion, voxelize
from fromthecraft.mesh_geometry import prepare_meshes
from fromthecraft.model import Part, Scene, State
from voxel_reference import reference_voxelize


def overlapping_decorations():
    rng = np.random.default_rng(114)
    parts = [Part("first host", "box", (1, 1, 1), np.eye(4), "Metal", (0.8, 0.2, 0.1))]
    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    closed_faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    for i in range(6):
        transform = np.eye(4)
        transform[:3, :3] = quaternion(rng.normal(size=4)) @ np.diag(rng.uniform(0.3, 2, 3))
        if i % 2:
            transform[:3, 0] *= -1
        transform[:3, 3] = rng.uniform(-0.5, 0.5, 3)
        parts.append(Part(
            f"decoration {i}", "mesh", (1, 1, 1), transform, "Metal", tuple(rng.random(3)),
            mesh=(vertices, closed_faces if i % 2 else closed_faces[:1]), decoration=True,
        ))
    for i, offset in enumerate((0.001, 0.875)):
        transform = np.eye(4)
        transform[:3, 3] = (2 + offset, offset, offset)
        parts.append(Part(f"small byte {i}", "box", (0.125,) * 3, transform,
                          "Stone", (0.1, 0.8, 0.9)))
    # A mapping override must retain ownership when a later mesh overlaps it.
    parts[0] = replace(parts[0], mapping_override=State("minecraft:gold_block"))
    return Scene(parts, "blueprint")


@pytest.mark.parametrize("scale,detailed", product((0.25, 0.5, 1, 2), (False, True)))
def test_optimized_voxelization_preserves_original_cell_order_masks_and_owners(scale, detailed):
    source = prepare_meshes(overlapping_decorations(), "appearance", 0.125, scale)
    expected, offset = reference_voxelize(source, scale, detailed=detailed)
    actual, actual_offset = voxelize(source, scale, detailed=detailed)
    assert actual_offset == offset
    assert list(actual) == list(expected)
    for key, part in actual.items():
        old = expected[key]
        assert (part.identity, part.shape, part.state, part.mapping_override) == (
            old.identity, old.shape, old.state, old.mapping_override
        )


@pytest.mark.parametrize("detailed,hollow", product((False, True), repeat=2))
@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_optimized_conversion_preserves_original_export_bytes(monkeypatch, detailed, hollow, output):
    import importlib

    module = importlib.import_module("fromthecraft.convert")
    # Litematic records wall-clock export timestamps; hold only that clock
    # constant so the byte comparison covers the complete serialized file.
    monkeypatch.setattr("litemapy.schematic.time", lambda: 1_700_000_000.0)
    source = overlapping_decorations()
    options = dict(mods=tuple(MODS), detailed_copycats=detailed, hollow=hollow,
                   preference="color", decoration_mode="appearance", surface_thickness=0.125)
    actual = convert(source, output, **options)
    monkeypatch.setattr(module, "voxelize", reference_voxelize)
    expected = convert(source, output, **options)
    assert actual.content == expected.content
    assert actual.offset == expected.offset
    assert actual.notices == expected.notices


def test_duplicate_seed_reduction_preserves_first_seen_order_and_all_octants():
    from fromthecraft.geometry import merge_seed_masks

    positions = np.array([[3, 0, 0], [1, 0, 0], [3, 0, 0], [2, 0, 0], [3, 0, 0]] * 50)
    octants = np.array([0, 2, 7, 5, 3] * 50)
    seeds = {}
    merge_seed_masks(seeds, positions, octants, {(2, 0, 0): 255})
    assert list(seeds) == [(3, 0, 0), (1, 0, 0)]
    assert seeds == {(3, 0, 0): 1 | 128 | 8, (1, 0, 0): 4}
