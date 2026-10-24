"""Fit target blocks to the union of source geometry, before choosing a material."""

from functools import lru_cache
from itertools import product

import numpy as np

from .model import State

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


OCTANT_MASKS = tuple(bits(OCTANTS == i) for i in range(8))
FULL_MASK = (1 << len(DETAIL_SAMPLES)) - 1

_PROJECTIONS = tuple(
    tuple(
        (float(value), bits(DETAIL_SAMPLES[:, axis] == value)) for value in np.unique(DETAIL_SAMPLES[:, axis])
    )
    for axis in range(3)
)


@lru_cache(maxsize=8192)
def projected_bounds(mask):
    """Sample extents, including hull probes, without unpacking per candidate."""
    return tuple(
        (
            next((value for value, plane in planes if mask & plane), 0),
            next((value for value, plane in reversed(planes) if mask & plane), 0),
        )
        for planes in _PROJECTIONS
    )


def extent_error(occupied, source_bounds):
    # A whole-height 1/16 board can be smaller in volume than a compact panel.
    # First avoid extending its silhouette into empty space beside a small trim.
    return max(
        max(0, source_low - low, high - source_high)
        for (low, high), (source_low, source_high) in zip(projected_bounds(occupied), source_bounds)
    )


def byte_candidate(mask):
    selected = tuple(bool(mask & octant) for octant in OCTANT_MASKS)
    target = state(
        "copycats:copycat_byte",
        **{slot: str(value).lower() for slot, value in zip(BYTE_SLOTS, selected)},
    )
    return target, sum(octant for octant, value in zip(OCTANT_MASKS, selected) if value)


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


def _covering_level(mask, variants):
    wanted = mask & variants[8]
    low, high = 0, 8
    while low < high:
        middle = (low + high) // 2
        if wanted & ~variants[middle]:
            low = middle + 1
        else:
            high = middle
    return low


def detail_choices(mask, covering_only=False):
    # Prefer a full block on ties, then continuous layers/panels, then discrete bytes.
    choices = [(None, FULL_MASK), *candidates(), byte_candidate(mask)]
    for target, groups in half_layer_options():
        # Also offer an outward-rounded profile. The least-volume fit can leave
        # a zero-height half at a slope tip, opening a hole in a continuous hull.
        covering = tuple(_covering_level(mask, variants) for variants in groups)
        pairs = [covering]
        if not covering_only:
            levels = tuple(
                min(range(9), key=lambda n: (mask ^ variants[n]).bit_count()) for variants in groups
            )
            pairs = dict.fromkeys((levels, covering))
        for negative, positive in pairs:
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
    return choices


@lru_cache(maxsize=8192)
def fit_detail(mask):
    if mask == FULL_MASK:
        return None

    source_bounds = projected_bounds(mask)

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
        return extent_error(occupied_bits, source_bounds), difference

    # The full-block candidate has zero missing samples, so a non-covering
    # candidate can never win. Nested half layers need only their least covering
    # levels: every larger covering level adds volume and the same block penalty.
    choices = (item for item in detail_choices(mask, covering_only=True) if not mask & ~item[1])
    return min(choices, key=error)[0]
