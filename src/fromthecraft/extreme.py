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
    byte_candidate,
    detail_choices,
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
    choices = (*extra_candidates(), *detail_choices(mask))
    return min(
        choices,
        key=lambda item: (
            (mask & ~item[1]).bit_count(),
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
    unique = np.unique(np.column_stack((positions, indices)), axis=0)
    for x, y, z, index in unique:
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
def surface_mask(mask):
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
    from .palettes import mc_target
    from .copycats import MULTI_SLOTS

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
        material = mc_target(replace(source, shape="box", detail_sources=()), preference, mods)
        materials[material] = materials.get(material, 0) | visible
    if len(materials) < 2:
        material = next(iter(materials), base)
        return replace(target, copied_material=material) if target else material

    # Bytes keep eight independently painted half-block regions without changing
    # the fitted hull. A slab/step may have an identical byte occupancy as well.
    if target is None or target.name not in MULTI_SLOTS:
        byte, occupied = byte_candidate(target_mask(target))
        if occupied == target_mask(target):
            target = byte
    boundary = part.detail_surface or surface_mask(target_mask(target))

    def select(mask):
        choices = []
        for material, source_mask in materials.items():
            shared = source_mask & mask
            if shared:
                # Give a concentrated small accent a chance to occupy a target
                # piece instead of always losing to the surrounding hull color.
                count = shared.bit_count() + 8 * (shared & boundary).bit_count()
                total = source_mask.bit_count() + 8 * (source_mask & boundary).bit_count()
                choices.append((count / total, count, material))
        return max(choices, key=lambda item: item[:2])[2] if choices else base

    if target and target.name in MULTI_SLOTS:
        painted = tuple((slot, select(mask)) for slot, mask in slot_masks(target))
        if len({material for _, material in painted}) > 1:
            return replace(target, copied_material=None, copied_materials=painted)
        return replace(target, copied_material=painted[0][1] if painted else base)
    material = select(target_mask(target))
    return replace(target, copied_material=material) if target else material
