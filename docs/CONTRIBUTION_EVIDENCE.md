# Contribution evidence schema

New asset reviews live in `docs/evidence/contributions/<review-name>.json`.
Use a descriptive lowercase filename. The following example uses the current
granite source to illustrate the contract. It is documentation, not an additional
approval. Replace it with the exact targets, files and checks for your own work.

```json
{
  "schema_version": 1,
  "kind": "asset-review",
  "targets": [
    {
      "asset_id": "CAB-8923bd833c4171316cf3c761b642c1c8:3915711535683601241",
      "stages": [
        "authored"
      ]
    }
  ],
  "checks": [
    {
      "name": "Source file identity and actual dimensions reviewed",
      "passed": true
    }
  ],
  "artifacts": [
    {
      "path": "assets/meadows/granite-surface-v1.png",
      "sha256": "49d76e5071066c821d45a0e4bf49584d63ccefa25172972bfc1e8b1a7b249df4"
    }
  ]
}
```

The manifest record supplies a unique review ID, this document's path and
SHA-256, a short public title, a scope description, and **the identical target
and stage pairs**. Its `targets` must match the review exactly. Any completion
claim requires at least one real, passing check. An authored claim also requires
a hash-verified artifact in the project's provenance registry. The source file
must be present, regular, bounded in size and owned for redistribution.

Stages are `authored`, `uv_reviewed`, `native_validated`,
`game_fixture_validated` and `approved`. Keep failed checks in a reference-only
record with empty stage arrays; a failed check cannot support a completion claim.
Human review decides whether the evidence is sufficient. CI checks consistency,
not visual quality or reviewer authority.

## Biome reviews

A biome review uses the same fields with `kind: "biome-review"`, plus `biome_id`
and a `gates` object containing these exact boolean keys:

```json
{
  "scope_complete": false,
  "world_visual_review": false,
  "weather_and_lod": false,
  "performance_review": false,
  "final_art_approval": false
}
```

Use one of `meadows`, `black-forest`, `swamp`, `mountains`, `plains`, `mistlands`,
`ashlands`, `deep-north` or `ocean`. Approval requires a nonempty, exact match to
the biome's declared asset scope, explicit final approval for every scoped asset,
all five gates true and passing recorded checks. Add the review's manifest ID to
that biome's `approval_evidence`. An active or planned biome cannot carry an
approval record. A retained original mesh may receive a scoped appearance approval
without being marked as an authored model.

## Limits and publishing

Use concise public check names without private paths, personal identities or
HTML. Checks use real JSON booleans, never strings. Do not add undocumented fields.
Lists and files are bounded; split large reviews into coherent asset families.
Do not include raw captures, extracted pixels, geometry or payload streams.

Run `python tools/refresh_tracker.py` and its `--check` mode before submitting.
The PR must include regenerated inventory, summary, roadmap and evidence pages.
A merged reviewed update appears on the live tracker only after repository
verification and the GitHub Pages deployment succeed.
