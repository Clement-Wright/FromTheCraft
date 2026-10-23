import io
import json
import struct
import zlib
import zipfile

import pytest

from fromthecraft.textures import TextureLibrary


def png(color=b"\xff\0\0\xff", width=1, height=1):
    def chunk(kind, content):
        return (
            struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + color * width) * height))
        + chunk(b"IEND", b"")
    )


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, value in files.items():
            zipped.writestr(name, json.dumps(value) if isinstance(value, dict) else value)
    return output.getvalue()


def cube(texture="example:block/red"):
    return {
        "textures": {"all": texture},
        "elements": [
            {
                "faces": {
                    face: {"texture": "#all"} for face in ("up", "down", "north", "south", "east", "west")
                }
            }
        ],
    }


def test_parent_texture_references_and_opaque_keys():
    library = TextureLibrary(discover=False)
    raw = png()
    library.add_archive(
        archive(
            {
                "assets/example/models/block/base.json": cube("#surface"),
                "assets/example/models/block/child.json": {
                    "parent": "example:block/base",
                    "textures": {"surface": "example:block/red"},
                },
                "assets/example/blockstates/child.json": {"variants": {"": {"model": "example:block/child"}}},
                "assets/example/textures/block/red.png": raw,
            }
        ),
        "original.zip",
    )
    faces = library.block_faces("example:child")
    assert set(faces) == {"up", "down", "north", "south", "east", "west"}
    assert len(set(faces.values())) == 1
    key = faces["up"]
    assert "/" not in key and "red" not in key
    assert library.image(key) == raw
    for unknown in ("../red.png", "assets/example/textures/block/red.png", "unknown"):
        with pytest.raises(KeyError):
            library.image(unknown)


def test_variants_properties_rotation_and_archive_overrides():
    library = TextureLibrary(discover=False)
    red, blue = png(), png(b"\0\0\xff\xff")
    library.add_archive(
        archive(
            {
                "assets/example/models/block/red.json": cube(),
                "assets/example/models/block/side.json": {
                    "textures": {"side": "example:block/blue"},
                    "elements": [{"faces": {"north": {"texture": "#side"}}}],
                },
                "assets/example/blockstates/beam.json": {
                    "variants": {
                        "axis=y": {"model": "example:block/red"},
                        "axis=x": {"model": "example:block/side", "y": 90},
                    }
                },
                "assets/example/textures/block/red.png": red,
                "assets/example/textures/block/blue.png": blue,
            }
        ),
        "models.jar",
    )
    old = library.block_faces("example:beam", (("axis", "y"),))["up"]
    assert library.image(old) == red
    assert library.image(library.block_faces("example:beam", {"axis": "x"})["east"]) == blue
    library.add_archive(archive({"assets/example/textures/block/red.png": blue}), "override.zip")
    new = library.block_faces("example:beam", (("axis", "y"),))["up"]
    assert library.image(new) == blue
    assert library.image(old) == red


def test_missing_assets_cycles_and_invalid_images_do_not_invent_textures():
    library = TextureLibrary(discover=False)
    library.add_archive(
        archive(
            {
                "assets/example/models/block/missing.json": cube(),
                "assets/example/models/block/cycle.json": {"parent": "example:block/cycle"},
                "assets/example/textures/block/red.png": b"not a PNG",
            }
        ),
        "bad-models.zip",
    )
    assert library.block_faces("example:missing") == {}
    assert library.block_faces("example:cycle") == {}
    assert library.block_faces("example:unknown") == {}
    assert library.ftd_face("Metal") is None
    assert library.status()["available"] is False


def test_archive_limits_reject_atomically(monkeypatch):
    import fromthecraft.textures as textures

    library = TextureLibrary(discover=False)
    with pytest.raises(ValueError):
        library.add_archive(b"not zip", "invalid.zip")
    with pytest.raises(ValueError):
        library.add_archive(archive({"../escape.png": png()}), "traversal.zip")
    monkeypatch.setattr(textures, "MAX_ARCHIVE_BYTES", 32)
    with pytest.raises(ValueError, match="archive"):
        library.add_archive(archive({"data": b"a" * 80}), "large.zip")
    monkeypatch.setattr(textures, "MAX_ARCHIVE_BYTES", 128 * 1024**2)
    monkeypatch.setattr(textures, "MAX_EXPANDED_BYTES", 64)
    with pytest.raises(ValueError, match="expanded"):
        library.add_archive(archive({"data": b"a" * 80}), "bomb.zip")
    monkeypatch.setattr(textures, "MAX_EXPANDED_BYTES", 512 * 1024**2)
    monkeypatch.setattr(textures, "MAX_MEMBERS", 1)
    with pytest.raises(ValueError, match="members"):
        library.add_archive(archive({"a": b"a", "b": b"b"}), "many.zip")
    assert library.status()["sources"] == []


