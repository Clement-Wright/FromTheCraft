import json
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


def mc_material(name):
    short = name.split(":", 1)[-1]
    color = (0.5, 0.5, 0.5)
    for dye, rgb in sorted(DYES.items(), key=lambda pair: -len(pair[0])):
        if short.startswith(dye + "_"):
            color = rgb
            break
    if "glass" in short or short == "ice":
        return "Glass", color if color != (0.5, 0.5, 0.5) else (0.7, 0.85, 0.87)
    if any(
        token in short
        for token in (
            "oak",
            "spruce",
            "birch",
            "jungle",
            "acacia",
            "mangrove",
            "cherry",
            "bamboo",
            "crimson",
            "warped",
        )
    ):
        return "Wood", (0.59, 0.43, 0.25)
    if any(
        token in short for token in ("iron", "copper", "gold", "anvil", "hopper", "piston", "rail", "chain")
    ):
        return "Metal", color
    return "Stone", color


def mc_target(part, preference):
    base = mc_target_material(part, preference)
    if part.shape.startswith("slab_") or part.shape.startswith("step_"):
        stem = "oak" if part.material == "Wood" else "stone"
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
        dye = min(DYES, key=lambda k: np.linalg.norm(np.array(DYES[k]) - part.color))
        return State("minecraft:" + dye + "_stained_glass")
    if part.material in {"Wood", "Reinforced Wood"}:
        return State("minecraft:oak_planks")
    if preference == "color" or (preference == "balanced" and np.ptp(part.color) > 0.15):
        dye = min(DYES, key=lambda k: np.linalg.norm(np.array(DYES[k]) - part.color))
        return State("minecraft:" + dye + "_concrete")
    if part.material == "Stone":
        return State("minecraft:stone")
    return State("minecraft:iron_block")
