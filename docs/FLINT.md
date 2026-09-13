# Flint candidates

An original pale flint surface now has 1024px and 512px opaque candidates.
Broad gray and ivory planes preserve the readable shape of loose stones and
piles. A denser repeated variant was evaluated but was busier on those meshes.
The selected fitting recipe uses only the owned surface source.

## Exact material scope

Target albedo `CAB-8923bd833c4171316cf3c761b642c1c8:2536012081126669073`
belongs to material `CAB-8923bd833c4171316cf3c761b642c1c8:6656279515724779218`
for this contribution. The texture also appears as an emission input on nine
other materials covering 41 renderers. Those effects are excluded. A future
binding must select the flint material explicitly.

The selected material has 71 serialized renderers across five mesh layouts:
loose flint, spearhead, arrowhead, new pile and worn pile. Shared uses include
items, construction, enemy equipment and projectiles. The spear review covers
its head slot only. Disabled pile combine inputs and the inactive worn state
are identified separately from active renderers.

The original opaque Standard material has no normal map, metallic 0,
glossiness 0.702 and white tint. Its MainTex scale is 0.2 on both axes, so the
meshes sample mostly the lower-left fifth of the image. A small negative V
excursion makes Repeat necessary. These controls are preserved.

## Reproduction and validation

Run `python tools/fit_flint.py --help` for the fitting command. The helper
checks the owned parent and both final output hashes before writing to a new
directory. The selected source is already fitted; staging adds no second seam
correction. The 512px candidate is derived in linear light from the 1024px fit.
See `assets/meadows/flint-recipe.json` for exact inputs and measurements.

Both candidates pass their complete BC3 mip chains, native payload and GPU
sampling checks. They use Repeat, Trilinear filtering, anisotropy 4 and mip
bias 0. All decoded albedo mips remain opaque.

Sixty original Standard-material frames cover the five mesh layouts, one
representative transform each, from front and rear at 1080p and 4K. Matched
views preserve texture transforms, shader properties and the null normal
binding. Scene and global restoration checks pass with no reported errors
or warnings.

## Remaining work

These are enlarged orthographic material studies. Their framing is computed
from each mesh's projected bounds; a 1024px source does not provide 1024 texels
across an object that samples only part of it. The new surface is brighter than
the original, and its retained gloss needs review under scene lighting.
Comparison PNGs clamp HDR values without tone mapping.

World visibility, distance, construction transitions, projectile contexts,
runtime binding, representative performance and final art approval remain
open. Adding these candidates does not enable a runtime binding or change the
installed package.

See [layout evidence](evidence/flint-layout.json) and
[native material evidence](evidence/flint-native-material.json).
