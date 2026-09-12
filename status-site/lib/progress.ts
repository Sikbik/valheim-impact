import { stages, type Asset } from './inventory.ts';

export type Biome = { id: string; name: string; state: string; asset_ids: string[]; approval_evidence: string[] };

// Inventory discovery is excluded: finding an asset is not overhaul work.
export function overallProgress(counts: Record<string, Record<string, number>>) {
  const total = Object.values(counts).reduce((sum, kind) => sum + kind.inventoried, 0);
  const possible = total * (stages.length - 1);
  const completed = Object.values(counts).reduce((sum, kind) =>
    sum + stages.slice(1).reduce((subtotal, stage) => subtotal + kind[stage], 0), 0);
  return { completed, possible, percent: possible ? completed / possible * 100 : 0 };
}

export function biomeProgress(biome: Biome, assets: Asset[]) {
  const ids = new Set(biome.asset_ids);
  const scoped = assets.filter(asset => ids.has(asset.id));
  return {
    scoped: scoped.length,
    authored: scoped.filter(asset => asset.stages.authored).length,
    approved: scoped.filter(asset => asset.stages.approved).length,
    completed: scoped.reduce((sum, asset) => sum + stages.slice(1).filter(stage => asset.stages[stage]).length, 0),
    possible: scoped.length * (stages.length - 1),
  };
}
