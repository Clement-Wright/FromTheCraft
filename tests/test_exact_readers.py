"""Reader differential tests against 1320422, including malformed inputs."""

import gzip
import io
from itertools import product

import nbtlib as nbt
import numpy as np
import pytest
from litemapy import BlockState, Region, Schematic

from fromthecraft import minecraft as module
from fromthecraft.preview import preview
import exact_reference as before


def encoded(root):
    stream = io.BytesIO()
    nbt.File(root).write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)


def test_sparse_litematic_does_not_accept_every_air_cell(monkeypatch):
    region = Region(4, -2, 7, 64, 64, 64)
    region[3, 2, 1] = BlockState("minecraft:stone")
    content = encoded(Schematic(regions={"sparse": region}, mc_version=3955).to_nbt())
    expected = preview(before.read_litematic(content))
    calls, original = 0, module.accept

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "accept", counted)
    assert preview(module.read_litematic(content)) == expected
    assert calls == 1, "Skip clean air in bounded packed-index batches"


def test_structure_prepares_palette_entries_once(monkeypatch):
    region = Region(0, 0, 0, 24, 1, 1)
    for x in range(24):
        region[x, 0, 0] = BlockState("minecraft:stone")
    content = encoded(region.to_structure_nbt(mc_version=3955))
    expected = preview(before.read_structure(content))
    original, calls = BlockState.from_nbt, 0

    def counted(value):
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(BlockState, "from_nbt", staticmethod(counted))
    assert preview(module.read_structure(content)) == expected
    assert calls <= 2


def test_render_shapes_are_prepared_once_but_placements_stay_independent(monkeypatch):
    from collections import Counter
    from fromthecraft.model import State

    state = State("copycats:copycat_layer", (("facing", "up"), ("layers", "3")))
    cells = {(x, 0, 0): state for x in range(30)}
    calls, original = 0, module.geometry_boxes

    def counted(value):
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(module, "geometry_boxes", counted)
    scene = module.scene_from_cells(cells, "nbt", Counter())
    assert calls == 1
    assert len({id(part.transform) for part in scene.parts}) == 30
    assert [part.source_cell for part in scene.parts] == list(cells)


def test_nbt_validation_does_not_allocate_a_buffer_per_scalar(monkeypatch):
    content = encoded(nbt.Compound({"values": nbt.List[nbt.Int](range(10000))}))
    reads, original = 0, io.BytesIO

    class CountedStream(original):
        def read(self, *args):
            nonlocal reads
            reads += 1
            return super().read(*args)

    # Isolate the bounded preflight; the unchanged nbtlib parse has its own reads.
    monkeypatch.setattr(module.io, "BytesIO", CountedStream)
    monkeypatch.setattr(module.nbt.File, "parse", lambda stream: "validated")
    assert module.parse_nbt(content) == "validated"
    assert reads < 20


@pytest.mark.parametrize("signs", list(product((-1, 1), repeat=3)))
@pytest.mark.parametrize("palette_size", [3, 5, 17, 33, 65])
def test_packed_regions_keep_source_order_across_words_and_signed_axes(signs, palette_size):
    size = tuple(a * b for a, b in zip(signs, (7, 3, 9)))
    region = Region(-8, 5, 3, *size)
    palette = [BlockState("minecraft:air"), BlockState("minecraft:water", level="0")]
    palette += [BlockState(f"unknown:test_{i}") for i in range(palette_size - 2)]
    rng = np.random.default_rng(palette_size)
    for x, y, z in region.block_positions():
        region[x, y, z] = palette[int(rng.integers(palette_size))]
    second = Region(-8, 5, 3, 2, 1, 1)
    second[0, 0, 0] = BlockState("minecraft:glass")
    content = encoded(Schematic(regions={"one": region, "overlap": second}, mc_version=3955).to_nbt())
    actual, reference = module.read_litematic(content), before.read_litematic(content)
    assert preview(actual) == preview(reference)
    assert list(actual.notices.items()) == list(reference.notices.items())


@pytest.mark.parametrize("filename", ["copycats-materials.nbt", "copycats-materials.litematic"])
def test_copycat_entities_remain_independent_and_equal_to_reference(filename):
    from pathlib import Path

    reader = module.read_litematic if filename.endswith("litematic") else module.read_structure
    reference = before.read_litematic if filename.endswith("litematic") else before.read_structure
    content = Path("tests/fixtures", filename).read_bytes()
    assert preview(reader(content)) == preview(reference(content))


def outcome(reader, content):
    try:
        root = reader(content)
    except Exception as exc:
        return type(exc), str(exc)
    return encoded(root)


def test_bounded_validation_preserves_all_truncation_failures():
    raw = gzip.decompress(
        encoded(
            nbt.Compound(
                {"a": nbt.String("test"), "b": nbt.List[nbt.Compound]([nbt.Compound({"x": nbt.Int(3)})])}
            )
        )
    )
    for length in range(len(raw) + 1):
        assert outcome(module.parse_nbt, raw[:length]) == outcome(before.parse_nbt, raw[:length])


