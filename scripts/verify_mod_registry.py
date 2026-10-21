"""Check bundled block facts against user-supplied, version-pinned mod jars."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "jars", type=Path, help="Folder containing the pinned mod jars; nothing is downloaded"
    )
    args = parser.parse_args()
    registry = Path(__file__).resolve().parents[1] / "src/fromthecraft/data/mod_palette_1_21_1.json"
    for mod in json.loads(registry.read_text(encoding="utf-8"))["mods"]:
        if not mod["blocks"]:
            continue  # Copycats+ schema evidence is source-derived, with its own fixture check.
        jar = args.jars / mod["blocks"][0]["evidence"]["jar"]
        assert hashlib.sha512(jar.read_bytes()).hexdigest() == mod["sha512"], f"Wrong jar version: {jar}"
        with zipfile.ZipFile(jar) as archive:
            for name, expected in mod["states"].items():
                namespace, identifier = name.split(":", 1)
                entry = json.loads(archive.read(f"assets/{namespace}/blockstates/{identifier}.json"))
                actual = {}
                for variant in entry["variants"]:
                    for term in variant.split(","):
                        if "=" in term:
                            key, value = term.split("=", 1)
                            actual.setdefault(key, set()).add(value)
                # Standard slabs/stairs inherit a nonvisual waterlogged property.
                if name.endswith(("_stairs", "_slab")):
                    actual["waterlogged"] = {"false", "true"}
                if mod["slug"] in {"create-deco", "create-design-n-decor"} and name.endswith("_sheet_metal"):
                    # These pinned classes inherit Create's ConnectedPillarBlock;
                    # connection flags are registered in code, independent of models.
                    actual.update(
                        {direction: {"false", "true"} for direction in ("east", "north", "south", "west")}
                    )
                assert {key: sorted(values) for key, values in actual.items()} == expected, name
            for block in mod["blocks"]:
                evidence = block["evidence"]
                assert evidence["blockstate"] in archive.namelist(), block["name"]
                for texture in evidence["texture_samples"]:
                    namespace, identifier = texture.split(":", 1)
                    assert f"assets/{namespace}/textures/{identifier}.png" in archive.namelist(), texture
        print(
            f"{mod['label']}: pinned SHA-512, {len(mod['blocks'])} palette blocks, {len(mod['states'])} state definitions verified"
        )


if __name__ == "__main__":
    main()
