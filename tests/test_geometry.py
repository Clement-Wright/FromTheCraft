import copy
import json
from pathlib import Path

import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.ftd import CATALOG, read_blueprint
from fromthecraft.geometry import bounds, rotation, voxelize
from fromthecraft.minecraft import read_structure
from fromthecraft.model import Part, Scene
from fromthecraft.palettes import BLOCKS, mc_policy
from test_adapters import nbt_bytes
from litemapy import BlockState, Region


def test_scale_two_expands_full_volume():
    scene = read_blueprint(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    result = convert(scene, "nbt", scale=2)
    assert len(result.scene.parts) == 56


@pytest.mark.parametrize(
    "scale,length,count", [(4, 16, 256), (2, 8, 32), (1, 4, 4), (0.5, 2, 2), (0.25, 1, 1)]
)
def test_requested_scale_choices_expand_or_reduce_beam(scale, length, count):
    part = Part("beam", "box", (1, 1, 4), np.eye(4), "Metal", (0.5, 0.5, 0.5))
    result = convert(Scene([part], "blueprint"), "nbt", scale=scale)
    assert len(result.scene.parts) == count
    low, high = bounds(result.scene)
    assert high[2] - low[2] == length
    if scale < 1:
        assert any("Reduced" in message for message in result.notices)


@pytest.mark.parametrize("orientation", range(24))
def test_long_native_slope_thin_tip_is_a_partial_cell_in_every_rotation(orientation):
    transform = np.eye(4)
    transform[:3, :3] = rotation(orientation)
    slope = Part("long red slope", "ftd_slope", (1, 1, 4), transform, "Metal", (0.65, 0.05, 0.05))
    cells, offset = voxelize(Scene([slope], "blueprint"))
    tip = [
        part
        for position, part in cells.items()
        if ((np.asarray(position) + offset + 0.5) @ transform[:3, :3])[2] > 3
    ]
    assert len(tip) == 1
    assert tip[0].shape.startswith("slab_")


def test_rotated_thin_copycat_slab_uses_its_real_axis_and_vanilla_uses_full_material():
    from fromthecraft.palettes import mc_target

    part = Part("thin side", "slab_x_top", (1, 1, 1), np.eye(4), "Metal", (0.65, 0.05, 0.05))
    base = mc_target(part, "color")
    assert not base.name.endswith(("_stairs", "_slab"))
    copied = mc_target(part, "color", ("copycats",))
    assert copied.name == "copycats:copycat_slab"
    assert dict(copied.properties) == {"axis": "x", "type": "top", "waterlogged": "false"}


@pytest.mark.parametrize("shape", ["wedge", "corner", "curve"])
@pytest.mark.parametrize("z", [-3, 0, 1, 3])
def test_quarter_scale_translated_small_primitives_do_not_vanish(shape, z):
    transform = np.eye(4)
    transform[2, 3] = z
    scene = Scene([Part("thin hull", shape, (1, 1, 1), transform, "Metal", (0.5, 0.5, 0.5))], "blueprint")
    assert len(voxelize(scene, 0.25)[0]) >= 1


@pytest.mark.parametrize("rot,axis,sign", [(0, 2, 1), (1, 0, 1), (2, 2, -1), (4, 1, -1), (10, 1, 1)])
def test_beam_rotations_keep_all_four_cells(rot, axis, sign):
    bp = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_text())
    for key in ("BLP", "BLR", "BCI", "BlockIds"):
        bp["Blueprint"][key] = [bp["Blueprint"][key][1]]
    bp["Blueprint"]["BLP"] = ["0,0,0"]
    bp["Blueprint"]["BLR"] = [rot]
    scene = read_blueprint(json.dumps(bp).encode())
    low, high = bounds(scene)
    assert high[axis] - low[axis] == 4
    cells, _ = voxelize(scene)
    assert len(cells) == 4
    assert np.sign(scene.parts[0].transform[axis, 2]) == sign


