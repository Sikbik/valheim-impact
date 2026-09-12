# Texture coverage inventory

The read-only snapshot from 2026-09-12 contains 3,179 `Texture2D` objects, four
`Texture3D` objects, two cubemaps, and two texture arrays. It links 3,907 materials,
77 shaders, 93,734 serialized renderer records, and 10,336 mesh objects across all
283 bundles named by the installed SoftRef asset locations and dependencies.
The manifest has 21,884 asset locations and 4,755 image source paths. Image paths
and compiled texture objects have different counts, including imported sprites
and shared assets.

These are metadata counts. They do not measure loaded objects, visible surfaces,
replacements, draw calls, or performance. Serialized prefab copies can repeat
renderer records. The snapshot has 52 unresolved built-in resource links and 36
null shader pointers. No non-built-in external texture or shader links remain
unresolved in this snapshot.

## Reproduce locally

Use a Python environment with UnityPy 1.25.3 and Pillow. Configure the game path
for the machine. The output must be beneath this project's ignored `local/`
directory, outside the game installation. The default output is
`local/texture-inventory`; the recorded complete snapshot used the command below.

```bash
/path/to/unity-python/bin/python tools/texture_inventory.py \
  --game /path/to/Valheim \
  --output "$PWD/local/texture-inventory/complete"
python -m unittest discover -s tests -p test_texture_inventory.py
```

Optional `--manifest` and `--bundles` arguments override the SoftRef input paths.
`--bundle c4210710` selects a partial single-bundle scan. `--scope image-bundles`
selects only bundles with image source paths and labels the report accordingly;
it can omit dependency-only shader resources. The default `--scope all` includes
both asset-bearing bundles and dependency-only bundles. Stale bundle files not
named by the current manifest are outside this snapshot.

The tool hashes input bundles and the manifest, records file sizes and modified
timestamps, and checks each bundle for changes during its scan. It never writes
to the game, follows output symlinks, starts the game, or changes a world. Texture
image decoding is limited to the selected materials. Mesh exports default to at
most three distinct meshes per selected material, including cross-bundle links.
Configurable limits default to 1,024 bundles, 3 GiB per input bundle, and 750,000
objects per bundle. One bundle parser is retained at a time. These are work/input
bounds, not a measured process-memory cap.

The full `inventory.json` and `summary.json` remain local. Original PNGs, OBJ
meshes and UV wire images stay in `local/texture-inventory/complete/references/`.
OBJ export mirrors Unity X and reverses triangle winding; UV0 is unchanged.
Do not place these original references in staging, tracked source or releases.
The tracked [coverage metadata](../assets/coverage.json) contains compact facts,
identities and estimates only.

The final end-to-end repeat produced byte-identical metadata and all 44 local
reference artifacts, with 17 material/mesh UV samples and zero extraction errors.
The nine fixture tests cover identity, conflict-aware deduplication, category
exclusions, manifest dependency scope, output paths, selected-submesh UV bounds
and bounded cross-bundle mesh selection.

## Identity and category estimates

An object identity combines its serialized CAB file name with its signed path
ID. Texture names are not unique identities. Exact material links retain shader
identity and name, texture property, texture object identity, scale, offset,
saved numeric/color properties, keywords, render queue and tags. Renderer records
retain material slots and mesh pointers. Repeated observations deduplicate by
object identity and reject conflicting metadata. This is metadata deduplication,
not a claim that matching names or matching pixels share one allocation.

Category estimates use paths and filenames. UI and supporting-map checks take
precedence over world categories. `_MainTex` links provide a separate observed
material-use count, but some shaders use other albedo properties or runtime
assignments. The category table is useful for planning, not a visible completion
percentage.

| Estimated category | Texture objects | Unique textures linked by `_MainTex` |
| --- | ---: | ---: |
| Building | 274 | 242 |
| Character | 196 | 140 |
| Effect | 95 | 75 |
| Equipment/item | 578 | 435 |
| Support map | 1,226 | 6 |
| Terrain/water | 44 | 7 |
| UI | 187 | 60 |
| Unclassified | 220 | 116 |
| Vegetation | 39 | 35 |
| World surface | 328 | 242 |
| Total | 3,187 | 1,358 |

Excluding estimated UI, effects and support maps leaves 1,217 `_MainTex`-linked
metadata candidates without a validated binding record in this inventory. This
includes unclassified objects and omits other texture properties, so it is not
the number of visible textures remaining. Authored visible coverage remains
unset until separate native binding and rendered evidence are supplied.

## First surface evidence

The local inspection extracted original alpha and 17 material/mesh UV samples
across six distinct materials. The selected material names include two different
`stone_huge` identities. UV extraction establishes layout evidence; it does not
validate authored rendering across every mesh, LOD, weather state or biome.

| Material | Shader | Original `_MainTex` | Finding |
| --- | --- | --- | --- |
| `stone_huge`, ordinary stone source | `Custom/StaticRock` | `rock_256`, 512 x 512 | Continuous stone surface on split rock UV islands. Alpha spans 254 to 255. Preserve the original normal and moss channels. |
| `stone_huge`, Deep North source | `Custom/StaticRock` | Same exact `rock_256` object | Separate material under `DeepNorth/HotSpring`. A name/shader/base-texture mapping reaches this material too. Its rendered result has not been validated. |
| `woodwall` | `Custom/Piece` | `Planks5c_low`, 128 x 128 | Continuous horizontal timber grain. Fully opaque. Preserve scale approximately (-0.56, 0.12) and offset (0, 0.014). |
| `woodpole` | `Custom/Piece` | Same exact `Planks5c_low` object | Fully opaque. Preserve scale approximately (0.3, 0.13), zero offset and its distinct original normal map. |
| `wood_roof_mat` | `Custom/Piece` | `wood_roof_d`, 128 x 128 | Two-region atlas. The measured practical fit uses the left 3/8 for thatch and the right 5/8 for timber, preserving a wide unused UV gap. Eight selected meshes fit without crossing regions. |
| `beech_bark` | `Custom/Vegetation` | `beech_bark`, 512 x 512 | Atlas with bark, endgrain and edge regions, actual alpha 0 to 255. Saved `_Mode=3`, `_ZWrite=0`. Defer from the opaque set. |

The ordinary stone material is
`Assets/world/Props/stone/stone_huge.mat`, path ID `-7750279688942954104`.
Its full rock sample `Rock_3_Untitled` has 136 vertices and 202 triangles, with UV0
bounds approximately (0.009125, 0.012101) to (0.996559, 0.985989). The local OBJ is
`references/9d1363d98f9e24cd.obj`. Cross-bundle pointers connect this material to
22 renderer records and two unique meshes. The separate Deep North material has
path ID `-652227259079398966`, 177 renderer records and 45 unique meshes. All these
objects use serialized file `CAB-8923bd833c4171316cf3c761b642c1c8` for the material
and texture identities.

The `wood_pole/New` sample is `references/30e1f6076349ad28.obj`, with 66 vertices
and 44 triangles. Its UVs extend approximately from -0.0205 to 1.0205 before
material scale/offset. The original timber image and wrap settings must therefore
remain compatible with sampling beyond the unit square. The `woodwall` material
also appears on roofs and older prefab pieces, so its replacement scope is shared
construction timber rather than one wall mesh.

Proceed with dedicated stone and timber tile artwork and an explicit shared
material scope. Preserve atlas structure before enabling roof or bark mappings.
Native material binding tests, rendered comparisons and representative LOD/weather
checks remain separate evidence requirements.
