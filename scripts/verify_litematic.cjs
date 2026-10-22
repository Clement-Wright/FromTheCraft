const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const nbt = require('../ui/node_modules/prismarine-nbt');
const {verifyCopycat, verifyTypes} = require('./verify_nbt.cjs');

function stateKey(state) {
  return state.Name + JSON.stringify(Object.entries(state.Properties ?? {}).sort());
}

async function read(file) {
  const raw = (await nbt.parse(fs.readFileSync(file))).parsed;
  verifyTypes(raw);
  return nbt.simplify(raw);
}

(async () => {
  for (const file of process.argv.slice(2)) {
    const root = await read(file);
    assert.equal(root.MinecraftDataVersion, 3955);
    const expectedFile = path.join(path.dirname(file), path.basename(file, '.litematic') + '.nbt');
    const expected = await read(expectedFile);
    const states = new Map(expected.blocks.map(block => [block.pos.join(','), stateKey(expected.palette[block.state])]));
    const entities = new Map(expected.blocks.filter(block => block.nbt).map(block => [block.pos.join(','), block.nbt]));
    const appearance = entity => Object.fromEntries(Object.entries(entity).filter(([key]) => !['x','y','z'].includes(key)));
    let occupied = 0;
    let entityCount = 0;
    for (const region of Object.values(root.Regions)) {
      const { x:w, y:h, z:l } = region.Size;
      assert(w > 0 && h > 0 && l > 0);
      const palette = region.BlockStatePalette.map(stateKey);
      const regionStates = new Map();
      const bits = BigInt(Math.max(2, Math.ceil(Math.log2(palette.length))));
      const mask = (1n << bits) - 1n;
      const longs = region.BlockStates.map(value => BigInt.asUintN(64, BigInt(value)));
      for (let i = 0; i < w*h*l; i++) {
        const bit = BigInt(i) * bits, word = Number(bit / 64n), shift = bit % 64n;
        let packed = longs[word] >> shift;
        if (shift + bits > 64n) packed |= longs[word+1] << (64n-shift);
        const index = Number(packed & mask);
        assert(index < palette.length);
        if (palette[index].startsWith('minecraft:air[')) continue;
        const x = i % w, z = Math.floor(i/w) % l, y = Math.floor(i/(w*l));
        const key = [x+region.Position.x,y+region.Position.y,z+region.Position.z].join(',');
        assert.equal(palette[index], states.get(key), `${file}: cell ${key}`);
        regionStates.set(key, region.BlockStatePalette[index]);
        occupied++;
      }
      for (const entity of region.TileEntities) {
        const key = [entity.x+region.Position.x,entity.y+region.Position.y,entity.z+region.Position.z].join(',');
        assert(entities.has(key), `${file}: unexpected block entity at ${key}`);
        assert.deepEqual(appearance(entity), appearance(entities.get(key)), `${file}: block entity ${key}`);
        verifyCopycat(regionStates.get(key), entity);
        entityCount++;
      }
    }
    assert.equal(occupied, states.size);
    assert.equal(entityCount, entities.size);
    console.log(`${path.basename(file)}: ${occupied} occupied states and ${entityCount} block entities match NBT exactly; independent bit unpack passed`);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
