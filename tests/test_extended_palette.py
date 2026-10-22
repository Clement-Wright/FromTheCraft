"""Offline integrity checks for the expanded, texture-measured building palette."""

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/fromthecraft/data"
PALETTE = json.loads((DATA / "expanded_palette_1_21_1.json").read_text(encoding="utf-8"))
BLOCKS = {block["name"]: block for block in PALETTE["blocks"]}
VANILLA = {
    "minecraft:" + block["name"]: block
    for block in json.loads((DATA / "minecraft_1_21_1.json").read_text(encoding="utf-8"))["blocks"]
}


def test_expansion_has_broad_independent_coverage_without_duplicating_existing_blocks():
    assert len(BLOCKS) == len(PALETTE["blocks"]) == 735
    assert Counter(block["mod"] for block in BLOCKS.values()) == {
        "vanilla": 228,
        "create": 101,
        "create-design-n-decor": 152,
        "create-deco": 49,
        "create-chipped": 68,
        "chipped": 137,
    }
    original = json.loads((DATA / "mod_palette_1_21_1.json").read_text(encoding="utf-8"))
    assert not set(BLOCKS) & {block["name"] for mod in original["mods"] for block in mod["blocks"]}
    for color in "white orange magenta light_blue yellow lime pink gray light_gray cyan purple blue brown green red black".split():
        for family in ("concrete", "terracotta", "wool", "glazed_terracotta"):
            assert f"minecraft:{color}_{family}" in BLOCKS
    assert sum(block["material"] == "Wood" for block in BLOCKS.values()) >= 80


def test_vanilla_ids_and_complete_state_rules_match_the_existing_versioned_registry():
    for name, states in PALETTE["states"].items():
        if not name.startswith("minecraft:"):
            continue
        assert name in VANILLA
        registry_states = {
            rule["name"]: rule.get(
                "values",
                ["false", "true"] if rule["type"] == "bool" else [str(i) for i in range(rule["num_values"])],
            )
            for rule in VANILLA[name]["states"]
        }
        assert states == registry_states
    for name, block in BLOCKS.items():
        if name.startswith("minecraft:"):
            assert VANILLA[name]["boundingBox"] == "block"
            assert VANILLA[name]["transparent"] is False
        for key, value in block["properties"].items():
            assert value in PALETTE["states"][name][key]


def test_color_facts_distinguish_textures_instead_of_reusing_dye_constants():
    for name, expected in {
        "minecraft:red_concrete": [142, 33, 33],
        "minecraft:red_terracotta": [143, 61, 47],
        "minecraft:red_wool": [161, 39, 35],
        "minecraft:oak_planks": [162, 131, 79],
        "minecraft:stone": [126, 126, 126],
        "chipped:boxed_oak_planks": [150, 120, 71],
        "dndecor:amber_dark_metal_block": [158, 138, 54],
    }.items():
        assert BLOCKS[name]["rgb8"] == expected
    for block in BLOCKS.values():
        assert len(block["rgb"]) == 3
        assert all(0 <= value <= 1 for value in block["rgb"])
        # RGB is stored to six decimal places; a rounded half-byte may straddle .5.
        assert all(abs(byte - value * 255) <= 0.500128 for byte, value in zip(block["rgb8"], block["rgb"]))
    assert len({tuple(block["rgb8"]) for block in BLOCKS.values()}) >= 450


def test_shapes_have_explicit_state_rules_and_matching_namespace_evidence():
    shapes = set()
    for block in BLOCKS.values():
        for kind in ("stairs", "slab"):
            shape = block[kind]
            if shape is None:
                continue
            shapes.add(shape)
            namespace, identifier = shape.split(":", 1)
            assert namespace == block["name"].split(":", 1)[0]
            assert (
                block["evidence"][kind + "_blockstate"] == f"assets/{namespace}/blockstates/{identifier}.json"
            )
            rules = PALETTE["states"][shape]
            assert set(rules["waterlogged"]) == {"false", "true"}
            if kind == "stairs":
                assert set(rules) == {"facing", "half", "shape", "waterlogged"}
                assert set(rules["shape"]) == {
                    "straight",
                    "inner_left",
                    "inner_right",
                    "outer_left",
                    "outer_right",
                }
            else:
                assert set(rules) == {"type", "waterlogged"}
                assert set(rules["type"]) == {"top", "bottom", "double"}
    assert len(shapes) == 335
    assert set(PALETTE["states"]) == set(BLOCKS) | shapes


def test_sheet_metal_keeps_runtime_connection_properties_absent_from_visual_models():
    for name in ("dndecor:navy_sheet_metal", "dndecor:amber_sheet_metal", "createdeco:iron_sheet_metal"):
        rules = PALETTE["states"][name]
        assert set(rules) == {"axis", "north", "east", "south", "west"}
        assert set(rules["axis"]) == {"x", "y", "z"}
        for direction in ("north", "east", "south", "west"):
            assert set(rules[direction]) == {"false", "true"}


