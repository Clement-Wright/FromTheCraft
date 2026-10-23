"""Extreme detail is judged from the actual exported Minecraft geometry."""

from dataclasses import replace
from itertools import product

import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.geometry import contains, rotation
from fromthecraft.minecraft import read_litematic, read_structure, write_litematic, write_structure
from fromthecraft.model import Part, Scene, State
from fromthecraft.preview import preview


def occupied(scene, points, offset=(0, 0, 0)):
    hit = np.zeros(len(points), dtype=bool)
    for part in scene.parts:
        inv = np.linalg.inv(part.transform)
        local = (points - offset) @ inv[:3, :3].T + inv[:3, 3]
        hit |= contains(part.shape, local / part.size)
    return hit


def test_conversion_cancels_during_material_fitting(monkeypatch):
    import importlib
    from fromthecraft.model import Cancelled

    module = importlib.import_module("fromthecraft.convert")
    parts = []
    for x in range(300):
        transform = np.eye(4)
        transform[0, 3] = x
        parts.append(Part("box", "box", (1, 1, 1), transform, "Stone", (0.8, 0.1, 0.1)))
    cancelled, calls = False, 0
    real = module.mc_target

    def painting(*args):
        nonlocal cancelled, calls
        calls += 1
        cancelled = True
        return real(*args)

    monkeypatch.setattr(module, "mc_target", painting)
    with pytest.raises(Cancelled):
        convert(
            Scene(parts, "blueprint"),
            "nbt",
            mods=("copycats",),
            extreme_detail=True,
            cancelled=lambda: cancelled,
        )
    assert calls < len(parts)


def smooth_states():
    for facing in ("south", "west", "north", "east"):
        yield State("copycats:copycat_vertical_slope", (("facing", facing),))
        for half in ("bottom", "top"):
            yield State("copycats:copycat_slope", (("facing", facing), ("half", half)))
            for layers in (1, 2, 3, 5, 6, 7, 8):
                yield State(
                    "copycats:copycat_slope_layer",
                    tuple(
                        sorted(
                            {
                                "facing": facing,
                                "half": half,
                                "layers": str(layers),
                            }.items()
                        )
                    ),
                )


@pytest.mark.parametrize("target", list(smooth_states()))
@pytest.mark.parametrize(
    "writer,reader", [(write_structure, read_structure), (write_litematic, read_litematic)]
)
def test_smooth_copycats_roundtrip_matches_independent_visible_plane(target, writer, reader):
    target = replace(target, copied_material=State("minecraft:red_concrete"))
    result = reader(writer({(0, 0, 0): target}, (1, 1, 1)))
    assert not result.notices
    assert result.parts[0].state == target
    points = np.random.default_rng(901).uniform(0.00001, 0.99999, (1000, 3))
    props = dict(target.properties)
    # Undo the documented block-facing transforms, independently of reader code.
    x, y, z = points.T
    x, z = {
        "south": (x, z),
        "west": (z, 1 - x),
        "north": (1 - x, 1 - z),
        "east": (1 - z, x),
    }[props["facing"]]
    if target.name.endswith("vertical_slope"):
        y = 1 - x
    elif props["half"] == "top":
        y = 1 - y
    layers = int(props.get("layers", "4"))
    lower, upper = (0, layers / 4) if layers <= 4 else ((layers - 4) / 4, 1)
    np.testing.assert_array_equal(occupied(result, points), y <= lower + (upper - lower) * z)
    display = preview(result)
    assert display["groups"][0].get("vertices"), "Preview must use the smooth hull, not a cube"


@pytest.mark.parametrize("orientation", range(24))
@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_extreme_uses_exact_smooth_slope_when_it_exists(output, orientation):
    transform = np.eye(4)
    transform[:3, :3] = rotation(orientation)
    source = Scene([Part("slope", "ftd_slope", (1, 1, 1), transform, "Metal", (0.8, 0.1, 0.1))], "blueprint")
    result = convert(source, output, mods=("copycats",), extreme_detail=True)
    assert {p.state.name for p in result.scene.parts} <= {
        "copycats:copycat_slope",
        "copycats:copycat_vertical_slope",
    }
    points = np.random.default_rng(516).uniform(0.001, 0.999, (500, 3))
    expected = points[:, 1] + points[:, 2] <= 1
    world = points @ transform[:3, :3].T
    np.testing.assert_array_equal(occupied(result.scene, world, result.offset), expected)


