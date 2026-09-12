using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;
using UnityEngine.SceneManagement;
using ValheimImpact.Core;
using Object = UnityEngine.Object;

namespace ValheimImpact.Unity
{
    // Main-thread adapter. Shared materials are changed only through exact allowlist
    // texture slots. Unity's material/instance names are never normalized.
    public sealed class OwnedMaterialBinder
    {
        private sealed class Entry
        {
            internal int Key;
            internal Material Material;
            internal Shader Shader;
            internal Texture Original;
            internal Vector2 Scale, Offset;
            internal MaterialBindingRule Rule;
            internal OwnedMaterialLease<Texture> Binding;
            internal Func<Texture> Read;
            internal Action<Texture> Write;
            internal Func<bool> CanRestore, CanApply;
            internal int LastSeenPass;
            internal bool Foreign;
        }
        private sealed class Node { internal Transform Transform; internal int Child; internal bool Inspected; }
        private readonly OwnedMaterialRegistry registry;
        private readonly List<Entry> entries = new List<Entry>();
        private readonly Dictionary<int, Entry> byMaterial = new Dictionary<int, Entry>();
        private readonly List<GameObject> roots = new List<GameObject>();
        private readonly Stack<Node> traversal = new Stack<Node>();
        private readonly Action<string> log;
        private readonly HashSet<string> misses = new HashSet<string>(StringComparer.Ordinal);
        private static readonly Func<Renderer, int> DefaultMaterialCount = ResolveMaterialCount();
        private static readonly int ModeId = Shader.PropertyToID("_Mode"), CutoffId = Shader.PropertyToID("_Cutoff"),
            CullId = Shader.PropertyToID("_Cull"), ZWriteId = Shader.PropertyToID("_ZWrite"),
            SrcBlendId = Shader.PropertyToID("_SrcBlend"), DstBlendId = Shader.PropertyToID("_DstBlend");
        private Func<Renderer, int> materialCount = DefaultMaterialCount;
        private readonly List<Material> sharedMaterials = new List<Material>(MaxSharedMaterials);
        private int sceneIndex, rootIndex, pass = 1, completedPass, entryCursor, visited;
        private double nextCensus;
        private bool scanning = true, incomplete, stopping, warnedSlotFallback;
        private const int WorkPerFrame = 64, MaxMaterials = 1024, MaxRoots = 8192, MaxNodes = 262144, MaxDepth = 256, MaxSharedMaterials = 8;
        public readonly OwnedTextureScheduler<Texture> Scheduler;
        public long DiscoveredCount { get; private set; }
        public long MatchedCount { get; private set; }
        public long AppliedCount { get; private set; }
        public long RestoredCount { get; private set; }
        public long ForeignChangeCount { get; private set; }
        public long SkippedCensusCount { get; private set; }
        public int TrackedMaterials { get { return entries.Count; } }
        public bool IsStopping { get { return stopping; } }
        public bool IsDrained { get { return stopping && Scheduler.LeaseCount == 0 && Scheduler.IsDrained; } }

