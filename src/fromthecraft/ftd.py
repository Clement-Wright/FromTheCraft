import json
import hashlib
import re
from collections import Counter
from pathlib import Path

import numpy as np

from .catalog import game_assets, installed_catalog
from .geometry import quaternion, rotation
from .ftd_shapes import native_shape
from .model import MAX_PARTS, Part, Scene, SourceRecord

DATA = Path(__file__).with_name("data")
CATALOG = json.loads((DATA / "ftd_blocks.json").read_text())
NATIVE_SHAPE_CORRECTIONS = json.loads((DATA / "ftd_native_shape_corrections.json").read_text())["corrections"]
for guid, shape in NATIVE_SHAPE_CORRECTIONS.items():
    if guid in CATALOG:
        CATALOG[guid]["NativeShape"] = shape
FOOTPRINTS = json.loads((DATA / "ftd_size_id_dictionary.json").read_text())
CUBE_IDS = {
    v["Material"]: k for k, v in CATALOG.items() if v["Name"].lower() == v["Material"].lower() + " block"
}
SLOPE_IDS = {
    v["Material"]: k
    for k, v in CATALOG.items()
    if v["Name"].lower() == v["Material"].lower() + " down slope (1m)"
}
LOCAL_CATALOG, CATALOG_INFO = installed_catalog(game_assets(), CATALOG)
CATALOG.update(LOCAL_CATALOG)
COLORS = {
    "Metal": (0.45, 0.45, 0.45),
    "Wood": (0.56, 0.38, 0.2),
    "Stone": (0.55, 0.55, 0.53),
    "Glass": (0.7, 0.85, 0.87),
    "Alloy": (0.78, 0.78, 0.78),
    "Lead": (0.2, 0.2, 0.2),
    "Heavy Armour": (0.46, 0.46, 0.52),
    "Rubber": (0.12, 0.15, 0.12),
}


def ftd_policy(entry):
    name = entry["Name"].lower()
    if "mimic" in name or "decoration" in name:
        return "skipped", "none"
    if any(word in name for word in ("curve", "quarter circle", "rounded hull")):
        return "approximated", "curve"
    shape = native_shape(entry)
    if shape:
        return "approximated", shape
    if re.fullmatch(
        r"(wood|metal|alloy|stone|glass|rubber|lead|heavy armour|reinforced wood|light-weight alloy) (block|beam \([1-4]m\))",
        name,
    ):
        return "mapped", "box"
    return "approximated", "box"


def vector(text, length=3):
    values = np.array(str(text).split(","), dtype=float)
    if len(values) != length or not np.isfinite(values).all() or np.max(np.abs(values)) > 1e7:
        raise ValueError("Invalid blueprint vector")
    return values


def read_blueprint(content: bytes) -> Scene:
    if len(content) > 32 * 1024**2:
        raise ValueError("Blueprint exceeds 32 MiB")
    try:
        document = json.loads(content)
        root, items = document["Blueprint"], document["ItemDictionary"]
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid FtD blueprint JSON or missing Blueprint/ItemDictionary") from exc
    if not isinstance(root, dict) or not isinstance(items, dict):
        raise ValueError("Blueprint and ItemDictionary must be JSON objects")
    parts, notices = [], Counter()
    records = 0
    source_hash = hashlib.sha256(content).hexdigest()
    colors = [vector(c, 4) for c in root.get("COL", [])]

    def visit(construct, parent, depth, path=("Blueprint",)):
        nonlocal records
        if depth > 32:
            raise ValueError("Blueprint construct nesting exceeds 32")
        transform = parent.copy()
        if depth:
            local = np.eye(4)
            local[:3, :3] = quaternion(vector(construct.get("LocalRotation", "0,0,0,1"), 4))
            local[:3, 3] = vector(construct.get("LocalPosition", "0,0,0"))
            transform = parent @ local
        count = len(construct["BLP"])
        records += count
        if any(len(construct.get(k, [])) != count for k in ("BLR", "BlockIds", "BCI")):
            raise ValueError("Blueprint block-array length mismatch")
        if records > MAX_PARTS:
            raise ValueError(f"Blueprint exceeds {MAX_PARTS:,} blocks")
        for index, (position, rot, block_id, paint) in enumerate(
            zip(construct["BLP"], construct["BLR"], construct["BlockIds"], construct["BCI"])
        ):
            guid = items.get(str(block_id), str(block_id))
            entry = CATALOG.get(guid)
            if entry is None:
                notices[f"Unrecognized FtD ID {guid}: omitted"] += 1
                continue
            policy, shape = ftd_policy(entry)
            if policy == "skipped":
                notices["Intentionally skipped mimics (ordinary host blocks retained)"] += 1
                continue
            extent = entry.get("Footprint")
            if extent is None:
                extent = FOOTPRINTS[str(entry["SizeId"])]
            size = tuple(extent[a + "n"] + extent[a + "p"] + 1 for a in "xyz")
            material = entry["Material"]
            color = np.array(entry.get("DefaultColor", COLORS.get(material, (0.45, 0.45, 0.45))))
            if not isinstance(paint, int) or not 0 <= paint < max(1, len(colors)):
                raise ValueError("Blueprint paint index is outside COL")
            if colors:
                rgba = colors[paint]
                if np.any(rgba < 0) or np.any(rgba > 1):
                    raise ValueError("Blueprint paint channels must be between 0 and 1")
                color = color * (1 - rgba[3]) + rgba[:3] * rgba[3]
            local = np.eye(4)
            local[:3, :3] = rotation(rot)
            local[:3, 3] = vector(position) + local[:3, :3] @ (
                -np.array([extent[a + "n"] for a in "xyz"]) - 0.5
            )
            world = transform @ local
            world[:3, 3] += 0.5
            record_path = path + ("blocks", str(index))
            record = SourceRecord(f"{source_hash}:{'/'.join(record_path)}", guid, "block", record_path, path)
            parts.append(
                Part(
                    entry["Name"],
                    shape,
                    size,
                    world,
                    material,
                    tuple(color),
                    material == "Glass",
                    source_record=record,
                )
            )
            if policy == "approximated":
                notices[
                    f"Approximated FtD {shape if shape != 'box' else 'known footprint'}: {entry['Name']}"
                ] += 1
        if construct.get("Decorations") or construct.get("DEC"):
            notices["Intentionally skipped decoration overlays"] += len(
                construct.get("Decorations", construct.get("DEC", []))
            )
        if construct.get("BlockData") or construct.get("VehicleData") or construct.get("BlockStringData"):
            notices[
                "Intentionally skipped block/vehicle payloads, including mechanisms and possible decoration overlays"
            ] += 1
        for index, child in enumerate(construct.get("SCs", [])):
            visit(child, transform, depth + 1, path + ("SCs", str(index)))

    try:
        visit(root, np.eye(4), 0)
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError(f"Malformed blueprint block data: {exc}") from exc
    return Scene(parts, "blueprint", notices, str(root.get("GameVersion", "unknown")), source_hash)


