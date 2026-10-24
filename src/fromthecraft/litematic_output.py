"""Exact bulk output adapter for the pinned litemapy 0.11.0b0 Region layout."""

from math import ceil, log

import nbtlib as nbt
import numpy as np
from litemapy import Region


class OutputRegion(Region):
    """Unique in-range placements need no palette scans or renumbering."""

    def __init__(self, *args):
        super().__init__(*args)
        self._indices = {self.palette[0].to_block_state_identifier(): 0}

    def __setitem__(self, position, block):
        identifier = block.to_block_state_identifier()
        if identifier not in self._indices:
            self._indices[identifier] = len(self._Region__palette)
            self._Region__palette.append(block)
        self._Region__blocks[position] = self._indices[identifier]

    def to_nbt(self):
        # Every non-air palette entry is used by at least one unique cell, and
        # identifiers are unique. The original optimizer would change nothing.
        root = nbt.Compound()
        root["Position"] = nbt.Compound({a: nbt.Int(v) for a, v in zip("xyz", (self.x, self.y, self.z))})
        root["Size"] = nbt.Compound(
            {a: nbt.Int(v) for a, v in zip("xyz", (self.width, self.height, self.length))}
        )
        root["BlockStatePalette"] = nbt.List[nbt.Compound]([state.to_nbt() for state in self.palette])
        root["Entities"] = nbt.List[nbt.Compound]([entity.to_nbt() for entity in self.entities])
        root["TileEntities"] = nbt.List[nbt.Compound]([entity.to_nbt() for entity in self.tile_entities])
        root["PendingBlockTicks"] = nbt.List[nbt.Compound](self.block_ticks)
        root["PendingFluidTicks"] = nbt.List[nbt.Compound](self.fluid_ticks)
        nbits = max(ceil(log(len(self.palette), 2)), 2)
        volume = self.volume()
        words = np.zeros(ceil(volume * nbits / 64), dtype=np.uint64)
        for start in range(0, volume, 65536):
            flat = np.arange(start, min(volume, start + 65536), dtype=np.int64)
            x = flat % self.width
            z, y = flat // self.width % self.length, flat // (self.width * self.length)
            values = self._Region__blocks[x, y, z].astype(np.uint64)
            bit = flat * nbits
            word, shift = bit >> 6, (bit & 63).astype(np.uint64)
            np.bitwise_or.at(words, word, values << shift)
            split = shift + nbits > 64
            np.bitwise_or.at(words, word[split] + 1, values[split] >> (64 - shift[split]))
        root["BlockStates"] = nbt.LongArray(words.view(np.int64))
        return root
