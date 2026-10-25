"""Preview our own written states without a second complete NBT object tree.

This is only for the unique placements just passed to the local writers.
Uploaded files always use the bounded, validating file readers.
"""

import hashlib
from collections import Counter
from functools import lru_cache

import numpy as np
from litemapy import BlockState

from .copycats import block_state_tag
from .geometry import checked_size
from .minecraft import (
    _entity_factory,
    accept,
    read_litematic,
    read_structure,
    scene_from_cells,
    state_template,
)
from .model import MAX_PARTS, Cancelled, SourceRecord, State


def export_scene(states, size, format, content, cancelled=None, progress=None):
    """Use the writer's order and the reader's state/material normalization."""
    checked_size(size)
    if format not in {"nbt", "litematic"}:
        raise ValueError("Generated preview requires Minecraft output")
    if len(states) > MAX_PARTS:
        raise ValueError(f"Input exceeds {MAX_PARTS:,} block records")
    if cancelled and cancelled():
        raise Cancelled("Conversion cancelled")
    ordinary = all(
        len(position) == 3
        and all(
            isinstance(value, (int, np.integer))
            and abs(int(value)) <= 100_000
            and (format == "nbt" or not isinstance(value, (bool, np.bool_)) and 0 <= value < size[axis])
            for axis, value in enumerate(position)
        )
        for position in states
    )
    if not ordinary:
        return (read_structure if format == "nbt" else read_litematic)(content)
    source_hash = hashlib.sha256(content).hexdigest()
    notices = Counter()
    entity_at = _entity_factory()

    @lru_cache(maxsize=4096)
    def normalized(state):
        # Follow exactly the writer's bare palette and entity representation,
        # then the reader's validation, inert-state policy and copied materials.
        bare = State(state.name, state.properties)
        template = state_template(BlockState.from_nbt(block_state_tag(bare)))
        one, delta = {}, Counter()
        accept(one, (0, 0, 0), None, delta, entity_at(state, (0, 0, 0)), template=template)
        return one.get((0, 0, 0)), delta

    def entries():
        # Both structure output and the pinned Litematic reader iterate x/y/z,
        # independently of Litematic's different packed-storage order.
        for index, position in enumerate(sorted(states)):
            if index % 256 == 0:
                if cancelled and cancelled():
                    raise Cancelled("Conversion cancelled")
                if progress:
                    progress(0.95 + 0.04 * index / max(1, len(states)))
            state, delta = normalized(states[position])
            notices.update(delta)
            if state is None:
                continue
            position = tuple(int(value) for value in position)
            path = (
                ("blocks", str(index))
                if format == "nbt"
                else ("Regions", "Structure", ",".join(str(value) for value in position))
            )
            record = SourceRecord(
                f"{source_hash}:{'/'.join(path)}",
                state.name,
                "block",
                path,
                () if format == "nbt" else ("Regions", "Structure"),
            )
            yield position, state, record

    return scene_from_cells({}, format, notices, source_hash=source_hash, entries=entries())