def test_png_dimension_limit():
    library = TextureLibrary(discover=False)
    library.add_archive(
        archive(
            {
                "assets/example/models/block/large.json": cube("example:block/large"),
                "assets/example/textures/block/large.png": png(width=2049),
            }
        ),
        "oversized-image.zip",
    )
    assert library.block_faces("example:large") == {}


def test_png_encoded_dimensions_cannot_hide_an_expansion_bomb():
    library = TextureLibrary(discover=False)
    library.add_archive(
        archive(
            {
                "assets/example/models/block/bomb.json": cube("example:block/bomb"),
                "assets/example/textures/block/bomb.png": png(color=b"x" * 100_000),
            }
        ),
        "image-bomb.zip",
    )
    assert library.block_faces("example:bomb") == {}
    assert not library.status()["available"]


def test_corrupt_png_zlib_payload_and_archive_aggregate_limits(monkeypatch):
    import fromthecraft.textures as textures

    library = TextureLibrary(discover=False)
    broken = png().replace(zlib.compress(b"\0\xff\0\0\xff"), b"x" * len(zlib.compress(b"\0\xff\0\0\xff")))
    library.add_archive(archive({"assets/example/textures/block/broken.png": broken}), "broken.zip")
    assert not library.status()["available"]
    content = archive({"asset": b"small"})
    monkeypatch.setattr(textures, "MAX_ARCHIVE_BYTES", len(content) * 2 - 1)
    library = TextureLibrary(discover=False)
    library.add_archive(content, "first.zip")
    with pytest.raises(ValueError, match="archive"):
        library.add_archive(content, "second.zip")
    assert len(library.status()["sources"]) == 1


@pytest.mark.parametrize(
    "payload", [None, [], {"elements": 3}, {"textures": [], "elements": [None, 1, {"faces": []}]}]
)
def test_malformed_model_metadata_is_missing_not_an_exception(payload):
    library = TextureLibrary(discover=False)
    library.add_archive(
        archive({"assets/example/models/block/broken.json": json.dumps(payload)}), "broken.zip"
    )
    assert library.block_faces("example:broken") == {}


def test_model_inheritance_cache_and_texture_maps_stay_bounded():
    library = TextureLibrary(discover=False)
    files = {"assets/example/models/block/base.json": cube()}
    files.update(
        {f"assets/example/models/block/child_{i}.json": {"parent": "example:block/base"} for i in range(600)}
    )
    files["assets/example/models/block/too_many.json"] = {
        "textures": {f"slot{i}": "example:block/red" for i in range(513)}
    }
    files["assets/example/models/block/too_long.json"] = {"textures": {"all": "x" * 513}}
    files["assets/example/textures/block/red.png"] = png()
    library.add_archive(archive(files), "many-models.zip")
    for i in range(600):
        assert library.block_faces(f"example:child_{i}")
    assert len(library._models) <= 512
    assert all(len(model["textures"]) <= 512 for model in library._models.values())
    assert library.block_faces("example:too_many") == {}
    assert library.block_faces("example:too_long") == {}


def test_local_discovery_uses_only_target_version_installed_mods_and_enabled_packs(tmp_path):
    root = tmp_path / ".minecraft"
    files = {"assets/example/models/block/red.json": cube(), "assets/example/textures/block/red.png": png()}
    vanilla = root / "versions/1.21.1/1.21.1.jar"
    vanilla.parent.mkdir(parents=True)
    vanilla.write_bytes(archive(files))
    mods = root / "mods"
    mods.mkdir()
    (mods / "installed.jar").write_bytes(
        archive({"assets/example/textures/block/red.png": png(b"\0\xff\0\xff")})
    )
    packs = root / "resourcepacks"
    packs.mkdir()
    blue = png(b"\0\0\xff\xff")
    (packs / "chosen.zip").write_bytes(archive({"assets/example/textures/block/red.png": blue}))
    (packs / "disabled.zip").write_bytes(archive({"assets/example/textures/block/red.png": png()}))
    (root / "options.txt").write_text('resourcePacks:["vanilla","file/chosen.zip"]', encoding="utf-8")
    research = tmp_path / "research/mod-compat"
    research.mkdir(parents=True)
    (research / "not-installed.jar").write_bytes(archive({"assets/example/textures/block/red.png": png()}))
    library = TextureLibrary(minecraft_root=root, ftd_root=tmp_path / "missing-ftd")
    key = library.block_faces("example:red")["up"]
    assert library.image(key) == blue
    sources = library.status()["sources"]
    assert [item["name"] for item in sources] == ["1.21.1.jar", "installed.jar", "chosen.zip"]
    assert [item["kind"] for item in sources] == ["vanilla", "mod", "resourcepack"]


