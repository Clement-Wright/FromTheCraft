from fromthecraft.model import Part
from fromthecraft.palettes import mc_material, mc_target
import numpy as np
import pytest


def test_wood_color_prefers_a_matching_ordinary_wood():
    part = Part("dark wood", "box", (1, 1, 1), np.eye(4), "Wood", (0.26, 0.17, 0.08))
    assert mc_target(part, "balanced").name == "minecraft:dark_oak_planks"
    assert mc_target(part, "color").name == "minecraft:dark_oak_planks"
    assert mc_material("minecraft:birch_planks")[1] != mc_material("minecraft:dark_oak_planks")[1]


def test_gold_is_an_inert_material_and_color_in_reverse():
    material, color = mc_material("minecraft:gold_block")
    assert material == "Metal"
    assert color[0] > color[2] and color[1] > color[2]


def test_balanced_preserves_dark_neutral_hull_paint():
    part = Part("dark hull", "box", (1, 1, 1), np.eye(4), "Metal", (0.08, 0.09, 0.13))
    assert max(mc_material(mc_target(part, "balanced").name)[1]) < 0.2
    assert mc_material(mc_target(part, "material").name)[0] == "Metal"


@pytest.mark.parametrize("shape", ["slab_bottom", "slab_top", "step_north_bottom", "step_west_top"])
@pytest.mark.parametrize("preference", ["balanced", "color", "material"])
def test_partial_metal_keeps_its_selected_material_when_no_matching_variant(shape, preference):
    from fromthecraft.palettes import mc_target_material

    part = Part("painted hull", shape, (1, 1, 1), np.eye(4), "Metal", (0.65, 0.05, 0.05))
    assert mc_target(part, preference) == mc_target_material(part, preference)


def test_color_first_wood_does_not_switch_back_to_unpainted_stairs():
    part = Part("painted wood", "step_south_top", (1, 1, 1), np.eye(4), "Wood", (0.65, 0.05, 0.05))
    assert mc_target(part, "color").name == "minecraft:red_wool"
    assert mc_material(mc_target(part, "material").name)[0] == "Wood"


def test_matching_stone_and_wood_variants_still_preserve_shape():
    stone = Part("stone", "slab_top", (1, 1, 1), np.eye(4), "Stone", (0.5, 0.5, 0.5))
    assert mc_target(stone, "material").name == "minecraft:cobblestone_slab"
    assert dict(mc_target(stone, "material").properties)["type"] == "top"


@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_serialized_painted_slope_contains_no_unrelated_stone(output):
    from fromthecraft.convert import convert
    from fromthecraft.model import Scene

    part = Part("red slope", "ftd_slope", (1, 1, 4), np.eye(4), "Metal", (0.65, 0.05, 0.05))
    result = convert(Scene([part], "blueprint"), output, preference="color")
    assert {p.state.name for p in result.scene.parts} == {mc_target(part, "color").name}
