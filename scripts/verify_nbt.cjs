const fs = require('node:fs');
const assert = require('node:assert/strict');
const nbt = require('../ui/node_modules/prismarine-nbt');

(async () => {
  for (const file of process.argv.slice(2)) {
    const { parsed } = await nbt.parse(fs.readFileSync(file));
    const root = nbt.simplify(parsed);
    assert.equal(root.DataVersion, 3955);
    assert.equal(root.size.length, 3);
    assert(root.size.every(n => Number.isInteger(n) && n > 0));
    assert(Array.isArray(root.palette) && root.palette.length > 0);
    const occupied = new Set();
    for (const block of root.blocks) {
      assert(block.pos.every((n,i) => Number.isInteger(n) && n >= 0 && n < root.size[i]));
      assert(block.state >= 0 && block.state < root.palette.length);
      assert(!occupied.has(block.pos.join(',')));
      occupied.add(block.pos.join(','));
    }
    assert.deepEqual(root.entities, []);
    console.log(`${file}: Java 1.21.1, ${root.size.join('x')}, ${occupied.size} occupied records; independent prismarine-nbt parse passed`);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
