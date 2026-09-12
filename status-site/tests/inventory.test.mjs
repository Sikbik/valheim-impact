import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {filterAssets,sortAssets,pageSlice,stages} from '../lib/inventory.ts';
const data=JSON.parse(readFileSync(new URL('../public/data/inventory.json',import.meta.url)));
const defaults={kind:'texture',query:'',category:'all',stage:'all'};
const manifest=JSON.parse(readFileSync(new URL('../../assets/status/manifest.json',import.meta.url)));
const catalog=JSON.parse(readFileSync(new URL('../../assets/status/catalog.json',import.meta.url)));
test('all exact IDs survive, with no completion by name or automatic stage promotion',()=>{
 assert.equal(data.assets.length,catalog.assets.length);
 assert.deepEqual(data.assets.map(a=>a.id).sort(),catalog.assets.map(a=>a.id).sort());
 assert.equal(new Set(data.assets.map(a=>a.id)).size,data.assets.length);
 for(const kind of ['texture','mesh']) {
  for(const stage of stages) assert.equal(data.assets.filter(a=>a.kind===kind&&a.stages[stage]).length,data.summary.stage_counts[kind][stage]);
 }
 for(const stage of stages.slice(1)) {
  const expected=new Set(manifest.evidence.flatMap(e=>e.targets.filter(t=>t.stages.includes(stage)).map(t=>t.asset_id)));
  assert.deepEqual(new Set(data.assets.filter(a=>a.stages[stage]).map(a=>a.id)),expected);
 }
});
test('search by precise ID returns only that asset, never same-name siblings',()=>{
 const target=data.assets.find(a=>a.kind==='texture'&&a.stages.authored);
 assert.equal(filterAssets(data.assets,{...defaults,query:target.id})[0].id,target.id);
 assert.equal(filterAssets(data.assets,{...defaults,query:target.id}).length,1);
 assert.equal(filterAssets(data.assets,{...defaults,stage:'game_fixture_validated'}).length,data.summary.stage_counts.texture.game_fixture_validated);
 assert.equal(filterAssets(data.assets,{...defaults,kind:'mesh',stage:'game_fixture_validated'}).length,data.summary.stage_counts.mesh.game_fixture_validated);
 assert.equal(filterAssets(data.assets,{...defaults,stage:'approved'}).length,data.summary.stage_counts.texture.approved);
});
test('category, case-insensitive search and kind compose; missing results stay empty',()=>{
 const a=data.assets.find(a=>a.kind==='texture'&&a.container_paths.length);
 const found=filterAssets(data.assets,{...defaults,category:a.category,query:'  '+a.container_paths[0].toUpperCase()+'  '});
 assert.ok(found.some(item=>item.id===a.id));
 assert.ok(found.every(item=>item.kind==='texture'&&item.category===a.category));
 assert.equal(filterAssets(data.assets,{...defaults,query:'not-an-asset-1234'}).length,0);
});
test('bounded pagination covers every filtered result exactly once and clamps stale pages',()=>{
 const rows=filterAssets(sortAssets(data.assets),defaults);
 const seen=[];
 for(let p=0;p<Math.ceil(rows.length/40);p++){const result=pageSlice(rows,p);assert.ok(result.rows.length<=40);seen.push(...result.rows.map(a=>a.id));}
 assert.deepEqual(seen,rows.map(a=>a.id));
 assert.equal(pageSlice(rows,99999).end,rows.length);
 assert.deepEqual(pageSlice([],10),{page:0,pages:1,rows:[],start:0,end:0});
 assert.equal(pageSlice(rows,-5).page,0);
 assert.throws(()=>pageSlice(rows,0,0));
});
test('every completion is traceable to a registered scoped evidence target',()=>{
 const evidence=new Map(data.evidence.map(e=>[e.id,e]));
 for(const asset of data.assets)for(const stage of stages.slice(1))if(asset.stages[stage]){
  assert.ok(asset.evidence[stage]?.length);
  for(const id of asset.evidence[stage])assert.ok(evidence.get(id)?.targets.includes(asset.id));
 }
});
