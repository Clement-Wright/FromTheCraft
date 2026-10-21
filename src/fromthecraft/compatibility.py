import json
from pathlib import Path

REGISTRY = json.loads(
    (Path(__file__).with_name("data") / "mod_palette_1_21_1.json").read_text(encoding="utf-8")
)
MODS = {mod["slug"]: mod for mod in REGISTRY["mods"]}
MOD_BLOCKS = {block["name"]: block for mod in MODS.values() for block in mod["blocks"]}
VARIANTS = {
    block[shape]: block for block in MOD_BLOCKS.values() for shape in ("stairs", "slab") if block.get(shape)
}
MOD_STATES = {name: rules for mod in MODS.values() for name, rules in mod.get("states", {}).items()}


def selected_mods(mods):
    selected = set(mods)
    unknown = selected - MODS.keys()
    if unknown:
        raise ValueError("Unknown installed mod: " + ", ".join(sorted(unknown)))
    for slug in tuple(selected):
        selected.update(MODS[slug]["dependencies"])
    return tuple(sorted(selected))


def mod_choices():
    return [{key: mod[key] for key in ("slug", "label", "version", "dependencies")} for mod in MODS.values()]