@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_extreme_retains_independent_colors_inside_a_full_cell_of_bytes(output):
    parts = []
    for x, y, z in product((0, 0.5), repeat=3):
        transform = np.eye(4)
        transform[:3, 3] = x, y, z
        parts.append(Part("byte", "box", (0.5,) * 3, transform, "Stone", (x + 0.2, y + 0.2, z + 0.2)))
    source = Scene(parts, "blueprint")
    detailed = convert(source, output, mods=("copycats",), detailed_copycats=True, preference="color")
    assert len({p.state.name for p in detailed.scene.parts}) == 1
    result = convert(source, output, mods=("copycats",), extreme_detail=True, preference="color")
    assert len({p.state for p in result.scene.parts}) == 1
    target = result.scene.parts[0].state
    assert target.name == "copycats:copycat_byte"
    assert len(target.copied_materials) == 8
    assert len(set(dict(target.copied_materials).values())) == 8
    assert len(result.scene.parts) == 8


def test_extreme_requires_copycats_and_minecraft_output():
    source = Scene([Part("box", "box", (1, 1, 1), np.eye(4), "Metal", (0.8, 0.1, 0.1))], "blueprint")
    with pytest.raises(ValueError, match="Extreme detail requires"):
        convert(source, "nbt", extreme_detail=True)


