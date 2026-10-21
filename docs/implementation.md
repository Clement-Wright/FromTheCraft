# Implementation and verification

The owner's `FromTheCraft_Codex_Handoff.md` supplied the implementation scope. Later requests added 4×, 0.5× and 0.25× scales and testing against the owner's Constructables folder. No existing source or uncommitted work was present when implementation began.

## Formats and dependencies

Python 3.12.15 runs the shared converter and local service. Tested dependencies are NumPy 2.2.6, nbtlib 2.0.4, Litemapy 0.11.0b0, FastAPI 0.115.12 and Uvicorn 0.34.2. The interface uses React 19.1.0, TypeScript 5.8.3, Three.js 0.180.0 and Vite 6.4.4. The Windows build uses PyInstaller 6.13.0 and includes dependency licenses. GPL-3.0-or-later was selected to accommodate Litemapy's GPL dependency.

- nbtlib handles gzip binary tags; the structure adapter writes Java `StructureTemplate` fields with data version 3955. This matches the [Create mc1.21.1 loader](https://github.com/Creators-of-Create/Create/blob/mc1.21.1/dev/src/main/java/com/simibubi/create/content/schematics/SchematicItem.java). Successful independent parsing does not establish game acceptance.
- Litemapy's installed API was exercised for region offsets, signed dimensions, palettes, states and version selection before adoption. Its default version is overridden. A direct nbtlib adapter keeps structure-NBT validation explicit; no `.schem` intermediate or MCSchematic dependency is used.
- The 1,060-block registry comes from minecraft-data 3.100.0, explicitly selected for Java 1.21.1. Protocol numbers are not used as NBT data versions. Each known ID has a mapped, approximated or skipped family policy.
- The bundled FtD catalog and footprint table come from MIT-licensed [FtD-Blueprint-Bot revision a7c162b](https://github.com/FRUCHTBA3R/FtD-Blueprint-Bot/tree/a7c162bec615f277fa1eeecdbaf9d4680d5ac2e4). Its renderer rounds construct rotations and was not reused. The original notice is retained.
- The optional local metadata reader resolved 1,938 item IDs from the owner's installed FtD **4.3.4.0 build 1**, including inherited negative beam extents. The merged catalog has 1,941 IDs. This reads metadata in place and bundles no game files.
- FtD output uses a small inspected 3.8.5.11 schema reference, checked against installed stock blueprint schemas. The unlicensed reference's code, blueprint and author metadata are excluded. Tests independently construct their own fixtures, check ordinary output IDs, parallel arrays and the fixed 32-slot paint palette.

## Geometry and preview contract

Coordinates are X right/east, Y up, Z forward/south. FtD anchors denote cell centers; Minecraft integer positions denote cell corners. One +0.5 translation bridges these conventions. Root world placement is ignored, child local transforms compose continuously, and multi-meter footprints expand before sampling. A nested 30-degree fixture checks independently calculated coordinates rather than comparing two implementations of the same formula.

First occupied contribution wins overlaps; air never erases another region. Sampling keeps thin leading wedges and quarter-scale translated shapes. With hollowing off, interiors remain empty and internal decks remain present. Slabs, stairs, glass, paint strength and ordinary wood/metal colors have regression tests. Balanced mode preserves dark neutral paint as well as saturated colors; Material first can retain iron instead.

Source primitives remain independent of the target grid. Conversion serializes the target, reparses those exact bytes, and caches them for export. The common comparison frame retains serialization offsets and visible scale differences. Source or option changes invalidate export; superseded work is discarded. Browser tests check the download's SHA-256 against the cached result and exercise camera synchronization, unlinking, presets, keyboard controls, failed import, replacement and cancellation.

## Native hull correction in 0.2.0

The original primitive assumed that every FtD slope rose along local +Z. The installed down-slope mesh descends along that axis. A true wedge tapers across X, while triangle corners occupy a tetrahedron or its complement. Sharing one generic wedge had reversed slopes and distorted corners in both source views and exports.

The correction uses explicit convex halfspaces for down-slopes, wedges, triangle and square corners, diagonal beam cuts, offsets and transition families. Preview vertices come from the same halfspaces that conversion samples. Regression tests independently compare those vertices and planes against **76 local cached meshes across 44 normalized variants**. The game importer negates the OBJ X coordinate; checks use the cached Unity coordinates. Read-only inspection of the game's quaternion initialization confirmed all 24 existing discrete rotations, so the rotation table stays unchanged. Reverse stair output now selects FtD slope rotations with the correct high face.

Some item names are ambiguous or incorrect. Local discovery retains the actual inherited mesh reference; a small versioned table corrects 234 older bundled IDs when the game isn't installed. It contains mathematical family identifiers and provenance, with no mesh contents. Tests exercise this path in a separate process with installation discovery disabled. The older fallback still lacks some newer vanilla IDs, which remain reported omissions.

## Hollowing and inspection

Hollowing is off by default. When enabled, a scanline flood fill marks exterior air on the bounded output grid, then face-neighbor expansion keeps a shell 1–4 cells deep. Existing empty cells remain empty. Sealed interior decks and parts can disappear; openings let exterior air reach inward. Cancellation checks run during the air scan and expansion. An independent review compared 200 randomized cases at all four thicknesses with a separate breadth-first implementation and found matching results.

Hover picking uses spatial buckets before triangle tests; instanced blocks retain their identity and state through a compact palette. Keyboard I inspects the center of the focused view. Displayed coordinates are comparison-space primitive origins, not a promise of original FtD anchor coordinates. Material totals come from the parsed scenes, and the converted total therefore counts the serialized export. Placement states share a material-list row but remain visible in the hover inspector.

## Real-file evidence

All source blueprints stayed untouched and outside Git. All **13 supplied harder FtD files** completed both Minecraft formats at 1× after the native geometry correction. Independent prismarine-nbt 2.7.0 checks parsed every structure NBT. A separate JavaScript checker unpacked Litematic palette indices across 64-bit boundaries and compared every occupied position and state against the sibling NBT.

The set spans 3,652–204,146 occupied output cells, up to 147 constructs and four nesting levels. The largest result measured 129×85×319 cells, taking 27.59 seconds for NBT and 31.27 seconds for Litematic, including serialization and reparsing. The batch's cumulative Python peak working set was 443.4 MiB. Other checks ran concurrently; these observations are not a controlled benchmark.

The reported aircraft is [Experimental - Horten H.XVIII AmerikaBomber](https://steamcommunity.com/sharedfiles/filedetails/?id=3786978690). Its local source contains 20,253 structural parts. The corrected normal export contains 58,945 blocks; a one-cell hollow shell contains 19,550. Browser checks verify native source vertices, hovered names and origins in both panes, material totals, stale-output invalidation and the exact download SHA-256. Screenshots were compared with the supplied images and the Workshop reference. The source file and screenshots are not bundled for redistribution.

Stock FtD ABlock, ShipTrainer and Marauder exercised installed IDs and newer schemas. A real Java 1.21.1 Atlas structure exercised reverse conversion with both views open. Older Minecraft data versions are rejected explicitly.

## UI and verification

The six requested writing/design skills guided labels, README editing and workbench review. Superdesign supplied a restrained workbench reference; the application uses ordinary local CSS and system fonts. The 0.2.0 pass adds a compact header, collapsible materials, an always-visible conversion action and fit controls that frame the common source/result bounds. It adds no application accounts, cloud conversion or CDN runtime assets.

The Python suite passes **107 tests** with the installed catalog; disabling installation discovery passes **103 tests**, with four local-asset checks skipped. These cover formats, all five scales, nested transforms, hollow interiors, malformed input, native shape directions, stale exports and CLI overwrite protection. Ruff and the TypeScript/Vite build pass. Starlette's test client emits one dependency deprecation warning. Chromium uses SwiftShader for browser checks; no hardware-GPU frame rate is claimed.

The final Windows 0.2.0 package passes **13 browser tests** when launched from a folder with spaces. These include the real aircraft, stock FtD and large nested-ship workflows, plus independent inventory and hover-contract tests. The large nested result contains 204,146 blocks and displayed its serialized preview in 30.61 seconds. The aircraft's normal/hollow count and export hash checks also passed in the packaged build. The launcher includes its Python runtime, compiled UI, notices and original demo files; end users need no development servers. npm audit reported no known vulnerabilities in the locked dependency set during this verification.

## Unverified behavior

No exported file has been loaded in Minecraft/Create, Litematica or FtD during this build. Schema and independent-reader checks do not establish game acceptance. Ordinary curved-hull families lack a verified real fixture; thin plate slopes currently use reported footprint approximations. Real nested ships in this set use right-angle child rotations, while non-right-angle pivot evidence comes from the asymmetric mathematical fixture. Cross-game conversion is lossy; catalog policies do not promise exact appearances.
