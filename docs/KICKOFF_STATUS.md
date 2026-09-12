# Development status guide

Valheim Impact has an authored asset pipeline, an owned asynchronous texture
runtime, and a reversible local installer. Selected stone, timber, and
roof-atlas albedos have native and guarded game-menu evidence. This remains a
partial visual overhaul, with original geometry and companion material channels
retained.

The [public tracker](https://sikbik.github.io/valheim-impact/) is the current
entry point for exact asset identities, evidence, unchecked stages, and biome
checkpoints. Milestone documents describe scoped results; they are not blanket
approval of the game or a hardware configuration.

## Technical milestones

| Record | What it establishes |
| --- | --- |
| [Milestone 1](MILESTONE_01.md) | Authored probe pipeline, native texture validation, scheduler lifecycle, and installer foundation. |
| [Milestone 2](MILESTONE_02.md) | Exact material matching, restorable demand leases, opt-in installation, and initial game-menu integration. |
| [Milestone 3](MILESTONE_03.md) | Fitted 67-degree roof atlas, bounded multi-slot discovery, and selected stone/timber/roof game fixtures. |
| [Milestone 4](MILESTONE_04.md) | Public evidence workflow, standard straw-fringe preparation, and constrained native cutout binding support. |

Historical check counts and artifact hashes belong to their cited snapshots.
They do not validate a later source or package revision. Native fixture cleanup
and ordinary game-process exit are different results and must remain distinct.

## Current contribution priorities

- Resolve standard straw-fringe mip coverage and review full roof UV placement,
  repeat edges, compression, and two-sided game rendering.
- Author and validate the separate corner fringe and remaining roof materials.
- Evaluate placed Meadows buildings, LOD transitions, weather, interiors, terrain,
  foliage, and water as a coherent scene.
- Broaden exact asset evidence without inferring coverage from shared names or
  increasing an allowlist before review.
- Collect representative hardware, route, residency, and frame-time measurements.

Native Linux with Vulkan is the exercised engine path. Windows, other APIs,
model/shader streaming, complete biome appearance, and final art approval remain
separate work. Balanced targets 6 GB VRAM, 16 GB RAM at 1080p, with crisp 4K
presentation also required. These targets are not yet measured guarantees.

## Start contributing

Read [CONTRIBUTING.md](../CONTRIBUTING.md), the
[asset plan](ASSET_PLAN.md), and [developer setup](TECHNICAL_HANDOFF.md).
Keep original game inputs and private configuration local. For progress changes,
use the exact catalog IDs and reviewed evidence described in
[STATUS_TRACKING.md](STATUS_TRACKING.md). Inventory progress and the nine biome
approval checkpoints are independent. A PR or passing test does not grant final
approval automatically.
