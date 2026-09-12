// Editor-only finite fixture for the production binder. Stage this with Core.dll,
// OwnedBundleLoad.cs, OwnedMaterialBinder.cs, OwnedMaterialHost.cs and the owned
// CutoutBindingFixture.shader. No game or
// saved scene is opened. Quit callbacks are invoked locally, never Application.Quit.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;
using ValheimImpact.Core;
using ValheimImpact.Unity;
using Object = UnityEngine.Object;

public static class MaterialBindingProbe
{
    [Serializable] private sealed class Check { public string name; public bool passed; }
    [Serializable] private sealed class Sample
    {
        public long frame, applied, restored, foreign, pending, resident, retiring, engineStarts;
        public int leases;
    }
    [Serializable] private sealed class CutoutCandidate
    {
        public string label, material, shader;
        public bool expectedAdmission, admitted, alphaTest, alphaBlend, alphaPremultiply;
        public bool declaresAlphaTest, declaresAlphaBlend, declaresAlphaPremultiply;
        public int renderQueue, leasesBefore, leasesAfter;
        public long matchedBefore, matchedAfter;
        public string[] properties;
        public bool[] present;
        public float[] values;
    }
    [Serializable] private sealed class Report
    {
        public string startedUtc, unityVersion, graphicsApi, packageRoot, error;
        public string scope = "Owned Standard and diagnostic cutout material fixtures using the production exact binder and native async bundle loader. No game scene, world, save, performance, total VRAM, custom game shader or UV approval claim.";
        public bool completed, passed, cleanupPending;
        public List<Check> checks = new List<Check>();
        public List<Sample> samples = new List<Sample>();
        public List<CutoutCandidate> cutoutCandidates = new List<CutoutCandidate>();
    }
    private sealed class Retirement { internal Texture Texture; internal long Frame; }
    private sealed class Run
    {
        internal Task<OwnedMaterialRegistry> Validation;
        internal OwnedMaterialBinder Binder;
        internal OwnedMaterialRegistry Registry;
        internal Material A, B, Miss, Secondary, PendingOpacity, AppliedOpacity;
        internal Material QuitOwned, QuitForeign;
        internal Material CutoutStable, CutoutPending, CutoutAdopted, CutoutForeign, CutoutKeyword;
        internal readonly List<Material> Churn = new List<Material>();
        internal Texture2D Original, Foreign, OtherChannel;
        internal GameObject Root;
        internal readonly List<Texture> Transferred = new List<Texture>();
        internal readonly List<Retirement> Retiring = new List<Retirement>();
        internal long Frame;
        internal int Stage;
        internal double StartTime, LastWrite;
        internal bool Failed, Wrote;
        internal Report Report;
        internal string Output;
    }
    private sealed class ProbeLoad : IOwnedTextureLoad<Texture>
    {
        private readonly OwnedBundleLoad inner;
        private readonly Run run;
        internal ProbeLoad(OwnedTextureBundle spec, Run run) { this.run = run; inner = new OwnedBundleLoad(spec); }
        public bool IsDone { get { return inner.IsDone; } }
        public bool IsReleased { get { return inner.IsReleased; } }
        public Exception Error { get { return inner.Error; } }
        public bool Pump(bool allow) { return inner.Pump(allow); }
        public Texture Take() { Texture value = inner.Take(); run.Transferred.Add(value); return value; }
        public void Cancel() { inner.Cancel(); }
        public void Dispose() { inner.Dispose(); }
    }
    private static Run current;
    public static void Start(string packageRoot, string reportPath)
    {
        if (current != null) throw new InvalidOperationException("Material binding probe already active");
        packageRoot = Path.GetFullPath(packageRoot); reportPath = Path.GetFullPath(reportPath);
        current = new Run { Output = reportPath, StartTime = EditorApplication.timeSinceStartup,
            Report = new Report { startedUtc = DateTime.UtcNow.ToString("o"), unityVersion = Application.unityVersion,
                graphicsApi = SystemInfo.graphicsDeviceType.ToString(), packageRoot = packageRoot },
            Validation = Task.Run(() => OwnedMaterialRegistry.Load(packageRoot)) };
        EditorApplication.update += Update;
    }
    private static void Require(Run run, bool value, string name)
    {
        run.Report.checks.Add(new Check { name = name, passed = value });
        if (!value) throw new InvalidOperationException(name);
    }
    private static void Setup(Run run, OwnedMaterialRegistry registry)
    {
        Require(run, registry.Enabled && registry.Rules.Count > 0 && registry.Catalog.Count > 0,
            "worker validated enabled installed profile, explicit rules and mapped owned archive hashes");
        string alias = registry.Rules[0].ownedTextureId;
        Shader shader = Shader.Find("Standard");
        if (shader == null) throw new InvalidOperationException("Built-in Standard shader is unavailable");
        // Change only this worker result's in-memory rule list. Input files, project
        // materials and game materials are untouched by the fixture.
        registry.Rules.Clear();
        registry.Rules.Add(new MaterialBindingRule { id = "owned-fixture", materialName = "Valheim Impact Binding Fixture",
            shaderName = shader.name, textureProperty = "_MainTex", originalTextureName = "Owned fixture fallback",
            originalWidth = 4, originalHeight = 4, ownedTextureId = alias });
        run.Registry = registry;
        run.Binder = Binder(run);
        run.Original = new Texture2D(4, 4) { name = "Owned fixture fallback", hideFlags = HideFlags.HideAndDontSave };
        run.Foreign = new Texture2D(4, 4) { name = "Owned fixture foreign edit", hideFlags = HideFlags.HideAndDontSave };
        run.OtherChannel = new Texture2D(4, 4) { name = "Owned fixture normal", hideFlags = HideFlags.HideAndDontSave };
        run.Root = new GameObject("Valheim Impact finite binding fixture") { hideFlags = HideFlags.HideAndDontSave };
        run.A = FixtureMaterial(run, shader, "Valheim Impact Binding Fixture");
        run.B = FixtureMaterial(run, shader, "Valheim Impact Binding Fixture");
        run.Miss = FixtureMaterial(run, shader, "Valheim Impact Binding Fixture (Instance)");
        run.Secondary = FixtureMaterial(run, shader, "Valheim Impact Binding Fixture", true);
        Require(run, run.Binder.MatchedCount == 3 && run.Binder.Scheduler.LeaseCount == 3 && run.Secondary.mainTexture == run.Original,
            "renderer discovery acquires exact demand for both shared material slots without starting a load");
        Require(run, run.Binder.MatchedCount == 3 && run.Binder.Scheduler.LeaseCount == 3 && run.Binder.Scheduler.StartedCount == 0 &&
            run.A.mainTexture == run.Original && run.B.mainTexture == run.Original && run.Miss.mainTexture == run.Original,
            "exact identity demand returns immediately, keeps originals and rejects Instance-name mismatch");
        run.PendingOpacity = FixtureMaterial(run, shader, "Valheim Impact Binding Fixture");
        run.AppliedOpacity = FixtureMaterial(run, shader, "Valheim Impact Binding Fixture");
        run.PendingOpacity.renderQueue = 3000;
    }
    private static OwnedMaterialBinder Binder(Run run, Action<string> log = null)
    {
        return new OwnedMaterialBinder(run.Registry, log ?? (message => Debug.Log(message)), spec => new ProbeLoad(spec, run),
            texture => run.Retiring.Add(new Retirement { Texture = texture, Frame = run.Frame + 3 }), texture => texture == null);
    }
    private static Material FixtureMaterial(Run run, Shader shader, string name, bool secondarySlot = false, bool transientRenderer = false, Action<Material> configure = null)
    {
        var material = new Material(shader) { name = name, hideFlags = HideFlags.HideAndDontSave };
        material.SetTexture("_MainTex", run.Original); material.SetTexture("_BumpMap", run.OtherChannel);
        material.SetTextureScale("_MainTex", new Vector2(2.5f, 3.25f));
        material.SetTextureOffset("_MainTex", new Vector2(0.125f, 0.375f));
        if (configure != null) configure(material);
        var go = new GameObject(name) { hideFlags = HideFlags.HideAndDontSave };
        go.transform.SetParent(run.Root.transform);
        var renderer = go.AddComponent<MeshRenderer>();
        // Only fixture setup constructs arrays. Production reads a scalar count
        // before fetching at most eight entries into its reusable material list.
        if (secondarySlot) renderer.sharedMaterials = new[] { run.A, material };
        else renderer.sharedMaterial = material;
        run.Binder.ObserveRenderer(renderer);
        if (transientRenderer) Object.DestroyImmediate(go);
        return material;
    }
    private static Material CutoutMaterial(Run run, Shader shader, string name, Action<Material> change = null, string label = "exact cutout", bool expectedAdmission = true)
    {
        long before = run.Binder.MatchedCount; int leases = run.Binder.Scheduler.LeaseCount;
        Material result = FixtureMaterial(run, shader, name, false, false, material =>
        {
            material.SetFloat("_Mode", 1); material.SetFloat("_Cutoff", .69f); material.SetFloat("_Cull", 0);
            material.SetFloat("_ZWrite", 1); material.SetFloat("_SrcBlend", 1); material.SetFloat("_DstBlend", 0);
            material.renderQueue = 2000;
            material.DisableKeyword("_ALPHATEST_ON"); material.DisableKeyword("_ALPHABLEND_ON"); material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            if (change != null) change(material);
        });
        run.Churn.Add(result); RecordCutoutCandidate(run, result, label, expectedAdmission, before, leases); return result;
    }
    private static void RecordCutoutCandidate(Run run, Material material, string label, bool expected, long before, int leases)
    {
        if (run.Report.cutoutCandidates.Count >= 32) throw new InvalidOperationException("Cutout candidate diagnostic limit exceeded");
        var row = new CutoutCandidate { label = label, material = material.name, shader = material.shader.name,
            expectedAdmission = expected, admitted = run.Binder.MatchedCount > before,
            matchedBefore = before, matchedAfter = run.Binder.MatchedCount, leasesBefore = leases, leasesAfter = run.Binder.Scheduler.LeaseCount,
            renderQueue = material.renderQueue, alphaTest = material.IsKeywordEnabled("_ALPHATEST_ON"), alphaBlend = material.IsKeywordEnabled("_ALPHABLEND_ON"),
            alphaPremultiply = material.IsKeywordEnabled("_ALPHAPREMULTIPLY_ON"),
            declaresAlphaTest = material.shader.keywordSpace.FindKeyword("_ALPHATEST_ON").isValid,
            declaresAlphaBlend = material.shader.keywordSpace.FindKeyword("_ALPHABLEND_ON").isValid,
            declaresAlphaPremultiply = material.shader.keywordSpace.FindKeyword("_ALPHAPREMULTIPLY_ON").isValid,
            properties = new[] { "_Mode", "_Cutoff", "_Cull", "_ZWrite", "_SrcBlend", "_DstBlend" }, present = new bool[6], values = new float[6] };
        for (int property = 0; property < row.properties.Length; property++)
        {
            row.present[property] = material.HasFloat(row.properties[property]);
            if (row.present[property]) row.values[property] = material.GetFloat(row.properties[property]);
        }
        run.Report.cutoutCandidates.Add(row);
    }
    private static void SetupCutout(Run run)
    {
        Shader shader = Shader.Find("Valheim Impact/Cutout Binding Fixture");
        if (shader == null) throw new InvalidOperationException("Stage owned CutoutBindingFixture.shader before running this fixture");
        const string name = "Valheim Impact Cutout Material Fixture";
        string alias = run.Registry.Rules[0].ownedTextureId;
        // As with the opaque fixture, these are new in-memory rules for an owned
        // test shader. Disk-loaded cutout rules remain restricted to Custom/Piece.
        run.Registry.Rules.Add(new MaterialBindingRule { id = "cutout-fixture", materialName = name, shaderName = shader.name,
            textureProperty = "_MainTex", originalTextureName = run.Original.name, originalWidth = 4, originalHeight = 4, ownedTextureId = alias,
            cutout = new CutoutBindingState { mode = 1, cutoff = .69f, cull = 0, zWrite = 1, srcBlend = 1, dstBlend = 0, renderQueue = 2000, alphaTest = false } });
        run.Registry.Rules.Add(new MaterialBindingRule { id = "opaque-cutout-rejection", materialName = "VI no cutout opt-in", shaderName = shader.name,
            textureProperty = "_MainTex", originalTextureName = run.Original.name, originalWidth = 4, originalHeight = 4, ownedTextureId = alias });
        run.Binder = Binder(run);
        run.CutoutStable = CutoutMaterial(run, shader, name);
        bool shaderDeclaresSavedState = false;
        for (int property = 0; property < shader.GetPropertyCount(); property++)
        {
            string propertyName = shader.GetPropertyName(property);
            shaderDeclaresSavedState |= propertyName == "_Mode" || propertyName == "_ZWrite" || propertyName == "_SrcBlend" || propertyName == "_DstBlend";
        }
        Require(run, !shaderDeclaresSavedState && run.CutoutStable.HasFloat("_Mode") && run.CutoutStable.GetFloat("_Mode") == 1 &&
            run.CutoutStable.HasFloat("_ZWrite") && run.CutoutStable.GetFloat("_ZWrite") == 1 &&
            run.CutoutStable.HasFloat("_SrcBlend") && run.CutoutStable.GetFloat("_SrcBlend") == 1 &&
            run.CutoutStable.HasFloat("_DstBlend") && run.CutoutStable.GetFloat("_DstBlend") == 0,
            "native material presence/getter APIs expose stored mode blend and depth floats absent from ShaderLab without missing-value reads");
        CutoutMaterial(run, shader, "VI no cutout opt-in", null, "missing cutout opt-in", false);
        string[] labels = { "mode changed", "cutoff changed", "cull changed", "zwrite changed", "source blend changed", "destination blend changed",
            "queue changed", "alpha-test enabled", "alpha-blend enabled", "alpha-premultiply enabled" };
        int changed = 0;
        foreach (Action<Material> change in new Action<Material>[] {
            material => material.SetFloat("_Mode", 2), material => material.SetFloat("_Cutoff", .4f), material => material.SetFloat("_Cull", 2),
            material => material.SetFloat("_ZWrite", 0), material => material.SetFloat("_SrcBlend", 5), material => material.SetFloat("_DstBlend", 10),
            material => material.renderQueue = 3000, material => material.EnableKeyword("_ALPHATEST_ON"),
            material => material.EnableKeyword("_ALPHABLEND_ON"), material => material.EnableKeyword("_ALPHAPREMULTIPLY_ON") })
            CutoutMaterial(run, shader, name, change, labels[changed++], false);
        // No saved _Mode/_ZWrite/_SrcBlend/_DstBlend values are set on this one.
        long before = run.Binder.MatchedCount; int leases = run.Binder.Scheduler.LeaseCount;
        Material missing = FixtureMaterial(run, shader, name); run.Churn.Add(missing);
        RecordCutoutCandidate(run, missing, "missing saved floats", false, before, leases);
        CutoutCandidate testKeyword = run.Report.cutoutCandidates.Find(candidate => candidate.label == "alpha-test enabled");
        CutoutCandidate blendKeyword = run.Report.cutoutCandidates.Find(candidate => candidate.label == "alpha-blend enabled");
        CutoutCandidate premultiplyKeyword = run.Report.cutoutCandidates.Find(candidate => candidate.label == "alpha-premultiply enabled");
        Require(run, testKeyword != null && testKeyword.declaresAlphaTest && testKeyword.alphaTest,
            "alpha-test mutation is a declared and enabled native shader keyword before testing its rejection");
        Require(run, blendKeyword != null && blendKeyword.declaresAlphaBlend && blendKeyword.alphaBlend,
            "alpha-blend mutation is a declared and enabled native shader keyword before testing its rejection");
        Require(run, premultiplyKeyword != null && premultiplyKeyword.declaresAlphaPremultiply && premultiplyKeyword.alphaPremultiply,
            "alpha-premultiply mutation is a declared and enabled native shader keyword before testing its rejection");
        Require(run, run.Binder.MatchedCount == 1 && run.Binder.Scheduler.LeaseCount == 1 && run.Binder.Scheduler.EngineStartCount == 0,
            "cutout opt-in accepts one exact state and rejects default opaque admission, missing floats and every blended or changed state before demand; matched=" +
            run.Binder.MatchedCount + ", leases=" + run.Binder.Scheduler.LeaseCount);
        run.CutoutPending = CutoutMaterial(run, shader, name);
        run.CutoutAdopted = CutoutMaterial(run, shader, name);
        run.CutoutForeign = CutoutMaterial(run, shader, name);
        run.CutoutKeyword = CutoutMaterial(run, shader, name);
        Require(run, run.Binder.MatchedCount == 5 && run.Binder.Scheduler.LeaseCount == 5 && run.Binder.Scheduler.EngineStartCount == 0 &&
            run.CutoutStable.mainTexture == run.Original && run.CutoutPending.mainTexture == run.Original,
            "exact cutout discovery retains originals and only queues asynchronous owned demand");
        run.CutoutPending.SetFloat("_Cutoff", .4f);
    }
    private static bool CutoutCompanionsPreserved(Run run, Material material)
    {
        return material.shader.name == "Valheim Impact/Cutout Binding Fixture" && material.GetFloat("_Mode") == 1 && material.GetFloat("_Cutoff") == .69f &&
            material.GetFloat("_Cull") == 0 && material.GetFloat("_ZWrite") == 1 && material.GetFloat("_SrcBlend") == 1 && material.GetFloat("_DstBlend") == 0 &&
            material.renderQueue == 2000 && !material.IsKeywordEnabled("_ALPHATEST_ON") && !material.IsKeywordEnabled("_ALPHABLEND_ON") &&
            !material.IsKeywordEnabled("_ALPHAPREMULTIPLY_ON") && material.GetTexture("_BumpMap") == run.OtherChannel &&
            material.GetTextureScale("_MainTex") == new Vector2(2.5f, 3.25f) && material.GetTextureOffset("_MainTex") == new Vector2(.125f, .375f);
    }
    private static void CheckSlotLimits(Run run)
    {
        var go = new GameObject("VI oversized material list fixture") { hideFlags = HideFlags.HideAndDontSave };
        go.transform.SetParent(run.Root.transform);
        var renderer = go.AddComponent<MeshRenderer>();
        var slots = new Material[2048];
        for (int i = 0; i < slots.Length; i++) slots[i] = i == 0 ? run.A : run.Secondary;
        renderer.sharedMaterials = slots;
        var messages = new List<string>();
        OwnedMaterialBinder binder = Binder(run, messages.Add);
        try
        {
            for (int i = 0; i < 5; i++) binder.ObserveRenderer(renderer);
            var buffer = (List<Material>)typeof(OwnedMaterialBinder).GetField("sharedMaterials", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(binder);
            Require(run, binder.MatchedCount == 1 && binder.Scheduler.LeaseCount == 1 && buffer.Count == 0 && buffer.Capacity == 8 &&
                messages.Count == 1 && run.Secondary.mainTexture == run.Original,
                "2048-slot renderer keeps first-slot demand, avoids material-list expansion and emits one bounded fallback warning");
        }
        finally { binder.RestoreForProcessExit(); }
        Require(run, binder.IsDrained && binder.Scheduler.EngineStartCount == 0, "oversized renderer demand cancels without starting a native load");
        renderer.sharedMaterials = new[] { run.A, run.Secondary };
        foreach (bool missing in new[] { true, false })
        {
            messages.Clear(); binder = Binder(run, messages.Add);
            try
            {
                // Simulate the platform capability result, not a separate discovery
                // implementation. A failed capability must be disabled after one use.
                int countCalls = 0;
                Func<Renderer, int> count = missing ? null : new Func<Renderer, int>(value => { countCalls++; throw new MissingMethodException("fixture count capability unavailable"); });
                typeof(OwnedMaterialBinder).GetField("materialCount", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(binder, count);
                for (int i = 0; i < 5; i++) binder.ObserveRenderer(renderer);
                Require(run, binder.MatchedCount == 1 && binder.Scheduler.LeaseCount == 1 && messages.Count == 1 &&
                    countCalls == (missing ? 0 : 1) && run.Secondary.mainTexture == run.Original,
                    missing ? "missing material-count capability retains first-slot coverage with one warning" :
                    "throwing material-count capability falls back once and retains first-slot coverage");
            }
            finally { binder.RestoreForProcessExit(); }
            if (!binder.IsDrained) throw new InvalidOperationException("Fallback demand did not release");
        }
        Object.DestroyImmediate(go);
    }
    private static void CheckSlotDiscoveryBudget(Run run)
    {
        var root = new GameObject("VI isolated multi-slot discovery budget") { hideFlags = HideFlags.HideAndDontSave };
        root.transform.SetParent(run.Root.transform);
        OwnedMaterialBinder binder = Binder(run);
        try
        {
            for (int i = 0; i < 16; i++)
            {
                var child = new GameObject("VI eight-slot renderer") { hideFlags = HideFlags.HideAndDontSave };
                child.transform.SetParent(root.transform);
                var materials = new Material[8];
                for (int slot = 0; slot < materials.Length; slot++)
                {
                    materials[slot] = new Material(run.A) { name = run.A.name, hideFlags = HideFlags.HideAndDontSave };
                    run.Churn.Add(materials[slot]);
                }
                child.AddComponent<MeshRenderer>().sharedMaterials = materials;
            }
            const BindingFlags fields = BindingFlags.Instance | BindingFlags.NonPublic;
            // Seed only our fixture root and mark all real scenes already visited.
            // The production traversal runs unchanged but cannot enumerate another
            // scene or acquire demand for a project material during this check.
            ((List<GameObject>)typeof(OwnedMaterialBinder).GetField("roots", fields).GetValue(binder)).Add(root);
            typeof(OwnedMaterialBinder).GetField("sceneIndex", fields).SetValue(binder, UnityEngine.SceneManagement.SceneManager.sceneCount);
            MethodInfo discover = typeof(OwnedMaterialBinder).GetMethod("Discover", fields);
            bool bounded = true; int passes = 0;
            while (binder.MatchedCount < 128 && passes++ < 16)
            {
                long before = binder.MatchedCount;
                discover.Invoke(binder, new object[] { 0.0 });
                bounded &= binder.MatchedCount - before <= 64;
            }
            Require(run, bounded && passes > 1 && binder.MatchedCount == 128 && binder.Scheduler.LeaseCount == 128 && binder.Scheduler.EngineStartCount == 0,
                "eight-slot discovery reaches 128 distinct materials while admitting at most 64 material observations per frame budget");
        }
        finally { binder.RestoreForProcessExit(); Object.DestroyImmediate(root); }
        Require(run, binder.IsDrained, "bounded multi-slot discovery releases all fixture-only queued demand without native allocations");
    }
    private static void CheckHostQuit(Run run)
    {
        var messages = new List<string>();
        var errors = new List<string>();
        var quitObject = new GameObject("VI fixture simulated process quit") { hideFlags = HideFlags.HideAndDontSave };
        var removedObject = new GameObject("VI fixture dynamic removal") { hideFlags = HideFlags.HideAndDontSave };
        quitObject.transform.SetParent(run.Root.transform); removedObject.transform.SetParent(run.Root.transform);
        try
        {
            OwnedMaterialHost quitting = FixtureHost(quitObject, run.Binder, messages, errors);
            run.QuitForeign.mainTexture = run.Foreign;
            // Invoke the real host callbacks without ending the Editor process.
            // The fixture retains this real binder and pumps its native drain later.
            HostCallback(quitting, "OnApplicationQuit");
            long resident = run.Binder.Scheduler.ResidentBytes;
            Require(run, run.QuitOwned.mainTexture == run.Original && run.QuitForeign.mainTexture == run.Foreign &&
                run.Binder.Scheduler.LeaseCount == 0 && resident > 0 && !run.Binder.IsDrained,
                "process quit restores originals and preserves foreign changes before releasing leases, without claiming native drain");
            HostCallback(quitting, "OnDestroy");
            Require(run, errors.Count == 0 && messages.Exists(message => message.Contains("residentPayload=" + resident)) &&
                run.Binder.Scheduler.ResidentBytes == resident && !run.Binder.IsDrained,
                "normal process quit suppresses unexpected-removal errors while reporting the remaining owned allocation honestly");
            OwnedMaterialHost removed = FixtureHost(removedObject, run.Binder, messages, errors);
            HostCallback(removed, "OnDestroy");
            Require(run, errors.Exists(message => message.Contains("pump destroyed before acknowledged drain")),
                "dynamic host removal still reports undrained ownership when no process-quit callback occurred");
        }
        finally
        {
            Object.DestroyImmediate(quitObject); Object.DestroyImmediate(removedObject);
        }
    }
    private static OwnedMaterialHost FixtureHost(GameObject go, OwnedMaterialBinder binder, List<string> messages, List<string> errors)
    {
        var host = go.AddComponent<OwnedMaterialHost>();
        const BindingFlags fields = BindingFlags.Instance | BindingFlags.NonPublic;
        // Skip Initialize's unrelated background registry work. Inject only the
        // already validated binder and sinks needed by the lifecycle callbacks.
        typeof(OwnedMaterialHost).GetField("binder", fields).SetValue(host, binder);
        typeof(OwnedMaterialHost).GetField("info", fields).SetValue(host, new Action<string>(messages.Add));
        typeof(OwnedMaterialHost).GetField("error", fields).SetValue(host, new Action<string>(errors.Add));
        return host;
    }
    private static void HostCallback(OwnedMaterialHost host, string method)
    {
        typeof(OwnedMaterialHost).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(host, null);
    }
    private static void Update()
    {
        Run run = current;
        if (run == null) return;
        try
        {
            run.Frame++;
            if (!run.Failed && EditorApplication.timeSinceStartup - run.StartTime > 45) throw new TimeoutException("Material fixture exceeded 45 seconds");
            if (run.Binder == null)
            {
                if (!run.Validation.IsCompleted) return;
                var registry = run.Validation.GetAwaiter().GetResult();
                Setup(run, registry);
            }
            for (int i = run.Retiring.Count - 1; i >= 0; i--)
            {
                Retirement item = run.Retiring[i];
                if (run.Frame < item.Frame) continue;
                int index = run.Transferred.FindIndex(value => ReferenceEquals(value, item.Texture));
                string path = item.Texture == null ? "" : AssetDatabase.GetAssetPath(item.Texture);
                if (index < 0 || !string.IsNullOrEmpty(path)) throw new InvalidOperationException("Refusing unowned or project-backed texture destruction: " + path);
                if (item.Texture != null) Object.DestroyImmediate(item.Texture, true);
                if (item.Texture != null) throw new InvalidOperationException("Owned texture destruction was not acknowledged");
                run.Transferred.RemoveAt(index); run.Retiring.RemoveAt(i);
            }
            long before = run.Binder.Scheduler.EngineStartCount;
            run.Binder.Tick(run.Frame, EditorApplication.timeSinceStartup - run.StartTime, false);
            var scheduler = run.Binder.Scheduler;
            if (scheduler.EngineStartCount - before > 1) throw new InvalidOperationException("Engine start gate exceeded");
            if (run.Report.samples.Count < 2048) run.Report.samples.Add(new Sample { frame = run.Frame,
                applied = run.Binder.AppliedCount, restored = run.Binder.RestoredCount, foreign = run.Binder.ForeignChangeCount,
                leases = scheduler.LeaseCount, pending = scheduler.PendingBytes, resident = scheduler.ResidentBytes,
                retiring = scheduler.RetiringBytes, engineStarts = scheduler.EngineStartCount });
            if (run.Failed)
            {
                if (run.Binder.IsDrained) Finish(run, false);
                else if (!run.Wrote && EditorApplication.timeSinceStartup - run.LastWrite > 1) Write(run, false, true);
                return;
            }
            if (scheduler.ErrorCount != 0) throw new InvalidOperationException(scheduler.LastError);
            switch (run.Stage)
            {
                case 0:
                    if (run.Binder.AppliedCount != 4) break;
                    Require(run, run.A.mainTexture != run.Original && run.A.mainTexture != null && ReferenceEquals(run.A.mainTexture, run.B.mainTexture) &&
                        ReferenceEquals(run.A.mainTexture, run.Secondary.mainTexture) && run.Miss.mainTexture == run.Original && scheduler.CompletedCount == 1,
                        "native async apply shares one owned texture across both renderer material slots and preserves the exact-name miss");
                    Require(run, run.PendingOpacity.mainTexture == run.Original && run.PendingOpacity.renderQueue == 3000 &&
                        run.Binder.ForeignChangeCount == 1 && scheduler.LeaseCount == 4,
                        "opaque eligibility is rechecked before apply and transparent pending demand releases without a write");
                    Require(run, run.A.shader.name == "Standard" && run.A.GetTextureScale("_MainTex") == new Vector2(2.5f, 3.25f) &&
                        run.A.GetTextureOffset("_MainTex") == new Vector2(0.125f, 0.375f) && run.A.GetTexture("_BumpMap") == run.OtherChannel,
                        "apply preserves shader, original UV scale and offset, and unrelated texture channel");
                    run.B.mainTexture = run.Foreign;
                    run.AppliedOpacity.EnableKeyword("_ALPHATEST_ON");
                    run.Stage = 1;
                    break;
                case 1:
                    Require(run, run.B.mainTexture == run.Foreign && run.Binder.ForeignChangeCount == 3 && scheduler.LeaseCount == 2 && run.A.mainTexture != null,
                        "foreign material change is preserved and releases only its own demand");
                    Require(run, run.AppliedOpacity.mainTexture == run.Original && run.AppliedOpacity.IsKeywordEnabled("_ALPHATEST_ON") &&
                        run.Binder.RestoredCount == 1,
                        "alpha keyword change after apply restores the owned slot, preserves the foreign keyword and releases demand");
                    run.Binder.Stop(); run.Stage = 2;
                    break;
                case 2:
                    Require(run, run.A.mainTexture == run.Original && run.Secondary.mainTexture == run.Original && run.B.mainTexture == run.Foreign && scheduler.LeaseCount == 0 &&
                        run.Binder.RestoredCount == 3 && scheduler.RetiringBytes > 0,
                        "disable restores both shared slots before releasing leases and retains deferred-destruction reservation");
                    Require(run, run.A.GetTextureScale("_MainTex") == new Vector2(2.5f, 3.25f) &&
                        run.A.GetTextureOffset("_MainTex") == new Vector2(0.125f, 0.375f) && run.A.GetTexture("_BumpMap") == run.OtherChannel,
                        "disable preserves captured UV transforms and unrelated material channel");
                    run.Stage = 3;
                    break;
                case 3:
                    if (!run.Binder.IsDrained) break;
                    Require(run, scheduler.AllocatedBytes == 0 && scheduler.LeaseCount == 0 && run.Retiring.Count == 0 && run.Transferred.Count == 0 &&
                        run.A.mainTexture == run.Original && run.Secondary.mainTexture == run.Original && run.B.mainTexture == run.Foreign,
                        "disable finishes after native release acknowledgement with zero owned allocations and valid originals");
                    run.Binder = Binder(run);
                    run.Stage = 4;
                    break;
                case 4:
                    // Materials stay alive while their observed renderer is destroyed.
                    // Each batch is a complete fixture-only pass, then an empty pass.
                    // More than 1024 total identities must fit a 32-record working set.
                    if (run.Binder.TrackedMaterials != 0) throw new InvalidOperationException("Completed unseen material records were not reclaimed");
                    if (run.Churn.Count < 1056)
                    {
                        for (int i = 0; i < 32; i++)
                            run.Churn.Add(FixtureMaterial(run, run.A.shader, "Valheim Impact Binding Fixture", false, true));
                        double now = EditorApplication.timeSinceStartup - run.StartTime;
                        run.Binder.CompleteObservationPass(now);
                        run.Binder.CompleteObservationPass(now);
                        break;
                    }
                    Require(run, run.Binder.MatchedCount == 1056 && run.Binder.TrackedMaterials == 0 && scheduler.LeaseCount == 0 &&
                        run.Churn.TrueForAll(material => material != null && material.mainTexture == run.Original),
                        "1056 distinct surviving materials reclaim unseen records after renderer churn without exhausting the 1024-record cap");
                    run.Churn.Add(FixtureMaterial(run, run.A.shader, "Valheim Impact Binding Fixture"));
                    Require(run, run.Binder.MatchedCount == 1057 && scheduler.LeaseCount == 1,
                        "new renderer demand remains admitted after more than one registry capacity of material churn");
                    run.Binder.Stop(); run.Stage = 5;
                    break;
                case 5:
                    if (!run.Binder.IsDrained) break;
                    Require(run, scheduler.AllocatedBytes == 0 && scheduler.LeaseCount == 0,
                        "churn fixture shutdown releases all queued demand without native allocation leftovers");
                    CheckSlotLimits(run);
                    CheckSlotDiscoveryBudget(run);
                    run.Binder = Binder(run);
                    run.QuitOwned = FixtureMaterial(run, run.A.shader, "Valheim Impact Binding Fixture");
                    run.QuitForeign = FixtureMaterial(run, run.A.shader, "Valheim Impact Binding Fixture");
                    run.Churn.Add(run.QuitOwned); run.Churn.Add(run.QuitForeign);
                    run.Stage = 6;
                    break;
                case 6:
                    if (run.Binder.AppliedCount != 2) break;
                    CheckHostQuit(run);
                    run.Stage = 7;
                    break;
                case 7:
                    if (!run.Binder.IsDrained) break;
                    Require(run, scheduler.AllocatedBytes == 0 && scheduler.LeaseCount == 0 && run.Retiring.Count == 0 && run.Transferred.Count == 0,
                        "simulated quit fixture finishes its separately pumped native drain with zero retained owned allocations");
                    SetupCutout(run); run.Stage = 8;
                    break;
                case 8:
                    if (run.Binder.AppliedCount != 4) break;
                    Require(run, run.CutoutStable.mainTexture != run.Original && ReferenceEquals(run.CutoutStable.mainTexture, run.CutoutAdopted.mainTexture) &&
                        scheduler.CompletedCount == 1 && scheduler.LeaseCount == 4 && CutoutCompanionsPreserved(run, run.CutoutStable),
                        "native cutout adoption shares one owned texture while preserving cutoff cull saved blend depth values keywords UVs and companion channel");
                    Require(run, run.CutoutPending.mainTexture == run.Original && run.CutoutPending.GetFloat("_Cutoff") == .4f && run.Binder.ForeignChangeCount == 1,
                        "cutoff change during asynchronous preparation rejects adoption and releases pending demand without overwriting the change");
                    run.CutoutAdopted.SetFloat("_Cull", 2);
                    run.CutoutForeign.mainTexture = run.Foreign;
                    run.CutoutKeyword.EnableKeyword("_ALPHATEST_ON");
                    run.Stage = 9;
                    break;
                case 9:
                    Require(run, run.CutoutAdopted.mainTexture == run.Original && run.CutoutAdopted.GetFloat("_Cull") == 2 &&
                        run.CutoutKeyword.mainTexture == run.Original && run.CutoutKeyword.IsKeywordEnabled("_ALPHATEST_ON") &&
                        run.CutoutForeign.mainTexture == run.Foreign && scheduler.LeaseCount == 1 && run.Binder.RestoredCount == 2 && run.Binder.ForeignChangeCount == 4,
                        "applied cutout cull and keyword changes restore only owned texture slots while a foreign texture remains untouched");
                    run.Binder.Stop(); run.Stage = 10;
                    break;
                case 10:
                    Require(run, run.CutoutStable.mainTexture == run.Original && scheduler.LeaseCount == 0 && scheduler.RetiringBytes > 0 &&
                        CutoutCompanionsPreserved(run, run.CutoutStable) && run.CutoutForeign.mainTexture == run.Foreign,
                        "cutout disable restores the original before releasing its lease and retains deferred native retirement accounting");
                    run.Stage = 11;
                    break;
                case 11:
                    if (!run.Binder.IsDrained) break;
                    Require(run, scheduler.AllocatedBytes == 0 && scheduler.LeaseCount == 0 && run.Retiring.Count == 0 && run.Transferred.Count == 0,
                        "cutout shutdown reaches acknowledged zero native ownership after restoration");
                    Finish(run, true);
                    break;
            }
        }
        catch (Exception ex)
        {
            if (!run.Failed)
            {
                run.Failed = true; run.Report.error = ex.ToString();
                if (run.Binder != null) run.Binder.Stop();
                Debug.LogError("Material binding fixture failed; retaining unfinished native ownership: " + ex);
            }
            if (run.Binder == null || run.Binder.IsDrained) Finish(run, false);
            else if (!run.Wrote && EditorApplication.timeSinceStartup - run.LastWrite > 1) Write(run, false, true);
        }
    }
    private static void Write(Run run, bool passed, bool pending)
    {
        run.LastWrite = EditorApplication.timeSinceStartup; run.Wrote = false;
        try
        {
            run.Report.completed = true; run.Report.passed = passed; run.Report.cleanupPending = pending;
            string json = JsonUtility.ToJson(run.Report, true);
            var decoded = JsonUtility.FromJson<Report>(json);
            if (decoded == null || decoded.checks.Count != run.Report.checks.Count || decoded.cutoutCandidates.Count != run.Report.cutoutCandidates.Count || !decoded.completed)
                throw new InvalidDataException("Material report round-trip failed");
            Directory.CreateDirectory(Path.GetDirectoryName(run.Output));
            string temporary = run.Output + ".tmp"; File.WriteAllText(temporary, json);
            if (File.Exists(run.Output)) File.Replace(temporary, run.Output, null); else File.Move(temporary, run.Output);
            if (File.ReadAllText(run.Output) != json) throw new IOException("Material report disk readback failed");
            run.Wrote = true; Debug.Log("Material binding probe report written and verified: " + run.Output);
        }
        catch (Exception ex) { Debug.LogError("Cannot write material probe report: " + ex); }
    }
    private static void Finish(Run run, bool passed)
    {
        if (run.Root != null) Object.DestroyImmediate(run.Root);
        foreach (Object value in new Object[] { run.A, run.B, run.Miss, run.Secondary, run.PendingOpacity, run.AppliedOpacity, run.Original, run.Foreign, run.OtherChannel })
            if (value != null) Object.DestroyImmediate(value);
        foreach (Material material in run.Churn) if (material != null) Object.DestroyImmediate(material);
        Write(run, passed, false); EditorApplication.update -= Update; current = null;
        Debug.Log("Material binding probe " + (passed ? "passed: " : "failed: ") + run.Output);
    }
}
