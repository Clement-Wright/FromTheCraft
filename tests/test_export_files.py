from pathlib import Path

import pytest


def test_failed_atomic_save_preserves_existing_file_and_cleans_temporary(monkeypatch, tmp_path):
    from fromthecraft import exporting

    destination = tmp_path / "existing.nbt"
    destination.write_bytes(b"original")

    def denied(*_):
        raise PermissionError("Read-only folder")

    monkeypatch.setattr(exporting.os, "replace", denied)
    with pytest.raises(PermissionError):
        exporting.atomic_save(destination, b"converted")
    assert destination.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [destination]


def test_export_extension_and_unicode_default():
    from fromthecraft.exporting import export_filename

    assert export_filename("船 design", "blueprint", 3) == "船 design_converted_3x.blueprint"
    assert export_filename("ship", "litematic", .5) == "ship_converted.litematic"
    assert export_filename("ship", "blueprint", 1, "design.v2") == "design.v2.blueprint"
    assert Path(export_filename("ship", "nbt", 2, "custom.NBT")).suffix.lower() == ".nbt"
