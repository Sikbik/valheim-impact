# Experimental installer

The installer manages only `BepInEx/plugins/ValheimImpact` beneath a selected
Valheim directory. It installs trusted local packages, records ownership, and
provides preview, verification, rollback, uninstall, and interrupted recovery.
It does not install BepInEx, manage other mods, or manage saves.

Packages and runtime builds remain experimental. Current validation includes
native Linux fixtures and reviewed local Linux installation. Windows code paths
and other Linux distributions require their own end-to-end validation.

## Source and desktop use

Use Python 3.12 or newer. The command-line interface and transaction core use the
standard library. The desktop application additionally requires Tk:

```sh
python -m installer gui
```

A locally built executable is `build/installer/ValheimImpactInstaller-linux-x86_64`.
It accepts the same CLI commands as the source application. A build artifact
is not a published or certified release.

1. Select the Valheim directory and a trusted package ZIP. Steam discovery also
   checks secondary libraries and standard Flatpak paths; review the destination.
2. Choose the action and profile. Experimental texture replacement is off until
   explicitly selected for a compatible package with a binding allowlist.
3. Select **Preview exact changes** and review the destination and file list.
   Changing the package, profile, action, or replacement option invalidates it.
4. Close Valheim normally and keep it closed. Apply only the reviewed preview.
   The installer refuses changes while it recognizes a running client or server.

The installer never terminates a game process. A closed-game check from an
older session is not evidence that it is safe to mutate files now.

## Command-line workflow

Replace the example paths and token with the package and preview you reviewed:

```sh
python -m installer detect
python -m installer verify-package build/experimental-linux.zip
python -m installer preview --game /path/to/Valheim --package build/experimental-linux.zip --profile Balanced
python -m installer apply --game /path/to/Valheim --package build/experimental-linux.zip --profile Balanced --review-token TOKEN_FROM_PREVIEW
python -m installer verify --game /path/to/Valheim
```

For update, uninstall, rollback, or interrupted recovery, pass `--operation
update`, `uninstall`, `rollback`, or `recover` to both preview and apply. Update
requires a package. Uninstall, rollback, and recover do not.

Use `--enable-game-replacement` on both preview and apply to opt in for an
install or update. It is part of the review token. An update without the flag
writes a disabled profile. Rollback restores the previous profile bytes,
including its enabled state. Do not use this flag for uninstall or recovery.

Apply recomputes the plan. Changed package bytes, destination state, profile,
operation, or ownership metadata invalidate the token. There is no force option
that bypasses ownership conflicts.

## Profiles

| Profile | Resident payload | In-flight payload | Concurrent loads | Starts per frame |
| --- | ---: | ---: | ---: | ---: |
| Compact | 384 MiB | 32 MiB | 1 | 1 |
| Balanced, default | 768 MiB | 64 MiB | 2 | 1 |
| High | 1536 MiB | 128 MiB | 2 | 1 |

These are owned compressed-texture component budgets, not total VRAM or RAM
limits. Balanced targets 6 GB VRAM, 16 GB RAM at 1080p; High supports evaluation
at higher resolutions. Crisp 4K presentation is a project requirement. None of
these profiles is a measured hardware guarantee, and they do not resize artwork.

The generated `profile.json` is included in the ownership receipt and backups.
The runtime consumes it only when experimental replacement is explicitly
allowed. A valid profile also needs a compatible catalog and exact binding
allowlist; enabling it cannot make an unsupported material eligible.

## Ownership, rollback, and recovery

Verification reports missing or changed owned files. Updates and rollback
refuse modified affected files. Uninstall removes only files that still match
the receipt and preserves modified or unrelated content. Review and preserve
any conflicts before retrying. File-to-directory layout changes require a
separate reviewed uninstall and inspection of remaining directories.

Before mutation, the installer creates a durable preparation marker, verifies
backups, stages replacements, and writes a recovery journal. File replacement
uses same-filesystem renames. Normal failures attempt restoration. Interrupted
transactions require a new reviewed `recover` operation. Unknown or modified
staging data blocks recovery instead of being silently removed.

