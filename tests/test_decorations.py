import base64
import struct
import uuid

import numpy as np
import pytest

from fromthecraft.decorations import read_decorations, unity_euler


def fixture_packet(fields):
    # Independent encoding of the observed SuperLoader layout: 8-byte module ID,
    # header count in bytes, unsorted count, data length, 7-byte header entries.
    data = b"".join(struct.pack("<HB", key, len(value)) + value for key, value in fields.items())
    header = (0).to_bytes(3, "little") + b"\0\0\0\0"
    return base64.b64encode(struct.pack("<QHHH", 291231, 7, 0, len(data)) + header + data).decode()


def test_decoration_packet_fields_preserve_transform_and_host_anchor():
    guid = "11111111-2222-3333-4444-555555555555"
    packet = fixture_packet(
        {
            0: uuid.UUID(guid).bytes_le,
            1: struct.pack("<3f", 2, 3, 4),
            2: struct.pack("<3f", 1, 0, -2),
            3: struct.pack("<3f", 0, 90, 0),
            4: struct.pack("<i", 7),
            5: struct.pack("<3i", 4, 5, 6),
            6: b"\1",
        }
    )
    records = read_decorations(packet)
    assert len(records) == 1
    assert records[0]["mesh_guid"] == guid
    assert records[0]["tether"] == (4, 5, 6)
    assert records[0]["paint"] == 7 and records[0]["hide_original"]
    np.testing.assert_allclose(
        unity_euler(records[0]["orientation"]) @ np.array([0, 0, 1]), [1, 0, 0], atol=1e-7
    )
    assert records[0]["scale"] == (2, 3, 4)


@pytest.mark.parametrize("data", ["broken!", base64.b64encode(b"\0" * 12).decode()])
def test_truncated_packets_reject_without_unbounded_allocations(data):
    with pytest.raises(ValueError):
        read_decorations(data)


def test_nested_rotated_scaled_decoration_is_separate_from_host(monkeypatch):
    import json
    from pathlib import Path
    from fromthecraft.ftd import read_blueprint
    from fromthecraft.edits import EditLayer
    from fromthecraft.convert import convert

    vertices = np.array([[x, y, z] for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)])
    indices = np.array(
        [
            [0, 1, 2],
            [1, 3, 2],
            [4, 6, 5],
            [5, 6, 7],
            [0, 4, 1],
            [1, 4, 5],
            [2, 3, 6],
            [3, 7, 6],
            [0, 2, 4],
            [2, 6, 4],
            [1, 5, 3],
            [3, 5, 7],
        ]
    )
    monkeypatch.setattr("fromthecraft.ftd.resolve_static_mesh", lambda guid: (vertices, indices, "test cube"))
    document = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    root = document["Blueprint"]
    root.update(BLP=["0,0,0"], BLR=[0], BCI=[0], BlockIds=[root["BlockIds"][0]], SCs=[])
    child = {**root, "LocalPosition": "10,0,0", "LocalRotation": "0,0.707106781,0,0.707106781"}
    child["VehicleData"] = fixture_packet(
        {
            1: struct.pack("<3f", -2, 3, 4),
            2: struct.pack("<3f", 1, 0, 0),
            3: struct.pack("<3f", 0, 90, 0),
            5: struct.pack("<3i", 0, 0, 0),
            6: b"\1",
        }
    )
    root["SCs"] = [child]
    scene = read_blueprint(json.dumps(document).encode())
    decoration = next(p for p in scene.parts if p.decoration)
    assert decoration.source_record.host_id == scene.parts[1].source_record.id
    center = decoration.transform[:3, :3] @ np.array([0.5, 0.5, 0.5]) + decoration.transform[:3, 3]
    np.testing.assert_allclose(center, [10.5, 0.5, -0.5], atol=1e-6)
    assert len(convert(scene, "nbt").scene.parts) == 2  # structure-only default
    layer = EditLayer(scene)
    host = decoration.source_record.host_id
    with pytest.raises(ValueError, match="attachments"):
        layer.apply({"kind": "exclude", "ids": [host]})
    layer.apply({"kind": "exclude", "ids": [host], "attachments": "host"})
    assert any(p.decoration for p in layer.derive(scene).parts)
    from fromthecraft.projects import export_project, import_project

    saved = export_project(scene, layer, "fixture", {"format": "nbt"}, {})
    reopened, _, _ = import_project(saved, scene)
    assert reopened.snapshot()["excluded"] == [host]
    combined = convert(scene, "nbt", decoration_mode="decorations")
    appearance = convert(scene, "nbt", decoration_mode="appearance")
    assert len(combined.scene.parts) > 2
    from fromthecraft.mesh_geometry import prepare_meshes

    prepared = prepare_meshes(scene, "appearance", 0.125, 1)
    assert all(p.source_record.id != host for p in prepared.parts)
    assert appearance.content != combined.content
    assert any("physical occupancy" in message for message in appearance.notices)


def test_local_static_mesh_cache_decoder_checks_indices_and_finiteness():
    from fromthecraft.ftd_meshes import decode_mesh_cache

    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="<f4").tobytes()
    cache = b"\0\3\0\0" + vertices + b"\12\3\0\0" + b"\0\0\0\1\0\0\2\0\0"
    points, indices = decode_mesh_cache(cache)
    assert points.shape == (3, 3) and indices.tolist() == [[0, 1, 2]]
    with pytest.raises(ValueError, match="index"):
        decode_mesh_cache(cache[:-3] + b"\3\0\0")


def test_installed_static_mesh_resolves_without_redistributed_assets():
    from fromthecraft.catalog import game_assets
    from fromthecraft.ftd_meshes import resolve_static_mesh

    if not (game_assets() / "Mods").exists():
        pytest.skip("Optional local game mesh evidence unavailable")
    vertices, indices, reason = resolve_static_mesh("911fe222-f9b2-4892-9cd6-8b154d55b2aa")
    assert vertices is not None, reason
    assert indices.shape[1] == 3
