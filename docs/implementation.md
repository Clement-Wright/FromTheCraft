# Implementation and verification

The owner's `FromTheCraft_Codex_Handoff.md` supplied the implementation scope. Later requests added 4×, 0.5× and 0.25× scales and testing against the owner's Constructables folder. No existing source or uncommitted work was present when implementation began.

## Formats and dependencies

Python 3.12.15 runs the shared converter and local service. Tested dependencies are NumPy 2.2.6, nbtlib 2.0.4, Litemapy 0.11.0b0, FastAPI 0.115.12 and Uvicorn 0.34.2. The interface uses React 19.1.0, TypeScript 5.8.3, Three.js 0.180.0 and Vite 6.4.4. The Windows build uses PyInstaller 6.13.0 and includes dependency licenses. GPL-3.0-or-later was selected to accommodate Litemapy's GPL dependency. No repository or release has been published.

- nbtlib handles gzip binary tags; the structure adapter writes Java `StructureTemplate` fields with data version 3955. This matches the [Create mc1.21.1 loader](https://github.com/Creators-of-Create/Create/blob/mc1.21.1/dev/src/main/java/com/simibubi/create/content/schematics/SchematicItem.java). Successful independent parsing does not establish game acceptance.
- Litemapy's installed API was exercised for region offsets, signed dimensions, palettes, states and version selection before adoption. Its default version is overridden. A direct nbtlib adapter keeps structure-NBT validation explicit; no `.schem` intermediate or MCSchematic dependency is used.
- The 1,060-block registry comes from minecraft-data 3.100.0, explicitly selected for Java 1.21.1. Protocol numbers are not used as NBT data versions. Each known ID has a mapped, approximated or skipped family policy.
- The bundled FtD catalog and footprint table come from MIT-licensed [FtD-Blueprint-Bot revision a7c162b](https://github.com/FRUCHTBA3R/FtD-Blueprint-Bot/tree/a7c162bec615f277fa1eeecdbaf9d4680d5ac2e4). Its renderer rounds construct rotations and was not reused. The original notice is retained.
- The optional local metadata reader resolved 1,938 item IDs from the owner's installed FtD **4.3.4.0 build 1**, including inherited negative beam extents. The merged catalog has 1,941 IDs. This reads metadata in place and bundles no game files.
- FtD output uses a small inspected 3.8.5.11 schema reference, checked against installed stock blueprint schemas. The unlicensed reference's code, blueprint and author metadata are excluded. Tests independently construct their own fixtures, check ordinary output IDs, parallel arrays and the fixed 32-slot paint palette.

## Geometry and preview contract

Coordinates are X right/east, Y up, Z forward/south. FtD anchors denote cell centers; Minecraft integer positions denote cell corners. One +0.5 translation bridges these conventions. Root world placement is ignored, child local transforms compose continuously, and multi-meter footprints expand before sampling. A nested 30-degree fixture checks independently calculated coordinates rather than comparing two implementations of the same formula.

First occupied contribution wins overlaps; air never erases another region. Sampling keeps thin leading wedges and quarter-scale translated shapes. Interiors remain empty and internal decks remain present. Slabs, stairs, glass, paint strength and ordinary wood/metal colors have regression tests. Balanced mode preserves dark neutral paint as well as saturated colors; Material first can retain iron instead.

Source primitives remain independent of the target grid. Conversion serializes the target, reparses those exact bytes, and caches them for export. The common comparison frame retains serialization offsets and visible scale differences. Source or option changes invalidate export; superseded work is discarded. Browser tests check the download's SHA-256 against the cached result and exercise camera synchronization, unlinking, presets, keyboard controls, failed import, replacement and cancellation.

## Real files checked locally

All third-party inputs were read in place. Generated files and measurements are in ignored `artifacts/`; no ship files are committed or bundled.

Stock FtD ABlock, ShipTrainer and Marauder exercised basic parsing and newer installed IDs. A real Minecraft 1.21.1 Atlas structure exercised reverse conversion with both views open. Older Minecraft data versions are rejected explicitly.

All 13 blueprints in the supplied Constructables folder converted to both Minecraft formats at 1×. Independent prismarine-nbt 2.7.0 parsed each NBT. A separate JavaScript Litematic checker unpacked palette indices across 64-bit boundaries and compared every occupied position and state against the sibling NBT.

| Blueprint | Occupied output cells | NBT seconds | Litematic seconds |
| --- | ---: | ---: | ---: |
| Aegis Bread Update | 140,774 | 16.17 | 28.50 |
| ARD AS-05-A Cygnus | 91,323 | 10.99 | 12.81 |
| B2A3 - Spirit of Freedom v1967 Compatible | 11,902 | 1.94 | 1.95 |
| BC - 061A Claymore | 205,523 | 24.49 | 29.33 |
| Constellation Class Battle-Frigate | 23,246 | 3.21 | 3.12 |
| Constrictor | 5,786 | 0.84 | 0.86 |
| Experimental - Horten HXVIII AmerikaBomber | 59,135 | 10.61 | 10.16 |
| Fledgling | 3,663 | 0.59 | 0.61 |
| MC80 Home One | 70,802 | 10.38 | 9.62 |
| Revenant | 6,265 | 1.04 | 1.04 |
| Stormcaller | 6,228 | 0.91 | 0.84 |
| The Falx | 26,259 | 3.43 | 3.10 |
| 飛空艇ラグナロク | 36,198 | 5.58 | 5.84 |

Times include conversion, serialization and reparsing, excluding initial source parsing. This batch ran alongside packaging work on the development machine; these are observations rather than benchmarks. Its cumulative Python peak working set was 428.6 MiB. A separate Claymore scale run peaked at 566.2 MiB. Claymore required raising the occupied-cell limit from 200,000 to 500,000. Its 0.5× and 0.25× NBT outputs contain 31,103 and 5,176 occupied cells. The set exercises up to 147 constructs and four nesting levels, with no unknown IDs; known special parts still receive approximation or omission notices. These batch timings precede the final dark-paint palette correction, which changes material choices rather than occupancy.

## Interface and Windows checks

The six requested skills were installed and read: Deslop, Make Interfaces Feel Better, no-ai-slop, Superdesign, Anti AI Slop Writing and Humanizer. The workbench uses local system fonts, restrained colors, visible focus, reduced-motion handling and compact notices. Deslop and the writing skills were applied to code comments, labels, errors and documentation. Superdesign supplied a workbench draft after the owner approved the context upload; it is not an application dependency.

The portable folder was built on Windows and launched from a path containing spaces. Seven Chromium workflow tests passed against the final executable, including Atlas, Marauder and Claymore. At 1366×768, the paired views fit the window and the settings area scrolls. Claymore displayed 205,523 converted primitives in about 37 seconds including its serialized preview; both cameras and fixed views remained operable. Its downloaded NBT matched the cached SHA-256 and the final Litematic's independently unpacked states. Chromium used SwiftShader for these automated checks; no hardware-GPU frame rate is claimed. Close app stopped the packaged service, an idle-shutdown test exited with code 0, and normal launch served bundled assets on its selected loopback port.

All 69 Python tests pass. They cover malformed and oversized records, both adapters and directions, all five scales, continuous transforms, native shape families, empty results, stale exports, Unicode filenames and CLI overwrite refusal. Ruff, the TypeScript/Vite build and independent format checks pass. npm audit reports no known dependency vulnerabilities at the time of verification. The Python run emits one dependency deprecation warning from Starlette's AnyIO test-client integration. A final independent code review found no new correctness defects in the launcher, packaging or installed-catalog reader.

## Unverified behavior

No exported file has been loaded in Minecraft/Create, Litematica or FtD during this build. Reverse blueprint schema and IDs have structural checks, but game acceptance remains unverified. Ordinary curved-hull families lack a verified real fixture; their primitive and sampling tests are synthetic. The real nested ships contain right-angle child rotations, so non-right-angle pivot evidence comes from the asymmetric mathematical fixture. Cross-game conversion is lossy; catalog policies do not promise exact appearances.
