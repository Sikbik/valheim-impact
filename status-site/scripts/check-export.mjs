import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root=fileURLToPath(new URL('../dist/client/',import.meta.url));
const prefix=process.env.GITHUB_PAGES==='true'?'/valheim-impact/':'/';
const index=path.join(root,'index.html');
assert.ok(existsSync(index),'Static export must contain a homepage');
const html=readFileSync(index,'utf8');
assert.ok(html.includes('id="root"'),'Homepage must contain the application mount');
let scripts=0, styles=0;
for(const match of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
  const url=match[1];
  if(url.startsWith('https://')||url.startsWith('#')) continue;
  assert.ok(url.startsWith(prefix),'Asset URL must use the deployment base path: '+url);
  const relative=url.slice(prefix.length).split('?')[0];
  assert.ok(!relative.split('/').includes('..'),'Export paths must remain contained');
  assert.ok(existsSync(path.join(root,relative)),'Missing exported asset: '+relative);
  if(relative.endsWith('.js'))scripts++;
  if(relative.endsWith('.css'))styles++;
}
assert.ok(scripts>0&&styles>0,'Static export must include application scripts and styles');
for(const relative of ['art/meadows-banner.webp','art/nordic-timber.webp','data/inventory.json'])
  assert.ok(existsSync(path.join(root,relative)),'Missing public content: '+relative);
const snapshot=JSON.parse(readFileSync(path.join(root,'data/inventory.json'),'utf8'));
const project=JSON.parse(readFileSync(new URL('../data/project.json',import.meta.url),'utf8'));
const evidence=new Set([...snapshot.evidence.map(e=>e.path),...project.milestones.map(m=>m.evidence).filter(Boolean),project.staged_evidence]);
for(const source of evidence) assert.ok(existsSync(path.join(root,'evidence',source.replaceAll('/','__')+'.html')),'Missing public evidence: '+source);
assert.ok(!readdirSync(root).some(name=>['server','.env','.git','node_modules'].includes(name)),'Export includes nonpublic server or configuration files');
const comparisons=JSON.parse(readFileSync(path.join(root,'comparisons/index.json'),'utf8'));
assert.equal(comparisons.catalog_sha256,snapshot.inputs.catalog_sha256,'Preview catalog identity must match inventory');
assert.deepEqual(Object.keys(comparisons.assets).sort(),snapshot.assets.map(asset=>asset.id).sort(),'Every inventory entry needs a preview record');
const previewFiles=[...comparisons.sheets,...Object.values(comparisons.assets).flatMap(entry=>entry.after ?? [])];
for(const preview of previewFiles) {
  assert.match(preview.file,/^[a-z0-9][a-z0-9_-]*\.webp$/,'Preview must use a local WebP basename');
  const bytes=readFileSync(path.join(root,'comparisons',preview.file));
  assert.equal(createHash('sha256').update(bytes).digest('hex'),preview.sha256,'Exported preview hash mismatch: '+preview.file);
}
console.log(`Verified ${previewFiles.length} comparison files for ${snapshot.assets.length} inventory entries.`);
console.log(`Static export verified: homepage, ${scripts} script(s), ${styles} stylesheet(s), ${evidence.size} evidence links.`);
