import argparse
import ctypes
import gc
import json
import time
from pathlib import Path

from fromthecraft.convert import convert, read_file
from fromthecraft.geometry import quaternion
from fromthecraft.preview import preview
from fromthecraft.compatibility import MODS


def peak_working_set_mb():
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working",
                "working",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = wintypes.HANDLE
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    query.restype = wintypes.BOOL
    if query(process(), ctypes.byref(counters), ctypes.sizeof(counters)):
        return round(counters.peak_working / 1024**2, 1)
    return None


def construct_stats(construct, depth=0):
    import numpy as np

    count, deepest, continuous = 1, depth, 0
    if depth:
        rotation = quaternion([float(n) for n in construct.get("LocalRotation", "0,0,0,1").split(",")])
        continuous = int(np.max(np.abs(rotation - np.round(rotation))) > 1e-3)
    for child in construct.get("SCs", []):
        child_count, child_depth, child_continuous = construct_stats(child, depth + 1)
        count += child_count
        deepest = max(deepest, child_depth)
        continuous += child_continuous
    return count, deepest, continuous


def main():
    parser = argparse.ArgumentParser(
        description="Read-only source-fixture checks; generated exports stay in artifacts"
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument("--litematic", action="store_true", help="Also test every fixture as Litematic")
    parser.add_argument("--detailed-copycats", action="store_true")
    parser.add_argument("--mods", nargs="*", choices=sorted(MODS), default=[])
    parser.add_argument("--output", type=Path, default=Path("artifacts/fixture-checks"))
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in sorted(args.folder.glob("*.blueprint")):
        report = {"name": path.name}
        try:
            started = time.perf_counter()
            content = path.read_bytes()
            document = json.loads(content)
            report.update(
                zip(
                    ("constructs", "max_depth", "continuous_rotations"),
                    construct_stats(document["Blueprint"]),
                )
            )
            scene = read_file(content, "blueprint")
            report.update(
                version=scene.version,
                source_primitives=len(scene.parts),
                parse_s=round(time.perf_counter() - started, 3),
            )
            for format in ["nbt", "litematic"] if args.litematic else ["nbt"]:
                started = time.perf_counter()
                result = convert(scene, format, mods=args.mods, detailed_copycats=args.detailed_copycats)
                display = preview(result.scene, result.offset)
                (output / (path.stem + "." + format)).write_bytes(result.content)
                report[format] = {
                    "seconds": round(time.perf_counter() - started, 3),
                    "bytes": len(result.content),
                    "primitives": len(result.scene.parts),
                    "dimensions": display["dimensions"],
                    "unknown_ids": sum(v for k, v in result.notices.items() if "Unrecognized" in k),
                    "copycat_cells": sum(
                        part.state.copied_material is not None for part in result.scene.parts
                    ),
                    "notices": dict(result.notices),
                }
                del result, display
            report["state"] = "passed"
            del content, document, scene
        except (ValueError, OSError) as exc:
            report.update(state="failed", error=str(exc))
        gc.collect()
        report["process_peak_mb"] = peak_working_set_mb()
        reports.append(report)
        print(json.dumps({k: v for k, v in report.items() if k not in {"nbt", "litematic"}}), flush=True)
        (output / "report.json").write_text(
            json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if any(report["state"] == "failed" for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
