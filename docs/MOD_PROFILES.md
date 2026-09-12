# Local mod profiles

`tools/mod_profile.py` reversibly disables the existing native Linux Valheim
plugins for isolated Valheim Impact tests. It moves the complete
`BepInEx/plugins` directory into a local profile vault, then creates a fresh
empty `BepInEx/plugins`. Install only the intended Valheim Impact runtime in that
fresh directory through the separate installer workflow.

The tool leaves BepInEx core, configuration, patchers, game files, characters,
and worlds in place. It refuses isolation when `BepInEx/patchers` contains any
entries, because moving plugins alone would leave those patchers active.
External injectors or custom launch commands are outside this tool's scope.

This utility is for local development, separate from the public installer.
The vault contains the user's original third-party mods. Keep it outside the
game directory, source control, and all release archives. It must share the
plugins directory's filesystem. A cross-filesystem request fails instead of
copying large packs. The current implementation requires Linux `renameat2`
support and fails if an atomic rename without replacement is unavailable.

## Inspect and isolate

Set the paths to the installation and a local vault. This example uses the
usual native Steam location, but every command requires explicit paths.

```bash
vi_game="$HOME/.local/share/Steam/steamapps/common/Valheim"
vi_vault="$HOME/.local/share/valheim-impact/mod-profiles"
vi_profile="legacy-before-valheim-impact"

python tools/mod_profile.py inspect \
  --game "$vi_game" --vault "$vi_vault" --profile "$vi_profile"
```

`inspect` is read-only. It reports the active and saved inventories, patcher
entries, journal phase, and running Valheim processes. When a journal exists,
`legacyInventoryMatches` reports whether the saved original inventory still
matches. No vault is created by inspection.

Once the game is closed normally, the explicit isolation command is:

```bash
python tools/mod_profile.py isolate \
  --game "$vi_game" --vault "$vi_vault" --profile "$vi_profile"

python tools/mod_profile.py inspect \
  --game "$vi_game" --vault "$vi_vault" --profile "$vi_profile"
```

Successful isolation reports `phase: isolated`. The old directory is at
`$vi_vault/$vi_profile/plugins` and its journal is at
`$vi_vault/$vi_profile/journal.json`. The active plugins inventory contains only
its empty root directory. Existing profile names are never overwritten or
reused, including after restoration. Choose a new name for a later isolation.

All mutation commands call `installer.discovery.running_valheim()` before
preparation and again before game directory changes. They refuse both a running
game and an unavailable process check. They never stop a process. Do not launch
Valheim while a profile operation is in progress. An advisory lock on the game
directory prevents simultaneous instances of this utility, even with different
vault arguments. It does not control Steam or another mod manager.

## Restore

Close the game normally. Inspect the active directory and explicitly preserve
or move any new Valheim Impact content before restoration. Keep the active
`BepInEx/plugins` directory itself in place; the journal records its identity.
An installer uninstall may leave its local receipt and backups, so check the
actual remaining directory content. The profile tool never removes that content
or merges it into the legacy tree.

```bash
python tools/mod_profile.py inspect \
  --game "$vi_game" --vault "$vi_vault" --profile "$vi_profile"

python tools/mod_profile.py restore \
  --game "$vi_game" --vault "$vi_vault" --profile "$vi_profile"
```

Restoration refuses a nonempty or replaced active directory. It verifies the
saved legacy inventory, removes only the recorded empty directory with `rmdir`,
and moves the original tree back with an atomic rename that cannot overwrite an
existing destination. Success reports `phase: restored`. The journal remains in
the vault as evidence; no legacy plugin directory remains in that profile.

## Interrupted operations

The journal is written and synced before the first legacy directory move and
before restoration removes the empty active directory. Each newly created vault ancestor is linked durably by syncing its parent
before any game rename. Parent directory syncs also follow renames. The pending phases are `isolating` and `restoring`.

```bash
python tools/mod_profile.py inspect \
  --game "$vi_game" --vault "$vi_vault" --profile "$vi_profile"

python tools/mod_profile.py recover \
  --game "$vi_game" --vault "$vi_vault" --profile "$vi_profile"
```

`recover` completes the operation recorded by the pending phase. It identifies
the original directory by filesystem device and inode, then verifies its
inventory. It handles a process exit before or after the original directory
rename and before or after the restoration rename. If isolation already moved
the legacy tree, it can finish creating or recording the empty active directory.
If restoration already removed the empty directory, it can finish moving the
legacy tree back.

Recovery refuses an ambiguous location, modified legacy inventory, or a
nonempty active destination. Preserve both locations and inspect the reported
conflict. There is no force, overwrite, or automatic-delete option. If initial
journal preparation fails before a journal exists, the game tree has not moved;
inspect and preserve that incomplete profile directory, then choose another
profile name. The tool cannot infer an intended operation without its journal.

## Preservation evidence and limits

The inventory records every directory, regular file, and symlink using
`lstat`-equivalent metadata. It stores relative paths, device and inode, type and
mode, owner and group, size, modification time, and exact symlink target text.
Directory traversal uses held directory descriptors and opens children without
following symlinks. Absolute and relative resource links are preserved as links.
Relative links that point outside the plugin tree may resolve differently while
the tree is disabled; restoration returns them to their original location.

DLL, EXE, SO, and DYLIB files are SHA-256 hashed up to 64 MiB per file. Other
regular files up to 1 MiB are also hashed. The scan refuses more than 512 MiB of
total hashing, 100,000 entries, 128 nested directory levels, or 32 MiB of encoded
inventory metadata. Journals are limited to 64 MiB. Large resource packs receive
metadata checks, not full content hashes. No resource payloads are copied.
Access and inode change times are excluded from preservation comparisons,
because reading files and renaming directories can update them.

The tested behavior is local profile switching. Tests exercise real temporary directories, a sparse 28 GiB pack,
absolute and relative symlinks, symlink directory traversal refusal, metadata
and executable hashes, running-process refusal, empty and nonempty collisions,
cross-filesystem refusal, and recovery after simulated process termination.
These tests do not establish live game compatibility or performance.

```bash
python -m unittest discover -s tests -p test_mod_profile.py
```
