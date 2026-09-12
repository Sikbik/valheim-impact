# Milestone 4: evidence workflow and cutout preparation

This milestone adds a public evidence workflow and prepares a standard
straw-fringe candidate and its constrained material-binding support. It does
not deploy the candidate or approve a roof, biome, or complete visual overhaul.

## Public progress

The [project tracker](https://sikbik.github.io/valheim-impact/) presents exact
texture and mesh identities, searchable status, evidence, project milestones,
and independent biome checkpoints. The catalog records 3,187 textures and
10,336 mesh objects. These counts describe inventory, not visible replacement
coverage or authored model count.

Public inputs live in `assets/status/catalog.json`, `manifest.json`, and
`roadmap.json` in that directory. `tools/prepare_status_site.py` validates evidence
hashes and prepares snapshots without original game files. See
[STATUS_TRACKING.md](STATUS_TRACKING.md) for the current contract and
[CONTRIBUTING.md](../CONTRIBUTING.md) for PR requirements.

Inventory progress counts post-inventory stages. Each of the nine biome
checkpoints requires separate reviewed evidence. A PR, a successful fixture, or
a source merge never grants final approval automatically. Original geometry
remains in use; no authored model replacement is implied by texture progress.

## Standard straw candidate

The original standard straw-fringe artwork is fitted to 512px RGBA with
measured alpha. Its retained RGB source contained a painted background rather
than usable transparency. A separate deterministic process derives a mask from
that authored image only. It does not copy a game mask or recover original
transparency.

The base image has 54.93% coverage at cutoff 0.69. Its two smallest uncompressed
mips lose all cutout coverage. Compression, repeat edges, full roof UV placement,
two-sided shading, native sampling, and game appearance remain unchecked. The
corner fringe is separate pending work. See [STRAW_FRINGE.md](STRAW_FRINGE.md).

Public artwork copies have had ancillary file metadata removed. The
[normalization record](evidence/artwork-file-normalization.json) connects old and
new file hashes and confirms unchanged decoded pixels and compressed pixel
chunks. This file normalization is not a new visual validation result.

## Native cutout adapter

Schema 2 supports explicit cutout state for `Custom/Piece`, preserving the
opaque default. Exact mode, cutoff, culling, depth write, blend factors, render
queue, and alpha keywords are checked at discovery, before async adoption, and
while applied. Missing required stored values reject a match. Only the selected
owned albedo changes.

The [native cutout fixture](evidence/cutout-binding-native.json) passed 35 checks
and finished with zero pending, resident, retiring, and leased ownership. It
covered stored-float presence, exact admission, actual keyword mutations,
asynchronous state changes, foreign texture preservation, restoration, and
cleanup. The recorded Core run passed 188 assertions.

Package validation also rejects cutoffs that are within range as Python doubles
but round to zero or one as runtime float32 values. It preserves the original
binding JSON bytes. These checks establish the staged adapter with an owned
diagnostic shader; they do not validate the game shader or straw candidate in
an actual game scene.

## Scope left open

No new candidate deployment or actual binding-allowlist addition was part of
this cutout milestone. The previous opaque game-fixture evidence remains
separate in [Milestone 3](MILESTONE_03.md). Placed buildings, weather, LODs,
representative hardware, complete 4K appearance, and native model/shader
streaming remain unvalidated. The Balanced target remains 6 GB VRAM, 16 GB RAM
at 1080p, with crisp 4K presentation also required.
