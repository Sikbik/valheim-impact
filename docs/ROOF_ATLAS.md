# Authored 67-degree roof atlas

The first roof replacement fits existing authored thatch and timber artwork to
`wood_roof_mat` and its original `wood_roof_d` layout. This material belongs to
the 67-degree roof family. Default and 45-degree roofs use separate straw and
alpha-fringe materials, so this atlas does not establish their coverage.

## Layout and provenance

The original 128 by 128 atlas is fully opaque. Its thatch fibers run vertically
and timber grain runs horizontally. Across eight selected meshes, 1,274 triangles
and 3,822 face corners stay within unit UV space. No selected triangle spans the
two material regions.

| Surface | Measured U range | Measured V range | Fitted 1024px rectangle |
| --- | --- | --- | --- |
| Thatch | 0.016226 to 0.362706 | 0.157064 to 0.962100 | `(0, 0, 384, 1024)` |
| Timber | 0.664012 to 0.985213 | 0.026597 to 0.966416 | `(384, 0, 1024, 1024)` |

Rectangles use top-down, half-open image coordinates. The 3/8 split is a fitting
choice within the unused UV gap, not a recovered hard edge from the original
authoring file. Lower mips sample broader neighborhoods than these base UVs.

`tools/fit_roof_atlas.py` verifies authored source hashes against provenance,
scales each region uniformly, crops it centrally, and makes its own edges
periodic. It does not blend the atlas's opposite outer edges across different
materials. It rejects uncovered or overlapping regions, transparency, unbounded
dimensions, and output aliases of inputs or metadata. Ten tests exercise layout,
orientation, opacity, deterministic fitting, provenance and protected outputs.

The resulting [authored atlas](../assets/meadows/roof-atlas-v1.png) is 1024 by
1024 with alpha 255 everywhere. Its source recipes and hashes are tracked in
`assets/meadows/roof-atlas-layout.json` and `assets/provenance.json`. No original
game pixels enter the composition or package.

## Local UV comparison

The full 67-degree roof, high-detail inner corner and inner-corner LOD were
compared at 3840 by 2160 in Blender. All 942 selected face corners retained UV0
within 5e-10. In this isolated view, authored thatch stays on roof planes and
timber on trim without visible boundary contamination or alpha holes.

The review isolates the atlas submesh because unrelated panels obscured it from
the initial camera. It is not an assembled-building comparison. The render uses
Blender lighting and base-level Closest/Repeat sampling; native mip behavior and
shader appearance require separate checks. Existing scenes and objects were
preserved. [Compact evidence](evidence/roof-uv-review.json) records hashes, scope
and limitations; original-containing renders and meshes remain under `local/`.

## Native texture validation

The atlas albedo has 11 BC3 mips and a 1,398,128-byte compressed payload. Its
neutral normal probe is also staged, but the game mapping changes only `_MainTex`
and preserves the original normal atlas. The complete development set contains
22 textures, 216 decoded mips and 12,933,024 bytes of BC3 payload. These numbers
describe assets, not total VRAM usage.

Unity 6000.0.75f1 built and read back each bundle on Vulkan with Linear color.
All 22 GPU base-mip readbacks agree with independent decoding within the stated
tolerance. Serialized textures retain full mips and are not CPU-readable.
See [native evidence](evidence/native-validation.json).

## Material slots and remaining scope

The high-detail inner corner assigns this atlas to slot 1; its LOD and the other
six selected meshes use slot 0. Production discovery now preflights and reads
up to eight shared material slots within its existing work budget. Oversized or
unsupported renderers retain first-slot coverage. The 24-check native fixture
verifies shared loading, both-slot restoration, bounded discovery, fallback and
acknowledged cleanup. See [runtime evidence](evidence/material-binding-native.json).

Default and 45-degree roofs use `woodwall`, `straw_roof`, `straw_roof_alpha` and
some corner-specific alpha materials. Their timber can use the existing wall
mapping; their straw and alpha fringes need separate fitting and shader checks.
Weather, distance transitions, a placed building, final art approval and the
6 GB hardware target remain unmeasured.

The next family has now been inspected locally: `straw_roof` and
`straw_roof_corner` are 64px whole-image tiles with graded alpha. Roughly 60% of
their texels pass the saved fringe cutoff of 0.69. A material-scoped replacement
of opaque `straw_roof` would leave sibling fringe materials untouched; it would
be only a partial visual update. A coherent replacement needs separate authored
standard and corner silhouettes, plus cutoff and mip-coverage checks.
[Layout metadata](evidence/default-roof-layout.json) records the next fitting
inputs without copying original imagery or masks into source.

The complete 67-degree roof mesh was subsequently checked in the guarded game
menu, from both sides. All submeshes and the companion `straw_roof_alpha` clone
remained intact. The selected atlas visibly changed, but the original cutout
layer still covers much of its top face. This confirms the remaining visual gap
rather than completing roof art. See [MENU_VALIDATION.md](MENU_VALIDATION.md).

An original standard-fringe candidate is now authored and fitted, with an
explicit derived-alpha mask and measured mip limitations. It remains unbound in
the installed game. [STRAW_FRINGE.md](STRAW_FRINGE.md) records the artwork, precise
material scope, staged cutout support, and remaining checks.
