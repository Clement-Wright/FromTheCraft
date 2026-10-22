"""Fit target blocks to the union of source geometry, before choosing a material."""

from functools import lru_cache
from itertools import product

import numpy as np

from .model import State

# Stratify each thickness axis at 1/16; the other two axes sample each octant.
# This resolves 1/8 layers, 3/16 panels and 1/2 bytes without a 16³ grid per cell.
DETAIL_SAMPLES = np.concatenate(
    [
        np.asarray(
            list(
                product(
                    *[(np.arange(16) + 0.5) / 16 if a == axis else (0.13, 0.37, 0.63, 0.87) for a in range(3)]
                )
            )
        )
        for axis in range(3)
    ]
)
OCTANTS = (DETAIL_SAMPLES >= 0.5).astype(int) @ [4, 2, 1]
BYTE_SLOTS = tuple(
    f"{y}_{z}{x}" for x in ("west", "east") for y in ("bottom", "top") for z in ("north", "south")
)


def bits(mask):
    return int.from_bytes(np.packbits(mask, bitorder="little").tobytes(), "little")


def state(name, **properties):
    return State(name, tuple(sorted({"waterlogged": "false", **properties}.items())))


@lru_cache(maxsize=1)
def candidates():
    from .copycats import geometry_boxes

    states = []
    directions = ("up", "down", "east", "west", "south", "north")
    for facing in directions:
        states.extend(state("copycats:copycat_layer", facing=facing, layers=str(n)) for n in range(1, 8))
        states.append(state("create:copycat_panel", facing=facing))
        for offset in ("north", "south", "east", "west"):
            states.append(state("copycats:copycat_half_panel", facing=facing, offset=offset))
        for mask in range(1, 16):
            states.append(
                state(
                    "copycats:copycat_byte_panel",
                    facing=facing,
                    **{
                        slot: str(bool(mask & (1 << i))).lower()
                        for i, slot in enumerate(("bottom_right", "bottom_left", "top_right", "top_left"))
                    },
                )
            )
    for facing in ("north", "south", "east", "west"):
        for half in ("bottom", "top"):
            states.append(state("create:copycat_step", facing=facing, half=half))
    for axis in "xyz":
        states.append(state("copycats:copycat_beam", axis=axis))
    for mask in range(1, 64):
        states.append(
            state(
                "copycats:copycat_board",
                **{side: str(bool(mask & (1 << i))).lower() for i, side in enumerate(directions)},
            )
        )
    for facing in ("north", "south", "east", "west"):
        states.append(state("copycats:copycat_vertical_step", facing=facing))
        for n in range(1, 8):
            states.append(state("copycats:copycat_vertical_slice", facing=facing, layers=str(n)))
            for half in ("bottom", "top"):
                for family in ("slice", "corner_slice"):
                    states.append(
                        state("copycats:copycat_" + family, facing=facing, half=half, layers=str(n))
                    )
    result = []
    for target in states:
        occupied = np.zeros(len(DETAIL_SAMPLES), dtype=bool)
        for _, box in geometry_boxes(target):
            occupied |= np.all((DETAIL_SAMPLES >= box[:3]) & (DETAIL_SAMPLES <= box[3:]), axis=1)
        result.append((target, bits(occupied)))
    return tuple(result)


@lru_cache(maxsize=1)
def half_layer_options():
    from .copycats import geometry_boxes

    options = []
    placements = [
        ("half_layer", {"axis": axis, "half": half}) for axis in ("x", "z") for half in ("top", "bottom")
    ]
    placements += [
        (family, {"facing": facing})
        for family in ("vertical_half_layer", "stacked_half_layer")
        for facing in ("north", "south", "east", "west")
    ]
    for family, properties in placements:
        target = state("copycats:copycat_" + family, **properties, negative_layers="0", positive_layers="0")
        groups = []
        for slot in ("negative_layers", "positive_layers"):
            variants = []
            for n in range(9):
                props = {**dict(target.properties), slot: str(n)}
                occupied = np.zeros(len(DETAIL_SAMPLES), dtype=bool)
                for _, box in geometry_boxes(State(target.name, tuple(sorted(props.items())))):
                    occupied |= np.all((DETAIL_SAMPLES >= box[:3]) & (DETAIL_SAMPLES < box[3:]), axis=1)
                variants.append(bits(occupied))
            groups.append(variants)
        options.append((target, groups))
    return tuple(options)


@lru_cache(maxsize=8192)
def fit_detail(mask):
    full = (1 << len(DETAIL_SAMPLES)) - 1
    if mask == full:
        return None
    occupied = np.asarray([bool(mask & (1 << i)) for i in range(len(DETAIL_SAMPLES))])
    byte_mask = sum(1 << i for i in range(8) if occupied[OCTANTS == i].mean() >= 0.5)
    # Keep tiny nonzero details if no octant reaches the majority threshold.
    if not byte_mask:
        counts = [occupied[OCTANTS == i].sum() for i in range(8)]
        byte_mask = 1 << int(np.argmax(counts))
    byte = state(
        "copycats:copycat_byte",
        **{slot: str(bool(byte_mask & (1 << i))).lower() for i, slot in enumerate(BYTE_SLOTS)},
    )
    byte_bits = bits(np.asarray([bool(byte_mask & (1 << i)) for i in OCTANTS]))
    # Prefer a full block on ties, then continuous layers/panels, then discrete bytes.
    choices = [(None, full), *candidates(), (byte, byte_bits)]
    for target, groups in half_layer_options():
        levels = [min(range(9), key=lambda n: (mask ^ variants[n]).bit_count()) for variants in groups]
        if not any(levels):
            continue
        properties = {
            **dict(target.properties),
            "negative_layers": str(levels[0]),
            "positive_layers": str(levels[1]),
        }
        choices.append(
            (
                State(target.name, tuple(sorted(properties.items()))),
                groups[0][levels[0]] | groups[1][levels[1]],
            )
        )

    def error(item):
        target, occupied_bits = item
        difference = (mask ^ occupied_bits).bit_count()
        if target and difference:
            # Prefer a continuous layer over a broken footprint for a tiny fit gain.
            difference += {
                "copycats:copycat_half_panel": 4,
                "copycats:copycat_byte_panel": 4,
                "copycats:copycat_byte": 4,
                "create:copycat_panel": 1,
            }.get(target.name, 0)
        return difference

    return min(choices, key=error)[0]
