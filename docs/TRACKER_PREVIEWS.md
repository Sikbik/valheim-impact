# Tracker comparison previews

The public tracker presents a bounded reference preview beside an authored
replacement only when an exact inventory identity is known. The current catalog
contains 13,523 serialized texture and mesh identities. Reference previews are
available for 13,463 identities; 60 entries have an explicit unavailable reason.
A displayed preview, an unavailable image, or an empty replacement position does
not change an asset's recorded progress stages.

## Rights and attribution

The `before` sprite sheets contain small comparative excerpts from Valheim.
Valheim artwork belongs to Iron Gate. These reference excerpts are identified as
game reference material and are excluded from the project's CC BY 4.0 artwork
license. They are published only for identification and comparison in the
tracker. Full textures, resource streams, extracted geometry, and raw capture
inputs remain outside the public repository and release archives. The separate
landscape gallery publishes reviewed rendered comparisons as described below.

## Landscape comparison gallery

The [landscape gallery](https://sikbik.github.io/valheim-impact/landscape/) presents
matching rendered views at 1080p and 4K. It includes original versus candidate
materials and controlled revision comparisons. These are native test-scene
captures, not screenshots of a played world. Each view states its fixed controls
and the changes being compared.

Only the reviewed image outputs are published as metadata-clean WebP files.
The gallery records their hashes, dimensions and source PNG hashes. Full source
textures, meshes, shader resources, local paths, logs and raw capture reports
remain private. Both resolutions preserve the native pixel dimensions; WebP
encoding is a lossy web presentation copy rather than the lossless validation
artifact. The gallery initially loads one 1080p pair and loads other views or
4K only when selected.

Both sides can contain original Valheim geometry, shaders or companion imagery.
Credit for that game content belongs to Iron Gate. The mixed rendered captures
in `status-site/public/landscape/images/` are excluded from the project's CC BY
4.0 artwork license. The separate, original authored texture files retain their
own registered artwork license. Publication of a comparison does not advance
any inventory, biome, performance or final-art stage.

The inventory tracker's authored `after` tiles come from sources registered in
`assets/provenance.json` with `original_game_pixels: false`. The project artwork
license applies to those standalone authored tiles, not mixed landscape render
captures. A side-by-side display does not grant
project rights in the game reference, and it does not establish UV fit, native
loading, scene coverage, biome completion, or final approval.

## Public schema

`status-site/public/comparisons/index.json` uses schema version 1. Its root fields
are:

| Field | Meaning |
| --- | --- |
| `schema_version` | Schema version, currently `1`. |
| `tile_size` | Fixed sprite width and height, currently `192` pixels. |
| `columns` | Fixed sheet width in tiles, currently `8`. |
| `catalog_sha256` | SHA-256 of the exact `assets/status/catalog.json` bytes. |
| `sheets` | Indexed WebP sheets containing bounded game-reference sprites. |
| `assets` | Object keyed by exact serialized catalog ID. |

Each sheet is a 1536 by 1536 WebP with eight columns and eight rows. Its record
contains the basename, SHA-256, decoded dimensions, `kind: reference-preview`,
`original_game_pixels: true`, and the game-reference license exclusion. Each
available asset has one `before` object containing the sheet basename, aligned
`x` and `y` coordinates, a 192 by 192 extent, and the catalog kind. Each
unavailable asset has `before: null`, `status: unavailable`, and a nonempty
reason.

An optional `after` list contains one or more authored alternatives for the
same exact asset. Every item records a safe WebP basename and hash, the
repository-relative authored source and source hash, a label, and a narrow scope
statement. An after image is at most 512 by 512 pixels and 256 KiB. Its source
must have matching authored provenance and the exact asset must have an
`authored` stage in `assets/status/manifest.json`.

## Exact authored mappings

The initial comparison set maps only these authored texture sources:

| Exact inventory ID | Authored source | Display scope |
| --- | --- | --- |
| `CAB-8923bd833c4171316cf3c761b642c1c8:3915711535683601241` | `assets/meadows/granite-surface-v1.png` | Authored granite albedo source for the mapped texture. |
| `CAB-8923bd833c4171316cf3c761b642c1c8:-8477877035390755812` | `assets/meadows/timber-surface-v1.png` | Authored timber albedo source for the mapped texture. |
| `CAB-8923bd833c4171316cf3c761b642c1c8:2604212865869356004` | `assets/meadows/roof-atlas-v1.png` | Authored roof atlas albedo for the mapped texture; original companion fringe is outside this image. |
| `CAB-8923bd833c4171316cf3c761b642c1c8:7569662044289518567` | `assets/meadows/straw-fringe-standard-v1.png` | Authored standard fringe candidate; Scoped UV and native mip sampling reviewed; actual game shader and game review remain pending. |
| `CAB-8923bd833c4171316cf3c761b642c1c8:5625371641502064416` | `assets/meadows/straw-fringe-corner-v1.png` | Authored corner fringe candidate; Scoped UV and native mip sampling reviewed; actual game shader and game review remain pending. |

Every other asset displays an explicit replacement placeholder. Mesh entries do
not claim an authored mesh simply because an authored material has been tested
on retained game geometry.

## Local generation

`tools/build_inventory_previews.py` creates the reference sheets from an
explicitly supplied local inventory and local bundle directory. Run it only when
display of the bounded comparative previews is authorized. The generator groups
exact serialized IDs by bundle, decodes only supported texture and mesh types,
and writes 192px cached tiles before packing 64 tiles per sheet. Texture images
are fitted without upscaling. Mesh entries use a neutral orthographic shape
preview and do not include original material imagery. Unsupported or bounded-out
objects remain unavailable with a reason.

Keep the generator's inventory, bundle inputs, cache, and private error log in
ignored local storage. Never publish those inputs or follow resource-file
symlinks. The checked-in comparison directory contains only the manifest,
bounded WebP sheets, and registered authored after images.

## Refreshing authored replacements

Edit the reviewed mappings in `assets/status/comparisons.json` when an exact
asset receives original artwork. Each mapping pins its source hash, preview
basename, label and scope. After adding supported authored evidence and
provenance, run:

```sh
python tools/refresh_comparisons.py
python tools/refresh_comparisons.py --check
```

The helper fits metadata-clean WebPs from registered artwork and updates the
comparison index while retaining the reference sprites. It requires no game
installation. Include the recipe, generated images and updated index in the PR.

## Validation

Run the read-only validator after changing the catalog or any comparison file:

```sh
python tools/check_comparisons.py --check
```

The validator requires the comparison ID set to equal the catalog ID set and
checks the pinned catalog hash, strict JSON parsing, sprite kind and bounds,
sheet and source hashes, decoded dimensions, WebP container metadata, authored
provenance and stages, safe basenames, symlinks, orphan WebPs, and file budgets.
The limits are 4 MiB per sheet, 256 sheets, 256 KiB per after image, and 64 MiB
for all published comparison WebPs. It reports aggregate counts and relative
filenames without publishing local source paths or metadata values.

The unit coverage is in `tests/test_comparisons.py` and
`tests/test_inventory_previews.py`. Run it with:

```sh
python -m unittest tests.test_comparisons tests.test_inventory_previews -v
```
