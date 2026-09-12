# Roof atlas and broader material discovery

The 67-degree roof family now has an authored 1024px atlas with measured UV
regions, verified native bundles, and an exact experimental game mapping.
The runtime discovers up to eight shared material slots within its existing
per-frame work budget. The local installer updated five files and retained all
20 prior texture bundles unchanged.

## Evidence

- The atlas keeps vertical thatch and horizontal timber in their measured
  regions. All eight selected meshes fit; three selected submeshes were rendered
  in Blender at 3840 by 2160. Original-containing comparisons stay local.
- Ten roof-fitting tests cover layout, rotation, transparency, provenance and
  protected source/metadata outputs. The Python suite has 107 passing tests and one
  opt-in GUI test skipped. The game-independent runtime passes 166 assertions.
- All 24 native binding checks pass with zero final pending, resident or retiring
  payload and zero leases. The new secondary-slot test failed on the previous
  binder before the implementation was changed.
- All 22 native textures and 216 BC3 mips validate. Total compressed payload is
  12,933,024 bytes. The roof albedo alone is 1,398,128 bytes. Payload accounting
  does not establish total VRAM usage or the 6 GB target.
- The guarded main-menu fixture proves stone, timber and roof-atlas albedo
  replacement on actual loaded game mesh/material pairs. Both roof sides were
  captured with all submeshes and companion slots intact. The original cutout
  straw layer still covers much of the top surface, so roof artwork is partial. The standing-stone selector uses the
  observed `highstone_2/high` hierarchy. Original moss, normal and other material
  channels remain in place, so this is not final art or relighting approval.

See [roof fitting](ROOF_ATLAS.md), [native binding](GAME_BINDING.md), and
[game-menu validation](MENU_VALIDATION.md) for exact scope and limitations.

## Local package and rollback

Candidate 4 is `build/valheim-impact-0.3.0-candidate4-linux.zip`, 4,205,007 bytes,
SHA256 `efce0d498a894082807b5612391312757be45b2bdec0e035b17a357197c19d1b`.
It contains 27 payload files; the generated profile brings installed ownership
to 28 verified files. Balanced remains the default profile, with experimental
replacement enabled for this local test. Existing mods remain reversibly
isolated outside BepInEx plugin discovery.

The reviewed frozen installer applied the update. The previous candidate is
retained in the local installer rollback history. Backups contain
encoded `.payload` files and no recursively discoverable DLLs. With Valheim
closed, preview the installer rollback and apply its exact review token to
restore that snapshot. No public binary release is created by this milestone.

## Next visual scope

Default and 45-degree roofs use separate straw and alpha-fringe materials. They
need their own artwork fitting and native validation. The current atlas covers
the `wood_roof_mat` family only. A placed Meadows building, LOD transitions,
weather, foliage, terrain, water and final coordinated lighting remain open.
Representative hardware and route benchmarks are still required before making
performance or complete 4K-quality claims.
