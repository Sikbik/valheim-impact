# Local main-menu validation

The 2026-09-12 native Linux test passes all three required comparisons in
Valheim l-1.0.12 on Unity 6000.0.75f1, Vulkan and Linear color. Only Valheim Impact
and a temporary local validation plugin loaded. The production binder visibly
replaced standing-stone, timber-pole and 67-degree roof-atlas albedos while the
reference materials and companion slots remained intact.

The compact result is [game-menu-binding.json](evidence/game-menu-binding.json).
The final 3840 by 2160 image and raw report are under ignored
`local/game-validation/menu-run-12/`. The earlier underside roof view is recorded
in [separate metadata](evidence/game-menu-roof-underside.json), with its image
under `local/game-validation/menu-run-11/`. Original-containing images remain
outside tracked source and release archives.

## Result and visual limits

| Exact material | Observed source | Mesh vertices / submeshes | Changed sampled pixels, final view |
| --- | --- | --- | ---: |
| `stone_huge` | `highstone_2/high` | 106 / 1 | 23,623 |
| `woodpole` | 39 references to one exact material/mesh pair | 66 / 1 | 24,512 |
| `wood_roof_mat` | `wood_roof_67/New/default`, slot 0 | 312 / 2 | 5,098 |

Each right-hand material received its authored 1024px texture. Each left-hand
material retained the captured original texture. The same camera, geometry,
position and lighting were used for the original-only baseline. Counts sample
every second pixel within disjoint row regions and require an RGB difference
over the defined threshold. They establish visible influence, not screen coverage
or texture quality percentages.

The roof keeps both submeshes, all 254 triangles, and its original
`straw_roof_alpha` companion material behavior. Five companion texture slots,
their UV transforms and the shader remained unchanged on reference-named clones.
The first view shows the wooden underside. Rotating the fixture 180 degrees
around Y shows the top, where the original 64px cutout straw still covers much
of the new atlas. The roof is therefore not a completed visual replacement.
The [next alpha-fitting inputs](evidence/default-roof-layout.json) cover this
shared fringe and the default/45-degree roof family.

The original rock moss and normal channels also remain in place. This is a
finite menu fixture, not final art or relighting approval. It does not validate
a placed building, `woodwall`, weather, LOD transitions, a whole scene or biome.
The capture target is 4K; the game window was 2560 by 1440. There is no route
benchmark, representative 6 GB hardware result, total VRAM claim or Windows
result. Diagnostic snapshots and CPU image readback are not gameplay timing.

## Exact source selection

The earlier `Rock_3_Untitled`/`stone_huge` selector had no matching loaded
renderer. A bounded diagnostic found the loaded standing-stone pair instead.
See [rock diagnosis](evidence/rock-menu-diagnosis.json). The roof hierarchy comes
from serialized Transform parent links, recorded in
[roof source metadata](evidence/roof-menu-source.json), and was independently
found in the final menu's loaded renderer snapshot.

The fixture inspects each resource type once and considers at most 65,536
renderer entries per selection. Exact hierarchy where specified, mesh name,
vertex/submesh counts, selected slot, material/shader/texture identities and UV
transforms must agree. A scalar count preflights a reusable list of at most eight
shared materials. Missing capability, oversized slots, truncated scans or
multiple distinct complete mesh/material-list identities refuse selection.
Repeated references to the same ordered identity are harmless. The fixture
loads no game bundle and chooses no guessed fallback pair.

## Guard and ownership

`tools/game/MenuValidationProbe.cs` is local tooling, never an installer payload.
It stays inactive without both `-demomode` and one
`-vi-menu-validation /absolute/new/output-directory` argument. Automatic world,
character and connection arguments are rejected. Output cannot enter the game
or original save tree, reuse a directory, or traverse symlinks.

Before menu loading, the probe enables `DontSaveAnything` and sets a separate
save path through the game's save API. It does not rely on `-savedir` being
parsed by the client. Every fixture action and automatic exit requires
`FejdStartup`, scene `start`, no `Game` instance, no local player, demo mode and
unchanged save prevention. A lost guard disables automated scene actions and
quit. There is no process-kill fallback.

All comparison materials are owned clones. Companion slots share a new clone
across the two sides, while the selected materials have separate original and
authored clones. Borrowed meshes, textures and shaders are never destroyed.
The final run acknowledged fixture cleanup and quit from the guarded menu.
The temporary plugin was then removed and the installed package reverified.

The game's existing Newtonsoft assembly serializes plain records, with list
counts checked before writing. All 38 pure activation/path/guard/slot checks and
the game-reference compile pass. Those include full-list ambiguity, secondary
slot isolation and refusing oversized lists before invoking their getter.

## Local deployment and preservation

Candidate 4 was applied by the reviewed frozen installer. It changed five files,
retained all 20 previous texture bundles byte for byte, and verifies all 28
installed owned files. Its 27-payload ZIP is 4,205,007 bytes with SHA256
`efce0d498a894082807b5612391312757be45b2bdec0e035b17a357197c19d1b`.
The previous DLL, catalog and bindings remain in verified encoded rollback
payloads under backup `6d0d0fcf7cdc4ef0a68b405c77fc86c0`.
Only the production Core and Unity DLLs remain discoverable under plugins.

The final game exit reported zero material leases and zero loader errors, while
honestly retaining 4,194,384 bytes of resident texture payload at process exit.
That is not an asynchronous drain result. The separate matching-Editor fixture
passes all 24 ownership checks and reaches acknowledged zero allocations and
leases. See [GAME_BINDING.md](GAME_BINDING.md).

No existing character or world was loaded. All 24 recorded local save-tree
metadata entries remained unchanged. Of 38 Steam save-tree entries, only
`remotecache.vdf` changed; all 15 recorded character/world header hashes remained
unchanged, and no new files appeared in either checked save tree.

## Startup diagnosis

Early X11 attempts stopped before game code while Unity waited for a window-map
event. Restarting Steam alone left its windows hidden as well. A minimal X11
window test also remained unmapped. After saving and closing Unity, restarting
Xwayland restored that test, Steam's main window and Friends List. The desktop
configuration was restored byte for byte, and Unity and the saved Blender review
scene were reopened. No desktop reset or permanent rendering flag was applied.

Separate native Wayland attempts crashed in Unity's Vulkan presentation path,
including a control without the production plugin. Matching installed Unity
symbols resolved the stack through `vk::CommandBuffer::DoImageWriteBarrier`
and `GfxDeviceVK::PresentImage`. That path remains unvalidated. The completed
menu runs used the original Vulkan/X11 route after desktop recovery.
