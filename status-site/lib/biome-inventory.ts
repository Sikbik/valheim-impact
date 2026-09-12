import type { BiomeScope } from './inventory';

export type BiomeInventory = {
  schema_version: number;
  inputs: { catalog_sha256: string; source_sha256: string };
  biomes: BiomeScope[];
};

// The application pins actual response bytes, not just a hash field supplied
// inside the response. This prevents stale membership from changing the counts.
export async function parseBiomeInventory(raw: string, expectedSha256: string): Promise<BiomeInventory> {
  const bytes = new TextEncoder().encode(raw);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const actual = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
  if (actual !== expectedSha256) throw new Error('Biome inventory content differs from the application snapshot');
  return JSON.parse(raw) as BiomeInventory;
}
