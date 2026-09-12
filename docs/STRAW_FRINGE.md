# Authored straw-fringe candidates

The Meadows pilot now has separate original 512 by 512 RGBA candidates for the standard and corner roof fringes. They preserve the two distinct silhouettes and target material-specific cutout bindings. Neither candidate replaces the opaque roof material that shares its source texture identity.

| Candidate | Material | Texture | Public asset | SHA-256 |
| --- | --- | --- | --- | --- |
| Standard | `straw_roof_alpha`, `CAB-8923bd833c4171316cf3c761b642c1c8:3815874719294672528` | `straw_roof`, `CAB-8923bd833c4171316cf3c761b642c1c8:7569662044289518567` | [`straw-fringe-standard-v1.png`](../assets/meadows/straw-fringe-standard-v1.png) | `a9b28e2316ecb886ed2a0f71d017723ae3679c1cf53a60b23c8db8f7ea6dd73c` |
| Corner | `straw_roof_corner_alpha`, `CAB-8923bd833c4171316cf3c761b642c1c8:-3672209594003148970` | `straw_roof_corner`, `CAB-8923bd833c4171316cf3c761b642c1c8:5625371641502064416` | [`straw-fringe-corner-v1.png`](../assets/meadows/straw-fringe-corner-v1.png) | `f49065a82ea0c5e1149a53f902da2aa9a380e5a2c72331bedb3a2f3832a63ec6` |

Both materials use `Custom/Piece`, cutout mode, a saved cutoff near 0.69, two-sided normals, unit texture transforms, and depth writes. The standard and corner normal maps remain separate companion channels.

## Authored alpha and mip processing

The standard source began as original RGB artwork. Its alpha is an authored color-key derivation, not recovered source transparency. The corner source is separate original RGBA artwork fitted to the corner silhouette. No game pixels or masks are present in either public asset.

The fitted standard candidate has 54.93% base texel coverage at cutoff 0.69. The corner candidate has 57.15%. Mip 0 remains byte-identical to each fitted candidate. Lower albedo mips retain linear-light, alpha-premultiplied RGB filtering. Alpha is then uniformly scaled per mip toward the nearest achievable authored base coverage. Corrected alpha never feeds the next filtering step, exact zero remains zero, and equal alpha values remain equal. The process does not create a per-texel pattern to force a requested count.

Small mips have unavoidable discrete coverage. The current standard and corner chains both retain two passing texels at 2 by 2 and one at 1 by 1 after BC3 decoding. The 1 by 1 alpha is held well above the cutoff to avoid fragile cutoff rounding in the final mip. Validation rejects complete compressed loss whenever an emitted mip has any passing texel.

The earlier [standard fitting report](evidence/straw-fringe-fit.json) and [corner fitting report](evidence/straw-fringe-corner-fit.json) describe the ordinary, uncorrected mip chains. Their reported 2 by 2 and 1 by 1 cutout loss is retained as historical evidence of the issue that prompted coverage-aware processing.

## Native sampling evidence

The [standard sampling report](evidence/straw_fringe_standard_albedo-sampling.json) and [corner sampling report](evidence/straw_fringe_corner_albedo-sampling.json) record successful Vulkan sampling of every BC3 mip at the saved cutoff. The standard base mip measured 54.91% native coverage and the corner base mip measured 57.11%. Their 2 by 2 mips measured 50%, and their 1 by 1 mips measured 100%. Point-sampled native masks agreed closely with the independent decoder.

Fractional trilinear diagnostics also retain visible alpha through the chain. At LOD 8.5, both candidates measured 100% coverage because interpolation ends at the single passing final texel. These measurements describe owned texture sampling in a linear-color Vulkan fixture. Texel coverage is not screen-space or whole-mesh coverage.

## Scoped UV review

The authored standard and corner fringes were compared on three exact roof meshes while preserving their UV0 data and companion material slots:

- `wood_roof_new`, `CAB-8923bd833c4171316cf3c761b642c1c8:-6155225557725131527`
- `wood_roof_45_new`, `CAB-8923bd833c4171316cf3c761b642c1c8:-7768300691103960695`
- `wood_roof_ocorner_45_new`, `CAB-8923bd833c4171316cf3c761b642c1c8:4913270748202539969`

Across 2,676 checked UV corners, paired geometry and UVs differed by at most `4.68688954313734e-09`. The top-facing review used base-level repeat sampling with backface culling disabled. Underside appearance still needs visual review. It supports the selected submesh mapping only. It does not establish assembled building appearance, lower LOD meshes, placement, weather behavior, or the actual game shader.

## Remaining validation

The candidates have authored-art, fitted-alpha, BC3, native texture-sampling, and scoped UV evidence. They have no actual game-shader rendering, deployment, placed-world review, weather review, LOD transition approval, or final art approval. Runtime binding and rollback remain separate from these texture and UV measurements.
