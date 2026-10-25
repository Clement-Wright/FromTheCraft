"""Trusted export previews match re-importing every state and source identity."""

from dataclasses import fields
from importlib import import_module

import numpy as np
import pytest

from fromthecraft import minecraft
from fromthecraft.model import Cancelled, Part, Scene, State


def assert_scene_equal(actual, expected):
    assert len(actual.parts) == len(expected.parts)
    for field in fields(Scene):
        if field.name != "parts":
            assert getattr(actual, field.name) == getattr(expected, field.name), field.name
    for actual_part, expected_part in zip(actual.parts, expected.parts):
        for field in fields(Part):
            a, b = getattr(actual_part, field.name), getattr(expected_part, field.name)
            if isinstance(a, np.ndarray):
                assert a.dtype == b.dtype and a.shape == b.shape
                assert a.tobytes() == b.tobytes(), field.name
            else:
                assert a == b, field.name


@pytest.mark.parametrize("format", ["nbt", "litematic"])
def test_generated_preview_matches_actual_file_order_materials_ids_and_notices(monkeypatch, format):
    from fromthecraft.generated_preview import export_scene

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    stone, glass, gold = State("minecraft:stone"), State("minecraft:glass"), State("minecraft:gold_block")
    variants = [
        stone,
        State("minecraft:air"),
        State("minecraft:chest"),
        State("minecraft:unknown_test_block"),
        State("minecraft:oak_stairs", (("shape", "inner_left"), ("half", "top"), ("facing", "east"))),
        State("copycats:copycat_layer", (("facing", "down"), ("layers", "3")), copied_material=gold),
        State(
            "copycats:copycat_byte",
            (("bottom_northeast", "true"), ("top_southwest", "true")),
            copied_materials=(("bottom_northeast", glass), ("top_southwest", gold)),
        ),
        State("copycats:copycat_slope", (("half", "top"), ("facing", "west")), copied_material=stone),
    ]
    positions = [(2, 1, 2), (0, 0, 2), (1, 0, 0), (3, 2, 1), (0, 2, 0), (3, 1, 1), (1, 2, 2), (2, 0, 1)]
    states = dict(zip(positions, variants))
    writer, reader = (
        (minecraft.write_structure, minecraft.read_structure)
        if format == "nbt"
        else (minecraft.write_litematic, minecraft.read_litematic)
    )
    content = writer(states, (4, 3, 3))
    expected = reader(content)
    actual = export_scene(states, (4, 3, 3), format, content)
    assert_scene_equal(actual, expected)


@pytest.mark.parametrize("format", ["nbt", "litematic"])
def test_optimized_preview_avoids_the_untrusted_input_parser_and_keeps_bytes(monkeypatch, format):
    module = import_module("fromthecraft.convert")
    scene = Scene([Part("wall", "box", (2, 2, 2), np.eye(4), "Stone", (0.8, 0.8, 0.8))], "blueprint")
    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    expected = module.convert(scene, format, mods=("create", "copycats"), extreme_detail=True)

    def unexpected(_content):
        pytest.fail("The app's own validated states need no decompression or second NBT tag tree")

    monkeypatch.setattr(minecraft, "parse_nbt", unexpected)
    actual = module.convert(
        scene, format, mods=("create", "copycats"), extreme_detail=True, optimized_conversion=True
    )
    assert actual.content == expected.content
    assert actual.notices == expected.notices and actual.offset == expected.offset
    assert_scene_equal(actual.scene, expected.scene)


def test_generated_preview_is_cancellable_between_placements():
    from fromthecraft.generated_preview import export_scene

    states = {(i, 0, 0): State("minecraft:stone") for i in range(512)}
    content = minecraft.write_structure(states, (512, 1, 1))
    with pytest.raises(Cancelled):
        export_scene(states, (512, 1, 1), "nbt", content, cancelled=lambda: True)


def test_file_only_conversion_does_not_allocate_a_preview(monkeypatch):
    module = import_module("fromthecraft.convert")
    scene = Scene([Part("cube", "box", (1, 1, 1), np.eye(4), "Stone", (0.5,) * 3)], "blueprint")
    expected = module.convert(scene, "nbt").content

    def unexpected(*_args, **_kwargs):
        pytest.fail("A file-only conversion does not need a viewer model")

    monkeypatch.setattr(module, "read_structure", unexpected)
    for optimized in (False, True):
        result = module.convert(scene, "nbt", build_preview=False, optimized_conversion=optimized)
        assert result.content == expected and result.scene is None


def test_fitted_grid_is_released_before_serialization(monkeypatch):
    import weakref

    module = import_module("fromthecraft.convert")
    refs = []

    class Grid(dict):
        pass

    def voxelize(*_args, **_kwargs):
        grid = Grid({(0, 0, 0): Part("cube", "box", (1, 1, 1), np.eye(4), "Stone", (0.5,) * 3)})
        refs.append(weakref.ref(grid))
        return grid, (0.0, 0.0, 0.0)

    write = module.write_structure

    def writer(*args):
        assert refs[-1]() is None, "The complete target-state map already owns everything the writer needs"
        return write(*args)

    monkeypatch.setattr(module, "voxelize", voxelize)
    monkeypatch.setattr(module, "write_structure", writer)
    scene = Scene([Part("cube", "box", (1, 1, 1), np.eye(4), "Stone", (0.5,) * 3)], "blueprint")
    assert module.convert(scene, "nbt").scene.parts


def test_generated_preview_does_not_relax_uploaded_file_limits(monkeypatch):
    module = import_module("fromthecraft.convert")
    scene = Scene([Part("cube", "box", (2, 2, 2), np.eye(4), "Stone", (0.5,) * 3)], "blueprint")
    monkeypatch.setattr(minecraft, "MAX_BYTES", 64)
    result = module.convert(scene, "nbt", optimized_conversion=True)
    assert len(result.scene.parts) == 8
    with pytest.raises(ValueError, match="Decompressed NBT"):
        minecraft.read_structure(result.content)


@pytest.mark.parametrize("format,position", [("nbt", (1.7, 0.6, 0)), ("litematic", (-1, 0, 0))])
def test_unusual_placements_keep_actual_reader_behavior(monkeypatch, format, position):
    from fromthecraft.generated_preview import export_scene

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    writer, reader = (
        (minecraft.write_structure, minecraft.read_structure)
        if format == "nbt"
        else (minecraft.write_litematic, minecraft.read_litematic)
    )
    states = {position: State("minecraft:stone")}
    content = writer(states, (3, 2, 2))
    assert_scene_equal(export_scene(states, (3, 2, 2), format, content), reader(content))
