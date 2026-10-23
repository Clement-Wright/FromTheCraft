import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import fromthecraft.app as module
    from fromthecraft.textures import TextureLibrary

    monkeypatch.setattr(module, "TextureLibrary", lambda: TextureLibrary(discover=False))
    app = module.app

    with TestClient(app) as client:
        session = client.get("/api/session").json()
        client.headers["X-FromTheCraft-Token"] = session["token"]
        yield client


def upload(client):
    return client.post(
        "/api/source",
        files={"file": ("asymmetric.blueprint", Path("tests/fixtures/asymmetric.blueprint").read_bytes())},
    )


def finished(client):
    for _ in range(150):
        status = client.get("/api/status").json()
        if status["state"] != "working":
            return status
        time.sleep(0.01)
    pytest.fail("Conversion did not finish")


def test_edit_exclusion_invalidates_export_but_visibility_preserves_it(client):
    source = upload(client).json()["source"]
    record = source["records"][1]["id"]
    client.post("/api/convert", json={"format": "nbt"})
    before = finished(client)
    hidden = client.post("/api/edits", json={"kind": "hide", "ids": [record]})
    assert hidden.status_code == 200
    assert client.get("/api/export", params={"result_id": before["result_id"]}).status_code == 200
    excluded = client.post("/api/edits", json={"kind": "exclude", "ids": [record]})
    assert excluded.status_code == 200
    assert client.get("/api/export", params={"result_id": before["result_id"]}).status_code == 409
    assert record in excluded.json()["edits"]["excluded"]
    assert client.post("/api/edits/undo").json()["edits"]["excluded"] == []


def test_finishing_worker_cannot_publish_after_source_edit(client, monkeypatch):
    import threading
    import fromthecraft.app as module

    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original = module.convert

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        done.set()
        return result

    monkeypatch.setattr(module, "convert", delayed)
    record = upload(client).json()["source"]["records"][0]["id"]
    client.post("/api/convert", json={"format": "nbt"})
    try:
        assert entered.wait(5)
        client.post("/api/edits", json={"kind": "exclude", "ids": [record]})
    finally:
        release.set()
    assert done.wait(5)
    assert client.get("/api/status").json()["state"] == "stale"
    assert client.get("/api/export").status_code == 409


def test_projects_presets_and_enabled_palette_are_validated_atomically(client):
    import copy

    source = upload(client).json()["source"]
    record = source["records"][0]["id"]
    client.post("/api/edits", json={"kind": "exclude", "ids": [record]})
    project = client.post("/api/project/save", json={"settings": {"format": "nbt"}}).json()
    client.post("/api/edits/undo")
    assert client.post("/api/project/open", json=project).json()["edits"]["excluded"] == [record]
    before = client.get("/api/edits").json()
    bad = copy.deepcopy(project)
    bad["settings"]["mods"] = ["missing"]
    assert client.post("/api/project/open", json=bad).status_code == 400
    assert client.get("/api/edits").json() == before
    palette = client.get("/api/palette").json()["blocks"]
    assert palette and all(b["name"].startswith("minecraft:") for b in palette)
    mod_palette = client.get("/api/palette?mods=chipped").json()["blocks"]
    target = next(b for b in mod_palette if b["name"].startswith("chipped:"))
    mapping = {"name": target["name"], "properties": target["properties"]}
    assert client.post("/api/palette/preview", json=mapping).json()["count"] == 1
    client.post(
        "/api/edits",
        json={"kind": "mapping", "type_keys": [source["records"][0]["type_key"]], "mapping": mapping},
    )
    assert client.post("/api/project/save", json={"settings": {"format": "nbt"}}).status_code == 400
    preset = client.post("/api/preset/save", json={"settings": {"format": "nbt", "mods": ["chipped"]}}).json()
    assert "commands" not in preset and "source" not in preset
    assert preset["type_mappings"][0]["mapping"]["name"] == target["name"]
    assert client.post("/api/preset/open", json=preset).status_code == 200


