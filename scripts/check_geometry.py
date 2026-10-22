"""Compare native source volume with serialized NBT near reported hover origins.

This is an independent sampler, not the converter's voxelizer or target reader.
FtD parsing/native halfspace facts come from the app; volume sampling and target
box interpretation are separate. Advanced dimensions come from the original
source-inspected research contract, never production copycats.geometry_boxes.
All coordinates are comparison-world coordinates, and each supplied hover point
is checked across its +/-1-cell neighborhood to cover transformed stair origins.
"""

import argparse
import json
from itertools import product
from pathlib import Path

import nbtlib
import numpy as np

from fromthecraft.convert import read_file
from fromthecraft.ftd_shapes import planes


def bounds(part):
    corners = np.array(list(product(*[(0, extent) for extent in part.size])))
    world = corners @ part.transform[:3, :3].T + part.transform[:3, 3]
    return world.min(0), world.max(0)


def native_occupancy(parts, points):
    result = np.zeros(len(points), dtype=bool)
    contributors = []
    low, high = points.min(0), points.max(0)
    for part, minimum, maximum in parts:
        if np.any(minimum > high) or np.any(maximum < low):
            continue
        inverse = np.linalg.inv(part.transform)
        local = (points @ inverse[:3, :3].T + inverse[:3, 3]) / part.size
        inside = np.all((local >= 0) & (local <= 1), axis=1)
        clipping = planes(part.shape)
        if clipping:
            coefficients = np.array(clipping)
            inside &= np.all(local @ coefficients[:, :3].T <= coefficients[:, 3] + 1e-9, axis=1)
        elif part.shape == "wedge":
            inside &= local[:, 1] <= local[:, 2]
        elif part.shape == "curve":
            inside &= local[:, 1] ** 2 + (1 - local[:, 2]) ** 2 <= 1
        elif part.shape == "corner":
            inside &= (local[:, 1] <= local[:, 2]) & (local[:, 1] <= local[:, 0])
        else:
            assert part.shape == "box", f"Unsupported source primitive: {part.shape}"
        if inside.any():
            result |= inside
            contributors.append(
                {
                    "name": part.identity,
                    "shape": part.shape,
                    "origin": part.transform[:3, 3].tolist(),
                    "size": list(part.size),
                    "sample_fraction": float(inside.mean()),
                }
            )
    return result, contributors


def nbt_states(path, offset):
    root = nbtlib.load(path)
    assert int(root["DataVersion"]) == 3955
    palette = [
        {
            "name": str(state["Name"]),
            "properties": {str(key): str(value) for key, value in state.get("Properties", {}).items()},
        }
        for state in root["palette"]
    ]
    return {
        tuple(int(n) + int(o) for n, o in zip(block["pos"], offset)): palette[int(block["state"])]
        for block in root["blocks"]
    }


def serialized_boxes(state, contract):
    if state is None:
        return []
    name, props = state["name"], state["properties"]
    family = name.removeprefix("copycats:copycat_")
    extras = {
        "half_layer",
        "vertical_half_layer",
        "stacked_half_layer",
        "beam",
        "board",
        "vertical_step",
        "slice",
        "vertical_slice",
        "corner_slice",
    }
    if name.startswith("copycats:") and family in extras:
        # Independently interpreted CCShapes base boxes; rotate all eight corners.
        raw = []
        if family == "beam":
            lo, hi = np.full(3, 0.25), np.full(3, 0.75)
            axis = "xyz".index(props.get("axis", "y"))
            lo[axis], hi[axis] = 0, 1
            return [np.r_[lo, hi]]
        if family == "board":
            for direction, axis, positive in (
                ("east", 0, True),
                ("west", 0, False),
                ("up", 1, True),
                ("down", 1, False),
                ("south", 2, True),
                ("north", 2, False),
            ):
                if props.get(direction) == "true":
                    box = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
                    box[axis], box[axis + 3] = (15 / 16, 1) if positive else (0, 1 / 16)
                    raw.append(box)
            return raw
        if family.endswith("half_layer"):
            for positive, slot in ((False, "negative_layers"), (True, "positive_layers")):
                h = int(props.get(slot, "0")) / 8
                if not h:
                    continue
                if family == "half_layer":
                    raw.append((0, 0, 0.5 if positive else 0, 1, h, 1 if positive else 0.5))
                elif family == "vertical_half_layer":
                    raw.append((0.5 if positive else 0, 0, 1 - h, 1 if positive else 0.5, 1, 1))
                else:
                    raw.append((0, 0.5 if positive else 0, 1 - h, 1, 1 if positive else 0.5, 1))
        elif family == "vertical_step":
            raw = [(0.5, 0, 0.5, 1, 1, 1)]
        else:
            h = int(props.get("layers", "1")) / 8
            raw = [
                (0, 0, 1 - h, 1, h, 1)
                if family == "slice"
                else (1 - h, 0, 1 - h, 1, 1, 1)
                if family == "vertical_slice"
                else (1 - h, 0, 1 - h, 1, h, 1)
            ]
        facing = (
            ("east" if props.get("axis", "x") == "x" else "south")
            if family == "half_layer"
            else props.get("facing", "south")
        )
        result = []
        for box in raw:
            corners = list(product(*zip(box[:3], box[3:])))
            transformed = []
            for x, y, z in corners:
                if props.get("half") == "top":
                    y = 1 - y
                transformed.append(
                    {
                        "south": (x, y, z),
                        "north": (1 - x, y, 1 - z),
                        "east": (z, y, 1 - x),
                        "west": (1 - z, y, x),
                    }[facing]
                )
            points = np.array(transformed)
            result.append(np.r_[points.min(0), points.max(0)])
        return result
    if name in contract["blocks"]:
        spec = contract["blocks"][name]
        props = {**spec["defaults"], **props}
        if "boxes_by_slot" in spec:
            boxes = [box for slot, box in spec["boxes_by_slot"].items() if props[slot] == "true"]
        elif "boxes_by_facing_and_slot" in spec:
            boxes = [
                box
                for slot, box in spec["boxes_by_facing_and_slot"][props["facing"]].items()
                if props[slot] == "true"
            ]
        elif "boxes_by_facing_and_offset" in spec:
            boxes = [spec["boxes_by_facing_and_offset"][props["facing"]][props["offset"]]]
        elif "boxes_by_facing_and_half" in spec:
            boxes = [spec["boxes_by_facing_and_half"][props["facing"]][props["half"]]]
        elif name.endswith("_layer"):
            boxes = [spec["boxes"][props["facing"]][props["layers"]]]
        else:
            boxes = [spec["boxes"][props["facing"]]]
        return [np.array(box, dtype=float) / 16 for box in boxes]
    if name.endswith("_slab"):
        box = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        if props.get("type") != "double":
            axis = "xyz".index(props.get("axis", "y")) if name == "copycats:copycat_slab" else 1
            if props.get("type") == "top":
                box[axis] = 0.5
            else:
                box[axis + 3] = 0.5
        return [box]
    if name.endswith("_stairs"):
        assert props.get("shape", "straight") == "straight", "This export check supports straight stairs only"
        # A stair is one full horizontal half plus a half-width adjoining half.
        top = props.get("half") == "top"
        base = [0.0, 0.5 if top else 0.0, 0.0, 1.0, 1.0 if top else 0.5, 1.0]
        raised = [0.0, 0.0 if top else 0.5, 0.0, 1.0, 0.5 if top else 1.0, 1.0]
        facing = props.get("facing", "north")
        axis = 0 if facing in {"east", "west"} else 2
        raised[axis + (0 if facing in {"east", "south"} else 3)] = 0.5
        return [np.array(base), np.array(raised)]
    assert not name.startswith("copycats:"), f"Unrecognized copycat geometry: {name}"
    return [np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])]


