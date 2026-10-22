# Fixtures

`asymmetric.blueprint` is independently authored for this project. Its four blocks exercise marked axes, a 4 m metal beam, red paint, wood, and glass. It follows the inspected FtD 3.8.5.11 schema; it has not been saved or loaded in the game.

Adapter tests also create binary structures and signed multi-region Litematics with Litemapy 0.11.0b0. These provide independent input writers for our readers.

Real ship files in the owner's Downloads folder are read-only local test inputs. They are not redistributed here.
# Material fixtures

`painted-slopes.blueprint` was authored for FromTheCraft. It contains six painted metal/glass slopes with catalog IDs, for checking vanilla full-block fallback and opt-in Copycats+ materials.

`copycats-materials.json`, `.nbt` and `.litematic` are an original four-block fixture derived from the documented Copycats+ 3.0.4 Minecraft 1.21.1 serialization schema. They cover red stairs, glass stairs, blue slabs and stained-glass slabs. They were not captured in Minecraft and do not establish in-game compatibility. No mod assets are included. Run `node scripts/verify_copycats.cjs` from the repository root for an independent parser and tag-type check.

`copycats-shapes.json` records original numeric shape observations, defaults and source links from pinned Copycats+ and Create. It contains no mod meshes or images. The independent geometry checker uses it to interpret serialized target boxes.
