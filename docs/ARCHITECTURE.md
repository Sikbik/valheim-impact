# Architecture

The runtime separates file validation and ownership policy from Unity object
lifecycle. Authored textures are built into native Unity AssetBundles and bound
to explicitly selected game materials. Existing shaders and companion channels
are retained.

## Components

| Component | Responsibility |
| --- | --- |
| `src/ValheimImpact.Core/` | Manifest validation, content identity, scheduling, leases, and restoration policy without Unity dependencies. |
| `src/ValheimImpact.Unity/` | BepInEx entry point, scene discovery, native async loading, material assignment, and acknowledged destruction. |
| `assets/` | Distributable artwork, provenance, binding metadata, and public status records. |
| `tools/` | Asset processing, builds, validation, packaging, and local inspection. |
| `unity/` | Matching Editor project and authored AssetBundle build entry point. |
| `installer/` | Package validation, previews, ownership receipts, local transactions, rollback, and recovery. |
| `tests/` | Synthetic Python and engine-independent C# regression fixtures. |
| `status-site/` | Public tracker presentation from reviewed metadata and evidence. |

## Data flow

1. Source artwork and public provenance feed deterministic fitting, mip
   generation, and compression. Local staging records the resulting hashes.
2. A matching Unity Editor builds owned native textures and records native
   readback evidence in a catalog.
3. Packaging validates source provenance, staged payloads, native bundle hashes,
   and optional exact binding rules. It includes only declared owned files.
4. The installer previews changes and writes an owned profile when applied.
5. A worker validates the enabled profile, catalog, rules, and referenced bundle
   files once. Unity calls stay on the engine thread.
6. Bounded scene discovery acquires demand leases for eligible materials. Async
   bundle and asset requests prepare a single owned texture for shared demand.
7. Adoption rechecks the material. A valid assignment retains its lease until
   restoration or loss of ownership. Destruction remains accounted for until
   Unity acknowledges that the object is gone.

## Binding and lifecycle invariants

Matching uses exact material name, shader name, property, original texture name,
and original dimensions. Only `_MainTex` albedo replacement is supported by the
current package contract. Schema 1 is opaque-only. Schema 2 adds an explicit,
constrained cutout state for `Custom/Piece`; it does not enable arbitrary blended
materials.

The binder captures the original texture object, shader object, and texture
scale/offset. It changes only the selected texture. Failed or pending loads keep
the original visible. Foreign texture or material-state changes end demand and
are not overwritten. Eligibility is rechecked while loading and while applied.

Scene transitions and disabling stop discovery, restore owned assignments, and
drain requests. A persistent host survives plugin disable long enough to finish
that work. Process exit restores assignments while Unity is available, but is
not reported as a completed asynchronous drain. Dynamic assembly or host removal
before drain is unsupported.

Discovery has fixed work and collection limits. A cached scalar material-count
capability permits up to eight shared slots without first allocating an array.
Missing capability or larger renderers fall back to the first shared slot.
Shared materials are deduplicated. Incomplete scene censuses are recorded, so
bounded discovery must not be represented as exhaustive game coverage.

## Public progress data

`assets/status/catalog.json` contains sanitized asset identities.
`assets/status/manifest.json` maps exact IDs and stages to evidence.
`assets/status/roadmap.json` records independent biome checkpoints.
`tools/prepare_status_site.py` validates evidence hashes and prepares snapshots
without game files; `--check` detects stale generated data.

Opening or merging a code-only pull request does not complete an asset stage.
Only reviewed evidence can support stage changes. Inventory progress counts
post-inventory stages separately from biome approval. See
[status tracking](STATUS_TRACKING.md).

## Validation boundaries

Synthetic tests establish policy behavior. Native fixtures establish the
specific engine lifecycle or sampling behavior they exercise. A guarded game
menu fixture establishes only its selected loaded material and mesh pairs.
World traversal, weather, LODs, model and shader streaming, and representative
memory/frame-time measurements need separate evidence.

Queue and payload budgets are component limits. They are not total VRAM or RAM
limits and do not validate the 6 GB VRAM / 16 GB RAM / 1080p Balanced target or
the crisp 4K presentation requirement.