def test_ftd_material_guid_reference_reads_only_actual_local_png(tmp_path):
    core = tmp_path / "Mods/Core_Structural"
    (core / "Materials").mkdir(parents=True)
    (core / "Textures").mkdir()
    material = {
        "ComponentId": {"Name": "metal mat"},
        "ColorTextureReference": {"IsValidReference": True, "Reference": {"Guid": "color-id"}},
    }
    (core / "Materials/metal.material").write_text(json.dumps(material))
    texture = {
        "ComponentId": {"Guid": "color-id"},
        "Source": 2,
        "FilenameOrUrl": "Triplanar/Metal/T_Base_Color.png",
    }
    (core / "Textures/color.texture").write_text(json.dumps(texture))
    library = TextureLibrary(minecraft_root=tmp_path / "missing-mc", ftd_root=tmp_path)
    assert library.ftd_face("Metal") is None
    assert "Triplanar/Metal/T_Base_Color.png" in " ".join(library.status()["ftd"]["reasons"])
    image_path = tmp_path / "Triplanar/Metal/T_Base_Color.png"
    image_path.parent.mkdir(parents=True)
    raw = png()
    image_path.write_bytes(raw)
    library = TextureLibrary(minecraft_root=tmp_path / "missing-mc", ftd_root=tmp_path)
    assert library.image(library.ftd_face("Metal")) == raw


def test_ftd_unity_resource_images_are_issued_as_opaque_keys(tmp_path, monkeypatch):
    from fromthecraft import ftd_textures

    core = tmp_path / "Mods/Core_Structural"
    (core / "Materials").mkdir(parents=True)
    (core / "Textures").mkdir()
    (core / "Materials/wood.material").write_text(
        json.dumps(
            {
                "ComponentId": {"Name": "wood mat"},
                "ColorTextureReference": {"IsValidReference": True, "Reference": {"Guid": "wood-color"}},
            }
        )
    )
    relative = "Standard/Wood/T_Base_Color.png"
    (core / "Textures/wood.texture").write_text(
        json.dumps(
            {
                "ComponentId": {"Guid": "wood-color"},
                "Source": 2,
                "FilenameOrUrl": relative,
            }
        )
    )
    raw = png()

    def extract(path, wanted):
        assert path == tmp_path.parent
        assert wanted == {relative}
        return {relative: raw}

    monkeypatch.setattr(ftd_textures, "extract_base_colors", extract)
    library = TextureLibrary(minecraft_root=tmp_path / "missing-mc", ftd_root=tmp_path)
    assert library.image(library.ftd_face("Wood")) == raw
    assert library.status()["ftd"]["available"]
    assert not library.status()["ftd"]["reasons"]
    assert library.status()["ftd"]["sources"] == [
        {"name": "From the Depths Unity Resources", "kind": "ftd", "assets": 1}
    ]


def test_gui_only_mod_images_do_not_claim_block_texture_availability():
    library = TextureLibrary(discover=False)
    library.add_archive(archive({"assets/example/textures/gui/icon.png": png()}), "gui-mod.jar")
    assert not library.status()["minecraft"]["available"]


def test_inherited_client_and_mod_assets_are_discovered_without_fixed_jar_name(tmp_path):
    versions = tmp_path / "versions"
    parent = versions / "client-custom"
    child = versions / "neoforge-pack"
    parent.mkdir(parents=True)
    child.mkdir()
    (parent / "client-custom.json").write_text(
        json.dumps(
            {
                "id": "client-custom",
                "releaseTime": "2024-08-08",
                "downloads": {"client": {"sha1": "30c73b1c5da787909b2f73340419fdf13b9def88"}},
            }
        )
    )
    (child / "neoforge-pack.json").write_text(
        json.dumps({"id": "neoforge-pack", "inheritsFrom": "client-custom"})
    )
    (parent / "client-custom.jar").write_bytes(
        archive(
            {
                "assets/minecraft/models/block/cube_all.json": cube("#all"),
                "assets/minecraft/textures/block/stone.png": png(),
            }
        )
    )
    mods = tmp_path / "mods"
    mods.mkdir()
    blue = png(b"\0\0\xff\xff")
    (mods / "mod.jar").write_bytes(
        archive(
            {
                "assets/example/models/block/paint.json": {
                    "parent": "minecraft:block/cube_all",
                    "textures": {"all": "example:block/paint"},
                },
                "assets/example/textures/block/paint.png": blue,
            }
        )
    )
    library = TextureLibrary(minecraft_root=tmp_path, ftd_root=tmp_path / "missing")
    faces = library.block_faces("example:paint")
    assert len(faces) == 6
    assert library.image(faces["up"]) == blue
    assert {s["kind"] for s in library.status()["sources"]} == {"vanilla", "mod"}


