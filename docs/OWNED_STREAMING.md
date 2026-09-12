# Owned texture streaming milestone

The independent `OwnedTextureScheduler<T>` manages project-owned replacement
textures. `OwnedBundleLoad` provides the native Unity implementation, and
`OwnedMaterialHost` connects scheduler demand to explicitly enabled material
replacement. An installed profile and exact binding rules control activation.

The hardware baseline is 6 GB VRAM, 16 GB system RAM, and 1080p. Higher-quality
art and 4K displays remain important, with per-asset resolution and full mip
chains chosen through visual validation. These presets are configurable component
budgets, not total VRAM limits or measured hardware compatibility claims:

| Profile | Resident capacity | Pending payload | Concurrent loads | New engine loads per frame |
| --- | ---: | ---: | ---: | ---: |
| Compact | 384 MiB | 32 MiB | 1 | 1 |
| Balanced, default | 768 MiB | 64 MiB | 2 | 1 |
| High | 1536 MiB | 128 MiB | 2 | 1 |

The resident-capacity admission check includes resident, pending, and retiring
payloads. Pending payload has its additional, smaller limit. Original textures,
meshes, render targets, upload staging, driver allocations, and other mods remain
outside these counters. Compressed texture payload bytes are not complete bundle
or GPU allocation sizes.

## Demand and ownership

Construct a fixed alias catalog from validated owned bundle descriptors. Each
`OwnedTextureRequest(bundle, payloadSha256)` identifies the full compressed mip
payload by SHA256, DXT5 format, width, height, mip count, and sRGB interpretation.
Aliases with an exact identity share pending and resident allocations. Bundle
archive SHA256 validates the archive and is distinct from payload SHA256. Catalog
hashes and descriptors must come from verified preparation, never an unverified
caller claiming two assets are identical.

`Acquire(alias)` returns a lease or null for an unknown alias, stopped scheduler,
oversized payload, or exhausted tracking capacity. It never opens a file, starts
a Unity operation, or waits for a request. `lease.TryGet(out texture)` only returns
a resident result after bundle ownership has finished unloading. Until then, keep
the valid original binding. A live lease protects its resident texture regardless
of idle duration or budget pressure. Restore a material's original binding before
calling `lease.Dispose()`. Release is idempotent.

Tracking defaults to 256 simultaneous identity records and 4096 live leases,
including failed demand. The finite constructor catalog bounds payload reload
history. These limits are configurable through `StreamingPolicy`; the scheduler
does not accumulate an unbounded queue or failure history. Capacity rejection
preserves the original, and the caller can retry demand later. An existing failed
lease does not restart automatically. Release all leases on that identity and
pump cleanup before acquiring it again to retry.

Use all scheduler and lease operations on the creating engine thread. Call
`Tick(frame, nowSeconds)` with monotonic gameplay frame IDs and a monotonic clock.
Repeated calls in a frame share one start slot. Bundle opening and the subsequent
asset request both consume that slot. A factory may start at most one engine load;
`IOwnedTextureLoad.Pump(allowEngineStart)` must honor its permission and report
whether it started a load. Provider callbacks must not reenter scheduler methods.
`Tick` has a reentrancy guard.

```csharp
var scheduler = new OwnedTextureScheduler<Texture2D>(catalog,
    spec => new OwnedBundleLoad(spec),
    texture => UnityEngine.Object.Destroy(texture),
    texture => texture == null,
    StreamingPolicy.Balanced);
var lease = scheduler.Acquire("timber_albedo");
// In the update loop, on the main thread:
scheduler.Tick(Time.frameCount, monotonicSeconds);
Texture2D replacement;
if (lease != null && lease.TryGet(out replacement))
{
    // Assign only after retaining the valid original and checking binding ownership.
}
// When the binding stops using the replacement, restore its original, then:
if (lease != null) lease.Dispose();
```

## Cancellation, eviction, and stopping

Releasing the last queued lease removes the need for a load. Releasing the last
in-flight lease requests cancellation and retains the engine handle and pending
reservation until its release acknowledgement. Reacquiring an alias during
cancellation waits in metadata for that handle to drain before admitting a fresh
load. An ordinary in-flight request with live demand is reused without any
synchronous completion path.

An unused resident enters retirement after the default 60-second grace period.
It stops being available to new leases and remains charged as retiring until
`isReleased(texture)` acknowledges destruction. New demand during retirement
receives no replacement until release and a later asynchronous reload. The
retirement callback must schedule destruction only for the supplied owned object;
the release predicate must not acknowledge a live object. Exceptions preserve
reservations, and provider faults can require investigation before draining can
finish. A factory that throws must not have orphaned an engine request.

`Stop()` and `Dispose()` request shutdown, reject new demand, and allow existing
leases to protect resident textures. They return promptly. Restore all bindings,
release their leases, and continue ticking until `IsDrained`. Do not discard the
scheduler, unload its host assembly, or stop its update pump while it still owns
allocations. A stuck engine operation intentionally retains its reservation;
shutdown is not permitted to invent a release acknowledgement.

`OwnedBundleLoad.Dispose()` and `Cancel()` are requests to drain. They do not
throw merely because opening or loading is in progress. Cancellation before asset
loading avoids starting that phase. Cancellation during asset loading waits for
the existing request. Cleanup uses `AssetBundle.UnloadAsync(true)` for retained
bundle ownership and `UnloadAsync(false)` after `Take()` transfers the texture.
The adapter releases its pending reservation only after the unload operation
completes. A transferred texture is never destroyed by subsequent adapter disposal
or cancellation. Scheduler retirement owns its later destruction.

