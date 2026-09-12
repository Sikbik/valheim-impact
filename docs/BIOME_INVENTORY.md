# Biome inventory membership

Biome browsing covers assets associated with game configuration, including
untouched artwork. It uses a separate input from the Meadows review pilot and
biome approval checkpoints. An inventory association adds no authored, UV,
native, game-fixture or approval stage.

## Mapping sources

The source records in `assets/status/biome-membership.json` identify configured
vegetation, clutter, locations and spawn associations. A record links a serialized
component and list entry to one or more explicit biome flags. Prefab references
resolve through exact object pointers or asset IDs in the game manifests.
Transform ancestry connects prefabs to renderers; renderer mesh references and
material texture properties connect them to exact catalog identities.

Configured disabled content is included because this is an inventory of potential
work, not a report of what currently spawns. Ordinary spawn lists resolve through
the zone controller's exact references. Event and alternate-biome spawn lists
describe their particular configurations. They do not establish a creature's
usual home biome. The existing Meadows review pilot also supplies a separate,
explicit membership record for its known targets.

Shared textures and meshes can participate in several biomes. They appear in
each matching filter and only once in the overall inventory. The table compacts
long shared lists; open an entry to see its full biome membership. Source and
configuration coverage is partial. Missing references, general player assets,
unused geometry and other entries without a recorded association remain
Unassigned. No membership is inferred from a repeated asset name.

The [discovery record](evidence/biome-inventory-discovery.json) records input
hashes, configured and joined rows, disabled content and unresolved references.
The inspected bundles covered by the prior inventory were checked against its
pinned digests. Additional location bundles from the regular game manifest have
separate recorded hashes. Original textures, geometry and game data files remain
local.

## Refresh from a local installation

With the inspection dependencies installed and a complete immutable inventory,
run the read-only extractor from the repository root:

```sh
python tools/inspect_biome_membership.py \
  --inventory local/texture-inventory/complete/inventory.json \
  --output local/biome-inventory
```

The inventory supplies the installation path; `--game` can specify another
installation with matching bundle bytes. Outputs must stay under `local/` and
outside the game installation. The extractor retains serialized bundle readers
and hierarchy metadata until exit, so inspection memory scales with its inputs.
It does not decode texture pixels or mesh vertex buffers.

Review `configured-associations.json`, `counts.json` and unresolved references
before promoting `membership-sources.json` into the public source. Preserve
separately reviewed associations, such as the Meadows pilot, and retain the
sanitized input hashes and limitations in the discovery record. Direct component
and descendant renderer references are covered; arbitrary gameplay prefab links
and item-drop relationships are not recursively classified.

## Public contract and workflow

The source file has `schema_version`, `catalog_sha256`, `inventory_sha256`,
`scope` and `sources`. Each source has exactly `id`, `kind`, `label`, `biomes` and
`asset_ids`. Use exact catalog IDs, unique source IDs, existing biome IDs, and a
concise description of the actual association. Retain the original extraction
identity when updating the portable catalog. Do not use this file to record
completion flags or to expand review approvals.

After reviewing new associations, run:

```sh
python tools/prepare_biome_inventory.py
python tools/prepare_biome_inventory.py --check
python tools/refresh_tracker.py --check
npm test --prefix status-site
GITHUB_PAGES=true npm run build --prefix status-site
```

The portable helper requires no game installation. It validates the source and
catalog, deduplicates membership and writes `status-site/public/data/biomes.json`
and the small `status-site/data/biome-summary.json` descriptor. The application
checks their matching hashes when loading. Include both generated files and the
reviewed source in the pull request. Review-progress files remain unchanged
unless separate evidence supports a progress update.
