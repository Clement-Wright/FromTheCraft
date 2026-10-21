from fromthecraft.model import Part
from fromthecraft.palettes import mc_material, mc_target
import numpy as np


def test_wood_color_prefers_a_matching_ordinary_wood():
    part = Part("dark wood", "box", (1, 1, 1), np.eye(4), "Wood", (0.26, 0.17, 0.08))
    assert mc_target(part, "balanced").name == "minecraft:dark_oak_planks"
    assert mc_target(part, "color").name.endswith("_concrete")
    assert mc_material("minecraft:birch_planks")[1] != mc_material("minecraft:dark_oak_planks")[1]


def test_gold_is_an_inert_material_and_color_in_reverse():
    material, color = mc_material("minecraft:gold_block")
    assert material == "Metal"
    assert color[0] > color[2] and color[1] > color[2]
