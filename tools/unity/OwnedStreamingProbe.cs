// Copy this file and OwnedBundleLoad.cs into an Editor-only staging assembly with
// ValheimImpact.Core.dll. Start returns promptly and never changes any scene.
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using UnityEditor;
using UnityEngine;
using ValheimImpact.Core;
using ValheimImpact.Unity;
using Object = UnityEngine.Object;

public static class OwnedStreamingProbe
{
    // Populated by Unity JsonUtility.
#pragma warning disable 0649
    [Serializable] private sealed class Descriptor
    {
        public string id, path, assetName, sha256, payloadSha256;
        public int width, height, mipCount, payloadBytes;
        public bool isSrgb;
    }
    [Serializable] private sealed class Catalog { public int schemaVersion; public Descriptor[] textures; }
#pragma warning restore 0649
    [Serializable] private sealed class Check { public string name; public bool passed; }
    [Serializable] private sealed class Sample
    {
        public long frame, pendingBytes, residentBytes, retiringBytes, allocatedBytes, started, engineStarts, completed, evicted, reloaded, cancelled, errors;
        public int stage, active, queued;
        public double seconds;
    }
    [Serializable] private sealed class Report
    {
        public string startedUtc, editorVersion, graphicsDeviceType, catalogPath, catalogSha256, error;
        public string scope = "Owned Texture2D Editor lifecycle only. No scene edits, game replacement, FPS or total VRAM claim.";
        public string retirement = "Probe delays DestroyImmediate(texture, true) for three Editor updates, and permits it only for exact registered owned-bundle instances with no AssetDatabase path. Retirement is acknowledged only after Unity null. Runtime integrations should use Destroy and Unity null acknowledgement.";
        public bool completed, passed, cleanupPending;
        public long componentBudgetBytes;
        public List<Check> checks = new List<Check>();
        public List<Sample> samples = new List<Sample>();
    }
    private sealed class Retirement { internal Texture2D Texture; internal long Frame; }
    private sealed class Run
    {
        internal OwnedTextureScheduler<Texture2D> Scheduler;
        internal OwnedTextureScheduler<Texture2D>.Lease A, Alias, B, Missing;
        internal readonly List<Retirement> Retirements = new List<Retirement>();
        internal readonly List<Texture2D> OwnedBundleTextures = new List<Texture2D>();
        internal Report Report;
        internal string ReportPath;
        internal Texture2D Original, Assigned;
        internal long Frame, LastStarts, FirstInstance;
        internal double StartTime, LastReportAttempt;
        internal int Stage;
        internal bool ReportWritten, DrainingAfterFailure;
    }
    // Records actual ownership transfer, independent of the later retirement queue.
    private sealed class ProbeLoad : IOwnedTextureLoad<Texture2D>
    {
        private readonly OwnedBundleLoad inner;
        private readonly Run run;
        internal ProbeLoad(OwnedTextureBundle spec, Run run) { this.run = run; inner = new OwnedBundleLoad(spec); }
        public bool IsDone { get { return inner.IsDone; } }
        public bool IsReleased { get { return inner.IsReleased; } }
        public Exception Error { get { return inner.Error; } }
        public bool Pump(bool allowEngineStart) { return inner.Pump(allowEngineStart); }
        public Texture2D Take()
        {
            Texture2D texture = inner.Take();
            run.OwnedBundleTextures.Add(texture);
            return texture;
        }
        public void Cancel() { inner.Cancel(); }
        public void Dispose() { inner.Dispose(); }
    }
    private static Run current;