def test_reverse_native_mapping_uses_verified_ftd_material(client):
    from fromthecraft.minecraft import write_structure
    from fromthecraft.model import State
    from fromthecraft.ftd import read_blueprint

    source = client.post(
        "/api/source",
        files={"file": ("cube.nbt", write_structure({(0, 0, 0): State("minecraft:stone")}, (1, 1, 1)))},
    ).json()["source"]
    palette = client.get("/api/palette?target=blueprint").json()["blocks"]
    target = next(b for b in palette if b["material"] == "Heavy Armour")
    mapping = {"name": target["name"], "properties": {}}
    assert client.post("/api/palette/preview", json=mapping).json()["format"] == "blueprint"
    assert (
        client.post(
            "/api/edits", json={"kind": "mapping", "ids": [source["records"][0]["id"]], "mapping": mapping}
        ).status_code
        == 200
    )
    client.post("/api/convert", json={"format": "blueprint"})
    result = finished(client)
    assert result["state"] == "ready", result
    content = client.get("/api/export", params={"result_id": result["result_id"]}).content
    assert read_blueprint(content).parts[0].material == "Heavy Armour"


def test_preview_is_exact_exported_serialization(client):
    from fromthecraft.convert import read_file
    from fromthecraft.preview import preview

    response = upload(client)
    assert response.status_code == 200
    assert response.json()["source"]["count"] == 4
    assert (
        client.post("/api/convert", json={"format": "nbt", "scale": 1, "preference": "balanced"}).status_code
        == 200
    )
    status = finished(client)
    assert status["state"] == "ready", status
    exported = client.get("/api/export", params={"result_id": status["result_id"]})
    assert exported.status_code == 200
    assert hashlib.sha256(exported.content).hexdigest() == status["sha256"]
    assert preview(read_file(exported.content, "nbt"), status["offset"]) == status["converted"]
    client.post("/api/invalidate")
    assert client.get("/api/export", params={"result_id": status["result_id"]}).status_code == 409


def test_selected_mods_reach_serialization_and_unknown_mods_are_rejected(client):
    from fromthecraft.convert import read_file
    from fromthecraft.preview import preview

    choices = client.get("/api/session").json()["mod_choices"]
    assert len(choices) == 8
    assert {"copycats", "create-chipped", "chipped"} <= {mod["slug"] for mod in choices}
    upload(client)
    assert client.post("/api/convert", json={"format": "nbt", "mods": ["copycats"]}).status_code == 200
    status = finished(client)
    assert status["state"] == "ready", status
    assert any("Copycats+" in message for message in status["notices"])
    content = client.get("/api/export", params={"result_id": status["result_id"]}).content
    assert preview(read_file(content, "nbt"), status["offset"]) == status["converted"]
    assert client.post("/api/convert", json={"format": "nbt", "mods": ["unknown-mod"]}).status_code == 422


def test_cancel_replace_failure_and_empty_output_recover(client):
    import json

    upload(client)
    client.post("/api/convert", json={"format": "litematic", "scale": 2})
    client.post("/api/cancel")
    assert finished(client)["state"] == "cancelled"
    assert client.get("/api/export").status_code == 409
    assert client.post("/api/source", files={"file": ("broken.blueprint", b"{bad")}).status_code == 400
    assert client.get("/api/status").json()["state"] == "failed"
    bp = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_text())
    for k in ("BLP", "BLR", "BCI", "BlockIds"):
        bp["Blueprint"][k] = []
    client.post("/api/source", files={"file": ("empty.blueprint", json.dumps(bp).encode())})
    client.post("/api/convert", json={"format": "nbt"})
    assert finished(client)["state"] == "failed"
    upload(client)
    client.post("/api/convert", json={"format": "nbt"})
    assert finished(client)["state"] == "ready"


def test_local_origin_and_token_checks(client):
    assert (
        client.post("/api/convert", json={}, headers={"Origin": "https://external.example"}).status_code
        == 403
    )
    assert client.post("/api/invalidate", headers={"X-FromTheCraft-Token": "wrong"}).status_code == 403
    assert client.get("/api/status", headers={"Host": "attacker.example"}).status_code == 400


def test_source_replacement_discards_result(client):
    upload(client)
    client.post("/api/convert", json={"format": "nbt"})
    status = finished(client)
    assert status["state"] == "ready"
    upload(client)
    assert client.get("/api/export", params={"result_id": status["result_id"]}).status_code == 409


def test_bad_output_option_and_oversized_dimensions(client):
    upload(client)
    assert client.post("/api/convert", json={"format": "exe"}).status_code == 422
    assert client.post("/api/convert", json={"format": "nbt", "scale": 50}).status_code == 422


def test_unicode_source_filename_can_be_exported(client):
    content = Path("tests/fixtures/asymmetric.blueprint").read_bytes()
    assert client.post("/api/source", files={"file": ("船.blueprint", content)}).status_code == 200
    client.post("/api/convert", json={"format": "nbt"})
    status = finished(client)
    response = client.get("/api/export", params={"result_id": status["result_id"]})
    assert response.status_code == 200
    assert "filename*=UTF-8''" in response.headers["content-disposition"]


