import json
from pathlib import Path

import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.ftd import read_blueprint
from fromthecraft.geometry import contains
from fromthecraft.preview import preview


@pytest.mark.parametrize(
    "name,inside,outside",
    [
        ("Wood down slope (4m)", (0.5, 0.75, 0.1), (0.5, 0.75, 0.9)),
        ("Wood wedge (4m)", (0.1, 0.5, 0.1), (0.1, 0.5, 0.9)),
        ("Wood triangle corner (left) (4m)", (0.05, 0.1, 0.1), (0.95, 0.1, 0.1)),
        ("Wood triangle corner (right) (4m)", (0.95, 0.1, 0.1), (0.05, 0.1, 0.1)),
        ("Wood inverted triangle corner (left) (4m)", (0.1, 0.9, 0.9), (0.9, 0.9, 0.9)),
        ("Metal inverted corner (right) (1m)", (0.9, 0.9, 0.9), (0.1, 0.9, 0.9)),
        ("Wood beam slope diagonal cut (4m)", (0.9, 0.75, 0.5), (0.1, 0.75, 0.5)),
        ("Wood beam slope (3m mirrored)", (0.1, 0.75, 0.5), (0.9, 0.75, 0.5)),
        ("wood 4m square backed corner left", (0.1, 0.1, 0.5), (0.9, 0.1, 0.5)),
        ("wood 4m square backed corner right", (0.9, 0.1, 0.5), (0.1, 0.1, 0.5)),
        ("WedgeFront4m", (0.5, 0.1, 0.1), (0.1, 0.9, 0.9)),
        ("WedgeBack4m", (0.5, 0.9, 0.9), (0.1, 0.9, 0.9)),
    ],
)
def test_native_mesh_derived_occupancy(name, inside, outside):
    from fromthecraft.ftd_shapes import native_shape

    shape = native_shape({"Name": name})
    assert shape is not None
    assert contains(shape, np.asarray([inside, outside])).tolist() == [True, False]


def test_down_slope_keeps_high_end_at_negative_local_z_in_source_and_export():
    document = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    from fromthecraft.ftd import CATALOG

    guid = next(k for k, v in CATALOG.items() if v["Name"] == "Wood down slope (1m)")
    document["ItemDictionary"] = {"0": guid}
    document["Blueprint"].update(BLP=["0,0,0"], BLR=[0], BCI=[0], BlockIds=[0], SCs=[])
    scene = read_blueprint(json.dumps(document).encode())
    group = preview(scene)["groups"][0]
    vertices = np.asarray(group["vertices"]).reshape(-1, 3)
    np.testing.assert_array_equal(vertices[vertices[:, 1] == 1, 2], 0)
    target = convert(scene, "nbt")
    assert target.scene.parts[0].state.name.endswith("_stairs")
    assert dict(target.scene.parts[0].state.properties)["facing"] == "north"


@pytest.mark.parametrize("facing", ["north", "south", "east", "west"])
@pytest.mark.parametrize("half", ["bottom", "top"])
def test_reverse_stair_writer_points_native_slope_in_the_same_direction(facing, half):
    from fromthecraft.ftd import write_blueprint
    from fromthecraft.geometry import rotation
    from fromthecraft.model import Part

    part = Part("stair", f"step_{facing}_{half}", (1, 1, 1), np.eye(4), "Wood", (0.5, 0.3, 0.2))
    document = json.loads(write_blueprint({(0, 0, 0): part}))
    matrix = rotation(document["Blueprint"]["BLR"][0])
    # Native mesh's high face is opposite local +Z for both lower and upper slopes.
    high_direction = -matrix[:, 2]
    expected = {"north": (0, 0, -1), "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0)}
    np.testing.assert_array_equal(high_direction, expected[facing])


def test_native_halfspaces_and_preview_vertices_match_installed_mesh_caches():
    from fromthecraft.catalog import game_assets
    from fromthecraft.ftd_shapes import native_shape, planes, vertices

    assets = game_assets() / "Mods/Core_Structural/Assets"
    if not assets.exists():
        pytest.skip("Local game mesh fixtures unavailable; assets are not redistributed")
    checked = 0
    for path in assets.glob("*.objbytes"):
        shape = native_shape({"Name": path.stem.replace("_", " ")})
        if shape is None:
            continue
        content = path.read_bytes()
        count = int.from_bytes(content[1:4], "little")
        mesh = np.frombuffer(content, dtype="<f4", offset=4, count=count * 3).reshape(-1, 3)
        low, high = mesh.min(0), mesh.max(0)
        normalized = (mesh - low) / (high - low)
        clipping = np.asarray(planes(shape))
        violation = normalized @ clipping[:, :3].T - clipping[:, 3]
        assert violation.max() < 0.003, path.name
        hull = np.asarray(vertices(shape)).reshape(-1, 3)
        distance = np.linalg.norm(hull[:, None, :] - normalized[None, :, :], axis=2).min(1)
        assert distance.max() < 0.003, path.name
        checked += 1
    assert checked >= 40
