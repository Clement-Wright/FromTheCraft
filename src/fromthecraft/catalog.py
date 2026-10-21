import json
import os
from pathlib import Path


def game_assets():
    configured = os.environ.get("FROMTHECRAFT_FTD")
    if configured:
        root = Path(configured)
        if root.name == "StreamingAssets":
            return root
        return root / "From_The_Depths_Data/StreamingAssets"
    return (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Steam/steamapps/common/From The Depths/From_The_Depths_Data/StreamingAssets"
    )


def installed_catalog(root, baseline):
    """Read metadata from an optional local game install; never extract or redistribute assets."""
    root = Path(root)
    definitions = {}
    issues = []
    if not (root / "Mods").exists():
        return {}, {"entries": 0, "version": "bundled MIT catalog", "issues": []}
    for pattern in ("Core_*/Items/*.item", "Core_*/ItemDup/*.itemduplicateandmodify"):
        for path in sorted((root / "Mods").glob(pattern)):
            try:
                item = json.loads(path.read_bytes())
                definitions[item["ComponentId"]["Guid"]] = item
            except (OSError, UnicodeError, KeyError, TypeError, json.JSONDecodeError) as exc:
                issues.append(f"{path.name}: {exc}")
    resolved = {}

    def resolve(guid, seen=()):
        if guid in resolved:
            return resolved[guid]
        if guid in seen or len(seen) > 16:
            raise ValueError("Cyclic or excessive item inheritance")
        item = definitions.get(guid)
        if item is None:
            if guid in baseline:
                return baseline[guid].copy()
            raise ValueError(f"Undefined item parent {guid}")
        parent = item.get("IdToDuplicate", {}).get("Reference", {}).get("Guid")
        entry = resolve(parent, seen + (guid,)).copy() if parent else {}
        name = item["ComponentId"]["Name"]
        entry.update(baseline.get(guid, {}))
        entry["Name"] = name
        mesh = item.get("MeshReference", {})
        if mesh.get("IsValidReference"):
            mesh_name = mesh.get("Reference", {}).get("Name")
            if isinstance(mesh_name, str) and mesh_name:
                entry["MeshName"] = mesh_name
        if "Material" not in entry:
            lower = name.lower()
            entry["Material"] = next(
                (
                    label
                    for word, label in [
                        ("heavy armour", "Heavy Armour"),
                        ("alloy", "Alloy"),
                        ("glass", "Glass"),
                        ("wood", "Wood"),
                        ("stone", "Stone"),
                        ("rubber", "Rubber"),
                        ("lead", "Lead"),
                    ]
                    if word in lower
                ),
                "Metal",
            )
        size = item.get("SizeInfo")
        if size and (not parent or item.get("change_SizeInfo")):
            footprint = {
                axis + suffix: int(size[key][axis])
                for axis in "xyz"
                for suffix, key in [("n", "SizeNeg"), ("p", "SizePos")]
            }
            if any(n < 0 or n > 256 for n in footprint.values()):
                raise ValueError(f"Invalid footprint for {name}")
            entry["Footprint"] = footprint
        if "Footprint" not in entry and "SizeId" not in entry:
            raise ValueError(f"No footprint for {name}")
        color = item.get("LowLevelOfDetailColor")
        if color:
            values = tuple(float(n) for n in color.split(","))
            if len(values) == 4 and all(0 <= n <= 1 for n in values):
                entry["DefaultColor"] = values[:3]
        resolved[guid] = entry
        return entry

    for guid in definitions:
        try:
            resolve(guid)
        except (ValueError, KeyError, TypeError) as exc:
            issues.append(f"{guid}: {exc}")
    version = "installed game (version unavailable)"
    try:
        builds = json.loads((root / "BuildLog.json").read_bytes())
        version = builds[-1]["Version"].replace(",", ".") + " build " + str(builds[-1]["Build"])
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        pass
    return resolved, {"entries": len(resolved), "version": version, "issues": issues}
