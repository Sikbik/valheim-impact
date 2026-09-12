# Milestone 1: authored Meadows foundation

This milestone established an offline material pipeline, native texture-loading
foundation, and local installer. It did not complete a playable Meadows scene
or deploy game material replacement. The figures below are historical results
from the [foundation snapshot](evidence/foundation-checks.json), not the size or
test count of every later build.

## Completed scope

Original lighting concepts, six material studies, a beech cutout card, and a
dedicated granite surface established a common palette and processing path.
Their owned probe geometry supported consistent daylight, sunset, and night
studies. The images are technical studies rather than game captures.

Sixteen albedo/normal textures contained 150 BC3 mip levels and 4,544,256 bytes
of compressed texture payload. A matching Unity 6000.0.75f1 Editor built native
bundles under Vulkan with Linear color space. Serialized payload checks and
base-mip GPU comparisons verified the tested color, alpha, and orientation
contract. Compressed payload size is not total RAM or VRAM consumption.

The engine-independent runtime passed 145 assertions. The
[native scheduler fixture](evidence/owned-streaming-native.json) passed 14 checks
covering shared ownership, budget deferral, retirement acknowledgement, reload,
opening cancellation, missing-selector fallback, and shutdown. It ended with
zero owned allocations; the missing-selector error was deliberate.

The recorded Python run completed 50 tests: 49 passed and one display test was
skipped. A separate installer run passed 28 tests with the GUI fixture enabled.
The Linux executable exercised install, update, verification, rollback, and
uninstall against a temporary game fixture. These results apply to the recorded
artifacts and environment, not all platforms.

## Contributor contracts established

- Keep source artwork, processing recipes, dimensions, color semantics, and
  hashes traceable through staging and native bundles.
- Preserve full mip chains and explicit normal-channel encoding.
- Separate worker-side file preparation from Unity object creation and lifecycle.
- Retain ownership until native destruction is acknowledged.
- Preview installer changes and preserve unrelated files and saves.
- Keep original game pixels, geometry, assemblies, and resource links outside
  source contributions and packages.

The current implementations and commands are documented in
[ARCHITECTURE.md](ARCHITECTURE.md), [RUNTIME.md](RUNTIME.md),
[UNITY_PIPELINE.md](UNITY_PIPELINE.md), and [INSTALLER.md](INSTALLER.md).
Later exact game binding work is recorded in [Milestone 2](MILESTONE_02.md).

## Acceptance still open

A coherent playable scene needs actual terrain, foliage, buildings, water,
characters, and lighting reviewed together at several distances and times of
day. Navigation, grass-card alpha, water seams, faces, equipment, weather, and
shadow transitions need explicit checks. Native probe success does not satisfy
that scene-level acceptance.

Representative tests must record hardware, game/version/API, resolution,
settings, material coverage, frame-time distributions, process memory, graphics
memory, loading misses, and return-travel behavior. The current Balanced target
is 6 GB VRAM, 16 GB RAM at 1080p, with crisp 4K presentation required. Historical
component counts do not establish that target, complete 4K quality, or model and
shader streaming.
