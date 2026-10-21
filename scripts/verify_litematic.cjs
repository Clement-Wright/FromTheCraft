const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const nbt = require('../ui/node_modules/prismarine-nbt');

function stateKey(state) {
  return state.Name + JSON.stringify(Object.entries(state.Properties ?? {}).sort());
}

async function read(file) {
  return nbt.simplify((await nbt.parse(fs.readFileSync(file))).parsed);
}

(async () => {
  for (const file of process.argv.slice(2)) {
    const root = await read(file);
    assert.equal(root.MinecraftDataVersion, 3955);
    const expectedFile = path.join(path.dirname(file), path.basename(file, '.litematic') + '.nbt');
    const expected = await read(expectedFile);
    const states = new Map(expected.blocks.map(block => [block.pos.join(','), stateKey(expected.palette[block.state])]));
    let occupied = 0;
    for (const region of Object.values(root.Regions)) {
      const { x:w, y:h, z:l } = region.Size;
      assert(w > 0 && h > 0 && l > 0);
      const palette = region.BlockStatePalette.map(stateKey);
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
        occupied++;
      }
    }
    assert.equal(occupied, states.size);
    console.log(`${path.basename(file)}: ${occupied} occupied states match NBT exactly; independent bit unpack passed`);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
