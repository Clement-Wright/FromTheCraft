# FromTheCraft

Convert structures between From the Depths `.blueprint` files and Minecraft Java 1.21.1 Create `.nbt` or `.litematic` files. Compare structural source and converted previews with linked cameras, then export the exact file shown in the converted view.

## Windows

Open `dist\FromTheCraft\FromTheCraft.exe`. Keep the whole portable folder together; it includes Python and the compiled interface. No Python or Node installation is needed to use it. The launcher opens your browser on a free loopback port. Use **Close app**, or close the browser tab; the service stops after three minutes without a browser heartbeat.

Open or drop a file, choose the output format and scale, click **Convert**, then **Export file**. Scale choices are 4×, 2×, 1×, 0.5× and 0.25× in both directions. At 1×, one Minecraft block equals one FtD meter. Smaller scales merge occupied cells and can remove small openings. Estimated dimensions appear before conversion. Changing options invalidates the old export.

## Conversion limits

The converter preserves occupied structure and internal decks without filling cavities. Beams use their full footprints. Ordinary slopes and corners use sampled primitives; axis-aligned output can use Minecraft stairs and slabs. Saved child transforms are composed continuously and baked into static geometry. Minecraft stairs become ordinary FtD slopes at 1×; half slabs become 1 m blocks, while 2× preserves their half-height geometry. First occupied contribution wins overlaps. FtD paint uses RGB blended by its saved paint-strength channel; glass transparency follows the material class.

Mimics and recognized decoration overlays are skipped. Special blocks receive inert approximations or documented omissions, with aggregated notices. Fluids, entities, inventories and gameplay payloads are ignored. There is no machinery, physics, mimic reconstruction or Aeronautics assembly. Unknown modded blocks use reported inert placeholders.

Minecraft input must have data version **3955**, for **Java 1.21.1**. Other versions receive an error; there is no data fixer. The version-pinned registry contains 1,060 IDs, each with a mapped, approximated or skipped family policy. These policies do not promise exact appearances. Litematic input supports multiple offset regions and signed dimensions.

FtD output follows the inspected **3.8.5.11** blueprint schema, also checked against installed blueprint schemas saved by 4.2.5.2 and 4.3.1.11. The bundled MIT catalog is a fallback. When available, FromTheCraft reads the installed game's `Core_*` item metadata and inherited beam footprints locally. This was checked against **4.3.4.0 build 1**, including the stock ABlock, ShipTrainer and Marauder files. Set `FROMTHECRAFT_FTD` to the game folder or `StreamingAssets` folder for another installation. No game files are copied or bundled. Its block rotations and nested transforms have mathematical fixture tests, but exported blueprints have not been loaded in the game. Ordinary curved-hull shapes still lack verified fixtures; the curve primitive has synthetic tests only. No universal FtD compatibility is claimed.

Limits: 32 MiB uploaded files, 128 MiB decompressed NBT, 500,000 occupied output cells, 2,048 cells per axis, and an 8,000,000-cell bounding volume. A large 4× conversion may exceed these limits. Previews use flat colors, simplified geometry and instancing, rather than game textures. Cross-game round trips are lossy.

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

Optional browser fixtures use `FROMTHECRAFT_SHIP` for a 1.21.1 `.nbt`, `FROMTHECRAFT_FTD_SHIP` for a stock FtD blueprint and `FROMTHECRAFT_HARD_SHIP` for the owner's Claymore blueprint. All 13 files in the supplied Constructables folder passed both Minecraft exports and independent format checks. Third-party ships are not distributed. Build on Windows; PyInstaller does not cross-compile a Windows executable from Linux.

The CLI uses the same engine and refuses to overwrite an existing destination:

```powershell
.venv\Scripts\python -m fromthecraft convert input.blueprint output.nbt --scale 0.5 --palette balanced
.venv\Scripts\python -m fromthecraft convert input.litematic output.blueprint
node scripts\verify_nbt.cjs output.nbt
node scripts\verify_litematic.cjs output.litematic # compares with sibling output.nbt
```

Normal conversion stays local, with no accounts, analytics, CDN assets or external network calls. Read [development evidence](docs/implementation.md) for fixture provenance, measured checks and unverified game acceptance.

## License and acknowledgments

GPL-3.0-or-later; see [COPYING](COPYING). Litemapy 0.11.0b0 is GPL-3.0 and supplies the Litematic adapter. nbtlib 2.0.4 handles binary NBT. Three.js 0.180.0 provides instancing and orbit controls; React supplies the interface. The [FtD-Blueprint-Bot catalog](https://github.com/FRUCHTBA3R/FtD-Blueprint-Bot/tree/a7c162bec615f277fa1eeecdbaf9d4680d5ac2e4) is reused under MIT with its notice. The Minecraft registry comes from [minecraft-data 3.100.0](https://github.com/PrismarineJS/minecraft-data), also MIT. Full dependency notices ship inside the portable folder. No game assets or third-party blueprints are bundled. Nothing has been pushed or published.
