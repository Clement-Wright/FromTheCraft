import argparse
from pathlib import Path

from .convert import convert
from .ftd import read_blueprint


def main():
    parser = argparse.ArgumentParser(description="FromTheCraft structural converter")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        parser.error("Source and destination must differ")
    result = convert(read_blueprint(args.source.read_bytes()), args.destination.suffix.lstrip("."))
    with args.destination.open("xb") as target:
        target.write(result.content)


if __name__ == "__main__":
    main()
