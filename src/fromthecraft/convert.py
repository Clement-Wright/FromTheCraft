from collections import Counter

import numpy as np

from .geometry import hollow_cells, voxelize
from .ftd import read_blueprint, write_blueprint
from .minecraft import read_litematic, read_structure, write_litematic, write_structure
from .model import Result
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
):
    mods = selected_mods(mods)
    if scale not in (0.25, 0.5, 1, 2, 4):
        raise ValueError("Scale must be 0.25, 0.5, 1, 2, or 4")
    if preference not in {"balanced", "material", "color"}:
        raise ValueError("Unknown material preference")
    if shell_thickness not in (1, 2, 3, 4):
        raise ValueError("Shell thickness must be 1, 2, 3, or 4 cells")
    if output not in ({"nbt", "litematic"} if scene.format == "blueprint" else {"blueprint"}):
        raise ValueError("Choose a format in the other game")
    if detailed_copycats and ("copycats" not in mods or output == "blueprint"):
        raise ValueError("Detailed Copycats requires Copycats+ and Minecraft output")
    allowed = {block["name"] for slug in mods for block in MODS[slug]["blocks"]}
    for part in scene.parts:
        mapping = part.mapping_override
        if mapping:
            if output == "blueprint":
                raise ValueError("Minecraft material overrides require Minecraft output")
            if not mapping.name.startswith("minecraft:") and mapping.name not in allowed:
                raise ValueError(f"Enable the mod required by mapping {mapping.name}")
    cells, offset = voxelize(scene, scale, progress, cancelled, detailed=detailed_copycats)
    if not cells:
        raise ValueError("No structural blocks remain after skipped blocks")
    notices = Counter(scene.notices)
    if hollow:
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
        notices["FtD output schema targets reference version 3.8.5.11; in-game acceptance is unverified"] += 1
        return Result(content, read_blueprint(content), output, offset, notices)
    for part in cells.values():
        if "copycats" not in mods and part.transparent and part.shape.startswith(("slab_", "step_")):
            notices[
                "Approximated partial glass with full transparent blocks; vanilla has no glass slabs or stairs"
            ] += 1
    states = {p: mc_target(part, preference, mods) for p, part in cells.items()}
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
    if detailed_copycats:
        notices["Detailed Copycats fits layers, panels and bytes to sampled source geometry"] += 1
    if mods:
        notices[
            "Export requires these selected mods: " + ", ".join(MODS[slug]["label"] for slug in mods)
        ] += 1
    size = tuple(np.max(list(cells), axis=0) + 1)
    writer, reader = (
        (write_structure, read_structure) if output == "nbt" else (write_litematic, read_litematic)
    )
    content = writer(states, size)
    if progress:
        progress(0.95)
    return Result(content, reader(content), output, offset, notices)


def read_file(content, suffix):
    readers = {"blueprint": read_blueprint, "nbt": read_structure, "litematic": read_litematic}
    reader = readers.get(suffix.lower().lstrip("."))
    if reader is None:
        raise ValueError("Open an FtD .blueprint, Minecraft .nbt, or .litematic file")
    return reader(content)
