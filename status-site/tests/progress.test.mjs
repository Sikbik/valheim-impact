import assert from 'node:assert/strict';
import test from 'node:test';
import { overallProgress, biomeProgress } from '../lib/progress.ts';

test('overall progress excludes inventory and never credits missing stages', () => {
  const counts = { texture: {inventoried: 10, authored: 2, uv_reviewed: 1, native_validated: 1, game_fixture_validated: 0, approved: 0} };
  assert.deepEqual(overallProgress(counts), {completed: 4, possible: 50, percent: 8});
  assert.deepEqual(overallProgress({}), {completed: 0, possible: 0, percent: 0});
});

test('biome scope uses exact identities and does not promote pilot work to approval', () => {
  const asset = {id:'CAB-a:1', stages:{inventoried:true,authored:true,uv_reviewed:false,native_validated:false,game_fixture_validated:false,approved:false}};
  assert.deepEqual(biomeProgress({asset_ids:['CAB-a:1','CAB-a:1']}, [asset, {...asset,id:'CAB-a:2'}]), {scoped:1,authored:1,approved:0,completed:1,possible:5});
  assert.equal(biomeProgress({asset_ids:[]},[asset]).possible,0);
});
