"""Fit target blocks to the union of source geometry, before choosing a material."""

from functools import lru_cache
from itertools import product

import numpy as np

from fromthecraft.model import State

# Resolve every 1/16 target interval in all three axes. Coarser stratified
# grids miss slice intersections or land on boards' inner boundaries.
VOLUME_SAMPLES = np.asarray(list(product((np.arange(16) + 0.5) / 16, repeat=3)))
_rays = (np.arange(16) + 0.5) / 16
# Probe near both ends of each ray so a thin hull face cannot fall between
# interior samples. These probes constrain coverage, not estimated volume.
DETAIL_SAMPLES = np.concatenate(
    [VOLUME_SAMPLES]
    + [
        np.asarray(list(product(*[(0.0001, 0.9999) if a == axis else _rays for a in range(3)])))
        for axis in range(3)
    ]
)
VOLUME_MASK = (1 << len(VOLUME_SAMPLES)) - 1
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
    from fromthecraft.copycats import geometry_boxes

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
    from fromthecraft.copycats import geometry_boxes

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
def _bounds(mask):
    selected = DETAIL_SAMPLES[[bool(mask & (1 << i)) for i in range(len(DETAIL_SAMPLES))]]
    return (selected.min(0), selected.max(0)) if len(selected) else (np.zeros(3), np.zeros(3))


def silhouette_error(mask, candidate):
    low, high = _bounds(mask)
    other_low, other_high = _bounds(candidate)
    return max(0, float(np.max(low - other_low)), float(np.max(other_high - high)))


@lru_cache(maxsize=8192)
def fit_detail(mask, compact=False):
    full = (1 << len(DETAIL_SAMPLES)) - 1
    if mask == full:
        return None
    occupied = np.asarray([bool(mask & (1 << i)) for i in range(len(DETAIL_SAMPLES))])
    byte_mask = sum(1 << i for i in range(8) if occupied[OCTANTS == i].any())
    byte = state(
        "copycats:copycat_byte",
        **{slot: str(bool(byte_mask & (1 << i))).lower() for i, slot in enumerate(BYTE_SLOTS)},
    )
    byte_bits = bits(np.asarray([bool(byte_mask & (1 << i)) for i in OCTANTS]))
    # Prefer a full block on ties, then continuous layers/panels, then discrete bytes.
    choices = [(None, full), *candidates(), (byte, byte_bits)]
    for target, groups in half_layer_options():
        levels = [min(range(9), key=lambda n: (mask ^ variants[n]).bit_count()) for variants in groups]
        # Also offer an outward-rounded profile. The least-volume fit can leave
        # a zero-height half at a slope tip, opening a hole in a continuous hull.
        covering = [
            next(n for n in range(9) if not (mask & variants[8]) & ~variants[n]) for variants in groups
        ]
        for negative, positive in dict.fromkeys((tuple(levels), tuple(covering))):
            if not (negative or positive):
                continue
            properties = {
                **dict(target.properties),
                "negative_layers": str(negative),
                "positive_layers": str(positive),
            }
            choices.append(
                (
                    State(target.name, tuple(sorted(properties.items()))),
                    groups[0][negative] | groups[1][positive],
                )
            )

    def error(item):
        target, occupied_bits = item
        difference = ((mask ^ occupied_bits) & VOLUME_MASK).bit_count()
        if target and difference:
            # Prefer a continuous layer over a broken footprint for a tiny fit gain.
            difference += {
                "copycats:copycat_half_panel": 4,
                "copycats:copycat_byte_panel": 4,
                "copycats:copycat_byte": 4,
                "create:copycat_panel": 1,
            }.get(target.name, 0)
        # Retain the sampled solid, including near-face probes, before reducing
        # excess volume. Projections alone allow open boards to replace a solid
        # corner and leave gaps when viewed from an oblique angle.
        missing = (mask & ~occupied_bits).bit_count()
        if compact:
            return missing, silhouette_error(mask, occupied_bits), difference
        return missing, difference

    return min(choices, key=error)[0]
