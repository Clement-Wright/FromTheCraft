"""Rebuild numeric building-palette facts from user-supplied, pinned upstream jars.

Research dependencies: Pillow. No network access; no images/assets are written.
Example: python scripts/inspect_extended_palettes.py research/mod-compat --write
The Minecraft client must be named minecraft-1.21.1-client.jar in that folder.
"""

import argparse
import hashlib
import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/fromthecraft/data"
COLORS = "white orange magenta light_blue yellow lime pink gray light_gray cyan purple blue brown green red black".split()
WOODS = "oak spruce birch jungle acacia dark_oak mangrove cherry bamboo crimson warped".split()
STONES = "granite diorite andesite calcite dripstone deepslate tuff limestone asurine crimsite ochrum veridium scoria scorchia".split()
FACES = {"north", "south", "east", "west", "up", "down"}
CLIENT_SHA1 = "30c73b1c5da787909b2f73340419fdf13b9def88"
CLIENT_URL = f"https://piston-data.mojang.com/v1/objects/{CLIENT_SHA1}/client.jar"
DOWNLOADS = {
    "create": "https://cdn.modrinth.com/data/LNytGWDc/versions/UjX6dr61/create-1.21.1-6.0.10.jar",
    "dndecor": "https://cdn.modrinth.com/data/x49wilh8/versions/uQsIRky8/Design-n-Decor-1.21.1-2.2b.jar",
    "createdeco": "https://cdn.modrinth.com/data/sMvUb4Rb/versions/qrcMVoBD/createdeco-2.1.3.jar",
    "create_chipped": "https://edge.forgecdn.net/files/7985/40/create_chipped-1.2.0-neoforge-1.21.1.jar",
    "chipped": "https://cdn.modrinth.com/data/BAscRYKm/versions/eqVowbGc/chipped-neoforge-1.21.1-4.0.2.jar",
    "createcasing": "https://cdn.modrinth.com/data/hSSqdyU1/versions/t6MATlU9/Create%20Encased-1.21.1-1.9.0-ht3.jar",
    "bellsandwhistles": "https://cdn.modrinth.com/data/gJ5afkVv/versions/w0mifib8/bellsandwhistles-0.4.7-1.21.1.jar",
}


def resource(identifier, category, extension="json"):
    namespace, value = identifier.split(":", 1) if ":" in identifier else ("minecraft", identifier)
    return f"assets/{namespace}/{category}/{value}.{extension}"


