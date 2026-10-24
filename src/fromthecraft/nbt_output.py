"""Write exact structure records without a tag-object tree per placement."""

import gzip
import io
import struct
from functools import lru_cache

import nbtlib as nbt

from .copycats import block_state_tag
from .model import DATA_VERSION, State

_POSITION = struct.Struct(">iii")
_ENTITY_POSITION = struct.Struct(">4si4si4si")
_POSITION_HEADER = b"\x09\x00\x03pos\x03\x00\x00\x00\x03"
_BLOCKS_HEADER = b"\x09\x00\x06blocks\x0a"
_ENTITY_HEADER = b"\x0a\x00\x03nbt"
_ROOT_END = b"\x09\x00\x08entities\x0a\x00\x00\x00\x00\x00"
_AXES = tuple(b"\x03\x00\x01" + axis for axis in (b"x", b"y", b"z"))


def _payload(tag):
    stream = io.BytesIO()
    tag.write(stream)
    return stream.getvalue()


def encode_structure(cells, size, entity_at):
    ordered = sorted(cells)
    palette, indices = [], {}

    @lru_cache(maxsize=4096)
    def fragment(state):
        entity = entity_at(state, (0, 0, 0))
        bare = State(state.name, state.properties)
        if bare not in indices:
            indices[bare] = len(palette)
            palette.append(block_state_tag(bare))
        prefix = _payload(nbt.Compound({"state": nbt.Int(indices[bare])}))
        if entity is None:
            return prefix, b""
        # The local Copycats entity factory puts the three Int coordinates
        # first. Only those values vary; its nested paid-item/material data
        # remains byte-for-byte the nbtlib encoding of this immutable state.
        for axis in "xyz":
            entity.pop(axis)
        return prefix[:-1] + _ENTITY_HEADER, _payload(entity) + b"\x00"

    # Preserve first appearance in sorted placement order, including multiple
    # copied materials sharing one bare palette entry. The second pass keeps
    # only a bounded number of encoded templates, rather than all block tags.
    for position in ordered:
        fragment(cells[position])
    stream = io.BytesIO()
    nbt.File(
        {
            "DataVersion": nbt.Int(DATA_VERSION),
            "size": nbt.List[nbt.Int](size),
            "palette": nbt.List[nbt.Compound](palette),
        }
    ).write(stream)
    stream.seek(-1, io.SEEK_CUR)  # Continue the root compound before its end tag.
    stream.write(_BLOCKS_HEADER + struct.pack(">i", len(ordered)))
    for position in ordered:
        prefix, suffix = fragment(cells[position])
        stream.write(_POSITION_HEADER)
        stream.write(_POSITION.pack(*position))
        stream.write(prefix)
        if suffix:
            x, y, z = position
            stream.write(_ENTITY_POSITION.pack(_AXES[0], x, _AXES[1], y, _AXES[2], z))
            stream.write(suffix)
    stream.write(_ROOT_END)
    return gzip.compress(stream.getvalue(), mtime=0)
