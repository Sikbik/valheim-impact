# Beech log material candidates

An original bark-and-endgrain atlas now fits the full and half beech logs.
The source is 1024px, with HD 1024px and Balanced 512px albedo candidates.
Their original geometry is retained. Companion normals, physics, world
appearance and final art approval remain separate work.

## Exact material scope

All identities below belong to `CAB-8923bd833c4171316cf3c761b642c1c8`.

| Role | Path ID |
| --- | --- |
| Original albedo, `beech_log` | `410654931012585407` |
| Original normal, `beech_log_n` | `8289421623877127654` |
| Material, `beech_log` | `2002271956048927406` |
| Retained mesh, `VerticalLog` | `-2626186852244817445` |

The material serves two renderers, `beech_log/log` and
`beech_log_half/PineTree_log (1)`. The mesh also serves 165 renderers using
other materials. Those consumers are outside this appearance review. Binding
must select the exact log material, not every object using this geometry.

The Standard material stores opaque mode, tint approximately 0.9632,
normal strength 1, zero glossiness and zero metallic value. Both texture
transforms are identity. Its original BC1 diffuse is opaque across all nine
stored mips. The original normal uses BC7 with directional X data in alpha;
that alpha is not transparency. The authored albedo does not copy either map.
An owned normal companion remains necessary before calling the material complete.

## Fit and reproduce

The 52-vertex mesh has 16 side triangles and two separate 24-triangle end
islands. Each end includes a bevel and a pointed center. The inherited shape
therefore stays slightly conical under the new endgrain; the texture does not
change the log silhouette.

The [fitting recipe](../assets/meadows/beech-log-recipe.json) maps the owned
beech bark across the exact side UV rectangle and blends its source edges
before wrapping them around the circumference. Two 148px endgrain patches
cover the separate cut islands. The [layout evidence](evidence/beech-log-layout.json)
records their positions, hashes and sampling limits.

Reproduce the source from the two public owned parents:

```sh
python tools/fit_beech_log.py --root . --output-dir build/beech-log-sources \
  --balanced-preview
```

The command rejects existing outputs and linked paths. Its recipe pins parent
and result hashes, numeric operations and encoder versions. The optional 512px
image is a fitting preview. Production payloads come from
`python tools/asset_pipeline.py` and the [native workflow](UNITY_PIPELINE.md).
Both prototype entries use `generate_normal: false`; no unused paired normal
study is packaged for this batch.

The full and half children use scales `(4, 4, 8)` and `(4, 4, 3.6)` with the
same UVs. Their bark detail therefore stretches differently along the log.
Both scales need visual comparison, including both end caps and the side seam.

The [native material comparison](evidence/beech-log-native-material.json)
records twelve matched frames on Unity 6000.0.75f1 with Vulkan and Linear
rendering. Both scales render before, HD and Balanced states at 1920x1080
and 3840x2160, with the side and both ends visible. The exact original Standard
material is cloned and only its albedo reference changes. All frame checks
passed with no shader errors or warnings, and scene and global state were
restored after cleanup.

Visual review confirms that the bark stays on the side and each ring pattern
lands on its own cut end. The original low-resolution normal still introduces
coarse shading beneath the new albedo. Some lit candidate pixels exceed one
in linear HDR and are clamped in the diagnostic PNGs, which use no tone mapping.
These controlled views support the scoped UV and native stages. They do not
settle lighting, companion-map quality or world appearance.

## Sampling and acceptance

The 1024px fit covers 10,147 texel centers on one end and 10,273 on the other.
Neither patch overlaps the side at that resolution, including a one-texel
margin. A finite bilinear side-seam diagnostic measures less than one RGB byte
of maximum difference across 1,024 longitudinal samples. These are fitting
measurements, not native seam or world approval.

The conservative one-texel margin reaches endgrain contribution at 16px mips;
the final 1px mip mixes the whole atlas. Inspect oblique filtering and distant
appearance before accepting either quality preset. The complete BC3 chains
cost 1,398,128 bytes at 1024px and 349,552 bytes at 512px. These describe
compressed payloads, not total residency or measured frame times.

Keep original normal detail only as an explicit matched comparison control.
It is not an approved companion for the new rings and bark. Review an authored
normal, roughness, lighting, wetness, rolling, ground contact and distance
transitions before material or biome approval. No original images, geometry,
normal data or game resource streams are included in the authored package.
