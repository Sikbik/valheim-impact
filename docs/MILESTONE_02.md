# Milestone 2: exact game material binding

This milestone connected the owned texture scheduler to an explicit material
allowlist and an installer-controlled profile. It established conservative
replacement and restoration rules before expanding visual coverage.

## Implemented behavior

The initial mappings selected `stone_huge`, `woodwall`, and `woodpole` through
exact shader, texture-property, original-texture-name, and dimension checks.
The binder captured each original texture object and UV transform, acquired a
demand lease, and adopted an asynchronously loaded albedo only after rechecking
the material. Foreign edits remained intact. Disabling restored owned slots
and drained requests.

The installer added explicit replacement opt-in, tracked the generated profile
in ownership hashes, and restored profile bytes on rollback. Backups and staging
use encoded `.payload` names so private DLL copies do not enter recursive plugin
discovery. See [INSTALLER.md](INSTALLER.md) for current transaction, recovery,
and older-storage migration behavior.

The binding discovery policy at this milestone covered the first shared
material slot only. [Milestone 3](MILESTONE_03.md) later extended discovery to
bounded multi-slot access. The current contract is in [RUNTIME.md](RUNTIME.md).

## Historical validation scope

The initial game-menu integration showed visible timber-pole replacement through
the game's shader in a 3840 by 2160 capture. That run could not resolve the
required loaded rock renderer, so its two-pair test was incomplete. Later
standing-stone and roof fixtures extended the result; they do not retroactively
turn the earlier incomplete run into a pass.

Selected rock and timber UV reviews used exact mesh/submesh identities and
material transforms. They established albedo fitting for those samples, not
full shader appearance or coverage of every material user. Equal material names
and matching descriptors can occur in different regions. Shared stone scope
includes uses that have not been visually reviewed in their biome.

The native binding fixture exercised exact misses, pending and applied opacity
changes, foreign edits, restoration, 1,056-material churn, and acknowledged
cleanup. Later [binding evidence](evidence/material-binding-native.json) adds
multi-slot and capability-fallback checks. Native fixtures use owned inputs and
are separate from actual-game rendering evidence.

The source runtime was compiled against game references, while synthetic tests
ran under .NET. The relocated Linux installer passed temporary-fixture install,
update, rollback, and uninstall. A reviewed local game test used explicit
installation and rollback, without opening a character or world. No generalized
compatibility guarantee follows from those checks.

## Continue from here

New bindings need exact identity evidence, inspected UV and companion-channel
scope, native loading validation, and a reviewable game fixture. Do not broaden
matching to make a missing source appear to pass. Report finite discovery misses
and investigate the actual renderer/material relationship.

Current selected game fixtures are summarized in
[MENU_VALIDATION.md](MENU_VALIDATION.md). The tracker records asset stages and
biome approvals separately. Whole-building appearance, LODs, weather, broader
biomes, model/shader streaming, and representative hardware remain open.
Balanced targets 6 GB VRAM, 16 GB RAM at 1080p; crisp 4K presentation is also
required. A 4K menu capture is not a complete quality or performance result.
