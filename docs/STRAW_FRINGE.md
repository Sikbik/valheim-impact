# Standard straw-fringe candidate

This original golden-straw candidate targets `straw_roof_alpha` with the
`Custom/Piece` shader and the shared `straw_roof` albedo. It is authored artwork,
not a deployed replacement. The opaque material sharing that texture and the
separate corner fringe are outside this candidate's scope.

The exact target texture is
`CAB-8923bd833c4171316cf3c761b642c1c8:7569662044289518567` and the target material
is `CAB-8923bd833c4171316cf3c761b642c1c8:3815874719294672528`.
The original texture dimensions are 64 by 64. See the
[authored-candidate record](evidence/straw-fringe-authored.json) for scoped stage
flags. Matching a name alone is not sufficient to extend this mapping.

## Source and derived alpha

The retained source image is 1254px square RGB with a painted neutral
background. It has no alpha channel and is not a usable cutout on its own.
The transparent candidate is a separate derivation from the project's own
artwork, with public provenance and hashes. It uses no original game pixels
or masks.

`tools/key_authored_straw.py` separates warm straw from the neutral background
using `min(R-B, 2*(G-B))`, byte thresholds 8 and 64, and smoothstep alpha.
Uncertain and transparent pixels take RGB from the nearest confident straw
pixel. This estimates a new mask; it does not recover missing transparency.
It can remove neutral fibers or borrow neighboring strand colors at thin tips.

The derived RGBA has alpha from 0 through 255 and 55.26% coverage at cutoff
0.69. Dark and light composites were reviewed as flat images. That review does
not establish mesh alignment, halo-free native sampling, or shader approval.
The [derivation report](evidence/straw-fringe-key.json) records the thresholds,
source hash, gaps, and edge uncertainty.

## Fitting and current limitation

`tools/fit_straw_fringe.py` requires real RGBA with an exact authored provenance
record. It fits the whole image to 512 by 512 using alpha-weighted linear RGB
and averaged alpha, preserving axes. RGB, unusable alpha, mismatched provenance,
modified input, links, and aliases of protected inputs are rejected.

The [512px candidate](../assets/meadows/straw-fringe-standard-v1.png) has 54.93%
base coverage at cutoff 0.69. Its SHA-256 is
`a9b28e2316ecb886ed2a0f71d017723ae3679c1cf53a60b23c8db8f7ea6dd73c`.
The original scalar reference is 59.72%; that measurement is diagnostic and is
not used to reshape the authored mask.

All ten uncompressed mip levels are measured in the
[fitting report](evidence/straw-fringe-fit.json). The 2 by 2 and 1 by 1 levels
have zero pixels above cutoff. Coverage preservation, repeat edges, BC3 edge
behavior, full roof UV placement, two-sided shading, and actual-game appearance
still need work. No native bundle or active binding has been created for this
candidate as part of the recorded cutout milestone.

## Reproduce the processing

Use the asset Python environment from the repository root:

```sh
python tools/key_authored_straw.py assets/meadows/straw-fringe-source-rgb-v1.png --sha256 7322cb1b76c54f5c1e953fac5f62ad1650c4aedc828c6fb6dc0b12b18165509b
python tools/fit_straw_fringe.py assets/meadows/straw-fringe-standard-recipe.json
python -m unittest tests.test_straw_key tests.test_straw_fringe
```

The source hash above identifies the current public PNG. The
[normalization report](evidence/artwork-file-normalization.json) connects it to
the original file hash: ancillary metadata was removed while decoded pixels
and compressed pixel chunks remained unchanged. Historical derivation evidence
retains the old input file hash and is not rewritten to imply a new test run.

The keyer writes ignored local candidates for review. It does not automatically
promote them into the authored source tree. The fitter uses the already reviewed
RGBA path in its recipe and rewrites the selected output and fitting report.
Review any changed provenance and evidence before submitting those results.
Neither tool outputs game texture, UV-buffer, or mesh data.

## Runtime readiness is separate

Binding schema 2 supports explicit cutout expectations for `Custom/Piece`;
schema 1 remains opaque. Exact mode, cutoff, culling, depth write, blend factors,
render queue, and keyword state are checked before adoption and during
maintenance. Missing required stored floats reject the match. The binder can
change only the selected albedo and preserves foreign edits.

The [35-check native fixture](evidence/cutout-binding-native.json) passes with
acknowledged zero pending, resident, retiring, and leased ownership after
cleanup. Its owned shader deliberately omits several floats from ShaderLab
Properties to exercise stored-value presence. Explicit assertions verify that
keyword mutations occur before testing their rejection.

This proves the cited adapter behavior with an owned diagnostic shader. It does
not prove the actual game's shader or the straw candidate works in-game, and it
adds no UV, native-artwork, game-fixture, or final-approval stage to the candidate.
