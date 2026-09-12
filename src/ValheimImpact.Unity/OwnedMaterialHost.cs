using System;
using System.Globalization;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.SceneManagement;
using ValheimImpact.Core;
using Object = UnityEngine.Object;

namespace ValheimImpact.Unity
{
    // Independent persistent pump outlives disabling/destroying the BepInEx plugin.
    // Keep the assembly loaded until this host reports a completed drain.
    public sealed class OwnedMaterialHost : MonoBehaviour
    {
        private Task<OwnedMaterialRegistry> validation;
        private OwnedMaterialRegistry registry;
        private OwnedMaterialBinder binder;
        private Action<string> info, error;
        private FrameTimeWindow timing;
        private bool requested, closeAfterDrain, invalid, ready, sceneReset, initialized;
        private bool applicationQuitting;
        private double nextReport;
        private long lastErrors;
        public void Initialize(string packageRoot, bool diagnostics, Action<string> info, Action<string> error)
        {
            if (initialized) throw new InvalidOperationException("Material host initialized twice");
            initialized = true; this.info = info; this.error = error;
            if (diagnostics) timing = new FrameTimeWindow();
            nextReport = Time.realtimeSinceStartupAsDouble + 30;
            // No Unity calls or object creation in this worker. No repeated hashing.
            validation = Task.Run(() => OwnedMaterialRegistry.Load(packageRoot));
            SceneManager.sceneLoaded += SceneLoaded;
            SceneManager.sceneUnloaded += SceneUnloaded;
        }
        public void SetReplacementEnabled(bool value) { requested = value; }
        public void CloseWhenDrained() { requested = false; closeAfterDrain = true; if (binder != null) binder.Stop(); }
        private void SceneLoaded(Scene scene, LoadSceneMode mode) { sceneReset = true; }
        private void SceneUnloaded(Scene scene) { sceneReset = true; }
        private void Update()
        {
            if (!initialized) return;
            double now = Time.realtimeSinceStartupAsDouble;
            if (timing != null) timing.AddSeconds(Time.unscaledDeltaTime);
            if (!ready && validation != null && validation.IsCompleted)
            {
                ready = true;
                try
                {
                    registry = validation.GetAwaiter().GetResult();
                    if (registry.Enabled)
                    {
                        bool platform = (Application.platform == RuntimePlatform.LinuxPlayer && registry.Target == "StandaloneLinux64") ||
                            (Application.platform == RuntimePlatform.WindowsPlayer && registry.Target == "StandaloneWindows64");
                        if (registry.EditorVersion != Application.unityVersion || !platform)
                            throw new InvalidOperationException("Owned catalog Unity version or platform does not match this game");
                        if (timing == null) timing = new FrameTimeWindow();
                        info("Valheim Impact owned file validation complete; profile=" + registry.ProfileName + "; mappings=" + registry.Rules.Count);
                    }
                    else info("Valheim Impact game replacement disabled by installed profile.");
                }
                catch (Exception ex) { invalid = true; error("Valheim Impact replacement kept disabled: " + ex); }
                validation = null;
            }
            if (sceneReset)
            {
                if (binder != null) binder.Stop();
                sceneReset = false;
            }
            bool enable = requested && ready && !invalid && registry != null && registry.Enabled && !closeAfterDrain;
            if (binder != null)
            {
                if (!enable) binder.Stop();
                try { binder.Tick(Time.frameCount, now); }
                catch (Exception ex)
                {
                    binder.Stop(); invalid = true;
                    error("Valheim Impact material pump error; retaining ownership for draining: " + ex);
                }
                if (binder.Scheduler.ErrorCount != lastErrors)
                { lastErrors = binder.Scheduler.ErrorCount; error("Valheim Impact owned load failed; original remains: " + binder.Scheduler.LastError); }
                if (binder.IsDrained)
                { Report(); info("Valheim Impact owned material drain complete; allocations=0; leases=0."); binder = null; lastErrors = 0; }
            }
            if (enable && !invalid && binder == null) binder = new OwnedMaterialBinder(registry, info);
            if (now >= nextReport) { nextReport = now + 30; Report(); }
            if (closeAfterDrain && ready && binder == null) Object.Destroy(gameObject);
        }
        private void Report()
        {
            if (timing != null)
            {
                var s = timing.Summarize();
                info(string.Format(CultureInfo.InvariantCulture,
                    "Observed Unity frame delta ms (not GPU time): samples={0}; observed={1}; p50={2:F3}; p95={3:F3}; p99={4:F3}; max={5:F3}; rollingCapacity=4096",
                    s.Count, s.Observed, s.P50Ms, s.P95Ms, s.P99Ms, s.MaxMs));
            }
            if (binder == null) return;
            var q = binder.Scheduler;
            info("Valheim Impact bindings: tracked=" + binder.TrackedMaterials + "; seen=" + binder.DiscoveredCount +
                "; matched=" + binder.MatchedCount + "; applied=" + binder.AppliedCount + "; restored=" + binder.RestoredCount +
                "; foreign=" + binder.ForeignChangeCount + "; incompleteCensus=" + binder.SkippedCensusCount +
                "; leases=" + q.LeaseCount + "; queued=" + q.QueuedCount + "; active=" + q.ActiveCount +
                "; residentPayload=" + q.ResidentBytes + "; pendingPayload=" + q.PendingBytes + "; retiringPayload=" + q.RetiringBytes +
                "; starts=" + q.EngineStartCount + "; completed=" + q.CompletedCount + "; errors=" + q.ErrorCount + "; stopping=" + binder.IsStopping);
        }
        private void OnApplicationQuit()
        {
            applicationQuitting = true;
            // Process exit is not an asynchronous drain test. Restore our slots while
            // the engine is alive; the OS subsequently ends the engine's allocations.
            if (binder != null) binder.RestoreForProcessExit();
            Report();
        }
        private void OnDestroy()
        {
            SceneManager.sceneLoaded -= SceneLoaded;
            SceneManager.sceneUnloaded -= SceneUnloaded;
            if (!applicationQuitting && binder != null && !binder.IsDrained)
                error("Valheim Impact pump destroyed before acknowledged drain; dynamic assembly/host removal is unsupported.");
        }
    }
}
