import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parseBiomeInventory } from '../lib/biome-inventory.ts';
const hash = raw => createHash('sha256').update(raw).digest('hex');

test('altered memberships fail even when embedded source hashes and counts are retained', async()=>{
 const original=JSON.stringify({schema_version:1,inputs:{source_sha256:'a'.repeat(64)},biomes:[{id:'meadows',name:'Meadows',asset_ids:['first'],texture_count:1}]});
 const changed=original.replace('first','other');
 await assert.rejects(parseBiomeInventory(changed,hash(original)),/content differs/);
 assert.deepEqual(await parseBiomeInventory(original,hash(original)),JSON.parse(original));
});
test('published membership bytes match the application descriptor',async()=>{
 const raw=readFileSync(new URL('../public/data/biomes.json',import.meta.url),'utf8');
 const summary=JSON.parse(readFileSync(new URL('../data/biome-summary.json',import.meta.url),'utf8'));
 const actual=await parseBiomeInventory(raw,summary.data_sha256);
 assert.equal(actual.inputs.source_sha256,summary.inputs.source_sha256);
});
