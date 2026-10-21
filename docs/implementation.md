# FromTheCraft implementation and evidence

The owner-supplied `FromTheCraft_Codex_Handoff.md` is the implementation specification. Work proceeds in its A–F order. Decisions here resolve details; they do not expand conversion scope.

- Python 3.12, NumPy, nbtlib 2.0.4, Litemapy 0.11.0b0, FastAPI; React/TypeScript and instanced Three.js. One engine serves browser and CLI.
- Proposed project license: GPL-3.0-or-later to accommodate Litemapy's GPL-3.0 dependency. No publication is authorized. Preserve the MIT FtD catalog notice and other dependency notices in the portable build.
- Shared coordinates: X right/east, Y up, Z forward/south. FtD block anchors are cell centers; MC integer positions denote cell corners. Apply a single +0.5 center translation at the FtD boundary. Ignore root world placement; compose child local transforms continuously. Normalize only serialized output and retain its offset for comparison.
- First occupied contribution wins overlaps; air never erases an occupied region. Conservative multi-sample voxelization preserves thin pieces. No flood fill.
- Output target is Minecraft Java 1.21.1, data version 3955. Refuse other input versions with a useful error. Catalog coverage means an explicit family policy, not exact visual support.
- Converted preview always reparses cached serialized bytes. Option/source changes invalidate export and superseded work is discarded.

## Working increments

1. FtD reader, full beam footprint, Create NBT, asymmetric fixture and independent Litemapy read.
2. Both MC adapters and static FtD output; signed multi-region fixtures and independent checks.
3. Primitive geometry, nested continuous transforms, states, palettes and coverage policies.
4. Upload/convert/cancel/export service and linked paired structural previews; browser checks.
5. Windows portable packaging, path-with-spaces launch, representative ship measurements, full review.

For each increment: write meaningful regression tests first, observe failure, implement, run relevant checks, inspect the diff, then commit locally.

## Evidence ledger

- Empty workspace inspected; no pre-existing work or repository instructions on disk.
- All six requested skills installed and read. Superdesign CLI 0.14.0 has no authenticated account; canvas work is unavailable without account access. Apply the brief and Make Interfaces Feel Better directly.
- FtD catalog source: FRUCHTBA3R/FtD-Blueprint-Bot revision `a7c162bec615f277fa1eeecdbaf9d4680d5ac2e4`, MIT. Its renderer rounds transforms and is unsuitable for continuous rotations.
- Read the public CAD_to_FromTheDepths single-block schema (game version 3.8.5.11) as a format reference only. No license is declared, so do not redistribute its fixture, author details, or code. Independently authored fixtures will be labeled as such.
- Local Minecraft ship fixtures found in Downloads; use read-only and keep them out of Git. No local FtD install or owner blueprint located in checked Steam/Documents folders. Game acceptance remains a separate check.
