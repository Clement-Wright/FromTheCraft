const fs = require('node:fs');
const assert = require('node:assert/strict');
const nbt = require('../ui/node_modules/prismarine-nbt');

// Independent facts from Copycats+ 3.0.4 revision 9f808ac and Create 6.0.10.
// This verifier imports no application geometry, block-entity writer or reader.
const bool = ['false', 'true'];
const horizontal = ['north', 'south', 'east', 'west'];
const directions = [...horizontal, 'up', 'down'];
const byteSlots = ['bottom_northwest', 'bottom_southwest', 'top_northwest', 'top_southwest',
  'bottom_northeast', 'bottom_southeast', 'top_northeast', 'top_southeast'];
const panelSlots = ['bottom_right', 'bottom_left', 'top_right', 'top_left'];
const schemas = {
  'copycats:copycat_stairs': {be: 'copycats:copycat', rules: {facing: horizontal, half: ['top','bottom'], shape: ['straight','inner_left','inner_right','outer_left','outer_right'], waterlogged: bool}},
  'copycats:copycat_slab': {slots: ['bottom','top'], rules: {axis: ['x','y','z'], type: ['top','bottom','double'], waterlogged: bool}},
  'copycats:copycat_layer': {be: 'copycats:copycat', rules: {facing: directions, layers: ['1','2','3','4','5','6','7','8'], waterlogged: bool}},
  'copycats:copycat_half_panel': {be: 'copycats:copycat', rules: {facing: directions, offset: horizontal, waterlogged: bool}},
  'copycats:copycat_byte': {slots: byteSlots, rules: {...Object.fromEntries(byteSlots.map(slot => [slot,bool])), waterlogged: bool}},
  'copycats:copycat_byte_panel': {slots: panelSlots, rules: {...Object.fromEntries(panelSlots.map(slot => [slot,bool])), facing: directions, waterlogged: bool}},
  'create:copycat_panel': {be: 'create:copycat', rules: {facing: directions, waterlogged: bool}},
  'create:copycat_step': {be: 'create:copycat', rules: {facing: horizontal, half: ['top','bottom'], waterlogged: bool}},
};

const levels = Array.from({length:9}, (_,i) => String(i));
for (const family of ['half_layer','vertical_half_layer','stacked_half_layer']) {
  schemas['copycats:copycat_' + family] = {slots:['negative_layers','positive_layers'],
    rules:{negative_layers:levels,positive_layers:levels,waterlogged:bool,
      ...(family==='half_layer' ? {axis:['x','z'],half:['top','bottom']} : {facing:horizontal})}};
}
schemas['copycats:copycat_board']={slots:directions,rules:{...Object.fromEntries(directions.map(d=>[d,bool])),waterlogged:bool}};
schemas['copycats:copycat_beam']={be:'copycats:copycat',rules:{axis:['x','y','z'],waterlogged:bool}};
schemas['copycats:copycat_vertical_step']={be:'copycats:copycat',rules:{facing:horizontal,waterlogged:bool}};
for (const family of ['slice','vertical_slice','corner_slice'])
  schemas['copycats:copycat_'+family]={be:'copycats:copycat',rules:{facing:horizontal,layers:levels.slice(1),waterlogged:bool,
    ...(family==='vertical_slice'?{}:{half:['top','bottom']})}};

function verifyTypes(tag) {
  if (tag.type === 'compound') {
    for (const [name, child] of Object.entries(tag.value)) {
      if (name === 'count') assert.equal(child.type, 'int', 'item count must be TAG_Int');
      if (name === 'EnableCT' || name === 'enableCT') {
        assert.equal(child.type, 'byte', 'CT flag must be TAG_Byte');
        assert([0,1].includes(child.value));
      }
      if (name === 'Material' || name === 'material' || name === 'material_data') assert.equal(child.type, 'compound');
      if (name === 'Item' || name === 'consumedItem') assert.equal(child.type, 'compound');
      if (name === 'Name' || name === 'id') assert.equal(child.type, 'string');
      if (name === 'Properties') {
        assert.equal(child.type, 'compound');
        assert(Object.values(child.value).every(value => value.type === 'string'));
      }
      assert.notEqual(name, 'Count', 'legacy Count is not the 1.21.1 ItemStack format');
      verifyTypes(child);
    }
  } else if (tag.type === 'list' && tag.value.type === 'compound') {
    for (const value of tag.value.value) verifyTypes({type: 'compound', value});
  }
}

