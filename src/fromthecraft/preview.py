import numpy as np

from .geometry import bounds
from .ftd_shapes import vertices


def preview(scene, offset=(0, 0, 0), textures=None):
    groups, blocks, block_ids, inventory = {}, [], {}, {}
    records = {
        r.id: {
            "id": r.id,
            "type_key": r.type_key,
            "kind": r.kind,
            "path": list(r.path),
            "parent_path": list(r.parent_path),
            "host_id": r.host_id,
            "name": r.name or r.type_key,
            "hide_host": r.hide_host,
            "geometry_status": r.geometry_status,
        }
        for r in scene.source_records
    }
    counted = set()
    for part in scene.parts:
        record = part.source_record
        if record:
            records.setdefault(
                record.id,
                {
                    "id": record.id,
                    "type_key": record.type_key,
                    "kind": record.kind,
                    "path": list(record.path),
                    "parent_path": list(record.parent_path),
                    "host_id": record.host_id,
                    "name": part.identity,
                },
            )
        properties = tuple(sorted(part.state.properties)) if part.state else ()
        copied = part.state.copied_material if part.state else None
        if part.state and part.material_slot:
            copied = dict(part.state.copied_materials).get(part.material_slot, copied)
        extra = (
            {"copied_material": {"name": copied.name, "properties": dict(copied.properties)}}
            if copied
            else {}
        )
        identity = (part.identity, part.material, properties, copied)
        if identity not in block_ids:
            block_ids[identity] = len(blocks)
            block = {
                "name": part.identity,
                "material": part.material,
                "properties": dict(properties),
                **extra,
            }
            if textures:
                if scene.format == "blueprint":
                    texture = textures.ftd_face(part.material)
                    faces = (
                        {face: texture for face in ("east", "west", "up", "down", "south", "north")}
                        if texture
                        else {}
                    )
                else:
                    faces = textures.block_faces(
                        copied.name if copied else part.identity, copied.properties if copied else properties
                    )
                if faces:
                    block["textures"] = faces
            blocks.append(block)
        slots = part.state.copied_materials if part.state else ()
        inventory_material = "Mixed" if slots else part.material
        inventory_copied = part.state.copied_material if part.state else None
        material_key = (
            part.identity,
            inventory_material,
            inventory_copied,
            slots,
            record.type_key if record else None,
        )
        placement = part.source_record.id if part.source_record else part.source_cell
        if placement is None or placement not in counted:
            inventory[material_key] = inventory.get(material_key, 0) + 1
            counted.add(placement)
        key = (part.shape, part.transparent, id(part.mesh[0]) if part.mesh else None)
        group = groups.setdefault(
            key,
            {
                "shape": part.shape,
                "transparent": part.transparent,
                "matrices": [],
                "colors": [],
                "block_indices": [],
                "source_ids": [],
                "decoration": part.decoration,
            },
        )
        group["block_indices"].append(block_ids[identity])
        group["source_ids"].append(record.id if record else None)
        hull_vertices = vertices(part.shape)
        if part.mesh and "vertices" not in group:
            group["vertices"] = np.asarray(part.mesh[0])[part.mesh[1]].reshape(-1).tolist()
            group["triangles"] = True
        if hull_vertices and "vertices" not in group:
            group["vertices"] = list(hull_vertices)
        matrix = part.transform.copy()
        matrix[:3, :3] = matrix[:3, :3] @ np.diag(part.size)
        matrix[:3, 3] += offset
        group["matrices"].extend(np.round(matrix.T.reshape(-1), 6).tolist())
        group["colors"].extend([round(float(c), 6) for c in part.color])
    low, high = bounds(scene)
    coverage = {
        "resolved_faces": sum(len(block.get("textures", {})) for block in blocks),
        "missing_faces": sum(6 - len(block.get("textures", {})) for block in blocks),
        "missing_blocks": sorted(
            {
                block.get("copied_material", {}).get("name", block["name"])
                for block in blocks
                if len(block.get("textures", {})) < 6
            }
        ),
    }
    return {
        "source_hash": scene.source_hash,
        "records": list(records.values()),
        "texture_coverage": coverage,
        "groups": list(groups.values()),
        "blocks": blocks,
        "materials": [
            {
                "name": name,
                "material": material,
                "properties": {},
                "count": count,
                **({"type_key": type_key} if type_key else {}),
                **(
                    {
                        "copied_materials": [
                            {"slot": slot, "name": state.name, "properties": dict(state.properties)}
                            for slot, state in slots
                        ]
                    }
                    if slots
                    else {}
                ),
                **(
                    {"copied_material": {"name": copied.name, "properties": dict(copied.properties)}}
                    if copied
                    else {}
                ),
            }
            for (name, material, copied, slots, type_key), count in sorted(
                inventory.items(), key=lambda item: (-item[1], item[0][0], str(item[0][2]))
            )
        ],
        "count": len(scene.parts),
        "bounds": [(low + offset).tolist(), (high + offset).tolist()],
        "dimensions": np.round(high - low, 3).tolist(),
        "format": scene.format,
        "version": scene.version,
    }
