import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

const sha=/^[a-f0-9]{64}$/;
const labels={clearing:['Original','Current candidate'],ground:['Original','Current candidate'],
  tree:['Original','Current candidate'],slope:['Original','Current candidate'],
  'slope-x':['Original','Current candidate'],coast:['Original','Current candidate'],
  'ground-revision':['Ground v2','Ground v3'],'filter-study':['Point filter','Bilinear filter'],
  'bark-tree':['Bark v1','Bark v2'],'bark-clearing':['Bark v1','Bark v2']};
const commonConditions={syntheticScene:true,matchedCameraGeometryAndLighting:true,
  originalNormalControlsRetained:true,dryDaylight:true,castShadows:false,
  liveWorldValidated:false,finalMaterialApproved:false,performanceValidated:false};

function fields(value,required,optional=[]) {
  assert.ok(value && typeof value==='object' && !Array.isArray(value),'Expected a metadata object');
  assert.ok(required.every(k=>Object.hasOwn(value,k)),'Missing gallery field');
  assert.ok(Object.keys(value).every(k=>required.includes(k)||optional.includes(k)),'Unknown gallery field');
}
function text(value) {
  assert.ok(typeof value==='string' && value.length>0 && value.length<=1500,'Expected bounded public prose');
  assert.ok(!/[\x00-\x1f\\<>]|(?:https?:|file:)|(?:^|[\s"'(=:])(?:\/|~\/|[A-Za-z]:\/|(?:local|private|build|reference|src|tools)\/)|\b(?:steamapps|valheim_Data|Bearer|password|api_key)\b|[\w.+-]+@[\w.-]+/i.test(value),'Unsafe gallery prose');
}
function integer(value,max) {
  assert.ok(Number.isSafeInteger(value) && value>=0 && value<=max,'Expected a bounded integer');
}

// This validates the public export contract, not the private native source association.
export function validateLandscape(data,readImage) {
  fields(data,['schemaVersion','verified','verificationScope','defaultWidth','materialSummary','export','rights','views']);
  assert.equal(data.schemaVersion,1); assert.equal(data.verified,true); assert.equal(data.defaultWidth,1920);
  text(data.verificationScope); text(data.materialSummary);
  assert.deepEqual(data.export,{format:'WebP',quality:90,method:6,resized:false,
    nativeSourceResolutions:[[1920,1080],[3840,2160]],metadataRemoved:true});
  assert.deepEqual(data.rights,{originalGameContent:'Valheim © Iron Gate AB',originalGameContentPresent:true,
    authoredContributions:'Valheim Impact original artwork, CC BY 4.0',mixedRenderedComparisonsExcludedFromArtworkLicense:true});
  assert.ok(Array.isArray(data.views) && data.views.length===10,'Expected ten reviewed gallery views');
  const seen=new Set(), images=new Map();
  for(const view of data.views) {
    fields(view,['id','label','description','beforeLabel','afterLabel','conditions','pairs'],['materialSummary']);
    assert.ok(Object.hasOwn(labels,view.id) && !seen.has(view.id),'Unknown or duplicate gallery view'); seen.add(view.id);
    for(const key of ['label','description']) text(view[key]);
    if(Object.hasOwn(view,'materialSummary')) text(view.materialSummary);
    assert.deepEqual([view.beforeLabel,view.afterLabel],labels[view.id],'Comparison labels must preserve the reviewed control');
    const expected={...commonConditions};
    if(!['slope','slope-x','coast'].includes(view.id)) Object.assign(expected,{frozenWind:true,manuallySelectedTreeLods:true});
    if(view.id==='filter-study') Object.assign(expected,{diffuseFilterBefore:'Point',diffuseFilterAfter:'Bilinear',normalFilter:'Point',filterAppliesToAll16DiffuseLayers:true});
    assert.deepEqual(view.conditions,expected,'Gallery conditions must preserve the reviewed scope and limits');
    assert.ok(Array.isArray(view.pairs) && view.pairs.length===2,'Expected two resolution pairs');
    const resolutions=new Set();
    for(const pair of view.pairs) {
      fields(pair,['width','height','clippedHdrPixels','sourceReportSha256',...['before','after'].flatMap(side=>[side,side+'Sha256',side+'Bytes',side+'SourcePngSha256'])]);
      assert.ok((pair.width===1920&&pair.height===1080)||(pair.width===3840&&pair.height===2160),'Expected native 16:9 dimensions');
      assert.ok(!resolutions.has(pair.width),'Duplicate gallery resolution'); resolutions.add(pair.width);
      fields(pair.clippedHdrPixels,['before','after']); fields(pair.sourceReportSha256,['before','after']);
      for(const side of ['before','after']) {
        integer(pair.clippedHdrPixels[side],pair.width*pair.height);
        for(const value of [pair.sourceReportSha256[side],pair[side+'Sha256'],pair[side+'SourcePngSha256']]) assert.ok(typeof value==='string'&&sha.test(value),'Invalid gallery hash');
        integer(pair[side+'Bytes'],32*1024*1024); assert.ok(pair[side+'Bytes']>0);
        assert.equal(pair[side],'images/'+pair[side+'SourcePngSha256']+'.webp','Image paths must remain in the reviewed gallery');
        const record={sha256:pair[side+'Sha256'],bytes:pair[side+'Bytes'],width:pair.width,height:pair.height};
        if(images.has(pair[side])) assert.deepEqual(images.get(pair[side]),record,'Inconsistent repeated-image metadata');
        images.set(pair[side],record);
      }
    }
  }
  // Validate all metadata before opening image files.
  for(const [relative,record] of images) {
    const bytes=readImage(relative);
    assert.equal(bytes.length,record.bytes,'Gallery image byte count differs');
    assert.equal(createHash('sha256').update(bytes).digest('hex'),record.sha256,'Gallery image hash differs');
    assert.equal(bytes.toString('ascii',0,4),'RIFF'); assert.equal(bytes.toString('ascii',8,12),'WEBP');
    assert.equal(bytes.readUInt32LE(4)+8,bytes.length,'Invalid WebP container length');
    let dimensions=null;
    for(let offset=12;offset<bytes.length;) {
      assert.ok(offset+8<=bytes.length,'Truncated WebP chunk');
      const kind=bytes.toString('ascii',offset,offset+4), length=bytes.readUInt32LE(offset+4), start=offset+8;
      assert.ok(start+length+(length%2)<=bytes.length,'Truncated WebP payload');
      assert.equal(kind,'VP8 ','Only the reviewed metadata-free lossy WebP encoding is supported');
      assert.ok(dimensions===null && length>=10,'Expected one complete WebP image');
      assert.equal(bytes.toString('hex',start+3,start+6),'9d012a','Invalid WebP frame signature');
      dimensions=[bytes.readUInt16LE(start+6)&0x3fff,bytes.readUInt16LE(start+8)&0x3fff];
      offset=start+length+(length%2);
    }
    assert.deepEqual(dimensions,[record.width,record.height],'Actual gallery image dimensions differ');
  }
  return {views:seen.size,pairs:20,imageReferences:40,uniqueImages:images.size};
}
