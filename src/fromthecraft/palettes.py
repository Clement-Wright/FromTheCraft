import json
from pathlib import Path

import numpy as np

from .model import State

REGISTRY = json.loads((Path(__file__).with_name("data") / "minecraft_1_21_1.json").read_text())
BLOCKS = {"minecraft:"+b["name"]: b for b in REGISTRY["blocks"]}
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
DYES = {"white": (0.82,.84,.81), "orange": (.88,.37,.01), "magenta": (.66,.19,.62),
        "light_blue": (.14,.54,.77), "yellow": (.95,.69,.08), "lime": (.37,.66,.1),
        "pink": (.84,.4,.55), "gray": (.21,.24,.25), "light_gray": (.49,.49,.45),
        "cyan": (.08,.47,.53), "purple": (.39,.12,.59), "blue": (.17,.18,.56),
        "brown": (.38,.24,.14), "green": (.29,.36,.12), "red": (.56,.13,.13), "black": (.08,.08,.1)}


def mc_policy(name):
    if name not in BLOCKS:
        return "unrecognized", "placeholder"
    short = name.split(":",1)[1]
    if name in AIR:
        return "skipped", "air"
    if short in {"water", "lava", "bubble_column"}:
        return "skipped", "fluid"
    if BLOCKS[name]["boundingBox"] == "empty" and short not in {"glass", "structure_void"}:
        return "skipped", "nonstructural"
    if short.endswith(("_slab", "_stairs", "_wall", "_pane", "_fence")) or short in {"iron_bars", "snow"}:
        return "approximated", "structural shape"
    if short.endswith(("_planks", "_log", "_wood", "_concrete", "_wool", "_terracotta", "_stained_glass")) or short in {"stone", "cobblestone", "glass", "iron_block", "bricks"}:
        return "mapped", "building material"
    return "approximated", "inert footprint"


def validate_state(state: State):
    entry = BLOCKS.get(state.name)
    if entry is None:
        return
    rules = {s["name"]: s for s in entry["states"]}
    for key,value in state.properties:
        rule = rules.get(key)
        if rule is None:
            raise ValueError(f"Invalid 1.21.1 property {state.name}[{key}]")
        allowed = rule.get("values")
        if rule["type"] == "bool":
            allowed = ["true", "false"]
        elif rule["type"] == "int":
            allowed = [str(i) for i in range(rule["num_values"])]
        if value not in allowed:
            raise ValueError(f"Invalid 1.21.1 state {state.name}[{key}={value}]")


def mc_material(name):
    short = name.split(":",1)[-1]
    color = (.5,.5,.5)
    for dye,rgb in sorted(DYES.items(), key=lambda pair: -len(pair[0])):
        if short.startswith(dye+"_"):
            color = rgb
            break
    if "glass" in short or short == "ice":
        return "Glass", color if color != (.5,.5,.5) else (.7,.85,.87)
    if any(token in short for token in ("oak", "spruce", "birch", "jungle", "acacia", "mangrove", "cherry", "bamboo", "crimson", "warped")):
        return "Wood", (.59,.43,.25)
    if any(token in short for token in ("iron", "copper", "gold", "anvil", "hopper", "piston", "rail", "chain")):
        return "Metal", color
    return "Stone", color


def mc_target(part, preference):
    if part.transparent:
        dye = min(DYES, key=lambda k: np.linalg.norm(np.array(DYES[k])-part.color))
        return State("minecraft:"+dye+"_stained_glass")
    if part.material in {"Wood", "Reinforced Wood"}:
        return State("minecraft:oak_planks")
    if preference == "color" or (preference == "balanced" and np.ptp(part.color) > .15):
        dye = min(DYES, key=lambda k: np.linalg.norm(np.array(DYES[k])-part.color))
        return State("minecraft:"+dye+"_concrete")
    if part.material == "Stone":
        return State("minecraft:stone")
    return State("minecraft:iron_block")