def selected_names():
    """Curated static construction families, deliberately excluding machinery."""
    vanilla = {
        "stone",
        "smooth_stone",
        "cobblestone",
        "mossy_cobblestone",
        "stone_bricks",
        "mossy_stone_bricks",
        "cracked_stone_bricks",
        "chiseled_stone_bricks",
        "bricks",
        "deepslate",
        "cobbled_deepslate",
        "polished_deepslate",
        "deepslate_bricks",
        "cracked_deepslate_bricks",
        "deepslate_tiles",
        "cracked_deepslate_tiles",
        "chiseled_deepslate",
        "granite",
        "polished_granite",
        "diorite",
        "polished_diorite",
        "andesite",
        "polished_andesite",
        "tuff",
        "polished_tuff",
        "tuff_bricks",
        "chiseled_tuff",
        "chiseled_tuff_bricks",
        "calcite",
        "dripstone_block",
        "basalt",
        "polished_basalt",
        "smooth_basalt",
        "blackstone",
        "polished_blackstone",
        "polished_blackstone_bricks",
        "chiseled_polished_blackstone",
        "cracked_polished_blackstone_bricks",
        "gilded_blackstone",
        "netherrack",
        "nether_bricks",
        "red_nether_bricks",
        "cracked_nether_bricks",
        "chiseled_nether_bricks",
        "end_stone",
        "end_stone_bricks",
        "purpur_block",
        "purpur_pillar",
        "quartz_block",
        "smooth_quartz",
        "quartz_bricks",
        "quartz_pillar",
        "chiseled_quartz_block",
        "sandstone",
        "cut_sandstone",
        "smooth_sandstone",
        "chiseled_sandstone",
        "red_sandstone",
        "cut_red_sandstone",
        "smooth_red_sandstone",
        "chiseled_red_sandstone",
        "prismarine",
        "prismarine_bricks",
        "dark_prismarine",
        "terracotta",
        "clay",
        "packed_mud",
        "mud_bricks",
        "obsidian",
        "crying_obsidian",
        "amethyst_block",
        "coal_block",
        "iron_block",
        "gold_block",
        "diamond_block",
        "emerald_block",
        "lapis_block",
        "netherite_block",
        "raw_iron_block",
        "raw_copper_block",
        "raw_gold_block",
        "copper_block",
        "exposed_copper",
        "weathered_copper",
        "oxidized_copper",
        "cut_copper",
        "exposed_cut_copper",
        "weathered_cut_copper",
        "oxidized_cut_copper",
        "waxed_copper_block",
        "waxed_exposed_copper",
        "waxed_weathered_copper",
        "waxed_oxidized_copper",
        "waxed_cut_copper",
        "waxed_exposed_cut_copper",
        "waxed_weathered_cut_copper",
        "waxed_oxidized_cut_copper",
        "chiseled_copper",
        "exposed_chiseled_copper",
        "weathered_chiseled_copper",
        "oxidized_chiseled_copper",
        "waxed_chiseled_copper",
        "waxed_exposed_chiseled_copper",
        "waxed_weathered_chiseled_copper",
        "waxed_oxidized_chiseled_copper",
        "bamboo_mosaic",
        "bamboo_block",
        "stripped_bamboo_block",
        "dried_kelp_block",
        "bone_block",
        "hay_block",
        "honeycomb_block",
        "snow_block",
    }
    vanilla.update(
        f"{c}_{kind}" for c in COLORS for kind in ("concrete", "wool", "terracotta", "glazed_terracotta")
    )
    vanilla.update(f"{w}_planks" for w in WOODS)
    vanilla.update(
        f"{prefix}{w}_{kind}"
        for w in WOODS
        if w not in {"bamboo", "crimson", "warped"}
        for prefix in ("", "stripped_")
        for kind in ("log", "wood")
    )
    vanilla.update(
        f"{prefix}{w}_{kind}"
        for w in ("crimson", "warped")
        for prefix in ("", "stripped_")
        for kind in ("stem", "hyphae")
    )
    create = {
        f"{prefix}{s}{suffix}"
        for s in STONES
        for prefix, suffix in (
            ("cut_", ""),
            ("polished_cut_", ""),
            ("cut_", "_bricks"),
            ("small_", "_bricks"),
            ("layered_", ""),
            ("", "_pillar"),
        )
    }
    create.update(
        {
            "zinc_block",
            "brass_block",
            "raw_zinc_block",
            "andesite_alloy_block",
            "rose_quartz_block",
            "rose_quartz_tiles",
            "cardboard_block",
            "bound_cardboard_block",
            "industrial_iron_block",
            "weathered_iron_block",
            "andesite_casing",
            "brass_casing",
            "copper_casing",
        }
    )
    create.update(
        f"{prefix}copper_{kind}"
        for prefix in (
            "",
            "exposed_",
            "weathered_",
            "oxidized_",
            "waxed_",
            "waxed_exposed_",
            "waxed_weathered_",
            "waxed_oxidized_",
        )
        for kind in ("tiles", "shingles")
    )
    chipped = {
        f"{c}_{kind}" for c in COLORS for kind in ("concrete_bricks", "terracotta_bricks", "terracotta_tiles")
    }
    chipped.update(f"{prefix}_{c}_wool" for prefix in ("woven", "knitted", "bundled") for c in COLORS)
    chipped.update(f"{prefix}_{w}_planks" for prefix in ("boxed", "basket_woven", "vertical") for w in WOODS)
    chipped.update(
        f"{prefix}_{s}"
        for prefix in ("polished", "tiled", "cobbled")
        for s in (
            "andesite",
            "diorite",
            "granite",
            "calcite",
            "blackstone",
            "obsidian",
            "prismarine",
            "packed_mud",
        )
    )
    chipped.update(
        f"{prefix}_{s}_block"
        for prefix in ("plated", "reinforced", "sheet", "polished")
        for s in ("iron", "gold", "diamond", "emerald")
    )
    create_chipped = {
        f"{s}_{kind}"
        for s in (
            "asurine",
            "crimsite",
            "limestone",
            "ochrum",
            "veridium",
            "scoria",
            "scorchia",
            "dark_limestone",
        )
        for kind in (
            "bricks",
            "polished",
            "cobbled",
            "flat_tiles",
            "scales",
            "smooth_inlayed",
            "rounded_bricks",
            "tiny_bricks",
            "massive_bricks",
            "tiled",
        )
    }
    return {"minecraft": vanilla, "create": create, "chipped": chipped, "create_chipped": create_chipped}


