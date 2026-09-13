# Runtime development

The runtime is a BepInEx plugin with an engine-independent C# core and a Unity
adapter. It supports explicitly mapped albedo replacements from owned native
AssetBundles. It retains existing game shaders and original texture fallbacks.

## Build and test

Requirements are Python, a local .NET runtime, and Roslyn `csc.dll`. A .NET SDK
can supply the compiler; an SDK is not required if those components are already
available. Copy `config/local.example.json` to ignored `local/build.json` and
configure `dotnet`, `roslyn_csc`, and, for the plugin build, `game_dir`.

```sh
mkdir -p local
cp config/local.example.json local/build.json
```

Edit the placeholders before running:

```sh
python tools/build.py --config local/build.json --test
python tools/build.py --config local/build.json
```

The first command builds and runs engine-independent tests using the newest
stable installed `Microsoft.NETCore.App` runtime. It does not require game
assemblies. The second reads Mono framework, Unity, and BepInEx assemblies from
an installed game and writes `ValheimImpact.Core.dll` and
`ValheimImpact.Unity.dll` to `build/runtime/`. It does not copy reference
assemblies or deploy anything.

`--roslyn` or `VALHEIM_ROSLYN_CSC` can select the compiler. `--game` or
`VALHEIM_DIR` can select the game directory. Keep actual machine paths in local
configuration. A .NET test pass and a game-reference compile exercise different
environments; neither substitutes for a native Mono/Unity fixture.

## Activation and files

The installed folder contains the two runtime DLLs, an installer-generated
`profile.json`, `assets/catalog.json`, native bundles, and an optional
`assets/bindings.json`. Replacement requires an enabled experimental profile,
a valid catalog and allowlist, a matching Unity version and bundle platform,
and the BepInEx `GameReplacement.Enabled` switch. The installer opt-in starts off.
A missing or disabled profile keeps replacement disabled.

`OwnedMaterialHost` validates manifests and referenced bundle hashes once on a
worker. No Unity calls occur there. The staged files must remain unchanged
while the runtime uses the validated registry. Unity bundle requests, asset
requests, material access, adoption, and destruction run on the engine thread.
There is no synchronous load-on-demand path.

## Native texture identity and sampling

Native catalog schema 1 accepts an optional `wrapMode` of `repeat` or `clamp`.
An explicit declaration also requires Trilinear filtering, anisotropy 4 and mip
bias 0. Before adoption, the native loader verifies wrapping on U, V and W and
each of those fixed sampler values. A mismatch prevents ownership transfer and
drains the asynchronous load. The loader does not repair sampler state.

Sharing includes pixel payload, format, dimensions, mip count, color space and
the declared sampler policy. Equal compatible declarations can share a texture
across bundle aliases. Identical pixels with different wrapping stay separate,
so request order cannot select the other material's sampler.

A historical catalog without `wrapMode` remains supported with unknown sampler
state. Its identity also includes the native bundle hash and exact asset
selector. Only identical legacy bundle/selector identities can share, and they
stay separate from declared samplers. An absent declaration does not assume
Repeat. Explicit null, unsupported values and non-string declarations are
rejected.

The package builder compares declared native wrapping with staged `wrap_mode`
and preserves the catalog bytes. Missing staged wrapping resolves to the
historical Repeat build default for that comparison; image `periodic` settings
do not choose a sampler. Missing native declarations remain absent and unknown.
Malformed explicit staging or native values and declared disagreements prevent
packaging.

The [native sampler fixture](evidence/texture-sampler-native.json) passed 14
cases and 55 checks using two owned normal textures with identical pixel
payloads and different wrapping. It covers both request orders, compatible
aliases, legacy isolation, and rejection of individual sampler mismatches with
cleanup. These are loader and ownership results. Material bindings remain
albedo-only, and this fixture does not render or validate game appearance.

## Exact material matching

Each rule specifies material name, shader name, `_MainTex`, original texture
name and dimensions, and an owned texture ID. Up to 32 explicit rules are
supported. Names are exact, including instance suffixes. No substring or
similarity fallback expands the allowlist.

