# Explicit owned material binding

The runtime can replace explicitly mapped opaque material albedo slots through
`OwnedMaterialBinder`. It consumes the installed `profile.json`,
`assets/catalog.json`, and `assets/bindings.json`. Older packages and profiles
without `enableGameReplacement: true` remain disabled. The BepInEx
`GameReplacement.Enabled` setting can disable an enabled profile and request
restoration and draining. The setting alone cannot activate a disabled profile.

The allowlist targets metadata-matched rock, timber-wall, timber-pole and
67-degree roof-atlas materials. The guarded menu fixture validates standing-stone,
timber-pole and roof-atlas albedo replacement. Roof fitting and its narrower
evidence are documented in [ROOF_ATLAS.md](ROOF_ATLAS.md); placed-wall validation remains open.
A material name can be shared across multiple game objects and biomes. In the
current inventory, `stone_huge` with the same shader and original texture identity
appears in both Meadows rocks and Deep North hot springs. A rule matching that
identity intentionally changes both uses. Deep North appearance is not visually
validated by Meadows or fixture evidence.

## Mapping format

```json
{
  "schemaVersion": 1,
  "bindings": [
    {
      "id": "example-rock-surface",
      "materialName": "stone_huge",
      "shaderName": "Custom/StaticRock",
      "textureProperty": "_MainTex",
      "originalTextureName": "rock_256",
      "originalWidth": 512,
      "originalHeight": 512,
      "ownedTextureId": "an-explicit-catalog-id"
    }
  ]
}
```

The example demonstrates the schema; its owned texture ID is a placeholder.
Every rule must identify an existing, sRGB owned catalog entry. Names are ordinal
and exact. `stone_huge (Instance)` is a different name and is never silently
normalized. Material identity here consists of its exact name, shader name,
texture property and original texture name/dimensions. It is not a claim that
names distinguish every material object across the game. Runtime ownership
additionally captures the exact original texture and shader objects.

Version 1 admits at most 32 explicit rules and 256 catalog descriptors. It rejects
conflicting rules for the same material/shader/property, unknown aliases,
unsupported schema or engine versions, invalid mip/payload metadata, path
traversal, and symlinks. Each JSON file is limited to one MiB and the parser has a
bounded object graph. Only `_MainTex` is admitted. Transparent render queues and
standard alpha test/blend keywords are excluded during discovery. The initial
catalog must still be selected and visually validated as opaque by its author.

An enabled profile requires schema version 1, a known Compact/Balanced/High name,
`experimental: true`, and explicit `residentMiB`, `inFlightMiB`,
`concurrentRequests`, and `startsPerFrame` fields. Limits remain configurable
within the supported component ceiling: at most 4096 MiB resident payload,
256 MiB pending payload, two concurrent loads and exactly one new engine load
per frame. They are not total GPU or system memory limits. Pending capacity
cannot exceed resident capacity. Each mapped texture must fit pending capacity.

## Loading, matching and preservation

A single background task reads and parses manifests and verifies the mapped
UnityFS bundle archive hashes. It creates no Unity objects. Main-thread startup
consumes the completed result and requires the catalog's native target and Unity
version to match the player. A malformed or missing enabled package keeps
replacement disabled and reports the error. Missing profiles and old disabled
profiles do not open catalogs. Package files are immutable during a running game;
installation and updates remain closed-game operations. File checks are performed
once, not repeated during texture demand or reload.

The scheduler receives only mapped owned aliases. Discovery and `Acquire` do not
open files, load assets, wait for async handles, or create replacement textures.
The existing native `OwnedBundleLoad` starts and pumps Unity's asynchronous bundle
and texture operations under the scheduler's shared start gate. Until an owned
texture is resident and its bundle ownership has finished unloading, materials
retain the captured original texture.

Before applying, the binder rechecks the original object, exact identity and
opaque eligibility. It also monitors render queue and alpha keywords after apply.
A transition to transparency cancels pending demand or restores an owned slot,
while preserving the changed render queue and keywords.
It sets only the mapped texture property. It never changes a shader, normal map,
other material property, texture scale or offset. The original scale and offset
are captured and monitored. A foreign texture, shader, name or UV transform edit
ends the binder's demand. It restores the original texture only if the slot still
contains the exact replacement object assigned by this binder; foreign texture
values are preserved. Shader and UV edits are preserved when restoring a slot
that remains ours. A foreign-edited material is not reacquired during that binder
session. If the original object has been destroyed while our texture is still
bound, its lease is retained until that binding can be safely released.

