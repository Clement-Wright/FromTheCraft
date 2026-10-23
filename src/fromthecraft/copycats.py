"""Static Copycat material containers and independently derived shape dimensions."""

from dataclasses import replace
import re

import nbtlib as nbt

from .model import State
from .palettes import validate_state

STAIRS = "copycats:copycat_stairs"
SLAB = "copycats:copycat_slab"
LAYER = "copycats:copycat_layer"
BYTE = "copycats:copycat_byte"
BYTE_PANEL = "copycats:copycat_byte_panel"
HALF_PANEL = "copycats:copycat_half_panel"
PANEL = "create:copycat_panel"
STEP = "create:copycat_step"
HALF_LAYERS = tuple(
    "copycats:copycat_" + family for family in ("half_layer", "vertical_half_layer", "stacked_half_layer")
)
BOARD = "copycats:copycat_board"
EXTRA_SINGLE = tuple(
    "copycats:copycat_" + family
    for family in ("beam", "vertical_step", "slice", "vertical_slice", "corner_slice")
)
SMOOTH = tuple("copycats:copycat_" + family for family in ("slope", "vertical_slope", "slope_layer"))
BASE = State("create:copycat_base")
BYTE_SLOTS = tuple(
    f"{height}_{depth}{side}"
    for height in ("bottom", "top")
    for depth in ("north", "south")
    for side in ("west", "east")
)
PANEL_SLOTS = ("bottom_right", "bottom_left", "top_right", "top_left")
MULTI_SLOTS = {SLAB: ("bottom", "top"), BYTE: BYTE_SLOTS, BYTE_PANEL: PANEL_SLOTS}
MULTI_SLOTS.update({name: ("negative_layers", "positive_layers") for name in HALF_LAYERS})
MULTI_SLOTS[BOARD] = ("up", "down", "north", "south", "east", "west")
SINGLE_IDS = {
    STAIRS: "copycats:copycat",
    LAYER: "copycats:copycat",
    HALF_PANEL: "copycats:copycat",
    PANEL: "create:copycat",
    STEP: "create:copycat",
}
SINGLE_IDS.update({name: "copycats:copycat" for name in EXTRA_SINGLE})
SINGLE_IDS.update({name: "copycats:copycat" for name in SMOOTH})
SUPPORTED = frozenset(SINGLE_IDS) | MULTI_SLOTS.keys()
DIRECTIONS = {
    "west": (0, -1),
    "east": (0, 1),
    "down": (1, -1),
    "up": (1, 1),
    "north": (2, -1),
    "south": (2, 1),
}


def block_state_tag(state):
    tag = nbt.Compound({"Name": nbt.String(state.name)})
    if state.properties:
        tag["Properties"] = nbt.Compound({key: nbt.String(value) for key, value in state.properties})
    return tag


def occupied_slots(state):
    props = dict(state.properties)
    if state.name == SLAB:
        half = props.get("type", "bottom")
        return ("bottom", "top") if half == "double" else (half,)
    if state.name in HALF_LAYERS:
        return tuple(slot for slot in MULTI_SLOTS[state.name] if int(props.get(slot, "0")) > 0)
    return tuple(slot for slot in MULTI_SLOTS.get(state.name, ()) if props.get(slot, "false") == "true")


def _material_valid(material):
    if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", material.name):
        raise ValueError("Invalid copied material identifier")
    validate_state(material)
    if (
        material.copied_material is not None
        or material.copied_materials
        or material.name.startswith("copycats:")
        or material.name.startswith("create:copycat_")
        and material != BASE
    ):
        raise ValueError("A copied material cannot itself be a copycat")


def _item(material):
    return nbt.Compound({"id": nbt.String(material.name), "count": nbt.Int(1)})


