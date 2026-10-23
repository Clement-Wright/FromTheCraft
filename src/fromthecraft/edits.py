"""Reversible source-record edits; imported geometry remains untouched."""

import json
from dataclasses import replace

from .compatibility import BUILDING_BLOCKS
from .model import State
from .palettes import validate_state
from .palettes import BLOCKS


class EditLayer:
    def __init__(self, scene):
        self.records = {record.id: record for record in scene.source_records}
        for part in scene.parts:
            if part.source_record:
                self.records.setdefault(part.source_record.id, part.source_record)
        self.commands = []
        self.cursor = 0
        self.revision = 0
        self.excluded, self.hidden, self.mappings = set(), set(), {}

    def _replay(self):
        self.excluded, self.hidden, self.mappings = set(), set(), {}
        for command in self.commands[: self.cursor]:
            ids, kind = command["ids"], command["kind"]
            if kind == "exclude":
                self.excluded.update(ids)
            elif kind == "hide":
                self.hidden.update(ids)
            elif kind == "show":
                self.hidden.difference_update(ids)
            elif kind == "restore":
                self.excluded.difference_update(ids)
                for record in ids:
                    self.mappings.pop(record, None)
            elif kind == "mapping":
                self.mappings.update({record: command["mapping"] for record in ids})

    def apply(self, command):
        if len(self.commands) >= 10_000:
            raise ValueError("Edit history exceeds 10,000 commands")
        if not isinstance(command, dict) or set(command) - {
            "kind",
            "ids",
            "type_keys",
            "mapping",
            "attachments",
        }:
            raise ValueError("Unknown edit fields")
        kind = command.get("kind")
        if kind not in {"exclude", "restore", "hide", "show", "mapping"}:
            raise ValueError("Unknown edit operation")
        ids, types = command.get("ids", []), command.get("type_keys", [])
        if (
            not isinstance(ids, list)
            or not isinstance(types, list)
            or any(not isinstance(v, str) for v in ids + types)
        ):
            raise ValueError("Edit targets must be record IDs or type keys")
        selected = set(ids)
        if not selected <= self.records.keys():
            raise ValueError("Unknown source record")
        known_types = {record.type_key for record in self.records.values()}
        if not set(types) <= known_types:
            raise ValueError("Unknown source type")
        selected.update(key for key, record in self.records.items() if record.type_key in types)
        if not selected:
            raise ValueError("Select source records first")
        children = {
            key for key, record in self.records.items() if record.host_id in selected and key not in selected
        }
        policy = command.get("attachments")
        if policy not in (None, "host", "all"):
            raise ValueError("Invalid attachment policy")
        if kind == "exclude" and children:
            if policy is None:
                raise ValueError("Choose host only or host and attachments")
            if policy == "all":
                selected.update(children)
        clean = {"kind": kind, "ids": sorted(selected)}
        if kind == "mapping":
            mapping = command.get("mapping")
            if not isinstance(mapping, dict) or set(mapping) - {"name", "properties", "full_block"}:
                raise ValueError("Invalid mapping")
            name, properties = mapping.get("name"), mapping.get("properties", {})
            if (
                not isinstance(name, str)
                or not isinstance(properties, dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in properties.items())
            ):
                raise ValueError("Invalid mapping state")
            target = State(name, tuple(sorted(properties.items())))
            validate_state(target)
            if name not in BUILDING_BLOCKS and not (
                name in BLOCKS and name.endswith((":glass", "_stained_glass"))
            ):
                raise ValueError("Choose a verified building material")
            full = mapping.get("full_block", False)
            if not isinstance(full, bool):
                raise ValueError("Invalid full-block mapping option")
            clean["mapping"] = {"name": name, "properties": properties, "full_block": full}
        commands = self.commands[: self.cursor] + [clean]
        if len(json.dumps(commands).encode()) > 32 * 1024**2:
            raise ValueError("Edit history exceeds 32 MiB")
        self.commands, self.cursor = commands, len(commands)
        self.revision += 1
        self._replay()
        return kind not in {"hide", "show"}

    def undo(self):
        if not self.cursor:
            return False
        self.cursor -= 1
        changed = self.commands[self.cursor]["kind"] not in {"hide", "show"}
        self.revision += 1
        self._replay()
        return changed

    def redo(self):
        if self.cursor == len(self.commands):
            return False
        changed = self.commands[self.cursor]["kind"] not in {"hide", "show"}
        self.cursor += 1
        self.revision += 1
        self._replay()
        return changed

    def snapshot(self):
        return {
            "revision": self.revision,
            "excluded": sorted(self.excluded),
            "hidden": sorted(self.hidden),
            "mappings": self.mappings.copy(),
            "can_undo": self.cursor > 0,
            "can_redo": self.cursor < len(self.commands),
        }

    def derive(self, scene):
        parts = []
        for part in scene.parts:
            key = part.source_record.id if part.source_record else None
            if key in self.excluded:
                continue
            mapping = self.mappings.get(key)
            if mapping:
                part = replace(
                    part,
                    mapping_override=State(mapping["name"], tuple(sorted(mapping["properties"].items()))),
                    mapping_full=mapping["full_block"],
                )
            parts.append(part)
        return replace(
            scene,
            parts=parts,
            source_records=tuple(r for r in scene.source_records if r.id not in self.excluded),
        )