    public static void Start(string catalogPath, string reportPath)
    {
        if (current != null) throw new InvalidOperationException("An owned streaming probe is already active");
        catalogPath = Path.GetFullPath(catalogPath); reportPath = Path.GetFullPath(reportPath);
        var catalog = JsonUtility.FromJson<Catalog>(File.ReadAllText(catalogPath));
        if (catalog == null || catalog.schemaVersion != 1 || catalog.textures == null || catalog.textures.Length < 2)
            throw new InvalidDataException("Expected at least two owned catalog textures");
        Array.Sort(catalog.textures, (x, y) => x.payloadBytes.CompareTo(y.payloadBytes));
        string directory = Path.GetDirectoryName(catalogPath);
        var first = Spec(directory, catalog.textures[0]);
        OwnedTextureRequest second = null;
        foreach (Descriptor candidate in catalog.textures)
        {
            var request = Spec(directory, candidate);
            if (request.Identity != first.Identity) { second = request; break; }
        }
        if (second == null) throw new InvalidDataException("Expected two distinct payload identities");
        first.Bundle.ValidateFile(); second.Bundle.ValidateFile();
        long budget = Math.Max(first.Bundle.PayloadBytes, second.Bundle.PayloadBytes);
        var run = new Run { StartTime = EditorApplication.timeSinceStartup, ReportPath = reportPath };
        run.Report = new Report { startedUtc = DateTime.UtcNow.ToString("o"), editorVersion = Application.unityVersion,
            graphicsDeviceType = SystemInfo.graphicsDeviceType.ToString(), catalogPath = catalogPath,
            catalogSha256 = Hash(File.ReadAllBytes(catalogPath)), componentBudgetBytes = budget };
        // Intentionally wrong selector in an otherwise validated owned bundle tests failure cleanup.
        var missing = new OwnedTextureBundle(first.Bundle.Path, "assets/missing/owned-probe.asset", first.Bundle.Sha256,
            first.Bundle.Width, first.Bundle.Height, first.Bundle.IsSrgb);
        var entries = new Dictionary<string, OwnedTextureRequest> { { "a", first }, { "alias", first }, { "b", second },
            { "missing", new OwnedTextureRequest(missing, new string('0', 64)) } };
        run.Scheduler = new OwnedTextureScheduler<Texture2D>(entries, spec => new ProbeLoad(spec, run),
            texture => run.Retirements.Add(new Retirement { Texture = texture, Frame = run.Frame + 3 }),
            texture => texture == null, new StreamingPolicy(budget, budget, 2, 0, 8, 16));
        Require(run, !RetirementAllowed(false, "") && !RetirementAllowed(true, "Assets/Owned/probe.asset") &&
            !RetirementAllowed(true, "Packages/example/probe.asset") && !RetirementAllowed(true, "Library/probe.asset"),
            "Editor destruction guard refuses unowned objects and every nonempty AssetDatabase path");
        run.Original = new Texture2D(4, 4, TextureFormat.RGBA32, false);
        run.Original.name = "ValheimImpact owned probe fallback";
        run.Assigned = run.Original;
        run.A = run.Scheduler.Acquire("a"); run.Alias = run.Scheduler.Acquire("alias");
        Texture2D value;
        Require(run, run.A != null && run.Alias != null && !run.A.TryGet(out value) && run.Scheduler.StartedCount == 0,
            "demand returns without starting or waiting for Unity");
        current = run;
        EditorApplication.update += Update;
    }
    private static OwnedTextureRequest Spec(string directory, Descriptor d)
    {
        if (d == null || string.IsNullOrWhiteSpace(d.path) || Path.IsPathRooted(d.path)) throw new InvalidDataException("Invalid catalog path");
        string full = Path.GetFullPath(Path.Combine(directory, d.path));
        if (!full.StartsWith(directory + Path.DirectorySeparatorChar, StringComparison.Ordinal)) throw new InvalidDataException("Catalog path escapes bundle directory");
        var bundle = new OwnedTextureBundle(full, d.assetName, d.sha256, d.width, d.height, d.isSrgb);
        if (bundle.PayloadBytes != d.payloadBytes || bundle.MipCount != d.mipCount) throw new InvalidDataException("Catalog mip contract mismatch");
        return new OwnedTextureRequest(bundle, d.payloadSha256);
    }
    private static string Hash(byte[] bytes)
    { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
    private static void Require(Run run, bool condition, string name)
    {
        run.Report.checks.Add(new Check { name = name, passed = condition });
        if (!condition) throw new InvalidOperationException(name);
    }
    private static void SampleNow(Run run)
    {
        var s = run.Scheduler;
        if (run.Report.samples.Count >= 2048) return;
        run.Report.samples.Add(new Sample { frame = run.Frame, stage = run.Stage, seconds = EditorApplication.timeSinceStartup - run.StartTime,
            pendingBytes = s.PendingBytes, residentBytes = s.ResidentBytes, retiringBytes = s.RetiringBytes, allocatedBytes = s.AllocatedBytes,
            active = s.ActiveCount, queued = s.QueuedCount, started = s.StartedCount, engineStarts = s.EngineStartCount,
            completed = s.CompletedCount, evicted = s.EvictedCount, reloaded = s.ReloadedCount, cancelled = s.CancelledCount, errors = s.ErrorCount });
    }
    private static void Update()
    {
        var run = current;
        if (run == null) return;
        try
        {
            run.Frame++;
            for (int i = run.Retirements.Count - 1; i >= 0; i--)
                if (run.Frame >= run.Retirements[i].Frame)
                {
                    DestroyOwnedBundleTexture(run, run.Retirements[i].Texture);
                    // A refused or unsuccessful destruction throws above and retains
                    // the retirement entry, its reference, and the scheduler reservation.
                    run.Retirements.RemoveAt(i);
                }
            long engineBefore = run.Scheduler.EngineStartCount;
            run.Scheduler.Tick(run.Frame, EditorApplication.timeSinceStartup - run.StartTime);
            if (run.Scheduler.EngineStartCount - engineBefore > 1) throw new InvalidOperationException("More than one engine start in an Editor update");
            if (run.Scheduler.AllocatedBytes > run.Report.componentBudgetBytes || run.Scheduler.PendingBytes > run.Report.componentBudgetBytes)
                throw new InvalidOperationException("Owned component budget exceeded");
            SampleNow(run);
            if (run.DrainingAfterFailure)
            {
                if (!run.ReportWritten && EditorApplication.timeSinceStartup - run.LastReportAttempt >= 1)
                    Write(run, false, !run.Scheduler.IsDrained);
                if (run.Scheduler.IsDrained) Finish(run, false);
                return;
            }
            if (EditorApplication.timeSinceStartup - run.StartTime > 45) throw new TimeoutException("Owned probe exceeded 45 seconds");
            Texture2D texture, alias;
            switch (run.Stage)
            {
                case 0:
                    if (!run.A.TryGet(out texture)) break;
                    Require(run, run.Alias.TryGet(out alias) && ReferenceEquals(texture, alias) && texture != null,
                        "native aliases share the same live resident texture after bundle unload");
                    run.FirstInstance = texture.GetInstanceID(); run.Assigned = texture;
                    run.LastStarts = run.Scheduler.StartedCount; run.B = run.Scheduler.Acquire("b"); run.Stage = 1;
                    break;
                case 1:
                    Require(run, run.Scheduler.QueuedCount == 1 && run.Scheduler.StartedCount == run.LastStarts && run.Assigned != null,
                        "full resident budget preserves the current texture and defers another demand");
                    run.Assigned = run.Original; run.A.Dispose(); run.Alias.Dispose(); run.Stage = 2;
                    break;
                case 2:
                    Require(run, run.Scheduler.RetiringBytes > 0 && run.Scheduler.StartedCount == run.LastStarts,
                        "deferred native retirement retains its reservation before destruction acknowledgement");
                    run.Stage = 3;
                    break;
                case 3:
                    if (!run.B.TryGet(out texture)) break;
                    Require(run, texture != null && run.Scheduler.EvictedCount == 1, "acknowledged native eviction admits deferred demand");
                    run.B.Dispose(); run.Stage = 4;
                    break;
                case 4:
                    if (!run.Scheduler.IsDrained) break;
                    run.A = run.Scheduler.Acquire("alias"); run.Stage = 5;
                    break;
                case 5:
                    if (!run.A.TryGet(out texture)) break;
                    Require(run, texture != null && texture.GetInstanceID() != run.FirstInstance && run.Scheduler.ReloadedCount == 1,
                        "return demand reloads the evicted native texture");
                    run.A.Dispose(); run.Stage = 6;
                    break;
                case 6:
                    if (!run.Scheduler.IsDrained) break;
                    run.B = run.Scheduler.Acquire("b"); run.Stage = 7;
                    break;
                case 7:
                    Require(run, run.Scheduler.ActiveCount == 1 && run.Scheduler.PendingBytes > 0, "native cancellation fixture starts an asynchronous opening");
                    run.B.Dispose(); run.Stage = 8;
                    break;
                case 8:
                    if (!run.Scheduler.IsDrained) break;
                    Require(run, run.Scheduler.CancelledCount == 1 && run.Scheduler.PendingBytes == 0,
                        "canceled native opening drains through acknowledged bundle unload");
                    run.Missing = run.Scheduler.Acquire("missing"); run.Stage = 9;
                    break;
                case 9:
                    if (run.Scheduler.ErrorCount == 0 || run.Scheduler.AllocatedBytes != 0) break;
                    Require(run, !run.Missing.TryGet(out texture) && run.Assigned == run.Original && run.Original != null,
                        "native missing asset failure preserves the valid original and drains its bundle");
                    run.Missing.Dispose(); run.A = run.Scheduler.Acquire("a"); run.Stage = 10;
                    break;
                case 10:
                    Require(run, run.Scheduler.ActiveCount == 1, "shutdown fixture has an in-flight native request");
                    run.A.Dispose(); run.Scheduler.Stop();
                    Require(run, run.Scheduler.Acquire("b") == null, "shutdown rejects new native demand");
                    run.Stage = 11;
                    break;
                case 11:
                    if (!run.Scheduler.IsDrained) break;
                    Require(run, run.Scheduler.PendingBytes == 0 && run.Scheduler.ResidentBytes == 0 && run.Scheduler.RetiringBytes == 0 &&
                        run.Scheduler.CancelledCount >= 2 && run.Scheduler.ErrorCount == 1,
                        "shutdown completes with zero owned allocations and only the intentional missing-asset error");
                    Require(run, run.Scheduler.PeakAllocatedBytes <= run.Report.componentBudgetBytes,
                        "every sampled engine update obeyed the payload budget and single-start gate");
                    Finish(run, true);
                    break;
            }
        }
        catch (Exception error)
        {
            if (!run.DrainingAfterFailure)
            {
                run.Report.error = error.ToString(); run.DrainingAfterFailure = true;
                Release(run.A); Release(run.Alias); Release(run.B); Release(run.Missing);
                run.Assigned = run.Original; run.Scheduler.Stop();
                Debug.LogError("Owned streaming probe failed; draining retained ownership: " + error);
            }
            // Write a finite failure result even if a broken engine request cannot drain.
            // Keep pumping retained handles until they release; never orphan a request.
            if (!run.ReportWritten && EditorApplication.timeSinceStartup - run.LastReportAttempt >= 1)
                Write(run, false, !run.Scheduler.IsDrained);
            if (run.Scheduler.IsDrained) Finish(run, false);
        }
    }
    private static bool RetirementAllowed(bool ownedBundleInstance, string assetDatabasePath)
    { return ownedBundleInstance && string.IsNullOrEmpty(assetDatabasePath); }
    private static void DestroyOwnedBundleTexture(Run run, Texture2D texture)
    {
        int ownedIndex = run.OwnedBundleTextures.FindIndex(candidate => ReferenceEquals(candidate, texture));
        string assetPath = texture == null ? "" : AssetDatabase.GetAssetPath(texture);
        if (!RetirementAllowed(ownedIndex >= 0, assetPath))
            throw new InvalidOperationException("Refusing Editor destruction of unowned or project-backed texture: " + assetPath);
        if (texture != null)
        {
            // Bundle textures are marked persistent by the Editor even after
            // Unload(false). The allowDestroyingAssets flag is restricted by the
            // exact ownership and AssetDatabase checks above, never project assets.
            Object.DestroyImmediate(texture, true);
            if (texture != null) throw new InvalidOperationException("Editor refused destruction of an owned bundle texture");
        }
        run.OwnedBundleTextures.RemoveAt(ownedIndex);
    }
    private static void Release(OwnedTextureScheduler<Texture2D>.Lease lease) { if (lease != null) lease.Dispose(); }
    private static void Write(Run run, bool passed, bool cleanupPending)
    {
        run.LastReportAttempt = EditorApplication.timeSinceStartup;
        run.ReportWritten = false;
        try
        {
            run.Report.completed = true; run.Report.passed = passed; run.Report.cleanupPending = cleanupPending;
            string json = JsonUtility.ToJson(run.Report, true);
            Report decoded = JsonUtility.FromJson<Report>(json);
            if (decoded == null || !decoded.completed || decoded.checks == null || decoded.checks.Count != run.Report.checks.Count)
                throw new InvalidDataException("Editor report serialization did not preserve the report contract");
            Directory.CreateDirectory(Path.GetDirectoryName(run.ReportPath));
            string temporary = run.ReportPath + ".tmp";
            File.WriteAllText(temporary, json);
            if (File.Exists(run.ReportPath)) File.Replace(temporary, run.ReportPath, null);
            else File.Move(temporary, run.ReportPath);
            if (File.ReadAllText(run.ReportPath) != json) throw new IOException("Editor report readback mismatch");
            run.ReportWritten = true;
            Debug.Log("Owned streaming probe report written and verified: " + run.ReportPath);
        }
        catch (Exception error)
        {
            Debug.LogError("Cannot write owned streaming probe report at " + run.ReportPath + ": " + error);
        }
    }
    private static void Finish(Run run, bool passed)
    {
        Release(run.A); Release(run.Alias); Release(run.B); Release(run.Missing);
        run.Scheduler.Stop(); run.Assigned = null;
        if (run.Original != null) Object.DestroyImmediate(run.Original);
        Write(run, passed, false);
        EditorApplication.update -= Update; current = null;
        Debug.Log("Owned streaming probe " + (passed ? "passed: " : "failed: ") + run.ReportPath);
    }
}
