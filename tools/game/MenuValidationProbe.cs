// Local validation only. Never include this plugin in an installer or release.
using System;
using System.IO;
using System.Collections.Generic;
#if !PROBE_POLICY_TEST
using System.Reflection;
using BepInEx;
using BepInEx.Bootstrap;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;
#endif

namespace ValheimImpact.LocalValidation
{
    // Kept independent of Unity so the bounded slot read and complete source
    // identity can be exercised without loading the game or creating a scene.
    public static class MenuValidationPairPolicy
    {
        public const int MaxSlots = 8;
        public static bool TryReadSlots<T>(Func<int> count, Action<List<T>> read, List<T> buffer, out string limitation)
        {
            buffer.Clear(); limitation = null;
            if (count == null) { limitation = "Scalar material count capability unavailable"; return false; }
            try
            {
                int length = count();
                if (length < 1 || length > MaxSlots) { limitation = "Material count outside 1..8; no list fetched"; return false; }
                read(buffer);
                if (buffer.Count == length) return true;
                limitation = "Material count changed during bounded read";
            }
            catch (Exception error) { limitation = "Material read failed: " + error.GetType().Name; }
            buffer.Clear(); return false;
        }
        public static bool ValidLayout(int count, int submeshes, int selectedSlot)
        { return count >= 1 && count <= MaxSlots && submeshes == count && selectedSlot >= 0 && selectedSlot < submeshes; }
        public static string SourceIdentity(int meshId, IList<int> materials, int selectedSlot)
        {
            if (!ValidLayout(materials.Count, materials.Count, selectedSlot)) throw new ArgumentException("Unsupported source material layout");
            string identity = meshId + ":" + selectedSlot;
            for (int slot = 0; slot < materials.Count; slot++) identity += ":" + materials[slot];
            return identity;
        }
        public static void CreateFixtureSlots<T>(IList<T> source, int selectedSlot, Func<T, int, bool, T> clone,
            out T[] reference, out T[] authored)
        {
            if (!ValidLayout(source.Count, source.Count, selectedSlot)) throw new ArgumentException("Unsupported fixture material layout");
            reference = new T[source.Count]; authored = new T[source.Count];
            for (int slot = 0; slot < source.Count; slot++)
            {
                reference[slot] = clone(source[slot], slot, false);
                authored[slot] = slot == selectedSlot ? clone(source[slot], slot, true) : reference[slot];
            }
        }
    }
    public static class MenuValidationPolicy
    {
        public static string ParseOutput(string[] args)
        {
            int selected = -1, count = 0; bool demo = false;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "-vi-menu-validation") { selected = i; count++; }
                if (args[i] == "-demomode") demo = true;
            }
            if (count == 0) return null;
            if (count != 1 || !demo || selected + 1 >= args.Length || !Path.IsPathRooted(args[selected + 1]))
                throw new ArgumentException("Validation requires one -vi-menu-validation absolute-output argument and -demomode");
            foreach (string arg in args)
                if (arg == "-joinserverwithcharacter" || arg == "-joincode" || arg == "-joinserver" ||
                    arg == "-joinip" || arg == "-world" || arg == "-server" || arg == "-character" ||
                    arg == "-connect" || arg == "+connect")
                    throw new ArgumentException("World, character and connection arguments are incompatible with menu validation");
            return Path.GetFullPath(args[selected + 1]);
        }
        public static bool CanOperate(bool menu, bool world, bool player, string scene)
        { return menu && !world && !player && string.Equals(scene, "start", StringComparison.Ordinal); }
        public static string NewOutput(string output, string game, string saves)
        {
            if (!Path.IsPathRooted(output)) throw new ArgumentException("Output must be absolute");
            output = Path.GetFullPath(output).TrimEnd(Path.DirectorySeparatorChar);
            if (output.Length < 2 || Directory.Exists(output) || File.Exists(output))
                throw new IOException("Validation output must be a new, absent local directory");
            foreach (string forbidden in new[] { game, saves })
            {
                string root = Path.GetFullPath(forbidden).TrimEnd(Path.DirectorySeparatorChar);
                if (output == root || output.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal))
                    throw new IOException("Validation output cannot be inside the game or original saves");
            }
            for (string path = output; path != null; path = Path.GetDirectoryName(path))
            {
                try
                {
                    if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("Validation output cannot use symlinks");
                }
                catch (FileNotFoundException) { }
                catch (DirectoryNotFoundException) { }
            }
            return output;
        }
    }