        // Provider injection keeps the finite Editor fixture on this exact adapter.
        // Production always uses OwnedBundleLoad and deferred Object.Destroy.
        public OwnedMaterialBinder(OwnedMaterialRegistry registry, Action<string> log = null,
            Func<OwnedTextureBundle, IOwnedTextureLoad<Texture>> begin = null, Action<Texture> retire = null,
            Func<Texture, bool> released = null)
        {
            if (registry == null || !registry.Enabled) throw new ArgumentException("Validated enabled material registry required");
            this.registry = registry; this.log = log ?? (_ => {});
            Scheduler = new OwnedTextureScheduler<Texture>(registry.Catalog,
                begin ?? (spec => new TextureLoad(spec)), retire ?? (texture => Object.Destroy(texture)),
                released ?? (texture => texture == null), registry.Policy);
        }
        private sealed class TextureLoad : IOwnedTextureLoad<Texture>
        {
            private readonly OwnedBundleLoad inner;
            internal TextureLoad(OwnedTextureBundle spec) { inner = new OwnedBundleLoad(spec); }
            public bool IsDone { get { return inner.IsDone; } }
            public bool IsReleased { get { return inner.IsReleased; } }
            public Exception Error { get { return inner.Error; } }
            public bool Pump(bool allow) { return inner.Pump(allow); }
            public Texture Take() { return inner.Take(); }
            public void Cancel() { inner.Cancel(); }
            public void Dispose() { inner.Dispose(); }
        }
        public void Tick(long frame, double seconds, bool discoverScenes = true)
        {
            if (!stopping && discoverScenes) Discover(seconds);
            int work = Math.Min(WorkPerFrame, entries.Count);
            for (int i = 0; i < work && entries.Count > 0; i++)
            {
                if (entryCursor >= entries.Count) entryCursor = 0;
                Entry entry = entries[entryCursor++];
                Maintain(entry);
                bool released = entry.Binding == null || entry.Binding.IsReleased;
                if (released && (entry.Material == null || (!entry.Foreign && entry.LastSeenPass < completedPass)))
                {
                    // Original materials may survive their last renderer. Reclaim
                    // completed, unseen records instead of exhausting tracking capacity.
                    // Foreign suppression remains bounded in this same registry.
                    byMaterial.Remove(entry.Key); entries.RemoveAt(--entryCursor);
                }
            }
            Scheduler.Tick(frame, seconds);
        }
        public void Stop()
        {
            if (stopping) return;
            stopping = true; traversal.Clear(); roots.Clear(); Scheduler.Stop();
        }
        public void RestoreForProcessExit()
        {
            Stop();
            foreach (Entry entry in entries) Maintain(entry);
        }
        // Also used by finite fixture scenes. This does not start any engine load.
        public void ObserveRenderer(Renderer renderer)
        { ObserveRendererMaterials(renderer); }
        private static Func<Renderer, int> ResolveMaterialCount()
        {
            try
            {
                // Unity's public list getter expands to its native material count.
                // Resolve the scalar preflight once, without per-renderer reflection
                // invocation or boxing. Future incompatible engines keep slot zero.
                MethodInfo method = typeof(Renderer).GetMethod("GetMaterialCount", BindingFlags.Instance | BindingFlags.NonPublic,
                    null, Type.EmptyTypes, null);
                if (method == null || method.ReturnType != typeof(int)) return null;
                return (Func<Renderer, int>)Delegate.CreateDelegate(typeof(Func<Renderer, int>), method);
            }
            catch (Exception) { return null; }
        }
        private void WarnSlotFallback(string reason)
        {
            if (warnedSlotFallback) return;
            warnedSlotFallback = true;
            log("Bounded material-slot discovery kept first-slot coverage: " + reason + "; later slots are skipped for affected renderers.");
        }
        private int ObserveRendererMaterials(Renderer renderer)
        {
            if (stopping || renderer == null || !renderer.enabled || !renderer.gameObject.activeInHierarchy) return 0;
            int count = -1;
            if (materialCount == null) WarnSlotFallback("material-count API unavailable");
            else
            {
                try { count = materialCount(renderer); }
                catch (Exception)
                {
                    materialCount = null;
                    WarnSlotFallback("material-count API failed and was disabled");
                }
            }
            if (count == 0) return 0;
            if (count > 0 && count <= MaxSharedMaterials)
            {
                bool read = false;
                try
                {
                    renderer.GetSharedMaterials(sharedMaterials);
                    read = sharedMaterials.Count == count;
                    if (!read) { materialCount = null; WarnSlotFallback("material count changed during shared-list read"); }
                }
                catch (Exception)
                {
                    materialCount = null;
                    WarnSlotFallback("shared-material read failed and was disabled");
                }
                if (read)
                {
                    try { for (int i = 0; i < sharedMaterials.Count; i++) ObserveMaterial(sharedMaterials[i]); }
                    finally { sharedMaterials.Clear(); }
                    return count;
                }
                sharedMaterials.Clear();
            }
            else if (materialCount != null) WarnSlotFallback("material count outside supported 1..8 range");
            ObserveMaterial(renderer.sharedMaterial);
            return 1;
        }
        private void ObserveMaterial(Material material)
        {
            if (material == null) return;
            int key = material.GetInstanceID();
            Entry existing;
            if (byMaterial.TryGetValue(key, out existing))
            {
                existing.LastSeenPass = pass;
                if (!existing.Foreign && (existing.Binding == null || existing.Binding.IsReleased) && Matches(existing))
                    Acquire(existing);
                return;
            }
            DiscoveredCount++;
            if (entries.Count >= MaxMaterials || material.shader == null) return;
            foreach (MaterialBindingRule rule in registry.Rules)
            {
                if (!material.HasProperty(rule.textureProperty)) continue;
                Texture original = material.GetTexture(rule.textureProperty);
                if (original == null) continue;
                if (!rule.Matches(material.name, material.shader.name, rule.textureProperty, original.name, original.width, original.height))
                {
                    if (misses.Count < 16 && original.name == rule.originalTextureName && material.shader.name == rule.shaderName)
                    {
                        string candidate = material.name + "; shader=" + material.shader.name + "; texture=" + original.name;
                        if (misses.Add(candidate)) log("Exact material candidate miss: " + candidate);
                    }
                    continue;
                }
                if (!Eligible(material, rule)) continue;
                var entry = new Entry { Key = key, Material = material, Shader = material.shader, Original = original, Rule = rule,
                    Scale = material.GetTextureScale(rule.textureProperty), Offset = material.GetTextureOffset(rule.textureProperty), LastSeenPass = pass };
                // Cache these once per tracked entry. The steady update path must
                // not allocate closures for every material on every frame.
                entry.Read = () => entry.Material == null ? null : entry.Material.GetTexture(entry.Rule.textureProperty);
                entry.Write = texture => entry.Material.SetTexture(entry.Rule.textureProperty, texture);
                entry.CanRestore = () => entry.Original != null;
                entry.CanApply = () => Matches(entry);
                byMaterial.Add(key, entry); entries.Add(entry); MatchedCount++; Acquire(entry); return;
            }
        }
        private void Acquire(Entry entry)
        {
            var lease = Scheduler.Acquire(entry.Rule.ownedTextureId);
            if (lease != null) entry.Binding = new OwnedMaterialLease<Texture>(entry.Original, lease);
        }
        private static bool EligibleOpaque(Material material)
        {
            return material != null && material.shader != null && material.renderQueue <= 2500 &&
                !material.IsKeywordEnabled("_ALPHATEST_ON") && !material.IsKeywordEnabled("_ALPHABLEND_ON") &&
                !material.IsKeywordEnabled("_ALPHAPREMULTIPLY_ON") &&
                (!material.HasFloat(ModeId) || material.GetFloat(ModeId) == 0) &&
                (!material.HasFloat(ZWriteId) || material.GetFloat(ZWriteId) == 1) &&
                (!material.HasFloat(SrcBlendId) || material.GetFloat(SrcBlendId) == 1) &&
                (!material.HasFloat(DstBlendId) || material.GetFloat(DstBlendId) == 0);
        }
        private static bool Eligible(Material material, MaterialBindingRule rule)
        {
            if (rule.cutout == null) return EligibleOpaque(material);
            // These can be stored material values even when absent from ShaderLab
            // Properties. HasFloat must prove their presence before a read. Never
            // guess a missing mode or blend/depth value from GetFloat's default.
            return material != null && material.shader != null && material.HasFloat(ModeId) && material.HasFloat(CutoffId) &&
                material.HasFloat(CullId) && material.HasFloat(ZWriteId) && material.HasFloat(SrcBlendId) && material.HasFloat(DstBlendId) &&
                rule.cutout.Matches(material.GetFloat(ModeId), material.GetFloat(CutoffId), material.GetFloat(CullId), material.GetFloat(ZWriteId),
                    material.GetFloat(SrcBlendId), material.GetFloat(DstBlendId), material.renderQueue,
                    material.IsKeywordEnabled("_ALPHATEST_ON"), material.IsKeywordEnabled("_ALPHABLEND_ON"), material.IsKeywordEnabled("_ALPHAPREMULTIPLY_ON"));
        }
        private bool Matches(Entry entry)
        {
            Material m = entry.Material;
            return Eligible(m, entry.Rule) && entry.Original != null && m.shader == entry.Shader && m.HasProperty(entry.Rule.textureProperty) &&
                entry.Rule.Matches(m.name, m.shader.name, entry.Rule.textureProperty, entry.Original.name, entry.Original.width, entry.Original.height) &&
                ReferenceEquals(m.GetTexture(entry.Rule.textureProperty), entry.Original);
        }
        private void Maintain(Entry entry)
        {
            if (entry.Binding == null || entry.Binding.IsReleased) return;
            Material m = entry.Material;
            Func<Texture> read = entry.Read;
            Action<Texture> write = entry.Write;
            bool foreign = m != null && (!Eligible(m, entry.Rule) || !entry.Binding.StillOwns(read) || m.shader != entry.Shader ||
                m.name != entry.Rule.materialName || m.GetTextureScale(entry.Rule.textureProperty) != entry.Scale ||
                m.GetTextureOffset(entry.Rule.textureProperty) != entry.Offset);
            if (foreign && !entry.Foreign) { entry.Foreign = true; ForeignChangeCount++; }
            bool release = stopping || m == null || entry.Foreign || entry.LastSeenPass < completedPass;
            if (release)
            {
                bool wasApplied = entry.Binding.IsApplied;
                bool ownedSlot = entry.Binding.StillOwns(read);
                if (entry.Binding.RestoreAndRelease(read, write, entry.CanRestore))
                    if (wasApplied && ownedSlot) RestoredCount++;
            }
            else if (entry.Binding.ApplyReady(read, write, entry.CanApply)) AppliedCount++;
        }
        private void Discover(double seconds)
        {
            if (!scanning)
            {
                if (seconds < nextCensus) return;
                scanning = true; sceneIndex = 0; rootIndex = 0; roots.Clear(); traversal.Clear(); visited = 0; incomplete = false;
            }
            for (int work = 0; work < WorkPerFrame; work++)
            {
                if (++visited > MaxNodes)
                { incomplete = true; CompleteObservationPass(seconds); return; }
                if (traversal.Count > 0)
                {
                    Node node = traversal.Peek();
                    if (node.Transform == null || !node.Transform.gameObject.activeInHierarchy) { traversal.Pop(); continue; }
                    if (!node.Inspected)
                    {
                        // Reserve the maximum slot batch before touching this node.
                        // Every inspected slot consumes the same 64-step discovery
                        // budget instead of multiplying material work by eight.
                        if (WorkPerFrame - work < MaxSharedMaterials) return;
                        node.Inspected = true;
                        Renderer renderer;
                        if (node.Transform.TryGetComponent<Renderer>(out renderer))
                            work += Math.Max(1, ObserveRendererMaterials(renderer)) - 1;
                    }
                    else if (node.Child < node.Transform.childCount)
                    {
                        Transform child = node.Transform.GetChild(node.Child++);
                        if (traversal.Count < MaxDepth) traversal.Push(new Node { Transform = child });
                        else incomplete = true;
                    }
                    else traversal.Pop();
                    continue;
                }
                if (rootIndex < roots.Count)
                {
                    GameObject root = roots[rootIndex++];
                    if (root != null) traversal.Push(new Node { Transform = root.transform });
                    continue;
                }
                roots.Clear(); rootIndex = 0;
                if (sceneIndex >= SceneManager.sceneCount) { CompleteObservationPass(seconds); return; }
                Scene scene = SceneManager.GetSceneAt(sceneIndex++);
                if (!scene.IsValid() || !scene.isLoaded) continue;
                if (scene.rootCount > MaxRoots) { incomplete = true; continue; }
                scene.GetRootGameObjects(roots);
            }
        }
        // Explicit ObserveRenderer clients call this after visiting their complete
        // active set. Production scene discovery calls the same method. An incomplete
        // native walk never authorizes unseen-record reclamation.
        public void CompleteObservationPass(double seconds)
        {
            if (!incomplete) completedPass = pass;
            else { SkippedCensusCount++; if (SkippedCensusCount <= 3) log("Material census exceeded bounded hierarchy limits; retaining existing demand until a complete census or scene reset."); }
            pass++; scanning = false; nextCensus = seconds + 2; roots.Clear(); traversal.Clear();
        }
    }
}
