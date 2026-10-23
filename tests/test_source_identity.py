import json
from pathlib import Path

from fromthecraft.convert import read_file
from fromthecraft.minecraft import write_structure
from fromthecraft.model import State
from fromthecraft.preview import preview


def test_ftd_record_ids_are_stable_and_overlap_does_not_merge_records():
    doc = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    block = doc["Blueprint"]
    for key in ("BLP", "BLR", "BCI", "BlockIds"):
        block[key] = [block[key][1], block[key][1]]
    block["SCs"] = []
    raw = json.dumps(doc).encode()
    a, b = read_file(raw, "blueprint"), read_file(raw, "blueprint")
    assert a.source_hash == b.source_hash
    assert [p.source_record for p in a.parts] == [p.source_record for p in b.parts]
    assert a.parts[0].source_record.id != a.parts[1].source_record.id
    assert a.parts[0].source_record.type_key == a.parts[1].source_record.type_key
    display = preview(a)
    assert len(display["groups"][0]["source_ids"]) == 2
    assert len(display["blocks"]) == 1
    assert len(display["records"]) == 2


def test_decomposed_minecraft_record_keeps_one_source_identity():
    state = State("copycats:copycat_byte", (("bottom_northwest", "true"), ("top_southeast", "true")))
    raw = write_structure({(0, 0, 0): state}, (1, 1, 1))
    scene = read_file(raw, "nbt")
    assert len(scene.parts) == 2
    assert scene.parts[0].source_record == scene.parts[1].source_record
    assert scene.parts[0].source_record.type_key == state.name
    assert len(preview(scene)["records"]) == 1


def test_overlapping_litematic_regions_retain_independently_editable_records():
    import io
    from litemapy import Region, BlockState, Schematic

    a, b = Region(0, 0, 0, 1, 1, 1), Region(0, 0, 0, 1, 1, 1)
    a[0, 0, 0], b[0, 0, 0] = BlockState("minecraft:stone"), BlockState("minecraft:oak_planks")
    root = Schematic(regions={"first": a, "second": b}).to_nbt()
    root["MinecraftDataVersion"] = __import__("nbtlib").Int(3955)
    stream = io.BytesIO()
    __import__("nbtlib").File(root).write(stream)
    scene = read_file(stream.getvalue(), "litematic")
    assert len(scene.parts) == 2
    assert {p.source_record.parent_path for p in scene.parts} == {("Regions", "first"), ("Regions", "second")}
