'use client';
import { useEffect, useMemo, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, Box, Check, ChevronLeft, ChevronRight, Circle, Clock3, FileCheck2, Layers3, Mountain, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import snapshot from '@/data/summary.json';
import project from '@/data/project.json';
import roadmap from '@/data/roadmap.json';
import biomeSnapshot from '@/data/biome-summary.json';
import { Progress } from '@/components/ui/progress';
import { overallProgress, biomeProgress } from '@/lib/progress';
import { type Asset, type Kind, type Stage, type SortOrder, type BiomeScope, stages, labels, categoryLabel, filterAssets, sortAssets, pageSlice, assetBiomes } from '@/lib/inventory';
import { parseBiomeInventory } from '@/lib/biome-inventory';
import { AssetComparison } from '@/components/asset-comparison';
import { type ComparisonIndex } from '@/lib/comparisons';

const repo = 'https://github.com/Sikbik/valheim-impact';
const evidenceUrl = (path: string) => './evidence/' + path.replaceAll('/', '__') + '.html';
const num = (value: number) => value.toLocaleString('en-US');
const stamp = snapshot.snapshot_at.replace('T',' ').replace('Z',' UTC');
const stagesShown = stages.slice(1);
const overall = overallProgress(snapshot.summary.stage_counts);
const initialFilters = { kind: 'texture' as Kind, query: '', category: 'all', stage: 'all', biome: 'all' };
const stageNotes: Record<Stage,string> = {
  inventoried: 'Serialized metadata is recorded. This does not establish visible coverage.',
  authored: 'An original authored replacement is mapped to this exact asset identity.',
  uv_reviewed: 'Authored appearance was inspected on identified original UVs within the evidence scope.',
  native_validated: 'The replacement passed native texture checks. This is not mesh or shader streaming proof.',
  game_fixture_validated: 'The exact asset participated in an isolated menu test, not an in-world playthrough.',
  approved: 'Final art approval within the recorded scope. None recorded yet.',
};

export default function Home() {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [biomeInventory, setBiomeInventory] = useState<BiomeScope[]>([]);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [filters, setFilters] = useState(initialFilters);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [biomeId, setBiomeId] = useState('meadows');
  const [sortOrder, setSortOrder] = useState<SortOrder>('evidence');
  const [comparisons, setComparisons] = useState<ComparisonIndex | null>(null);
  const [comparisonError, setComparisonError] = useState(false);
  const [comparisonAttempt, setComparisonAttempt] = useState(0);
  const biome = roadmap.biomes.find(item => item.id === biomeId)!;
  const scoped = biomeProgress(biome, assets ?? []);
  const browsing = biomeSnapshot.biomes.find(item => item.id === biomeId)!;
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    Promise.all(['./data/inventory.json', './data/biomes.json'].map(url =>
      fetch(url, { signal: controller.signal }).then(response => { if (!response.ok) throw new Error('Inventory request failed'); return url.endsWith('biomes.json') ? response.text().then(text=>parseBiomeInventory(text, biomeSnapshot.data_sha256)) : response.json(); })))
      .then(([value, membership]) => {
        if (!value || typeof value !== 'object') throw new Error('Invalid snapshot');
        const data = value as { schema_version: number; snapshot_at: string;
          inputs: { status_manifest_sha256: string }; assets: Asset[] };
        if (data.schema_version !== 1 || data.snapshot_at !== snapshot.snapshot_at
          || data.inputs.status_manifest_sha256 !== snapshot.inputs.status_manifest_sha256
          || !Array.isArray(data.assets) || data.assets.length !== snapshot.summary.textures + snapshot.summary.meshes)
          throw new Error('Snapshot mismatch');
        if (membership.schema_version !== 1 || membership.inputs?.catalog_sha256 !== snapshot.inputs.catalog_sha256
          || membership.inputs?.source_sha256 !== biomeSnapshot.inputs.source_sha256
          || !Array.isArray(membership.biomes) || membership.biomes.length !== roadmap.biomes.length
          || membership.biomes.some((row: BiomeScope, i: number) => row.id !== biomeSnapshot.biomes[i].id || !Array.isArray(row.asset_ids)))
          throw new Error('Biome membership mismatch');
        setBiomeInventory(membership.biomes);
        setAssets(sortAssets(data.assets));
      })
      .catch(cause => { if (cause.name !== 'AbortError') setError('The inventory could not be loaded. Retry to request this snapshot again.'); });
    return () => controller.abort();
  },[attempt]);
  useEffect(() => {
    const controller = new AbortController();
    setComparisonError(false);
    fetch('./comparisons/index.json', { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('Preview request failed'); return response.json(); })
      .then((value: ComparisonIndex) => {
        if (value.schema_version !== 1 || value.tile_size !== 192 || value.columns !== 8 || !Array.isArray(value.sheets)
          || value.catalog_sha256 !== snapshot.inputs.catalog_sha256 || !value.assets || Object.keys(value.assets).length !== snapshot.summary.textures + snapshot.summary.meshes) throw new Error('Invalid comparison index');
        setComparisons(value);
      })
      .catch(error => { if (error.name !== 'AbortError') setComparisonError(true); });
    return () => controller.abort();
  }, [comparisonAttempt]);
  const rows = useMemo(() => assets ? sortAssets(filterAssets(assets, filters, biomeInventory), sortOrder, biomeInventory) : [], [assets, filters, sortOrder, biomeInventory]);
  const current = pageSlice(rows,page);
  const counts = snapshot.summary.stage_counts[filters.kind];
  const categories = Object.entries(snapshot.summary.category_counts[filters.kind]).sort(([a],[b]) => a.localeCompare(b));
  const updateFilters = (change: Partial<typeof filters>) => { setFilters(value=>({...value,...change})); setPage(0); };
  const evidence = selected ? snapshot.evidence.filter(item => Object.values(selected.evidence).flat().includes(item.id)) : [];
  const done = project.milestones.filter(item => item.state === 'done').length;
  const biomeLabel = (id: string) => {
    const names = assetBiomes(id, biomeInventory).map(biome => biome.name);
    return <span title={names.join(', ')}>{names.length > 2 ? `Shared across ${names.length} biomes` : names.join(', ') || 'Unassigned'}</span>;
  };
  return <div className="app-shell">
    <a href="#inventory" className="skip-link">Skip to asset inventory</a>
    <aside className="sidebar"><img className="nav-timber" src="./art/nordic-timber.webp" alt=""/>
      <a href="#overview" className="brand"><Mountain size={27}/><span>VALHEIM<span className="brand-impact">IMPACT</span></span></a>
      <p className="nav-caption">THE ARTISAN’S LEDGER</p>
      <nav aria-label="Project sections">
        <a className="nav-item" href="#overview"><Layers3 size={18}/> Overview</a>
        <a className="nav-item" href="#inventory"><Box size={18}/> Asset inventory</a>
        <a className="nav-item" href="#milestones"><ShieldCheck size={18}/> Milestones</a>
        <a className="nav-item" href="#validation"><FileCheck2 size={18}/> Validation</a>
      </nav>
      <div className="sidebar-foot"><span className="status-dot"/> Meadows first<p>Original art. Familiar world.</p><a href={repo} target="_blank" rel="noreferrer" className="repo-link mt-5">Project repository <ArrowUpRight size={14}/></a></div>
    </aside>
    <main id="overview" className="main-content">
      <header className="topbar"><span>WORLD IN THE MAKING <span className="crumb">/ Development ledger</span></span><a className="repo-link" href={repo} target="_blank" rel="noreferrer">Open GitHub <ArrowUpRight size={16}/></a></header>
      <div className="page-heading" style={{borderImageSource:"url(./art/nordic-timber.webp)",borderImageSlice:72,borderImageWidth:12}}><img className="meadows-art" src="./art/meadows-banner.webp" alt="" fetchPriority="high"/><div className="masthead-copy"><p className="eyebrow">THE ARTISAN’S LEDGER</p><h1>Valheim Impact</h1><p className="subheading">A Viking world, painted anew. Follow every texture, model, and milestone.</p></div><span className="phase-badge"><span className="status-dot"/> {project.phase}</span></div>
      <section className="stats-grid" aria-label="Project inventory">
        {[[snapshot.summary.textures,'Textures inventoried','Albedo, normal and supporting maps'],[snapshot.summary.meshes,'Mesh objects inventoried','Original geometry currently retained'],[project.material_fixtures,'Game material fixtures','Passed in the isolated menu fixture'],[snapshot.summary.stage_counts.texture.approved + snapshot.summary.stage_counts.mesh.approved,'Assets art-approved','Complete scene review still ahead']].map(([value,label,note])=><div className="stat" key={label}><p>{label}</p><strong>{typeof value === 'number' ? num(value) : value}</strong><small>{note}</small></div>)}
      </section>
      <div className="work-notice"><span className="next-label">IN FOCUS</span><div><strong>One coherent Meadows scene.</strong><span> Straw cutouts now have UV and native mip evidence. Full buildings, foliage, and weather are next.</span></div><a href="#milestones" aria-label="View current milestones"><ArrowUpRight size={20}/></a></div>
      <section className="world-journey panel" aria-labelledby="journey-title">
        <div className="journey-heading"><div><p className="eyebrow">FROM THE MEADOWS TO THE EDGE OF THE WORLD</p><h2 id="journey-title">The journey so far</h2><p>Overall inventory progress</p></div><div className="journey-percent"><strong>{overall.percent.toFixed(2)}<span>%</span></strong><span>{num(overall.completed)} / {num(overall.possible)} steps evidenced</span></div></div>
        <Progress className="world-progress" value={overall.percent} aria-label="Overall inventory progress" aria-valuetext={`${overall.percent.toFixed(2)} percent, ${overall.completed} of ${overall.possible} art and validation steps evidenced`}/>
        <div className="biome-checkpoints" aria-label="Biome checkpoints">{roadmap.biomes.map((item,index)=><button key={item.id} aria-pressed={biomeId===item.id} className={'biome-checkpoint '+item.state+(biomeId===item.id?' selected':'')} onClick={()=>setBiomeId(item.id)}><span className="checkpoint-rune">{item.state==='approved'?<Check size={15}/>:<span>{String(index+1).padStart(2,'0')}</span>}</span><strong>{item.name}</strong><span>{item.state==='active'?'In the workshop':item.state==='approved'?'Approved':'On the horizon'}</span></button>)}</div>
        <div className="biome-detail" aria-live="polite"><Mountain size={22}/><div><strong>{biome.name} {biome.state==='active'?'· pilot scope':biome.state==='approved'?'· approved':'· planned'}</strong><p>{biome.asset_ids.length ? assets ? `${biome.asset_ids.length} review-pilot assets mapped. ${scoped.authored} authored replacements, ${scoped.approved} final art approvals. A complete biome review is still ahead.` : `${biome.asset_ids.length} review-pilot assets mapped. Loading validation counts...` : 'Review scope and visual approval have not been recorded for this biome yet.'}</p><p>{num(browsing.texture_count)} textures and {num(browsing.mesh_count)} meshes available in the inventory.</p></div><a href="#inventory" onClick={()=>updateFilters({biome:biome.id})}>Browse {biome.name} inventory <ArrowUpRight size={15}/></a></div>
        <p className="journey-method">Each recorded asset has five art and validation steps. Discovery earns no completion credit. This is inventory work, not a percentage of the visible world replaced. Biome checkmarks require a separate reviewed approval.</p>
      </section>
      <section className="panel" id="inventory">
        <div className="section-heading"><div><p className="eyebrow">CRAFTED, CHECKED, RECORDED</p><h2>The world archive</h2></div><a className="text-link" href="./data/inventory.json" download="valheim-impact-inventory.json"><ArrowDownToLine size={16}/> Download snapshot</a></div>
        <div className="inventory-intro">Checkmarks record evidence for an exact asset. Unchecked means unverified, and stages are independent. Open an asset for scope and proof.</div>
        <div className="inventory-tabs">
          <Tabs value={filters.kind} onValueChange={value=>updateFilters({kind:value as Kind, category:'all'})}>
            <TabsList variant="line" className="h-12 gap-5">
              <TabsTrigger value="texture" className="px-1 text-sm">Textures <span className="count-badge">{num(snapshot.summary.textures)}</span></TabsTrigger>
              <TabsTrigger value="mesh" className="px-1 text-sm">Models / meshes <span className="count-badge">{num(snapshot.summary.meshes)}</span></TabsTrigger>
            </TabsList>
          </Tabs>
          <span className="muted">Original asset inventory</span>
        </div>
        {filters.kind === 'mesh' && <div className="mesh-note"><Box size={16}/><span>{num(snapshot.summary.meshes)} serialized mesh objects, including LODs and shared parts. This is not a count of models needing replacement. {snapshot.summary.authored_models} authored model replacements; native model streaming remains unvalidated.</span></div>}
        <div className="stage-totals" aria-label={filters.kind + ' stage counts'}>
          {stagesShown.map(stage=><div key={stage}><span>{labels[stage]}</span><strong>{num(counts[stage])}</strong></div>)}
        </div>
        <div className="filter-bar">
          <div className="search-control"><Search size={17}/><Input aria-label="Search asset names, paths or IDs" placeholder="Search names, paths, or asset IDs..." value={filters.query} onChange={event=>updateFilters({query:event.target.value})} className="h-10 pl-10 bg-transparent"/></div>
          <NativeSelect aria-label="Filter by category" value={filters.category} onChange={event=>updateFilters({category:event.target.value})} className="filter-select"><NativeSelectOption value="all">All categories</NativeSelectOption>{categories.map(([name,count])=><NativeSelectOption key={name} value={name}>{categoryLabel(name)} ({num(count)})</NativeSelectOption>)}</NativeSelect>
          <NativeSelect aria-label="Filter by stage" value={filters.stage} onChange={event=>updateFilters({stage:event.target.value})} className="filter-select"><NativeSelectOption value="all">All stages</NativeSelectOption><NativeSelectOption value="in_progress">Work evidenced</NativeSelectOption><NativeSelectOption value="pending">Awaiting art approval</NativeSelectOption>{stagesShown.map(stage=><NativeSelectOption key={stage} value={stage}>{labels[stage]}</NativeSelectOption>)}</NativeSelect>
          <NativeSelect aria-label="Filter by biome" value={filters.biome} onChange={event=>updateFilters({biome:event.target.value})} className="filter-select"><NativeSelectOption value="all">All biomes</NativeSelectOption>{biomeSnapshot.biomes.map(biome=><NativeSelectOption key={biome.id} value={biome.id}>{biome.name} ({num(filters.kind === 'texture' ? biome.texture_count : biome.mesh_count)})</NativeSelectOption>)}<NativeSelectOption value="unassigned">Unassigned</NativeSelectOption></NativeSelect>
          <NativeSelect aria-label="Sort inventory" value={sortOrder} onChange={event=>{setSortOrder(event.target.value as SortOrder);setPage(0);}} className="filter-select"><NativeSelectOption value="evidence">Evidence first</NativeSelectOption><NativeSelectOption value="biome">Sort by biome</NativeSelectOption><NativeSelectOption value="name">Name A to Z</NativeSelectOption></NativeSelect>
          <Button variant="ghost" className="h-10 px-3" onClick={()=>{updateFilters({...initialFilters,kind:filters.kind});setSortOrder('evidence');}} disabled={!filters.query && filters.category === 'all' && filters.stage === 'all' && filters.biome === 'all' && sortOrder === 'evidence'}>Reset</Button>
        </div>
        <p className="biome-mapping-note">Biome filters include untouched assets from game configuration and source mappings. Shared assets appear in each matching biome. Biome membership does not add progress checkmarks; Unassigned means no mapping is recorded.</p>
        {comparisonError && <div className="preview-error">The preview library could not be loaded. <Button variant="outline" onClick={()=>setComparisonAttempt(value=>value+1)}>Retry previews</Button></div>}
        <div className="table-status" aria-live="polite">{error ? error : assets ? num(rows.length) + ' matching ' + (filters.kind === 'texture' ? 'textures' : 'mesh objects') : 'Loading inventory...'} <span>{sortOrder === 'biome' ? 'Biome order, then evidence' : sortOrder === 'name' ? 'Name A to Z' : 'Evidence first, then name'} · 40 per page</span></div>
        {error ? <div className="empty-state"><Circle size={24}/><p>{error}</p><Button onClick={()=>setAttempt(value=>value+1)}>Retry inventory</Button></div> : !assets ? <div className="empty-state"><Clock3 size={24}/><p>Loading the recorded asset inventory...</p></div> : rows.length === 0 ? <div className="empty-state"><Search size={24}/><h3>No matching assets</h3><p>Try a different name, biome, category or stage.</p><Button variant="outline" onClick={()=>updateFilters({...initialFilters,kind:filters.kind})}>Clear filters</Button></div> :
          <Table className="asset-table"><TableHeader><TableRow><TableHead>Asset / category</TableHead><TableHead>Comparison</TableHead><TableHead>Biome</TableHead><TableHead>Original size</TableHead>{stages.map(stage=><TableHead key={stage} className="stage-column" title={stageNotes[stage]}>{labels[stage]}</TableHead>)}</TableRow></TableHeader><TableBody>{current.rows.map(asset=><TableRow key={asset.id}><TableCell><button className="asset-name" onClick={()=>setSelected(asset)}>{asset.name}<ArrowUpRight size={13}/></button><div className="asset-meta">{categoryLabel(asset.category)} <span>· {asset.id.split(':')[1]}</span></div></TableCell><TableCell><button className="open-comparison" aria-label={'Compare '+asset.name+' before and after'} onClick={()=>setSelected(asset)}>{comparisonError ? <span className="small-note">Preview unavailable</span> : <AssetComparison key={asset.id} entry={comparisons?.assets[asset.id]} index={comparisons} name={asset.name} kind={asset.kind} compact/>}</button></TableCell><TableCell className="asset-biomes">{biomeLabel(asset.id)}</TableCell><TableCell className="asset-size">{asset.dimensions ? asset.dimensions.join(' × ') : 'Mesh'}</TableCell>{stages.map(stage=><TableCell key={stage} className="stage-column"><Checkbox checked={asset.stages[stage]} readOnly tabIndex={-1} className="mx-auto" aria-label={asset.name + ': ' + labels[stage] + (asset.stages[stage] ? ', evidenced' : ', unverified')}/></TableCell>)}</TableRow>)}</TableBody></Table>
        }
        <div className="pagination"><span>{current.start}–{current.end} of {num(rows.length)} <span className="hide-small">· Categories are estimates</span></span><div><Button variant="outline" size="icon" aria-label="Previous page" disabled={!assets || current.page===0} onClick={()=>setPage(current.page-1)}><ChevronLeft/></Button><span>Page {current.page+1} / {current.pages}</span><Button variant="outline" size="icon" aria-label="Next page" disabled={!assets || current.page+1>=current.pages} onClick={()=>setPage(current.page+1)}><ChevronRight/></Button></div></div>
      </section>
      <div className="lower-grid">
        <section className="panel" id="milestones"><div className="section-heading"><div><p className="eyebrow">THE PATH AHEAD</p><h2>Project milestones</h2></div><span className="muted">{done} of {project.milestones.length} complete</span></div>
          <div className="milestone-list">{project.milestones.map(item=><article key={item.title} className={'milestone '+item.state}><span className="milestone-icon" aria-label={item.state}>{item.state==='done'?<Check size={16}/>:item.state==='active'?<Clock3 size={16}/>:<Circle size={16}/>}</span><div><h3>{item.title}{item.state==='active'&&<span className="active-label">In progress</span>}</h3><p>{item.detail}</p>{item.evidence&&<a href={evidenceUrl(item.evidence)} target="_blank" rel="noreferrer">View evidence <ArrowUpRight size={12}/></a>}</div></article>)}</div>
        </section>
        <section className="panel validation-panel" id="validation"><div className="section-heading"><div><p className="eyebrow">QUALITY & PERFORMANCE</p><h2>Validation ledger</h2></div><ShieldCheck size={22} className="gold"/></div>
          <div className="validation-body">
            <p className="ledger-label">LOCAL CANDIDATE</p><p className="candidate">{project.candidate}</p>
            <dl className="ledger"><div><dt>Platform tested</dt><dd>Linux · Vulkan · Linear</dd></div><div><dt>Native texture checks</dt><dd>{project.native_texture_count} textures / {project.mip_levels} mips</dd></div><div><dt>Material binding fixture</dt><dd>{project.native_binding_checks} checks passed</dd></div><div><dt>Menu comparisons</dt><dd>{project.material_fixtures} material pairs · 4K captures</dd></div><div><dt>Texture payload</dt><dd>{(project.native_texture_payload_bytes/1048576).toFixed(2)} MiB</dd></div><div><dt>Install package</dt><dd>{(project.package_bytes/1048576).toFixed(2)} MiB</dd></div></dl>
            <p className="small-note">Payload size is not total VRAM usage. Menu captures establish binding behavior, not full-scene art approval.</p>
            <div className="target-card"><SlidersHorizontal size={19}/><div><strong>Balanced quality target</strong><p>6 GB VRAM · 16 GB RAM · 1080p</p><span className="unmeasured">Hardware benchmark pending</span></div></div>
            <div className="staging-note"><strong>In the workshop</strong><p>{project.staged_detail} {project.staged_native_texture_count} staged textures / {project.staged_mip_levels} mips. The cutout adapter has {project.staged_native_binding_checks} native checks.</p><a className="text-link" href={evidenceUrl(project.staged_evidence)} target="_blank" rel="noreferrer">Read latest staged review <ArrowUpRight size={14}/></a></div><p className="small-note">Selective high-resolution textures and crisp presentation on 4K displays remain art goals. Whole-world coverage, weather, LOD transitions, and model or shader streaming still need validation.</p>
            <a className="text-link" href={evidenceUrl('docs/MILESTONE_03.md')} target="_blank" rel="noreferrer">Read the installed-candidate evidence <ArrowUpRight size={16}/></a>
          </div>
        </section>
      </div>
      <footer><div><span className="status-dot"/> Evidence snapshot: {stamp}</div><div>Updated with project milestones. Reload after a published update.<br/>Inventory counts are not a percentage of the visible world replaced.</div></footer>
    </main>
    <Sheet open={!!selected} onOpenChange={open=>{if(!open)setSelected(null);}}>
      <SheetContent className="w-full sm:max-w-xl overflow-y-auto p-2">
        <SheetHeader className="pt-9"><p className="eyebrow">{selected?.kind==='mesh'?'ORIGINAL MESH':'ORIGINAL TEXTURE'}</p><SheetTitle className="text-2xl break-words">{selected?.name}</SheetTitle><SheetDescription>{selected ? categoryLabel(selected.category) : ''} · {selected?.dimensions?.join(' × ') ?? 'Original geometry retained'}</SheetDescription></SheetHeader>
        {selected && <div className="asset-detail">
          {comparisonError ? <p className="small-note">Preview library unavailable. Use Retry previews in the inventory.</p> : <AssetComparison key={selected.id} entry={comparisons?.assets[selected.id]} index={comparisons} name={selected.name} kind={selected.kind}/>}
          <h3>Inventory biomes</h3><p className="small-note">{assetBiomes(selected.id,biomeInventory).map(b=>b.name).join(', ') || 'Unassigned, biome mapping pending.'}</p>
          <h3>Exact asset identity</h3><code>{selected.id}</code><p className="small-note">Names can repeat. Checkmarks belong only to this identity.</p>
          {selected.note&&<div className="detail-note">{selected.note}</div>}
          <h3>Validation stages</h3>{stages.map(stage=><div className="detail-stage" key={stage}><Checkbox checked={selected.stages[stage]} readOnly aria-label={labels[stage]}/><div><strong>{labels[stage]} <span>{selected.stages[stage]?'Evidenced':'Unverified'}</span></strong><p>{stageNotes[stage]}</p></div></div>)}
          <h3>Evidence & scope</h3>{evidence.length ? evidence.map(item=><div className="evidence-item" key={item.id}><a href={evidenceUrl(item.path)} target="_blank" rel="noreferrer">{item.title}<ArrowUpRight size={14}/></a><p>{item.scope}</p></div>):<p className="small-note">Only inventory metadata is recorded for this asset. No authored or validation evidence yet.</p>}
          <h3>Source identity paths</h3>{selected.container_paths.length ? selected.container_paths.map(path=><code className="source-path" key={path}>{path}</code>):<p className="small-note">No container path was recorded.</p>}
          <p className="small-note">Reference images are small comparison thumbnails. Full game textures and mesh files are not included.</p>
        </div>}
      </SheetContent>
    </Sheet>
  </div>;
}
