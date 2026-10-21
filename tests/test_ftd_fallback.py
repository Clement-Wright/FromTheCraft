import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from fromthecraft.ftd_shapes import native_shape


DATA = Path(__file__).parents[1] / "src/fromthecraft/data"


def bundled_shapes_without_installation(tmp_path, guids):
    script = """
import json
import sys
from fromthecraft.ftd import CATALOG, CATALOG_INFO, ftd_policy
from fromthecraft.ftd_shapes import native_shape

assert CATALOG_INFO['entries'] == 0
guids = json.loads(sys.argv[1])
assert all('MeshName' not in CATALOG[guid] for guid in guids)
print(json.dumps({guid: [native_shape(CATALOG[guid]), ftd_policy(CATALOG[guid])[1]] for guid in guids}))
"""
    environment = os.environ.copy()
    environment["FROMTHECRAFT_FTD"] = str(tmp_path / "no-game-installed")
    environment["PYTHONPATH"] = str(DATA.parents[1])
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(guids)],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_bundled_catalog_disambiguates_native_families_without_game_installation(tmp_path):
    expected = {
        "3a42ac8c-2c51-429c-a375-5d0f2c41742e": "ftd_transition_left_2_3",
        "c5550009-2b37-41ff-a788-d413b39376ae": "ftd_transition_right_2_3",
        "d6b944ee-04fc-411c-9d22-935d5f4b2440": "ftd_backed_right",
        "c30ac9c4-8fa1-4812-a56a-1926d2119dc5": "ftd_offset_left_1",
        "0a0754e4-024e-4622-9a06-506a7f4a6ca3": "ftd_transition_inverse_right_1_2",
    }
    actual = bundled_shapes_without_installation(tmp_path, list(expected))
    assert actual == {guid: [shape, shape] for guid, shape in expected.items()}


@pytest.mark.parametrize("shape", ["ftd_wedge", None])
def test_explicit_native_fallback_applies_only_without_resolved_mesh(shape):
    entry = {"Name": "Metal down slope (1m)", "NativeShape": shape}
    assert native_shape(entry) == shape
    assert native_shape({**entry, "MeshName": "Wood down slope (1m)"}) == "ftd_slope"


def test_all_versioned_shape_corrections_are_narrow_and_work_without_installation(tmp_path):
    document = json.loads((DATA / "ftd_native_shape_corrections.json").read_text())
    corrections = document["corrections"]
    bundled = json.loads((DATA / "ftd_blocks.json").read_text())
    assert document["schema_version"] == 1
    assert document["provenance"]["game_version"] == "4.3.4.0"
    assert document["provenance"]["game_build"] == 1
    assert len(corrections) == 234
    assert corrections.keys() <= bundled.keys()
    assert all(native_shape(bundled[guid]) != shape for guid, shape in corrections.items())
    actual = bundled_shapes_without_installation(tmp_path, list(corrections))
    assert actual == {
        guid: [shape, shape if shape is not None else "box"] for guid, shape in corrections.items()
    }


def test_shape_corrections_match_resolved_installed_native_families():
    from fromthecraft.catalog import game_assets, installed_catalog

    root = game_assets()
    if not (root / "Mods/Core_Structural").is_dir():
        pytest.skip("Local FtD installation unavailable; game assets are not redistributed")
    corrections = json.loads((DATA / "ftd_native_shape_corrections.json").read_text())["corrections"]
    bundled = json.loads((DATA / "ftd_blocks.json").read_text())
    installed, _ = installed_catalog(root, bundled)
    for guid, shape in corrections.items():
        assert guid in installed
        assert native_shape(installed[guid]) == shape, guid
