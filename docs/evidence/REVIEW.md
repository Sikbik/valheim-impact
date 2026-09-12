# Kickoff review

The initial runtime review covered offline parsing, ownership and scheduling.
Core tests passed and repeated runtime builds produced identical hashes.

The final integration review reproduced an output symlink issue in asset
generation using temporary directories only. Input checks already rejected links,
but output paths lacked equivalent checks. The fix preflights every output and
all ancestors before the first write. Regression cases cover a redirected output
directory and a later normal-map filename, requiring no earlier albedo write and
an unchanged external sentinel. Both failed before the fix and pass afterward.

Scoped re-review accepted the fix with all 16 Python tests passing. No remaining
actionable findings were reported within the offline kickoff boundary.

At that initial review, Unity serialization, native asynchronous loading, Vulkan
sampling, game UVs, rendering and performance were still unexecuted validation work.
Review acceptance does not convert those pending checks into tested behavior.

## First game binding review

Independent review found and resolved four integration problems: newly created
vault ancestors needed parent-directory sync before moving legacy plugins;
shared-material array enumeration allocated before its cap; released materials
retained tracker capacity after their renderers vanished; and opacity eligibility
was not rechecked during async load/application. The new native fixture reproduced
the secondary-slot issue before the fix and passes all 14 final checks, including
1056 surviving material identities, opacity mutation and zero final allocations.

The installer review found an incorrect completion message that claimed
replacement remained disabled after explicit opt-in. The message now reflects
the installed profile. Opt-in participates in the review token and receipt, and
update/rollback tests verify the actual enabled state. The first-slot scope and
unmeasured game/performance limits are explicit in GAME_BINDING.md.
