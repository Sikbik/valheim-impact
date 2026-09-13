# Mushroom candidates

The ordinary mushroom has original 512px and 256px opaque albedo candidates.
Russet cap colors, a cream underside and restrained stalk fibers follow the
retained mushroom layout. Both sizes come independently from one owned atlas
source, preserving useful detail without assigning a large texture to every
small item.

## Exact scope

| Role | Serialized identity |
| --- | --- |
| Albedo | `CAB-8923bd833c4171316cf3c761b642c1c8:-3959143803454952172` |
| Retained normal | `CAB-8923bd833c4171316cf3c761b642c1c8:-2362882054155494049` |
| Material | `CAB-8923bd833c4171316cf3c761b642c1c8:-8680085326074669664` |
| Retained mesh | `CAB-8923bd833c4171316cf3c761b642c1c8:7556872827288687829` |

Five serialized consumers share the 37-vertex, 45-triangle mesh: the item
attachment, an inactive item node, the pickable, and two StartTemple placements.
Configured ordinary mushroom use also includes the Black Forest and Swamp.
The shared yellow and blue mushroom normal users are outside this albedo study.

The retained Standard material is opaque, with white tint, glossiness 0.22,
normal scale 1, and zero emission color. Its saved emission and normal keywords
remain part of the comparison control. Original game pixels, masks and geometry
payloads are excluded from the distributed artwork.

## Reproduction and validation

Run `python tools/fit_mushroom.py --help` for the reproduction command. The
helper reads only the hash-pinned owned atlas source and checks both output
hashes before writing. It refuses linked paths and existing outputs. Public
provenance records the cap and stalk artwork as ancestry. The helper reproduces
the final bases; it does not recreate the earlier placement of colors.

All 19 compressed mips pass decoded and payload checks. Both base mips pass
native GPU sampling and sampler checks. They use BC3 sRGB, Repeat, Trilinear filtering, anisotropy 4 and
mip bias 0. All 120 original-material frames pass across five rest transforms,
front/rear/top/underside views, and 1080p/4K captures. Source material, scene and
render-state preservation pass with no reported errors or warnings.

These are isolated draws with a 0.5-unit orthographic vertical span. They retain
the modeled shape, including its open stalk base. HDR highlights are measured
before the comparison PNGs are clamped and encoded without tone mapping.

## Remaining work

The narrow rim has finite filtered seam differences. Cap and cream colors mix
in coarse mips, especially below 8px. The original 32px normal is retained as an
unapproved control, and the brighter cream needs material and scene review.

World integration, picking, distance transitions, representative performance
and final art approval remain open. These staging candidates do not enable a
runtime binding or change the installed package.

See [UV evidence](evidence/mushroom-layout.json) and
[native material evidence](evidence/mushroom-native-material.json).
