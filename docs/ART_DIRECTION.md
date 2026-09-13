# Art direction

Build a painterly Viking world with smooth material separation, crisp
silhouettes, soft atmospheric depth, and expressive light. Preserve Valheim's
forms and handmade construction. This direction is a working art brief;
concepts and isolated material studies still need evaluation in the game.

## Materials and palette

Use broad, intentional color and value groups, with small detail where it
supports form and close-up readability. Keep texture noise restrained.

- Timber retains warm grain, knots, cuts, age, and visible construction joints.
- Stone uses readable planes, cool fissures, and restrained mineral variation.
- Thatch has directional bundles and uneven edges that remain legible at distance.
- Cloth, leather, metal, snow, and foliage each need distinct light response.

For the Meadows, explore warm green foliage, honey-brown timber, cool blue-gray
stone, and blue atmospheric distance. Coordinate albedo, normal strength, and
material response. An attractive albedo alone is not a finished material.

## Fit the asset

Inspect the exact texture and material identity before authoring a replacement.
Equal names can refer to different assets, and one material may appear on many
meshes or in more than one biome. Record the intended shared scope.

Preserve UV island placement, orientation, texture scale and offset, alpha
semantics, emissive alignment, and channel packing. Review every affected
submesh and material slot. Atlases need padding and mip-aware edge treatment;
tileable surfaces need seam checks. Do not infer UV correctness from a flat
preview or a filename.

Transparency must be actual image alpha, not a painted checkerboard. Inspect
the saved file's dimensions, channel values, and coverage at the intended
cutoff. Check thin shapes and cutout coverage through the mip chain and under
compression. Review both faces where the game material is double-sided.

Keep private inspection inputs separate from distributable artwork. Original
game textures, masks, extracted geometry, and third-party packs must not enter
a pull request or release. The tracker may include the authorized 192px
game-reference excerpts and reviewed landscape render comparisons described in
[tracker comparison previews](TRACKER_PREVIEWS.md). These game references and
mixed-content captures are excluded from the project artwork license and do not
permit publication of their full sources. Other public evidence can record
exact identities, hashes, dimensions and measured outcomes without
redistributing inspection inputs.

## Lighting and atmosphere

Explore warm sunlight, cool ambient shadows, softened shadow transitions,
subtle contact shading, and restrained rim light. Preserve night readability,
weather variation, and the mood of each biome. Water and terrain should share a
coherent palette across tiles, distance levels, and biome boundaries.

Color grading, bloom, outlines, and custom shaders are proposals until tested.
Global changes need evidence for interiors, dense foliage, combat, darkness,
and severe weather. The current albedo binding runtime does not implement a
coordinated lighting overhaul.

## Review scenes

Start with a consistent Meadows composition containing grass, bare earth, a
tree, a wood-and-thatch house, stone, a character for scale, and nearby water.
Compare daylight, sunset, and night. Include near and far views, oblique angles,
LOD changes, wet surfaces, and material transitions.

Use 1080p for the Balanced target and 4K captures to examine crisp presentation.
State the actual render dimensions. A 4K screenshot does not establish complete
4K quality, and a concept must always be labeled as a concept.

## Submitting artwork

Provide original files, a repeatable fitting recipe where applicable, exact
target IDs, and public per-file provenance with SHA-256 hashes. State the rights
and license for each file truthfully. Include material and mesh scope, UV and
alpha checks, and remaining limitations. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the submission checklist and staged
validation process.
