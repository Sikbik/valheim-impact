import assert from 'node:assert/strict';
import test from 'node:test';
import {previewUrl,validSprite} from '../lib/comparisons.ts';

test('comparison images stay in the public preview directory',()=>{
 assert.equal(previewUrl('before-001.webp'),'./comparisons/before-001.webp');
 for(const bad of ['../original.png','https://example.com/a.webp','a/b.webp','before-001.webp?x','a\\b.webp']) assert.equal(previewUrl(bad),null);
});
test('sprites must fit within the hash-indexed sheet',()=>{
 const sheet={file:'before-001.webp',width:1536,height:1536,sha256:'x'};
 const index={schema_version:1,tile_size:192,columns:8,sheets:[sheet],assets:{}};
 const sprite={sheet:sheet.file,x:1344,y:1344,width:192,height:192,kind:'texture'};
 assert.equal(validSprite(sprite,index),sheet);
 for(const change of [{x:1345},{y:-1},{width:0},{height:1.5},{sheet:'missing.webp'}]) assert.equal(validSprite({...sprite,...change},index),null);
});
