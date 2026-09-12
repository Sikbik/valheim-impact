# Beech material candidates

This batch adds a shared authored branch source, 1024px and 512px foliage
payloads, and a 1024px bark atlas fitted to the near and middle large-tree
meshes. These are staged material candidates. No beech runtime binding or final
art approval is included.

## Exact scope

All identities below belong to serialized file
`CAB-8923bd833c4171316cf3c761b642c1c8`.

| Original albedo path ID | Candidate | Recorded review |
| --- | --- | --- |
| `-3647773947989605833` | `beech_branch_hd_albedo`, 1024px | Leaf slot 0 on the three large-tree blob meshes, front and rear; native texture and diagnostic cutout sampling. |
| `-5355041863167301984` | `beech_branch_balanced_albedo`, 512px | Leaf slot 0 on two small-tree blobs, the sapling and one imported model, using white tint; native texture and diagnostic cutout sampling. |
| `-7789706379099817400` | `beech_bark_near_hd_albedo`, 1024px | Bark slot 1 on near and middle large-tree meshes, including underside caps; native texture sampling. |

The [layout evidence](evidence/beech-material-layout.json) records exact
material slots, hierarchy joins and shared scope. The [UV review](evidence/beech-material-uv.json)
records 5,376 imported face corners with zero measured UV error across seven
retained meshes, plus hashes of the local front, rear and close views.
Original geometry and full original images remain outside the public source.
These checks do not establish authored models or native mesh streaming.

## Reproduce the authored inputs

The public branch RGB source has a neutral working background. Its transparency
is estimated from authored color variation, not recovered source alpha or an
original game mask. Reproduce the RGBA candidate with:

```sh
python tools/key_authored_foliage.py assets/meadows/beech-branch-source-rgb-v1.png \
  --sha256 2587c46cbf69bfec2592bff1240fddb203af792f6c58b967094c25496818a02f \
  --output local/beech-review/branch.png \
  --report local/beech-review/branch.json
```

The chroma score is the maximum RGB channel minus the minimum. Values at or
below 10 become transparent; values at or above 32 become opaque. Smoothstep
interpolation provides partial edges. Nearest confident authored colors pad
transparent and partial pixels before filtering. Neutral foreground can be
removed by this method, so review the result visually before accepting another
source. The selected 1254px source has 23.68% coverage at cutoff 0.5 and empty
outer edges. No crop or UV repacking is applied to either foliage size.

The [bark recipe](../assets/meadows/beech-bark-near-recipe.json) combines the
owned bark and endgrain sources. It places a 95px square endgrain patch in the
1024px bark image at the measured near/middle cap region. The recipe records
source hashes, saturation, filter, placement and output hash. Its alpha is
fully opaque.

Run `python tools/asset_pipeline.py`, `python tools/validate_staging.py` and
the [native authoring workflow](UNITY_PIPELINE.md). For the finite cutout
fixture, run `CutoutSamplingProbe.Run("beech_branch_hd_albedo", 0.5f)` and
`CutoutSamplingProbe.Run("beech_branch_balanced_albedo", 0.5f)` in the matching
Editor, then validate each identity with `tools/validate_cutout_sampling.py`.
The fixture samples an owned diagnostic shader, not Valheim's vegetation shader.

## Resolution and sampling evidence

The complete BC3 albedo mip payload is 1,398,128 bytes at 1024px and 349,552 bytes
at 512px. Each paired normal study costs the same amount as its albedo. The
current native authoring fixture contains 32 textures totaling 20,622,848
compressed payload bytes, including previous studies. These figures describe
texture payloads, not measured residency, bundle overhead, frame time or a
whole-scene VRAM budget.

A matched 3840 by 2160 unlit view shows readable small-tree outlines and leaf
groups at 512px, with finer leaf and twig edges at 1024px. Both sizes remain
available for actual shader and distance review before assigning quality
presets. The foliage normal studies are flat and unmapped; they do not replace
the original leaf normals.

Unity 6000.0.75f1 on Vulkan in Linear color sampled all 11 HD and 10 Balanced
point mips, with 10 and 9 additional fractional diagnostics. Native color is
bounded against independent BC3 decoding. Binary masks are checked against the
separate native color captures, with one-byte uncertainty near the threshold;
sparse decoder-versus-mask disagreements are still counted and bounded. The
fixtures confirmed destruction of their owned textures, materials and bundles.

Coverage becomes coarse in small mips and reaches zero at the final 1x1 mip
for both candidates. Fractional sampling also loses coverage near the tail.
Passing sampling checks confirms payload interpretation, not acceptable distant
foliage. Actual screen-space coverage and LOD transitions remain unapproved.

## Remaining acceptance work

The near/middle endgrain patch overlaps 9,025 distant trunk texels. The distant
mesh therefore retains original bark in the review. Resolve this atlas conflict
before any shared bark binding; other bark consumers include stumps, logs and
small trees. The middle underside cap also stretches its endgrain with the
retained low-detail geometry.

Small-tree and healthy sapling materials store cutoff 0.5. The unhealthy sapling
stores cutoff 0.26, an orange tint and different ripple strength, which need a
separate material comparison. Stored blend values and invalid keywords do not
prove the shader's active rendering path. White-tint UV views do not approve
that unhealthy state.

Review companion normals and moss, two-sided lighting, wind, growth, weather,
actual alpha handling, all LOD transitions and representative hardware before
promoting this work to game or final approval. The roadmap and tracker keep
these gates separate from authored, scoped UV and native texture evidence.
