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
    assert all(p.state.copied_material == vanilla.scene.parts[0].state for p in shapes)
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
    from fromthecraft.palettes import mc_target, validate_state, mc_material

    for slug, mod in MODS.items():
        for entry in mod["blocks"]:
            part = Part(entry["name"], "box", (1, 1, 1), np.eye(4), entry["material"], tuple(entry["rgb"]))
            assert mc_target(part, "color").name.startswith("minecraft:")
            target = mc_target(part, "color", selected_mods((slug,)))
            np.testing.assert_allclose(mc_material(target.name)[1], entry["rgb"], atol=1e-6)
            validate_state(target)
    assert set(selected_mods(("create-chipped",))) == {"create-chipped", "create", "chipped"}
    with pytest.raises(ValueError, match="Invalid verified mod state"):
        validate_state(State("copycats:copycat_stairs", (("facing", "up"),)))


@pytest.mark.parametrize(
    "facing,axis,positive",
    [
        ("up", 1, False),
        ("down", 1, True),
        ("east", 0, False),
        ("west", 0, True),
        ("south", 2, False),
        ("north", 2, True),
    ],
)
@pytest.mark.parametrize("layers", range(1, 9))
def test_advanced_layers_preserve_exact_thickness_and_anchor(facing, axis, positive, layers):
    state = State(
        "copycats:copycat_layer",
        (("facing", facing), ("layers", str(layers))),
        copied_material=State("minecraft:blue_concrete"),
    )
    scene = read_structure(write_structure({(2, 3, 4): state}, (3, 4, 5)))
    assert not scene.notices
    assert len(scene.parts) == 1
    part = scene.parts[0]
    assert part.size[axis] == layers / 8
    assert all(part.size[i] == 1 for i in range(3) if i != axis)
    expected = np.array((2.0, 3.0, 4.0))
    expected[axis] += 1 - layers / 8 if positive else 0
    np.testing.assert_allclose(part.transform[:3, 3], expected)
    assert part.source_cell == (2, 3, 4)


def test_bytes_render_only_occupied_octants_and_pay_material_once():
    from fromthecraft.copycats import BYTE_SLOTS

    properties = tuple(
        (slot, str(slot in {"bottom_northwest", "top_southeast"}).lower()) for slot in BYTE_SLOTS
    )
    state = State("copycats:copycat_byte", properties, copied_material=State("minecraft:blue_concrete"))
    content = write_structure({(0, 0, 0): state}, (1, 1, 1))
    entity = parse_nbt(content)["blocks"][0]["nbt"]
    data = entity["material_data"]
    assert set(data) == set(BYTE_SLOTS)
    assert sum(bool(slot["consumedItem"]) for slot in data.values()) == 1
    assert all(isinstance(slot["enableCT"], nbt.Byte) for slot in data.values())
    scene = read_structure(content)
    assert not scene.notices
    assert len(scene.parts) == 2
    assert sum(np.prod(p.size) for p in scene.parts) == 0.25
    assert {p.material_slot for p in scene.parts} == {"bottom_northwest", "top_southeast"}
    assert all(p.source_cell == (0, 0, 0) for p in scene.parts)
    assert sorted(tuple(p.transform[:3, 3]) for p in scene.parts) == [(0.0, 0.0, 0.0), (0.5, 0.5, 0.5)]


@pytest.mark.parametrize("output", ["nbt", "litematic"])
def test_multimaterial_bytes_roundtrip_with_separate_appearance_and_shared_parent(output):
    red, glass = State("minecraft:red_concrete"), State("minecraft:glass")
    state = State(
        "copycats:copycat_byte",
        (("bottom_northwest", "true"), ("top_southeast", "true")),
        copied_materials=(("bottom_northwest", red), ("top_southeast", glass)),
    )
    writer, reader = (
        (write_structure, read_structure) if output == "nbt" else (write_litematic, read_litematic)
    )
    scene = reader(writer({(0, 0, 0): state}, (1, 1, 1)))
    assert not scene.notices
    assert len(scene.parts) == 2
    assert all(p.state == state for p in scene.parts)
    assert {p.transparent for p in scene.parts} == {False, True}
    assert {p.material_slot for p in scene.parts} == {"bottom_northwest", "top_southeast"}


@pytest.mark.parametrize(
    "name,properties,expected",
    [
        (
            "copycats:copycat_byte_panel",
            (("facing", "south"), ("bottom_left", "true")),
            (8, 0, 13, 16, 8, 16),
        ),
        ("copycats:copycat_byte_panel", (("facing", "north"), ("top_left", "true")), (0, 8, 0, 8, 16, 3)),
        ("copycats:copycat_byte_panel", (("facing", "up"), ("top_right", "true")), (0, 13, 0, 8, 16, 8)),
        ("copycats:copycat_half_panel", (("facing", "east"), ("offset", "east")), (13, 8, 0, 16, 16, 16)),
        ("copycats:copycat_half_panel", (("facing", "up"), ("offset", "north")), (0, 13, 0, 16, 16, 8)),
        ("create:copycat_panel", (("facing", "up"),), (0, 0, 0, 16, 3, 16)),
        ("create:copycat_step", (("facing", "east"), ("half", "top")), (8, 8, 0, 16, 16, 16)),
    ],
)
def test_advanced_panels_and_steps_have_verified_boxes(name, properties, expected):
    state = State(name, properties, copied_material=State("minecraft:blue_concrete"))
    scene = read_structure(write_structure({(0, 0, 0): state}, (1, 1, 1)))
    assert not scene.notices
    assert len(scene.parts) == 1
    part = scene.parts[0]
    low = part.transform[:3, 3]
    np.testing.assert_allclose(np.r_[low, low + part.size], np.array(expected) / 16)


