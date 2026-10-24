"""Frozen 1320422 algorithms for exact performance differential tests."""

import gzip
import hashlib
import io
import json
import struct

from collections import Counter

import numpy as np

import nbtlib as nbt

from litemapy import BlockState, Region, Schematic, TileEntity

from fromthecraft.ftd import CATALOG, CUBE_IDS, SLOPE_IDS

from fromthecraft.geometry import checked_size

from fromthecraft.model import DATA_VERSION, MAX_PARTS, MAX_VOLUME, State, SourceRecord

from fromthecraft.minecraft import MAX_BYTES, MAX_LIST_ITEMS, check_version, scene_from_cells

from fromthecraft.palettes import MOD_STATES, validate_state, mc_policy

from fromthecraft.copycats import block_entity, block_state_tag, read_material


def write_blueprint(cells, name="FromTheCraft"):
    paints = [(0.0, 0.0, 0.0, 0.0)]
    positions, rotations, paint_indices, block_ids = [], [], [], []
    dictionary = {"499": "e63040c9-0027-4fd3-be30-67fe3e950140"}
    ids = {}
    for position, part in sorted(cells.items()):
        material = part.material if part.material in CUBE_IDS else "Metal"
        if part.mapping_override and part.mapping_override.name.startswith("ftd:"):
            material = CATALOG[part.mapping_override.name[4:]]["Material"]
        guid = CUBE_IDS[material]
        rot = 0
        if part.shape.startswith("step_") and material in SLOPE_IDS and not part.mapping_full:
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


