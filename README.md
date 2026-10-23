# FromTheCraft

Convert structures between From the Depths `.blueprint` files and Minecraft Java 1.21.1 Create `.nbt` or Litematica `.litematic` files.

FromTheCraft runs locally on Windows. It converts hulls, decks and building materials.

![FromTheCraft showing the included demo hull, linked previews, a hovered block and material counts](assets/readme/workbench.png)

## Download and run

1. Open the [latest Windows release](https://github.com/Clement-Wright/FromTheCraft/releases/latest) and download the Windows ZIP under Assets.
2. Extract the entire ZIP to a folder.
3. Open `FromTheCraft.exe` in the extracted folder.

The launcher opens your browser on a free loopback port. Conversion stays on your computer, with no accounts, analytics, CDN assets or external network calls. Use **Close app** to stop the service, or close the browser tab and let it stop after three minutes without a browser heartbeat.

Try the included [demo hull](examples/demo-hull.blueprint) if you want a small starting file. The [examples folder](examples) also contains its NBT and Litematic exports.

## Convert a structure

Open or drop a `.blueprint`, `.nbt` or `.litematic` file. For an FtD source, choose **Create NBT** or **Litematic**. Minecraft sources convert to **FtD blueprint**. Choose the output scale and, for Minecraft output, a material preference: **Balanced**, **Material first** or **Color first**.

Click **Convert**, inspect both views, then click **Export file**. Hover over either preview to see the block name, material, and state. You can also focus a viewer and press **I** to inspect its center. These coordinates describe the displayed origin, which can differ from an FtD block's saved anchor.

The **Build materials** list counts source parts or exported blocks. A 4 m source beam counts as one part. The converted list counts the actual serialized blocks, grouping their facing and other placement states under the same block name. Search the list or collapse it to give the previews more space. Linked cameras help you check the same area in both views. Changing the source or conversion options clears the previous export until you convert again.

All five scales work in both directions: 4×, 2×, 1×, 0.5× and 0.25×. At 1×, one Minecraft block equals one FtD meter. Smaller scales merge occupied cells and can remove small openings or thin details. Estimated dimensions appear before conversion. Large 4× results may exceed the limits below.

**Hollow interior** is optional and off by default. Set a shell thickness of 1 to 4 output cells to keep a shell along surfaces that face outside air. Air reaches inward through openings, so the shell can follow open passages. Enclosed interior decks and parts may disappear when you enable hollowing.

### Vanilla and Create add-ons

Leave **Installed mods** at **Vanilla only** for vanilla building blocks. If a selected material has no matching slab or stair, conversion uses its full block. Painted red slopes no longer turn into stone stairs or slabs.

For modded output, open **Installed mods** and check the mods in your pack. The profile targets **Minecraft 1.21.1, NeoForge and Create 6.0.10**. It includes Copycats+, Design n' Decor, Create: Chipped, Encased, Deco, Chipped, and Bells & Whistles. Dependencies are selected automatically. FromTheCraft doesn't install mods.

The palette contains **1,237 measured full blocks and 375 matching slab/stair variants**: 237 vanilla full blocks and 1,000 across Create and its add-ons. It includes varied stone, wood, concrete, terracotta, wool, metal and static casings. Material first keeps the source material family. Balanced preserves wood and favors other matching material families; Color first chooses the closest measured color.

**Create: Copycats+** applies the selected material to copycat stairs and slabs. Enable **Detailed Copycats** for finer sampled shapes using eighth-block layers, panels, half panels, byte-panel quadrants, half-block byte octants, independently adjustable half layers, slices, boards, beams and vertical steps. It requires Copycats+ and Minecraft output, and is off by default. The pinned profile has no verified Copycat Wing block.

Detailed Copycats rounds partial shapes outward to retain the sampled hull, including thin slope tips. This avoids holes caused by choosing a smaller piece with a similar volume. Some edges become thicker at Minecraft's block resolution; the result remains an approximation.

The inspector and build list show each copycat's **Applied material**, with separate searchable rows for different materials. Counts describe exported blocks, not survival crafting costs. The exported NBT includes the applied material state and the inspected consumed-item fields. See [mod versions and format checks](MOD_COMPATIBILITY.md) for the exact profiles and unverified in-game behavior.

### Preview textures

Enable **Display textures** to use locally available texture assets in both views. Use **Load textures** to open a Minecraft 1.21.1 client JAR, mod JAR or resource-pack ZIP. Files stay in the current local session. Discovery checks `%APPDATA%\.minecraft` and the default FtD install. Set `FROMTHECRAFT_MINECRAFT` or `FROMTHECRAFT_FTD` for another installation. The texture-status panel shows what is available; missing faces keep their flat colors.

The texture toggle changes only the display. It does not change the selected materials or exported file. Previews use simplified structural geometry and do not reproduce game lighting, connected textures or custom shaders. When FtD is installed, the viewer reads supported structural base-color textures from its loose files or embedded Unity Resources. Glass and any missing textures keep their simplified appearance. FromTheCraft includes no game or mod texture assets.

### Conversion edits and inspection

Click a source part to select it; Ctrl-click toggles selection. Source material rows select a whole canonical block type, and overlapping hits can be selected separately. **Exclude selected**, **Exclude all of this type**, **Restore selected** and **Replace mapping** operate on original source records, so a four-meter beam remains one editable part. Undo/Redo and Ctrl-Z/Ctrl-Y are available. Exclusions and mapping changes clear the old export and apply before sampling and hollowing. Original files are never rewritten.

**Hide selected**, **Show hidden**, clipping planes and one-block layer views affect inspection only. They preserve the cached export. The source record browser also lists hidden and unresolved records. When a host has attached decorations, choose whether exclusion affects the host alone or its attachments too.

**Save project** downloads a local JSON file with the source hash, edit history, conversion settings and view filters. Open the original source before **Open project**; a different hash is rejected. **Save preset** keeps settings and mappings applied to an entire source type, without source record IDs. The local block browser searches enabled vanilla/mod materials, shows a textured thumbnail when assets are available, exposes verified orientation states and assigns mappings. Minecraft sources also offer nine native FtD material families.

### Decorations and mimics

With FtD installed, supported current decoration packets and mimic payloads resolve through local core item, object and mesh definitions. Static OBJ caches and simple local OBJ meshes retain their saved position, rotation, scale, paint and host identity. **Show decorations and mimics** controls the source viewer separately from conversion.

**Structure only** is the default. **Structure + decorations** adds supported visible geometry. **Appearance-focused** also removes hosts explicitly hidden by supported attachments, including intentionally empty meshes; this changes physical occupancy. Closed meshes are sampled as solids. Open surfaces use a selectable thickness of 1/16, 1/8, 1/4 or 1/2 output block. Thin details and unresolved geometry receive notices. Custom renderers, skinned meshes, unverified legacy payloads and missing local references remain unsupported. Decorative FtD output is not generated.

## How conversion works

The source preview uses native structural primitives independently of the target grid. FtD beams occupy their full footprints, and nested child transforms compose continuously before the converter samples the geometry at the selected scale. Overlapping geometry contributes to the same cell's sampled shape; the first occupied contributor supplies its material.

After sampling, the converter assigns building materials and writes the target format. It reads those exact bytes back to make the converted preview and caches them for export.

Native FtD slopes, wedges and corners use distinct convex shape definitions. Their local direction comes from checks against installed game meshes. The source viewer and converter share those definitions. Axis-aligned Minecraft output uses matching stairs and slabs, matching full blocks, or enabled copycats. Minecraft stairs become ordinary FtD slopes at 1×. Half slabs become 1 m blocks at that scale, while 2× preserves their half-height geometry. FtD paint uses RGB blended by its saved paint-strength channel. Glass transparency follows the material class.

## Conversion limits

Unsupported decorations and special blocks receive approximation or omission notices. Fluids, entities, stored item inventories and gameplay payloads are ignored. Known copycat appearance data is read for structural conversion. Unknown modded blocks use placeholders.

Minecraft input must have data version **3955**, for **Java 1.21.1**. Other versions receive an error. Litematic input supports format versions 5–7; output uses version 6.

FtD output follows the inspected **3.8.5.11** blueprint schema, also checked against installed blueprint schemas saved by 4.2.5.2 and 4.3.1.11. The bundled MIT catalog is a fallback, with versioned native-shape corrections for ambiguous IDs. When available, FromTheCraft reads the installed game's `Core_*` item metadata and inherited beam footprints locally. This was checked against **4.3.4.0 build 1**, including stock blueprints. Set `FROMTHECRAFT_FTD` to the game folder or `StreamingAssets` folder for another installation. The older bundled catalog omits some newer IDs when the game isn't installed. The app reports those omissions. No game files are copied or bundled. Ordinary curved-hull shapes and thin plate slopes still use limited approximations. FtD version compatibility and in-game acceptance need further checks.

Structure uploads are limited to 32 MiB. Texture ZIP/JAR imports have a separate 128 MiB total archive budget per session, with 512 MiB declared expanded data and 2,048-pixel image limits. Other limits are 128 MiB decompressed NBT, 500,000 occupied output cells, 2,048 cells per axis, and a 128,000,000-cell bounding volume.

Projects allow at most 10,000 commands and 32 MiB. Static meshes have per-mesh vertex/triangle limits, a two-million-triangle scene preview budget and a cancellable sampling budget. Large decorative conversions may need a smaller scale or structure-only mode. Game acceptance remains unverified; the preview reparses the exact generated file but cannot establish how a game will load it.

## Development

Use Python 3.12 and Node 22 or newer on Windows. From the repository folder:

```powershell
uv sync --python 3.12 --extra dev
Set-Location ui
npm.cmd ci
npm.cmd run build
Set-Location ..
.venv\Scripts\python -m fromthecraft
```

Tests and Windows packaging:

The portable build includes a native decorative-mesh sampler and requires the
Visual Studio C++ build tools with a Windows SDK. It uses strict floating-point
arithmetic and retains the NumPy path for boundary cases. Source installations
without a C compiler use the NumPy sampler.

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src scripts tests
.venv\Scripts\python -m fromthecraft --no-browser --port 8765
# In another terminal:
Set-Location ui
npx.cmd playwright install chromium
npm.cmd test
# From the repository folder:
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

## License and acknowledgments

GPL-3.0-or-later. See [COPYING](COPYING). Litemapy 0.11.0b0 is GPL-3.0 and supplies the Litematic adapter. nbtlib 2.0.4 handles binary NBT. UnityPy 1.25.3 (MIT) reads selected local Unity texture ranges. Three.js 0.180.0 provides instancing and orbit controls. React supplies the interface. The [FtD-Blueprint-Bot catalog](https://github.com/FRUCHTBA3R/FtD-Blueprint-Bot/tree/a7c162bec615f277fa1eeecdbaf9d4680d5ac2e4) is reused under MIT with its notice. The Minecraft registry comes from [minecraft-data 3.100.0](https://github.com/PrismarineJS/minecraft-data), also MIT. Full dependency notices ship inside the portable folder. No game assets or third-party blueprints are bundled.
