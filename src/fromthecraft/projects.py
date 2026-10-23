"""Portable conversion projects. Native source bytes are never rewritten."""

import json
from copy import deepcopy

from .edits import EditLayer

MAX_PROJECT_BYTES = 32 * 1024**2


def export_project(scene, edits, filename, settings, view):
    return {
        "schema": 1,
        "kind": "fromthecraft-project",
        "source": {"name": filename, "hash": scene.source_hash, "format": scene.format},
        "commands": deepcopy(edits.commands),
        "cursor": edits.cursor,
        "settings": settings,
        "view": view,
    }


def import_project(document, scene):
    if (
        not isinstance(document, dict)
        or len(json.dumps(document, allow_nan=False).encode()) > MAX_PROJECT_BYTES
    ):
        raise ValueError("Project exceeds 32 MiB")
    if (
        type(document.get("schema")) is not int
        or document.get("schema") != 1
        or document.get("kind") != "fromthecraft-project"
    ):
        raise ValueError("Unsupported project schema")
    if set(document) - {"schema", "kind", "source", "commands", "cursor", "settings", "view"}:
        raise ValueError("Unknown project fields")
    source = document.get("source")
    if not isinstance(source, dict) or source.get("hash") != scene.source_hash:
        raise ValueError("Source hash does not match. Open the original source file first.")
    commands, cursor = document.get("commands"), document.get("cursor")
    if (
        not isinstance(commands, list)
        or len(commands) > 10_000
        or type(cursor) is not int
        or not 0 <= cursor <= len(commands)
    ):
        raise ValueError("Invalid project history")
    settings, view = document.get("settings"), document.get("view", {})
    if not isinstance(settings, dict) or not isinstance(view, dict):
        raise ValueError("Invalid project settings or view")
    layer = EditLayer(scene)
    for command in commands:
        layer.apply(command)
    while layer.cursor > cursor:
        layer.undo()
    return layer, settings, view
