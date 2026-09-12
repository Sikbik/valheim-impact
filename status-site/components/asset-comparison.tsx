import { useState } from 'react';
import { ImageOff } from 'lucide-react';
import { type Comparison, type ComparisonIndex, type BeforePreview, type AfterPreview, previewUrl, validSprite } from '@/lib/comparisons';

function Preview({before, after, index, label}: {before?: BeforePreview | null; after?: AfterPreview; index: ComparisonIndex; label: string}) {
  const [failed, setFailed] = useState(false);
  const sheet = before ? validSprite(before, index) : null;
  const url = after ? previewUrl(after.file) : sheet ? previewUrl(sheet.file) : null;
  return <span className="comparison-image" role="img" aria-label={label}>
    {url && !failed ? <img src={url} alt="" loading="lazy" decoding="async" onError={()=>setFailed(true)}
      style={before && sheet ? {width:`${sheet.width / before.width * 100}%`,height:`${sheet.height / before.height * 100}%`,maxWidth:'none',left:`${-before.x / before.width * 100}%`,top:`${-before.y / before.height * 100}%`} : undefined}/>
      : <span className="comparison-placeholder"><ImageOff size={22}/><span>{failed ? 'Preview unavailable' : label}</span></span>}
  </span>;
}

export function AssetComparison({entry, index, name, kind, compact=false}: {entry?: Comparison; index: ComparisonIndex | null; name: string; kind: string; compact?: boolean}) {
  const after = entry?.after ?? [];
  const [variant, setVariant] = useState(0);
  const current = after[Math.min(variant, Math.max(0, after.length - 1))];
  if (!index) return <span className="small-note">Loading previews...</span>;
  const beforeLabel = entry?.before ? `${name}, original ${kind} preview` : 'Reference unavailable';
  if (compact) return <span className="asset-comparison compact"><span className="comparison-pair">
    <span><span className="comparison-label">Before</span><Preview before={entry?.before} index={index} label={beforeLabel}/></span>
    <span><span className="comparison-label">After</span><Preview after={current} index={index} label={current ? `${name}, ${current.label}` : kind === 'mesh' ? 'Original geometry retained' : 'Not authored yet'}/></span>
  </span></span>;
  return <div className={compact ? 'asset-comparison compact' : 'asset-comparison'}>
    <div className="comparison-pair">
      <figure><figcaption>Before</figcaption><Preview key={name+'before'} before={entry?.before} index={index} label={beforeLabel}/></figure>
      <figure><figcaption>After</figcaption><Preview key={name+(current?.file ?? 'pending')} after={current} index={index} label={current ? `${name}, ${current.label}` : kind === 'mesh' ? 'Original geometry retained' : 'Not authored yet'}/></figure>
    </div>
    {!compact && <>
      {after.length > 1 && <label className="comparison-variant">Replacement variant<select value={variant} onChange={event=>setVariant(Number(event.target.value))}>{after.map((item,i)=><option key={item.file} value={i}>{item.label}</option>)}</select></label>}
      {current ? <p className="comparison-caption"><strong>{current.label}.</strong> {current.scope}</p> : <p className="comparison-caption">{kind === 'mesh' ? 'No replacement mesh or reviewed material preview is mapped to this identity yet.' : 'This texture has no mapped authored replacement yet.'}</p>}
      {entry?.before?.note && <p className="small-note">{entry.before.note}</p>}
      {!entry?.before && <p className="small-note">{entry?.reason || 'A displayable reference has not been captured.'}</p>}
      <p className="comparison-credit">Small reference previews are for comparison. Original Valheim artwork belongs to Iron Gate. Preview images do not indicate validation or approval.</p>
    </>}
  </div>;
}
