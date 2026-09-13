# Developer setup and handoff

This guide covers portable contributor setup. Keep the repository, local tool
configuration, generated artifacts, and installed game separate. Read the
[project brief](PROJECT_BRIEF.md) and [art direction](ART_DIRECTION.md) before
starting a feature or asset family.

## Choose the required environment

| Work | Requirements |
| --- | --- |
| Installer CLI and transaction fixtures | Python 3.12 or newer. |
| Asset processing and Python suite | Python environment with `requirements-inspection.txt`, which includes asset dependencies. |
| Desktop installer | Python with Tk and a working desktop display. |
| Core C# regression tests | Python, .NET runtime, and Roslyn compiler. |
| Runtime plugin compilation | Core build tools plus read-only Valheim/Unity and BepInEx assembly references. |
| Native authored bundle validation | Unity 6000.0.75f1 with Linux build support, Vulkan, and the Built-in Render Pipeline. |
| Public tracker metadata | Python and the checked-in sanitized catalog, evidence, and bounded comparison previews. |

Native Linux/Vulkan is the currently exercised engine path. Compilation support
or recognized platform metadata does not establish Windows compatibility.

## Python setup

Run from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-inspection.txt
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/prepare_status_site.py --check
```

For asset processing alone, `requirements-assets.txt` is sufficient. The
installer CLI does not need those image libraries. A narrower test selection is
useful during development; run all checks affected by the final change before
submitting a PR. Report skipped GUI or native tests explicitly.

## Local configuration and outputs

Copy `config/local.example.json` to ignored `local/build.json` and replace its
placeholders with your compiler and game paths. Do not submit that local file.
The runtime build accepts command-line paths as well; see [RUNTIME.md](RUNTIME.md).

`build/`, `.venv/`, `local/`, Unity cache directories, bundles, raw captures, and
extracted references are development outputs. Check the diff before submission,
even when ignore rules are present. Never copy game DLLs into source to make
another machine compile.

The ordinary build and test tools write within the repository's staging
locations. Some validators regenerate tracked evidence reports. Review those
diffs and their hashes before including them in a contribution. A newly written
report is not automatically approved evidence.

## Common workflows

For runtime policy changes:

```sh
python tools/build.py --config local/build.json --test
```

For game-reference compilation, after configuring a local game and BepInEx:

```sh
python tools/build.py --config local/build.json
```

For authored material preparation:

```sh
python tools/asset_pipeline.py
python tools/validate_staging.py
python tools/prepare_unity.py
```

The last command stages inputs only and uses the public Unity package manifest
for its separate generated project. Before opening the interactive `unity/`
project in a fresh checkout, create its local manifest:

```sh
cp unity/Packages/manifest.public.json unity/Packages/manifest.json
```

The local manifest and resolved package lock are ignored state. Preserve an
existing workstation configuration and test the public template in a separate
project. Follow [UNITY_SETUP.md](UNITY_SETUP.md) to execute native builds and
fixtures, and [INSTALLER.md](INSTALLER.md) to make and review a local package.
None of these build commands installs the runtime.

For an evidence-backed tracker update:

```sh
python tools/prepare_status_site.py
python tools/prepare_status_site.py --check
```

Review exact asset IDs and stage scope first. Public inputs are
`assets/status/catalog.json`, `manifest.json`, and `roadmap.json` in that same
directory. Keep post-inventory progress separate from independent biome
approval. See [STATUS_TRACKING.md](STATUS_TRACKING.md).

## Validation levels

Synthetic tests can verify parsing, bounds, ownership transitions, and failure
handling. Native fixtures add actual Unity serialization, async lifecycle,
material state, and destruction checks. A guarded main-menu fixture adds a
small number of loaded game mesh/material pairs. Placed-world visual and
performance tests add a different scope and must be recorded separately.

For any handoff, include the changed source/artifact hashes, commands and exit
results, prerequisites, exact asset identities, screenshots or summaries that
may be shared, and what remains untested. Preserve failures and limitations.
Do not equate texture loading with model or shader streaming, component payload
budgets with total memory, or a 4K capture with completed 4K quality validation.

The Balanced goal remains 6 GB VRAM, 16 GB RAM at 1080p. Representative hardware
and routes are required before claiming that target is met.

## Game and data protection

Inspect only a legally obtained local game installation. Keep original pixels,
UV and geometry exports, game assemblies, third-party packs, saves, and private
logs outside public source and packages. Scoped display exceptions cover the
authorized 192px tracker references and reviewed landscape render comparisons in
[tracker comparison previews](TRACKER_PREVIEWS.md), which never permits full
sources, resource streams, or extracted geometry. Sanitize other public evidence
instead of copying raw inspection output. Do not follow resource-file symlinks
when staging.

Game tests require explicit local installation and rollback. Confirm the game
is closed immediately before changing files, and never terminate an active
world session. Do not attach a temporary diagnostic plugin to an ordinary play
session. Preserve the exact original and owned-object boundaries in fixtures.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for rights, attribution, PR review,
and evidence requirements.