@pytest.mark.parametrize("mutation", ["width", "regions", "longs", "palette", "entity", "ticks"])
def test_malformed_litematic_keeps_legacy_validation(mutation):
    region = Region(0, 0, 0, 4, 2, 2)
    region[0, 0, 0] = BlockState("minecraft:stone")
    root = Schematic(regions={"one": region}, mc_version=3955).to_nbt()
    item = root["Regions"]["one"]
    if mutation == "width":
        root["Metadata"]["EnclosingSize"]["x"] = nbt.Int(2)
    elif mutation == "regions":
        root["Metadata"]["RegionCount"] = nbt.Int(10)
    elif mutation == "longs":
        item["BlockStates"] = nbt.LongArray([])
    elif mutation == "palette":
        item["BlockStatePalette"] = nbt.List[nbt.Compound]()
    elif mutation == "entity":
        item["Entities"] = nbt.List[nbt.Compound]([nbt.Compound()])
    else:
        del item["PendingFluidTicks"]
    content = encoded(root)
    with pytest.raises(Exception) as reference:
        before.read_litematic(content)
    with pytest.raises(type(reference.value)) as actual:
        module.read_litematic(content)
    assert str(actual.value) == str(reference.value)


@pytest.mark.parametrize(
    "writer,reference",
    [(module.write_structure, before.write_structure), (module.write_litematic, before.write_litematic)],
)
def test_repeated_export_templates_preserve_complete_file_bytes(writer, reference, monkeypatch):
    from fromthecraft.model import State

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    states = [
        State("minecraft:stone"),
        State("minecraft:oak_stairs", (("facing", "north"), ("half", "top"))),
        State(
            "copycats:copycat_layer",
            (("facing", "up"), ("layers", "3")),
            copied_material=State("minecraft:red_concrete"),
        ),
        State(
            "copycats:copycat_byte",
            (("bottom_northeast", "true"), ("top_southwest", "true")),
            copied_materials=(
                ("bottom_northeast", State("minecraft:gold_block")),
                ("top_southwest", State("minecraft:glass")),
            ),
        ),
    ]
    cells = {
        (x, y, z): states[(x + 3 * y + 7 * z) % len(states)]
        for x in range(5)
        for y in range(2)
        for z in range(3)
    }
    assert writer(cells, (8, 4, 5)) == reference(cells, (8, 4, 5))


def test_sparse_litematic_export_packs_in_batches_without_per_cell_bit_setters(monkeypatch):
    from litemapy.storage import LitematicaBitArray
    from fromthecraft.model import State

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    cells = {(1, 2, 3): State("minecraft:stone"), (31, 30, 29): State("minecraft:glass")}
    expected = before.write_litematic(cells, (32, 32, 32))
    calls, original = 0, LitematicaBitArray.__setitem__

    def counted(self, *args):
        nonlocal calls
        calls += 1
        return original(self, *args)

    monkeypatch.setattr(LitematicaBitArray, "__setitem__", counted)
    assert module.write_litematic(cells, (32, 32, 32)) == expected
    assert calls == 0, "Pack integer words in bounded batches instead of setting every air cell"


def test_structure_entity_templates_are_prepared_once_per_state(monkeypatch):
    from fromthecraft.model import State

    state = State("copycats:copycat_layer", (("layers", "2"),), copied_material=State("minecraft:iron_block"))
    cells = {(i, 0, 0): state for i in range(100)}
    expected = before.write_structure(cells, (100, 1, 1))
    original, calls = module.block_entity, 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(module, "block_entity", counted)
    assert module.write_structure(cells, (100, 1, 1)) == expected
    assert calls <= 2


def test_unusual_litematic_output_coordinates_keep_the_library_path(monkeypatch):
    from fromthecraft.model import State

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    cells = {(-1, 0, 0): State("minecraft:stone"), (1, 0, 0): State("minecraft:glass")}
    assert module.write_litematic(cells, (2, 1, 1)) == before.write_litematic(cells, (2, 1, 1))


@pytest.mark.parametrize("palette_size", [1, 3, 5, 17, 33, 65])
@pytest.mark.parametrize("sparse", [False, True])
def test_litematic_export_palette_and_cross_word_bytes(palette_size, sparse, monkeypatch):
    from fromthecraft.model import State

    monkeypatch.setattr("litemapy.schematic.time", lambda: 1700000000.0)
    states = [State(f"minecraft:test_{i}", (("z", str(i)), ("a", "b"))) for i in range(palette_size)]
    cells = {
        (x, y, z): states[(x + 7 * y + 17 * z) % palette_size]
        for x in range(17)
        for y in range(5)
        for z in range(13)
        if not sparse or (x + y + z) % 3 == 0
    }
    # Unknown structural states are accepted by both writers; preserve property
    # insertion order and first-use palette order across non-divisor bit widths.
    assert module.write_litematic(cells, (17, 5, 13)) == before.write_litematic(cells, (17, 5, 13))
