"""Structure import keeps each contributing identity without discarded copies."""

import gzip
import io
import weakref
from dataclasses import fields, is_dataclass

import nbtlib as nbt
import numpy as np
import pytest

from fromthecraft import minecraft
from fromthecraft.model import Part, Scene
from fromthecraft.preview import preview
import exact_reference


def encoded(root):
    stream = io.BytesIO()
    nbt.File(root).write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)


@pytest.fixture
def structure_records():
    palette = ["minecraft:stone", "minecraft:glass", "unknown:test", "minecraft:air", "minecraft:water"]
    return nbt.Compound({
        "DataVersion": nbt.Int(3955),
        "size": nbt.List[nbt.Int]((4, 1, 1)),
        "palette": nbt.List[nbt.Compound]([nbt.Compound({"Name": nbt.String(name)}) for name in palette]),
        "blocks": nbt.List[nbt.Compound]([
            nbt.Compound({"state": nbt.Int(state), "pos": nbt.List[nbt.Int]((x, 0, 0))})
            for x, state in [(3, 0), (0, 1), (3, 2), (1, 3), (2, 4), (0, 0)]
        ]),
        "entities": nbt.List[nbt.Compound](),
    })


def test_structure_allocates_only_contributing_source_records(monkeypatch, structure_records):
    content = encoded(structure_records)
    expected = exact_reference.read_structure(content)
    original, calls = minecraft.SourceRecord, 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(minecraft, "SourceRecord", counted)
    actual = minecraft.read_structure(content)
    assert preview(actual) == preview(expected)
    assert calls == 4, "Allocate one identity per retained source entry, including overlapping records"


def test_structure_duplicate_unknown_and_skipped_records_match_complete_reference(structure_records):
    content = encoded(structure_records)
    actual, expected = minecraft.read_structure(content), exact_reference.read_structure(content)
    for field in fields(Scene):
        if field.name != "parts":
            assert getattr(actual, field.name) == getattr(expected, field.name), field.name
    assert len(actual.parts) == len(expected.parts) == 4
    assert [part.source_record.path for part in actual.parts] == [
        ("blocks", "0"), ("blocks", "1"), ("blocks", "2"), ("blocks", "5")
    ]
    assert [part.source_cell for part in actual.parts] == [(3, 0, 0), (0, 0, 0), (3, 0, 0), (0, 0, 0)]
    for actual_part, expected_part in zip(actual.parts, expected.parts):
        for field in fields(Part):
            a, b = getattr(actual_part, field.name), getattr(expected_part, field.name)
            if isinstance(a, np.ndarray):
                assert a.dtype == b.dtype and a.shape == b.shape
                assert a.tobytes() == b.tobytes(), field.name
            else:
                assert a == b, field.name


def test_structure_does_not_retain_an_unused_placement_grid(monkeypatch, structure_records):
    original = minecraft.scene_from_cells

    def build(cells, *args, **kwargs):
        assert not cells, "Source entries already contain every retained placement"
        return original(cells, *args, **kwargs)

    monkeypatch.setattr(minecraft, "scene_from_cells", build)
    assert len(minecraft.read_structure(encoded(structure_records)).parts) == 4


def test_structure_releases_nbt_tree_before_building_render_parts(monkeypatch):
    from fromthecraft.model import State

    state = State("copycats:copycat_layer", (("layers", "3"),), copied_material=State("minecraft:iron_block"))
    content = minecraft.write_structure({(0, 0, 0): state}, (1, 1, 1))
    root = minecraft.parse_nbt(content)
    root["blocks"][-1]["unused"] = nbt.ByteArray(np.zeros(1024, dtype=np.int8))
    content = encoded(root)
    del root
    parse, build = minecraft.parse_nbt, minecraft.scene_from_cells
    roots = []

    def parse_tracked(raw):
        root = parse(raw)
        roots.append(weakref.ref(root))
        roots.append(weakref.ref(root["blocks"][-1]["unused"]))
        return root

    def assert_detached(value):
        assert not isinstance(value, nbt.Base)
        if is_dataclass(value):
            for field in fields(value):
                assert_detached(getattr(value, field.name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                assert_detached(item)

    def build_detached(*args, **kwargs):
        assert all(ref() is None for ref in roots), "Release the tree and final record before allocating parts"
        assert_detached(kwargs["entries"])
        return build(*args, **kwargs)

    monkeypatch.setattr(minecraft, "parse_nbt", parse_tracked)
    monkeypatch.setattr(minecraft, "scene_from_cells", build_detached)
    assert minecraft.read_structure(content).parts[0].state == state


@pytest.mark.parametrize("mutation", ["palette", "index", "position", "bounds", "name", "missing"])
def test_structure_record_optimization_preserves_validation(structure_records, mutation):
    if mutation == "palette":
        del structure_records["palette"]
    elif mutation == "index":
        structure_records["blocks"][1]["state"] = nbt.Int(5)
    elif mutation == "position":
        structure_records["blocks"][1]["pos"] = nbt.List[nbt.Int]((0, 0))
    elif mutation == "bounds":
        structure_records["blocks"][1]["pos"] = nbt.List[nbt.Int]((100001, 0, 0))
    elif mutation == "name":
        del structure_records["palette"][1]["Name"]
    else:
        del structure_records["blocks"][3]["pos"]
    content = encoded(structure_records)
    with pytest.raises(Exception) as expected:
        exact_reference.read_structure(content)
    with pytest.raises(type(expected.value)) as actual:
        minecraft.read_structure(content)
    assert str(actual.value) == str(expected.value)
