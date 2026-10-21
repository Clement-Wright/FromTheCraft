import json


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


def test_mesh_metadata_follows_valid_overrides_and_duplicate_inheritance(tmp_path):
    from fromthecraft.catalog import installed_catalog

    items = tmp_path / "Mods/Core_Structural/Items"
    duplicates = tmp_path / "Mods/Core_Structural/ItemDup"
    items.mkdir(parents=True)
    duplicates.mkdir()
    base = {
        "ComponentId": {"Guid": "base", "Name": "Metal Block"},
        "SizeInfo": {"SizePos": dict(x=0, y=0, z=0), "SizeNeg": dict(x=0, y=0, z=0)},
        "MeshReference": {
            "Reference": {"Guid": "base-mesh", "Name": "Wood down slope (1m)"},
            "IsValidReference": True,
        },
    }
    (items / "base.item").write_text(json.dumps(base))
    for guid, parent, mesh in [
        ("unchanged", "base", None),
        ("invalid", "base", (False, "Ignored invalid mesh")),
        ("changed", "base", (True, "Wood triangle corner (right) (1m)")),
        ("descendant", "changed", None),
    ]:
        variant = {
            "ComponentId": {"Guid": guid, "Name": "Same misleading item name"},
            "IdToDuplicate": {"Reference": {"Guid": parent}},
        }
        if mesh is not None:
            valid, name = mesh
            variant["MeshReference"] = {
                "Reference": {"Guid": "replacement-mesh", "Name": name},
                "IsValidReference": valid,
            }
        (duplicates / f"{guid}.itemduplicateandmodify").write_text(json.dumps(variant))

    entries, info = installed_catalog(tmp_path, {})
    assert info["issues"] == []
    assert entries["base"]["MeshName"] == "Wood down slope (1m)"
    assert entries["unchanged"]["MeshName"] == entries["base"]["MeshName"]
    assert entries["invalid"]["MeshName"] == entries["base"]["MeshName"]
    assert entries["changed"]["MeshName"] == "Wood triangle corner (right) (1m)"
    assert entries["descendant"]["MeshName"] == entries["changed"]["MeshName"]


def test_installed_mesh_metadata_disambiguates_mislabeled_transition_items():
    import pytest
    from fromthecraft.catalog import game_assets, installed_catalog

    root = game_assets()
    if not (root / "Mods/Core_Structural").is_dir():
        pytest.skip("Local FtD installation unavailable; game assets are not redistributed")
    entries, _ = installed_catalog(root, {})
    assert entries["3a42ac8c-2c51-429c-a375-5d0f2c41742e"]["MeshName"] == (
        "wood 2m to 3m slope transition left"
    )
    assert entries["c5550009-2b37-41ff-a788-d413b39376ae"]["MeshName"] == (
        "wood 2m to 3m slope transition right"
    )
    assert entries["d6b944ee-04fc-411c-9d22-935d5f4b2440"]["MeshName"] == (
        "wood 2m square backed corner right"
    )


def test_real_installed_ftd_fixtures_and_ordinary_output_ids():
    import pytest
    from fromthecraft.catalog import game_assets
    from fromthecraft.convert import convert
    from fromthecraft.ftd import CATALOG, read_blueprint

    root = game_assets()
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
