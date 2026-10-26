"""Keep exact paint/surface behavior while bounding repeated fitting work."""

from dataclasses import replace
from itertools import product

import numpy as np
import pytest

from fromthecraft import extreme
from fromthecraft.detail import DETAIL_SAMPLES, FULL_MASK, VOLUME_MASK, bits
from fromthecraft.model import Part, State
from fromthecraft.palettes import mc_target


def source(**changes):
    return Part("source", "box", (1, 1, 1), np.eye(4), "Metal", (0.9, 0.1, 0.1), **changes)


def surface_reference(mask):
    volume = np.array([bool(mask & (1 << i)) for i in range(4096)]).reshape(16, 16, 16)
    padded = np.pad(volume, 1)
    interior = volume.copy()
    for axis, shift in product(range(3), (0, 2)):
        slices = [slice(1, -1)] * 3
        slices[axis] = slice(shift, shift + 16)
        interior &= padded[tuple(slices)]
    return bits((volume & ~interior).ravel()) | (mask & ~VOLUME_MASK)


def test_surface_extraction_does_not_allocate_unpacked_sample_arrays(monkeypatch):
    mask = bits(DETAIL_SAMPLES[:, 1] + DETAIL_SAMPLES[:, 2] / 3 <= 1)
    expected = surface_reference(mask)

    def unpack(*args, **kwargs):
        pytest.fail("Surface extraction must keep the occupancy mask packed")

    monkeypatch.setattr(np, "unpackbits", unpack)
    assert extreme.surface_mask.__wrapped__(mask) == expected


def test_surface_extraction_keeps_probe_bits_axis_boundaries_and_random_masks():
    rng = np.random.default_rng(7091)
    masks = [0, FULL_MASK, VOLUME_MASK, FULL_MASK ^ VOLUME_MASK]
    masks += [1 << i for i in (0, 15, 16, 255, 256, 4095, 4096, len(DETAIL_SAMPLES) - 1)]
    masks += [
        bits(rng.random(len(DETAIL_SAMPLES)) < density) for density in (0.01, 0.3, 0.9) for _ in range(8)
    ]
    for mask in masks:
        assert extreme.surface_mask.__wrapped__(mask) == surface_reference(mask)


@pytest.mark.parametrize("mask", [-1, 1 << len(DETAIL_SAMPLES)])
def test_surface_extraction_preserves_unsigned_mask_domain_errors(mask):
    with pytest.raises(OverflowError) as expected:
        mask.to_bytes((len(DETAIL_SAMPLES) + 7) // 8, "little")
    with pytest.raises(OverflowError) as actual:
        extreme.surface_mask.__wrapped__(mask)
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize("mask", [None, "1", 1.0, np.int64(1)])
def test_surface_extraction_preserves_non_integer_input_errors(mask):
    with pytest.raises(AttributeError) as expected:
        mask.to_bytes((len(DETAIL_SAMPLES) + 7) // 8, "little")
    with pytest.raises(AttributeError) as actual:
        extreme.surface_mask.__wrapped__(mask)
    assert str(actual.value) == str(expected.value)


def test_surface_extraction_retains_its_bounded_cache_without_using_neighbor_cache():
    extreme.surface_mask.cache_clear()
    exposed_before = extreme.exposed_samples.cache_info()
    try:
        for mask in range(2050):
            extreme.surface_mask(mask)
        extreme.surface_mask(2049)
        info = extreme.surface_mask.cache_info()
        assert (info.maxsize, info.currsize, info.hits, info.misses) == (2048, 2048, 1, 2050)
        assert extreme.exposed_samples.cache_info() == exposed_before
    finally:
        extreme.surface_mask.cache_clear()


def test_visible_source_material_does_not_copy_the_source_part(monkeypatch):
    contributor = source()
    part = replace(contributor, shape="extreme", detail_sources=((contributor, FULL_MASK),))
    expected = mc_target(contributor, "color", ("copycats",))
    copied = []
    original = extreme.replace

    def counting_replace(value, **changes):
        if isinstance(value, Part):
            copied.append(value)
        return original(value, **changes)

    monkeypatch.setattr(extreme, "replace", counting_replace)
    assert extreme.paint_target(part, "color", ("copycats",), State("minecraft:iron_block")) == expected
    assert copied == []


@pytest.mark.parametrize("preference", ["color", "balanced", "material"])
@pytest.mark.parametrize("mods", [(), ("copycats",), ("copycats", "create")])
@pytest.mark.parametrize("transparent,full,override", product((False, True), repeat=3))
def test_source_material_keeps_mapping_mod_and_full_override_precedence(
    preference, mods, transparent, full, override
):
    contributor = source(
        transparent=transparent,
        mapping_full=full,
        mapping_override=State("minecraft:blue_concrete") if override else None,
    )
    # The current decision for a source is the ordinary box mapping.
    expected = mc_target(contributor, preference, mods)
    part = replace(
        contributor, shape="extreme", mapping_full=False, detail_sources=((contributor, FULL_MASK),)
    )
    assert extreme.paint_target(part, preference, mods, State("minecraft:iron_block")) == expected


def test_paint_agreement_reuses_the_selected_slot_score():
    class CountedMask(int):
        popcounts = 0

        def __and__(self, other):
            return CountedMask(int(self) & int(other))

        def __or__(self, other):
            return CountedMask(int(self) | int(other))

        __ror__ = __or__

        def bit_count(self):
            CountedMask.popcounts += 1
            return super().bit_count()

    left = source(mapping_override=State("minecraft:red_concrete"))
    right = source(mapping_override=State("minecraft:blue_concrete"))
    left_mask = CountedMask(bits(DETAIL_SAMPLES[:, 0] < 0.5))
    right_mask = CountedMask(FULL_MASK ^ left_mask)
    part = replace(
        left,
        shape="extreme",
        detail_sources=((left, left_mask), (right, right_mask)),
        detail_surface=FULL_MASK,
    )
    painted = extreme.paint_target(part, "color", ("copycats",), State("minecraft:iron_block"))
    assert painted.name == "copycats:copycat_byte"
    assert len(painted.copied_materials) == 8
    assert {material for _, material in painted.copied_materials} == {
        State("minecraft:red_concrete"),
        State("minecraft:blue_concrete"),
    }
    assert CountedMask.popcounts == 16, "Each painted slot needs its weighted count only once"


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_piece_paint_scores_keep_the_first_source_material(reverse):
    red, blue = State("minecraft:red_concrete"), State("minecraft:blue_concrete")
    first, second = source(mapping_override=red), source(mapping_override=blue)
    alternating = bits((np.floor(DETAIL_SAMPLES[:, 2] * 16).astype(int) % 2) == 0) & VOLUME_MASK
    sources = ((first, alternating), (second, VOLUME_MASK ^ alternating))
    if reverse:
        sources = tuple(reversed(sources))
    part = replace(first, shape="extreme", detail_sources=sources, detail_surface=VOLUME_MASK)
    painted = extreme.paint_target(part, "color", ("copycats",), State("minecraft:iron_block"))
    assert painted.name == "copycats:copycat_byte"
    assert painted.copied_material == (blue if reverse else red)
    assert painted.copied_materials == ()
