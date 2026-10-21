from dataclasses import replace

import nbtlib as nbt

from .model import State
from .palettes import validate_state

STAIRS = "copycats:copycat_stairs"
SLAB = "copycats:copycat_slab"


def block_state_tag(state):
    tag = nbt.Compound({"Name": nbt.String(state.name)})
    if state.properties:
        tag["Properties"] = nbt.Compound({key: nbt.String(value) for key, value in state.properties})
    return tag


def block_entity(state, position):
    material = state.copied_material
    if material is None:
        return None
    validate_state(material)
    if material.copied_material is not None:
        raise ValueError("A copied material cannot itself be a copycat")
    item = nbt.Compound({"id": nbt.String(material.name), "count": nbt.Int(1)})
    tag = nbt.Compound({axis: nbt.Int(value) for axis, value in zip("xyz", position)})
    if state.name == STAIRS:
        tag.update(
            {
                "id": nbt.String("copycats:copycat"),
                "Material": block_state_tag(material),
                "Item": item,
                "EnableCT": nbt.Byte(1),
            }
        )
    elif state.name == SLAB:
        half = dict(state.properties).get("type", "bottom")
        data = nbt.Compound()
        for side in ("bottom", "top"):
            active = half == side or half == "double"
            data[side] = nbt.Compound(
                {
                    "material": block_state_tag(material if active else State("create:copycat_base")),
                    "consumedItem": item
                    if active and (side == "bottom" or half == "top")
                    else nbt.Compound(),
                    "enableCT": nbt.Byte(1),
                }
            )
        tag.update({"id": nbt.String("copycats:multistate_copycat"), "material_data": data})
    else:
        raise ValueError(f"Unsupported copycat material container: {state.name}")
    return tag


def read_material(state, entity, notices):
    if not entity:
        return state
    if state.name not in {STAIRS, SLAB}:
        notices["Intentionally skipped block entity data (inventories, commands, gameplay)"] += 1
        return state
    try:
        if state.name == STAIRS:
            if str(entity["id"]) != "copycats:copycat":
                raise ValueError("wrong block entity id")
            material, item = entity["Material"], entity["Item"]
        else:
            if str(entity["id"]) != "copycats:multistate_copycat":
                raise ValueError("wrong block entity id")
            half = dict(state.properties).get("type", "bottom")
            data = entity["material_data"]
            if half == "double" and data["top"]["material"] != data["bottom"]["material"]:
                raise ValueError("double slab has two different materials")
            entry = data["bottom" if half == "double" else half]
            material, item = entry["material"], entry["consumedItem"]
            if half == "double" and not item:
                item = data["top"]["consumedItem"]
        if not isinstance(material, nbt.Compound) or not isinstance(item, nbt.Compound):
            raise ValueError("material and consumed item must be compounds")
        properties = material.get("Properties", nbt.Compound())
        if not isinstance(properties, nbt.Compound):
            raise ValueError("material properties must be a compound")
        copied = State(
            str(material["Name"]),
            tuple(sorted((str(key), str(value)) for key, value in properties.items())),
        )
        validate_state(copied)
        if copied.name == "create:copycat_base":
            return state
        if str(item["id"]) != copied.name or int(item.get("count", 1)) < 1:
            raise ValueError("applied material does not match consumed item")
        if copied.name.startswith("copycats:"):
            raise ValueError("nested copycat material")
        return replace(state, copied_material=copied)
    except (KeyError, TypeError, ValueError) as exc:
        notices[f"Copycat material could not be read; using an inert placeholder: {exc}"] += 1
        return state
