import argparse
from pathlib import Path

from .convert import convert
from .convert import read_file
from .compatibility import MODS


def main():
    parser = argparse.ArgumentParser(description="FromTheCraft structural converter")
    parser.add_argument(
        "--no-browser", action="store_true", help="Start the local service without opening a browser"
    )
    parser.add_argument("--port", type=int, default=0, help="Local UI port; 0 selects a free port")
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=180,
        help="Stop after this many seconds without a browser heartbeat",
    )
    commands = parser.add_subparsers(dest="command")
    conversion = commands.add_parser("convert", help="Convert a structure without opening the interface")
    conversion.add_argument("source", type=Path)
    conversion.add_argument("destination", type=Path)
    conversion.add_argument("--scale", type=float, choices=[5, 4, 3, 2, 1, 0.5, 0.25], default=1)
    conversion.add_argument("--palette", choices=["balanced", "material", "color"], default="balanced")
    conversion.add_argument(
        "--hollow", action="store_true", help="Keep an exterior shell and remove enclosed parts"
    )
    conversion.add_argument("--shell-thickness", type=int, choices=[1, 2, 3, 4], default=1)
    conversion.add_argument(
        "--detailed-copycats",
        action="store_true",
        help="Fit finer layers, bytes and panels (requires --mod copycats)",
    )
    conversion.add_argument(
        "--extreme-detail",
        action="store_true",
        help="Fit smooth slopes and independently painted small pieces (requires --mod copycats)",
    )
    conversion.add_argument(
        "--decoration-mode",
        choices=["structure", "decorations", "appearance"],
        default="structure",
        help="Choose structural or visible decorative geometry",
    )
    conversion.add_argument(
        "--surface-thickness",
        type=float,
        choices=[0.0625, 0.125, 0.25, 0.5],
        default=0.125,
        help="Thickness in output blocks for open decorative surfaces",
    )
    conversion.add_argument(
        "--mod",
        action="append",
        choices=sorted(MODS),
        default=[],
        help="Installed Minecraft mod; repeat for each add-on (default: vanilla only)",
    )
    args = parser.parse_args()
    if args.command is None:
        from .launch import launch

        launch(args.port, not args.no_browser, args.idle_timeout)
        return
    if args.source.resolve() == args.destination.resolve():
        parser.error("Source and destination must differ")
    try:
        scene = read_file(args.source.read_bytes(), args.source.suffix)
        result = convert(
            scene,
            args.destination.suffix.lstrip("."),
            args.scale,
            args.palette,
            hollow=args.hollow,
            shell_thickness=args.shell_thickness,
            mods=args.mod,
            detailed_copycats=args.detailed_copycats,
            extreme_detail=args.extreme_detail,
            decoration_mode=args.decoration_mode,
            surface_thickness=args.surface_thickness,
        )
        with args.destination.open("xb") as target:
            target.write(result.content)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Wrote {args.destination} ({len(result.content):,} bytes)")
    for message, count in result.notices.items():
        print(f"{count:,}: {message}")


if __name__ == "__main__":
    main()
