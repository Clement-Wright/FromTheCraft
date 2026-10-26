"""Opt-in fitting of visible smooth hulls and independently painted small pieces."""

from dataclasses import replace
from functools import lru_cache
from itertools import product

import numpy as np

from .detail import (
    DETAIL_SAMPLES,
    VOLUME_SAMPLES,
    FULL_MASK,
    VOLUME_MASK,
    bits,
    detail_choices,
    extent_error,
    projected_bounds,
    state,
)


@lru_cache(maxsize=2048)
def target_mask(target):
    if target is None:
        return FULL_MASK
    from .geometry import contains
    from .minecraft import scene_from_cells
    from collections import Counter

    occupied = np.zeros(len(DETAIL_SAMPLES), dtype=bool)
    for part in scene_from_cells({(0, 0, 0): target}, "nbt", Counter()).parts:
        inv = np.linalg.inv(part.transform)
        local = (DETAIL_SAMPLES @ inv[:3, :3].T + inv[:3, 3]) / part.size
        occupied |= contains(part.shape, local)
    return bits(occupied)


@lru_cache(maxsize=1)
def extra_candidates():
    targets = []
    for facing in ("south", "west", "north", "east"):
        targets.append(state("copycats:copycat_vertical_slope", facing=facing))
        for half in ("bottom", "top"):
            targets.append(state("copycats:copycat_slope", facing=facing, half=half))
            for layer in (1, 2, 3, 5, 6, 7):
                targets.append(
                    state("copycats:copycat_slope_layer", facing=facing, half=half, layers=str(layer))
                )
            for shape in ("straight", "inner_left", "inner_right", "outer_left", "outer_right"):
                targets.append(state("copycats:copycat_stairs", facing=facing, half=half, shape=shape))
    for axis, half in product("xyz", ("bottom", "top")):
        targets.append(state("copycats:copycat_slab", axis=axis, type=half))
    return tuple((target, target_mask(target)) for target in targets)


@lru_cache(maxsize=8192)
def fit_extreme(mask):
    if mask == FULL_MASK:
        return None
    # Smooth surfaces win exact geometric ties. The full-block fallback means
    # every sampled solid point can always be retained, including hull probes.
    choices = (*extra_candidates(), *detail_choices(mask, covering_only=True))
    source_bounds = projected_bounds(mask)
    return min(
        (item for item in choices if not mask & ~item[1]),
        key=lambda item: (
            extent_error(item[1], source_bounds),
            ((mask ^ item[1]) & VOLUME_MASK).bit_count(),
        ),
    )[0]


def appearance_key(part):
    return (part.material, tuple(part.color), part.transparent, part.mapping_override, part.decoration)


def record_contribution(group, part, appearance, mask):
    """Resolve source order before grouping equal paint appearances."""
    for key, (owner, occupied) in tuple(group.items()):
        if owner.decoration != part.decoration:
            continue
        if part.decoration:
            if key != appearance:
                group[key] = (owner, occupied & ~mask)
        else:
            mask &= ~occupied
    owner, previous = group.get(appearance, (part, 0))
    group[appearance] = (owner, previous | mask)


_VOLUME_FACES = tuple(
    (bits(VOLUME_SAMPLES[:, axis] < 1 / 16), bits(VOLUME_SAMPLES[:, axis] > 15 / 16)) for axis in range(3)
)
_PROBE_FACES = tuple(
    (bits(DETAIL_SAMPLES[:, axis] == 0.0001), bits(DETAIL_SAMPLES[:, axis] == 0.9999)) for axis in range(3)
)


@lru_cache(maxsize=2048)
def exposed_samples(mask, neighbors):
    volume = mask & VOLUME_MASK
    interior = volume
    probes = mask & ~VOLUME_MASK
    for axis, stride in enumerate((256, 16, 1)):
        low_face, high_face = _VOLUME_FACES[axis]
        before, after = neighbors[axis * 2 : axis * 2 + 2]
        lower = ((volume << stride) & ~low_face) | ((before & high_face) >> (15 * stride))
        upper = ((volume >> stride) & ~high_face) | ((after & low_face) << (15 * stride))
        interior &= lower & upper
        low_probe, high_probe = _PROBE_FACES[axis]
        # Probe pairs are separated by 256, 16 and 1 bits in their axis batches.
        probes &= ~(((before & high_probe) >> stride) | ((after & low_probe) << stride))
    return (volume & ~interior) | probes


def merge_fine_seeds(seed_masks, positions, fractions, sampled):
    """Keep unsampled features at 1/16 resolution, including their paint owner."""
    indices = np.clip((fractions * 16).astype(int), 0, 15) @ [256, 16, 1]
    positions = np.asarray(positions)
    if positions.dtype.kind == "i" and not np.any((positions < 0) | (positions >= 4096)):
        # Four bounded integer coordinates form one lexicographically ordered
        # 48-bit key. Scalar sorting avoids structured-row comparisons; unpack
        # back to the same integer rows and keep the original iteration order.
        p = positions.astype(np.uint64)
        packed = (p[:, 0] << 36) | (p[:, 1] << 24) | (p[:, 2] << 12) | indices.astype(np.uint64)
        keys = np.unique(packed)
        unique = np.empty((len(keys), 4), dtype=np.result_type(positions.dtype, indices.dtype))
        for axis, shift in enumerate((36, 24, 12, 0)):
            unique[:, axis] = (keys >> shift) & 4095
    else:
        unique = np.unique(np.column_stack((positions, indices)), axis=0)
    for x, y, z, index in unique.tolist():
        key = (x, y, z)
        if key not in sampled:
            seed_masks[key] = seed_masks.get(key, 0) | (1 << int(index))


