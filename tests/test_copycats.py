import gzip
import io
from pathlib import Path

import nbtlib as nbt
import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.minecraft import parse_nbt, read_litematic, read_structure, write_litematic, write_structure
from fromthecraft.model import Part, Scene, State
from fromthecraft.preview import preview


@pytest.mark.parametrize("extension,reader", [("nbt", read_structure), ("litematic", read_litematic)])
def test_independently_authored_material_fixture(extension, reader):
    scene = reader(Path(f"tests/fixtures/copycats-materials.{extension}").read_bytes())
    assert [part.state.copied_material.name for part in scene.parts] == [
        "minecraft:red_concrete",
        "minecraft:glass",
        "minecraft:blue_concrete",
        "minecraft:cyan_stained_glass",
    ]
    assert [part.transparent for part in scene.parts] == [False, True, False, True]
    assert not scene.notices


@pytest.mark.parametrize("version", [5, 6, 7])
def test_current_litematic_versions_keep_static_copycat_materials(version):
    root = parse_nbt(Path("tests/fixtures/copycats-materials.litematic").read_bytes())
    root["Version"] = nbt.Int(version)
    root["SubVersion"] = nbt.Int(1)
    stream = io.BytesIO()
    root.write(stream)
    scene = read_litematic(gzip.compress(stream.getvalue()))
    assert scene.parts[0].state.copied_material == State("minecraft:red_concrete")


def test_copycat_stairs_write_material_and_consumed_item_outside_the_palette():
    state = State(
        "copycats:copycat_stairs",
        (("facing", "east"), ("half", "top"), ("shape", "straight"), ("waterlogged", "false")),
        copied_material=State("minecraft:red_concrete"),
    )
    root = parse_nbt(write_structure({(0, 0, 0): state}, (1, 1, 1)))
    assert set(root["palette"][0]) == {"Name", "Properties"}
    entity = root["blocks"][0]["nbt"]
    assert str(entity["id"]) == "copycats:copycat"
    assert str(entity["Material"]["Name"]) == "minecraft:red_concrete"
    assert entity["Item"] == nbt.Compound({"id": nbt.String("minecraft:red_concrete"), "count": nbt.Int(1)})
    assert isinstance(entity["EnableCT"], nbt.Byte)
    assert [int(entity[a]) for a in "xyz"] == [0, 0, 0]


@pytest.mark.parametrize("half", ["top", "bottom"])
@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_copycat_slab_multistate_schema_and_exact_reread(half, output):
    state = State(
        "copycats:copycat_slab",
        (("axis", "y"), ("type", half), ("waterlogged", "false")),
        copied_material=State("minecraft:blue_concrete"),
    )
    writer, reader = (
        (write_structure, read_structure) if output == "nbt" else (write_litematic, read_litematic)
    )
    content = writer({(1, 2, 3): state}, (2, 3, 4))
    root = parse_nbt(content)
    entity = root["blocks"][0]["nbt"] if output == "nbt" else root["Regions"]["Structure"]["TileEntities"][0]
    assert str(entity["id"]) == "copycats:multistate_copycat"
    data = entity["material_data"]
    assert str(data[half]["material"]["Name"]) == "minecraft:blue_concrete"
    assert str(data[half]["consumedItem"]["id"]) == "minecraft:blue_concrete"
    inactive = "bottom" if half == "top" else "top"
    assert str(data[inactive]["material"]["Name"]) == "create:copycat_base"
    assert not data[inactive]["consumedItem"]
    scene = reader(content)
    assert scene.parts[0].state == state
    assert scene.parts[0].color[2] > scene.parts[0].color[0]
    assert scene.parts[0].size == (1, 0.5, 1)
    assert not any("skipped block entity" in key for key in scene.notices)


def test_copycat_materials_share_palette_entry_but_keep_separate_inventory_rows():
    cells = {
        (x, 0, 0): State(
            "copycats:copycat_stairs",
            (("facing", "north"), ("half", "bottom"), ("shape", "straight"), ("waterlogged", "false")),
            copied_material=State(f"minecraft:{color}_concrete"),
        )
        for x, color in enumerate(["red", "blue", "red"])
    }
    content = write_structure(cells, (3, 1, 1))
    assert len(parse_nbt(content)["palette"]) == 1
    display = preview(read_structure(content))
    assert len(display["blocks"]) == 2
    assert sorted(row["count"] for row in display["materials"]) == [1, 2]
    assert {row["copied_material"]["name"] for row in display["materials"]} == {
        "minecraft:red_concrete",
        "minecraft:blue_concrete",
    }


