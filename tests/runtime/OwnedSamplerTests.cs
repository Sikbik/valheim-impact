using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using ValheimImpact.Core;

internal static class OwnedSamplerTests
{
    private sealed class Texture { internal OwnedTextureBundle Source; internal bool Released; }
    // The real registry, identity, scheduler and accounting surround this engine boundary.
    private sealed class Load : IOwnedTextureLoad<Texture>
    {
        internal Texture Value;
        public bool IsDone { get { return true; } }
        public bool IsReleased { get; private set; }
        public Exception Error { get { return null; } }
        public bool Pump(bool allow) { return false; }
        public Texture Take() { return Value; }
        public void Cancel() { IsReleased = true; }
        public void Dispose() { IsReleased = true; }
    }
    private static OwnedTextureRequest Read(string directory, string label, string wrapJson,
        string content, string selector = "assets/texture.asset")
    {
        string root = Path.Combine(directory, "sampler-" + label);
        Directory.CreateDirectory(Path.Combine(root, "assets"));
        byte[] bytes = Encoding.ASCII.GetBytes("UnityFS\0synthetic-sampler-" + content);
        File.WriteAllBytes(Path.Combine(root, "assets/fixture.bundle"), bytes);
        File.WriteAllText(Path.Combine(root, "profile.json"), "{\"schemaVersion\":1,\"profile\":\"Balanced\",\"experimental\":true,\"enableGameReplacement\":true,\"residentMiB\":768,\"inFlightMiB\":64,\"concurrentRequests\":2,\"startsPerFrame\":1}");
        File.WriteAllText(Path.Combine(root, "assets/catalog.json"), "{\"schemaVersion\":1,\"editorVersion\":\"6000.0.75f1\",\"target\":\"StandaloneLinux64\",\"nativeReadback\":true,\"textures\":[{\"id\":\"fixture\",\"path\":\"fixture.bundle\",\"assetName\":\"" + selector + "\",\"sha256\":\"" + Fingerprint.Hex(bytes) + "\",\"payloadSha256\":\"" + new string('a', 64) + "\",\"width\":4,\"height\":4,\"mipCount\":3,\"payloadBytes\":48,\"isSrgb\":true" + (wrapJson == null ? "" : ",\"wrapMode\":" + wrapJson) + "}]}");
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), "{\"schemaVersion\":1,\"bindings\":[{\"id\":\"fixture\",\"materialName\":\"fixture\",\"shaderName\":\"Standard\",\"textureProperty\":\"_MainTex\",\"originalTextureName\":\"original\",\"originalWidth\":4,\"originalHeight\":4,\"ownedTextureId\":\"fixture\"}]}");
        return OwnedMaterialRegistry.Load(root).Catalog["fixture"];
    }
    private static void Pair(Action<bool, string> check, string label,
        OwnedTextureRequest a, OwnedTextureRequest b, bool shared)
    {
        foreach (bool reverse in new[] { false, true })
        {
            int starts = 0;
            var scheduler = new OwnedTextureScheduler<Texture>(
                new Dictionary<string, OwnedTextureRequest> { { "a", a }, { "b", b } },
                source => { starts++; return new Load { Value = new Texture { Source = source } }; },
                value => value.Released = true, value => value.Released);
            var first = scheduler.Acquire(reverse ? "b" : "a");
            var second = scheduler.Acquire(reverse ? "a" : "b");
            for (int frame = 0; frame < 8; frame++) scheduler.Tick(frame, frame);
            Texture x, y;
            bool ready = first.TryGet(out x) & second.TryGet(out y);
            check(ready && ReferenceEquals(x, y) == shared && starts == (shared ? 1 : 2) &&
                (shared || (ReferenceEquals(x.Source, reverse ? b.Bundle : a.Bundle) &&
                            ReferenceEquals(y.Source, reverse ? a.Bundle : b.Bundle))),
                label + (reverse ? " reverse order" : " forward order"));
            check(scheduler.ResidentBytes == (shared ? 48 : 96), label + " accounts each distinct resource");
            first.Dispose(); second.Dispose(); scheduler.Stop();
            for (int frame = 8; frame < 16; frame++) scheduler.Tick(frame, frame);
            check(scheduler.IsDrained && scheduler.AllocatedBytes == 0, label + " releases every sampler resource");
        }
    }
    internal static void Run(Action<bool, string> check, string directory)
    {
        var repeat = Read(directory, "repeat", "\"repeat\"", "repeat");
        var clamp = Read(directory, "clamp", "\"clamp\"", "clamp");
        Pair(check, "distinct declared wrapping preserves each demand", repeat, clamp, false);
        Pair(check, "equivalent declared samplers share across bundles", repeat,
            Read(directory, "repeat-alias", "\"repeat\"", "another-bundle", "assets/alias.asset"), true);
        Pair(check, "equivalent declared Clamp samplers share across bundles", clamp,
            Read(directory, "clamp-alias", "\"clamp\"", "another-clamp", "assets/alias.asset"), true);
        var unknown = Read(directory, "unknown", null, "unknown");
        Pair(check, "legacy unknown samplers isolate different bundle hashes", unknown,
            Read(directory, "unknown-other", null, "different-bundle"), false);
        Pair(check, "legacy unknown samplers isolate exact selector differences", unknown,
            Read(directory, "unknown-selector", null, "unknown", "assets/Texture.asset"), false);
        Pair(check, "legacy unknown samplers share identical bundle and selector", unknown,
            Read(directory, "unknown-copy", null, "unknown"), true);
        Pair(check, "legacy unknown does not assume declared Repeat", repeat,
            Read(directory, "unknown-repeat", null, "repeat"), false);
        int index = 0;
        foreach (string value in new[] { "null", "true", "false", "0", "1", "1.0", "{}", "[]", "\"\"", "\"Repeat\"", "\"mirror\"", "\"clamp \"" })
        {
            bool rejected = false;
            try { Read(directory, "invalid-" + (++index), value, "invalid"); }
            catch (Exception) { rejected = true; }
            check(rejected, "catalog rejects invalid explicit sampler token " + value);
        }
    }
}