def block_entity(state, position):
    if state.copied_material is None and not state.copied_materials:
        return None
    if state.name not in SUPPORTED:
        raise ValueError(f"Unsupported copycat material container: {state.name}")
    if state.copied_material is not None and state.copied_materials:
        raise ValueError("Use a shared copied material or individual slot materials, not both")
    validate_state(state)
    tag = nbt.Compound({axis: nbt.Int(value) for axis, value in zip("xyz", position)})
    if state.name in SINGLE_IDS:
        if state.copied_materials:
            raise ValueError("Single-state copycats do not have material slots")
        material = state.copied_material
        _material_valid(material)
        tag.update(
            {
                "id": nbt.String(SINGLE_IDS[state.name]),
                "Material": block_state_tag(material),
                "Item": _item(material),
                "EnableCT": nbt.Byte(1),
            }
        )
        return tag
    slots, active = MULTI_SLOTS[state.name], occupied_slots(state)
    custom = dict(state.copied_materials)
    if len(custom) != len(state.copied_materials) or set(custom) - set(active):
        raise ValueError("Material slots must be unique occupied copycat parts")
    data, paid = nbt.Compound(), set()
    for slot in slots:
        material = (state.copied_material or custom.get(slot, BASE)) if slot in active else BASE
        _material_valid(material)
        consume = slot in active and material != BASE and material.name not in paid
        data[slot] = nbt.Compound(
            {
                "material": block_state_tag(material),
                "consumedItem": _item(material) if consume else nbt.Compound(),
                "enableCT": nbt.Byte(1),
            }
        )
        if consume:
            paid.add(material.name)
    tag.update({"id": nbt.String("copycats:multistate_copycat"), "material_data": data})
    return tag


def _read_state(material):
    if not isinstance(material, nbt.Compound) or not isinstance(material.get("Name"), nbt.String):
        raise ValueError("material must be a block-state compound")
    properties = material.get("Properties", nbt.Compound())
    if not isinstance(properties, nbt.Compound):
        raise ValueError("material properties must be a compound")
    if any(not isinstance(value, nbt.String) for value in properties.values()):
        raise ValueError("material properties must contain strings")
    copied = State(str(material["Name"]), tuple(sorted((str(k), str(v)) for k, v in properties.items())))
    _material_valid(copied)
    return copied


def _read_item(item, material):
    if not isinstance(item, nbt.Compound):
        raise ValueError("consumed item must be a compound")
    if not item:
        return None
    if not isinstance(item.get("id"), nbt.String) or not isinstance(item.get("count"), nbt.Int):
        raise ValueError("consumed item needs a String id and Int count")
    if str(item["id"]) != material.name or int(item["count"]) < 1:
        raise ValueError("applied material does not match consumed item")
    return material.name


def _read_ct(entry, key):
    if key in entry and (not isinstance(entry[key], nbt.Byte) or int(entry[key]) not in (0, 1)):
        raise ValueError("connected texture flag must be Byte 0 or 1")


def read_material(state, entity, notices):
    if not entity:
        return state
    if state.name not in SUPPORTED:
        notices["Intentionally skipped block entity data (inventories, commands, gameplay)"] += 1
        return state
    try:
        if not isinstance(entity, nbt.Compound) or not isinstance(entity.get("id"), nbt.String):
            raise ValueError("block entity needs a String id")
        if state.name in SINGLE_IDS:
            if str(entity["id"]) != SINGLE_IDS[state.name]:
                raise ValueError("wrong block entity id")
            _read_ct(entity, "EnableCT")
            material = _read_state(entity["Material"])
            paid = _read_item(entity["Item"], material)
            if material == BASE:
                return state
            if paid is None:
                raise ValueError("applied material has no consumed item")
            return replace(state, copied_material=material)
        if str(entity["id"]) != "copycats:multistate_copycat":
            raise ValueError("wrong block entity id")
        data, active = entity["material_data"], occupied_slots(state)
        if not isinstance(data, nbt.Compound) or set(data) - set(MULTI_SLOTS[state.name]):
            raise ValueError("invalid material_data slots")
        materials, paid = {}, set()
        for slot, entry in data.items():
            if not isinstance(entry, nbt.Compound):
                raise ValueError("material slot must be a compound")
            _read_ct(entry, "enableCT")
            material = _read_state(entry["material"])
            item = _read_item(entry.get("consumedItem", nbt.Compound()), material)
            if slot not in active and (material != BASE or item is not None):
                raise ValueError("inactive copycat slot contains material or item")
            if item is not None:
                paid.add(item)
            if slot in active:
                materials[slot] = material
        for slot in active:
            materials.setdefault(slot, BASE)
        if any(material != BASE and material.name not in paid for material in materials.values()):
            raise ValueError("applied material has no shared consumed item")
        distinct = set(materials.values())
        if len(distinct) == 1 and BASE not in distinct:
            return replace(state, copied_material=next(iter(distinct)))
        custom = tuple(sorted((slot, material) for slot, material in materials.items() if material != BASE))
        return replace(state, copied_materials=custom)
    except (KeyError, TypeError, ValueError) as exc:
        notices[f"Copycat material could not be read; using an inert placeholder: {exc}"] += 1
        return state


