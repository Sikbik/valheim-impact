using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;

namespace ValheimImpact.Core
{
    // Files and hashes only. Load on a worker once; never from a demand callback.
    public sealed class OwnedMaterialRegistry
    {
        // DataContractJsonSerializer populates these fields.
#pragma warning disable 0649
        [DataContract] private sealed class Profile
        {
            [DataMember(IsRequired = true)] public int schemaVersion;
            [DataMember(IsRequired = true)] public string profile;
            [DataMember(IsRequired = true)] public bool experimental;
            [DataMember] public bool enableGameReplacement;
            [DataMember(IsRequired = true)] public int residentMiB;
            [DataMember(IsRequired = true)] public int inFlightMiB;
            [DataMember(IsRequired = true)] public int concurrentRequests;
            [DataMember(IsRequired = true)] public int startsPerFrame;
        }
        [DataContract] private sealed class Descriptor
        {
            [DataMember(IsRequired = true)] public string id;
            [DataMember(IsRequired = true)] public string path;
            [DataMember(IsRequired = true)] public string assetName;
            [DataMember(IsRequired = true)] public string sha256;
            [DataMember(IsRequired = true)] public string payloadSha256;
            [DataMember(IsRequired = true)] public int width;
            [DataMember(IsRequired = true)] public int height;
            [DataMember(IsRequired = true)] public int mipCount;
            [DataMember(IsRequired = true)] public long payloadBytes;
            [DataMember(IsRequired = true)] public bool isSrgb;
        }
        [DataContract] private sealed class CatalogFile
        {
            [DataMember(IsRequired = true)] public int schemaVersion;
            [DataMember(IsRequired = true)] public string editorVersion;
            [DataMember(IsRequired = true)] public string target;
            [DataMember(IsRequired = true)] public bool nativeReadback;
            [DataMember(IsRequired = true)] public Descriptor[] textures;
        }
        [DataContract] private sealed class BindingsFile
        {
            [DataMember(IsRequired = true)] public int schemaVersion;
            [DataMember(IsRequired = true)] public MaterialBindingRule[] bindings;
        }
#pragma warning restore 0649
        public bool Enabled { get; private set; }
        public string ProfileName { get; private set; }
        public string EditorVersion { get; private set; }
        public string Target { get; private set; }
        public StreamingPolicy Policy { get; private set; }
        public readonly List<MaterialBindingRule> Rules = new List<MaterialBindingRule>();
        public readonly Dictionary<string, OwnedTextureRequest> Catalog = new Dictionary<string, OwnedTextureRequest>(StringComparer.Ordinal);
        public static OwnedMaterialRegistry Load(string root)
        {
            root = Path.GetFullPath(root);
            var result = new OwnedMaterialRegistry();
            string profilePath = SafeFile(root, "profile.json");
            if (!File.Exists(profilePath)) return result;
            var profile = Read<Profile>(profilePath);
            if (profile.schemaVersion != 1 || !profile.experimental ||
                (profile.profile != "Compact" && profile.profile != "Balanced" && profile.profile != "High"))
                throw new InvalidDataException("Unsupported installed profile");
            result.ProfileName = profile.profile;
            if (!profile.enableGameReplacement) return result;
            if (profile.residentMiB <= 0 || profile.residentMiB > 4096 || profile.inFlightMiB <= 0 ||
                profile.inFlightMiB > 256 || profile.inFlightMiB > profile.residentMiB || profile.concurrentRequests < 1 ||
                profile.concurrentRequests > 2 || profile.startsPerFrame != 1)
                throw new InvalidDataException("Installed profile exceeds supported component limits");
            result.Policy = new StreamingPolicy(profile.residentMiB * 1048576L, profile.inFlightMiB * 1048576L,
                profile.concurrentRequests, 60, 256, 1024);
            var catalog = Read<CatalogFile>(SafeFile(root, "assets/catalog.json"));
            var bindings = Read<BindingsFile>(SafeFile(root, "assets/bindings.json"));
            if (catalog.schemaVersion != 1 || !catalog.nativeReadback || catalog.editorVersion != "6000.0.75f1" ||
                (catalog.target != "StandaloneLinux64" && catalog.target != "StandaloneWindows64") ||
                catalog.textures == null || catalog.textures.Length == 0 || catalog.textures.Length > 256 ||
                (bindings.schemaVersion != 1 && bindings.schemaVersion != 2) || bindings.bindings == null || bindings.bindings.Length == 0 || bindings.bindings.Length > 32)
                throw new InvalidDataException("Unsupported owned catalog or binding allowlist");
            result.EditorVersion = catalog.editorVersion; result.Target = catalog.target;
            var all = new Dictionary<string, OwnedTextureRequest>(StringComparer.Ordinal);
            foreach (Descriptor d in catalog.textures)
            {
                if (d == null || string.IsNullOrWhiteSpace(d.id) || d.id.Length > 128 || all.ContainsKey(d.id) ||
                    (string.IsNullOrWhiteSpace(d.path) || !d.path.EndsWith(".bundle", StringComparison.Ordinal))) throw new InvalidDataException("Invalid owned catalog alias");
                var bundle = new OwnedTextureBundle(SafeFile(root, "assets/" + d.path), d.assetName, d.sha256, d.width, d.height, d.isSrgb);
                if (bundle.MipCount != d.mipCount || bundle.PayloadBytes != d.payloadBytes)
                    throw new InvalidDataException("Owned mip or payload descriptor mismatch");
                all.Add(d.id, new OwnedTextureRequest(bundle, d.payloadSha256));
            }
            var ids = new HashSet<string>(StringComparer.Ordinal);
            var slots = new HashSet<string>(StringComparer.Ordinal);
            foreach (MaterialBindingRule rule in bindings.bindings)
            {
                if (rule == null) throw new InvalidDataException("Null material rule");
                // Version 2 is required for the explicit cutout opt-in. Older
                // runtimes reject that version rather than ignoring new fields.
                if (rule.CutoutSpecified && (rule.cutout == null || bindings.schemaVersion != 2 || rule.shaderName != "Custom/Piece" || !rule.cutout.IsSupported))
                    throw new InvalidDataException("Unsupported cutout material expectation");
                foreach (string value in new[] { rule.id, rule.materialName, rule.shaderName, rule.textureProperty, rule.originalTextureName, rule.ownedTextureId })
                    if (string.IsNullOrWhiteSpace(value) || value.Length > 256 || value.IndexOf('\0') >= 0)
                        throw new InvalidDataException("Invalid exact material identity");
                OwnedTextureRequest request;
                if (!ids.Add(rule.id) || !slots.Add(rule.materialName + "\0" + rule.shaderName + "\0" + rule.textureProperty) ||
                    rule.textureProperty != "_MainTex" || rule.originalWidth <= 0 || rule.originalHeight <= 0 ||
                    rule.originalWidth > 16384 || rule.originalHeight > 16384 || !all.TryGetValue(rule.ownedTextureId, out request) ||
                    !request.Bundle.IsSrgb || request.Bundle.PayloadBytes > result.Policy.PendingBudgetBytes)
                    throw new InvalidDataException("Unsupported, duplicate or unknown material binding");
                if (!result.Catalog.ContainsKey(rule.ownedTextureId)) result.Catalog.Add(rule.ownedTextureId, request);
                result.Rules.Add(rule);
            }
            var verified = new HashSet<string>(StringComparer.Ordinal);
            foreach (OwnedTextureRequest request in result.Catalog.Values)
                if (verified.Add(request.Bundle.Path + "\0" + request.Bundle.Sha256)) request.Bundle.ValidateFile();
            result.Enabled = true;
            return result;
        }
        private static T Read<T>(string path)
        {
            using (var stream = File.OpenRead(path))
            {
                if (stream.Length > 1048576) throw new InvalidDataException("Owned manifest exceeds one MiB");
                var serializer = new DataContractJsonSerializer(typeof(T), new DataContractJsonSerializerSettings { MaxItemsInObjectGraph = 16384 });
                return (T)serializer.ReadObject(stream);
            }
        }
        private static string SafeFile(string root, string relative)
        {
            if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.IndexOf('\\') >= 0 || relative.IndexOf(':') >= 0)
                throw new InvalidDataException("Invalid owned relative path");
            foreach (string part in relative.Split('/'))
                if (part == ".." || part == "." || part.Length == 0) throw new InvalidDataException("Owned path traversal refused");
            string full = Path.GetFullPath(Path.Combine(root, relative));
            if (!full.StartsWith(root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.Ordinal))
                throw new InvalidDataException("Owned path escaped package");
            for (string path = full; path != null; path = Path.GetDirectoryName(path))
                if ((File.Exists(path) || Directory.Exists(path)) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Owned files cannot use links: " + path);
            return full;
        }
    }
}