#if !PROBE_POLICY_TEST
    [BepInPlugin("org.valheimimpact.validation", "Valheim Impact Local Menu Validation", "0.1.0")]
    public sealed class MenuValidationProbe : BaseUnityPlugin
    {
        [Serializable] private sealed class MaterialRecord
        {
            public string material, shader, texture; public int instanceId, textureId, width, height;
            public bool originalMatch, ownedMatch;
        }
        [Serializable] private sealed class MeshRecord
        { public string name; public int instanceId, vertices, submeshes; public float[] boundsSize; }
        [Serializable] private sealed class PairRecord
        {
            public string material, mesh, expectedOwned, actualTexture, limitation, sourceRenderer, sourceHierarchy, slotReadLimitation;
            public int materialCandidates, originalTextureCandidates, meshCandidates, rendererCandidates, distinctSourcePairs, actualWidth, actualHeight, visiblePixels, changedPixels;
            public int expectedSelectedSlot, expectedSubmeshes, selectedSlot = -1, materialSlotCount, meshVertices, meshSubmeshes, scannedRenderers, meshLayoutCandidates, slotReadRejected, slotLayoutRejected;
            public int companionMaterialCount, companionTextureCount;
            public float rowCenterY;
            public bool applied, referencePreserved, companionSlotsPreserved, slotAssignmentsPreserved, allSubmeshesPreserved, rendererScanTruncated, distinctSourcePairsIsLowerBound;
            public float[] meshBoundsSize, fixtureRotationEuler;
            public long[] submeshIndexCounts;
            public List<MaterialSlotRecord> sourceSlots = new List<MaterialSlotRecord>();
        }
        [Serializable] private sealed class MaterialSlotRecord
        {
            public int slot, materialId, textureId, textureWidth, textureHeight;
            public string material, shader, texture;
            public bool hasMainTexture, originalTextureMatch, ownedTextureMatch;
            public float[] scale, offset;
        }
        [Serializable] private sealed class RockRendererRecord
        {
            public string renderer, rendererType, hierarchy, scene, mesh, slotReadLimitation;
            public int instanceId, meshId, vertices, submeshes, materialSlotCount = -1;
            public bool enabled, activeInHierarchy, sceneValid, hierarchyTruncated, materialSlotsTruncated;
            public MaterialSlotRecord firstSlot;
            public List<MaterialSlotRecord> slots = new List<MaterialSlotRecord>();
            public List<string> selectorRejections = new List<string>();
        }
        [Serializable] private sealed class Report
        {
            public string startedUtc, phase, scene, output, saves, unityVersion, graphicsApi, gpu, colorSpace, screenshot, error;
            public string scope = "Local main-menu fixture only. Left uses the captured original; right uses production-bound authored texture. Existing loaded game meshes and shaders are borrowed. No character/world load, game-bundle load, scene coverage, route performance or hardware-target claim.";
            public bool demoMode, dontSaveAnything, expectedPluginsOnly, passed, aborted, quitRequested, cleanupRequested, createdObjectsCleaned;
            public int reportedVramMiB, screenWidth, screenHeight, loadedMaterials, loadedMeshes, loadedTextures, loadedRenderers, frameSamples;
            public int expectedPairs = 3, builtPairs;
            public int rockDiagnosticScannedRenderers, rockDiagnosticRelevantRenderers, rockDiagnosticOmittedRecords;
            public bool rockDiagnosticScanTruncated;
            public string rockDiagnosticScope = "At most 65536 entries from the existing MeshRenderer snapshot, selected only for diagnostic relevance by first material stone_huge prefix or Rock_3_Untitled mesh prefix. At most 128 records and 8 material slots per record. This does not broaden the exact pair selector.";
            public long unityAllocatedBytes, unityReservedBytes, managedBytes;
            public double elapsedSeconds, meanFrameMs, maxFrameMs;
            public List<string> plugins = new List<string>(), limitations = new List<string>();
            public List<MaterialRecord> materials = new List<MaterialRecord>();
            public List<MeshRecord> meshes = new List<MeshRecord>();
            public List<PairRecord> pairs = new List<PairRecord>();
            public List<RockRendererRecord> rockRenderers = new List<RockRendererRecord>();
        }
        private sealed class Pair
        {
            internal PairRecord Record; internal Material Reference, Authored; internal Texture2D Original;
            internal Material[] ReferenceSlots, AuthoredSlots;
            internal MeshRenderer Left, Right; internal Mesh Mesh;
            internal readonly List<CompanionSlot> Companions = new List<CompanionSlot>();
        }
        private sealed class TextureSlot
        {
            internal string Name; internal Texture Texture; internal Vector2 Scale, Offset;
        }
        private sealed class CompanionSlot
        {
            internal Material Material; internal Shader Shader;
            internal readonly List<TextureSlot> Textures = new List<TextureSlot>();
        }
        private readonly List<Pair> pairs = new List<Pair>();
        private readonly List<Material> ownedMaterials = new List<Material>();
        private Report report;
        private GameObject fixture;
        private Camera capture;
        private RenderTexture target;
        private bool armed, aborted, enteredMenu, wroteReport;
        private int stage;
        private double started, menuSince, applyDeadline, readySince = -1, cleanupAt, frameSum;
        private const int Layer = 31, Width = 3840, Height = 2160;
        private const int MaxSourceRenderers = 65536;
        private static readonly Func<Renderer, int> ReadMaterialCount = ResolveMaterialCount();
        private readonly List<Material> sourceSlotBuffer = new List<Material>(MenuValidationPairPolicy.MaxSlots);
        private static readonly Vector3 FixtureOrigin = new Vector3(20000, 20000, 20000);

        private void Awake()
        {
            try
            {
                string output = MenuValidationPolicy.ParseOutput(Environment.GetCommandLineArgs());
                if (output == null) return;
                // BepInEx can start before FejdStartup. This startup-only absence
                // check permits save prevention, never scene actions or game quit.
                if (Game.instance != null || Player.m_localPlayer != null)
                    throw new InvalidOperationException("World or local player already exists; validation remains inactive");
                output = MenuValidationPolicy.NewOutput(output, Path.GetDirectoryName(Application.dataPath), Application.persistentDataPath);
                SaveSystem.SetSessionFlags(SaveSystemSessionFlags.DontSaveAnything);
                Utils.SetSaveDataPath(Path.Combine(output, "saves"));
                Directory.CreateDirectory(output); Directory.CreateDirectory(Path.Combine(output, "saves"));
                started = Time.realtimeSinceStartupAsDouble;
                report = new Report { output = output, saves = Path.Combine(output, "saves"), startedUtc = DateTime.UtcNow.ToString("o"), phase = "awaiting-menu" };
                armed = true; WriteReport();
                Logger.LogInfo("Local validation armed with save prevention and isolated save path: " + output);
            }
            catch (Exception ex) { armed = false; aborted = true; Logger.LogError("Local menu validation inactive: " + ex); }
        }
        private bool MenuGuard()
        { return !aborted && MenuValidationPolicy.CanOperate(FejdStartup.instance != null, Game.instance != null, Player.m_localPlayer != null, SceneManager.GetActiveScene().name); }
        private void RequireMenu()
        { if (!MenuGuard()) throw new InvalidOperationException("Positive main-menu guard was lost"); }
        private void Update()
        {
            if (!armed || aborted) return;
            try
            {
                double now = Time.realtimeSinceStartupAsDouble;
                if (Game.instance != null || Player.m_localPlayer != null) { Abort("World or local player appeared. Automated actions and quit permanently disabled."); return; }
                if (!MenuGuard())
                {
                    if (enteredMenu || now - started > 90) Abort("Known main-menu guard unavailable. Game was left running.");
                    return;
                }
                enteredMenu = true;
                if (!SaveSystem.HasSessionFlag(SaveSystemSessionFlags.DontSaveAnything) ||
                    Utils.GetSaveDataPath(FileHelpers.FileSource.Local) != report.saves)
                { Abort("Save-prevention state changed. Game was left running."); return; }
                report.frameSamples++; frameSum += Time.unscaledDeltaTime * 1000.0;
                report.maxFrameMs = Math.Max(report.maxFrameMs, Time.unscaledDeltaTime * 1000.0);
                if (stage == 0) { menuSince = now; stage = 1; report.phase = "menu-settling"; WriteReport(); }
                if (now - started > 90 && stage < 3) { report.limitations.Add("90-second diagnostic deadline reached"); Finish(false); }
                if (stage == 1 && now - menuSince >= 20)
                {
                    RequireMenu(); InspectAndBuild();
                    if (pairs.Count == 0) Finish(false);
                    else { stage = 2; applyDeadline = now + 30; report.phase = "waiting-production-binding"; WriteReport(); }
                }
                if (stage == 2)
                {
                    RequireMenu(); bool ready = ObserveApplied();
                    if (ready && readySince < 0) readySince = now;
                    if (ready && now - readySince >= 1) { CaptureComparison(); Finish(report.passed); }
                    else if (now >= applyDeadline) { report.limitations.Add("Production replacement did not become ready within 30 seconds"); Finish(false); }
                }
                if (stage == 3 && now >= cleanupAt)
                {
                    // No process-kill fallback. Every automatic quit rechecks the
                    // positive menu, absence, demo and save-prevention conditions.
                    RequireMenu();
                    bool cleaned = fixture == null;
                    foreach (Material material in ownedMaterials) cleaned &= material == null;
                    report.createdObjectsCleaned = cleaned;
                    if (!cleaned && now - started <= 95) return;
                    if (!cleaned) { report.passed = false; report.limitations.Add("Owned cleanup was requested but Unity-null acknowledgement did not arrive before the final menu deadline"); }
                    if (!DemoMode.Enabled) { Abort("Demo mode unavailable; automatic quit suppressed"); return; }
                    report.phase = "completed"; report.quitRequested = true; WriteReport();
                    RequireMenu(); armed = false; Application.Quit();
                }
            }
            catch (Exception ex)
            {
                if (!MenuGuard()) { Abort(ex.ToString()); return; }
                report.error = ex.ToString(); Logger.LogError(ex);
                try { Finish(false); } catch (Exception cleanup) { Abort("Cleanup failed: " + cleanup); }
            }
        }
        private void InspectAndBuild()
        {
            RequireMenu();
            foreach (string guid in Chainloader.PluginInfos.Keys) report.plugins.Add(guid);
            report.plugins.Sort(StringComparer.Ordinal);
            report.expectedPluginsOnly = report.plugins.Count == 2 && report.plugins.Contains("org.valheimimpact.validation") && report.plugins.Contains("org.valheimimpact.diagnostics");
            if (!report.expectedPluginsOnly) { report.limitations.Add("Loaded plugin GUIDs differ from the expected production and validation pair"); return; }
            if (!DemoMode.Enabled) { report.limitations.Add("Installed game did not enable demo mode"); return; }
            // Exactly one diagnostic snapshot per type, never used by production.
            // No game bundles or prefabs are loaded and no original is mutated.
            Material[] materials = Resources.FindObjectsOfTypeAll<Material>();
            Mesh[] meshes = Resources.FindObjectsOfTypeAll<Mesh>();
            Texture2D[] textures = Resources.FindObjectsOfTypeAll<Texture2D>();
            MeshRenderer[] renderers = Resources.FindObjectsOfTypeAll<MeshRenderer>();
            report.loadedMaterials = materials.Length; report.loadedMeshes = meshes.Length; report.loadedTextures = textures.Length; report.loadedRenderers = renderers.Length;
            foreach (Material material in materials)
            {
                if (material == null || (material.name != "stone_huge" && material.name != "woodwall" && material.name != "woodpole" && material.name != "wood_roof_mat") || report.materials.Count >= 128) continue;
                Texture texture = material.HasProperty("_MainTex") ? material.GetTexture("_MainTex") : null;
                bool stone = material.name == "stone_huge", roof = material.name == "wood_roof_mat";
                report.materials.Add(new MaterialRecord { material = material.name, shader = material.shader == null ? null : material.shader.name,
                    instanceId = material.GetInstanceID(), texture = texture == null ? null : texture.name, textureId = texture == null ? 0 : texture.GetInstanceID(),
                    width = texture == null ? 0 : texture.width, height = texture == null ? 0 : texture.height,
                    originalMatch = TextureMatches(texture, stone ? "rock_256" : roof ? "wood_roof_d" : "Planks5c_low", stone ? 512 : 128),
                    ownedMatch = TextureMatches(texture, stone ? "granite_hd_albedo" : roof ? "roof_atlas_hd_albedo" : "timber_hd_albedo", 1024) });
            }
            foreach (Mesh mesh in meshes)
                if (mesh != null && (mesh.name == "Rock_3_Untitled" || (mesh.name == "default" && (mesh.vertexCount == 106 || mesh.vertexCount == 312)) || mesh.name == "Cube_Cube_Material") && report.meshes.Count < 128)
                    report.meshes.Add(new MeshRecord { name = mesh.name, instanceId = mesh.GetInstanceID(), vertices = mesh.vertexCount, submeshes = mesh.subMeshCount,
                        boundsSize = new[] { mesh.bounds.size.x, mesh.bounds.size.y, mesh.bounds.size.z } });
            InspectRockRenderers(renderers);
            RequireMenu();
            fixture = new GameObject("VI local menu comparison") { layer = Layer, hideFlags = HideFlags.DontSave };
            fixture.transform.position = FixtureOrigin;
            AddPair(materials, meshes, textures, renderers, "stone_huge", "Custom/StaticRock", "rock_256", 512, "granite_hd_albedo", "default", 106, 1, 0, 4.4f, Vector3.one, Quaternion.identity, Vector2.one, "highstone_2/high");
            AddPair(materials, meshes, textures, renderers, "woodpole", "Custom/Piece", "Planks5c_low", 128, "timber_hd_albedo", "Cube_Cube_Material", 66, 1, 0, 0, new Vector3(1, .4f, .4f), Quaternion.Euler(0, 0, 90), new Vector2(.3f, .13f));
            AddPair(materials, meshes, textures, renderers, "wood_roof_mat", "Custom/Piece", "wood_roof_d", 128, "roof_atlas_hd_albedo", "default", 312, 2, 0, -4.4f, Vector3.one, Quaternion.Euler(0, 180, 0), Vector2.one, "wood_roof_67/New/default");
            if (pairs.Count == 0) return;
            GameObject cameraObject = Child("VI capture camera"); capture = cameraObject.AddComponent<Camera>();
            capture.enabled = false; capture.cullingMask = 1 << Layer; capture.clearFlags = CameraClearFlags.SolidColor;
            capture.backgroundColor = new Color(.08f, .10f, .14f, 1); capture.orthographic = true;
            capture.orthographicSize = 6.6f;
            capture.aspect = (float)Width / Height; capture.nearClipPlane = .1f; capture.farClipPlane = 50;
            capture.allowHDR = false; capture.allowMSAA = false; capture.useOcclusionCulling = false;
            capture.transform.localPosition = new Vector3(0, 0, -20); capture.transform.localRotation = Quaternion.identity;
            Light light = Child("VI capture light").AddComponent<Light>(); light.type = LightType.Directional;
            light.cullingMask = 1 << Layer; light.color = Color.white; light.intensity = 1.3f; light.shadows = LightShadows.None;
            light.transform.localRotation = Quaternion.Euler(35, -30, 0);
            WriteReport();
        }
        private static bool TextureMatches(Texture texture, string name, int size)
        { return texture is Texture2D && texture.name == name && texture.width == size && texture.height == size; }
        private static string DiagnosticName(string value)
        { return value == null || value.Length <= 256 ? value : value.Substring(0, 256) + "..."; }
        private static MaterialSlotRecord DescribeRockSlot(Material material, int slot, string originalName = "rock_256", int originalSize = 512, string ownedName = "granite_hd_albedo")
        {
            var result = new MaterialSlotRecord { slot = slot };
            if (material == null) return result;
            result.material = DiagnosticName(material.name); result.materialId = material.GetInstanceID();
            result.shader = material.shader == null ? null : DiagnosticName(material.shader.name);
            result.hasMainTexture = material.HasProperty("_MainTex");
            if (!result.hasMainTexture) return result;
            Vector2 scale = material.GetTextureScale("_MainTex"), offset = material.GetTextureOffset("_MainTex");
            result.scale = new[] { scale.x, scale.y }; result.offset = new[] { offset.x, offset.y };
            Texture texture = material.GetTexture("_MainTex");
            if (texture == null) return result;
            result.texture = DiagnosticName(texture.name); result.textureId = texture.GetInstanceID();
            result.textureWidth = texture.width; result.textureHeight = texture.height;
            result.originalTextureMatch = TextureMatches(texture, originalName, originalSize);
            result.ownedTextureMatch = TextureMatches(texture, ownedName, 1024);
            return result;
        }
        private void InspectRockRenderers(MeshRenderer[] renderers)
        {
            RequireMenu();
            const int MaxScanned = 65536, MaxRecords = 128, MaxSlots = 8, MaxParents = 12;
            // The installed Unity 6000.0.75f1 Renderer exposes a private scalar
            // GetMaterialCount used by GetSharedMaterials. Inspect this count first:
            // the public list getter itself otherwise expands to the native size.
            MethodInfo countMethod = typeof(Renderer).GetMethod("GetMaterialCount", BindingFlags.Instance | BindingFlags.NonPublic,
                null, Type.EmptyTypes, null);
            var slotMaterials = new List<Material>(MaxSlots);
            report.rockDiagnosticScanTruncated = renderers.Length > MaxScanned;
            for (int index = 0; index < Math.Min(renderers.Length, MaxScanned); index++)
            {
                report.rockDiagnosticScannedRenderers++;
                MeshRenderer renderer = renderers[index];
                if (renderer == null) continue;
                Material first = renderer.sharedMaterial;
                MeshFilter filter = renderer.GetComponent<MeshFilter>(); Mesh mesh = filter == null ? null : filter.sharedMesh;
                bool namedMaterial = first != null && first.name.StartsWith("stone_huge", StringComparison.Ordinal);
                bool namedMesh = mesh != null && mesh.name.StartsWith("Rock_3_Untitled", StringComparison.Ordinal);
                if (!namedMaterial && !namedMesh) continue;
                report.rockDiagnosticRelevantRenderers++;
                if (report.rockRenderers.Count >= MaxRecords) { report.rockDiagnosticOmittedRecords++; continue; }
                var record = new RockRendererRecord { renderer = DiagnosticName(renderer.name), rendererType = renderer.GetType().Name,
                    instanceId = renderer.GetInstanceID(), enabled = renderer.enabled, activeInHierarchy = renderer.gameObject.activeInHierarchy,
                    scene = DiagnosticName(renderer.gameObject.scene.name), sceneValid = renderer.gameObject.scene.IsValid(),
                    mesh = mesh == null ? null : DiagnosticName(mesh.name), meshId = mesh == null ? 0 : mesh.GetInstanceID(),
                    vertices = mesh == null ? 0 : mesh.vertexCount, submeshes = mesh == null ? 0 : mesh.subMeshCount,
                    firstSlot = DescribeRockSlot(first, 0) };
                Transform ancestor = renderer.transform;
                for (int depth = 0; ancestor != null && depth < MaxParents; depth++, ancestor = ancestor.parent)
                    record.hierarchy = DiagnosticName(ancestor.name) + (record.hierarchy == null ? "" : "/" + record.hierarchy);
                record.hierarchyTruncated = ancestor != null;
                // Reasons mirror the existing AddPair renderer filter only. An
                // empty list still requires that method's unique source identity
                // and valid captured-original checks before creating a fixture.
                if (first == null) record.selectorRejections.Add("first material missing");
                else
                {
                    if (first.name != "stone_huge") record.selectorRejections.Add("first material name differs from stone_huge");
                    if (first.shader == null || first.shader.name != "Custom/StaticRock") record.selectorRejections.Add("first material shader differs from Custom/StaticRock");
                    if (!first.HasProperty("_MainTex")) record.selectorRejections.Add("first material has no _MainTex");
                    else
                    {
                        Vector2 scale = first.GetTextureScale("_MainTex");
                        if (Mathf.Abs(scale.x - 1) > .0001f || Mathf.Abs(scale.y - 1) > .0001f) record.selectorRejections.Add("_MainTex scale differs from (1,1)");
                        if (first.GetTextureOffset("_MainTex") != Vector2.zero) record.selectorRejections.Add("_MainTex offset differs from (0,0)");
                    }
                }
                if (mesh == null) record.selectorRejections.Add("MeshFilter shared mesh missing");
                else
                {
                    if (mesh.name != "default") record.selectorRejections.Add("mesh name differs from default");
                    if (mesh.vertexCount != 106) record.selectorRejections.Add("mesh vertex count differs from 106");
                    if (mesh.subMeshCount != 1) record.selectorRejections.Add("mesh submesh count differs from 1");
                }
                if (ExactHierarchy(renderer.transform) != "highstone_2/high") record.selectorRejections.Add("hierarchy differs from highstone_2/high");
                record.materialSlotsTruncated = true;
                try
                {
                    if (countMethod == null) record.slotReadLimitation = "Installed private Renderer.GetMaterialCount API unavailable; only first shared slot inspected";
                    else
                    {
                        record.materialSlotCount = (int)countMethod.Invoke(renderer, null);
                        if (record.materialSlotCount < 0 || record.materialSlotCount > MaxSlots)
                            record.slotReadLimitation = "Material slot count outside 0..8 diagnostic limit; no material list fetched";
                        else
                        {
                            slotMaterials.Clear(); renderer.GetSharedMaterials(slotMaterials);
                            if (slotMaterials.Count != record.materialSlotCount) throw new InvalidOperationException("Material slot count changed during diagnostic read");
                            foreach (Material material in slotMaterials) record.slots.Add(DescribeRockSlot(material, record.slots.Count));
                            record.materialSlotsTruncated = false;
                        }
                    }
                }
                catch (Exception error) { record.slotReadLimitation = DiagnosticName(error.GetType().Name + ": " + error.Message); }
                report.rockRenderers.Add(record);
            }
        }
        private static string ExactHierarchy(Transform transform)
        {
            string path = null;
            for (int depth = 0; transform != null && depth < 12; depth++, transform = transform.parent)
                path = transform.name + (path == null ? "" : "/" + path);
            return transform == null ? path : null;
        }
        private static Func<Renderer, int> ResolveMaterialCount()
        {
            try
            {
                MethodInfo method = typeof(Renderer).GetMethod("GetMaterialCount", BindingFlags.Instance | BindingFlags.NonPublic,
                    null, Type.EmptyTypes, null);
                return method == null || method.ReturnType != typeof(int) ? null :
                    (Func<Renderer, int>)Delegate.CreateDelegate(typeof(Func<Renderer, int>), method);
            }
            catch { return null; }
        }
        private void AddPair(Material[] materials, Mesh[] meshes, Texture2D[] textures, MeshRenderer[] renderers, string materialName, string shaderName,
            string originalName, int originalSize, string ownedName, string meshName, int vertices, int expectedSubmeshes, int selectedSlot,
            float row, Vector3 shape, Quaternion rotation, Vector2 expectedScale, string expectedHierarchy = null)
        {
            RequireMenu();
            var record = new PairRecord { material = materialName, mesh = meshName, expectedOwned = ownedName,
                expectedSelectedSlot = selectedSlot, expectedSubmeshes = expectedSubmeshes, rowCenterY = row,
                fixtureRotationEuler = new[] { rotation.eulerAngles.x, rotation.eulerAngles.y, rotation.eulerAngles.z } };
            report.pairs.Add(record);
            Material source = null; Material[] sourceSlots = null; Mesh mesh = null; Texture2D original = null;
            foreach (Material candidate in materials)
                if (candidate != null && candidate.name == materialName && candidate.shader != null && candidate.shader.name == shaderName && candidate.HasProperty("_MainTex"))
                    record.materialCandidates++;
            foreach (Mesh candidate in meshes)
                if (candidate != null && candidate.name == meshName && candidate.vertexCount == vertices && candidate.subMeshCount == expectedSubmeshes)
                    record.meshCandidates++;
            foreach (Texture2D candidate in textures)
                if (TextureMatches(candidate, originalName, originalSize)) { record.originalTextureCandidates++; original = candidate; }
            // Resolve an actual loaded renderer with the exact selected slot.
            // Complete ordered material identity matters: a different companion
            // material could hide or alter the selected submesh in the capture.
            string sourceIdentity = null;
            record.rendererScanTruncated = renderers.Length > MaxSourceRenderers;
            for (int index = 0; index < Math.Min(renderers.Length, MaxSourceRenderers); index++)
            {
                record.scannedRenderers++;
                MeshRenderer renderer = renderers[index];
                if (renderer == null || (expectedHierarchy != null && ExactHierarchy(renderer.transform) != expectedHierarchy)) continue;
                MeshFilter filter = renderer.GetComponent<MeshFilter>(); Mesh candidateMesh = filter == null ? null : filter.sharedMesh;
                if (candidateMesh == null || candidateMesh.name != meshName || candidateMesh.vertexCount != vertices || candidateMesh.subMeshCount != expectedSubmeshes) continue;
                record.meshLayoutCandidates++;
                string readLimitation;
                Func<int> count = ReadMaterialCount == null ? null : (Func<int>)(() => ReadMaterialCount(renderer));
                if (!MenuValidationPairPolicy.TryReadSlots(count, renderer.GetSharedMaterials, sourceSlotBuffer, out readLimitation))
                {
                    record.slotReadRejected++;
                    if (record.slotReadLimitation == null) record.slotReadLimitation = readLimitation;
                    continue;
                }
                if (!MenuValidationPairPolicy.ValidLayout(sourceSlotBuffer.Count, expectedSubmeshes, selectedSlot))
                { record.slotLayoutRejected++; continue; }
                bool missingSlot = false;
                foreach (Material slot in sourceSlotBuffer) missingSlot |= slot == null || slot.shader == null;
                if (missingSlot) { record.slotLayoutRejected++; continue; }
                Material candidate = sourceSlotBuffer[selectedSlot];
                if (candidate.name != materialName || candidate.shader == null || candidate.shader.name != shaderName || !candidate.HasProperty("_MainTex")) continue;
                Vector2 scale = candidate.GetTextureScale("_MainTex");
                if (Mathf.Abs(scale.x - expectedScale.x) > .0001f || Mathf.Abs(scale.y - expectedScale.y) > .0001f || candidate.GetTextureOffset("_MainTex") != Vector2.zero) continue;
                Texture selectedTexture = candidate.GetTexture("_MainTex");
                if (!TextureMatches(selectedTexture, originalName, originalSize) && !TextureMatches(selectedTexture, ownedName, 1024)) continue;
                record.rendererCandidates++;
                var identities = new int[sourceSlotBuffer.Count];
                for (int slot = 0; slot < identities.Length; slot++) identities[slot] = sourceSlotBuffer[slot].GetInstanceID();
                string identity = MenuValidationPairPolicy.SourceIdentity(candidateMesh.GetInstanceID(), identities, selectedSlot);
                if (sourceIdentity == null)
                {
                    sourceIdentity = identity; record.distinctSourcePairs = 1;
                    source = candidate; sourceSlots = sourceSlotBuffer.ToArray(); mesh = candidateMesh;
                    record.sourceRenderer = DiagnosticName(renderer.name); record.sourceHierarchy = DiagnosticName(ExactHierarchy(renderer.transform));
                }
                else if (identity != sourceIdentity)
                { record.distinctSourcePairs = 2; record.distinctSourcePairsIsLowerBound = true; }
            }
            sourceSlotBuffer.Clear();
            // Prefer a proven current original slot if it is still vanilla. If the
            // production binder already changed it, only a unique loaded original
            // texture identity is acceptable for the baseline clone.
            Texture currentSlot = source == null ? null : source.GetTexture("_MainTex");
            if (TextureMatches(currentSlot, originalName, originalSize)) original = (Texture2D)currentSlot;
            else if (!TextureMatches(currentSlot, ownedName, 1024) || record.originalTextureCandidates != 1) original = null;
            if (record.rendererScanTruncated || record.distinctSourcePairs != 1 || original == null)
            { record.limitation = "Required exact loaded renderer resources are missing, ambiguous, or the bounded renderer scan was truncated; no resource loading or guessed candidate selection performed"; return; }
            record.selectedSlot = selectedSlot; record.materialSlotCount = sourceSlots.Length;
            record.meshVertices = mesh.vertexCount; record.meshSubmeshes = mesh.subMeshCount;
            record.meshBoundsSize = new[] { mesh.bounds.size.x, mesh.bounds.size.y, mesh.bounds.size.z };
            record.submeshIndexCounts = new long[mesh.subMeshCount];
            for (int slot = 0; slot < mesh.subMeshCount; slot++) record.submeshIndexCounts[slot] = mesh.GetIndexCount(slot);
            for (int slot = 0; slot < sourceSlots.Length; slot++)
                record.sourceSlots.Add(DescribeRockSlot(sourceSlots[slot], slot, originalName, originalSize, ownedName));
            var pair = new Pair { Record = record, Original = original, Mesh = mesh };
            // Every borrowed submesh remains present. Companion slots share a new
            // reference-named clone across both sides; only the selected right
            // clone retains the exact production binding name.
            MenuValidationPairPolicy.CreateFixtureSlots(sourceSlots, selectedSlot, (candidate, slot, authoredSelected) =>
            {
                var clone = new Material(candidate) { name = authoredSelected ? materialName : "VI_reference_" + materialName + "_slot" + slot,
                    hideFlags = HideFlags.DontSave };
                ownedMaterials.Add(clone);
                if (slot == selectedSlot) clone.SetTexture("_MainTex", original);
                return clone;
            }, out pair.ReferenceSlots, out pair.AuthoredSlots);
            pair.Reference = pair.ReferenceSlots[selectedSlot]; pair.Authored = pair.AuthoredSlots[selectedSlot];
            for (int slot = 0; slot < pair.ReferenceSlots.Length; slot++)
            {
                if (slot == selectedSlot) continue;
                Material companion = pair.ReferenceSlots[slot];
                var state = new CompanionSlot { Material = companion, Shader = companion.shader };
                int properties = state.Shader.GetPropertyCount();
                if (properties > 128) throw new InvalidOperationException("Companion shader exceeds bounded fixture property inspection");
                for (int property = 0; property < properties; property++)
                {
                    if (state.Shader.GetPropertyType(property) != UnityEngine.Rendering.ShaderPropertyType.Texture) continue;
                    string name = state.Shader.GetPropertyName(property);
                    state.Textures.Add(new TextureSlot { Name = name, Texture = companion.GetTexture(name),
                        Scale = companion.GetTextureScale(name), Offset = companion.GetTextureOffset(name) });
                }
                pair.Companions.Add(state);
                record.companionMaterialCount++; record.companionTextureCount += state.Textures.Count;
            }
            pair.Left = CreateMesh(mesh, pair.ReferenceSlots, new Vector3(-3.3f, row, 0), shape, rotation);
            pair.Right = CreateMesh(mesh, pair.AuthoredSlots, new Vector3(3.3f, row, 0), shape, rotation);
            pairs.Add(pair);
        }
        private GameObject Child(string name)
        {
            RequireMenu(); var value = new GameObject(name) { layer = Layer, hideFlags = HideFlags.DontSave };
            value.transform.SetParent(fixture.transform, false); return value;
        }
        private MeshRenderer CreateMesh(Mesh mesh, Material[] materials, Vector3 center, Vector3 shape, Quaternion rotation)
        {
            RequireMenu(); GameObject go = Child("VI fixture " + materials[0].name);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            MeshRenderer renderer = go.AddComponent<MeshRenderer>(); renderer.sharedMaterials = materials;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off; renderer.receiveShadows = false;
            Vector3 dimensions = Vector3.Scale(mesh.bounds.size, shape);
            float factor = 3 / Mathf.Max(dimensions.x, Mathf.Max(dimensions.y, dimensions.z));
            if (float.IsNaN(factor) || float.IsInfinity(factor) || factor <= 0) throw new InvalidOperationException("Invalid borrowed mesh bounds");
            go.transform.localScale = shape * factor; go.transform.localRotation = rotation;
            go.transform.localPosition = center - rotation * Vector3.Scale(mesh.bounds.center, shape * factor);
            return renderer;
        }
        private bool ObserveApplied()
        {
            bool all = pairs.Count > 0;
            foreach (Pair pair in pairs)
            {
                Texture current = pair.Authored == null ? null : pair.Authored.GetTexture("_MainTex");
                pair.Record.applied = current != null && !ReferenceEquals(current, pair.Original) && TextureMatches(current, pair.Record.expectedOwned, 1024);
                pair.Record.referencePreserved = pair.Reference != null && ReferenceEquals(pair.Reference.GetTexture("_MainTex"), pair.Original);
                pair.Record.actualTexture = current == null ? null : current.name;
                pair.Record.actualWidth = current == null ? 0 : current.width; pair.Record.actualHeight = current == null ? 0 : current.height;
                pair.Record.slotAssignmentsPreserved = SlotsAssigned(pair.Left, pair.ReferenceSlots) && SlotsAssigned(pair.Right, pair.AuthoredSlots);
                pair.Record.allSubmeshesPreserved = pair.Left != null && pair.Right != null && pair.Mesh != null &&
                    pair.Left.GetComponent<MeshFilter>().sharedMesh == pair.Mesh && pair.Right.GetComponent<MeshFilter>().sharedMesh == pair.Mesh &&
                    pair.Mesh.subMeshCount == pair.Record.expectedSubmeshes;
                pair.Record.companionSlotsPreserved = true;
                foreach (CompanionSlot companion in pair.Companions)
                {
                    bool same = companion.Material != null && companion.Material.shader == companion.Shader;
                    if (same)
                        foreach (TextureSlot texture in companion.Textures)
                            same &= ReferenceEquals(companion.Material.GetTexture(texture.Name), texture.Texture) &&
                                companion.Material.GetTextureScale(texture.Name) == texture.Scale && companion.Material.GetTextureOffset(texture.Name) == texture.Offset;
                    pair.Record.companionSlotsPreserved &= same;
                }
                all &= pair.Record.applied && pair.Record.referencePreserved && pair.Record.slotAssignmentsPreserved &&
                    pair.Record.companionSlotsPreserved && pair.Record.allSubmeshesPreserved;
            }
            return all;
        }
        private bool SlotsAssigned(Renderer renderer, Material[] expected)
        {
            if (renderer == null) return false;
            string limitation;
            Func<int> count = ReadMaterialCount == null ? null : (Func<int>)(() => ReadMaterialCount(renderer));
            bool same = MenuValidationPairPolicy.TryReadSlots(count, renderer.GetSharedMaterials, sourceSlotBuffer, out limitation) && sourceSlotBuffer.Count == expected.Length;
            if (same)
                for (int slot = 0; slot < expected.Length; slot++) same &= ReferenceEquals(sourceSlotBuffer[slot], expected[slot]);
            sourceSlotBuffer.Clear(); return same;
        }
        private void CaptureComparison()
        {
            RequireMenu(); if (!ObserveApplied()) throw new InvalidOperationException("Owned texture identity changed before capture");
            Texture2D readback = null; RenderTexture previous = RenderTexture.active;
            try
            {
                target = new RenderTexture(Width, Height, 24, RenderTextureFormat.ARGB32) { name = "VI owned capture target", hideFlags = HideFlags.DontSave };
                target.Create(); capture.targetTexture = target;
                readback = new Texture2D(Width, Height, TextureFormat.RGBA32, false) { name = "VI owned CPU capture", hideFlags = HideFlags.DontSave };
                RequireMenu(); capture.Render(); RequireMenu(); RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, Width, Height), 0, 0); readback.Apply(false, false);
                Color32[] authored = readback.GetPixels32();
                string screenshot = Path.Combine(report.output, "comparison-4k.png");
                using (var stream = new FileStream(screenshot, FileMode.CreateNew, FileAccess.Write))
                { byte[] png = readback.EncodeToPNG(); stream.Write(png, 0, png.Length); stream.Flush(); }
                report.screenshot = screenshot;
                // Same geometry/camera/position baseline proves the assigned owned
                // texture affects visible pixels, not just a CPU material pointer.
                // Only our renderer slots are changed, within this synchronous call.
                foreach (Pair pair in pairs) pair.Right.sharedMaterials = pair.ReferenceSlots;
                RequireMenu(); capture.Render(); RequireMenu(); RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, Width, Height), 0, 0); readback.Apply(false, false);
                Color32[] baseline = readback.GetPixels32();
                foreach (Pair pair in pairs)
                {
                    Vector3 point = capture.WorldToViewportPoint(pair.Right.bounds.center);
                    int centerX = Mathf.RoundToInt(point.x * Width), centerY = Mathf.RoundToInt(point.y * Height);
                    int radius = Mathf.CeilToInt(Height * 1.7f / (2 * capture.orthographicSize));
                    for (int y = Math.Max(0, centerY - radius); y < Math.Min(Height, centerY + radius); y += 2)
                        for (int x = Math.Max(0, centerX - radius); x < Math.Min(Width, centerX + radius); x += 2)
                        {
                            int index = y * Width + x;
                            if (Difference(authored[index], authored[0]) > 12) pair.Record.visiblePixels++;
                            if (Difference(authored[index], baseline[index]) > 12) pair.Record.changedPixels++;
                        }
                }
                report.passed = pairs.Count == report.expectedPairs && report.expectedPluginsOnly;
                foreach (Pair pair in pairs) report.passed &= pair.Record.applied && pair.Record.referencePreserved && pair.Record.companionSlotsPreserved &&
                    pair.Record.slotAssignmentsPreserved && pair.Record.allSubmeshesPreserved && pair.Record.visiblePixels > 64 && pair.Record.changedPixels > 64;
                if (!report.passed) report.limitations.Add("Full three-pair visible replacement proof was not established; inspect per-pair counts and the local screenshot");
            }
            finally
            {
                RenderTexture.active = previous;
                if (MenuGuard())
                {
                    foreach (Pair pair in pairs) if (pair.Right != null) pair.Right.sharedMaterials = pair.AuthoredSlots;
                    if (capture != null) capture.targetTexture = null;
                    if (target != null) { target.Release(); Object.Destroy(target); target = null; }
                    if (readback != null) Object.Destroy(readback);
                }
            }
        }
        private static int Difference(Color32 a, Color32 b)
        { return Math.Abs(a.r - b.r) + Math.Abs(a.g - b.g) + Math.Abs(a.b - b.b); }
        private void Finish(bool passed)
        {
            RequireMenu(); report.passed = passed; report.phase = "cleanup";
            if (fixture != null) Object.Destroy(fixture);
            // These are only new Material(source) clones. Borrowed meshes, textures
            // and shaders are never destroyed or unloaded by the probe.
            foreach (Material material in ownedMaterials) if (material != null) Object.Destroy(material);
            report.cleanupRequested = true;
            stage = 3; cleanupAt = Time.realtimeSinceStartupAsDouble + 2; WriteReport();
        }
        private void Abort(string error)
        {
            aborted = true; armed = false;
            if (report != null) { report.aborted = true; report.passed = false; report.quitRequested = false; report.error = error; report.phase = "aborted-no-quit"; }
            Logger.LogError("Menu validation aborted; no game quit or scene cleanup will be attempted: " + error);
            // Writing our own diagnostic report is allowed after losing the scene
            // guard. No Unity scene mutation, save write, or quit is attempted.
            try { WriteReport(); } catch (Exception ex) { Logger.LogError(ex); }
        }
        private void WriteReport()
        {
            if (report == null) return;
            report.scene = SceneManager.GetActiveScene().name; report.elapsedSeconds = Time.realtimeSinceStartupAsDouble - started;
            report.demoMode = DemoMode.Enabled; report.dontSaveAnything = SaveSystem.HasSessionFlag(SaveSystemSessionFlags.DontSaveAnything);
            report.unityVersion = Application.unityVersion; report.graphicsApi = SystemInfo.graphicsDeviceType.ToString(); report.gpu = SystemInfo.graphicsDeviceName;
            report.reportedVramMiB = SystemInfo.graphicsMemorySize; report.colorSpace = QualitySettings.activeColorSpace.ToString();
            report.screenWidth = Screen.width; report.screenHeight = Screen.height;
            report.builtPairs = pairs.Count;
            report.unityAllocatedBytes = UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong(); report.unityReservedBytes = UnityEngine.Profiling.Profiler.GetTotalReservedMemoryLong();
            report.managedBytes = GC.GetTotalMemory(false); report.meanFrameMs = report.frameSamples == 0 ? 0 : frameSum / report.frameSamples;
            string path = Path.Combine(report.output, "report.json"), temporary = path + ".tmp";
            // The installed player's Unity serializer omits lists of these
            // plugin-defined record types. Use its existing Newtonsoft assembly
            // and plain DTO fields so missing-resource evidence is retained.
            string json = Newtonsoft.Json.JsonConvert.SerializeObject(report, Newtonsoft.Json.Formatting.Indented);
            var parsed = Newtonsoft.Json.Linq.JObject.Parse(json);
            if (((Newtonsoft.Json.Linq.JArray)parsed["materials"]).Count != report.materials.Count ||
                ((Newtonsoft.Json.Linq.JArray)parsed["meshes"]).Count != report.meshes.Count ||
                ((Newtonsoft.Json.Linq.JArray)parsed["pairs"]).Count != report.pairs.Count ||
                ((Newtonsoft.Json.Linq.JArray)parsed["rockRenderers"]).Count != report.rockRenderers.Count)
                throw new InvalidDataException("Diagnostic record lists were not serialized completely");
            for (int pair = 0; pair < report.pairs.Count; pair++)
                if (((Newtonsoft.Json.Linq.JArray)parsed["pairs"][pair]["sourceSlots"]).Count != report.pairs[pair].sourceSlots.Count)
                    throw new InvalidDataException("Source material slot records were not serialized completely");
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write))
            using (var writer = new StreamWriter(stream)) { writer.Write(json); writer.Flush(); stream.Flush(); }
            if (wroteReport) File.Replace(temporary, path, null); else File.Move(temporary, path);
            wroteReport = true;
        }
    }
#endif
}
