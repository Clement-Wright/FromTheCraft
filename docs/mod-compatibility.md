# Minecraft mod profiles

The profiles target Minecraft Java **1.21.1**, data version **3955**, **NeoForge**, and **Create 6.0.10**. The dropdown starts empty. Enabling an add-on also selects its dependencies among the supported mods. Install the mods and their own dependencies in Minecraft; FromTheCraft only writes their block IDs and safe appearance data.

| Mod                                                                                                          | Inspected version | Palette                                                                    |
| ------------------------------------------------------------------------------------------------------------ | ----------------- | -------------------------------------------------------------------------- |
| Vanilla Minecraft                                                                                            | 1.21.1            | 228 measured solid blocks, 112 matching variants                           |
| [Create](https://modrinth.com/mod/create/version/UjX6dr61)                                                   | 6.0.10            | 113 solid blocks, 114 matching variants; applied-material panels and steps |
| [Create: Copycats+](https://github.com/copycats-plus/copycats/tree/9f808ac0b437817696c50f2e8b57f590b1196094) | 3.0.4+mc1.21.1    | Applied-material stairs, slabs, layers, bytes, byte panels and half panels |
| [Create: Design n' Decor](https://www.curseforge.com/minecraft/mc-mods/create-design-n-decor)                | 2.2b              | 164 solid blocks, 39 matching variants                                     |
| [Create Deco](https://modrinth.com/mod/create-deco)                                                          | 2.1.3             | 61 solid blocks, 110 matching variants                                     |
| [Create: Chipped](https://www.curseforge.com/minecraft/mc-mods/create-chipped/files/7985040)                 | File 7985040      | 80 solid blocks                                                            |
| [Chipped](https://modrinth.com/mod/chipped)                                                                  | 4.0.2             | 149 solid blocks                                                           |
| [Create Encased](https://modrinth.com/mod/create-encased)                                                    | 1.21.1-1.9.0-ht3  | Zinc casing                                                                |
| [Create: Bells & Whistles](https://modrinth.com/mod/bellsandwhistles)                                        | 0.4.7-1.21.1      | Two metro casings                                                          |

Create: Chipped's inspected file has conflicting version labels: the release title says 1.1.0, its filename says 1.2.0, and embedded metadata says 1.0.0. The profile therefore identifies the exact file and SHA-512. It requires Create and Chipped. Encased's inspected version requires Create 6.0.10 or newer. Chipped also needs Resourceful Lib and Athena; install the dependencies specified by each mod's release.

The [original registry](../src/fromthecraft/data/mod_palette_1_21_1.json) and [expanded palette](../src/fromthecraft/data/expanded_palette_1_21_1.json) record release links, hashes, embedded version/license/dependency declarations, block IDs, state values and model/texture paths. Version 0.4.0 adds 735 measured entries to the original 63, for **798 solid blocks and 375 matching slab/stair variants**. The selection covers colored concrete, terracotta, wool, wood, masonry, metals and static casings. Functional machinery is excluded.

The original entries were checked for opaque cube models and matching texture families or direct crafting recipes. Every expanded full-block candidate must resolve through its model parents to a complete, untinted, opaque cube in every visual state. Expanded shapes must use standard Minecraft slab/stair model parents and the same texture set as their full block. RGB values average the first texture frame over the six cube faces, including model weights where a state has random alternatives. This measures the default assets; resource packs can change their appearance.

Vanilla choices are always available. Enabled mod profiles extend those choices. Material first restricts matching to the source material family. Balanced preserves wood families and gives other matching material families a small preference; Color first chooses by measured color. A matching native slab or stair follows the selected full material. When none exists, the converter retains that full block.

Visual model variants omit some runtime properties. The sheet-metal entries also include the four connection booleans registered by Create's `ConnectedPillarBlock`, verified from the pinned mod classes. Unfamiliar mod input properties receive an approximation notice while valid orientation is kept; generated output remains strictly validated.

## Copycat format

Copycats+ has two different serializers. These fields were checked against [revision 9f808ac](https://github.com/copycats-plus/copycats/tree/9f808ac0b437817696c50f2e8b57f590b1196094):

| Geometry block                                          | Block entity ID               | Appearance data                                                         |
| ------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------- |
| `copycats:copycat_stairs`                               | `copycats:copycat`            | `Material`, `Item`, `EnableCT`                                          |
| `copycats:copycat_slab`                                 | `copycats:multistate_copycat` | `material_data.bottom` / `.top`: `material`, `consumedItem`, `enableCT` |
| `copycats:copycat_layer`, `copycats:copycat_half_panel` | `copycats:copycat`            | `Material`, `Item`, `EnableCT`                                          |
| `copycats:copycat_byte`                                 | `copycats:multistate_copycat` | Eight `material_data` octants: `material`, `consumedItem`, `enableCT`   |
| `copycats:copycat_byte_panel`                           | `copycats:multistate_copycat` | Four `material_data` quadrants: `material`, `consumedItem`, `enableCT`  |
| `create:copycat_panel`, `create:copycat_step`           | `create:copycat`              | `Material`, `Item`, `EnableCT`                                          |

Materials store the applied block's `Name` and optional `Properties`. Item stacks use lowercase `count` as an integer, following the [Minecraft item-stack format introduced in 1.20.5](https://www.minecraft.net/en-us/article/minecraft-java-edition-1-20-5). Empty stacks are empty compounds. Inactive multistate parts retain `create:copycat_base` and no consumed item. Active parts sharing an applied block ID share one consumed item. Connected textures are enabled on generated copycats. The file references the applied block; it embeds no texture images.

Ordinary exports use straight stairs and slabs along any of the three axes. Thin slope tips retain their sampled partial shape, including after rotation. **Detailed Copycats** adds a finer fit over the union of contributing source geometry. It can select layers in eighth-block increments, 3/16-thick panels, half panels, byte panels and half-block octants, independently adjustable half layers, slices, boards, beams and vertical steps, or retain a full block. It is an optional sampled approximation and requires Copycats+. The pinned Copycats+ version has no verified Copycat Wing block, so wings are not offered.

Reverse imports read the inspected stair shapes, slab axes and additional container shapes. Distinct materials on occupied slab halves, byte octants or byte-panel quadrants retain separate structural parts. The reader requires matching consumed items, including the inspected shared-item rule; some manually edited or migrated material-only copycats therefore receive a notice. Reverse conversion uses geometry and applied material; connected-texture toggles and gameplay state do not carry into FtD.

![Original painted slope fixture beside its 1× Copycats approximation, with partial thin ends and applied-material counts](images/slopes-copycats.png)

Structure NBT attaches block entity compounds under each block's `nbt` field. Litematic stores them directly in each region's `TileEntities` list. Signed region dimensions need an offset from the minimum corner before associating a tile entity with its block. The inspected [Litematica 1.21.1 reader](https://github.com/maruohon/litematica/blob/dc426db5b2ff93cc56790287d203d03944facf5d/src/main/java/fi/dy/masa/litematica/schematic/LitematicaSchematic.java) supports the same structural fields through format version 7. FromTheCraft accepts versions 5–7 and writes version 6, always requiring Minecraft data version 3955.

Additional supported static families use `copycats:copycat` for beams, vertical steps and the three slice types, and `copycats:multistate_copycat` for boards and the three half-layer types. Half-layer slots are `negative_layers` and `positive_layers` (0–8); board slots are the six face names. These dimensions and transforms were checked against the pinned `CCShapes.java`. Functional shafts, pipes, doors and other moving machinery are outside conversion scope.

## Reproduce the checks

The original four-block fixtures contain red concrete stairs, glass stairs, blue concrete slabs and cyan stained-glass slabs. They were authored from the inspected schema, independently of the application's writer. They are not captures from Minecraft. Run:

```powershell
node scripts\verify_copycats.cjs
.venv\Scripts\python -m pytest tests/test_copycats.py
.venv\Scripts\python scripts/verify_mod_registry.py path\to\pinned-mod-jars
python scripts/inspect_extended_palettes.py path\to\pinned-mod-jars
.venv\Scripts\python -m fromthecraft convert input.blueprint output.nbt --mod copycats --mod create-deco
```

The JavaScript check uses prismarine-nbt, compares complete block-entity payloads and checks integer item counts and byte CT flags. The registry checker verifies jar hashes, blockstate definitions and texture-path existence without downloading anything. The expanded-palette script also resolves models and recomputes every bundled RGB value. It requires Pillow for research, the pinned mod jars and the official 1.21.1 client named `minecraft-1.21.1-client.jar`; Pillow is also installed through UnityPy for local FtD texture decoding. The sibling-file Litematic checker also compares every block entity with structure NBT, as well as independently unpacking its block palette.

These checks establish file encoding and agreement with inspected schemas. **Minecraft placement, Schematicannon material use, connected-texture rendering and Litematica placement have not been tested in game.** Modpack tags can change which applied materials copycats accept.

## Local preview textures

**Display textures** uses locally available Minecraft client, mod or resource-pack assets. **Load textures** accepts a local ZIP or JAR and keeps its assets in the current local session. Missing faces keep their measured flat colors. Texture display changes neither material selection nor exported files; connected textures, custom shaders and the game's full rendering pipeline are not reproduced.

FtD material definitions may refer to textures embedded in Unity resources rather than loose image files. The viewer reads selected structural base-color images with UnityPy 1.25.3. It uses the local Resources name index and bounded pixel ranges, without loading the entire asset archive. Seven structural base-color textures were read from the installed game; glass has no base-color reference. Missing textures remain flat. No images are downloaded or bundled.

## Licensing

No mod jars, source implementations, models or texture images are distributed with FromTheCraft. The bundled data contains block identifiers, numeric color measurements and format facts. Create and Design n' Decor separate code and asset licensing; Copycats+ reserves its rights. Chipped declares restricted licensing. Create Deco's Modrinth metadata says MIT while its inspected jar declares All Rights Reserved; the registry retains both declarations. Create: Chipped declares CC BY-NC 3.0, Encased MIT, and Bells & Whistles GPL-3.0-or-later. The app implements the small appearance serializers itself and does not include these mods as dependencies.