def test_nested_continuous_rotation_uses_parent_frame_and_pivot():
    bp = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_text())
    block = copy.deepcopy(bp["Blueprint"])
    for k in ("BLP", "BLR", "BCI", "BlockIds"):
        block[k] = [block[k][0]]
    block["BLP"] = ["1,0,0"]
    block["LocalPosition"] = "2,1,0"
    block["LocalRotation"] = "0,-0.13052619222005157,0,0.9914448613738104"
    parent = copy.deepcopy(block)
    for k in ("BLP", "BLR", "BCI", "BlockIds"):
        parent[k] = []
    parent["LocalPosition"] = "10,0,2"
    parent["LocalRotation"] = "0,0.25881904510252074,0,0.9659258262890683"
    parent["SCs"] = [block]
    for k in ("BLP", "BLR", "BCI", "BlockIds"):
        bp["Blueprint"][k] = []
    bp["Blueprint"]["SCs"] = [parent]
    scene = read_blueprint(json.dumps(bp).encode())
    center = scene.parts[0].transform @ np.array([0.5, 0.5, 0.5, 1])
    np.testing.assert_allclose(
        center[:3],
        [10 + np.sqrt(3) + np.cos(np.pi / 12) + 0.5, 1.5, 2 - 1 - np.sin(np.pi / 12) + 0.5],
        atol=1e-7,
    )
    assert len(voxelize(scene)[0]) >= 1
    assert not np.allclose(scene.parts[0].transform[:3, :3], np.round(scene.parts[0].transform[:3, :3]))


@pytest.mark.parametrize("facing", ["north", "east", "south", "west"])
@pytest.mark.parametrize("half", ["top", "bottom"])
def test_stairs_and_slabs_keep_shapes(facing, half):
    region = Region(0, 0, 0, 3, 1, 1)
    region[0, 0, 0] = BlockState(
        "minecraft:oak_stairs", facing=facing, half=half, shape="straight", waterlogged="false"
    )
    region[2, 0, 0] = BlockState("minecraft:stone_slab", type=half, waterlogged="false")
    scene = read_structure(nbt_bytes(region.to_structure_nbt(mc_version=3955)))
    assert scene.parts[0].shape.startswith("stairs")
    assert scene.parts[1].size[1] == 0.5
    cells, _ = voxelize(scene, 2)
    assert len(cells) == 10  # 6 stair eighths, 4 slab eighths


def test_hollow_hull_and_internal_deck_remain_empty():
    parts = []
    for x in range(7):
        for y in range(5):
            for z in range(9):
                if x in (0, 6) or y in (0, 4) or z in (0, 8) or (y == 2 and z < 7):
                    t = np.eye(4)
                    t[:3, 3] = (x, y, z)
                    parts.append(Part("hull", "box", (1, 1, 1), t, "Metal", (0.5, 0.5, 0.5)))
    cells, _ = voxelize(Scene(parts, "blueprint"))
    assert (3, 1, 4) not in cells and (3, 3, 4) not in cells
    assert (3, 2, 4) in cells and (3, 2, 7) not in cells


def test_wedge_exports_stairs_and_known_curve_keeps_native_preview():
    from fromthecraft.ftd import ftd_policy

    assert ftd_policy({"Name": "Metal down slope (1m)", "Material": "Metal"})[1] == "ftd_slope"
    assert ftd_policy({"Name": "Metal quarter circle (2m)", "Material": "Metal"})[1] == "curve"
    t = np.eye(4)
    part = Part("slope", "wedge", (1, 1, 1), t, "Stone", (0.5, 0.5, 0.5))
    result = convert(Scene([part], "blueprint"), "nbt")
    assert result.scene.parts[0].state.name.endswith("_stairs")


def test_thin_sections_and_mimic_host_survive():
    t = np.eye(4)
    thin = Part("plate", "box", (1, 0.125, 4), t, "Metal", (0.5, 0.5, 0.5))
    assert len(voxelize(Scene([thin], "blueprint"))[0]) == 4
    bp = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_text())
    bp["Blueprint"]["Decorations"] = [{"appearance": "ignored"}]
    scene = read_blueprint(json.dumps(bp).encode())
    assert len(scene.parts) == 4
    assert any("decoration" in k for k in scene.notices)


