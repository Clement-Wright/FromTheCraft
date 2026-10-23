import json
import hashlib
import re
from dataclasses import replace
from collections import Counter
from pathlib import Path

import numpy as np

from .catalog import game_assets, installed_catalog
from .geometry import quaternion, rotation
from .ftd_shapes import native_shape
from .model import MAX_PARTS, Part, Scene, SourceRecord
from .decorations import read_decorations, packet_headers, fields, decode_decoration, unity_euler
from .ftd_meshes import resolve_static_mesh

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
    source_records, mesh_cache = [], {}
    mesh_triangles = 0
    source_hash = hashlib.sha256(content).hexdigest()
    colors = [vector(c, 4) for c in root.get("COL", [])]

    def visit(construct, parent, depth, path=("Blueprint",)):
        nonlocal records, mesh_triangles
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
        hosts, mimics = {}, {}
        for index, (position, rot, block_id, paint) in enumerate(
            zip(construct["BLP"], construct["BLR"], construct["BlockIds"], construct["BCI"])
        ):
            guid = items.get(str(block_id), str(block_id))
            entry = CATALOG.get(guid)
            record_path = path + ("blocks", str(index))
            record = SourceRecord(
                f"{source_hash}:{'/'.join(record_path)}",
                guid,
                "block",
                record_path,
                path,
                name=entry["Name"] if entry else guid,
            )
            source_records.append(record)
            anchor = tuple(vector(position))
            hosts.setdefault(anchor, record.id)
            if entry is None:
                notices[f"Unrecognized FtD ID {guid}: omitted"] += 1
                continue
            policy, shape = ftd_policy(entry)
            if policy == "skipped":
                mimics[index] = (record, vector(position), rotation(rot), paint)
                continue
            extent = entry.get("Footprint")
            if extent is None:
                extent = FOOTPRINTS[str(entry["SizeId"])]
            size = tuple(extent[a + "n"] + extent[a + "p"] + 1 for a in "xyz")
            if np.prod(size) <= 512:
                from itertools import product

                for delta in product(*[range(-extent[a + "n"], extent[a + "p"] + 1) for a in "xyz"]):
                    cell = tuple(np.rint(np.asarray(anchor) + rotation(rot) @ delta).astype(int))
                    hosts.setdefault(cell, record.id)
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

        def add_decoration(data, record, base, paint):
            nonlocal mesh_triangles
            guid = data["mesh_guid"]
            if guid not in mesh_cache:
                vertices, indices, reason = resolve_static_mesh(guid)
                if vertices is not None:
                    low, high = vertices.min(0), vertices.max(0)
                    span = np.maximum(high - low, 1e-6)
                    mesh_cache[guid] = ((vertices - low) / span, indices, low, span, reason)
                else:
                    mesh_cache[guid] = (None, None, None, None, reason)
            vertices, indices, low, span, reason = mesh_cache[guid]
            if vertices is None and "intentionally empty" in reason:
                source_records.append(
                    replace(record, hide_host=data["hide_original"], geometry_status="empty")
                )
                return
            if vertices is None or mesh_triangles + len(indices) > 2_000_000:
                source_records.append(replace(record, geometry_status="unresolved"))
                notices[
                    f"Unresolved decoration {guid}: {reason if vertices is None else 'scene triangle budget reached'}"
                ] += 1
                return
            record = replace(record, hide_host=data["hide_original"])
            source_records.append(record)
            material = CATALOG.get(guid, {}).get("Material", "Metal")
            color = np.array(COLORS.get(material, COLORS["Metal"]))
            if colors and 0 <= paint < len(colors):
                rgba = colors[paint]
                color = color * (1 - rgba[3]) + rgba[:3] * rgba[3]
            if data["material_guid"] != "00000000-0000-0000-0000-000000000000":
                notices["Decoration material replacement uses a structural color approximation"] += 1
            local = np.eye(4)
            local[:3, :3] = unity_euler(data["orientation"]) @ np.diag(data["scale"])
            local[:3, 3] = data["position"]
            normalize = np.eye(4)
            normalize[:3, :3] = np.diag(span)
            normalize[:3, 3] = low
            world = base @ local @ normalize
            parts.append(
                Part(
                    "Decoration: " + reason,
                    "mesh",
                    (1, 1, 1),
                    world,
                    material,
                    tuple(color),
                    material == "Glass",
                    source_record=record,
                    mesh=(vertices, indices),
                    decoration=True,
                    replaces_host=data["hide_original"],
                )
            )
            mesh_triangles += len(indices)

        try:
            decorations = read_decorations(construct.get("VehicleData"))
        except ValueError as exc:
            decorations = []
            notices[f"Unresolved decoration payload: {exc}"] += 1
        for data in decorations:
            record_path = path + ("decorations", str(data["id"]))
            record = SourceRecord(
                f"{source_hash}:{'/'.join(record_path)}",
                data["mesh_guid"],
                "decoration",
                record_path,
                path,
                hosts.get(tuple(data["tether"])),
                "Decoration " + data["mesh_guid"],
            )
            if len(source_records) > MAX_PARTS:
                raise ValueError("Blueprint source record budget exceeded")
            base = transform.copy()
            base[:3, 3] += transform[:3, :3] @ np.asarray(data["tether"])
            base[:3, 3] += 0.5
            add_decoration(data, record, base, data["paint"])
        if mimics:
            resolved_mimics = set()
            try:
                for index, headers, _ in packet_headers(construct.get("BlockData", ""), id_bytes=3):
                    if index not in mimics or 1 not in headers:
                        continue
                    record, position, orientation, paint = mimics[index]
                    data = decode_decoration(fields(headers[1]), index, mimic=True)
                    base = transform.copy()
                    base[:3, :3] = transform[:3, :3] @ orientation
                    base[:3, 3] += transform[:3, :3] @ position + 0.5
                    add_decoration(data, record, base, paint)
                    resolved_mimics.add(index)
            except ValueError as exc:
                notices[f"Unresolved mimic payload: {exc}"] += 1
            notices["Legacy or unresolved mimic records retained without visible geometry"] += len(
                mimics
            ) - len(resolved_mimics)
        if construct.get("Decorations") or construct.get("DEC"):
            notices["Unsupported legacy decoration overlay representation"] += len(
                construct.get("Decorations", construct.get("DEC", []))
            )
        if construct.get("BlockData") or construct.get("VehicleData") or construct.get("BlockStringData"):
            notices["Mechanism payloads and unsupported renderer data are not converted"] += 1
        for index, child in enumerate(construct.get("SCs", [])):
            visit(child, transform, depth + 1, path + ("SCs", str(index)))

    try:
        visit(root, np.eye(4), 0)
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError(f"Malformed blueprint block data: {exc}") from exc
    return Scene(
        parts,
        "blueprint",
        notices,
        str(root.get("GameVersion", "unknown")),
        source_hash,
        tuple(source_records),
    )


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
