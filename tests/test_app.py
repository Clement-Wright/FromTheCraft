import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from fromthecraft.app import app

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