Schema 1 accepts opaque rules only. Schema 2 permits opaque rules and explicit
`cutout` expectations for `Custom/Piece`. A cutout rule specifies mode 1,
cutoff strictly between 0 and 1, cull 0 or 2, depth write 1, source blend 1,
destination blend 0, an exact render queue from 1000 through 2500, and the
expected alpha-test keyword state. Alpha-blend and premultiplied-alpha keywords
must remain disabled. Missing required stored floats or unsupported states
reject the match. Getters are guarded by property-presence checks.

Schema 3 additionally permits explicit `grass` expectations for the two reviewed
`Custom/Grass` Meadows materials. Its fixed-pass contract checks cutoff 0.46,
queue 2000, instancing, terrain-color identity and scale, variant wind settings,
and the measured shader property and pass signature. Missing mode, cull, blend
and depth properties are required to be absent, rather than read as zero.
Grass never enters through an implicit opaque rule. Schema 3 validates original
JSON types and rejects unknown fields in both the runtime and package builder;
it may also carry existing opaque and `Custom/Piece` cutout rules.

The cutoff is compared at exact single-precision runtime representation. Package
validation checks float32 rounding before acceptance. The package parser also
rejects unknown cutout keys and quoted numeric values; the C# deserializer is
more permissive about those lexical forms in schemas 1 and 2, while recognized state values remain
constrained. Use the package builder to validate distributable input.

Opaque rules retain the opaque queue and alpha-keyword guard and reject stored
non-opaque mode, blend, or depth-write state. Both policies are rechecked before
adoption and while an assignment is maintained. Cutout support does not imply
that any cutout artwork is on the actual game allowlist or visually approved.

## Bounded discovery and ownership

The scene walker uses a 64-step discovery budget and at most 1,024 tracked
materials. It limits roots, hierarchy nodes, and depth, and reports incomplete
censuses. Released, unseen records are reclaimed after a complete census.

A cached open delegate to the installed renderer's scalar material-count method
preflights shared-material access. A reusable list holds at most eight slots.
Oversized renderers, missing capability, or a capability failure use first-slot
coverage with bounded diagnostics. This compatibility fallback is intentional;
it does not establish complete renderer coverage.

When explicit grass rules exist, the same walk also observes active
`InstanceRenderer` components. It resolves the exact game type and declared
material/mesh fields once, then uses cached getters and scalar component access.
Duplicate components and ordinary Renderers share the existing material lease.
The observer reserves its maximum work within the same 64-step budget. Missing
component support disables grass participation while ordinary Renderer binding
continues.

An instancer node with more than eight total components makes the census
incomplete. Unseen leases remain held through repeated incomplete passes,
potentially until a later complete pass or shutdown. The material bound limits
growth but does not guarantee eviction during recurring overflow. Grass also
guards the original terrain-color texture object, its UVs and scale, material
state and shader. A foreign change restores only a still-owned albedo slot.

A material keeps its original texture object, shader object, and texture
scale/offset. The binder changes only the selected albedo. Shared demand uses
leases so an assigned texture cannot be evicted. A foreign texture, shader, UV
transform, or eligibility change ends demand. Restoration only replaces an
assignment still owned by this runtime, preserving foreign edits.

Disabling or scene transitions stop discovery and drain the scheduler after
restoring assignments. Texture retirement remains charged until Unity object
null semantics acknowledge destruction. The host outlives plugin disable to
pump that drain. At process exit it restores owned slots, but does not claim an
asynchronous drain completed. Removing the host or assembly before drain is
unsupported.

## Diagnostics and evidence

The host reports runtime/API information and bounded binding and ownership
counts. Frame diagnostics keep a fixed ring of 4,096 Unity frame-delta samples
and report p50/p95/p99 and maximum values. They are observed frame deltas, not
GPU timings; menus and summary overhead can affect them. Driver-reported memory
capacity is not measured VRAM usage.

Native fixtures cover async loading, shared adoption, exact misses, bounded
multi-slot discovery, foreign changes, opacity and cutout-state changes,
restoration, churn, and acknowledged cleanup. Game-menu evidence covers only
selected loaded stone, timber, and roof-atlas pairs. Check the public tracker
and scoped evidence for the exact tested artifacts.

Representative route measurements, broader platform compatibility, placed-world
visual checks, and model or shader streaming remain open. Payload budgets do
not prove the 6 GB VRAM / 16 GB RAM / 1080p Balanced target or crisp 4K quality.
