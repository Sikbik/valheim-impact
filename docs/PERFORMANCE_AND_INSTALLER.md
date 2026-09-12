# Performance and installation direction

The default hardware target is 6 GB VRAM, 16 GB system RAM and 1920 x 1080.
This is a development target, not a measured compatibility claim. Keep the
original Viking anime direction and crisp silhouettes. Use selective texture
resolution, full mip chains, anisotropic filtering, restrained material noise
and coherent lighting before adding expensive effects or oversized textures.

The user also prioritizes a beautiful image on 4K displays and permits raising
requirements when needed for quality. Preserve original high-resolution artwork
and offer a High preset for 4K. Choose 1K/2K/4K authored surface sizes by matched
close-up renders and texel density, never by indiscriminate downscaling. The
default hardware target is not a ceiling on the source artwork or High preset.

## First implementation milestone

Build and validate the authored Meadows probe bundles in the matching Vulkan
Editor. Add an independent owned-texture scheduler with bounded asynchronous
loads, deduplicated residency, demand leases and safe deferred retirement.
Keep the accepted legacy loader as an unchanged reference. Exercise the new
scheduler with owned probe textures in Unity before binding it into the game.

Balanced is the default preset: 768 MiB for owned resident compressed texture
payload, 64 MiB for in-flight payload, two concurrent engine requests and one
new request per frame. Compact uses 384/32 MiB and one concurrent request.
High uses 1536/128 MiB and two concurrent requests. These are component limits,
not total GPU-memory limits. Original textures, render targets, meshes, Unity,
drivers and other mods still consume memory. Protect currently demanded assets;
on budget exhaustion preserve the original binding and defer replacement.

Count pending and retiring allocations until ownership has actually been
released. Share exact payload identities only when dimensions, format and color
interpretation match. Never wait synchronously for a texture on a gameplay
demand. Retain valid originals while requests finish or fail. Stop requesting
unneeded assets, drain in-flight work and restore bindings before destruction.

The initial installer is a local desktop application with Steam detection,
folder selection, package verification, an exact change preview, profile
selection, install/update, verify and uninstall/rollback. It installs only our
owned folder under BepInEx/plugins/ValheimImpact and records its ownership.
It must reject tampered packages, path traversal, symlinks and changes to files
it does not own. It must detect a running Valheim process and refuse mutation.
Never stop the game. Test destructive operations only against disposable game
fixtures. Existing mods, game files and saves are outside installer ownership.

Package the current milestone honestly as an experimental diagnostic/probe
build. The small material studies are not the finished HD replacement library.
Do not auto-enable game material replacement until UV fitting, original alpha
and in-game compatibility have been validated. Windows distribution builds and
6 GB hardware benchmarks remain separate required validation.

## Evidence required before performance claims

Record fixed-route frame-time distributions, hitch counts, process RSS, total
GPU use, owned residency, queue pressure and return-travel reload behavior.
Compare identical camera routes and graphics settings with the same save and
world state. A smaller archive or a successful bundle read is not an FPS result.
Reject quality changes using matched near/far and daylight/sunset/night captures.

The user authorized incremental source pushes to Sikbik/valheim-impact. Push
validated commits without uploading original game/mod assets, downloaded packs,
local credentials or extracted references. Publish installer binaries only
after the current platform's validation is stated explicitly.