function materialName(material) {
  assert(material && typeof material.Name === 'string', 'material needs state Name');
  assert(/^[a-z0-9_.-]+:[a-z0-9_./-]+$/.test(material.Name), 'invalid material identifier');
  assert(material.Name === 'create:copycat_base' ||
    !material.Name.startsWith('copycats:') && !material.Name.startsWith('create:copycat_'), 'nested copycat material');
  assert(Object.values(material.Properties ?? {}).every(value => typeof value === 'string'));
  return material.Name;
}

function paidItem(item, material) {
  assert(item && typeof item === 'object' && !Array.isArray(item), 'item compound missing');
  if (!Object.keys(item).length) return null;
  assert.equal(item.id, material);
  assert.equal(item.count, 1, 'canonical item count must be one');
  assert.deepEqual(Object.keys(item).sort(), ['count','id']);
  return material;
}

function verifyCopycat(state, entity) {
  const schema = schemas[state.Name];
  if (!schema) return false;
  const properties = state.Properties ?? {};
  for (const [key,value] of Object.entries(properties)) {
    assert(schema.rules[key]?.includes(value), `${state.Name}: invalid ${key}=${value}`);
  }
  assert(entity, `${state.Name}: applied-material block entity missing`);
  if (schema.be) {
    assert.equal(entity.id, schema.be);
    const material = materialName(entity.Material);
    assert.equal(paidItem(entity.Item, material), material);
    assert([0,1].includes(entity.EnableCT));
    assert(!entity.material_data);
  } else {
    assert.equal(entity.id, 'copycats:multistate_copycat');
    assert.deepEqual(Object.keys(entity.material_data).sort(), schema.slots.slice().sort());
    const active = state.Name.endsWith('_slab')
      ? (properties.type === 'double' ? ['bottom','top'] : [properties.type ?? 'bottom'])
      : schema.slots.filter(slot => slot.endsWith("_layers") ? Number(properties[slot] ?? 0) > 0 : properties[slot] === 'true');
    const required = new Set(), paid = new Set();
    for (const slot of schema.slots) {
      const data = entity.material_data[slot];
      assert.deepEqual(Object.keys(data).sort(), ['consumedItem','enableCT','material']);
      const material = materialName(data.material);
      const item = paidItem(data.consumedItem, material);
      assert([0,1].includes(data.enableCT));
      if (active.includes(slot) && material !== 'create:copycat_base') required.add(material);
      else {
        assert.equal(material, 'create:copycat_base', 'inactive slot must retain base material');
        assert.equal(item, null, 'inactive slot must have an empty item');
      }
      if (item) {
        assert(!paid.has(item), 'same material item was consumed more than once');
        paid.add(item);
      }
    }
    assert.deepEqual([...paid].sort(), [...required].sort(), 'distinct applied items must each be consumed once');
  }
  return true;
}

async function main() {
  for (const file of process.argv.slice(2)) {
    const { parsed } = await nbt.parse(fs.readFileSync(file));
    verifyTypes(parsed);
    const root = nbt.simplify(parsed);
    assert.equal(root.DataVersion, 3955);
    assert.equal(root.size.length, 3);
    assert(root.size.every(n => Number.isInteger(n) && n > 0));
    assert(Array.isArray(root.palette) && root.palette.length > 0);
    const occupied = new Set();
    const containers = {};
    for (const block of root.blocks) {
      assert(block.pos.every((n,i) => Number.isInteger(n) && n >= 0 && n < root.size[i]));
      assert(block.state >= 0 && block.state < root.palette.length);
      assert(!occupied.has(block.pos.join(',')));
      occupied.add(block.pos.join(','));
      const state = root.palette[block.state];
      if (verifyCopycat(state, block.nbt)) containers[state.Name] = (containers[state.Name] ?? 0) + 1;
    }
    assert.deepEqual(root.entities, []);
    console.log(`${file}: Java 1.21.1, ${root.size.join('x')}, ${occupied.size} records; independent parse/types/container schemas passed ${JSON.stringify(containers)}`);
  }
}

module.exports = {verifyCopycat, verifyTypes};
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
