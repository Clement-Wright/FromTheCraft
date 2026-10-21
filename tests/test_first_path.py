import gzip
import io
import json
from pathlib import Path

import nbtlib
from litemapy import Region


def test_asymmetric_blueprint_beam_and_independent_structure_reader():
    from fromthecraft.ftd import read_blueprint
    from fromthecraft.convert import convert

    scene = read_blueprint(Path("tests/fixtures/asymmetric.blueprint").read_bytes())
    assert len(scene.parts) == 4
    beam = scene.parts[1]
    assert beam.size == (1, 1, 4)
    assert beam.material == "Metal"
    result = convert(scene, "nbt")
    root = nbtlib.File.parse(io.BytesIO(gzip.decompress(result.content)))
    assert root["DataVersion"] == 3955
    assert isinstance(root["DataVersion"], nbtlib.Int)
    region, version = Region.from_structure_nbt(root)
    occupied = {(x, y, z) for x, y, z in region.block_positions() if region[x, y, z].id != "minecraft:air"}
    assert occupied == {(0, 0, 0), (2, 0, 0), (2, 0, 1), (2, 0, 2), (2, 0, 3), (0, 1, 0), (0, 0, 2)}
    assert version == 3955
    assert result.scene.format == "nbt"


def test_blueprint_rejects_mismatched_arrays():
    import pytest
    from fromthecraft.ftd import read_blueprint

    fixture = json.loads(Path("tests/fixtures/asymmetric.blueprint").read_text())
    fixture["Blueprint"]["BLR"].pop()
    with pytest.raises(ValueError, match="length"):
        read_blueprint(json.dumps(fixture).encode())