Private backups and staging use deterministic encoded logical-path names ending
in `.payload`. Receipts and snapshots retain the logical destination paths.
This prevents backup DLLs from entering BepInEx's recursive plugin discovery.
Do not rename private payloads to `.dll` or manually copy snapshots into plugins.

If a process crash leaves `.installer/lock`, first close all installer instances
and confirm none is active. Remove only that stale lock, then preview recovery.
Do not delete journals or backup payloads to bypass an interrupted transaction.
If the game starts during a transaction, further file changes stop. Close it
normally before reviewing recovery.

The transaction model handles ordinary errors and process interruption. It is
not a guarantee against disk failure, filesystem corruption, or hostile local
processes racing directory changes. Keep the destination untouched while applying.

## Older storage migration

Older installer snapshots can contain discoverable DLL filenames. Normal
operations refuse game-ready status while those remain. Keep the game closed
and use the explicit migration tool:

```sh
python tools/migrate_installer_state.py preview --game /path/to/Valheim
python tools/migrate_installer_state.py apply --game /path/to/Valheim --review-token TOKEN_FROM_MIGRATION_PREVIEW
```

Migration verifies the snapshot descriptors and hashes before changing only
private payload names and storage metadata. Active DLLs, profiles, game assets,
and saves are outside that change. Unknown files, changed bytes, links,
collisions, or ambiguous state stop it.

An exclusive same-filesystem hard link creates each encoded destination before
the old name is removed. Filesystems without hard-link support fail without
removing the source. A durable migration journal supports resume through the
same preview/apply commands. After interruption, both names are accepted only
when they identify the same verified object. Empty or partial metadata writes
resume only when they match the journal's expected bytes and original snapshot.
Do not launch the game until migration reports completion and no discoverable
private DLLs remain.

## Package building

Build the runtime and validated authored native bundles first. The package tool
requires a matching catalog with native readback evidence, a staging manifest,
and source provenance. A typical authoring-project build is:

```sh
python tools/package_install.py --catalog unity/Bundles/catalog.json --bindings assets/bindings.json --version 0.0.0-local --output build/experimental-linux.zip
python -m installer verify-package build/experimental-linux.zip
```

Use a fresh output filename. Omit `--bindings` for a package without game
replacement. Optional `--runtime-dir`, `--staging-manifest`, `--provenance`, and
`--source-root` select another reviewed staging set. The builder checks exact
source, payload, bundle, and binding metadata and preserves the original binding
JSON bytes in the archive.

Package validation rejects undeclared entries, invalid hashes, unsafe paths,
links, case collisions, resource payloads, and oversized input. Hashes establish
integrity, not publisher identity; packages are unsigned. Include only files
with verified distribution rights. Read the
[contribution policy](../CONTRIBUTING.md) before preparing a distributable package.

## Installer validation

Run synthetic transaction and package tests without changing a real game:

```sh
python -m unittest discover -s tests -p 'test_installer*.py' -v
```

On a desktop with Tk, enable the GUI fixture explicitly:

```sh
VALHEIM_INSTALLER_GUI_TESTS=1 python -m unittest discover -s tests -p 'test_installer*.py' -v
```

The storage tests exercise install, disabled update, rollback, uninstall, crash
recovery, old-format migration, and recursive DLL scans. Migration regressions
include partial metadata writes and preservation of unrecognized bytes. Frozen
executable validation has also exercised enabled install, disabled update,
rollback, uninstall, and private storage against temporary game fixtures.
These results do not establish compatibility with every filesystem or platform.

To build a standalone executable, install PyInstaller in a Python environment
with working Tk, then run:

```sh
python tools/build_installer.py
```

That command checks CLI startup. Separately verify the relocated executable's
GUI, exact package hash, full fixture workflow, and recursive DLL discovery after
updates and rollback. Record the executable SHA-256, size, platform, and package
hash with each new result; a previous binary's success does not validate a rebuild.
