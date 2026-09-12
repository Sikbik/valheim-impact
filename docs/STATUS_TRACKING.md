# Progress tracking and reviewed contributions

The [public tracker](https://sikbik.github.io/valheim-impact/) is built from this
repository. It shows exact texture and mesh identities, scoped validation
checkmarks, all nine biome checkpoints, project-wide milestones and validation
summaries. It is a dated snapshot, not live game telemetry.

## What progress means

Every catalog asset has five post-inventory stages: authored, UV reviewed,
native validated, game fixture validated and approved. Overall inventory progress
is the number of evidenced stages divided by five times the catalog size.
Discovery adds no completion credit. The percentage measures recorded inventory
work, not elapsed effort or the fraction of the visible world replaced. The
catalog includes shared materials, retained geometry, support maps and placeholders;
its replacement scope may be refined as the project develops.

Stages are independent. A game fixture does not approve artwork. Retaining an
original mesh does not make it an authored model or prove native mesh streaming.
An unchecked stage means no matching completion evidence, not necessarily a
failed test. Names can repeat; checkmarks belong to exact `CAB:path_id` strings.

Biome checkpoints are separate. `assets/status/roadmap.json` records planned,
active and approved biomes and explicitly mapped asset IDs. Meadows currently
contains a pilot scope. It is not a complete biome inventory. Shared assets may
belong to several biome scopes, but count once in the overall inventory.
A biome approval requires all scoped assets to be approved and a reviewed,
hash-pinned record covering complete scope, world visuals, weather and LOD,
performance, and final art approval.

The project milestones cover the overhaul as a whole: art direction, a playable
Meadows scene, biome expansion, structures and creatures, lighting and weather,
streaming and performance, installer compatibility, and the public alpha.
They are maintained in `status-site/data/project.json`. Individual successful
fixtures remain in the validation ledger and evidence summaries.

## Inventory previews and biome controls

The inventory supports exact-scope biome filtering and biome sorting in journey
order. Shared entries can appear in several biome filters, but appear once in
the full inventory. Unassigned entries have no recorded biome mapping.

Each row and detail panel provides before and after previews. Missing originals
and unfinished replacements remain explicit. Preview availability does not add
a validation stage. See [comparison publication](TRACKER_PREVIEWS.md) for rights,
bounds, the authored preview recipe and contributor checks.

## Contributor files

| File | Purpose |
| --- | --- |
| `assets/status/catalog.json` | Portable metadata only, no completion flags or game payloads. |
| `assets/status/manifest.json` | Pinned input hashes, exact evidence targets and claimed stages. |
| `assets/status/roadmap.json` | Explicit biome scopes and separate approval records. |
| `assets/provenance.json` | Authored file hashes, credits, license and ownership declarations. |
| `docs/evidence/` | Public validation summaries and contribution reviews. |
| `status-site/` | Webpage, derived inventory, evidence pages and tests. |

The catalog retains IDs, kind, friendly and serialized names, estimated category,
texture dimensions and project-relative `Assets/...` identity paths. It contains
no original pixels, geometry, UV buffers, resource streams, machine paths or save
data. The original extraction is not needed for contributor checks.

## Updating progress in a pull request

1. Choose a bounded asset or feature and discuss its scope in an issue. Read
   [CONTRIBUTING.md](../CONTRIBUTING.md) and the art direction first.
2. Add original artwork or code, public provenance and the relevant checks.
   For new review records, use `docs/evidence/contributions/` and the supported
   contribution schema. Link exact target IDs and keep unperformed stages absent.
3. Add the evidence path and SHA-256 to the manifest. List each exact asset and
   its supported stages. Review changed evidence before replacing a pinned hash.
4. Update the pinned UTC timestamp. A catalog change also requires review of its
   identity mapping and a new `catalog_sha256`. Preserve the original inventory
   hash as the extraction identity, not as a hash of the public catalog.
5. Refresh and verify the tracker, then commit both the source records and outputs:

```sh
python tools/refresh_tracker.py
python tools/refresh_tracker.py --check
python tools/check_public_content.py
python tools/check_comparisons.py --check
npm ci --prefix status-site
npm test --prefix status-site
GITHUB_PAGES=true npm run build --prefix status-site
```

`tools/prepare_status_site.py` is the inventory-only helper.
`tools/refresh_tracker.py` also validates the roadmap and refreshes evidence pages.
Check mode compares expected files without rewriting them. Outputs are stable
for identical source bytes and the pinned timestamp.

CI checks source privacy, authored hashes, regression tests, exact stage claims,
biome approval gates, snapshot freshness and the static build. It does not judge
art quality or grant approval. Maintainer review is required for progress claims.
Opening a PR does not change the live tracker. After the reviewed change merges
to `main` and verification succeeds, GitHub Actions publishes that tested revision.

## Evidence and deployment

Known fixture summaries use bounded adapters. New contribution records must
match the supported schema, use hash-verified project artwork and contain real
check results. The exporter escapes text, validates source hashes and writes
standalone summaries. It never copies raw extraction data or original images.
See [the contribution evidence schema](CONTRIBUTION_EVIDENCE.md) for an example.

The React/Vite static site is exported to `status-site/dist/client`, using the
`/valheim-impact` base path. The Pages workflow publishes only that directory.
The deployment uses no game files, user credentials or application database.
The repository is the source of truth for future updates.
