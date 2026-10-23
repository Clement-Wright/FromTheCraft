from pathlib import Path

import pytest

from fromthecraft.convert import read_file, convert
from fromthecraft.edits import EditLayer


def scene():
    return read_file(Path("tests/fixtures/asymmetric.blueprint").read_bytes(), "blueprint")


def test_hide_and_exclude_are_separate_and_history_restores_whole_beam():
    source = scene()
    edits = EditLayer(source)
    beam = source.parts[1].source_record.id
    assert not edits.apply({"kind": "hide", "ids": [beam]})
    assert len(edits.derive(source).parts) == 4
    assert beam in edits.snapshot()["hidden"]
    assert edits.apply({"kind": "exclude", "ids": [beam]})
    assert len(edits.derive(source).parts) == 3
    assert edits.undo()
    assert len(edits.derive(source).parts) == 4
    assert beam in edits.snapshot()["hidden"]
    assert edits.redo()
    assert len(edits.derive(source).parts) == 3
    assert len(source.parts) == 4


def test_mapping_is_applied_before_fitting_and_restore_removes_override():
    source = scene()
    edits = EditLayer(source)
    record = source.parts[1].source_record
    edits.apply(
        {"kind": "mapping", "ids": [record.id], "mapping": {"name": "minecraft:gold_block", "properties": {}}}
    )
    result = convert(edits.derive(source), "nbt")
    assert any(p.state.name == "minecraft:gold_block" for p in result.scene.parts)
    edits.apply({"kind": "restore", "ids": [record.id]})
    assert not edits.snapshot()["mappings"]


def test_unknown_id_or_invalid_mapping_is_atomic():
    source = scene()
    edits = EditLayer(source)
    before = edits.snapshot()
    with pytest.raises(ValueError):
        edits.apply({"kind": "exclude", "ids": ["missing"]})
    with pytest.raises(ValueError):
        edits.apply(
            {
                "kind": "mapping",
                "ids": [source.parts[0].source_record.id],
                "mapping": {"name": "madeup:machine"},
            }
        )
    assert edits.snapshot() == before