Unity object destruction acknowledgement means Unity ownership was released.
It is not a measurement of physical driver memory reclamation or total VRAM.
There is no guessed two-frame accounting deadline in the new scheduler.

## Evidence and Editor probe

The initial test-first run reported eight failing lifecycle scenarios with
`Owned demand lifecycle not implemented`. The implemented scheduler then passed
those scenarios. Additional cases cover a transferred result whose bundle unload
is delayed and a factory failure before an engine request exists.

Run the complete engine-independent regression suite and compile staging DLLs:

```bash
python tools/build.py --config local/build.json --test
python tools/build.py --config local/build.json
```

Both commands passed on September 12, 2026. The test result was `Failures: 0`.
The non-test command compiled against installed read-only Unity/game references
into `build/runtime` and performed no game deployment. Relevant assertions include:

- Owned aliases share one in-flight allocation and the same resident texture.
- Color interpretation and dimensions prevent incorrect content sharing.
- Repeated same-frame ticks and the bundle-to-asset phase share one start slot.
- Pending capacity, resident capacity, queue capacity, and lease bounds hold.
- Demanded residents survive pressure, and retirement delays capacity reuse.
- Acknowledged eviction permits return-demand reload with a new texture.
- Cancellation and reacquisition never overlap the draining allocation.
- Shutdown protects live leases, drains unfinished requests, and reaches zero.
- Missing/failed loads preserve the original and do not retry each frame.
- Transferred results remain reserved through delayed request unloading and are
  retired exactly once after shutdown.

`tools/unity/OwnedStreamingProbe.cs` is an opt-in Editor harness. It is not compiled
by the ordinary runtime build and is not installed into the game. For a local
Editor run, copy `build/runtime/ValheimImpact.Core.dll` and
`src/ValheimImpact.Unity/OwnedBundleLoad.cs` into
`unity/Assets/GeneratedRuntime/`, and copy the probe into its `Editor/` subfolder.
Treat those copies as local staging artifacts. Let the matching Unity Editor
compile them, then invoke:

```csharp
OwnedStreamingProbe.Start(absoluteCatalogPath, absoluteReportPath);
```

The entry returns promptly and pumps `EditorApplication.update`. The probe uses
synthetic frame IDs because edit-mode `Time.frameCount` does not advance like a
gameplay loop. It validates the selected owned bundle files, loads two distinct
catalog textures, shares aliases, forces budget deferral, retires and reloads,
cancels opening requests, checks a deliberately invalid selector, and drains stop.
It creates its own fallback texture and never modifies a scene or material.

The first native Editor run reached alias sharing, budget deferral, and retirement,
then timed out because the Editor refused the default `DestroyImmediate` call on
a bundle-loaded asset. The scheduler correctly retained its 87,408-byte retiring
reservation. The original failure report was written and parsed successfully.
The probe cleanup path was corrected without changing runtime ownership rules.

The probe intentionally delays `DestroyImmediate(texture, true)` for three Editor
updates on its own transferred bundle textures. Before allowing destruction, it
requires the exact managed reference to appear in its independent transfer
registry and requires `AssetDatabase.GetAssetPath(texture)` to be empty. Every
nonempty path, including project, package, and library paths, is refused. The
probe's startup checks exercise this guard. A refusal or still-live object retains
its retirement entry and reservation. Only a confirmed Unity null acknowledgement
removes the entry and transfer record. The Editor-specific flag is required for
these bundle-loaded instances and must not be used to delete authored project
assets. This exercises accounting under a controlled release delay;
it does not claim to reproduce gameplay `Destroy` scheduling. Successful cleanup
uses asynchronous native bundle-unload completion. JSON includes catalog SHA256,
Unity version, rendering backend, named checks, bounded samples, and allocation,
queue, load, eviction, reload, cancellation, and error counters. The one deliberate
missing-asset error is expected. A 45-second test timeout writes a failure result
with `cleanupPending`; its pump continues retaining and draining handles until
ownership releases. Report writes validate JSON round-trip structure, replace the
destination through a temporary file, verify disk readback, and log the absolute
report path. Write failures are logged explicitly and retried during draining.
Domain reload during a pending probe is not a supported test operation.

Actual Editor results belong in the separately captured report. Compiling the
adapter and passing engine-independent tests alone do not establish native bundle
behavior, game binding correctness, hitch improvements, 6 GB compatibility,
Windows behavior, model streaming, or shader streaming.

## Integration and remaining validation

Exact-content sharing, bounded native concurrency, one start per frame,
explicit ownership, acknowledged retirement and reload counters define the
scheduler contract. Current material integration adds an exact alias registry,
restorable bindings, bounded renderer discovery and profile-file consumption.
See [GAME_BINDING.md](GAME_BINDING.md) for its current behavior.

Representative routes, broad material scope, weather, performance and complete
biome art acceptance remain open. The native fixture below proves the recorded
texture lifecycle only.

## Native evidence, 2026-09-12

The matching Linux Editor executed the corrected probe through Vulkan. All 14
checks passed, including shared instances, budget deferral, acknowledged
retirement, eviction/reload, opening cancellation, missing-selector fallback
and shutdown. The run ended with zero pending, resident and retiring payload.
The one error was deliberately induced by an invalid asset selector. Full
per-update evidence is in `docs/evidence/owned-streaming-native.json`.

Native loading-phase cancellation and shutdown during transferred bundle unload
still have simulated coverage only. The Editor probe is not a gameplay frame-time,
GPU residency, 6 GB compatibility or Windows result.
