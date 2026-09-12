# Project brief

Valheim Impact is an original Viking fantasy visual overhaul for Valheim.
It aims to make the world crisp and visually coherent through painterly
materials, clear shapes, and expressive lighting while preserving the game's
recognizable architecture, creatures, equipment, landscape, and atmosphere.

## Visual goals

Use smooth color groups, restrained texture noise, readable silhouettes, and
selective material detail. Wood, stone, cloth, leather, metal, thatch, foliage,
and snow should remain distinct in changing light. Preserve weather, navigation
cues, combat readability, and each biome's character.

Textures, normal maps, material response, atmosphere, water, and lighting belong
to one visual system. Higher resolution should improve useful detail and texel
consistency. It should not introduce distracting noise or require every asset
to use the same dimensions.

## Development scope

Begin with a coherent Meadows scene before extending the approach across the
biomes. The initial runtime work uses authored textures with existing game
shaders and explicit material bindings. Selected stone, timber, and roof-atlas
replacements have limited native and game-menu evidence. A menu fixture does
not establish the appearance or stability of a complete playable biome.

The longer-term scope includes terrain, vegetation, construction, equipment,
creatures, water, effects, and lighting. Model and shader changes need separate
design, compatibility, lifecycle, and validation work. Texture streaming success
does not demonstrate model or shader streaming.

## Technical goals

Use metadata-first validation, asynchronous native texture loading, shared
content ownership, bounded work queues, demand-based residency, and safe
restoration. Preserve original material state whenever a replacement is absent,
invalid, or still loading. Keep development outputs separate from the game.

Native Linux with Vulkan is the current validated engine path. Windows and
other graphics APIs are future validation work. Balanced targets **6 GB VRAM,
16 GB RAM at 1080p**. Crisp 4K presentation is also required. These remain
targets until measured on representative hardware, scenes, and routes.

## Acceptance criteria

- Valheim's Nordic identity, silhouettes, weather, and gameplay remain readable.
- Authored materials form a consistent visual language at near and far distances.
- UV layouts, transparency, mip levels, and companion material channels behave
  correctly on the identified assets.
- Repeated exploration, unloading, and return visits retain correct fallback
  behavior and bounded ownership without unsupported performance claims.
- Installation is reviewable and reversible, with unrelated files and saves
  outside the installer's ownership.
- Every distributed asset has clear rights, public provenance, and a content hash.

## Evidence and contributions

The [tracker](https://sikbik.github.io/valheim-impact/) records exact asset
identities and scoped evidence. Inventory progress and biome approval are
separate measures. Each of the nine biome checkpoints requires its own reviewed
evidence; approval is never inferred from another biome or from a pull request
being opened.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for submission and validation rules.