Each active material lease protects its replacement from eviction. Shared
materials and exact-content aliases share scheduler allocations. A complete
scene census can release a material that is no longer observed on an active,
enabled renderer. Original restoration precedes lease release. After a completed
census, released, unseen records without foreign edits are removed even when their
original Material objects remain alive. This lets discovery continue through
renderer churn without permanently consuming the 1024-record capacity. Records
suppressing foreign edits remain bounded in that registry until the material is
destroyed or the binder session drains. No untracked texture is destroyed by
scheduler retirement.

## Bounded discovery and lifecycle

The adapter walks loaded scenes incrementally, processing at most 64 discovery
work steps and 64 tracked binding checks per update. It considers active, enabled
renderers and inspects up to eight shared material slots without instantiating
material copies. Each inspected slot consumes the existing discovery budget.
A reusable list retains capacity eight and clears its references after each read.

The matching Unity version has no public scalar material-count API. A cached open
delegate to `Renderer.GetMaterialCount` checks the native count before calling
`GetSharedMaterials`. Oversized renderers keep first-slot coverage. An unavailable
or failing count capability also retains first-slot coverage and emits one
bounded warning per binder. A failed capability is disabled for that binder.
A shared Material remains shared across its renderers and slots.
The registry is limited to 1024 material records and leases. Each entry caches its
ownership callbacks when discovered, so its steady update does not recreate
those delegates. This is not a measured claim of zero gameplay allocation. The
walk performs no
`Resources.LoadAll`, no per-frame global
`FindObjectsOfTypeAll`, and no eager asset-pack load. One renderer lookup handles
the ordinary one-renderer-per-GameObject case; multiple Renderer components on a
single object are outside this first adapter's discovery coverage.

The walk admits scenes
with at most 8192 root objects, a hierarchy depth of 256, and 262144 traversal
steps per census. A census ends at its fixed limits. An
incomplete census retains existing demand and does not infer that an unvisited
material is unused. It records a bounded warning, then retries after the normal
two-second census interval. Scene root enumeration and bounded shared-material reads are
individual Unity API calls; their internal CPU cost has not been benchmarked.
These safeguards bound managed work and memory, not a measured frame-time ceiling.

Scene load/unload requests a full restore and scheduler stop. The adapter drains
before a new binder starts for the remaining loaded scenes. Disabling the plugin
or its replacement setting also restores and drains. A separate persistent
`OwnedMaterialHost` keeps pumping after the BepInEx Plugin component is disabled
or destroyed. Do not manually remove that host or unload the assembly while
ownership remains. Runtime retirement uses `Object.Destroy` and acknowledges only
Unity null, with no guessed frame deadline. Process exit restores owned slots
while possible, then the process ends; it is not evidence of a completed async
drain. Original game assets, shaders, bundles and saves remain outside ownership.

Every 30 seconds, enabled replacement reports bounded frame-delta percentiles,
tracked/matched/applied/restored/foreign material counts, leases, queue/load
counts, errors, and pending/resident/retiring compressed payload bytes. Those
frame deltas are not GPU timings. At most 16 distinct original-texture/shader
candidate material-name misses are logged per binder session, including instance
suffix misses, to support allowlist diagnosis without a per-frame dump.

## Verification and finite Editor fixture

Run the engine-independent suite and compile staging DLLs:

```bash
python tools/build.py --config local/build.json --test
python tools/build.py --config local/build.json
```

The material work first produced eight failing ownership assertions and seven
failing package-registry assertions. After implementation, the full suite passed
166 assertions with `Failures: 0`. The independent policy-guard regression was
also mutation-checked: removing the one-start-per-frame profile guard caused
exactly that test to fail, with all other inputs valid. Game-reference compilation
and a compile-only check of the Editor harness also passed. These checks
performed no game writes and did not execute the Editor fixture.

For the native fixture, locally stage `build/runtime/ValheimImpact.Core.dll`,
`src/ValheimImpact.Unity/OwnedBundleLoad.cs`, and
`src/ValheimImpact.Unity/OwnedMaterialBinder.cs`, and
`src/ValheimImpact.Unity/OwnedMaterialHost.cs` in
`unity/Assets/GeneratedRuntime/`, then stage
`tools/unity/MaterialBindingProbe.cs` in its `Editor/` subfolder. Do not include
Plugin source. Keep the host outside `Editor/` so Unity can attach its
MonoBehaviour during the lifecycle checks. Invoke the following through the
matching Editor after its normal compilation:

```csharp
MaterialBindingProbe.Start(absolutePackageRoot, absoluteReportPath);
```

