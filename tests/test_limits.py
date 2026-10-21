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