@pytest.mark.parametrize("bad_key,bad_value", [("count", nbt.Byte(1)), ("enableCT", nbt.String("true"))])
def test_advanced_reader_rejects_wrong_nbt_primitive_types(bad_key, bad_value):
    state = State(
        "copycats:copycat_byte",
        (("bottom_northwest", "true"),),
        copied_material=State("minecraft:blue_concrete"),
    )
    root = parse_nbt(write_structure({(0, 0, 0): state}, (1, 1, 1)))
    slot = root["blocks"][0]["nbt"]["material_data"]["bottom_northwest"]
    if bad_key == "count":
        slot["consumedItem"][bad_key] = bad_value
    else:
        slot[bad_key] = bad_value
    stream = io.BytesIO()
    root.write(stream)
    scene = read_structure(stream.getvalue())
    assert scene.parts[0].state.copied_material is None
    assert not scene.parts[0].state.copied_materials
    assert any("Copycat material could not be read" in key for key in scene.notices)


def test_multistate_writer_rejects_material_attached_to_an_absent_part():
    state = State(
        "copycats:copycat_byte",
        (("bottom_northwest", "true"),),
        copied_materials=(("top_southeast", State("minecraft:red_concrete")),),
    )
    with pytest.raises(ValueError, match="occupied copycat parts"):
        write_structure({(0, 0, 0): state}, (1, 1, 1))


def test_multistate_reader_rejects_hidden_item_requirements_in_absent_parts():
    state = State(
        "copycats:copycat_byte",
        (("bottom_northwest", "true"),),
        copied_material=State("minecraft:blue_concrete"),
    )
    root = parse_nbt(write_structure({(0, 0, 0): state}, (1, 1, 1)))
    data = root["blocks"][0]["nbt"]["material_data"]
    data["top_southeast"] = nbt.Compound(data["bottom_northwest"])
    stream = io.BytesIO()
    root.write(stream)
    scene = read_structure(stream.getvalue())
    assert scene.parts[0].state.copied_material is None
    assert any("inactive copycat slot" in key for key in scene.notices)


def test_empty_byte_container_has_no_invisible_full_cell():
    scene = read_structure(write_structure({(0, 0, 0): State("copycats:copycat_byte")}, (1, 1, 1)))
    assert scene.parts == []


def test_expanded_copycat_parts_respect_the_scene_part_limit(monkeypatch):
    from fromthecraft import minecraft

    state = State(
        "copycats:copycat_byte",
        (("bottom_northwest", "true"), ("bottom_northeast", "true"), ("top_southeast", "true")),
    )
    content = write_structure({(0, 0, 0): state}, (1, 1, 1))
    monkeypatch.setattr(minecraft, "MAX_PARTS", 2)
    with pytest.raises(ValueError, match="render parts"):
        read_structure(content)


@pytest.mark.parametrize("material", ["copycats:unknown_copycat", "create:copycat_panel", "not a block ID"])
def test_copycat_writer_rejects_nested_or_invalid_material_identifiers(material):
    state = State("copycats:copycat_layer", copied_material=State(material))
    with pytest.raises(ValueError, match="copycat|identifier"):
        write_structure({(0, 0, 0): state}, (1, 1, 1))


@pytest.mark.parametrize(
    "name,properties,be_id,slots",
    [
        ("copycats:copycat_layer", (("layers", "3"),), "copycats:copycat", None),
        ("copycats:copycat_half_panel", (), "copycats:copycat", None),
        ("create:copycat_panel", (), "create:copycat", None),
        ("create:copycat_step", (), "create:copycat", None),
        (
            "copycats:copycat_byte",
            (("bottom_northwest", "true"),),
            "copycats:multistate_copycat",
            {
                "bottom_northwest",
                "bottom_northeast",
                "bottom_southwest",
                "bottom_southeast",
                "top_northwest",
                "top_northeast",
                "top_southwest",
                "top_southeast",
            },
        ),
        (
            "copycats:copycat_byte_panel",
            (("bottom_left", "true"),),
            "copycats:multistate_copycat",
            {"bottom_left", "bottom_right", "top_left", "top_right"},
        ),
    ],
)
def test_advanced_export_uses_pinned_block_entity_ids_and_slot_names(name, properties, be_id, slots):
    state = State(name, properties, copied_material=State("minecraft:blue_concrete"))
    entity = parse_nbt(write_structure({(0, 0, 0): state}, (1, 1, 1)))["blocks"][0]["nbt"]
    assert str(entity["id"]) == be_id
    if slots is None:
        assert str(entity["Material"]["Name"]) == "minecraft:blue_concrete"
        assert isinstance(entity["Item"]["count"], nbt.Int)
    else:
        assert set(entity["material_data"]) == slots