The package root must have the enabled profile, catalog and bindings described
above. Start returns promptly. The worker validates those files; the probe then
replaces only that result's in-memory allowlist with Standard-shader fixture
rules. It creates its own hidden GameObjects, materials, fallback, normal and
foreign-edit textures. The production binder receives those renderers directly
with general scene discovery disabled. Its explicit observation clients complete
fixture-only passes using `CompleteObservationPass`, the same completion API
called by production scene discovery. Calling that API promises the complete
active set has been visited; a partial external scan must not call it. No project
material, saved scene, game world or character is opened or modified.

The 24 checks cover validation, exact-name misses, both shared material slots,
asynchronous shared apply, shader/UV/unrelated
channel preservation, opacity changes before and after apply, foreign edits,
disable restoration, deferred destruction and final zero-allocation drain.
The additional bounded cases use a 2048-slot renderer, simulate missing and
throwing count capabilities, and traverse 128 distinct materials on eight-slot
renderers while checking the 64-step observation limit. A
bounded churn case retains 1056 distinct owned Material objects while their
renderers are destroyed, completes each fixture-only census, and verifies that
unseen records are reclaimed and a later material still receives demand. The
Editor delays retirement for three updates, then permits
`DestroyImmediate(texture, true)` only for the exact transferred owned-bundle
instance with an empty AssetDatabase path. This is an Editor-only cleanup rule,
not the gameplay destruction API. Runtime uses `Object.Destroy`.

The lifecycle checks invoke the real host callbacks on isolated components.
They verify that normal process quit restores originals, preserves foreign edits,
and releases material leases while still reporting resident payload honestly.
Only the misleading unexpected-removal warning is suppressed during process
quit. Destroying an undrained host without that callback still reports an error.
The fixture separately pumps its native allocations through acknowledged cleanup;
process exit itself does not prove asynchronous drain.

A 45-second timeout writes a finite failure report. If engine ownership remains,
its pump stays attached solely to retain and drain those handles. The report
marks `cleanupPending`; it never invents a release acknowledgement to stop the
pump. Reports use a temporary file, JSON round-trip validation and disk readback.
Do not reload the Editor domain while the fixture is pending. The separately
captured native report determines fixture success. Standard fixture success does
not establish real game shader behavior, mesh UV fitting, visual quality, route
frame time, physical VRAM reclamation, 6 GB hardware compatibility or Windows
behavior. Model and shader streaming remain separate unvalidated work.

## Executed native fixture

The final binder and host pass all 24 checks in the matching Unity
6000.0.75f1 Editor on Vulkan. The report records completed cleanup, no pending,
resident or retiring owned payload, and zero leases. It includes source and
compiled DLL hashes in `docs/evidence/material-binding-native.json`.

The game-reference build passes 166 engine-independent runtime assertions.
Separate Blender evidence validates UV0 transfer and material texture scale for
the original rock and timber-pole meshes. This does not validate custom game
shader appearance. The local enabled package is installed through the reviewed
installer and verifies against its ownership receipt. The guarded game-menu
fixture and its narrower visual evidence are documented in
[MENU_VALIDATION.md](MENU_VALIDATION.md).

## Staged explicit cutout support

Source after milestone 4 also accepts binding schema 2. The current installed
candidate and `assets/bindings.json` still use the four opaque schema-1 rules.
No fringe binding is enabled by this source change alone.

Schema 2 permits an optional per-rule `cutout` object for exact `Custom/Piece`
rules. It requires all eight fields, for example:

```json
"cutout": {
  "mode": 1, "cutoff": 0.69, "cull": 0,
  "zWrite": 1, "srcBlend": 1, "dstBlend": 0,
  "renderQueue": 2000, "alphaTest": false
}
```

Use observed material values, not this example as an automatic allowlist. The
cutoff is compared as its exact float32 value; mode must be 1, cull must be 0 or 2,
depth writes enabled, and blending One/Zero. An exact queue from 1000 through
2500 is required. Alpha blend and premultiply keywords must be absent, and
alpha test must match the explicit boolean. Schema 1 rejects a cutout field.
Without that field, opaque rules reject a stored nonzero mode or incompatible
blend/depth state as well as alpha keywords and transparent queues.

The binder uses cached property IDs and `HasFloat` before reading each required
stored value. Missing values reject the candidate. It repeats eligibility at
discovery, before adopting a loaded texture and after adoption. State changes
release demand and restore only a texture still owned by the binder, preserving
the changed shader properties and foreign textures. No render state is set.

A 35-check owned diagnostic fixture validates this staged path, including
stored floats absent from ShaderLab Properties and actual keyword mutations.
Actual `Custom/Piece` runtime compatibility and authored fringe rendering remain
pending. See [cutout evidence](evidence/cutout-binding-native.json) and
[art preparation](STRAW_FRINGE.md). Package validation is lexically stricter than
the C# DataContract parser, but both constrain the recognized state values;
packaging additionally checks the cutoff after float32 rounding.
