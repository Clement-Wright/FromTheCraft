import gzip
import io
import json
from pathlib import Path

import nbtlib
import pytest
from litemapy import BlockState, Region, Schematic

from fromthecraft.convert import convert
from fromthecraft.ftd import CATALOG, read_blueprint
from fromthecraft.minecraft import read_structure


def nbt_bytes(root):
    stream = io.BytesIO()
    nbtlib.File(root).write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)


@pytest.fixture
def mc_scene():
    region = Region(0, 0, 0, 3, 2, 2)
    region[0,0,0] = BlockState("minecraft:oak_planks")
    region[2,0,1] = BlockState("minecraft:red_stained_glass")
    region[1,1,0] = BlockState("minecraft:stone")
    return read_structure(nbt_bytes(region.to_structure_nbt(mc_version=3955)))


def test_reverse_writes_static_blueprint_with_valid_catalog_and_paint(mc_scene):
    result = convert(mc_scene, "blueprint")
    document = json.loads(result.content)
    bp = document["Blueprint"]
    assert len(bp["BLP"]) == len(bp["BLR"]) == len(bp["BCI"]) == len(bp["BlockIds"]) == 3
    assert not bp["SCs"]
    assert all(guid in CATALOG for guid in document["ItemDictionary"].values())
    assert all(0 <= i < len(bp["COL"]) for i in bp["BCI"])
    scene = read_blueprint(result.content)
    assert {p.material for p in scene.parts} == {"Wood", "Glass", "Stone"}
    assert next(p for p in scene.parts if p.material == "Glass").transparent


def test_litematic_signed_regions_offsets_and_air_do_not_erase():
    from fromthecraft.minecraft import read_litematic

    left = Region(-3, 1, -2, -2, 1, 1)
    left[-1,0,0] = BlockState("minecraft:oak_planks")
    left[0,0,0] = BlockState("minecraft:glass")
    right = Region(-3, 1, -2, 2, 1, 1)
    right[1,0,0] = BlockState("minecraft:stone")
    schematic = Schematic(regions={"left":left, "right":right}, mc_version=3955)
    scene = read_litematic(nbt_bytes(schematic.to_nbt()))
    assert {tuple(p.transform[:3,3]) for p in scene.parts} == {(-4,1,-2),(-3,1,-2),(-2,1,-2)}
    result = convert(scene, "blueprint")
    assert len(result.scene.parts) == 3


def test_litematic_export_uses_3955_and_library_can_read():
    scene = read_blueprint(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    result = convert(scene, "litematic")
    root = nbtlib.File.parse(io.BytesIO(gzip.decompress(result.content)))
    independent = Schematic.from_nbt(root)
    assert independent.mc_version == 3955
    region = next(iter(independent.regions.values()))
    assert region.count_blocks() == 7


def test_non_1211_input_is_not_silently_upgraded():
    region = Region(0,0,0,1,1,1)
    region[0,0,0] = BlockState("minecraft:stone")
    with pytest.raises(ValueError, match="1.21.1"):
        read_structure(nbt_bytes(region.to_structure_nbt(mc_version=2975)))


def test_unknown_modded_and_fluids_are_reported():
    region = Region(0,0,0,3,1,1)
    region[0,0,0] = BlockState("some_mod:machine")
    region[1,0,0] = BlockState("minecraft:water", level="0")
    region[2,0,0] = BlockState("minecraft:tnt")
    scene = read_structure(nbt_bytes(region.to_structure_nbt(mc_version=3955)))
    assert len(scene.parts) == 2
    assert any("Unrecognized" in k for k in scene.notices)
    assert any("fluid" in k for k in scene.notices)
    output = convert(scene, "blueprint")
    assert all("Mimic" not in p.identity for p in output.scene.parts)
