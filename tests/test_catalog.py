import json
from pathlib import Path


def test_installed_metadata_resolves_variant_footprint_without_meshes(tmp_path):
    from fromthecraft.catalog import installed_catalog

    items = tmp_path / "Mods/Core_Structural/Items"
    duplicates = tmp_path / "Mods/Core_Structural/ItemDup"
    items.mkdir(parents=True)
    duplicates.mkdir()
    base = {
        "ComponentId": {"Guid": "base", "Name": "Metal Block"},
        "SizeInfo": {"SizePos": dict(x=0, y=0, z=0), "SizeNeg": dict(x=0, y=0, z=0)},
        "LowLevelOfDetailColor": "0.2,0.3,0.4,1",
    }
    variant = {
        "ComponentId": {"Guid": "beam", "Name": "Metal beam (4m)"},
        "IdToDuplicate": {"Reference": {"Guid": "base"}},
        "change_SizeInfo": True,
        "SizeInfo": {"SizePos": dict(x=0, y=0, z=3), "SizeNeg": dict(x=0, y=0, z=0)},
    }
    (items / "base.item").write_text(json.dumps(base))
    (duplicates / "beam.itemduplicateandmodify").write_text(json.dumps(variant))
    entries, info = installed_catalog(tmp_path, {})
    assert entries["beam"]["Footprint"] == dict(xn=0, xp=0, yn=0, yp=0, zn=0, zp=3)
    assert entries["beam"]["Material"] == "Metal"
    assert entries["beam"]["DefaultColor"] == (0.2, 0.3, 0.4)
    assert info["entries"] == 2
    assert sorted(p.name for p in items.iterdir()) == ["base.item"]


def test_real_installed_ftd_fixtures_and_ordinary_output_ids():
    import pytest
    from fromthecraft.convert import convert
    from fromthecraft.ftd import CATALOG, read_blueprint

    root = Path(
        r"C:\Program Files (x86)\Steam\steamapps\common\From The Depths\From_The_Depths_Data\StreamingAssets"
    )
    if not root.exists():
        pytest.skip("Local FtD installation unavailable; game fixtures are not redistributed")
    source = root / "Blueprints/Guides/Examples/ABlock.blueprint"
    scene = read_blueprint(source.read_bytes())
    assert len(scene.parts) == 1
    assert tuple(scene.parts[0].transform[:3, 3]) == (0, 1, -6)
    marauder = root / "Blueprints/Neter/DWG/Marauder.blueprint"
    scene = read_blueprint(marauder.read_bytes())
    assert len(scene.parts) > 3000
    assert not any("Unrecognized" in key for key in scene.notices)
    assert CATALOG["830354c9-e41e-44f6-949d-9303dbb49982"]["Footprint"]["zn"] == 3
    result = convert(scene, "nbt")
    assert len(result.scene.parts) > 6000
