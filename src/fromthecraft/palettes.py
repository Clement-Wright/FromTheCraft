import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np

from .model import State
from .compatibility import BUILDING_BLOCKS, MODS, MOD_STATES, VANILLA_BLOCKS, VARIANTS

REGISTRY = json.loads((Path(__file__).with_name("data") / "minecraft_1_21_1.json").read_text())
BLOCKS = {"minecraft:" + b["name"]: b for b in REGISTRY["blocks"]}
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
DYES = {
    "white": (0.82, 0.84, 0.81),
    "orange": (0.88, 0.37, 0.01),
    "magenta": (0.66, 0.19, 0.62),
    "light_blue": (0.14, 0.54, 0.77),
    "yellow": (0.95, 0.69, 0.08),
    "lime": (0.37, 0.66, 0.1),
    "pink": (0.84, 0.4, 0.55),
    "gray": (0.21, 0.24, 0.25),
    "light_gray": (0.49, 0.49, 0.45),
    "cyan": (0.08, 0.47, 0.53),
    "purple": (0.39, 0.12, 0.59),
    "blue": (0.17, 0.18, 0.56),
    "brown": (0.38, 0.24, 0.14),
    "green": (0.29, 0.36, 0.12),
    "red": (0.56, 0.13, 0.13),
    "black": (0.08, 0.08, 0.1),
}


def mc_policy(name):
    if name in MOD_STATES:
        return "mapped", "verified mod building block"
    if name not in BLOCKS:
        return "unrecognized", "placeholder"
    if name in BUILDING_BLOCKS:
        return "mapped", "verified building material"
    short = name.split(":", 1)[1]
    if name in AIR:
        return "skipped", "air"
    if short in {"water", "lava", "bubble_column"}:
        return "skipped", "fluid"
    if BLOCKS[name]["boundingBox"] == "empty" and short not in {"glass", "structure_void"}:
        return "skipped", "nonstructural"
    if short.endswith(("_slab", "_stairs", "_wall", "_pane", "_fence")) or short in {"iron_bars", "snow"}:
        return "approximated", "structural shape"
    if short.endswith(
        ("_planks", "_log", "_wood", "_concrete", "_wool", "_terracotta", "_stained_glass")
    ) or short in {"stone", "cobblestone", "glass", "iron_block", "bricks"}:
        return "mapped", "building material"
    return "approximated", "inert footprint"


def validate_state(state: State):
    if state.name in MOD_STATES:
        rules = MOD_STATES[state.name]
        for key, value in state.properties:
            if key not in rules or value not in rules[key]:
                raise ValueError(f"Invalid verified mod state {state.name}[{key}={value}]")
        return
    entry = BLOCKS.get(state.name)
    if entry is None:
        return
    rules = {s["name"]: s for s in entry["states"]}
    for key, value in state.properties:
        rule = rules.get(key)
        if rule is None:
            raise ValueError(f"Invalid 1.21.1 property {state.name}[{key}]")
        allowed = rule.get("values")
        if rule["type"] == "bool":
            allowed = ["true", "false"]
        elif rule["type"] == "int" and allowed is None:
            allowed = [str(i) for i in range(rule["num_values"])]
        if value not in allowed:
            raise ValueError(f"Invalid 1.21.1 state {state.name}[{key}={value}]")


WOODS = {
    "oak": (0.63, 0.51, 0.31),
    "spruce": (0.44, 0.32, 0.19),
    "birch": (0.77, 0.70, 0.50),
    "dark_oak": (0.26, 0.17, 0.08),
    "mangrove": (0.45, 0.20, 0.17),
    "cherry": (0.90, 0.70, 0.67),
    "acacia": (0.66, 0.36, 0.20),
    "warped": (0.17, 0.42, 0.39),
    "crimson": (0.40, 0.19, 0.27),
    "bamboo": (0.76, 0.69, 0.31),
    "jungle": (0.63, 0.46, 0.32),
}


@lru_cache(maxsize=512)
def nearest_color(family, color):
    palette = WOODS if family == "wood" else DYES
    return min(palette, key=lambda name: sum((a - b) ** 2 for a, b in zip(palette[name], color)))