class Inspector:
    def __init__(self, jar_dir):
        from PIL import Image

        self.image = Image
        self.jar_dir = jar_dir
        self.zips = {p.name: zipfile.ZipFile(p) for p in sorted(jar_dir.glob("*.jar"))}
        self.files = {
            name: (filename, archive)
            for filename, archive in self.zips.items()
            for name in archive.namelist()
            if name.startswith(("assets/", "data/"))
        }
        self.block_tags = {}
        for path in self.files:
            if path.startswith("data/chipped/tags/block/") and path.endswith(".json"):
                for value in self.read_json(path).get("values", []):
                    if isinstance(value, str):
                        self.block_tags.setdefault(value, path)

    def read_json(self, path):
        return json.loads(self.files[path][1].read(path))

    @lru_cache(maxsize=None)
    def model(self, identifier):
        doc = self.read_json(resource(identifier, "models"))
        parent = self.model(doc["parent"]) if doc.get("parent") else {}
        assert "loader" not in doc, (identifier, "custom model loader")
        return {**parent, **doc, "textures": {**parent.get("textures", {}), **doc.get("textures", {})}}

    @lru_cache(maxsize=None)
    def texture(self, identifier):
        path = resource(identifier, "textures", "png")
        im = self.image.open(io.BytesIO(self.files[path][1].read(path))).convert("RGBA")
        # The standard animation frame size is texture width; first frame only.
        im = im.crop((0, 0, im.width, min(im.width, im.height)))
        pixels = list(im.getdata())
        assert all(pixel[3] >= 254 for pixel in pixels), (identifier, "transparent texture")
        return tuple(sum(pixel[channel] for pixel in pixels) / len(pixels) for channel in range(3))

    def cube(self, identifier):
        model = self.model(identifier)
        elements = model.get("elements", [])
        assert len(elements) == 1, (identifier, "not one cube")
        element = elements[0]
        assert element["from"] == [0, 0, 0] and element["to"] == [16, 16, 16]
        assert not element.get("rotation") and set(element["faces"]) == FACES
        textures = []
        for face in element["faces"].values():
            assert "tintindex" not in face, (identifier, "biome tinted")
            uv = face.get("uv", [0, 0, 16, 16])
            assert sorted(uv[::2]) == [0, 16] and sorted(uv[1::2]) == [0, 16], (identifier, "cropped UV")
            texture = face["texture"]
            seen = set()
            while texture.startswith("#"):
                assert texture not in seen, (identifier, "texture reference cycle")
                seen.add(texture)
                texture = model["textures"][texture[1:]]
            self.texture(texture)
            textures.append(texture)
        return textures

    def variants(self, identifier):
        return self.read_json(resource(identifier, "blockstates"))["variants"]

    def rules(self, identifier):
        rules = {}
        for key in self.variants(identifier):
            for term in key.split(","):
                if "=" in term:
                    name, value = term.split("=", 1)
                    rules.setdefault(name, set()).add(value)
        if identifier.endswith(("_slab", "_stairs")):
            rules["waterlogged"] = {"false", "true"}
        if identifier.startswith(("dndecor:", "createdeco:")) and identifier.endswith("_sheet_metal"):
            rules.update({direction: {"false", "true"} for direction in ("north", "east", "south", "west")})
        return {key: sorted(values) for key, values in sorted(rules.items())}

    def shape(self, identifier, kind, textures):
        namespace, name = identifier.split(":", 1)
        stems = [name]
        if name.endswith("_planks"):
            stems.append(name.removesuffix("_planks"))
        if name.endswith("_bricks"):
            stems.append(name.removesuffix("s"))
        if name.endswith("_tiles"):
            stems.append(name.removesuffix("s"))
        if name in {"quartz_block", "purpur_block"}:
            stems.append(name.removesuffix("_block"))
        for stem in stems:
            shape_id = f"{namespace}:{stem}_{kind}"
            path = resource(shape_id, "blockstates")
            if path not in self.files:
                continue
            try:
                variants = self.variants(shape_id)
                variant = next(
                    (value for key, value in variants.items() if "shape=straight" in key),
                    next(iter(variants.values())),
                )
                entry = variant[0] if isinstance(variant, list) else variant
                model = self.model(entry["model"])
                expected_parent = "stairs" if kind == "stairs" else "slab"
                # Only standard Minecraft stairs/slabs; excludes mod custom machinery.
                raw_model = self.read_json(resource(entry["model"], "models"))
                assert raw_model.get("parent", "").removeprefix("minecraft:") == f"block/{expected_parent}"
                used = {value for value in model["textures"].values() if not value.startswith("#")}
                assert used == set(textures)
                for alternative in variants.values():
                    for shape_model in alternative if isinstance(alternative, list) else [alternative]:
                        alternative_model = self.model(shape_model["model"])
                        assert {
                            value
                            for value in alternative_model["textures"].values()
                            if not value.startswith("#")
                        } == set(textures)
                        parent = self.read_json(resource(shape_model["model"], "models")).get("parent", "")
                        allowed = (
                            {"block/stairs", "block/inner_stairs", "block/outer_stairs"}
                            if kind == "stairs"
                            else {"block/slab", "block/slab_top", "block/cube_all", "block/cube_column"}
                        )
                        # Slab double variants may directly reference the verified full cube.
                        if parent.removeprefix("minecraft:") not in allowed:
                            assert kind == "slab" and set(self.cube(shape_model["model"])) == set(textures)
                return shape_id
            except (KeyError, AssertionError):
                continue
        return None

    def block(self, identifier, material):
        variants = self.variants(identifier)
        rules = self.rules(identifier)
        assert set(rules) <= {"axis", "facing", "north", "east", "south", "west"}
        # Validate every visual state, including every random model alternative.
        for variant in variants.values():
            for entry in variant if isinstance(variant, list) else [variant]:
                self.cube(entry["model"])
        defaults = {
            "axis": "y",
            "facing": "north",
            "north": "false",
            "east": "false",
            "south": "false",
            "west": "false",
        }
        key = min(
            variants,
            key=lambda value: sum(
                term.split("=", 1)[1] != defaults.get(term.split("=", 1)[0])
                for term in value.split(",")
                if "=" in term
            ),
        )
        properties = dict(term.split("=", 1) for term in key.split(",") if "=" in term)
        # Nonvisual connection properties intentionally remain at engine defaults.
        variant = variants[key]
        alternatives = variant if isinstance(variant, list) else [variant]
        weight = sum(entry.get("weight", 1) for entry in alternatives)
        rgb = [0.0, 0.0, 0.0]
        textures = set()
        for entry in alternatives:
            faces = self.cube(entry["model"])
            textures.update(faces)
            for texture in faces:
                for channel, value in enumerate(self.texture(texture)):
                    rgb[channel] += value * entry.get("weight", 1) / weight / 6 / 255
        path = resource(identifier, "blockstates")
        namespace, name = identifier.split(":", 1)
        evidence = {
            "jar": self.files[path][0],
            "blockstate": path,
            "models": sorted({entry["model"] for entry in alternatives}),
            "texture_samples": sorted(textures),
            "sample_variant": key,
            "geometry": "all visual variants resolve to a complete opaque six-face 16x16x16 cube",
        }
        loot = f"data/{namespace}/loot_table/blocks/{name}.json"
        if namespace != "minecraft":
            if loot in self.files:
                evidence["loot_table"] = loot
            else:
                assert identifier in self.block_tags, (identifier, "no upstream block tag or loot evidence")
                evidence["block_tag"] = self.block_tags[identifier]
                evidence["registration_class"] = "earth/terrarium/chipped/common/registry/ModBlocks.class"
        stairs = self.shape(identifier, "stairs", textures)
        slab = self.shape(identifier, "slab", textures)
        for kind, shape in (("stairs", stairs), ("slab", slab)):
            if shape:
                evidence[kind + "_blockstate"] = resource(shape, "blockstates")
        return {
            "name": identifier,
            "rgb": [round(value, 6) for value in rgb],
            "rgb8": [round(value * 255) for value in rgb],
            "material": material,
            "properties": properties,
            "stairs": stairs,
            "slab": slab,
            "evidence": evidence,
        }


