# Unity authoring setup

Use Unity **6000.0.75f1**, matching the current authored bundle contract and the
recorded game fixtures. The project uses the Built-in Render Pipeline, Linear
color space, and native Linux/Vulkan validation. Install the matching Linux
build support through your Unity installation tools.

A different Editor, game version, or graphics API requires compatibility work
and fresh evidence. Do not silently rebuild bundles for a new version or switch
the project to another render pipeline.

## Initialize the public project

For a fresh checkout, create the local package manifest before opening `unity/`:

```sh
cp unity/Packages/manifest.public.json unity/Packages/manifest.json
```

The public manifest contains the minimal contributor dependencies. The local
`manifest.json` and Unity's resolved `packages-lock.json` are ignored files.
Do not overwrite a configured workstation manifest just to test the template;
use a separate checkout or the generated staging project. Keep local integration
packages and credentials out of contributions.

## Prepare owned inputs

Install the Python asset requirements in a virtual environment. From the
repository root:

```sh
python -m pip install -r requirements-assets.txt
python tools/asset_pipeline.py
python tools/validate_staging.py
python tools/prepare_unity.py
```

The pipeline reads `assets/meadows/prototype.json` by default. It produces fitted
images, BC3/DXT5 payloads with full mip chains, and a staging manifest under
`build/staging/meadows/`. The staging validator records its report in
`docs/evidence/asset-validation.json`; review any tracked evidence changes before
including them in a PR.

The final command prepares `build/unity-project/` with only owned inputs, the
public package manifest, and the build template. It does not execute Unity or
produce a native validation result.
No game files are needed for this preparation path.

## Build native bundles

Use one of these two workflows.

For a separate staging project, supply your installed Editor executable:

```sh
python tools/prepare_unity.py --editor /path/to/Unity
```

This runs the selected Editor in batch mode with Vulkan and the Linux64 target,
calling `MeadowsBuild.Build`. Do not use it on a project already open in another
Editor instance. Review `build/unity-project/editor-build.log` and the generated
catalog before claiming success.

For interactive authoring, stage into the tracked project template:

```sh
python tools/prepare_unity.py --authoring
```

Open `unity/` in the matching Editor, using Vulkan. Run **Valheim Impact > Build
owned Meadows probes**. This preserves the authoring project's settings and
packages; `--authoring` cannot be combined with `--editor`. Build outputs appear
under `unity/Bundles/`.

The build verifies its Editor, Vulkan, and Linear-color-space prerequisites,
constructs owned texture assets, builds native bundles, validates native texture
data, and captures base-mip GPU readback. Native textures are non-readable after
loading and use explicit sRGB albedo or linear normal data. Do not replace a
failed build with a hand-edited success flag in the catalog.

For an authoring-project build, additional inspection uses:

```sh
python -m pip install -r requirements-inspection.txt
python tools/validate_native.py
```

This command reads `unity/Bundles/` and the matching staged payloads. It checks
bundle and readback hashes, texture metadata, payload bytes, and rendered
samples. It does not build bundles or test game material assignment. The script
currently targets the authoring-project output, not the separate batch project's
bundle directory.

## Native runtime fixtures

`tools/unity/OwnedStreamingProbe.cs` and `MaterialBindingProbe.cs` contain finite
Editor fixtures for ownership, async loading, binding, and drain behavior.
`CutoutBindingFixture.shader` is an owned diagnostic shader for the cutout-state
checks. Compile or stage the current runtime source and fixture together in an
isolated Editor project before running them. Record the source hashes, Editor
version, API, report, and cleanup outcome.

The fixture shader is a test input. Passing its checks does not prove how a
particular game shader renders authored transparency. Tests must preserve
borrowed engine objects and account for owned textures until destruction is
acknowledged. A successful process exit is not a substitute for a drain check.

## Contribution boundaries

Keep `Library/`, `Temp/`, `OwnedInputs/`, bundles, generated probe objects, raw
captures, and other generated state out of source contributions. Preserve the
checked-in project version and build template. Do not import original game
textures, exported meshes, or game assemblies into tracked assets.

Public evidence should identify exact assets and measured outcomes without
including original payloads, private paths, or account state. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for rights and evidence requirements.

## Explicit cutout mip sampling

The finite `tools/unity/CutoutSamplingProbe.cs` fixture belongs in the local
project's `Assets/GeneratedRuntime/Editor/` folder. Stage
`tools/unity/CutoutSampling.shader` under `Assets/GeneratedRuntime/` and let the
Editor compile before building the authored bundles. The probe requires the
stopped Unity 6000.0.75f1 Editor, Vulkan and Linear color. It uses only owned
textures and a diagnostic shader, without modifying a game installation.

After `MeadowsBuild.Build()` completes, evaluate each call in that Editor:

```csharp
CutoutSamplingProbe.Run("straw_fringe_standard_albedo", 0.69f);
CutoutSamplingProbe.Run("straw_fringe_corner_albedo", 0.69f);
```

Then validate the readbacks from the asset Python environment:

```sh
python tools/validate_native.py
python tools/validate_cutout_sampling.py straw_fringe_standard_albedo
python tools/validate_cutout_sampling.py straw_fringe_corner_albedo
```

Point samples cover every mip. Fractional trilinear samples are diagnostics;
saved 8-bit alpha cannot recover every sub-byte shader cutoff decision. The
reports distinguish those rounding differences and record destroyed owned
objects. These fixtures do not validate the game shader, roof undersides,
weather, world appearance, screen-space coverage or frame times.