def target_occupancy(state, local_points, contract):
    result = np.zeros(len(local_points), dtype=bool)
    for box in serialized_boxes(state, contract):
        result |= np.all((local_points >= box[:3]) & (local_points < box[3:]), axis=1)
    return result


def compare(source, exports, points, contract, samples=16):
    parts = [(part, *bounds(part)) for part in source.parts]
    offset = np.floor(np.min([minimum for _, minimum, _ in parts], axis=0) + 1e-6).astype(int)
    decoded = {label: nbt_states(path, offset) for label, path in exports.items()}
    grid = np.array(list(product((np.arange(samples) + 0.5) / samples, repeat=3)))
    report = {
        "offset": offset.tolist(),
        "samples_per_axis": samples,
        "method": "Independent center-volume samples of parsed native source primitives and schema-derived serialized target boxes. Hover origins may differ from cell corners; inspect +/-1 cells. No game rendering or collision engine used.",
        "exports": {label: str(path) for label, path in exports.items()},
        "points": [],
    }
    for point in points:
        center = np.floor(point).astype(int)
        cells = []
        totals = {
            label: {
                "mismatched_samples": 0,
                "false_positive_samples": 0,
                "false_negative_samples": 0,
                "sampled_full_source_cells_made_partial": 0,
            }
            for label in exports
        }
        for delta in product(range(-1, 2), repeat=3):
            position = tuple(int(value) for value in center + delta)
            original, contributors = native_occupancy(parts, grid + position)
            cell = {
                "position": position,
                "source_fraction": float(original.mean()),
                "contributors": contributors,
                "targets": {},
            }
            for label, states in decoded.items():
                state = states.get(position)
                target = target_occupancy(state, grid, contract)
                false_positive, false_negative = (
                    int((target & ~original).sum()),
                    int((original & ~target).sum()),
                )
                cell["targets"][label] = {
                    "state": state,
                    "fraction": float(target.mean()),
                    "false_positive_fraction": false_positive / len(grid),
                    "false_negative_fraction": false_negative / len(grid),
                    "mismatch_fraction": (false_positive + false_negative) / len(grid),
                }
                total = totals[label]
                total["mismatched_samples"] += false_positive + false_negative
                total["false_positive_samples"] += false_positive
                total["false_negative_samples"] += false_negative
                total["sampled_full_source_cells_made_partial"] += int(original.all() and not target.all())
            cells.append(cell)
        for total in totals.values():
            total["mismatch_fraction"] = total["mismatched_samples"] / (len(grid) * len(cells))
        report["points"].append({"reported_origin": list(point), "neighborhood": totals, "cells": cells})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--export", action="append", required=True, help="LABEL=structure.nbt; repeat for each output"
    )
    parser.add_argument("--point", action="append", required=True, help="x,y,z comparison-world hover origin")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("tests/fixtures/copycats-shapes.json"),
        help="Original source-inspected Copycats+ shape contract, not application code",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert 2 <= args.samples <= 64
    exports = {label: Path(path) for label, path in (value.split("=", 1) for value in args.export)}
    points = [tuple(float(value) for value in point.split(",")) for point in args.point]
    assert all(len(point) == 3 for point in points)
    source = read_file(args.source.read_bytes(), "blueprint")
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = compare(source, exports, points, contract, args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    for point in result["points"]:
        print(json.dumps({key: value for key, value in point.items() if key != "cells"}))


if __name__ == "__main__":
    main()
