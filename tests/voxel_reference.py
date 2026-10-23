"""Frozen pre-optimization cell merging and ordering for exact export checks."""

from itertools import product, islice
from dataclasses import replace
import numpy as np
from fromthecraft.model import MAX_PARTS, Cancelled, Scene
from fromthecraft.geometry import bounds, checked_size, contains, SAMPLES, cell_shape


def reference_voxelize(scene: Scene, scale=1, progress=None, cancelled=None, detailed=False):
    from fromthecraft.detail import DETAIL_SAMPLES, fit_detail

    samples = DETAIL_SAMPLES if detailed else SAMPLES
    sample_count = len(samples)
    full_mask = (1 << sample_count) - 1
    cells, occupancy, fallback = {}, {}, {}
    low, high = bounds(scene, scale)
    origin = np.floor(low + 1e-6).astype(int)
    checked_size(np.maximum(1, np.ceil(high - 1e-6).astype(int) - origin))
    for index, part in enumerate(scene.parts):
        if index % 64 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(index / max(1, len(scene.parts)) * 0.75)
        corners = np.array(list(product(*[(0, n) for n in part.size])))
        world = (corners @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
        pmin, pmax = np.floor(world.min(0) + 1e-7).astype(int), np.ceil(world.max(0) - 1e-7).astype(int)
        if int(np.prod(pmax - pmin)) > MAX_PARTS:
            raise ValueError("One part's sampled footprint is too large; choose a smaller scale")
        candidates = np.array(list(product(*[range(a, b) for a, b in zip(pmin, pmax)])))
        if len(candidates) == 0:
            continue
        # Boxes on integer grid boundaries need no occupancy samples.
        aligned = np.allclose(part.transform[:3, :3], np.round(part.transform[:3, :3]))
        grid_box = np.allclose(world, np.round(world), rtol=0, atol=1e-7)
        solid_box = part.shape == "box" and aligned and grid_box
        inv = None if solid_box else np.linalg.inv(part.transform)
        mesh_sampler = None
        if part.mesh:
            from mesh_reference import ReferenceMeshSampler as MeshSampler

            verts, indices, closed, thickness, span = part.mesh
            mesh_sampler = MeshSampler(verts * span, indices, thickness, cancelled, closed)
        # Keep the denser detail grid within the former sampling memory budget.
        batch_size = max(1, 1_572_864 // sample_count)
        for start in range(0, len(candidates), batch_size):
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            batch = candidates[start : start + batch_size]
            masks = None
            if not solid_box:
                points = (batch[:, None, :] + samples).reshape(-1, 3) / scale
                local = (points @ inv[:3, :3].T + inv[:3, 3]) / part.size
                masks = (
                    mesh_sampler.contains(local * span) if mesh_sampler else contains(part.shape, local)
                ).reshape(-1, sample_count)
            for row, position in enumerate(batch):
                mask = masks[row] if masks is not None else None
                if mask is None or mask.any():
                    key = tuple(position - origin)
                    bits = (
                        full_mask
                        if mask is None
                        else int.from_bytes(np.packbits(mask, bitorder="little").tobytes(), "little")
                    )
                    occupancy[key] = occupancy.get(key, 0) | bits
                    cells.setdefault(key, part)
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
            from mesh_reference import reference_surface_seeds as surface_seeds

            source_seeds = surface_seeds(part, scale, cancelled) if part.mesh else product(*axes)
            while batch := list(islice(source_seeds, 4096)):
                if cancelled and cancelled():
                    raise Cancelled("Conversion cancelled")
                seeds = np.asarray(batch)
                seeds = seeds * part.size if mesh_sampler else seeds[contains(part.shape, seeds)] * part.size
                world_seeds = (seeds @ part.transform[:3, :3].T + part.transform[:3, 3]) * scale
                positions = np.floor(world_seeds + 1e-7).astype(int)
                octants = ((world_seeds - positions >= 0.5).astype(int) @ [4, 2, 1]).tolist()
                for position, octant in zip(positions, octants):
                    key = tuple(position - origin)
                    if key not in occupancy:
                        seed_masks[key] = seed_masks.get(key, 0) | (1 << octant)
            for position, mask in seed_masks.items():
                previous, owner = fallback.get(position, (0, part))
                if detailed:
                    selected = np.asarray([bool(mask & (1 << bit)) for bit in range(8)])
                    octants = (samples >= 0.5).astype(int) @ [4, 2, 1]
                    mask = int.from_bytes(
                        np.packbits(selected[octants], bitorder="little").tobytes(), "little"
                    )
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
    if len(cells) > MAX_PARTS:
        raise ValueError(f"Output exceeds {MAX_PARTS:,} occupied cells; choose a smaller scale or structure")
    for index, (position, part) in enumerate(cells.items()):
        if index % 256 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(0.75 + 0.03 * index / max(1, len(cells)))
        mask = occupancy[position]
        if detailed:
            target = fit_detail(mask)
            cells[position] = (
                replace(part, shape="detailed", state=target) if target else replace(part, shape="box")
            )
        else:
            occupied = np.asarray([bool(mask & (1 << bit)) for bit in range(8)])
            cells[position] = replace(part, shape=cell_shape(occupied))
    return cells, tuple(float(n) for n in origin)

