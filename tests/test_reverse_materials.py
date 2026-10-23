import json

import numpy as np
import pytest

from fromthecraft.ftd import CATALOG, write_blueprint
from fromthecraft.model import Part


@pytest.mark.parametrize("material", ["Alloy", "Heavy Armour", "Reinforced Wood", "Lead", "Rubber"])
def test_native_reverse_writer_preserves_available_material_families(material):
    part = Part("source", "box", (1, 1, 1), np.eye(4), material, (0.2, 0.3, 0.4))
    document = json.loads(write_blueprint({(0, 0, 0): part}))
    key = str(document["Blueprint"]["BlockIds"][0])
    assert CATALOG[document["ItemDictionary"][key]]["Material"] == material
    from fromthecraft.ftd import read_blueprint

    assert read_blueprint(json.dumps(document).encode()).parts[0].material == material


@pytest.mark.parametrize("material", ["Alloy", "Heavy Armour", "Lead", "Rubber"])
def test_reverse_slope_preserves_native_material_and_orientation(material):
    from fromthecraft.ftd import SLOPE_IDS

    part = Part("source", "step_east_top", (1, 1, 1), np.eye(4), material, (0.2, 0.3, 0.4))
    document = json.loads(write_blueprint({(0, 0, 0): part}))
    root = document["Blueprint"]
    assert root["BLR"] == [15]
    assert document["ItemDictionary"][str(root["BlockIds"][0])] == SLOPE_IDS[material]
