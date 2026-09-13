# Raspberry candidates

The raspberry fruit material now has original 512px and 256px opaque albedo
candidates. A red drupelet surface and the project's existing leaf artwork fit
the retained fruit, stem and calyx regions. The recipe preserves round surface
detail through uniform scaling and cropping, with padding around the small
green regions. Original geometry guides private UV inspection; original game
pixels, image masks and mesh payloads are excluded from the distributed artwork.

## Exact scope

| Role | Serialized identity |
| --- | --- |
| Albedo | `CAB-8923bd833c4171316cf3c761b642c1c8:4336459423859995684` |
| Original normal | `CAB-8923bd833c4171316cf3c761b642c1c8:-930578383931095846` |
| Material | `CAB-8923bd833c4171316cf3c761b642c1c8:5156263323322596695` |
| Retained mesh | `CAB-8923bd833c4171316cf3c761b642c1c8:5184478007217032880` |

The material has 24 serialized consumers: 21 fruit renderers across three bush
hierarchies, the active Raspberry item attachment, and two inactive item nodes.
The bush fruit belongs to LOD0; the farther bush material is outside this
replacement. Exact configuration establishes Meadows use. A disabled Mistlands
entry does not establish active use there.

The mesh has 144 vertices and 152 triangles. Fruit and shoulder occupy a narrow
connected region, with a thin stem and two separate calyx bands. The original
albedo is fully opaque throughout its six mips. Its normal alpha carries packed
normal data, not transparency.

## Reproduction and validation

Run `python tools/fit_raspberry.py --help` for the fitting command. The helper
checks both owned parent hashes, reproduces both atlas hashes before writing,
and refuses to overwrite existing outputs. Public provenance and
`assets/meadows/raspberry-recipe.json` identify every distributed input.

Both candidates pass complete BC3 mip, native payload, GPU sampling and sampler
checks. They use Repeat, Trilinear filtering, anisotropy 4 and mip bias 0.
Twenty-four original Standard-material frames cover two representative
transforms, bush fruit and the item, from front and rear at 1080p and 4K. The
original normal, material controls, transforms and tint remain intact. Scene,
global and material preservation checks pass with no reported errors or warnings.

These are isolated fruit draws with a 0.5-unit orthographic vertical span.
They do not show a complete bush, gameplay distance or live LOD transitions.
The other placements have offline geometry review only.

## Remaining work

The original 32px normal produces blocky highlights that disagree with the new
drupelets. It is a comparison control, not an approved companion. A separate
aligned normal study is required. Stem and calyx colors also mix into red at
coarse atlas mips. The native comparison PNGs clamp HDR highlights without
tone mapping.

World binding, lighting and weather, distance transitions, representative
performance and final art approval remain open. No runtime binding or installer
payload is enabled by adding these candidates.

See [UV evidence](evidence/raspberry-layout.json) and
[native material evidence](evidence/raspberry-native-material.json).
