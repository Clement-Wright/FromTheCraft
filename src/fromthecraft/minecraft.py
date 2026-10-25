import gzip
import hashlib
import io
import struct
from collections import Counter
from functools import lru_cache

import nbtlib as nbt
import numpy as np
from litemapy import BlockState, Region, Schematic, TileEntity

from .compatibility import MOD_STATES
from .geometry import checked_size
from .model import DATA_VERSION, MAX_PARTS, MAX_VOLUME, Part, Scene, State, SourceRecord
from .palettes import mc_material, mc_policy, validate_state
from .copycats import block_entity, block_state_tag, geometry_boxes, read_material

MAX_BYTES = 128 * 1024**2
MAX_LIST_ITEMS = 8_000_000


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
        position = 0

        def take(count):
            nonlocal position
            if count < 0 or count > len(raw) - position:
                raise ValueError("Truncated or invalid NBT length")
            position += count

        def number(fmt):
            nonlocal position
            size = struct.calcsize(fmt)
            if size > len(raw) - position:
                raise struct.error(f"unpack requires a buffer of {size} bytes")
            value = struct.unpack_from(fmt, raw, position)[0]
            position += size
            return value

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
                if item in (1, 2, 3, 4, 5, 6):
                    if count and depth + 1 > 64:
                        raise ValueError("NBT nesting exceeds 64")
                    take(count * {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}[item])
                else:
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
        if position != len(raw):
            raise ValueError("Unexpected data after NBT root")
        return nbt.File.parse(io.BytesIO(raw))
    except (OSError, EOFError, struct.error, UnicodeDecodeError, OverflowError) as exc:
        raise ValueError(f"Invalid NBT: {exc}") from exc


def _entity_factory():
    @lru_cache(maxsize=4096)
    def template(state):
        validate_state(state)
        return block_entity(state, (0, 0, 0))

    def at(state, position):
        original = template(state)
        if original is None:
            return None
        result = nbt.Compound(original)
        for axis, value in zip("xyz", position):
            result[axis] = nbt.Int(value)
        return result

    return at


def write_structure(cells: dict, size) -> bytes:
    checked_size(size)
    try:
        ordinary = all(
            len(pos) == 3
            and all(isinstance(n, (int, np.integer)) and -(2**31) <= int(n) < 2**31 for n in pos)
            for pos in cells
        )
    except TypeError:
        ordinary = False
    if ordinary:
        from .nbt_output import encode_structure

        return encode_structure(cells, size, _entity_factory())
    return _write_structure_tags(cells, size)


def _write_structure_tags(cells, size):
    """Retain nbtlib's coordinate coercion and errors for unusual public inputs."""
    checked_size(size)
    palette, indices, blocks = [], {}, []
    entity_at = _entity_factory()
    for position, state in sorted(cells.items()):
        entity = entity_at(state, position)
        bare = State(state.name, state.properties)
        if bare not in indices:
            indices[bare] = len(palette)
            palette.append(block_state_tag(bare))
        block = nbt.Compound({"pos": nbt.List[nbt.Int](position), "state": nbt.Int(indices[bare])})
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


def read_structure(content: bytes):
    root = parse_nbt(content)
    notices = Counter()
    templates = {}
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
            if index not in templates:
                templates[index] = state_template(BlockState.from_nbt(root["palette"][index]))
            accept(one, pos, None, notices, block.get("nbt"), template=templates[index])
            if one:
                record_path = ("blocks", str(index_record))
                record = SourceRecord(
                    f"{source_hash}:{'/'.join(record_path)}", one[pos].name, "block", record_path, ()
                )
                entries.append((pos, one[pos], record))
        if root.get("entities"):
            notices["Intentionally skipped entities"] += len(root["entities"])
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"Malformed structure NBT: {exc}") from exc
    # Entries contain detached states and records; release tags before parts.
    # The loop local can retain a large unused payload in its final record.
    block = None
    del root
    return scene_from_cells({}, "nbt", notices, source_hash=source_hash, entries=entries)


def check_version(version):
    if int(version) != DATA_VERSION:
        raise ValueError(
            f"Expected Minecraft Java 1.21.1 (data version 3955); file has {version}. No data fixer is included."
        )


def state_template(block):
    state = State(block.id, tuple(sorted((str(k), str(v)) for k, v in block.properties())))
    message = None
    if state.name in MOD_STATES:
        rules = MOD_STATES[state.name]
        supported = tuple((key, value) for key, value in state.properties if value in rules.get(key, ()))
        if supported != state.properties:
            omitted = ", ".join(
                f"{key}={value}" for key, value in state.properties if (key, value) not in supported
            )
            message = (
                f"Approximated mod state {state.name}: unsupported source properties {omitted}; "
                "using verified inert shape"
            )
            state = State(state.name, supported)
    validate_state(state)
    policy, family = mc_policy(state.name)
    return state, policy, family, message


