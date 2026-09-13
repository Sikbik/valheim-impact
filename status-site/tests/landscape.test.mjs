import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {validateLandscape} from '../scripts/validate-landscape.mjs';

const root=new URL('../public/landscape/',import.meta.url);
const source=JSON.parse(readFileSync(new URL('captures.json',root),'utf8'));
const readImage=relative=>readFileSync(new URL(relative,root));

test('reviewed gallery has ten bounded comparisons and exact exported image hashes',()=>{
  assert.deepEqual(validateLandscape(source,readImage),{views:10,pairs:20,imageReferences:40,uniqueImages:32});
});

test('gallery rejects unsafe paths and extra private fields before reading images',()=>{
  for(const mutate of [
    d=>{d.views[0].pairs[0].before='../original.png';},
    d=>{d.views[0].pairs[0].before='https://example.test/original.webp';},
    d=>{d.views[0].pairs[0].sourcePath='local/captures/original.png';},
    d=>{d.views[0].sourceCoordinates=[1,2,3];},
    d=>{d.views[0].description='See local/private/source.png';},
    d=>{d.views[0].label='C:/private/source.png';},
    d=>{d.views[0].description={private:'unreviewed'};},
  ]) {
    const data=structuredClone(source); mutate(data);
    let reads=0;
    assert.throws(()=>validateLandscape(data,relative=>{reads++;return readImage(relative);}));
    assert.equal(reads,0,'Invalid metadata must fail before file reads');
  }
});

test('gallery rejects malformed coverage, claims and controlled filter labels',()=>{
  for(const mutate of [
    d=>{d.schemaVersion=true;}, d=>{d.verified='true';},
    d=>{d.rights.originalGameContentPresent=false;},
    d=>{d.rights.mixedRenderedComparisonsExcludedFromArtworkLicense=false;},
    d=>{d.views.pop();}, d=>{d.views[1].id=d.views[0].id;},
    d=>{d.views[0].pairs[1]=structuredClone(d.views[0].pairs[0]);},
    d=>{d.views[0].pairs[0].width=1920.5;},
    d=>{d.views[0].pairs[0].clippedHdrPixels.after=1920*1080+1;},
    d=>{d.views[0].pairs[0].afterBytes=true;},
    d=>{d.views[0].conditions.finalMaterialApproved=true;},
    d=>{d.views[0].conditions.liveWorldValidated=true;},
    d=>{d.views.find(v=>v.id==='filter-study').conditions.normalFilter='Bilinear';},
    d=>{d.views.find(v=>v.id==='ground-revision').beforeLabel='Original';},
  ]) {
    const data=structuredClone(source); mutate(data);
    assert.throws(()=>validateLandscape(data,readImage));
  }
});

test('gallery rejects changed image bytes and inconsistent repeated-image metadata',()=>{
  assert.throws(()=>validateLandscape(source,relative=>{
    const bytes=Buffer.from(readImage(relative)); bytes[bytes.length-1]^=1; return bytes;
  }),/hash/i);
  const data=structuredClone(source);
  data.views[0].pairs[0].beforeSha256='0'.repeat(64);
  assert.throws(()=>validateLandscape(data,readImage),/hash|inconsistent/i);
});

test('rehashing an image cannot hide metadata chunks or different image dimensions',()=>{
  const target=source.views[0].pairs[0].before;
  for(const change of ['metadata','dimensions']) {
    let bytes=Buffer.from(readImage(target));
    if(change==='metadata') {
      bytes=Buffer.concat([bytes,Buffer.from('EXIF\x04\x00\x00\x00test','binary')]);
      bytes.writeUInt32LE(bytes.length-8,4);
    } else bytes.writeUInt16LE(1919,26);
    const data=structuredClone(source), hash=createHash('sha256').update(bytes).digest('hex');
    for(const view of data.views) for(const pair of view.pairs) for(const side of ['before','after']) {
      if(pair[side]===target) {pair[side+'Sha256']=hash;pair[side+'Bytes']=bytes.length;}
    }
    assert.throws(()=>validateLandscape(data,relative=>relative===target?bytes:readImage(relative)),
      change==='metadata'?/metadata-free/:/dimensions/);
  }
});