def test_hollow_option_reloads_the_exact_download_and_inventory(client):
    import json
    from fromthecraft.convert import read_file
    from fromthecraft.preview import preview

    document = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    document["Blueprint"].update(BLP=["0,0,0"], BLR=[0], BCI=[0], BlockIds=[0], SCs=[])
    response = client.post("/api/source", files={"file": ("cube.blueprint", json.dumps(document).encode())})
    assert response.status_code == 200
    assert client.post("/api/convert", json={"format": "nbt", "scale": 4, "hollow": True}).status_code == 200
    status = finished(client)
    assert status["state"] == "ready", status
    response = client.get("/api/export", params={"result_id": status["result_id"]})
    assert status["converted"]["count"] == 56
    assert sum(item["count"] for item in status["converted"]["materials"]) == 56
    assert preview(read_file(response.content, "nbt"), status["offset"]) == status["converted"]
    assert client.post("/api/convert", json={"format": "nbt", "shell_thickness": 9}).status_code == 422


def test_reverse_slope_preview_matches_serialized_blueprint_with_native_vertices(client):
    from fromthecraft.convert import read_file
    from fromthecraft.minecraft import write_structure
    from fromthecraft.model import State
    from fromthecraft.preview import preview

    state = State(
        "minecraft:oak_stairs",
        (("facing", "east"), ("half", "bottom"), ("shape", "straight"), ("waterlogged", "false")),
    )
    source = write_structure({(0, 0, 0): state}, (1, 1, 1))
    client.post("/api/source", files={"file": ("stairs.nbt", source)})
    client.post("/api/convert", json={"format": "blueprint"})
    status = finished(client)
    assert status["state"] == "ready", status
    assert status["converted"]["groups"][0]["vertices"]
    exported = client.get("/api/export", params={"result_id": status["result_id"]})
    assert preview(read_file(exported.content, "blueprint"), status["offset"]) == status["converted"]


def test_detailed_preview_and_export_stay_identical_after_loading_textures(client):
    from test_textures import archive, cube, png
    from fromthecraft.convert import read_file
    from fromthecraft.preview import preview
    import fromthecraft.app as module

    client.post(
        "/api/source",
        files={"file": ("slopes.blueprint", Path("tests/fixtures/painted-slopes.blueprint").read_bytes())},
    )
    client.post("/api/convert", json={"format": "nbt", "mods": ["copycats"], "detailed_copycats": True})
    ready = finished(client)
    assert ready["state"] == "ready", ready
    before = client.get("/api/export", params={"result_id": ready["result_id"]}).content
    raw = png()
    data = archive(
        {
            "assets/minecraft/blockstates/red_wool.json": {
                "variants": {"": {"model": "minecraft:block/red_wool"}}
            },
            "assets/minecraft/models/block/red_wool.json": cube("minecraft:block/red_wool"),
            "assets/minecraft/textures/block/red_wool.png": raw,
        }
    )
    loaded = client.post("/api/textures", files={"file": ("original.zip", data)})
    assert loaded.status_code == 200
    after = client.get("/api/export", params={"result_id": ready["result_id"]}).content
    assert before == after
    status = client.get("/api/status").json()
    session = module.sessions[client.cookies["fromthecraft"]]
    assert status["converted"] == preview(read_file(after, "nbt"), status["offset"], session.textures)
    faces = [block["textures"] for block in loaded.json()["converted"]["blocks"] if block.get("textures")]
    assert faces
    key = next(iter(faces[0].values()))
    assert client.get(f"/api/textures/{key}").status_code == 403
    assert client.get(f"/api/textures/{key}", params={"token": session.token}).content == raw
    assert client.get("/api/textures/missing", params={"token": session.token}).status_code == 404


def test_chunked_upload_limit_is_enforced_before_multipart_parsing(client):
    def chunks():
        yield b'--original\r\nContent-Disposition: form-data; name="file"; filename="test.blueprint"\r\nContent-Type: application/octet-stream\r\n\r\n'
        yield b"x" * (17 * 1024**2)
        yield b"y" * (17 * 1024**2)
        yield b"\r\n--original--\r\n"

    response = client.post(
        "/api/source", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=original"}
    )
    assert response.status_code == 413
