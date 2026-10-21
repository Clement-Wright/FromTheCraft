import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from .model import State

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
    if name not in BLOCKS:
        return "unrecognized", "placeholder"
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


def mc_target(part, preference):
    base = mc_target_material(part, preference)
    if part.transparent:
        return base
    if part.shape.startswith("slab_") or part.shape.startswith("step_"):
        stem = nearest_color("wood", part.color) if part.material in {"Wood", "Reinforced Wood"} else "stone"
        if part.shape.startswith("slab_"):
            return State(
                f"minecraft:{stem}_slab", (("type", part.shape.split("_")[1]), ("waterlogged", "false"))
            )
        _, facing, half = part.shape.split("_")
        return State(
            f"minecraft:{stem}_stairs",
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
        return State("minecraft:" + nearest_color("wood", part.color) + "_planks")
    if preference == "color" or (
        preference == "balanced" and (np.ptp(part.color) > 0.15 or max(part.color) < 0.35)
    ):
        dye = nearest_color("dye", part.color)
        return State("minecraft:" + dye + "_concrete")
    if part.material == "Stone":
        return State("minecraft:stone")
    return State("minecraft:iron_block")
