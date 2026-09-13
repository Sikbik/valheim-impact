# Dandelion material candidates

Two fitted albedos replace the flower head, leaves and stems on the retained
dandelion mesh. The HD candidate is 512px and Balanced is 256px. They are
original authored artwork, with yellow petal groups, serrated green leaves and
an opaque stem strip. See the [fitting recipe](../assets/meadows/dandelion-recipe.json).

## Exact shared scope

All IDs below use prefix `CAB-8923bd833c4171316cf3c761b642c1c8:`.
Texture `-4286054824775633638` (`Dandelion`) is a 32px albedo. Material
`-8929892379601486267` uses the original Standard shader with cutout mode 1,
cutoff approximately 0.14, queue 2450, white tint and no normal-map texture.
Mesh `-2264560222537116440` (`Dandelion02`) has 150 vertices and 136 triangles
in one material slot. Its two heads, five leaves and two stems use separate
regions of the atlas, with explicit front and rear faces.

The same material appears on seven consumers: the pickable plant, inventory
item, a trophy item and its two mounted forms, and two creature attachment
forms. Their rest transforms include scales 1.2, 1 and approximately 0.895.
The replacement therefore has shared scope beyond a single Meadows plant.
No model replacement or animated-pose approval follows from this mapping.

The source sampler clamps. A stem UV extends slightly beyond V=1, so both
authored recipes explicitly use `wrap_mode: clamp`. The stem's root samples the
top of the PNG, opposite the leaf's root-to-tip orientation. The fitting helper
reverses an owned leaf-midrib color profile for that strip.

## Reproduce the artwork

With `requirements-assets.txt` installed, run:

```sh
python tools/fit_dandelion.py --output-dir build/dandelion-reproduction
```

The helper checks both parent hashes and reproduces the exact 512px and 256px
PNG hashes before writing either result. It removes only tiny detached alpha
components from the owned sources, fits the two shapes into their UV regions,
and pads their transparent RGB borders. It does not read original game pixels,
masks or geometry. Its fixed placement constants record the earlier retained-UV
review. The recipe pins the helper hash and dependency manifest separately from
that private review.

Exact PNG reproduction uses Pillow 12.3.0 and zlib 1.3.2, with RGBA8 encoding,
compression level 6 and optimization disabled. The verified files contain only
IHDR, IDAT and IEND chunks. RGB is staged as sRGB albedo and alpha controls
cutout coverage. The recipe records these encoding settings and the numerical
library versions.

A cutoff-preserving alpha ramp makes the shape interiors opaque. The stem
strip has mip-aligned gutters outside the sampled stem region. These choices
resolve measured BC3 coverage errors without changing pipeline mip algorithms
or validation tolerances. The 256px output includes its own ramp after resizing;
a plain resize of the 512px source is a different candidate.

## Current evidence and limits

Both complete chains pass independent BC3 decoding, native bundle sampling and
serialized Clamp checks. Together they contain 19 mip levels and 436,960 bytes
of compressed payload. These figures are not measured VRAM residency or frame
times. No unused companion normal is emitted.

The CPU UV study compares original, HD and Balanced from both sides across all
seven consumer transforms, producing 42 images at 480 by 480. The two heads,
five leaves and two stems stay in their intended regions. Original geometry,
UVs, normals and tangents are retained, and the raw comparison captures remain
private inspection inputs.

The [finite native material fixture](evidence/dandelion-native-material.json)
passes 72 comparison captures across six exact rest-transform cases, covering
all seven consumers. Each case includes original, HD and Balanced from front
and rear at 1920 by 1080 and 3840 by 2160. Only the two identical creature
attachment matrices share a case. All six runs report zero errors or warnings
and preserve scenes and render globals after owned-object cleanup.

The independent pickable review covers three full frames and scaled crops of
all twelve pickable captures. Flower heads, serrated leaves and stems stay in
their intended atlas regions. The upper head retains the original planar card
tilt, which looks flat near an edge-on angle. Other cases have complete technical
checks, without an independent visual approval recorded here.

The fixture reads linear HDR pixels before saving, and 48 of the 72 frames
contain RGB values above one. PNG encoding clamps those highlights without tone
mapping. Bright petal color and material response therefore still need a final
lighting review. The orthographic camera has a one-unit vertical span. These
are close material views; changing capture resolution is not a distance test.

Head-region texel centers retain passing alpha through the 8px mip. The 4px
and 2px levels lose head coverage, and the single-texel tail is transparent.
These region measurements do not predict actual fractional-LOD visibility by
themselves. Native distance transitions, animated attachments, weather, placed-world
consistency and final art approval remain separate gates.