@pytest.mark.parametrize("output", ["nbt", "litematic"])
@pytest.mark.parametrize("thickness,colors", [(3 / 16, 4), (1 / 8, 2)])
@pytest.mark.parametrize("orientation", range(24))
def test_thin_colored_details_use_equivalent_multi_material_shapes(output, thickness, colors, orientation):
    parts = []
    for index in range(colors):
        x, z = (index // 2, index % 2) if colors == 4 else (index, 0)
        transform = np.eye(4)
        transform[:3, :3] = rotation(orientation)
        transform[:3, 3] = rotation(orientation) @ (x / 2, 0, z / 2)
        color = ((0.9, 0.1, 0.1), (0.1, 0.1, 0.9), (0.1, 0.9, 0.1), (0.9, 0.9, 0.9))[index]
        parts.append(
            Part(
                "colored panel", "box", (0.5, thickness, 0.5 if colors == 4 else 1), transform, "Stone", color
            )
        )
    result = convert(
        Scene(parts, "blueprint"), output, mods=("copycats",), extreme_detail=True, preference="color"
    )
    target = result.scene.parts[0].state
    assert len(set(dict(target.copied_materials).values())) == colors
    from fromthecraft.palettes import mc_target
    from fromthecraft.compatibility import selected_mods

    for source in parts:
        center = source.transform[:3, :3] @ (np.array(source.size) / 2) + source.transform[:3, 3]
        material = mc_target(source, "color", selected_mods(("copycats",)))
        matching = [
            p for p in result.scene.parts if dict(target.copied_materials).get(p.material_slot) == material
        ]
        assert occupied(Scene(matching, output), np.array([center]), result.offset).all()
    points = np.random.default_rng(716).uniform(0.0001, 0.9999, (2000, 3))
    world = points @ rotation(orientation).T
    np.testing.assert_array_equal(occupied(result.scene, world, result.offset), points[:, 1] <= thickness)


def test_small_decoration_keeps_its_color_on_a_larger_host_without_opening_holes():
    host = Part("white host", "box", (1, 1, 1), np.eye(4), "Stone", (0.95, 0.95, 0.95))
    transform = np.eye(4)
    transform[:3, 3] = (0.875, 0.875, 0.875)
    accent = Part("cyan accent", "box", (0.125,) * 3, transform, "Stone", (0.1, 0.8, 0.8), decoration=True)
    result = convert(
        Scene([host, accent], "blueprint"),
        "nbt",
        mods=("copycats",),
        extreme_detail=True,
        preference="color",
        decoration_mode="decorations",
    )
    assert any(p.color[1] > p.color[0] + 0.1 for p in result.scene.parts)
    points = np.random.default_rng(983).uniform(0.001, 0.999, (1000, 3))
    assert occupied(result.scene, points, result.offset).all()


def test_tiny_accent_between_volume_probes_is_retained_in_a_byte():
    host = Part("white host", "box", (1, 1, 1), np.eye(4), "Stone", (0.95, 0.95, 0.95))
    transform = np.eye(4)
    transform[:3, 3] = (0.507, 0.507, 0.99)
    accent = Part("tiny cyan dot", "box", (0.01,) * 3, transform, "Stone", (0.1, 0.8, 0.8), decoration=True)
    result = convert(
        Scene([host, accent], "blueprint"),
        "nbt",
        mods=("copycats",),
        extreme_detail=True,
        preference="color",
        decoration_mode="decorations",
    )
    assert any(p.color[1] > p.color[0] + 0.1 for p in result.scene.parts)


def test_repeated_decoration_colors_keep_local_overlay_order():
    white = Part("white decal", "box", (1, 1, 1), np.eye(4), "Stone", (0.95, 0.95, 0.95), decoration=True)
    cyan = replace(white, identity="cyan decal", color=(0.1, 0.8, 0.8))
    transform = np.eye(4)
    transform[:3, 3] = 0.5
    last = replace(white, identity="white corner", size=(0.5,) * 3, transform=transform)
    result = convert(
        Scene([white, cyan, last], "blueprint"),
        "nbt",
        mods=("copycats",),
        extreme_detail=True,
        preference="color",
        decoration_mode="decorations",
    )
    assert len(result.scene.parts) == 8
    white_parts = [p for p in result.scene.parts if p.color[0] > 0.8]
    assert len(white_parts) == 1
    np.testing.assert_array_equal(white_parts[0].transform[:3, 3] + result.offset, [0.5, 0.5, 0.5])


def test_buried_decoration_does_not_paint_the_exposed_hull():
    host = Part("white host", "box", (1, 1, 1), np.eye(4), "Stone", (0.95, 0.95, 0.95))
    transform = np.eye(4)
    transform[:3, 3] = 0.55
    accent = replace(
        host,
        identity="buried cyan",
        size=(0.125,) * 3,
        transform=transform,
        color=(0.1, 0.8, 0.8),
        decoration=True,
    )
    result = convert(
        Scene([host, accent], "blueprint"),
        "nbt",
        mods=("copycats",),
        extreme_detail=True,
        preference="color",
        decoration_mode="decorations",
    )
    assert all(p.color[0] > 0.8 for p in result.scene.parts)


def test_repeated_structure_colors_do_not_override_an_earlier_different_owner():
    red = Part("red corner", "box", (0.5,) * 3, np.eye(4), "Stone", (0.8, 0.1, 0.1))
    blue = replace(red, identity="blue block", size=(1, 1, 1), color=(0.1, 0.1, 0.8))
    transform = np.eye(4)
    transform[:3, 3] = 0.5
    last = replace(red, transform=transform)
    result = convert(
        Scene([red, blue, last], "blueprint"),
        "nbt",
        mods=("copycats",),
        extreme_detail=True,
        preference="color",
    )
    red_parts = [p for p in result.scene.parts if p.color[0] > p.color[2]]
    assert len(red_parts) == 1


@pytest.mark.parametrize("height", [0.25, 0.5, 0.75])
def test_extreme_fits_a_fractional_slope_without_steps(height):
    source = Scene(
        [Part("low slope", "wedge", (1, height, 1), np.eye(4), "Stone", (0.8, 0.1, 0.1))], "blueprint"
    )
    result = convert(source, "nbt", mods=("copycats",), extreme_detail=True)
    assert result.scene.parts[0].state.name == "copycats:copycat_slope_layer"
    points = np.random.default_rng(122).uniform(0.001, 0.999, (2000, 3))
    np.testing.assert_array_equal(
        occupied(result.scene, points, result.offset), points[:, 1] <= height * points[:, 2]
    )


@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_extreme_optimizations_preserve_reference_export_bytes(monkeypatch, output):
    from itertools import islice

    from fromthecraft import mesh_geometry
    from mesh_reference import ReferenceMeshSampler, reference_surface_seeds
    from test_geometry_equivalence import overlapping_decorations

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1_700_000_000.0)
    source = overlapping_decorations()
    options = dict(
        mods=("copycats",),
        extreme_detail=True,
        preference="color",
        decoration_mode="appearance",
        surface_thickness=0.125,
    )
    actual = convert(source, output, **options)

    def batches(part, scale, cancelled):
        seeds = reference_surface_seeds(part, scale, cancelled)
        while chunk := list(islice(seeds, 4096)):
            yield np.asarray(chunk)

    monkeypatch.setattr(mesh_geometry, "MeshSampler", ReferenceMeshSampler)
    monkeypatch.setattr(mesh_geometry, "surface_seed_batches", batches)
    expected = convert(source, output, **options)
    assert actual.content == expected.content
    assert actual.notices == expected.notices
    assert actual.offset == expected.offset


@pytest.mark.parametrize(
    "family,length",
    [("ftd_slope", 4), ("ftd_square_left", 4), ("ftd_square_right", 3), ("ftd_corner_left", 4)],
)
@pytest.mark.parametrize("orientation", range(24))
def test_extreme_keeps_sampled_hull_coverage_in_every_orientation(family, length, orientation):
    from fromthecraft.detail import DETAIL_SAMPLES

    transform = np.eye(4)
    transform[:3, :3] = rotation(orientation)
    source = Scene([Part("hull", family, (1, 1, length), transform, "Metal", (0.8, 0.1, 0.1))], "blueprint")
    result = convert(source, "nbt", mods=("copycats",), extreme_detail=True)
    points = np.concatenate([DETAIL_SAMPLES + (0, 0, z) for z in range(length)])
    inside = contains(family, points / (1, 1, length))
    assert occupied(result.scene, points[inside] @ transform[:3, :3].T, result.offset).all()
