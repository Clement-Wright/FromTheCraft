import json
from pathlib import Path

REGISTRY = json.loads(
    (Path(__file__).with_name("data") / "mod_palette_1_21_1.json").read_text(encoding="utf-8")
)
EXPANDED_REGISTRY = json.loads(
    (Path(__file__).with_name("data") / "expanded_palette_1_21_1.json").read_text(encoding="utf-8")
)
MODS = {mod["slug"]: mod for mod in REGISTRY["mods"]}
for block in EXPANDED_REGISTRY["blocks"]:
    if block["mod"] != "vanilla":
        MODS[block["mod"]]["blocks"].append(block)
MOD_BLOCKS = {block["name"]: block for mod in MODS.values() for block in mod["blocks"]}
VANILLA_BLOCKS = {block["name"]: block for block in EXPANDED_REGISTRY["blocks"] if block["mod"] == "vanilla"}
BUILDING_BLOCKS = {**VANILLA_BLOCKS, **MOD_BLOCKS}
VARIANTS = {
    block[shape]: block
    for block in BUILDING_BLOCKS.values()
    for shape in ("stairs", "slab")
    if block.get(shape)
}
MOD_STATES = {name: rules for mod in MODS.values() for name, rules in mod.get("states", {}).items()}
MOD_STATES.update(
    {name: rules for name, rules in EXPANDED_REGISTRY["states"].items() if not name.startswith("minecraft:")}
)

# These static container schemas were verified from the pinned Copycats+/Create
# classes. Their copied material is serialized independently by copycats.py.
_BOOLEAN = ["false", "true"]
_HORIZONTAL = ["east", "north", "south", "west"]
_DIRECTIONS = ["down", "east", "north", "south", "up", "west"]
MOD_STATES.update(
    {
        "copycats:copycat_layer": {
            "facing": _DIRECTIONS,
            "layers": [str(n) for n in range(1, 9)],
            "waterlogged": _BOOLEAN,
        },
        "copycats:copycat_byte": {
            **{
                f"{height}_{depth}{side}": _BOOLEAN
                for height in ("bottom", "top")
                for depth in ("north", "south")
                for side in ("west", "east")
            },
            "waterlogged": _BOOLEAN,
        },
        "copycats:copycat_byte_panel": {
            "facing": _DIRECTIONS,
            "waterlogged": _BOOLEAN,
            **{slot: _BOOLEAN for slot in ("bottom_right", "bottom_left", "top_right", "top_left")},
        },
        "copycats:copycat_half_panel": {
            "facing": _DIRECTIONS,
            "offset": _HORIZONTAL,
            "waterlogged": _BOOLEAN,
        },
        "create:copycat_panel": {"facing": _DIRECTIONS, "waterlogged": _BOOLEAN},
        "create:copycat_step": {"facing": _HORIZONTAL, "half": ["bottom", "top"], "waterlogged": _BOOLEAN},
    }
)


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


# Additional static structural families, verified against pinned CCShapes and block properties.
for _family in ("half_layer", "vertical_half_layer", "stacked_half_layer"):
    MOD_STATES["copycats:copycat_" + _family] = {
        "negative_layers": [str(n) for n in range(9)],
        "positive_layers": [str(n) for n in range(9)],
        "waterlogged": _BOOLEAN,
        **(
            {"axis": ["x", "z"], "half": ["top", "bottom"]}
            if _family == "half_layer"
            else {"facing": _HORIZONTAL}
        ),
    }
MOD_STATES["copycats:copycat_beam"] = {"axis": ["x", "y", "z"], "waterlogged": _BOOLEAN}
MOD_STATES["copycats:copycat_board"] = {**{side: _BOOLEAN for side in _DIRECTIONS}, "waterlogged": _BOOLEAN}
MOD_STATES["copycats:copycat_vertical_step"] = {"facing": _HORIZONTAL, "waterlogged": _BOOLEAN}
for _family in ("slice", "vertical_slice", "corner_slice"):
    MOD_STATES["copycats:copycat_" + _family] = {
        "facing": _HORIZONTAL,
        "layers": [str(n) for n in range(1, 9)],
        "waterlogged": _BOOLEAN,
        **({} if _family == "vertical_slice" else {"half": ["top", "bottom"]}),
    }
for _family in ("slope", "vertical_slope", "slope_layer"):
    MOD_STATES["copycats:copycat_" + _family] = {
        "facing": _HORIZONTAL,
        "waterlogged": _BOOLEAN,
        **({} if _family == "vertical_slope" else {"half": ["top", "bottom"]}),
        **({"layers": [str(n) for n in range(1, 9)]} if _family == "slope_layer" else {}),
    }
