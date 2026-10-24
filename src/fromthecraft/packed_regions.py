"""Bounded, ordered Litematic extraction for the pinned litemapy format.

Only integer packing is accelerated. Unsupported/malformed headers retain the
library's validation path, including its metadata and entity error messages.
"""

from dataclasses import dataclass
from math import ceil, log

import numpy as np
from litemapy import BlockState, Entity, Schematic, TileEntity

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
BATCH = 65536


@dataclass
class PackedRegion:
    name: str
    position: tuple
    size: tuple
    palette: tuple
    words: np.ndarray
    nbits: int
    entities: list
    tile_entities: list

    @property
    def minimum(self):
        return tuple(min(0, n + 1) for n in self.size)

    def blocks(self):
        width, height, length = (abs(n) for n in self.size)
        volume = width * height * length
        minimum = self.minimum
        air = np.array([block.id in AIR and not tuple(block.properties()) for block in self.palette])
        mask = np.uint64((1 << self.nbits) - 1)
        for start in range(0, volume, BATCH):
            # Iteration stays x/y/z, matching Region.block_positions; packed
            # storage instead has x as its fastest-changing coordinate.
            flat = np.arange(start, min(volume, start + BATCH), dtype=np.int64)
            x, y, z = flat // (height * length), flat // length % height, flat % length
            bit = ((y * width * length) + z * width + x) * self.nbits
            word, shift = bit >> 6, (bit & 63).astype(np.uint64)
            values = self.words[word] >> shift
            split = shift + self.nbits > 64
            values[split] |= self.words[word[split] + 1] << (64 - shift[split])
            values &= mask
            if np.any(values >= len(self.palette)):
                raise IndexError("list index out of range")
            selected = np.flatnonzero(~air[values])
            for index in selected:
                yield (
                    (int(x[index]) + minimum[0], int(y[index]) + minimum[1], int(z[index]) + minimum[2]),
                    self.palette[int(values[index])],
                )


def regions(root):
    """Return descriptors; preserve legacy validation for exceptional headers."""
    try:
        result = []
        for name, item in root["Regions"].items():
            position = tuple(int(item["Position"][axis]) for axis in "xyz")
            size = tuple(int(item["Size"][axis]) for axis in "xyz")
            palette = tuple(BlockState.from_nbt(block) for block in item["BlockStatePalette"])
            entities = [Entity.from_nbt(entity) for entity in item["Entities"]]
            attached = [TileEntity.from_nbt(entity) for entity in item["TileEntities"]]
            nbits = max(ceil(log(len(palette), 2)), 2)
            count = abs(size[0] * size[1] * size[2])
            if len(item["BlockStates"]) != ceil(count * nbits / 64):
                raise ValueError("Use library length validation")
            words = np.asarray(item["BlockStates"], dtype=np.uint64)
            tuple(item["PendingBlockTicks"])
            tuple(item["PendingFluidTicks"])
            result.append(PackedRegion(str(name), position, size, palette, words, nbits, entities, attached))
        meta = root["Metadata"]
        # These fields are read by the original loader even though conversion
        # does not consume their values. Do not silently accept missing fields.
        for key in ("Author", "Name", "Description"):
            str(meta[key])
        int(meta["TimeCreated"]), int(meta["TimeModified"])
        for axis, label in enumerate("xyz"):
            minimum = min((r.position[axis] + min(0, r.size[axis] + 1) for r in result), default=0)
            maximum = max((r.position[axis] + max(0, r.size[axis] - 1) for r in result), default=-1)
            if maximum - minimum + 1 != int(meta["EnclosingSize"][label]):
                raise ValueError("Use library enclosure validation")
        if "RegionCount" in meta and len(result) != meta["RegionCount"]:
            raise ValueError("Use library region-count validation")
        return result
    except (ValueError, KeyError, TypeError, IndexError):
        # Retain the pinned library's error type, message and validation of
        # uncommon headers rather than adding a permissive alternate parser.
        schematic = Schematic.from_nbt(root)
        return [LegacyRegion(str(name), region) for name, region in schematic.regions.items()]


class LegacyRegion:
    def __init__(self, name, region):
        self.name, self.region = name, region
        self.position = (region.x, region.y, region.z)
        self.minimum = (region.min_x(), region.min_y(), region.min_z())
        self.entities, self.tile_entities = region.entities, region.tile_entities

    def blocks(self):
        for position in self.region.block_positions():
            yield position, self.region[position]