def write_blueprint(cells, name="FromTheCraft"):
    paints = [(0.0, 0.0, 0.0, 0.0)]
    positions, rotations, paint_indices, block_ids = [], [], [], []
    dictionary = {"499": "e63040c9-0027-4fd3-be30-67fe3e950140"}
    ids = {}
    for position, part in sorted(cells.items()):
        material = part.material if part.material in {"Wood", "Stone", "Glass"} else "Metal"
        guid = CUBE_IDS[material]
        rot = 0
        if part.shape.startswith("step_") and material in SLOPE_IDS:
            _, facing, half = part.shape.split("_")
            guid = SLOPE_IDS[material]
            rot = {"north": 0, "west": 1, "south": 2, "east": 3}[facing] + (12 if half == "top" else 0)
        if guid not in ids:
            ids[guid] = 1000 + len(ids)
            dictionary[str(ids[guid])] = guid
        paint = tuple(round(float(v), 6) for v in part.color) + (1.0,)
        if paint not in paints and len(paints) < 32:
            paints.append(paint)
        index = min(range(1, len(paints)), key=lambda i: np.linalg.norm(np.array(paints[i][:3]) - part.color))
        positions.append(",".join(str(int(n)) for n in position))
        rotations.append(rot)
        paint_indices.append(index)
        block_ids.append(ids[guid])
    count = len(positions)
    coords = np.array(list(cells))

    def coord_string(point):
        return ",".join(str(int(n)) for n in point)

    construct = {
        "Name": name,
        "blueprintName": name,
        "blueprintVersion": 1,
        "GameVersion": "3.8.5.11",
        "LocalPosition": "0,0,0",
        "LocalRotation": "0,0,0,1",
        "ItemNumber": 499,
        "SCs": [],
        "COL": [",".join(str(n) for n in c) for c in paints + [(0.0, 0.0, 0.0, 0.0)] * (32 - len(paints))],
        "BLP": positions,
        "BLR": rotations,
        "BCI": paint_indices,
        "BlockIds": block_ids,
        "BP1": None,
        "BP2": None,
        "BEI": None,
        "BlockData": "",
        "VehicleData": "",
        "BlockState": f"=0,{count}",
        "BlockStringData": [],
        "BlockStringDataIds": [],
        "TotalBlockCount": count,
        "BlockCount": count,
        "AliveCount": count,
        "MinCords": coord_string(coords.min(0)),
        "MaxCords": coord_string(coords.max(0)),
        "ContainedMaterialCost": 0.0,
        "PersistentSubObjectIndex": 0,
        "PersistentBlockIndex": 0,
        "SerialisedInfo": {"JsonDictionary": {}, "IsEmpty": True},
        "designChanged": False,
    }
    return json.dumps(
        {
            "FileModelVersion": {"Major": 1, "Minor": 0},
            "Name": name,
            "Version": 1,
            "SavedTotalBlockCount": count,
            "ContainedMaterialCost": 0.0,
            "ItemDictionary": dictionary,
            "Blueprint": construct,
        },
        separators=(",", ":"),
    ).encode()