@lru_cache(maxsize=2048)
def slot_masks(target):
    from .copycats import geometry_boxes

    boxes = geometry_boxes(target)
    return (
        tuple(
            (slot, bits(np.all((DETAIL_SAMPLES >= box[:3]) & (DETAIL_SAMPLES < box[3:]), axis=1)))
            for slot, box in boxes
        )
        if boxes
        else ()
    )


@lru_cache(maxsize=2048)
def material_partitions(target):
    """Split paint regions as finely as possible without changing the hull."""
    from .copycats import MULTI_SLOTS

    mask = target_mask(target)
    equivalents = [
        candidate
        for candidate, occupied in detail_choices(mask, covering_only=True)
        if candidate and candidate.name in MULTI_SLOTS and occupied == mask
    ]
    if target and target.name in MULTI_SLOTS:
        equivalents.insert(0, target)
    finest = max((len(slot_masks(candidate)) for candidate in equivalents), default=0)
    seen, result = set(), []
    for candidate in equivalents:
        regions = tuple(sorted(mask for _, mask in slot_masks(candidate)))
        if len(regions) == finest and regions not in seen:
            seen.add(regions)
            result.append(candidate)
    return tuple(result)


@lru_cache(maxsize=2048)
def surface_mask(mask):
    if isinstance(mask, int) and 0 <= mask <= FULL_MASK:
        volume = mask & VOLUME_MASK
        interior = volume
        for stride, (low_face, high_face) in zip((256, 16, 1), _VOLUME_FACES):
            interior &= ((volume << stride) & ~low_face) & ((volume >> stride) & ~high_face)
        return (volume & ~interior) | (mask & ~VOLUME_MASK)
    # Preserve conversion errors and byte-compatible inputs outside the integer fast path.
    packed = np.frombuffer(mask.to_bytes((len(DETAIL_SAMPLES) + 7) // 8, "little"), dtype=np.uint8)
    volume = np.unpackbits(packed, bitorder="little")[:4096].reshape(16, 16, 16).astype(bool)
    padded = np.pad(volume, 1)
    interior = volume.copy()
    for axis in range(3):
        for shift in (0, 2):
            slices = [slice(1, -1)] * 3
            slices[axis] = slice(shift, shift + 16)
            interior &= padded[tuple(slices)]
    return bits((volume & ~interior).ravel()) | (mask & ~VOLUME_MASK)


def paint_target(part, preference, mods, base):
    from .palettes import mc_target_material, mod_target

    target = part.state
    if not part.detail_sources:
        return replace(target, copied_material=base) if target else base
    # Structure keeps its first-owner rule; later visual decorations overlay it.
    sources = sorted(part.detail_sources, key=lambda item: item[0].decoration, reverse=True)
    covered, materials = 0, {}
    for source, mask in sources:
        if source.decoration:
            mask &= part.detail_surface
        visible = mask & ~covered
        covered |= mask
        if not visible:
            continue
        material = source.mapping_override or mc_target_material(source, preference)
        if not source.mapping_full and mods and source.mapping_override is None:
            material = mod_target(
                material, source.material, tuple(source.color), source.transparent, preference, mods
            )
        materials[material] = materials.get(material, 0) | visible
    if len(materials) < 2:
        material = next(iter(materials), base)
        return replace(target, copied_material=material) if target else material

    # A thin single-material panel/layer can have an identical byte-panel or
    # half-layer hull, allowing separate colors without making the detail thicker.
    boundary = part.detail_surface or surface_mask(target_mask(target))

    def select(mask):
        choices = []
        for material, source_mask in materials.items():
            shared = source_mask & mask
            if shared:
                # Paint each available piece with its locally dominant source.
                # Normalizing by a source's total footprint lets a single tiny
                # mark repaint a whole byte, turning fine lines into patches.
                count = shared.bit_count() + 8 * (shared & boundary).bit_count()
                choices.append((count, material))
        selected = max(choices, key=lambda item: item[0]) if choices else (0, base)
        return selected

    partitions = []
    for candidate in material_partitions(target):
        regions = slot_masks(candidate)
        selected = tuple(select(mask) for _, mask in regions)
        painted = tuple((slot, choice[1]) for (slot, _), choice in zip(regions, selected))
        agreement = sum(choice[0] for choice in selected)
        partitions.append((candidate, painted, agreement))
    if partitions:
        target, painted, _ = max(partitions, key=lambda item: item[2])
        if len({material for _, material in painted}) > 1:
            return replace(target, copied_material=None, copied_materials=painted)
        return replace(target, copied_material=painted[0][1] if painted else base)
    material = select(target_mask(target))[1]
    return replace(target, copied_material=material) if target else material
