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

test('biome filter uses exact scope IDs and includes shared assets without duplicates',()=>{
 const base=data.assets.find(a=>a.kind==='texture');
 const other={...base,id:'different:1',name:base.name};
 const mappings=[{id:'meadows',name:'Meadows',asset_ids:[base.id]}, {id:'black-forest',name:'Black Forest',asset_ids:[base.id]}];
 const input=[base,other];
 assert.deepEqual(filterAssets(input,{...defaults,biome:'meadows'},mappings).map(a=>a.id),[base.id]);
 assert.deepEqual(filterAssets(input,{...defaults,biome:'black-forest'},mappings).map(a=>a.id),[base.id]);
 assert.deepEqual(filterAssets(input,{...defaults,biome:'unassigned'},mappings).map(a=>a.id),[other.id]);
 assert.equal(filterAssets(input,{...defaults,biome:'swamp'},mappings).length,0);
 assert.equal(filterAssets(input,{...defaults,biome:'all'},mappings).length,2);
});

test('biome sort follows journey order and puts unassigned entries last',()=>{
 const base=data.assets.find(a=>a.kind==='texture');
 const a={...base,id:'a:1',name:'Zebra'};
 const b={...base,id:'b:2',name:'Beech'};
 const c={...base,id:'c:3',name:'Ash'};
 const map=[{id:'meadows',name:'Meadows',asset_ids:[a.id]}, {id:'black-forest',name:'Black Forest',asset_ids:[b.id]}];
 assert.deepEqual(sortAssets([c,b,a],'biome',map).map(a=>a.id),[a.id,b.id,c.id]);
 assert.deepEqual(sortAssets([c,b,a],'name',map).map(a=>a.id),[c.id,b.id,a.id]);
});


test('every biome can browse untouched catalog assets independently of the review pilot',()=>{
 const membership=JSON.parse(readFileSync(new URL('../public/data/biomes.json',import.meta.url)));
 const roadmap=JSON.parse(readFileSync(new URL('../../assets/status/roadmap.json',import.meta.url)));
 assert.equal(membership.inputs.catalog_sha256,data.inputs.catalog_sha256);
 for(const biome of membership.biomes) {
  const textures=filterAssets(data.assets,{...defaults,biome:biome.id},membership.biomes);
  const meshes=filterAssets(data.assets,{...defaults,kind:'mesh',biome:biome.id},membership.biomes);
  assert.equal(textures.length,biome.texture_count);
  assert.equal(meshes.length,biome.mesh_count);
  assert.ok(textures.some(asset=>stages.slice(1).every(stage=>!asset.stages[stage])),biome.name+' needs untouched texture entries');
  assert.ok(meshes.some(asset=>stages.slice(1).every(stage=>!asset.stages[stage])),biome.name+' needs untouched mesh entries');
  if(biome.id==='meadows') assert.ok(biome.asset_ids.length>roadmap.biomes[0].asset_ids.length);
 }
 const assigned=new Set(membership.biomes.flatMap(biome=>biome.asset_ids));
 assert.equal(membership.summary.assigned,assigned.size);
 for(const kind of ['texture','mesh']) {
  const unassigned=filterAssets(data.assets,{...defaults,kind,biome:'unassigned'},membership.biomes);
  assert.ok(unassigned.every(asset=>!assigned.has(asset.id)));
 }
});
