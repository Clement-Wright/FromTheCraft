from pathlib import Path

import pytest

from fromthecraft.convert import read_file
from fromthecraft.edits import EditLayer
from fromthecraft.projects import export_project, import_project


def test_project_roundtrip_cursor_and_source_hash_validation():
    scene = read_file(Path("tests/fixtures/asymmetric.blueprint").read_bytes(), "blueprint")
    edits = EditLayer(scene)
    record = scene.parts[0].source_record.id
    edits.apply({"kind": "exclude", "ids": [record]})
    edits.apply({"kind": "hide", "ids": [record]})
    edits.undo()
    document = export_project(scene, edits, "original", {"format": "nbt"}, {})
    loaded, settings, view = import_project(document, scene)
    assert loaded.snapshot()["excluded"] == [record]
    assert loaded.snapshot()["hidden"] == []
    assert loaded.snapshot()["can_redo"]
    assert settings == {"format": "nbt"} and view == {}
    document["source"]["hash"] = "wrong"
    with pytest.raises(ValueError, match="hash"):
        import_project(document, scene)


@pytest.mark.parametrize("field,value", [("schema", 2), ("cursor", -1), ("commands", [{"kind": "unknown"}])])
def test_invalid_project_rejects_before_live_history_is_replaced(field, value):
    scene = read_file(Path("tests/fixtures/asymmetric.blueprint").read_bytes(), "blueprint")
    edits = EditLayer(scene)
    document = export_project(scene, edits, "original", {"format": "nbt"}, {})
    document[field] = value
    with pytest.raises(ValueError):
        import_project(document, scene)
    assert not edits.commands
