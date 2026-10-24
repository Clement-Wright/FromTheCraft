"""Streaming must retain the complete serialized structure, including copycat data."""

import weakref
from importlib import import_module

import nbtlib as nbt
import numpy as np
import pytest

from fromthecraft import minecraft
from fromthecraft.model import Part, Scene, State
import exact_reference


def test_structure_serialization_work_scales_with_states_instead_of_placements(monkeypatch):
    state = State("copycats:copycat_layer", (("layers", "3"),), copied_material=State("minecraft:iron_block"))
    cells = {(x, 0, 0): state for x in range(512)}
    expected = exact_reference.write_structure(cells, (512, 1, 1))
    calls, write = 0, nbt.Compound.write

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return write(self, *args, **kwargs)

    monkeypatch.setattr(nbt.Compound, "write", counted)
    assert minecraft.write_structure(cells, (512, 1, 1)) == expected
    assert calls < 30, "Encode each repeated compound once instead of rebuilding every placement"


@pytest.mark.parametrize("positions", [[], [(0, 0, 0)], [(3, 2, 1), (-4, 7, -9), (0, 0, 0)],
                                      [(-(2**31), 0, 0), (2**31-1, 0, 0)], [(-1.7, 0.6, 3.2)]])
def test_streamed_structure_matches_reference_order_and_unusual_positions(positions):
    states = [State("minecraft:stone"), State("copycats:copycat_byte",
        (("bottom_northeast", "true"), ("top_southwest", "true")),
        copied_materials=(("bottom_northeast", State("minecraft:gold_block")),
                          ("top_southwest", State("minecraft:glass"))))]
    cells = {position: states[i % len(states)] for i, position in enumerate(positions)}
    assert minecraft.write_structure(cells, (8, 8, 8)) == exact_reference.write_structure(cells, (8, 8, 8))


def test_conversion_releases_intermediate_grid_before_importing_export(monkeypatch):
    module = import_module("fromthecraft.convert")
    original_reader = module.read_structure
    grids = []

    class TrackedGrid(dict):
        pass

    def voxelize(*args, **kwargs):
        grid = TrackedGrid({(0, 0, 0): Part("cube", "box", (1, 1, 1), np.eye(4), "Stone", (0.5,) * 3)})
        grids.append(weakref.ref(grid))
        return grid, (0.0,) * 3

    def read(content):
        assert grids[-1]() is None, "Drop the sampling grid before allocating the imported preview"
        return original_reader(content)

    monkeypatch.setattr(module, "voxelize", voxelize)
    monkeypatch.setattr(module, "read_structure", read)
    source = Scene([Part("cube", "box", (1, 1, 1), np.eye(4), "Stone", (0.5,) * 3)], "blueprint")
    assert module.convert(source, "nbt").scene.parts
