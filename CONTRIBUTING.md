# Contributing to Valheim Impact

Thanks for helping build a coherent Viking fantasy overhaul. Contributions can
improve artwork, tools, runtime behavior, tests, documentation, or the quality of
our evidence. You do not need a game installation to work on ordinary Python
tests or public tracker data.

Read the [project brief](docs/PROJECT_BRIEF.md),
[art direction](docs/ART_DIRECTION.md), and
[developer setup](docs/TECHNICAL_HANDOFF.md) before implementing a change.
For a large feature, new asset family, shader change, or model replacement,
open an issue first to agree on scope and validation. Small fixes can go directly
to a focused pull request.

## Pull request workflow

1. Fork [the repository](https://github.com/Sikbik/valheim-impact), create a
   branch, and keep the change focused on one reviewable outcome.
2. Describe the exact problem or asset target. Include stable inventory IDs
   where relevant; names alone are not unique identifiers.
3. Make the change and run the relevant checks below. A behavior fix should
   include a regression that fails before the fix and checks the actual failure.
4. Review the diff for unintended files, private information, and asset rights.
5. Open a pull request explaining what changed, why, tests run, measured results,
   and remaining limitations. Include reproduction steps for failures.
6. Address review feedback. Maintainers merge only the reviewed scope and
   evidence. A pull request is not approval of an asset, biome, or release.

Use clear prose and descriptive names. Keep local machine configuration in
ignored `local/`. Avoid hardcoded personal paths in source, commands, logs,
screenshots, or metadata. Public reports should not contain account details,
email addresses, access tokens, or other secrets.

## Code and documentation checks

From an activated Python environment:

```sh
python -m pip install -r requirements-inspection.txt
python tools/asset_pipeline.py
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/refresh_tracker.py --check
python tools/check_comparisons.py --check
```

Run a narrower test module during development and the relevant broader suite
before submission. The inspection requirements include the asset dependencies.
GUI tests need a desktop and are opt-in; see [installer validation](docs/INSTALLER.md).
C# changes use the [runtime test and build commands](docs/RUNTIME.md).
Native engine changes also need the corresponding [Unity fixture](docs/UNITY_SETUP.md).
Report unavailable checks as unrun, with the missing prerequisite.

Documentation-only changes need accurate commands, working links, and a review
of claims and privacy. Do not invent test results to complete a checklist.

## Artwork submissions and rights

Code contributions use the [MIT License](LICENSE). Project artwork uses
[CC BY 4.0](assets/LICENSE). Submit only files you have the right to distribute
under the applicable license. Preserve attribution, license notices, and
modification information. Describe provenance truthfully; do not invent a
creator, production history, or ownership claim.

For each distributable artwork file, provide public provenance containing:

- Repository-relative path, SHA-256, actual dimensions, role, and color space.
- Public attribution or credited project identity, license, and rights basis.
- Sources and modifications relevant to redistribution, without private paths.
- Exact replacement target IDs, or an explicit label that it is an unmapped study.
- Reproducible fitting or processing recipe and output hashes when applicable.

For a model, explicitly record `original_geometry: false`; for all artwork,
record `original_game_pixels: false`. Remove embedded text, EXIF and other
ancillary personal metadata before calculating the submission hash. The provided
cleaner writes a new file and preserves the source:

```sh
python tools/clean_image_metadata.py local/artwork/source.png --output local/artwork/clean.png
```

Review the cleaned file, promote it to `assets/`, then record its new SHA-256.
Color profiles and compressed pixel data are preserved. PNG and WebP are
supported; keep raw source files outside tracked content.

Update `assets/provenance.json` and [assets/ATTRIBUTION.md](assets/ATTRIBUTION.md)
for the submitted files. A provenance entry or content hash does not itself
establish rights. Flag uncertain rights for review before adding the file.

Do not submit original game textures, masks, extracted geometry, game DLLs,
resource payloads, downloaded third-party packs, saves, or private exports.
Do not include symlinks to those inputs. The scoped display exceptions are
authorized 192px game-reference previews and reviewed landscape render
comparisons documented in
[tracker comparison previews](docs/TRACKER_PREVIEWS.md). Local reference
inspection can inform original artwork without otherwise placing its source
files in the repository or release.

## Asset validation

For each target, record the exact material, shader, texture property, source
texture identity and dimensions, and affected mesh/submesh/material slots.
Describe shared-material scope, including other objects or biomes that may use
it. Do not infer replacement coverage from a texture name.

Validate actual saved pixels, alpha coverage, orientation, UV placement,
scale/offset, seams, padding, channel packing, compression, and the full mip
chain. Show which checks were automated and which were visually reviewed.
Cutout art needs evidence at the material's real cutoff and at distant mips.
Companion textures, shader state, and unselected material slots must remain
correct. Label concepts and isolated previews accurately.

A native texture load proves only the cited loading or readback behavior. Game
validation must name the tested game and Unity version, platform/API, exact
assets, scene scope, capture dimensions, and outcome. Distinguish a menu fixture
from a placed-world test. Keep full original-containing captures local. Publish
sanitized measurements and summaries permitted by the evidence contract, plus
only the bounded tracker reference previews described in
[tracker comparison previews](docs/TRACKER_PREVIEWS.md).

The Balanced goal is 6 GB VRAM, 16 GB RAM at 1080p, with crisp 4K presentation
also required. Component budgets, high-resolution captures, and a successful
load are not hardware compatibility or frame-time measurements.

## Progress and biome approval

The public inputs are `assets/status/catalog.json`,
`assets/status/manifest.json`, and `assets/status/roadmap.json`.
Read [STATUS_TRACKING.md](docs/STATUS_TRACKING.md) before changing them.

Inventory progress counts completed post-inventory stages. It is displayed
separately from the nine biome approval checkpoints. Each biome needs its own
explicit reviewed evidence. Shared assets and one biome's success do not
implicitly approve another biome.

For a proposed progress change, add sanitized evidence with exact asset IDs,
stages, scope, and hashes. Update only the stages that evidence supports, then
run:

```sh
python tools/refresh_tracker.py
python tools/refresh_tracker.py --check
```

Review the generated diff and include it in the pull request. These commands do
not require game files. Do not refresh an evidence hash without reviewing the
changed evidence. Opening a PR never adds a checkmark automatically. Merged,
reviewed evidence supports progress updates; final approval remains an explicit
review decision, never an automated consequence of tests or merging.

## Biome inventory assignments

Biome membership is separate from review and completion. To make untouched
assets browsable, add exact configured associations to
`assets/status/biome-membership.json`, following
[the biome mapping workflow](docs/BIOME_INVENTORY.md). Refresh its generated data
with `python tools/prepare_biome_inventory.py` and check mode. Adding membership
must not mark artwork complete or approve a biome.

## Local game testing

Keep game files, saves, extracted references, and personal settings outside
tracked source. Use a reviewed package and the installer's explicit preview and
apply workflow. Close the game normally before any file changes. Never terminate
an active world session or assume a previous test's closed-game state still
holds. Record the package hash, runtime versions, rollback plan, and actual
validation scope without publishing local paths or save data.
