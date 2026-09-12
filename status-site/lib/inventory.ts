export const stages = ['inventoried', 'authored', 'uv_reviewed', 'native_validated', 'game_fixture_validated', 'approved'] as const;
export type Stage = typeof stages[number];
export type Kind = 'texture' | 'mesh';
export type Asset = {
  id: string; kind: Kind; name: string; object_name: string;
  category: string; dimensions: number[] | null; container_paths: string[];
  stages: Record<Stage, boolean>; evidence: Record<string, string[]>; note?: string;
};
export type Filters = { kind: Kind; query: string; category: string; stage: string };
export const labels: Record<Stage, string> = {
  inventoried: 'Inventoried', authored: 'Authored', uv_reviewed: 'UV checked',
  native_validated: 'Native tested', game_fixture_validated: 'Game fixture', approved: 'Art approved',
};
export const categoryLabel = (category: string) => category.split('_').map(word => word[0]?.toUpperCase() + word.slice(1)).join(' ');
export const progressScore = (asset: Asset) => stages.slice(1).filter(stage => asset.stages[stage]).length;
export function matchesAsset(asset: Asset, filters: Filters): boolean {
  const query = filters.query.trim().toLowerCase();
  return asset.kind === filters.kind
    && (filters.category === 'all' || asset.category === filters.category)
    && (filters.stage === 'all' || (filters.stage === 'pending' ? !asset.stages.approved
      : filters.stage === 'in_progress' ? progressScore(asset) > 0 && !asset.stages.approved
      : stages.includes(filters.stage as Stage) && asset.stages[filters.stage as Stage]))
    && (!query || [asset.name, asset.object_name, asset.id, ...asset.container_paths].some(value => value.toLowerCase().includes(query)));
}
export function filterAssets(assets: Asset[], filters: Filters): Asset[] {
  return assets.filter(asset => matchesAsset(asset, filters));
}
export function sortAssets(assets: Asset[]): Asset[] {
  return [...assets].sort((a,b) => progressScore(b)-progressScore(a)
    || a.name.localeCompare(b.name, 'en') || a.id.localeCompare(b.id, 'en'));
}
export function pageSlice<T>(items: T[], requestedPage: number, pageSize=40) {
  if (!Number.isInteger(pageSize) || pageSize < 1) throw new Error('Invalid page size');
  const pages = Math.max(1, Math.ceil(items.length/pageSize));
  const page = Math.max(0, Math.min(Number.isInteger(requestedPage) ? requestedPage : 0, pages-1));
  return { page, pages, rows: items.slice(page*pageSize,(page+1)*pageSize), start: items.length ? page*pageSize+1 : 0,
    end: Math.min((page+1)*pageSize,items.length) };
}
