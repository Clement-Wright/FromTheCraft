from itertools import product

import numpy as np
import pytest

from fromthecraft.convert import convert
from fromthecraft.geometry import hollow_cells
from fromthecraft.model import Cancelled, Part, Scene


def test_closed_hull_loses_interior_deck_and_keeps_one_cell_shell():
    cells = {p: "part" for p in product(range(7), repeat=3) if any(n in (0, 6) for n in p) or p[1] == 3}
    result = hollow_cells(cells, 1)
    assert (3, 3, 3) not in result
    assert set(result) == {p for p in cells if any(n in (0, 6) for n in p)}


def test_shell_thickness_and_open_tunnel_follow_exterior_air():
    solid = dict.fromkeys(product(range(7), repeat=3), "part")
    assert len(hollow_cells(solid, 1)) == 343 - 125
    assert len(hollow_cells(solid, 2)) == 343 - 27
    assert len(hollow_cells(solid, 4)) == 343
    for z in range(4):
        solid.pop((3, 3, z))
    result = hollow_cells(solid, 1)
    assert (3, 3, 4) in result
    assert (1, 1, 1) not in result


def test_hollow_is_opt_in_and_serialized_preview_and_inventory_are_hollow():
    part = Part("solid", "box", (5, 5, 5), np.eye(4), "Metal", (0.4, 0.4, 0.4))
    scene = Scene([part], "blueprint")
    assert len(convert(scene, "nbt").scene.parts) == 125
    for format in ("nbt", "litematic"):
        result = convert(scene, format, hollow=True)
        assert len(result.scene.parts) == 98
        assert any("Hollow" in notice for notice in result.notices)
    minecraft = convert(scene, "nbt").scene
    assert len(convert(minecraft, "blueprint", hollow=True).scene.parts) == 98


def test_hollow_validates_thickness_and_cancels():
    with pytest.raises(ValueError, match="thickness"):
        hollow_cells({(0, 0, 0): "part"}, 0)
    with pytest.raises(Cancelled):
        hollow_cells({(0, 0, 0): "part"}, 1, cancelled=lambda: True)