def test_incompatible_and_unsafe_inheritance_cannot_supply_client_assets(tmp_path):
    for name, manifest in [
        ("wrong", {"id": "wrong", "inheritsFrom": "1.20.1"}),
        ("unsafe", {"id": "unsafe", "inheritsFrom": "../../outside"}),
        ("cycle", {"id": "cycle", "inheritsFrom": "cycle"}),
    ]:
        folder = tmp_path / "versions" / name
        folder.mkdir(parents=True)
        (folder / (name + ".json")).write_text(json.dumps(manifest))
        (folder / (name + ".jar")).write_bytes(archive({"assets/example/textures/block/red.png": png()}))
    library = TextureLibrary(minecraft_root=tmp_path, ftd_root=tmp_path / "missing")
    assert not library.status()["minecraft"]["available"]


def test_mod_resource_override_changes_one_face_and_preserves_inherited_faces():
    library = TextureLibrary(discover=False)
    red, blue = png(), png(b"\0\0\xff\xff")
    library.add_archive(
        archive(
            {
                "assets/base/models/block/cube.json": {
                    "textures": {"side": "base:block/red", "top": "base:block/red"},
                    "elements": [{"faces": {"up": {"texture": "#top"}, "north": {"texture": "#side"}}}],
                },
                "assets/base/textures/block/red.png": red,
                "assets/example/models/block/paint.json": {
                    "parent": "base:block/cube",
                    "textures": {"top": "example:block/top"},
                },
                "assets/example/textures/block/top.png": blue,
            }
        ),
        "mod.jar",
    )
    faces = library.block_faces("example:paint")
    assert library.image(faces["up"]) == blue
    assert library.image(faces["north"]) == red


def test_unqualified_mod_model_parent_uses_the_minecraft_namespace():
    library = TextureLibrary(discover=False)
    library.add_archive(
        archive(
            {
                "assets/minecraft/models/block/cube_all.json": cube("#all"),
                "assets/minecraft/textures/block/stone.png": png(),
                "assets/example/models/block/paint.json": {
                    "parent": "block/cube_all",
                    "textures": {"all": "block/stone"},
                },
            }
        ),
        "mod.zip",
    )
    assert len(library.block_faces("example:paint")) == 6


def test_pinned_compatible_mod_set_fits_the_bounded_texture_library():
    from pathlib import Path
    from fromthecraft.compatibility import BUILDING_BLOCKS

    folder = Path("research/mod-compat")
    jars = list(folder.glob("*.jar"))
    if len(jars) < 8:
        pytest.skip("Local pinned compatibility JARs required")
    library = TextureLibrary(discover=False)
    for path in sorted(jars, key=lambda p: p.name != "minecraft-1.21.1-client.jar"):
        library.add_archive(path.read_bytes(), path.name)
    for name in (
        "minecraft:red_concrete",
        "create:cut_scorchia",
        "chipped:white_concrete_bricks",
        "dndecor:cut_dolomite",
        "createdeco:industrial_iron_sheet_metal",
    ):
        block = BUILDING_BLOCKS.get(name)
        faces = library.block_faces(name, block.get("properties", {}) if block else {})
        assert len(faces) == 6, name
        assert all(library.image(key).startswith(b"\x89PNG") for key in faces.values())


def test_multipart_conditions_and_texture_reference_cycle():
    library = TextureLibrary(discover=False)
    library.add_archive(
        archive(
            {
                "assets/example/models/block/base.json": cube(),
                "assets/example/models/block/cycle.json": {
                    "textures": {"a": "#b", "b": "#a"},
                    "elements": [{"faces": {"up": {"texture": "#a"}}}],
                },
                "assets/example/blockstates/multi.json": {
                    "multipart": [
                        {
                            "when": {"OR": [{"facing": "north|south"}, {"powered": "true"}]},
                            "apply": {"model": "example:block/base"},
                        }
                    ]
                },
                "assets/example/textures/block/red.png": png(),
            }
        ),
        "multipart.zip",
    )
    assert library.block_faces("example:multi", {"facing": "north"})
    assert not library.block_faces("example:multi", {"facing": "east"})
    assert not library.block_faces("example:cycle")