@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_conversion_uses_copycat_shapes_only_when_enabled_and_can_convert_back(output):
    scene = Scene(
        [Part("red slope", "ftd_slope", (1, 1, 4), np.eye(4), "Metal", (0.65, 0.05, 0.05))], "blueprint"
    )
    vanilla = convert(scene, output, preference="color")
    result = convert(scene, output, preference="color", mods=("copycats",))
    assert not any(p.identity.startswith("copycats:") for p in vanilla.scene.parts)
    shapes = [p for p in result.scene.parts if p.identity.startswith("copycats:")]
    assert shapes
    assert all(p.state.copied_material.name == "minecraft:red_concrete" for p in shapes)
    assert all(p.color[0] > p.color[1] for p in result.scene.parts)
    reverse = convert(result.scene, "blueprint", scale=2)
    assert all(p.color[0] > p.color[1] for p in reverse.scene.parts)


def test_unknown_mod_selection_is_rejected_before_conversion():
    with pytest.raises(ValueError, match="Unknown installed mod"):
        convert(Scene([], "blueprint"), "nbt", mods=("invented-mod",))


def test_unrelated_block_entity_data_is_still_discarded():
    root = parse_nbt(write_structure({(0, 0, 0): State("minecraft:stone")}, (1, 1, 1)))
    root["blocks"][0]["nbt"] = nbt.Compound({"Command": nbt.String("ignored")})
    stream = io.BytesIO()
    root.write(stream)
    scene = read_structure(gzip.compress(stream.getvalue()))
    assert scene.parts[0].state.copied_material is None
    assert any("skipped block entity" in key for key in scene.notices)


@pytest.mark.parametrize("invalid", [nbt.List[nbt.String](["bad"]), nbt.String("bad"), nbt.Int(1)])
def test_malformed_copycat_properties_are_reported_without_crashing_import(invalid):
    root = parse_nbt(Path("tests/fixtures/copycats-materials.nbt").read_bytes())
    root["blocks"][0]["nbt"]["Material"]["Properties"] = invalid
    stream = io.BytesIO()
    root.write(stream)
    scene = read_structure(gzip.compress(stream.getvalue()))
    assert scene.parts[0].state.copied_material is None
    assert any("Copycat material could not be read" in key for key in scene.notices)


def test_negative_litematic_region_keeps_copycat_material_at_the_correct_block():
    from litemapy import BlockState, Region, Schematic, TileEntity

    region = Region(10, 0, 0, -2, 1, 1)
    region[-1, 0, 0] = BlockState(
        "copycats:copycat_stairs", facing="north", half="bottom", shape="straight", waterlogged="false"
    )
    region.tile_entities.append(
        TileEntity(
            nbt.Compound(
                {
                    "id": nbt.String("copycats:copycat"),
                    "x": nbt.Int(0),
                    "y": nbt.Int(0),
                    "z": nbt.Int(0),
                    "Material": nbt.Compound({"Name": nbt.String("minecraft:red_concrete")}),
                    "Item": nbt.Compound({"id": nbt.String("minecraft:red_concrete"), "count": nbt.Int(1)}),
                }
            )
        )
    )
    stream = io.BytesIO()
    nbt.File(Schematic(regions={"negative": region}, mc_version=3955).to_nbt()).write(stream)
    scene = read_litematic(gzip.compress(stream.getvalue()))
    assert len(scene.parts) == 1
    assert scene.parts[0].state.copied_material == State("minecraft:red_concrete")


def test_pinned_mod_palettes_are_opt_in_and_use_verified_states():
    from fromthecraft.compatibility import MODS, selected_mods
    from fromthecraft.palettes import mc_target, validate_state

    for slug, mod in MODS.items():
        for entry in mod["blocks"]:
            part = Part(entry["name"], "box", (1, 1, 1), np.eye(4), entry["material"], tuple(entry["rgb"]))
            assert mc_target(part, "color").name.startswith("minecraft:")
            target = mc_target(part, "color", selected_mods((slug,)))
            assert target.name == entry["name"]
            validate_state(target)
    assert set(selected_mods(("create-chipped",))) == {"create-chipped", "create", "chipped"}
    with pytest.raises(ValueError, match="Invalid verified mod state"):
        validate_state(State("copycats:copycat_stairs", (("facing", "up"),)))
