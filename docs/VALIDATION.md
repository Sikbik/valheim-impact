# Local validation and removable prototype

## Current boundary

This is an experimental visual overhaul. Owned native texture loading and
bounded material binding have recorded Editor and isolated game-menu evidence.
The installed local candidate covers stone, timber and a roof atlas. A staged
cutout adapter and straw artwork are still being prepared. See
[MILESTONE_04.md](MILESTONE_04.md) for current scope.

A full played biome, representative older hardware, Windows, weather, LOD
transitions and model or shader streaming have not been validated. The Balanced
goal is 6 GB VRAM and 16 GB RAM at 1080p, while preserving crisp options for 4K.
Existing measurements do not establish that target.

## Reproducible comparison scene

Start with an isolated authored geometry/material probe in Unity or Blender.
Keep one camera and the same geometry for daylight, sunset and night. Use grass
and earth planes, a small steep-roof timber house, a rock, a tree with transparent
leaf cards, a shoreline/water study and a roughly 1.8 m scale proxy.

For game validation, use a user-approved disposable test world or a local copy of
a world, preserving the original. Record world identifier, position, heading,
camera distance, FOV, resolution, graphics settings, mods, weather, time of day
and the installation fingerprint. Establish marked near, medium and far viewpoints
at approximately 2, 10 and 40 m. Capture unchanged settings before and after.

At each treatment: stand still for 60 seconds, walk a fixed 300 m route toward the
forest edge, return over the same route, wait 60 seconds, then repeat. Record cold
first-use and warm return separately. Do not combine menu, load-screen and world
frame distributions. Repeat after a normal restart controlled by the user.

Check grass-card edges, backfaces and distant alpha coverage, wood atlas alignment,
stone/moss transitions, water seams, equipment and character silhouettes, fog,
weather, night readability and shadow transitions. Select production asset
resolutions only after these comparisons.

## Measurements

Use `tools/inspect_local.py --game /path/to/Valheim --output local/evidence/before.json`
before a session and `--compare local/evidence/before.json` afterward. This hashes
selected assemblies, plugin DLLs and mod configuration, not every byte of the
installation. Its idle GPU memory observation is not game memory usage.

Opt-in plugin diagnostics collect a bounded ring of observed Unity frame deltas
and report count, p50, p95, p99 and maximum. These are not GPU execution or present
timings and need a separate frame capture tool for precise stall analysis.
The diagnostic log reports advertised GPU capacity, not used VRAM.

Use `tools/capture_metrics.py` with an existing Valheim PID, selected GPU sysfs
`mem_info_vram_used` path and a new local output CSV. It measures process RSS and
GPU-wide used VRAM. Other desktop applications contribute to the GPU number.
An example command, with locally verified values substituted:

```bash
python tools/capture_metrics.py --pid 1234 --duration 180 --interval 0.5 \
  --gpu /sys/class/drm/card1/device/mem_info_vram_used \
  --output local/evidence/route-01.csv
```

Also record runtime resident bytes, pending bytes, starts per frame, active loads,
misses, failures, evictions and reloads. A component queue budget or asset payload
sum is not a total VRAM cap. Record hardware, renderer, settings, scene coverage
and warm/cold state with each result. Do not substitute another workload's
measurements for this project's performance.

## Local installation and rollback

Build a package only after its authored inputs, native catalog and runtime have
passed the relevant checks. Follow [INSTALLER.md](INSTALLER.md) for package
verification, previews, opt-in replacement, update, rollback and uninstall.
Only the files owned under `BepInEx/plugins/ValheimImpact` may be changed.

Close the game normally before deployment. Never terminate an active world or
edit saves. Preserve unrelated mods, use an explicit isolated test profile, and
keep exact rollback metadata locally. Re-run installed-file verification after
changes. Publish code or documentation separately from any binary release;
a public repository is not a promise that an experimental package is ready.

Keep raw captures and installation details local. Public evidence should record
scoped checks and measurements without game pixels, geometry, usernames, save
identifiers or workstation paths. Link public authored-only illustrations where
useful, and identify concepts separately from actual game validation.