def _side_box(facing, thickness, outward=False):
    axis, sign = DIRECTIONS[facing]
    if outward:
        sign = -sign
    box = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    box[axis], box[axis + 3] = (1 - thickness, 1) if sign > 0 else (0, thickness)
    return box


def geometry_boxes(state):
    """Return occupied (slot, bounds) pairs, or None for shapes handled elsewhere."""
    props = dict(state.properties)
    if state.name in HALF_LAYERS or state.name in EXTRA_SINGLE or state.name == BOARD:
        from .extra_shapes import boxes

        return boxes(state)
    if state.name == LAYER:
        box = _side_box(props.get("facing", "up"), int(props.get("layers", "1")) / 8, True)
        return ((None, tuple(box)),)
    if state.name == PANEL:
        return ((None, tuple(_side_box(props.get("facing", "up"), 3 / 16, True))),)
    if state.name == HALF_PANEL:
        facing, offset = props.get("facing", "north"), props.get("offset", "north")
        axis, sign = DIRECTIONS[offset]
        if axis == DIRECTIONS[facing][0]:
            axis = 1
        box = _side_box(facing, 3 / 16)
        box[axis], box[axis + 3] = (0.5, 1) if sign > 0 else (0, 0.5)
        return ((None, tuple(box)),)
    if state.name == STEP:
        box = _side_box(props.get("facing", "south"), 0.5)
        box[1], box[4] = (0.5, 1) if props.get("half", "bottom") == "top" else (0, 0.5)
        return ((None, tuple(box)),)
    if state.name == SLAB:
        axis = "xyz".index(props.get("axis", "y"))
        boxes = []
        for slot in occupied_slots(state):
            box = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
            box[axis], box[axis + 3] = (0.5, 1) if slot == "top" else (0, 0.5)
            boxes.append((slot, tuple(box)))
        return tuple(boxes)
    if state.name == BYTE:
        boxes = []
        for slot in occupied_slots(state):
            low = [
                0.5 if "east" in slot else 0.0,
                0.5 if slot.startswith("top") else 0.0,
                0.5 if "south" in slot else 0.0,
            ]
            boxes.append((slot, tuple(low + [value + 0.5 for value in low])))
        return tuple(boxes)
    if state.name == BYTE_PANEL:
        facing = props.get("facing", "down")
        horizontal = {
            "down": "east",
            "up": "east",
            "north": "west",
            "south": "east",
            "east": "north",
            "west": "south",
        }[facing]
        vertical = {"down": "south", "up": "north"}.get(facing, "up")
        boxes = []
        for slot in occupied_slots(state):
            box = _side_box(facing, 3 / 16)
            for direction, value in (
                (horizontal, int(slot.endswith("left"))),
                (vertical, int(slot.startswith("top"))),
            ):
                axis, sign = DIRECTIONS[direction]
                low = 0.5 * (value if sign > 0 else 1 - value)
                box[axis], box[axis + 3] = low, low + 0.5
            boxes.append((slot, tuple(box)))
        return tuple(boxes)
    return None