def test_axis_aligned_half_height_uses_target_slab():
    part = Part("half height", "box", (1, 0.5, 1), np.eye(4), "Stone", (0.5, 0.5, 0.5))
    result = convert(Scene([part], "blueprint"), "nbt")
    assert result.scene.parts[0].state.name.endswith("_slab")
    assert dict(result.scene.parts[0].state.properties)["type"] == "bottom"


def test_glass_slope_preserves_transparency_when_vanilla_has_no_glass_stair():
    part = Part("glass slope", "wedge", (1, 1, 1), np.eye(4), "Glass", (0.5, 0.8, 0.8), True)
    result = convert(Scene([part], "blueprint"), "nbt")
    assert all(part.transparent for part in result.scene.parts)
    assert any("glass slabs" in message for message in result.notices)


def test_long_wedge_keeps_thin_leading_section():
    part = Part("sloped beam", "wedge", (1, 1, 4), np.eye(4), "Metal", (0.5, 0.5, 0.5))
    cells, _ = voxelize(Scene([part], "blueprint"))
    assert {position[2] for position in cells} == {0, 1, 2, 3}


def test_all_vanilla_ids_have_honest_policy_and_rotations_are_proper():
    assert len(BLOCKS) == 1060
    assert {mc_policy(k)[0] for k in BLOCKS} <= {"mapped", "approximated", "skipped"}
    assert mc_policy("minecraft:tnt")[0] == "approximated"
    assert mc_policy("mod:unknown")[0] == "unrecognized"
    for i in range(24):
        assert np.linalg.det(rotation(i)) == 1
    assert all("SizeId" in entry or "Footprint" in entry for entry in CATALOG.values())


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_half_parts_form_a_solid_cell_regardless_of_order(reverse):
    lower = Part("lower", "box", (1, 0.5, 1), np.eye(4), "Metal", (0.6, 0.1, 0.1))
    transform = np.eye(4)
    transform[1, 3] = 0.5
    upper = Part("upper", "box", (1, 0.5, 1), transform, "Metal", (0.6, 0.1, 0.1))
    cells, _ = voxelize(Scene([upper, lower] if reverse else [lower, upper], "blueprint"))
    assert cells[(0, 0, 0)].shape == "box"


@pytest.mark.parametrize("orientation", range(24))
def test_detailed_long_slope_uses_gradual_layers_without_full_end_caps(orientation):
    from fromthecraft.copycats import geometry_boxes

    transform = np.eye(4)
    transform[:3, :3] = rotation(orientation)
    slope = Part("long slope", "ftd_slope", (1, 1, 4), transform, "Metal", (0.6, 0.1, 0.1))
    cells, offset = voxelize(Scene([slope], "blueprint"), detailed=True)
    assert len(cells) == 4
    ordered = sorted(
        cells.items(), key=lambda item: ((np.asarray(item[0]) + offset + 0.5) @ transform[:3, :3])[2]
    )
    volumes = [
        sum(np.prod(np.asarray(box[3:]) - box[:3]) for _, box in geometry_boxes(part.state))
        for _, part in ordered
    ]
    np.testing.assert_allclose(volumes, [7 / 8, 5 / 8, 3 / 8, 1 / 8], atol=1 / 16)
    assert all(0 < volume < 1 for volume in volumes)


def test_detailed_full_wall_union_stays_full():
    lower = Part("lower", "box", (1, 0.5, 1), np.eye(4), "Metal", (0.6, 0.1, 0.1))
    transform = np.eye(4)
    transform[1, 3] = 0.5
    upper = Part("upper", "box", (1, 0.5, 1), transform, "Metal", (0.6, 0.1, 0.1))
    cells, _ = voxelize(Scene([lower, upper], "blueprint"), detailed=True)
    assert cells[(0, 0, 0)].shape == "box"
