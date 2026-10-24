from itertools import product, islice
from dataclasses import replace
from collections import deque
from functools import lru_cache

import numpy as np

from .ftd_shapes import planes
from .model import MAX_AXIS, MAX_PARTS, MAX_VOLUME, Cancelled, Scene

# FtD's 24 discrete orientations, forward and up. Right = up cross forward.
FORWARD = (
    [(0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0)]
    + [(0, -1, 0)] * 4
    + [(0, 1, 0)] * 4
    + [
        (0, 0, 1),
        (1, 0, 0),
        (0, 0, -1),
        (-1, 0, 0),
        (0, 0, 1),
        (0, 0, -1),
        (0, 0, 1),
        (0, 0, -1),
        (1, 0, 0),
        (-1, 0, 0),
        (1, 0, 0),
        (-1, 0, 0),
    ]
)
UP = (
    [(0, 1, 0)] * 4
    + [(0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0)] * 2
    + [(0, -1, 0)] * 4
    + [(1, 0, 0), (1, 0, 0), (-1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, 1), (0, 0, -1), (0, 0, -1)]
)

_ROTATIONS = tuple(
    np.column_stack((np.cross(up, forward), up, forward)).astype(float) for forward, up in zip(FORWARD, UP)
)


def rotation(index: int) -> np.ndarray:
    if not 0 <= index < 24:
        raise ValueError(f"Invalid FtD block rotation: {index}")
    return _ROTATIONS[index].copy()


def quaternion(values) -> np.ndarray:
    x, y, z, w = np.asarray(values, dtype=float)
    length = np.linalg.norm([x, y, z, w])
    if not np.isfinite(length) or length < 1e-8:
        raise ValueError("Invalid construct quaternion")
    x, y, z, w = np.array([x, y, z, w]) / length
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


@lru_cache(maxsize=1024)
def _corners(size):
    result = np.array(list(product(*[(0, n) for n in size])))
    result.flags.writeable = False
    return result


