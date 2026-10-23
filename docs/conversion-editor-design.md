# Conversion editor, textures and decorative geometry

Status: proposed design for review. No application changes implemented yet.
Branch: `feature/conversion-editor-decorations`, based on `1eddcca` (0.4.1).

## Outcome

Choose which original source records contribute to a conversion, inspect the
interior without changing export contents, and preserve supported decorative
geometry when requested. The original file remains byte-for-byte unchanged.
Minecraft textures must be usable in the converted viewer independently of FtD
texture availability. Changes stay off main until the user requests integration.

## Approach

Keep the imported document and its structural scene immutable. Apply a separate,
versioned conversion edit layer to a derived scene before voxelization, target
material selection and hollowing. Viewer visibility and clipping operate on the
display only. Saving a native edited blueprint is outside this design; the
existing reconstructed blueprint export remains a conversion output.

Patching native arrays directly would mix editor actions with unrelated gameplay
metadata and attachments. Editing sampled target cells would lose the identity of
beams and overlapping records. A source-record edit layer avoids both problems.

## Source identities

Add immutable source metadata alongside each Part: record ID, canonical type key,
record kind, construct/region path, parent path and optional host record ID.
Derive IDs from the original record location, not names, colors or world position.
Scope IDs with the SHA-256 hash of the exact imported bytes. Reimporting those bytes
must produce the same IDs; editing a source record externally may change its ID.

FtD block IDs use construct traversal paths and original block-array indices;
type keys use FtD GUIDs. Minecraft NBT IDs use original block-record indices;
Litematic IDs use region names and local cell coordinates. Decomposed boxes from
one Minecraft block retain one source ID. Overlapping records retain separate IDs.
Decorations receive distinct IDs and explicit verified host relationships.

The preview carries per-instance source IDs separately from shared block identity
metadata. The picker returns an ID and type key in addition to its existing hover
information. Source material rows group canonical types, even when names coincide.

## Editor behavior

Click selects one source record. Ctrl-click toggles additional records; clicking
empty space clears selection. A small list disambiguates overlapping hits rather
than making the front record the only selectable one. Selecting a materials row
selects every original record of that canonical type.

Actions: select all of this type, exclude selected, exclude all of this type,
replace mapping, restore selected, hide selected and show hidden. Exclusion is
visible in the source viewer as a distinct state with an optional excluded-record
display toggle. Hiding is reversible independently of exclusion. Undo and redo
cover edits and visibility changes from the first editor increment.

Host exclusion offers three explicit choices: host only, host and attachments,
or cancel. Attachments selected independently can be excluded independently. A
missing or unresolved host relationship is reported rather than guessed.

Every edit, undo and redo increments a source-edit revision, cancels active
conversion, clears cached result bytes and invalidates Export. Conversion captures
the source hash, edit revision and settings. Completion from an older revision
cannot publish its result. Visibility, clipping and texture changes do not alter
conversion revision or serialized bytes.

Mapping overrides select a verified target block state and apply to selected
records or a canonical type. Validate version, enabled mods, properties and
Copycat materials server-side. Mapping changes retain geometry fitting unless the
user explicitly chooses a full-block replacement. Restore removes overrides and
exclusions without touching the imported scene.

## Minecraft textures and block browser

Keep texture assets local and subject to existing archive/image budgets. Discover
version manifests that reference Minecraft 1.21.1, including inherited modpack
versions, instead of assuming a single JAR filename. Offer local client/mod JAR
and resource-pack ZIP loading as a fallback. Show separate source and target
availability and unresolved target texture counts, with a direct load action.
Do not download or redistribute game textures automatically.

The block browser searches the verified vanilla and selected-mod palette. Show a
textured 3D thumbnail when local assets resolve, a labeled flat-color fallback
otherwise, namespace, allowed properties and the selected orientation. Assignment
uses the same validated mapping representation as editor overrides.

## Decorative geometry: staged implementation

First establish the actual on-disk schema from controlled fixtures and installed
game evidence. Search Decorations/DEC and block payload representations; do not
treat a field name or decoded-looking payload as a verified attachment contract.
Required fixtures: one decoration, rotated, nonuniformly scaled, and attached in a
rotated subconstruct. Record game version and independently checked transforms.
Use original fixtures or local read-only game data; do not distribute user craft
or game meshes and textures.

Stage A resolves supported referenced static meshes using the existing pinned
UnityPy dependency where possible. Compose host, construct and decoration local
transforms once, preserving scale and paint/material. Include a separate viewer
mimics/decorations toggle. Unresolved geometry gets a specific notice and remains
selectable through its source record. Complex renderers remain explicitly unsupported.

Stage B adds Structure only (default), Structure + decorations and
Appearance-focused conversion modes. The latter prioritizes verified visible
decorative representations and warns when physical occupancy changes. Host
suppression follows verified representation semantics rather than assuming every
decoration replaces its host. Selection and exclusions operate before mode
composition. Preview toggles never choose conversion modes implicitly.

Stage C adds a mesh path only for records not represented by known primitives.
Classify watertight solids separately from open surfaces; voxelize closed solids
with bounded work and use an explicit thickness setting for open surfaces.
Report affected records and details below the target resolution. Prefer matching
native target shapes, then enabled Copycats, then stepped blocks. Preserve current
fast paths and cancellation/size limits; never fill an open railing as a solid.

For reverse conversion, expand verified native FtD material and shape selection
first. Decorative FtD output follows only after its writer schema and attachment
semantics are established, and remains opt-in. Do not generate guessed payloads.

## Inspection and project persistence

Add per-view clipping planes and axis layer ranges, with linked controls optional.
Clipping affects rendering and picking only; reset restores all geometry. Hidden
or clipped records remain in the editor list and in conversion unless excluded.

Saved project JSON contains a schema version, source name/hash, edit commands and
history cursor, mapping overrides, conversion settings and view state. The user
reselects the source file when reopening; require a matching hash before replaying
record edits. Do not silently apply edits to a different craft. Include bounded
schema validation and reject unknown commands. Presets store reusable conversion
settings and type mappings, without source-specific record IDs. Assets are
referenced, not embedded. Neither operation overwrites the original source.

## Verification and increments

1. Local Minecraft texture discovery/loading with independent target-face checks.
2. Stable identities, server edit history and pre-conversion filtering/mappings.
3. Click/list/overlap selection, exclusions, visibility, undo/redo and stale-export checks.
4. Clipping/layers, project replay/hash checks, presets and textured palette browser.
5. Decoration schema evidence and transformed preview fixtures.
6. Decoration conversion modes, bounded mesh sampling and resolution notices.
7. Better reverse native material/shape selection; verified optional decorative output.

Each increment needs regression tests and a working local interface, inspected
diffs and local commits. Use real read-only craft fixtures alongside small original
fixtures. Independently parse exports and compare exported bytes with the displayed
result. Check source hashes after all editor actions, decomposition and overlap
selection, undo/redo invalidation, concurrent edits during conversion, hidden deck
preservation, project mismatches, missing textures, nested decoration transforms,
open surfaces and cancellation. In-game acceptance must be reported separately.

No push, release or merge of this feature branch is planned until requested.
