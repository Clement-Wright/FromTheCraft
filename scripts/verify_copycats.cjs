// Independent parser verifies original expected block states, BE fields and NBT types.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const nbt = require('../ui/node_modules/prismarine-nbt');
const recipe = JSON.parse(fs.readFileSync(require('node:path').join(__dirname, '../tests/fixtures/copycats-materials.json'), 'utf8'));

function expectedNumbers(value) {
  if (typeof value === 'boolean') return Number(value);
  if (Array.isArray(value)) return value.map(expectedNumbers);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, expectedNumbers(v)]));
  return value;
}

function verifyTypes(tag) {
  if (tag.type === 'compound') {
    for (const [name, child] of Object.entries(tag.value)) {
      if (name === 'count') assert.equal(child.type, 'int', 'ItemStack count must use TAG_Int');
      if (name === 'EnableCT' || name === 'enableCT') assert.equal(child.type, 'byte', 'CT toggle must use TAG_Byte');
      assert.notEqual(name, 'Count', 'Legacy Count tag is not the 1.21.1 format');
      verifyTypes(child);
    }
  }
  if (tag.type === 'list' && tag.value.type === 'compound') {
    for (const child of tag.value.value) verifyTypes({type: 'compound', value: child});
  }
}

function appearance(data) {
  const clean = {...data};
  delete clean.x; delete clean.y; delete clean.z;
  return clean;
}

(async () => {
  const paths = process.argv.slice(2);
  if (!paths.length) paths.push('tests/fixtures/copycats-materials.nbt', 'tests/fixtures/copycats-materials.litematic');
  for (const file of paths) {
    const raw = (await nbt.parse(fs.readFileSync(file))).parsed;
    verifyTypes(raw);
    const root = nbt.simplify(raw);
    if (root.blocks) {
      assert.equal(root.DataVersion, 3955);
      assert.equal(root.blocks.length, recipe.blocks.length);
      for (const expected of recipe.blocks) {
        const block = root.blocks.find(block => String(block.pos) === String(expected.pos));
        assert(block);
        assert.deepEqual(root.palette[block.state], expected.state);
        assert.deepEqual(appearance(block.nbt), expectedNumbers(expected.nbt));
      }
    } else {
      assert.equal(root.MinecraftDataVersion, 3955);
      const regions = Object.values(root.Regions);
      assert.equal(regions.length, 1);
      const region = regions[0];
      assert.deepEqual(region.Position, {x: 0, y: 0, z: 0});
      assert.deepEqual(region.Size, {x: 4, y: 1, z: 1});
      assert.equal(region.TileEntities.length, recipe.blocks.length);
      const bits = BigInt(Math.max(2, Math.ceil(Math.log2(region.BlockStatePalette.length))));
      const mask = (1n << bits) - 1n;
      const longs = region.BlockStates.map(value => BigInt.asUintN(64, BigInt(value)));
      for (const expected of recipe.blocks) {
        const [x, y, z] = expected.pos;
        const offset = BigInt((y * 4 + z * 4 + x)) * bits;
        const word = Number(offset / 64n), shift = offset % 64n;
        let packed = longs[word] >> shift;
        if (shift + bits > 64n) packed |= longs[word + 1] << (64n - shift);
        assert.deepEqual(region.BlockStatePalette[Number(packed & mask)], expected.state);
        const tile = region.TileEntities.find(tile => tile.x === x && tile.y === y && tile.z === z);
        assert(tile);
        assert.deepEqual(appearance(tile), expectedNumbers(expected.nbt));
      }
    }
    process.stdout.write(`${file}: independent NBT parser verified 4 expected states and full BE payloads, count Int and CT Byte\n`);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
