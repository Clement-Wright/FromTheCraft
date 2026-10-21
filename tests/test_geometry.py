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

    assert ftd_policy({"Name": "Metal down slope (1m)", "Material": "Metal"})[1] == "wedge"
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


def test_all_vanilla_ids_have_honest_policy_and_rotations_are_proper():
    assert len(BLOCKS) == 1060
    assert {mc_policy(k)[0] for k in BLOCKS} <= {"mapped", "approximated", "skipped"}
    assert mc_policy("minecraft:tnt")[0] == "approximated"
    assert mc_policy("mod:unknown")[0] == "unrecognized"
    for i in range(24):
        assert np.linalg.det(rotation(i)) == 1
    assert all("SizeId" in entry for entry in CATALOG.values())
