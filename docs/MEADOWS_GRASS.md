# Meadows grass candidates

Tall and short Meadows grass now have original neutral-white cutouts fitted to
the retained grass cards. Each has an HD and a smaller Balanced candidate.
These are material studies, with actual game integration and final appearance
kept as separate acceptance work.

## Exact scope

All serialized identities in this table belong to
`CAB-8923bd833c4171316cf3c761b642c1c8`.

| Variant | Material path ID | Albedo path ID | HD / Balanced |
| --- | --- | --- | --- |
| Tall | `1669900682560515117` | `-6685763419340257079` | 512px / 256px |
| Short | `2753016777081159198` | `8723292681815040943` | 256px / 128px |

Both materials use `Custom/Grass`, cutoff approximately 0.46 and shared terrain
color texture `5952445177512870087`. The original visible albedo RGB is white.
Inspection of the compiled GLCore fragment shows multiplication by terrain
color at world XZ coordinates. A green-painted replacement would therefore tint
the terrain color twice. The new files retain white RGB, including transparent
pixels, and carry their authored silhouettes in alpha.

Both use mesh `2397346978479642237`: 48 vertices, 36 triangles and six bent
crossed cards. Each card samples nearly the whole square, with roots at the
bottom. No atlas packing, original-mask transfer or UV edits are used. Tall
instance component scale is `(1.5, 2, 1.5)`; short scale is `(1.2, 1.2, 1.2)`.
Placed instances apply additional scale and rotation.

The prefabs draw through `InstanceRenderer` and `Graphics.DrawMeshInstanced`.
They do not appear as ordinary MeshRenderer material slots. Runtime discovery
now has an explicit schema-3 observer for this instanced path, with the finite
ownership evidence described below. Actual gameplay discovery remains untested.
The shared terrain-color texture and other grass materials remain outside this
replacement scope. Neither material has a normal-map texture, so these four
studies emit albedo only.

## Artwork and fitting

The two public grayscale masks are original authored silhouette sources. Their
sample values are alpha, although the mask files themselves are opaque L images.
The [tall recipe](../assets/meadows/grass-tall-recipe.json) uses those samples
directly. The [short recipe](../assets/meadows/grass-short-recipe.json) thickens
each of five separate authored blades around its row center and reduces the
sideways bend. This avoids exaggerated curling on the wide, low grass cards.
Both recipes record exact parents, interpolation and output hashes.

The selected source coverage at cutoff 0.46 is about 11.15% for tall grass and
6.71% for short grass. The originals measure 9.48% and 6.76%, respectively.
These area fractions describe texture masks, not screen coverage or rendering
cost. Original game images and geometry remain private inspection inputs.

## Validation and remaining work

The finite UV review compares original, HD and Balanced cutouts from both sides
on the exact retained card geometry. Grass color is held constant in this unlit
view. It establishes UV placement and silhouette readability, not the original
shader, wind, lighting or a playable world.

A separate [native shader fixture](evidence/meadows-grass-native-shader.json)
renders the HD candidates through the exact original `Custom/Grass` materials
with `Graphics.DrawMeshInstanced`. Eight matched original/authored captures at
1920 by 1080 and 3840 by 2160 pass finite-output checks on Vulkan in Linear color.
The fixture preserves terrain-color input, source normals and tangents, camera,
instance transforms and world coordinates. Wind strength is frozen at zero.
Owned objects are destroyed and Editor scenes and globals are restored, with
no warnings or errors. Balanced sizes have native payload and diagnostic mip
evidence, but were not rendered in this original-shader fixture.

Complete BC3 chains require 349,552 bytes at 512px, 87,408 bytes at 256px and
21,872 bytes at 128px. All four grass albedos total 546,240 compressed payload
bytes. These are payload sizes, not measured VRAM residency or frame times.

The tall 32px mip exposed a compression problem: source alpha near the cutoff
fell below it after BC3 encoding. A bounded uniform-scale fallback evaluates
decoded coverage within the existing validation tolerance. It preserves zero
alpha and keeps equal input alpha values equal, without drawing a spatial mask.
The resulting coarse coverage is higher than the base coverage, and the smallest
mips still lose silhouettes. Passing the payload checks does not approve those
distance transitions.

A separate [native ownership fixture](evidence/meadows-grass-binding.json) passes
19 checks using the original material copies, production binder/observer code,
inert components and a diagnostic texture provider. It covers shared demand,
readiness, reassignment, incomplete discovery, foreign changes and restoration.
All fixture objects drain and cleanup passes without warnings or errors. The
observer allocates zero managed bytes across 512 warmed scans of its test node;
this excludes hierarchy allocation and makes no frame-time claim.

The [runtime guide](RUNTIME.md) describes schema 3 and its explicit limits.
These changes add no default grass mapping or game deployment. Production
authored-bundle loading through this instanced path still needs its own fixture.

Review actual gameplay discovery and rollback, original shader behavior on
supported graphics APIs, both faces under light, wind, player interaction,
terrain tint, fade distances 20 to 35, weather and representative hardware.
The quality presets remain candidates until those checks are complete.
