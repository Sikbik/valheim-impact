# Meadows asset plan

Use the Meadows to establish a coherent material palette and a repeatable
asset pipeline before expanding across the game. The
[lighting concept](../assets/concepts/meadows-lighting-v2.png) is a visual
hypothesis for daylight, sunset, and night. It is neither a game screenshot nor
a registered before/after comparison.

## Material families and current scope

| Family | Current authored work | Remaining review |
| --- | --- | --- |
| Stone | Dedicated 1024px albedo, selected mesh UV review, native checks, and a standing-stone menu fixture. | Shared moss/normal response, other rock geometry, weather, and broader biome scope. |
| Timber | Dedicated 1024px albedo, selected pole UV review, and a timber-pole menu fixture. | Wall coverage, other timber pieces, construction joins, LODs, and weather. |
| 67-degree roof atlas | 1024px atlas fitted to measured regions, selected submesh UV reviews, and a full-mesh menu fixture. | Original companion straw layer, placed buildings, oblique views, and LOD transitions. |
| Standard straw fringe | Original 512px RGBA candidate with measured alpha and uncompressed mips. | Coverage at small mips, repeat edges, compression, full-mesh UV review, native and game validation. |
| Corner straw fringe | Exact reference metadata and layout preparation. | Authored candidate and all replacement validation. |
| Grass, earth, leaves, and beech card | Palette and processing studies on owned probe geometry. | Exact production mappings, terrain semantics, atlas fitting, native game rendering, and world review. |

These descriptions are scoped to the recorded evidence. They are not counts of
visible game coverage. Consult the [tracker](https://sikbik.github.io/valheim-impact/)
for exact identities and stages before selecting a contribution.

## Studies and source files

`assets/meadows/prototype.json` selects the authored inputs and output sizes.
The six-material sheet is 1254 by 1254 with three columns and two rows. Explicit
418px square crops avoid stretching rectangular cells or taking neighboring
materials. Those studies produce 256px probe albedos.

The beech source is 1363 by 1154 RGBA. A square crop preserves the branch before
fitting to a 512px probe card. Its alpha comes from the authored image, not a game
mask. It is not a replacement for the game's leaf atlas.

Dedicated stone, timber, and thatch surface sources are fitted to 1024px without
upscaling. A continuous thatch tile is distinct from a fitted roof atlas and
from a cutout fringe. Do not substitute one for another based on similar names.

The paired normal studies use linear DXT5nm, with tangent X in alpha and Y in
green. Their mild slopes are derived material studies, not measured surface
heights. The beech probe normal is flat. Albedo alpha does not imply a roughness
or metallic mask.

Public per-file rights, credits, dimensions, and hashes belong in
[provenance](../assets/provenance.json) and
[attribution](../assets/ATTRIBUTION.md). Metadata-normalized source files retain
identical pixels; historical results keep their original file hashes and are
linked through the [normalization report](evidence/artwork-file-normalization.json).

## Prepare and review

Use the asset Python requirements, then run from the repository root:

```sh
python tools/asset_pipeline.py
python tools/validate_staging.py
```

The pipeline rejects linked or unsafe destinations before writing under
`build/staging/meadows/`. Albedo mips are filtered in linear light with
premultiplied alpha. Normal mips are renormalized. Tile edges are matched before
BC3 compression, which can still introduce edge differences requiring rendered
review.

Top-down DDS files support image inspection. Separate `-unity.dds` files store
each mip bottom-up for raw Unity ingestion. Do not feed preview payloads to the
native importer. Independent BC3 decoding checks every mip and records actual
alpha and error measurements. Those checks do not establish Unity sampling.

Run relevant asset tests and use [UNITY_PIPELINE.md](UNITY_PIPELINE.md) for
native validation. Original inspection inputs must stay local. Review exact
UVs, submeshes, material transforms, real alpha, companion channels, and
shared-material scope before proposing an allowlist addition.

## Resolution decisions

Choose resolution by visible improvement at matched viewing distances and
measured cost. Compare candidate resolutions with the same geometry, camera,
lighting, and shader. Preserve crisp 4K presentation while evaluating the
Balanced target of 6 GB VRAM, 16 GB RAM at 1080p. Neither a high-resolution source
nor compressed payload accounting proves those targets are met.