def parse_nbt(content):
    if len(content) > 32 * 1024**2:
        raise ValueError("Input exceeds 32 MiB")
    try:
        if content[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as compressed:
                raw = compressed.read(MAX_BYTES + 1)
        else:
            raw = content
        if len(raw) > MAX_BYTES:
            raise ValueError("Decompressed NBT exceeds 128 MiB")
        stream = io.BytesIO(raw)

        def take(count):
            if count < 0 or len(stream.read(count)) != count:
                raise ValueError("Truncated or invalid NBT length")

        def number(fmt):
            return struct.unpack(fmt, stream.read(struct.calcsize(fmt)))[0]

        def string():
            take(number(">H"))

        def payload(tag, depth=0):
            if depth > 64:
                raise ValueError("NBT nesting exceeds 64")
            if tag in (1, 2, 3, 4, 5, 6):
                take({1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}[tag])
            elif tag == 8:
                string()
            elif tag in (7, 11, 12):
                count = number(">i")
                if not 0 <= count <= MAX_BYTES // {7: 1, 11: 4, 12: 8}[tag]:
                    raise ValueError("Invalid NBT array length")
                take(count * {7: 1, 11: 4, 12: 8}[tag])
            elif tag == 9:
                item, count = number(">B"), number(">i")
                if not 0 <= count <= MAX_LIST_ITEMS or (item == 0 and count):
                    raise ValueError("Invalid NBT list length")
                for _ in range(count):
                    payload(item, depth + 1)
            elif tag == 10:
                while (item := number(">B")) != 0:
                    string()
                    payload(item, depth + 1)
            else:
                raise ValueError(f"Unsupported NBT tag {tag}")

        if number(">B") != 10:
            raise ValueError("NBT root must be a compound")
        string()
        payload(10)
        if stream.tell() != len(raw):
            raise ValueError("Unexpected data after NBT root")
        return nbt.File.parse(io.BytesIO(raw))
    except (OSError, EOFError, struct.error, UnicodeDecodeError, OverflowError) as exc:
        raise ValueError(f"Invalid NBT: {exc}") from exc


def read_structure(content: bytes):
    root = parse_nbt(content)
    notices = Counter()
    cells, records = {}, {}
    entries = []
    source_hash = hashlib.sha256(content).hexdigest()
    try:
        check_version(root["DataVersion"])
        checked_size(root["size"])
        if len(root["blocks"]) > MAX_PARTS:
            raise ValueError(f"Input exceeds {MAX_PARTS:,} block records")
        for index_record, block in enumerate(root["blocks"]):
            index = int(block["state"])
            if not 0 <= index < len(root["palette"]):
                raise ValueError("Structure palette index out of range")
            pos = tuple(int(n) for n in block["pos"])
            if len(pos) != 3 or any(abs(n) > 100_000 for n in pos):
                raise ValueError("Invalid structure block position")
            one = {}
            accept(one, pos, BlockState.from_nbt(root["palette"][index]), notices, block.get("nbt"))
            record_path = ("blocks", str(index_record))
            records.setdefault(
                pos,
                SourceRecord(
                    f"{source_hash}:{'/'.join(record_path)}",
                    str(root["palette"][index]["Name"]),
                    "block",
                    record_path,
                    (),
                ),
            )
            if one:
                record = SourceRecord(
                    f"{source_hash}:{'/'.join(record_path)}", one[pos].name, "block", record_path, ()
                )
                entries.append((pos, one[pos], record))
                cells.setdefault(pos, one[pos])
        if root.get("entities"):
            notices["Intentionally skipped entities"] += len(root["entities"])
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed structure NBT: {exc}") from exc
    return scene_from_cells(cells, "nbt", notices, records, source_hash, entries)


def accept(cells, position, block, notices, entity=None):
    state = State(block.id, tuple(sorted((str(k), str(v)) for k, v in block.properties())))
    if state.name in MOD_STATES:
        rules = MOD_STATES[state.name]
        supported = tuple((key, value) for key, value in state.properties if value in rules.get(key, ()))
        if supported != state.properties:
            omitted = ", ".join(
                f"{key}={value}" for key, value in state.properties if (key, value) not in supported
            )
            notices[
                f"Approximated mod state {state.name}: unsupported source properties {omitted}; "
                "using verified inert shape"
            ] += 1
            state = State(state.name, supported)
    validate_state(state)
    policy, family = mc_policy(state.name)
    if policy == "skipped":
        if family != "air":
            notices[f"Intentionally skipped {family}: {state.name}"] += 1
        return
    state = read_material(state, entity, notices)
    if position in cells:
        if cells[position] != state:
            notices["Overlapping occupied cells: first region/block wins"] += 1
        return
    cells[position] = state
    if len(cells) > MAX_PARTS:
        raise ValueError(f"Input exceeds {MAX_PARTS:,} occupied cells")
    if policy == "unrecognized":
        notices[f"Unrecognized block {state.name}: inert placeholder"] += 1
    elif policy == "approximated":
        notices[f"Approximated {family}: {state.name}"] += 1


def read_litematic(content):
    root = parse_nbt(content)
    try:
        check_version(root["MinecraftDataVersion"])
        if int(root["Version"]) not in (5, 6, 7):
            raise ValueError("Only Litematic format versions 5, 6 and 7 are supported")
        volume = 0
        for region in root["Regions"].values():
            size = checked_size([abs(int(region["Size"][a])) for a in "xyz"])
            volume += int(np.prod(size))
        if volume > MAX_VOLUME:
            raise ValueError("Combined Litematic region volume exceeds limit")
        schematic = Schematic.from_nbt(root)
        cells, notices, records = {}, Counter(), {}
        entries = []
        source_hash = hashlib.sha256(content).hexdigest()
        for name, region in schematic.regions.items():
            minimum = (region.min_x(), region.min_y(), region.min_z())
            entities = {
                tuple(coordinate + low for coordinate, low in zip(entity.position, minimum)): entity.data
                for entity in region.tile_entities
            }
            for x, y, z in region.block_positions():
                one = {}
                accept(
                    one,
                    (region.x + x, region.y + y, region.z + z),
                    region[x, y, z],
                    notices,
                    entities.get((x, y, z)),
                )
                position = (region.x + x, region.y + y, region.z + z)
                if position in one:
                    record_path = ("Regions", name, f"{x},{y},{z}")
                    record = SourceRecord(
                        f"{source_hash}:{'/'.join(record_path)}",
                        one[position].name,
                        "block",
                        record_path,
                        ("Regions", name),
                    )
                    entries.append((position, one[position], record))
                    if position in cells:
                        notices[
                            "Overlapping source records retained; first contributor owns conversion material"
                        ] += 1
                    cells.setdefault(position, one[position])
                    if len(entries) > MAX_PARTS:
                        raise ValueError(f"Input exceeds {MAX_PARTS:,} block records")
            if region.entities:
                notices["Intentionally skipped entities"] += len(region.entities)
        return scene_from_cells(cells, "litematic", notices, records, source_hash, entries)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed Litematic: {exc}") from exc


def write_structure(cells: dict, size) -> bytes:
    checked_size(size)
    palette, indices, blocks = [], {}, []
    for position, state in sorted(cells.items()):
        validate_state(state)
        bare = State(state.name, state.properties)
        if bare not in indices:
            indices[bare] = len(palette)
            palette.append(block_state_tag(bare))
        block = nbt.Compound({"pos": nbt.List[nbt.Int](position), "state": nbt.Int(indices[bare])})
        entity = block_entity(state, position)
        if entity is not None:
            block["nbt"] = entity
        blocks.append(block)
    root = nbt.File(
        {
            "DataVersion": nbt.Int(DATA_VERSION),
            "size": nbt.List[nbt.Int](size),
            "palette": nbt.List[nbt.Compound](palette),
            "blocks": nbt.List[nbt.Compound](blocks),
            "entities": nbt.List[nbt.Compound](),
        }
    )
    stream = io.BytesIO()
    root.write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)


def write_litematic(cells, size):
    checked_size(size)
    region = Region(0, 0, 0, *[int(n) for n in size])
    for pos, state in cells.items():
        validate_state(state)
        region[pos] = BlockState(state.name, **dict(state.properties))
        entity = block_entity(state, pos)
        if entity is not None:
            region.tile_entities.append(TileEntity(entity))
    root = Schematic(name="FromTheCraft", regions={"Structure": region}, mc_version=DATA_VERSION).to_nbt()
    stream = io.BytesIO()
    nbt.File(root).write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)
