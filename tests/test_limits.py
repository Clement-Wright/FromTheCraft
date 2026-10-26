import gzip
import struct

import pytest

from fromthecraft.minecraft import parse_nbt


@pytest.mark.parametrize(
    "content",
    [b"", b"not nbt", gzip.compress(b"not nbt"), b"\x0a\0\0\x09\0\x01a\x01" + struct.pack(">i", 2**31 - 1)],
)
def test_malformed_nbt_is_an_actionable_value_error(content):
    with pytest.raises(ValueError):
        parse_nbt(content)


def test_nested_nbt_is_bounded_before_library_parse():
    content = b"\x0a\0\0" + b"\x0a\0\x01x" * 70 + b"\0" * 71
    with pytest.raises(ValueError, match="nesting"):
        parse_nbt(content)


def test_all_declared_integer_registry_states_are_valid():
    from fromthecraft.model import State
    from fromthecraft.palettes import BLOCKS, validate_state

    for name, entry in BLOCKS.items():
        for rule in entry["states"]:
            for value in rule.get("values", []):
                validate_state(State(name, ((rule["name"], value),)))


@pytest.mark.parametrize("root,items", [([], {}), ({}, []), (None, {})])
def test_blueprint_root_objects_are_validated(root, items):
    import json
    from fromthecraft.ftd import read_blueprint

    with pytest.raises(ValueError, match="object"):
        read_blueprint(json.dumps({"Blueprint": root, "ItemDictionary": items}).encode())


def test_skipped_blocks_still_count_toward_input_limit(monkeypatch):
    import json
    import fromthecraft.ftd as ftd

    monkeypatch.setattr(ftd, "MAX_PARTS", 5)
    guid = next(guid for guid, entry in ftd.CATALOG.items() if "mimic" in entry["Name"].lower())
    child = dict(BLP=["0,0,0"] * 3, BLR=[0] * 3, BCI=[0] * 3, BlockIds=[0] * 3, SCs=[])
    root = dict(BLP=[], BLR=[], BCI=[], BlockIds=[], SCs=[child, child])
    with pytest.raises(ValueError, match="blocks"):
        ftd.read_blueprint(json.dumps({"Blueprint": root, "ItemDictionary": {"0": guid}}).encode())


def test_sparse_structure_can_use_a_billion_cell_bounding_volume():
    import numpy as np
    from fromthecraft.convert import convert
    from fromthecraft.model import Part, Scene

    far = np.eye(4)
    far[:3, 3] = (999, 999, 999)
    source = Scene([
        Part("near", "box", (1, 1, 1), np.eye(4), "Metal", (0.5, 0.5, 0.5)),
        Part("far", "box", (1, 1, 1), far, "Metal", (0.5, 0.5, 0.5)),
    ], "blueprint")
    result = convert(source, "nbt")
    assert len(result.scene.parts) == 2
    assert {tuple(p.transform[:3, 3]) for p in result.scene.parts} == {(0, 0, 0), (999, 999, 999)}


def test_bounding_volume_still_rejects_more_than_one_billion_cells():
    from fromthecraft.geometry import checked_size

    with pytest.raises(ValueError, match="bounding-volume"):
        checked_size((1001, 1000, 1000))


def test_large_sparse_bounds_and_axis_ceiling():
    from fromthecraft.geometry import checked_size

    assert checked_size((1000, 1000, 1000)) == (1000, 1000, 1000)
    assert checked_size((8192, 1, 1)) == (8192, 1, 1)
    with pytest.raises(ValueError, match="Dimensions"):
        checked_size((8193, 1, 1))


def nested_blueprint(depth):
    import json
    from fromthecraft.ftd import CUBE_IDS

    node = dict(BLP=["0,0,0"], BLR=[0], BCI=[0], BlockIds=[0], SCs=[])
    for _ in range(depth):
        node = dict(BLP=[], BLR=[], BCI=[], BlockIds=[], SCs=[node])
        node["SCs"][0]["LocalPosition"] = "1,0,0"
    return json.dumps({"Blueprint": node, "ItemDictionary": {"0": CUBE_IDS["Metal"]}}).encode()


@pytest.mark.parametrize("depth", [41, 128])
def test_deep_constructs_preserve_transforms_and_record_paths(depth):
    from fromthecraft.ftd import read_blueprint

    scene = read_blueprint(nested_blueprint(depth))
    assert len(scene.parts) == 1
    assert tuple(scene.parts[0].transform[:3, 3]) == (depth, 0, 0)
    expected_path = ("Blueprint",) + ("SCs", "0") * depth + ("blocks", "0")
    assert scene.parts[0].source_record.path == expected_path
    assert scene.parts[0].source_record.parent_path == expected_path[:-2]


def test_construct_nesting_remains_bounded():
    from fromthecraft.ftd import read_blueprint

    with pytest.raises(ValueError, match="nesting exceeds 128"):
        read_blueprint(nested_blueprint(129))


def test_larger_geometry_bounds_do_not_raise_the_nbt_list_length_guard():
    # A declared list length is checked before attempting to read its elements.
    content = b"\x0a\0\0\x09\0\x01a\x01" + struct.pack(">i", 8_000_001)
    with pytest.raises(ValueError, match="Invalid NBT list length"):
        parse_nbt(content)