def mc_material(name):
    entry = BUILDING_BLOCKS.get(name) or VARIANTS.get(name)
    if entry:
        return entry["material"], tuple(entry["rgb"])
    short = name.split(":", 1)[-1]
    color = (0.5, 0.5, 0.5)
    for dye, rgb in sorted(DYES.items(), key=lambda pair: -len(pair[0])):
        if short.startswith(dye + "_"):
            color = rgb
            break
    if "glass" in short or short == "ice":
        return "Glass", color if color != (0.5, 0.5, 0.5) else (0.7, 0.85, 0.87)
    for wood in sorted(WOODS, key=len, reverse=True):
        if wood in short:
            return "Wood", WOODS[wood]
    if any(
        token in short for token in ("iron", "copper", "gold", "anvil", "hopper", "piston", "rail", "chain")
    ):
        for metal, rgb in {
            "gold": (0.98, 0.86, 0.27),
            "copper": (0.75, 0.42, 0.30),
            "iron": (0.87, 0.87, 0.87),
        }.items():
            if metal in short:
                color = rgb
                break
        return "Metal", color
    return "Stone", color


@lru_cache(maxsize=4096)
def mod_target(base, material, color, transparent, preference, mods):
    if transparent:
        return base
    choices = [*VANILLA_BLOCKS.values(), *(block for slug in mods for block in MODS[slug]["blocks"])]
    family = "Wood" if material == "Reinforced Wood" else material
    if preference == "material" or (material in {"Wood", "Reinforced Wood"} and preference != "color"):
        choices = [block for block in choices if block["material"] == family]

    def distance(rgb):
        return sum((a - b) ** 2 for a, b in zip(rgb, color))

    def score(block_material, rgb):
        penalty = 0.0125 if preference == "balanced" and block_material != family else 0
        return distance(rgb) + penalty

    best = min(choices, key=lambda block: score(block["material"], block["rgb"]), default=None)
    base_material, base_rgb = mc_material(base.name)
    if best and score(best["material"], best["rgb"]) < score(base_material, base_rgb):
        return State(best["name"], tuple(sorted(best["properties"].items())))
    return base


def mc_target(part, preference, mods=()):
    base = part.mapping_override or mc_target_material(part, preference)
    if part.mapping_full:
        return base
    if mods and part.mapping_override is None:
        base = mod_target(base, part.material, tuple(part.color), part.transparent, preference, mods)
    if part.shape == "extreme":
        from .extreme import paint_target

        return paint_target(part, preference, mods, base)
    if part.shape == "detailed" and part.state is not None:
        return replace(part.state, copied_material=base)
    partial = part.shape.startswith(("slab_", "step_"))
    slab_axis = part.shape.split("_")[1] if part.shape.startswith(("slab_x_", "slab_z_")) else "y"
    slab_half = part.shape.rsplit("_", 1)[-1]
    if partial and "copycats" in mods:
        if part.shape.startswith("slab_"):
            return State(
                "copycats:copycat_slab",
                tuple(sorted({"axis": slab_axis, "type": slab_half, "waterlogged": "false"}.items())),
                copied_material=base,
            )
        _, facing, half = part.shape.split("_")
        return State(
            "copycats:copycat_stairs",
            tuple(
                sorted({"facing": facing, "half": half, "shape": "straight", "waterlogged": "false"}.items())
            ),
            copied_material=base,
        )
    if part.transparent:
        return base
    if partial:
        if part.shape.startswith("slab_") and slab_axis != "y":
            return base
        stem = base.name.removesuffix("_planks")
        suffix = "_slab" if part.shape.startswith("slab_") else "_stairs"
        entry = BUILDING_BLOCKS.get(base.name)
        name = entry.get("slab" if suffix == "_slab" else "stairs") if entry else stem + suffix
        if not name or name not in BLOCKS and name not in MOD_STATES:
            return base
        if part.shape.startswith("slab_"):
            return State(name, (("type", slab_half), ("waterlogged", "false")))
        _, facing, half = part.shape.split("_")
        return State(
            name,
            tuple(
                sorted({"facing": facing, "half": half, "shape": "straight", "waterlogged": "false"}.items())
            ),
        )
    return base


def mc_target_material(part, preference):
    if part.transparent:
        dye = nearest_color("dye", part.color)
        return State("minecraft:" + dye + "_stained_glass")
    if part.material in {"Wood", "Reinforced Wood"} and preference != "color":
        base = State("minecraft:" + nearest_color("wood", part.color) + "_planks")
    elif preference == "color" or (
        preference == "balanced" and (np.ptp(part.color) > 0.15 or max(part.color) < 0.35)
    ):
        dye = nearest_color("dye", part.color)
        base = State("minecraft:" + dye + "_concrete")
    elif part.material == "Stone":
        base = State("minecraft:stone")
    else:
        base = State("minecraft:iron_block")
    return mod_target(base, part.material, tuple(part.color), False, preference, ())