def test_every_block_records_pinned_source_and_asset_identifiers_only():
    sources = {source["slug"]: source for source in PALETTE["sources"]}
    for name, block in BLOCKS.items():
        source = sources[block["mod"]]
        assert len(source["sha512"]) == 128
        assert source["download_url"].startswith("https://")
        evidence = block["evidence"]
        assert evidence["jar"] == source["jar"]
        assert evidence["blockstate"].endswith(name.split(":", 1)[1] + ".json")
        assert evidence["models"] and evidence["texture_samples"]
        assert block["material"] in {"Stone", "Metal", "Wood"}
        if block["mod"] != "vanilla":
            assert "loot_table" in evidence or "block_tag" in evidence
    assert sources["vanilla"]["sha1"] == "30c73b1c5da787909b2f73340419fdf13b9def88"


def test_inspector_rejects_partial_tinted_and_cropped_models_without_reading_jars():
    spec = importlib.util.spec_from_file_location(
        "extended_inspector", ROOT / "scripts/inspect_extended_palettes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inspector = module.Inspector.__new__(module.Inspector)
    model = {
        "textures": {"all": "example:block/paint"},
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {direction: {"texture": "#all"} for direction in module.FACES},
            }
        ],
    }
    inspector.model = lambda identifier: model
    inspector.texture = lambda identifier: (120, 120, 120)
    assert inspector.cube("example:block/cube") == ["example:block/paint"] * 6
    model["elements"][0]["to"] = [16, 8, 16]
    with pytest.raises(AssertionError):
        inspector.cube("example:block/half")
    model["elements"][0]["to"] = [16, 16, 16]
    face = model["elements"][0]["faces"]["north"]
    face["tintindex"] = 0
    with pytest.raises(AssertionError, match="tinted"):
        inspector.cube("example:block/tinted")
    del face["tintindex"]
    face["uv"] = [0, 0, 8, 16]
    with pytest.raises(AssertionError, match="UV"):
        inspector.cube("example:block/cropped")


@pytest.mark.parametrize(
    "name", ["minecraft:red_terracotta", "minecraft:blue_wool", "minecraft:cherry_planks"]
)
def test_expanded_vanilla_colors_are_available_without_mods(name):
    import numpy as np

    from fromthecraft.model import Part
    from fromthecraft.palettes import mc_material, mc_target

    block = BLOCKS[name]
    part = Part(name, "box", (1, 1, 1), np.eye(4), block["material"], tuple(block["rgb"]))
    selected = mc_target(part, "color")
    assert selected.name.startswith("minecraft:")
    assert mc_material(selected.name)[1] == tuple(block["rgb"])


def test_expanded_mods_are_opt_in_and_native_shape_variants_keep_their_material():
    import numpy as np

    from fromthecraft.compatibility import BUILDING_BLOCKS, selected_mods
    from fromthecraft.model import Part
    from fromthecraft.palettes import mc_material, mc_target, validate_state

    entry = BLOCKS["dndecor:amber_dark_metal_block"]
    part = Part("amber metal", "box", (1, 1, 1), np.eye(4), "Metal", tuple(entry["rgb"]))
    assert mc_target(part, "material").name.startswith("minecraft:")
    assert mc_target(part, "material", selected_mods((entry["mod"],))).name == entry["name"]
    for block in BUILDING_BLOCKS.values():
        for shape, kind in (("step_west_top", "stairs"), ("slab_top", "slab")):
            if not block.get(kind):
                continue
            mods = (
                ()
                if block["name"].startswith("minecraft:")
                else selected_mods(
                    (
                        next(
                            source["slug"]
                            for source in PALETTE["sources"]
                            if source["namespace"] == block["name"].split(":", 1)[0]
                        ),
                    )
                )
            )
            part = Part("native family", shape, (1, 1, 1), np.eye(4), block["material"], tuple(block["rgb"]))
            target = mc_target(part, "material", mods)
            validate_state(target)
            # Equal-color families may tie; the shape must retain the chosen RGB.
            assert mc_material(target.name)[1] == tuple(block["rgb"])


def test_detailed_container_keeps_its_geometry_and_receives_selected_material():
    import numpy as np

    from fromthecraft.model import Part, State
    from fromthecraft.palettes import mc_target, validate_state

    geometry = State(
        "copycats:copycat_layer", (("facing", "east"), ("layers", "3"), ("waterlogged", "false"))
    )
    entry = BLOCKS["minecraft:red_terracotta"]
    part = Part("detail", "detailed", (1, 1, 1), np.eye(4), "Stone", tuple(entry["rgb"]), state=geometry)
    target = mc_target(part, "color", ("copycats",))
    assert target.name == geometry.name and target.properties == geometry.properties
    assert target.copied_material.name == entry["name"]
    validate_state(target)


def test_transparent_parts_stay_glass_with_expanded_opaque_palettes_enabled():
    import numpy as np

    from fromthecraft.compatibility import MODS, selected_mods
    from fromthecraft.model import Part
    from fromthecraft.palettes import mc_target

    part = Part("glass", "box", (1, 1, 1), np.eye(4), "Glass", (0.65, 0.05, 0.05), transparent=True)
    assert mc_target(part, "color", selected_mods(MODS)).name.endswith("_stained_glass")
