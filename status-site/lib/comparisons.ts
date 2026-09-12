export type BeforePreview = { sheet: string; x: number; y: number; width: number; height: number; kind: string; note?: string };
export type AfterPreview = { file: string; label: string; scope: string; source: string; sha256: string };
export type Comparison = { before: BeforePreview | null; status: string; reason?: string; after?: AfterPreview[] };
export type ComparisonIndex = {
  schema_version: number; catalog_sha256: string; tile_size: number; columns: number;
  sheets: { file: string; width: number; height: number; sha256: string }[];
  assets: Record<string, Comparison>;
};
// Public previews are same-origin files; metadata never supplies an external URL.
export const previewUrl = (name: string) => /^[a-z0-9][a-z0-9_-]*\.webp$/.test(name) ? './comparisons/' + name : null;
export function validSprite(sprite: BeforePreview, index: ComparisonIndex) {
  const sheet = index.sheets.find(sheet => sheet.file === sprite.sheet);
  if (!sheet || !previewUrl(sheet.file) || ![sprite.x,sprite.y,sprite.width,sprite.height,sheet.width,sheet.height].every(Number.isInteger)
    || sprite.x < 0 || sprite.y < 0 || sprite.width < 1 || sprite.height < 1
    || sprite.x + sprite.width > sheet.width || sprite.y + sprite.height > sheet.height) return null;
  return sheet;
}