def accept(cells, position, block, notices, entity=None, *, template=None):
    state, policy, family, message = template if template is not None else state_template(block)
    if message:
        notices[message] += 1
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


def scene_from_cells(cells, format, notices, records=None, source_hash="", entries=None):
    parts = []

    @lru_cache(maxsize=4096)
    def shape_boxes(name, properties):
        return geometry_boxes(State(name, properties))

    material_color = lru_cache(maxsize=4096)(mc_material)
    source_entries = (
        entries
        if entries is not None
        else ((pos, state, (records or {}).get(pos)) for pos, state in cells.items())
    )
    for position, state, record in source_entries:
        start = len(parts)
        boxes = shape_boxes(state.name, state.properties)
        if boxes is not None:
            appearances = dict(state.copied_materials)
            for slot, box in boxes:
                visual = appearances.get(slot, state.copied_material or state)
                material, color = material_color(visual.name)
                transform = np.eye(4)
                transform[:3, 3] = np.asarray(position) + box[:3]
                size = tuple(high - low for low, high in zip(box[:3], box[3:]))
                parts.append(
                    Part(
                        state.name,
                        "box",
                        size,
                        transform,
                        material,
                        color,
                        material == "Glass",
                        state,
                        position,
                        slot,
                    )
                )
                parts[-1].source_record = record
                if len(parts) > MAX_PARTS:
                    raise ValueError(f"Input exceeds {MAX_PARTS:,} render parts")
            continue
        transform = np.eye(4)
        transform[:3, 3] = position
        material, color = material_color((state.copied_material or state).name)
        shape, size = "box", (1, 1, 1)
        props = dict(state.properties)
        from .smooth_shapes import smooth_geometry

        smooth = smooth_geometry(state)
        if smooth:
            shape, transform = smooth
            transform[:3, 3] += position
        elif state.name.endswith("_slab") and props.get("type", "bottom") != "double":
            axis = "xyz".index(props.get("axis", "y")) if state.name == "copycats:copycat_slab" else 1
            size = tuple(0.5 if index == axis else 1 for index in range(3))
            if props.get("type") == "top":
                transform[axis, 3] += 0.5
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
                            position,
                        )
                    )
        parts.append(
            Part(state.name, shape, size, transform, material, color, material == "Glass", state, position)
        )
        for part in parts[start:]:
            part.source_record = record
    return Scene(parts, format, notices, str(DATA_VERSION), source_hash)


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
        from .packed_regions import regions

        parsed_regions = regions(root)
        cells, notices, records = {}, Counter(), {}
        entries = []
        source_hash = hashlib.sha256(content).hexdigest()
        for region in parsed_regions:
            name, minimum = region.name, region.minimum
            templates = {}
            entities = {
                tuple(coordinate + low for coordinate, low in zip(entity.position, minimum)): entity.data
                for entity in region.tile_entities
            }
            for (x, y, z), block in region.blocks():
                one = {}
                key = (block.id, tuple(block.properties()))
                if key not in templates:
                    templates[key] = state_template(block)
                position = tuple(a + b for a, b in zip(region.position, (x, y, z)))
                accept(
                    one,
                    position,
                    None,
                    notices,
                    entities.get((x, y, z)),
                    template=templates[key],
                )
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


def write_litematic(cells, size):
    checked_size(size)
    from .litematic_output import OutputRegion, SparseOutputRegion

    ordinary = all(
        len(pos) == 3
        and all(
            isinstance(n, (int, np.integer)) and not isinstance(n, (bool, np.bool_)) and 0 <= n < size[axis]
            for axis, n in enumerate(pos)
        )
        for pos in cells
    )
    region_type = SparseOutputRegion if len(cells) * 32 < int(np.prod(size)) else OutputRegion
    region = (region_type if ordinary else Region)(0, 0, 0, *[int(n) for n in size])
    entity_at = _entity_factory()
    states = lru_cache(maxsize=4096)(lambda name, properties: BlockState(name, **dict(properties)))
    for pos, state in cells.items():
        entity = entity_at(state, pos)
        region[pos] = states(state.name, state.properties)
        if entity is not None:
            region.tile_entities.append(TileEntity(entity))
    root = Schematic(name="FromTheCraft", regions={"Structure": region}, mc_version=DATA_VERSION).to_nbt()
    stream = io.BytesIO()
    nbt.File(root).write(stream)
    return gzip.compress(stream.getvalue(), mtime=0)
