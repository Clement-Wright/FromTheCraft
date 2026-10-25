from collections import Counter
from dataclasses import replace

import numpy as np

from .geometry import hollow_cells, voxelize
from .ftd import read_blueprint, write_blueprint
from .minecraft import read_litematic, read_structure, write_litematic, write_structure
from .model import Result, Cancelled
from .palettes import mc_target
from .compatibility import MODS, selected_mods


def convert(
    scene,
    output,
    scale=1,
    preference="balanced",
    progress=None,
    cancelled=None,
    hollow=False,
    shell_thickness=1,
    mods=(),
    detailed_copycats=False,
    decoration_mode="structure",
    surface_thickness=0.125,
    extreme_detail=False,
    geometry_cache=None,
    geometry_key=None,
    optimized_conversion=False,
    build_preview=True,
):
    if decoration_mode not in {"structure", "decorations", "appearance"}:
        raise ValueError("Unknown decoration mode")
    if surface_thickness not in (0.0625, 0.125, 0.25, 0.5):
        raise ValueError("Invalid decorative surface thickness")
    from .mesh_geometry import prepare_meshes

    mods = selected_mods(mods)
    if scale not in (0.25, 0.5, 1, 2, 3, 4, 5):
        raise ValueError("Scale must be 0.25, 0.5, 1, 2, 3, 4, or 5")
    if preference not in {"balanced", "material", "color"}:
        raise ValueError("Unknown material preference")
    if shell_thickness not in (1, 2, 3, 4):
        raise ValueError("Shell thickness must be 1, 2, 3, or 4 cells")
    if output not in ({"nbt", "litematic"} if scene.format == "blueprint" else {"blueprint"}):
        raise ValueError("Choose a format in the other game")
    if detailed_copycats and ("copycats" not in mods or output == "blueprint"):
        raise ValueError("Detailed Copycats requires Copycats+ and Minecraft output")
    if extreme_detail and ("copycats" not in mods or output == "blueprint"):
        raise ValueError("Extreme detail requires Copycats+ and Minecraft output")
    stage_key = (
        geometry_key,
        scale,
        detailed_copycats or extreme_detail,
        extreme_detail,
        decoration_mode,
        surface_thickness,
        optimized_conversion,
        shell_thickness if optimized_conversion and hollow else None,
    )
    cached = (
        geometry_cache.get(stage_key) if geometry_cache is not None and geometry_key is not None else None
    )
    scene = cached[0] if cached else prepare_meshes(scene, decoration_mode, surface_thickness, scale)
    allowed = {block["name"] for slug in mods for block in MODS[slug]["blocks"]}
    for part in scene.parts:
        mapping = part.mapping_override
        if mapping:
            if mapping.name.startswith("ftd:"):
                from .ftd import CUBE_IDS

                if output != "blueprint" or mapping.name[4:] not in CUBE_IDS.values():
                    raise ValueError("FtD material overrides require a verified native target and FtD output")
                continue
            if output == "blueprint":
                raise ValueError("Minecraft material overrides require Minecraft output")
            if not mapping.name.startswith("minecraft:") and mapping.name not in allowed:
                raise ValueError(f"Enable the mod required by mapping {mapping.name}")
    options = {"extreme": True} if extreme_detail else {}
    early_hollow = optimized_conversion and hollow
    before_hollow = 0
    if optimized_conversion:
        options["optimized"] = True
    if early_hollow:

        def filter_interior(cells):
            nonlocal before_hollow
            before_hollow = len(cells)
            return hollow_cells(cells, shell_thickness, cancelled, progress)

        options["cell_filter"] = filter_interior
    if cached:
        if cancelled and cancelled():
            raise Cancelled("Conversion cancelled")
        _, cells, offset = cached
        if progress:
            progress(0.78)
    else:
        cells, offset = voxelize(
            scene,
            scale,
            progress,
            cancelled,
            detailed=detailed_copycats or extreme_detail,
            compact=True,
            **options,
        )
    if not cells:
        raise ValueError("No structural blocks remain after skipped blocks")
    if early_hollow and not cached:
        scene = replace(scene, notices=scene.notices.copy())
        scene.notices[
            f"Hollow interior removed {before_hollow - len(cells):,} cells; kept a {shell_thickness}-cell exterior shell"
        ] += 1
    if not cached and geometry_cache is not None and geometry_key is not None:
        geometry_cache.put(stage_key, scene, cells, offset, cancelled)
    notices = Counter(scene.notices)
    if hollow and not early_hollow:
        before = len(cells)
        cells = hollow_cells(cells, shell_thickness, cancelled, progress)
        notices[
            f"Hollow interior removed {before - len(cells):,} cells; kept a {shell_thickness}-cell exterior shell"
        ] += 1
    if scale < 1:
        notices["Reduced scale merges occupied cells; small openings and thin details may be lost"] += 1
    if output == "blueprint":
        for part in cells.values():
            if part.shape.startswith("slab_"):
                notices["Approximated half slabs with 1 m blocks; 2× preserves half-height geometry"] += 1
            elif part.shape.startswith("step_"):
                notices["Approximated Minecraft stairs with ordinary FtD slopes"] += 1
        content = write_blueprint(cells)
        del cells
        notices["FtD output schema targets reference version 3.8.5.11; in-game acceptance is unverified"] += 1
        return Result(content, read_blueprint(content) if build_preview else None, output, offset, notices)
    for part in cells.values():
        if "copycats" not in mods and part.transparent and part.shape.startswith(("slab_", "step_")):
            notices[
                "Approximated partial glass with full transparent blocks; vanilla has no glass slabs or stairs"
            ] += 1
    states, state_cache = {}, {}
    for index, (position, part) in enumerate(cells.items()):
        if index % 256 == 0:
            if cancelled and cancelled():
                raise Cancelled("Conversion cancelled")
            if progress:
                progress(0.88 + 0.03 * index / max(1, len(cells)))
        identifier = id(part)
        target = state_cache.get(identifier) if not cached else None
        if target is None:
            target = mc_target(part, preference, mods)
            if not cached:
                if len(state_cache) >= 4096:
                    state_cache.clear()
                state_cache[identifier] = target
        states[position] = target
    full_fallbacks = sum(
        part.shape.startswith(("slab_", "step_"))
        and not states[pos].copied_material
        and not states[pos].name.endswith(("_slab", "_stairs"))
        for pos, part in cells.items()
    )
    if full_fallbacks:
        notices["Used matching full blocks where the selected material has no slab or stair"] += (
            full_fallbacks
        )
    if extreme_detail:
        notices[
            "Extreme detail fits smooth slopes, fine Copycats pieces and independent piece materials"
        ] += 1
    elif detailed_copycats:
        notices["Detailed Copycats fits layers, panels and bytes to sampled source geometry"] += 1
    if mods:
        notices[
            "Export requires these selected mods: " + ", ".join(MODS[slug]["label"] for slug in mods)
        ] += 1
    size = tuple(np.max(list(cells), axis=0) + 1)
    # Only immutable target states are needed by the writer and preview now.
    # Cached geometry remains owned by the session; release this local map.
    del cells, cached, state_cache
    writer, reader = (
        (write_structure, read_structure) if output == "nbt" else (write_litematic, read_litematic)
    )
    if cancelled and cancelled():
        raise Cancelled("Conversion cancelled")
    content = writer(states, size)
    if cancelled and cancelled():
        raise Cancelled("Conversion cancelled")
    if not build_preview:
        return Result(content, None, output, offset, notices)
    if progress:
        progress(0.95)
    if optimized_conversion:
        from .generated_preview import export_scene

        display = export_scene(states, size, output, content, cancelled, progress)
        return Result(content, display, output, offset, notices)
    # Normal mode independently reimports the bytes. Optimized mode above
    # uses the same decoder on the exact states emitted by the local writer.
    del states
    return Result(content, reader(content), output, offset, notices)


def read_file(content, suffix):
    readers = {"blueprint": read_blueprint, "nbt": read_structure, "litematic": read_litematic}
    reader = readers.get(suffix.lower().lstrip("."))
    if reader is None:
        raise ValueError("Open an FtD .blueprint, Minecraft .nbt, or .litematic file")
    return reader(content)
