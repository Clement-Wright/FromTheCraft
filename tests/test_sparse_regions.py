"""Sparse packed decoding must preserve every source-order value and failure."""

import gzip
import io
from dataclasses import fields
from itertools import product

import nbtlib as nbt
import numpy as np
import pytest
from litemapy import BlockState, Region, Schematic

from fromthecraft import minecraft, packed_regions
from fromthecraft.model import Part, Scene
from fromthecraft.preview import preview
import exact_reference


def encoded(root):
    stream = io.BytesIO()
    nbt.File(root).write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)


def packed_words(values, nbits):
    words = [0] * ((len(values) * nbits + 63) // 64)
    for index, value in enumerate(values):
        bit = index * nbits
        word, shift = divmod(bit, 64)
        words[word] |= int(value) << shift & ((1 << 64) - 1)
        if shift + nbits > 64:
            words[word + 1] |= int(value) >> (64 - shift)
    return np.asarray(words, dtype=np.uint64)


def scalar_blocks(region):
    width, height, length = (abs(n) for n in region.size)
    minimum = region.minimum
    for x, y, z in product(range(width), range(height), range(length)):
        bit = ((y * width * length) + z * width + x) * region.nbits
        word, shift = divmod(bit, 64)
        value = int(region.words[word]) >> shift
        if shift + region.nbits > 64:
            value |= int(region.words[word + 1]) << (64 - shift)
        index = value & ((1 << region.nbits) - 1)
        if index >= len(region.palette):
            raise IndexError("list index out of range")
        block = region.palette[index]
        if block.id not in packed_regions.AIR or tuple(block.properties()):
            yield tuple(a + b for a, b in zip((x, y, z), minimum)), block


def prefix(iterator):
    values = []
    try:
        values.extend(iterator)
    except Exception as exc:
        return values, type(exc), str(exc)
    return values, None, None


def test_sparse_regions_decode_occupied_words_instead_of_every_air_cell(monkeypatch):
    size = (128, 64, 128)
    words = np.zeros(int(np.prod(size)) // 32, dtype=np.uint64)
    for index in (0, 127, 4097, 222222, int(np.prod(size)) - 1):
        words[index // 32] |= np.uint64(1 << ((index % 32) * 2))
    region = packed_regions.PackedRegion(
        "sparse", (0, 0, 0), size, (BlockState("minecraft:air"), BlockState("minecraft:stone")),
        words, 2, [], [],
    )
    calls, arange = 0, np.arange

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return arange(*args, **kwargs)

    monkeypatch.setattr(packed_regions.np, "arange", counted)
    actual = list(region.blocks())
    stone = BlockState("minecraft:stone")
    assert actual == [(position, stone) for position in [(0, 0, 0), (1, 0, 32), (14, 13, 72),
                                                       (127, 0, 0), (127, 63, 127)]]
    assert calls <= 1, "Do not allocate coordinate batches for a million clean-air cells"


@pytest.mark.parametrize("nbits,palette_size", [(2, 3), (3, 5), (5, 17), (7, 65), (9, 257), (17, 65537)])
@pytest.mark.parametrize("signs", list(product((-1, 1), repeat=3)))
@pytest.mark.parametrize("invalid", [False, True])
def test_sparse_words_preserve_straddling_values_signed_axes_and_invalid_prefix(nbits, palette_size, signs, invalid):
    palette = (BlockState("minecraft:air"),) + (BlockState("minecraft:stone"),) * (palette_size - 1)
    size = tuple(a * b for a, b in zip(signs, (5, 3, 9)))
    values = np.zeros(135, dtype=np.uint64)
    values[[0, 1, 63 // nbits, 64 // nbits, 65 // nbits, 31, 67, 134]] = palette_size - 1
    if invalid:
        values[[12, 99]] = palette_size
    region = packed_regions.PackedRegion("one", (3, -9, 7), size, palette, packed_words(values, nbits), nbits, [], [])
    assert prefix(region.blocks()) == prefix(scalar_blocks(region))


@pytest.mark.parametrize("zero", [
    BlockState("minecraft:air"), BlockState("minecraft:cave_air"), BlockState("minecraft:void_air"),
    BlockState("minecraft:air", unusual="true"), BlockState("minecraft:stone"),
])
@pytest.mark.parametrize("padding", [False, True])
def test_sparse_words_preserve_zero_palette_semantics_and_ignore_padding(zero, padding):
    values = np.zeros(13, dtype=np.uint64)
    values[[1, 7, 11]] = 1
    words = packed_words(values, 2)
    if padding:
        words[-1] |= np.uint64(0xFFFFFFFFFC000000)
    region = packed_regions.PackedRegion(
        "one", (0, 0, 0), (13, 1, 1), (zero, BlockState("minecraft:glass")), words, 2, [], [],
    )
    assert prefix(region.blocks()) == prefix(scalar_blocks(region))


@pytest.mark.parametrize("width", [1, 2, 3, 5, 9, 17])
@pytest.mark.parametrize("padding", [False, True])
def test_all_air_regions_ignore_nonzero_padding_without_yielding_cells(width, padding):
    words = np.zeros(1, dtype=np.uint64)
    if padding:
        words[0] = np.uint64(((1 << 64) - 1) ^ ((1 << (width * 2)) - 1))
    region = packed_regions.PackedRegion(
        "air", (0, 0, 0), (width, 1, 1), (BlockState("minecraft:air"),), words, 2, [], [],
    )
    assert list(region.blocks()) == []


def test_sparse_candidate_limit_falls_back_before_allocating_indices(monkeypatch):
    monkeypatch.setattr(packed_regions, "SPARSE_CANDIDATES", 32, raising=False)
    words = np.full(64, np.uint64(0x5555555555555555))
    region = packed_regions.PackedRegion(
        "dense", (0, 0, 0), (128, 4, 4), (BlockState("minecraft:air"), BlockState("minecraft:stone")),
        words, 2, [], [],
    )
    unique = np.unique

    def bounded(values, *args, **kwargs):
        assert len(values) <= 32, "Check candidate capacity before expanding packed words"
        return unique(values, *args, **kwargs)

    monkeypatch.setattr(packed_regions.np, "unique", bounded)
    assert list(region.blocks()) == list(scalar_blocks(region))


@pytest.mark.parametrize("mutation", ["none", "invalid", "truncated", "padding", "first_state"])
def test_sparse_full_reader_matches_frozen_scene_and_validation(mutation):
    region = Region(-3, 7, 2, -7, 3, -9)
    region[0, 0, 0] = BlockState("minecraft:stone")
    region[-6, 1, -8] = BlockState("minecraft:glass")
    root = Schematic(regions={"one": region}, mc_version=3955).to_nbt()
    item = root["Regions"]["one"]
    words = np.asarray(item["BlockStates"], dtype=np.uint64)
    if mutation in {"invalid", "first_state"}:
        # Corrupt a later source-order cell; an earlier invalid state must win.
        words[0] |= np.uint64(3 << 2)
        if mutation == "first_state":
            item["BlockStatePalette"][0] = BlockState("minecraft:air", bad="value").to_nbt()
        item["BlockStates"] = nbt.LongArray(words.view(np.int64))
    elif mutation == "truncated":
        item["BlockStates"] = nbt.LongArray(words[:-1].view(np.int64))
    elif mutation == "padding":
        words[-1] |= np.uint64(0xF000000000000000)
        item["BlockStates"] = nbt.LongArray(words.view(np.int64))
    content = encoded(root)
    try:
        expected = exact_reference.read_litematic(content)
    except Exception as exc:
        with pytest.raises(type(exc)) as actual:
            minecraft.read_litematic(content)
        assert str(actual.value) == str(exc)
    else:
        actual = minecraft.read_litematic(content)
        assert preview(actual) == preview(expected)
        assert list(actual.notices.items()) == list(expected.notices.items())
        for field in fields(Scene):
            if field.name != "parts":
                assert getattr(actual, field.name) == getattr(expected, field.name), field.name
        assert len(actual.parts) == len(expected.parts)
        for actual_part, expected_part in zip(actual.parts, expected.parts):
            for field in fields(Part):
                a, b = getattr(actual_part, field.name), getattr(expected_part, field.name)
                if isinstance(a, np.ndarray):
                    assert a.dtype == b.dtype and a.shape == b.shape
                    assert a.tobytes() == b.tobytes(), field.name
                else:
                    assert a == b, field.name