def material(name):
    if any(
        token in name
        for token in ("copper", "iron", "gold", "netherite", "brass", "zinc", "metal", "alloy", "casing")
    ):
        return "Metal"
    if any(token in name for token in ("planks", "_log", "_wood", "_stem", "hyphae", "bamboo", "cardboard")):
        return "Wood"
    return "Stone"


def build(jar_dir):
    inspector = Inspector(jar_dir)
    client = jar_dir / "minecraft-1.21.1-client.jar"
    assert hashlib.sha1(client.read_bytes()).hexdigest() == CLIENT_SHA1, "Wrong Minecraft client version"
    previous = json.loads((DATA / "mod_palette_1_21_1.json").read_text(encoding="utf-8"))
    registry = {
        "minecraft:" + block["name"]: block
        for block in json.loads((DATA / "minecraft_1_21_1.json").read_text(encoding="utf-8"))["blocks"]
    }
    sources = [
        {key: value for key, value in mod.items() if key not in {"blocks", "states"}}
        for mod in previous["mods"]
    ]
    for source in sources:
        if source["namespace"] == "copycats":
            continue
        filename = next(
            b["evidence"]["jar"]
            for mod in previous["mods"]
            if mod["namespace"] == source["namespace"]
            for b in mod["blocks"]
        )
        source["jar"] = filename
        source["download_url"] = DOWNLOADS[source["namespace"]]
        assert hashlib.sha512((jar_dir / filename).read_bytes()).hexdigest() == source["sha512"]
    sources.insert(
        0,
        {
            "slug": "vanilla",
            "namespace": "minecraft",
            "label": "Minecraft",
            "version": "1.21.1",
            "jar": client.name,
            "sha1": CLIENT_SHA1,
            "sha512": hashlib.sha512(client.read_bytes()).hexdigest(),
            "download_url": CLIENT_URL,
            "license": "Minecraft EULA / Usage Guidelines",
            "source": "https://www.minecraft.net/en-us/eula",
            "license_note": "EULA reviewed 2026-10-21: Mojang retains its game content and restricts redistribution. This file records numeric observations only; no game assets redistributed.",
        },
    )
    selections = selected_names()
    for namespace in ("dndecor", "createdeco", "createcasing", "bellsandwhistles"):
        ids = {
            path.rsplit("/", 1)[1][:-5]
            for path in inspector.files
            if path.startswith(f"assets/{namespace}/blockstates/") and path.endswith(".json")
        }
        if namespace == "dndecor":
            selections[namespace] = {
                name
                for name in ids
                if name.endswith(("_dark_metal_block", "_stone_metal", "_velvet_block", "_sheet_metal"))
            }
            selections[namespace].update({"dark_metal_block", "dark_metal_bricks", "dark_metal_plating"})
            selections[namespace].update(
                f"{prefix}{stone}{suffix}"
                for stone in ("amethyst", "dolomite", "gabbro", "weathered_limestone", "packed_mud")
                for prefix, suffix in (
                    ("cut_", ""),
                    ("polished_cut_", ""),
                    ("cut_", "_bricks"),
                    ("small_", "_bricks"),
                    ("layered_", ""),
                )
            )
        elif namespace == "createdeco":
            selections[namespace] = {name for name in ids if name.endswith(("_bricks", "_sheet_metal"))}
        elif namespace == "createcasing":
            selections[namespace] = {"zinc_casing"}
        else:
            selections[namespace] = {"metro_casing", "corrugated_metro_casing", "station_platform"}
    slugs = {source["namespace"]: source["slug"] for source in sources}
    output = {
        "minecraft_version": "1.21.1",
        "loader": "neoforge",
        "method": "Curated inert building families. Every selected full block's visual variants resolve through model parents to one full 16-cube with six untinted, uncropped, opaque faces. RGB is arithmetic sRGB mean of frame-zero pixels (alpha >=254), weighted equally by cube face and by model variant weights for the selected state. Shape families require matching textures and standard Minecraft slab/stairs parents. State declarations use bundled vanilla 1.21.1 registry; mod visual variants plus standard shape waterlogged and source-verified ConnectedPillarBlock connection booleans. Numeric facts and resource identifiers only; no assets redistributed.",
        "sources": sources,
        "blocks": [],
        "states": {},
        "excluded": [],
    }
    existing = {block["name"] for mod in previous["mods"] for block in mod["blocks"]}
    for namespace, names in sorted(selections.items()):
        count = 0
        for name in sorted(names):
            identifier = f"{namespace}:{name}"
            if identifier in existing:
                continue
            if resource(identifier, "blockstates") not in inspector.files:
                # Family names differ between mods; never invent missing IDs.
                continue
            try:
                block = inspector.block(identifier, material(name))
                if namespace == "minecraft":
                    assert (
                        identifier in registry
                        and registry[identifier]["boundingBox"] == "block"
                        and not registry[identifier]["transparent"]
                    )
                block["mod"] = slugs[namespace]
                output["blocks"].append(block)
                count += 1
                for block_id in (identifier, block["stairs"], block["slab"]):
                    if block_id is None:
                        continue
                    if namespace == "minecraft":
                        output["states"][block_id] = {
                            rule["name"]: rule.get(
                                "values",
                                ["false", "true"]
                                if rule["type"] == "bool"
                                else [str(i) for i in range(rule["num_values"])],
                            )
                            for rule in registry[block_id]["states"]
                        }
                    else:
                        output["states"][block_id] = inspector.rules(block_id)
            except (AssertionError, KeyError) as error:
                output["excluded"].append({"name": identifier, "reason": str(error)})
        print(f"{namespace}: {count} additional full blocks")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jars", type=Path, help="Directory of pinned upstream jars; nothing is downloaded")
    parser.add_argument(
        "--write", action="store_true", help="Write bundled JSON; default verifies exact reproducibility"
    )
    args = parser.parse_args()
    output = build(args.jars)
    target = DATA / "expanded_palette_1_21_1.json"
    if args.write:
        target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    else:
        assert json.loads(target.read_text(encoding="utf-8")) == output, (
            "Bundled palette differs from pinned jar observations"
        )
    print(
        f"Verified {len(output['blocks'])} full blocks and {len(output['states'])} states; {len(output['excluded'])} candidates excluded"
    )


if __name__ == "__main__":
    main()