def bounds(scene: Scene, scale=1):
    if not scene.parts:
        return np.zeros(3), np.zeros(3)
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    for part in scene.parts:
        corners = _corners(tuple(part.size))
        points = (corners @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
        low, high = np.minimum(low, points.min(0)), np.maximum(high, points.max(0))
    return low, high


def checked_size(size):
    if len(size) != 3 or any(int(n) != n or n <= 0 or n > MAX_AXIS for n in size):
        raise ValueError(f"Dimensions must be 1–{MAX_AXIS} cells on each axis")
    if int(np.prod(size, dtype=np.int64)) > MAX_VOLUME:
        raise ValueError(f"Structure exceeds the {MAX_VOLUME:,}-cell bounding-volume limit")
    return tuple(int(n) for n in size)


def contains(shape, points):
    x, y, z = points.T
    inside = np.all((points >= -1e-8) & (points <= 1 + 1e-8), axis=1)
    clipping = planes(shape)
    if clipping:
        coefficients = np.asarray(clipping)
        inside &= np.all(points @ coefficients[:, :3].T <= coefficients[:, 3] + 1e-8, axis=1)
    elif shape == "wedge":
        inside &= y <= z + 1e-8
    elif shape == "curve":
        inside &= y * y + (1 - z) ** 2 <= 1 + 1e-8
    elif shape == "corner":
        inside &= (y <= z + 1e-8) & (y <= x + 1e-8)
    elif shape.startswith("stairs"):
        high = z >= 0.5
        if "inner_left" in shape:
            high |= x >= 0.5
        elif "inner_right" in shape:
            high |= x <= 0.5
        elif "outer_left" in shape:
            high &= x >= 0.5
        elif "outer_right" in shape:
            high &= x <= 0.5
        inside &= (y < 0.5) | high
    return inside


SAMPLES = np.array(list(product((0.25, 0.75), repeat=3)))


def cell_shape(mask):
    if mask.all():
        return "box"
    for axis in (1, 0, 2):
        bottom = SAMPLES[:, axis] < 0.5
        prefix = "slab_" if axis == 1 else f"slab_{'xyz'[axis]}_"
        if np.array_equal(mask, bottom):
            return prefix + "bottom"
        if np.array_equal(mask, ~bottom):
            return prefix + "top"
    bottom = SAMPLES[:, 1] < 0.5
    for facing, axis, positive in (
        ("south", 2, True),
        ("north", 2, False),
        ("east", 0, True),
        ("west", 0, False),
    ):
        high = (SAMPLES[:, axis] > 0.5) if positive else (SAMPLES[:, axis] < 0.5)
        for half, base in (("bottom", bottom), ("top", ~bottom)):
            if np.array_equal(mask, base | high):
                return f"step_{facing}_{half}"
    return "box"


@lru_cache(maxsize=256)
def _cell_shape_bits(mask):
    return cell_shape(np.asarray([bool(mask & (1 << bit)) for bit in range(8)]))


@lru_cache(maxsize=256)
def _detail_octants(mask):
    from .detail import DETAIL_SAMPLES

    selected = np.asarray([bool(mask & (1 << bit)) for bit in range(8)])
    octants = (DETAIL_SAMPLES >= 0.5).astype(int) @ [4, 2, 1]
    return int.from_bytes(np.packbits(selected[octants], bitorder="little").tobytes(), "little")


def cell_candidates(low, high):
    """Generate product(x, y, z) order without Python tuples per output cell."""
    size = high - low
    if np.any(size <= 0):
        return np.empty((0, 3), dtype=int)
    indices = np.arange(int(np.prod(size)), dtype=int)
    result = np.empty((len(indices), 3), dtype=int)
    result[:, 0] = indices // (size[1] * size[2]) + low[0]
    result[:, 1] = indices // size[2] % size[1] + low[1]
    result[:, 2] = indices % size[2] + low[2]
    return result


def candidate_batches(low, high, batch_size):
    """The original product order and batch boundaries, with bounded storage."""
    size = high - low
    if np.any(size <= 0):
        return
    total = int(np.prod(size))
    for start in range(0, total, batch_size):
        indices = np.arange(start, min(total, start + batch_size), dtype=int)
        result = np.empty((len(indices), 3), dtype=int)
        result[:, 0] = indices // (size[1] * size[2]) + low[0]
        result[:, 1] = indices // size[2] % size[1] + low[1]
        result[:, 2] = indices % size[2] + low[2]
        yield result


def merge_seed_masks(seed_masks, keys, octants, occupancy):
    """Combine duplicates with integer operations while retaining insertion order."""
    if len(keys) > 32:
        unique, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
        masks = np.zeros(len(unique), dtype=np.uint8)
        np.bitwise_or.at(masks, inverse, np.left_shift(np.uint8(1), np.asarray(octants, dtype=np.uint8)))
        order = np.argsort(first)
        for index in order:
            key = tuple(unique[index])
            if key not in occupancy:
                seed_masks[key] = seed_masks.get(key, 0) | int(masks[index])
    else:
        for position, octant in zip(keys, octants):
            key = tuple(position)
            if key not in occupancy:
                seed_masks[key] = seed_masks.get(key, 0) | (1 << int(octant))


def voxelize(scene: Scene, scale=1, progress=None, cancelled=None, detailed=False, extreme=False):
    from concurrent.futures import ThreadPoolExecutor

    workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mesh-samples")
    wait_for_workers = True
    try:
        return _voxelize(scene, scale, progress, cancelled, detailed, extreme, workers)
    except Cancelled:
        # Running chunks retain their own read-only inputs and discard results.
        # Do not hold up cancellation while those bounded queries finish.
        wait_for_workers = False
        raise
    finally:
        workers.shutdown(wait=wait_for_workers, cancel_futures=True)


def _voxelize(scene, scale, progress, cancelled, detailed, extreme, workers):
    from .detail import DETAIL_SAMPLES, fit_detail

    detailed = detailed or extreme
    samples = DETAIL_SAMPLES if detailed else SAMPLES
    sample_count = len(samples)
    full_mask = (1 << sample_count) - 1
    cells, occupancy, fallback = {}, {}, {}
    contributions = {}
    from .mesh_geometry import MeshSamplerCache

    samplers = MeshSamplerCache()
    low, high = bounds(scene, scale)
    origin = np.floor(low + 1e-6).astype(int)
    checked_size(np.maximum(1, np.ceil(high - 1e-6).astype(int) - origin))
    for index, part in enumerate(scene.parts):
        if extreme:
            from .extreme import appearance_key, record_contribution

            appearance = appearance_key(part)
        if index % 64 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(index / max(1, len(scene.parts)) * 0.75)
        corners = _corners(tuple(part.size))
        world = (corners @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
        pmin, pmax = np.floor(world.min(0) + 1e-7).astype(int), np.ceil(world.max(0) - 1e-7).astype(int)
        if int(np.prod(pmax - pmin)) > MAX_PARTS:
            raise ValueError("One part's sampled footprint is too large; choose a smaller scale")
        if np.any(pmax <= pmin):
            continue
        # Boxes on integer grid boundaries need no occupancy samples.
        aligned = np.allclose(part.transform[:3, :3], np.round(part.transform[:3, :3]))
        grid_box = np.allclose(world, np.round(world), rtol=0, atol=1e-7)
        solid_box = part.shape == "box" and aligned and grid_box
        inv = None if solid_box else np.linalg.inv(part.transform)
        mesh_sampler = None
        sampled = set() if extreme else None
        if part.mesh:
            verts, indices, closed, thickness, span = part.mesh
            mesh_sampler = samplers.get(verts * span, indices, thickness, cancelled, closed)
            mesh_sampler.executor = workers
        # Keep the denser detail grid within the former sampling memory budget.
        batch_size = max(1, 1_572_864 // sample_count)
        full_group = {appearance: (part, full_mask)} if extreme else None
        for batch in candidate_batches(pmin, pmax, batch_size):
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            masks = None
            if not solid_box:
                # Union with an already full cell cannot change either its
                # occupancy or the first contributor that owns its material.
                if occupancy:
                    batch = batch[
                        [
                            (
                                contributions.get(tuple(position - origin), {}).get(appearance, (None, 0))[1]
                                if extreme
                                else occupancy.get(tuple(position - origin), 0)
                            )
                            != full_mask
                            for position in batch
                        ]
                    ]
                    if not len(batch):
                        continue
                points = (batch[:, None, :] + samples).reshape(-1, 3) / scale
                local = (points @ inv[:3, :3].T + inv[:3, 3]) / part.size
                masks = (
                    mesh_sampler.contains(local * span) if mesh_sampler else contains(part.shape, local)
                ).reshape(-1, sample_count)
            packed = np.packbits(masks, axis=1, bitorder="little") if masks is not None else None
            for row, position in enumerate(batch):
                bits = full_mask if packed is None else int.from_bytes(packed[row], "little")
                if bits:
                    key = tuple(position - origin)
                    previous = occupancy.get(key, 0)
                    occupancy[key] = (
                        full_mask if bits == full_mask or previous == full_mask else previous | bits
                    )
                    cells.setdefault(key, part)
                    if extreme:
                        sampled.add(key)
                        if key not in contributions and bits == full_mask:
                            contributions[key] = full_group
                        else:
                            # A shared full-wall group is immutable. Copy before
                            # applying a later cell-local contributor or overlay.
                            group = contributions.get(key, {}).copy()
                            contributions[key] = group
                            record_contribution(group, part, appearance, bits)
        # Forward sampling protects small features that fall between target sample centers.
        if not aligned or min(part.size) * scale < 0.5 or part.shape != "box":
            axes = [
                np.r_[
                    1e-4,
                    (np.arange(max(1, int(np.ceil(n * scale * 2)))) + 0.5)
                    / max(1, int(np.ceil(n * scale * 2))),
                    1 - 1e-4,
                ]
                for n in part.size
            ]
            seed_masks = {}
            from .mesh_geometry import surface_seed_batches

            source_seeds = iter(product(*axes))
            seed_batches = (
                surface_seed_batches(part, scale, cancelled)
                if part.mesh
                else iter(lambda: list(islice(source_seeds, 4096)), [])
            )
            for batch in seed_batches:
                if cancelled and cancelled():
                    raise Cancelled("Conversion cancelled")
                seeds = np.asarray(batch)
                seeds = seeds * part.size if mesh_sampler else seeds[contains(part.shape, seeds)] * part.size
                world_seeds = (seeds @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
                positions = np.floor(world_seeds + 1e-7).astype(int)
                if extreme:
                    from .extreme import merge_fine_seeds

                    merge_fine_seeds(seed_masks, positions - origin, world_seeds - positions, sampled)
                else:
                    octants = (world_seeds - positions >= 0.5).astype(int) @ [4, 2, 1]
                    merge_seed_masks(seed_masks, positions - origin, octants, occupancy)
            for position, mask in seed_masks.items():
                if extreme:
                    occupancy[position] = occupancy.get(position, 0) | mask
                    cells.setdefault(position, part)
                    group = contributions.get(position, {}).copy()
                    contributions[position] = group
                    record_contribution(group, part, appearance, mask)
                    continue
                previous, owner = fallback.get(position, (0, part))
                if detailed:
                    mask = _detail_octants(mask)
                fallback[position] = (previous | mask, owner)
        if len(cells) > MAX_PARTS:
            raise ValueError(
                f"Output exceeds {MAX_PARTS:,} occupied cells; choose a smaller scale or structure"
            )
    if cancelled and cancelled():
        raise Cancelled("Conversion cancelled")
    for position, (mask, part) in fallback.items():
        if position not in occupancy:
            occupancy[position], cells[position] = mask, part
            if extreme:
                contributions[position] = {appearance_key(part): (part, mask)}
    if len(cells) > MAX_PARTS:
        raise ValueError(f"Output exceeds {MAX_PARTS:,} occupied cells; choose a smaller scale or structure")
    for index, (position, part) in enumerate(cells.items()):
        if index % 256 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(0.75 + 0.03 * index / max(1, len(cells)))
        mask = occupancy[position]
        if extreme:
            from .extreme import fit_extreme, exposed_samples

            neighbors = []
            for axis in range(3):
                for direction in (-1, 1):
                    other = list(position)
                    other[axis] += direction
                    neighbors.append(occupancy.get(tuple(other), 0))

            cells[position] = replace(
                part,
                shape="extreme",
                state=fit_extreme(mask),
                detail_sources=tuple(contributions[position].values()),
                detail_surface=exposed_samples(mask, tuple(neighbors)),
            )
        elif detailed:
            target = fit_detail(mask)
            cells[position] = (
                replace(part, shape="detailed", state=target) if target else replace(part, shape="box")
            )
        else:
            cells[position] = replace(part, shape=_cell_shape_bits(mask))
    return cells, tuple(float(n) for n in origin)


def hollow_cells(cells, thickness=1, cancelled=None, progress=None):
    """Keep cells within the requested face-neighbor distance of exterior air."""
    if thickness not in (1, 2, 3, 4):
        raise ValueError("Shell thickness must be 1, 2, 3, or 4 cells")
    if cancelled and cancelled():
        raise Cancelled("Conversion cancelled")
    if not cells:
        return {}
    positions = np.asarray(list(cells), dtype=np.intp)
    size = positions.max(0) + 1
    checked_size(size)
    # Scan air along the longest axis, so long narrow structures need fewer spans.
    order = np.argsort(-size)
    points = positions[:, order] + 1
    solid = np.zeros(tuple(size[order] + 2), dtype=bool, order="F")
    solid[tuple(points.T)] = True
    outside = np.zeros_like(solid)
    pending = deque([(0, 0, 0)])
    spans = 0
    while pending:
        x, y, z = pending.popleft()
        if outside[x, y, z] or solid[x, y, z]:
            continue
        if spans % 128 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(0.78)
        clear = ~(solid[:, y, z] | outside[:, y, z])
        before = np.flatnonzero(~clear[:x])
        after = np.flatnonzero(~clear[x + 1 :])
        left = int(before[-1] + 1) if len(before) else 0
        right = int(x + 1 + after[0]) if len(after) else len(clear)
        outside[left:right, y, z] = True
        for ny, nz in ((y - 1, z), (y + 1, z), (y, z - 1), (y, z + 1)):
            if not (0 <= ny < solid.shape[1] and 0 <= nz < solid.shape[2]):
                continue
            free = ~(solid[left:right, ny, nz] | outside[left:right, ny, nz])
            starts = np.flatnonzero(free & ~np.r_[False, free[:-1]])
            pending.extend((left + int(start), ny, nz) for start in starts)
        spans += 1
    # Expand through grid cells after finding exterior air; sealed cavities stay sealed.
    for _ in range(thickness):
        if cancelled and cancelled():
            raise Cancelled("Conversion cancelled")
        grown = outside.copy()
        for axis in range(3):
            lower, upper = [slice(None)] * 3, [slice(None)] * 3
            lower[axis], upper[axis] = slice(None, -1), slice(1, None)
            grown[tuple(lower)] |= outside[tuple(upper)]
            grown[tuple(upper)] |= outside[tuple(lower)]
        outside = grown
    keep = outside[tuple(points.T)]
    if progress:
        progress(0.88)
    return {position: part for (position, part), retained in zip(cells.items(), keep) if retained}
