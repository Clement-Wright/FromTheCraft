import gzip
import io
import struct
from collections import Counter

import nbtlib as nbt
import numpy as np
from litemapy import BlockState, Region, Schematic

from .geometry import checked_size
from .model import DATA_VERSION, MAX_PARTS, MAX_VOLUME, Part, Scene, State
from .palettes import mc_material, mc_policy, validate_state

MAX_BYTES = 128 * 1024**2


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
                if not 0 <= count <= MAX_VOLUME or (item == 0 and count):
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


def write_structure(cells: dict, size) -> bytes:
    checked_size(size)
    palette, indices, blocks = [], {}, []
    for position, state in sorted(cells.items()):
        validate_state(state)
        if state not in indices:
            indices[state] = len(palette)
            entry = nbt.Compound({"Name": nbt.String(state.name)})
            if state.properties:
                entry["Properties"] = nbt.Compound({k: nbt.String(v) for k, v in state.properties})
            palette.append(entry)
        blocks.append(nbt.Compound({"pos": nbt.List[nbt.Int](position), "state": nbt.Int(indices[state])}))
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


def read_structure(content: bytes):
    root = parse_nbt(content)
    notices = Counter()
    cells = {}
    try:
        check_version(root["DataVersion"])
        checked_size(root["size"])
        if len(root["blocks"]) > MAX_PARTS:
            raise ValueError(f"Input exceeds {MAX_PARTS:,} block records")
        for block in root["blocks"]:
            index = int(block["state"])
            if not 0 <= index < len(root["palette"]):
                raise ValueError("Structure palette index out of range")
            pos = tuple(int(n) for n in block["pos"])
            if len(pos) != 3 or any(abs(n) > 100_000 for n in pos):
                raise ValueError("Invalid structure block position")
            accept(cells, pos, BlockState.from_nbt(root["palette"][index]), notices)
            if "nbt" in block:
                notices["Intentionally skipped block entity data (inventories, commands, gameplay)"] += 1
        if root.get("entities"):
            notices["Intentionally skipped entities"] += len(root["entities"])
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed structure NBT: {exc}") from exc
    return scene_from_cells(cells, "nbt", notices)


def check_version(version):
    if int(version) != DATA_VERSION:
        raise ValueError(
            f"Expected Minecraft Java 1.21.1 (data version 3955); file has {version}. No data fixer is included."
        )


def accept(cells, position, block, notices):
    state = State(block.id, tuple(sorted((str(k), str(v)) for k, v in block.properties())))
    validate_state(state)
    policy, family = mc_policy(state.name)
    if policy == "skipped":
        if family != "air":
            notices[f"Intentionally skipped {family}: {state.name}"] += 1
        return
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


def scene_from_cells(cells, format, notices):
    parts = []
    for position, state in cells.items():
        transform = np.eye(4)
        transform[:3, 3] = position
        material, color = mc_material(state.name)
        shape, size = "box", (1, 1, 1)
        props = dict(state.properties)
        if state.name.endswith("_slab") and props.get("type", "bottom") != "double":
            size = (1, 0.5, 1)
            if props.get("type") == "top":
                transform[1, 3] += 0.5
        elif state.name.endswith("_stairs"):
            shape = "stairs_" + props.get("shape", "straight")
            turn = {"south": 0, "east": 1, "north": 2, "west": 3}[props.get("facing", "north")]
            transform[:3, :3] = np.array(
                [
                    [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
                    [[-1, 0, 0], [0, 1, 0], [0, 0, -1]],
                    [[0, 0, -1], [0, 1, 0], [1, 0, 0]],
                ][turn]
            )
            transform[:3, 3] += 0.5 - transform[:3, :3] @ np.full(3, 0.5)
            if props.get("half") == "top":
                transform[:3, 3] += transform[:3, 1]
                transform[:3, 1] *= -1
        elif state.name.endswith(("_pane", "_fence", "_wall")) or state.name == "minecraft:iron_bars":
            thickness = 0.125 if state.name.endswith("_pane") or state.name == "minecraft:iron_bars" else 0.5
            size = (thickness, 1, thickness)
            transform[:3, 3] += [(1 - thickness) / 2, 0, (1 - thickness) / 2]
            for direction, axis, positive in (
                ("north", 2, False),
                ("south", 2, True),
                ("east", 0, True),
                ("west", 0, False),
            ):
                if props.get(direction, "false") not in {"false", "none"}:
                    arm = np.eye(4)
                    arm[:3, 3] = position
                    arm[:3, 3] += [(1 - thickness) / 2, 0, (1 - thickness) / 2]
                    arm_size = [thickness, 1, thickness]
                    arm_size[axis] = (1 + thickness) / 2
                    arm[axis, 3] = position[axis] + ((1 - thickness) / 2 if positive else 0)
                    parts.append(
                        Part(
                            state.name,
                            "box",
                            tuple(arm_size),
                            arm,
                            material,
                            color,
                            material == "Glass",
                            state,
                        )
                    )
        parts.append(Part(state.name, shape, size, transform, material, color, material == "Glass", state))
    return Scene(parts, format, notices, str(DATA_VERSION))


def read_litematic(content):
    root = parse_nbt(content)
    try:
        check_version(root["MinecraftDataVersion"])
        if int(root["Version"]) not in (5, 6):
            raise ValueError("Only Litematic format versions 5 and 6 are supported")
        volume = 0
        for region in root["Regions"].values():
            size = checked_size([abs(int(region["Size"][a])) for a in "xyz"])
            volume += int(np.prod(size))
        if volume > MAX_VOLUME:
            raise ValueError("Combined Litematic region volume exceeds limit")
        schematic = Schematic.from_nbt(root)
        cells, notices = {}, Counter()
        for region in schematic.regions.values():
            for x, y, z in region.block_positions():
                accept(cells, (region.x + x, region.y + y, region.z + z), region[x, y, z], notices)
            if region.entities:
                notices["Intentionally skipped entities"] += len(region.entities)
            if region.tile_entities:
                notices["Intentionally skipped block entity data (inventories, commands, gameplay)"] += len(
                    region.tile_entities
                )
        return scene_from_cells(cells, "litematic", notices)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed Litematic: {exc}") from exc


def write_litematic(cells, size):
    checked_size(size)
    region = Region(0, 0, 0, *[int(n) for n in size])
    for pos, state in cells.items():
        validate_state(state)
        region[pos] = BlockState(state.name, **dict(state.properties))
    root = Schematic(name="FromTheCraft", regions={"Structure": region}, mc_version=DATA_VERSION).to_nbt()
    stream = io.BytesIO()
    nbt.File(root).write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)
