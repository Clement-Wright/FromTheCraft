import gzip
import io

import nbtlib as nbt
import pytest
from litemapy import BlockState, Region, Schematic

from fromthecraft.minecraft import read_litematic, read_structure, write_litematic, write_structure
from fromthecraft.model import State
from fromthecraft.palettes import validate_state


def source_file(name, properties, format):
    """Author source NBT independently of the generated-output validators."""
    if format == "nbt":
        root = nbt.File(
            {
                "DataVersion": nbt.Int(3955),
                "size": nbt.List[nbt.Int]([1, 1, 1]),
                "palette": nbt.List[nbt.Compound](
                    [
                        nbt.Compound(
                            {
                                "Name": nbt.String(name),
                                "Properties": nbt.Compound(
                                    {key: nbt.String(value) for key, value in properties.items()}
                                ),
                            }
                        )
                    ]
                ),
                "blocks": nbt.List[nbt.Compound](
                    [nbt.Compound({"pos": nbt.List[nbt.Int]([0, 0, 0]), "state": nbt.Int(0)})]
                ),
                "entities": nbt.List[nbt.Compound](),
            }
        )
    else:
        region = Region(0, 0, 0, 1, 1, 1)
        region[0, 0, 0] = BlockState(name, **properties)
        root = nbt.File(Schematic(regions={"source": region}, mc_version=3955).to_nbt())
    stream = io.BytesIO()
    root.write(stream)
    return gzip.compress(stream.getvalue())


@pytest.mark.parametrize("format,reader", [("nbt", read_structure), ("litematic", read_litematic)])
def test_createdeco_sheet_metal_imports_actual_nonvisual_connection_properties(format, reader):
    # Atlas v16 saves these four ConnectedPillarBlock Boolean properties. They
    # are absent from the model variants because they affect connected textures.
    properties = {"axis": "y", "north": "false", "south": "false", "east": "false", "west": "false"}
    scene = reader(source_file("createdeco:industrial_iron_sheet_metal", properties, format))
    assert len(scene.parts) == 1
    assert scene.parts[0].size == (1, 1, 1)
    assert dict(scene.parts[0].state.properties) == properties
    assert not any("Approximated mod state" in message for message in scene.notices)
    validate_state(scene.parts[0].state)


@pytest.mark.parametrize("format,reader", [("nbt", read_structure), ("litematic", read_litematic)])
def test_newer_mod_properties_are_reported_without_losing_verified_stair_orientation(format, reader):
    properties = {
        "facing": "east",
        "half": "top",
        "shape": "outer_left",
        "waterlogged": "false",
        "new_finish": "ribbed",
    }
    scene = reader(source_file("createdeco:scarlet_brick_stairs", properties, format))
    part = scene.parts[0]
    assert dict(part.state.properties) == {
        "facing": "east",
        "half": "top",
        "shape": "outer_left",
        "waterlogged": "false",
    }
    assert part.shape == "stairs_outer_left"
    assert any(
        "Approximated mod state" in message and "new_finish=ribbed" in message for message in scene.notices
    )
    validate_state(part.state)


def test_invalid_mod_orientation_is_removed_and_reported_before_geometry_is_built():
    scene = read_structure(
        source_file(
            "createdeco:scarlet_brick_stairs", {"facing": "up", "half": "top", "shape": "straight"}, "nbt"
        )
    )
    assert dict(scene.parts[0].state.properties) == {"half": "top", "shape": "straight"}
    assert any("facing=up" in message for message in scene.notices)


def test_invalid_vanilla_source_states_still_fail_validation():
    with pytest.raises(ValueError, match="Invalid 1.21.1 state"):
        read_structure(source_file("minecraft:oak_stairs", {"facing": "up"}, "nbt"))


@pytest.mark.parametrize("writer", [write_structure, write_litematic])
def test_generated_mod_states_remain_strict(writer):
    with pytest.raises(ValueError, match="Invalid verified mod state"):
        writer({(0, 0, 0): State("createdeco:scarlet_brick_stairs", (("new_finish", "ribbed"),))}, (1, 1, 1))
