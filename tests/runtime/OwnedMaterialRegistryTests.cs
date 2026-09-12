using System;
using System.IO;
using System.Text;
using ValheimImpact.Core;

internal static class OwnedMaterialRegistryTests
{
    private static bool Reject(string root)
    { try { OwnedMaterialRegistry.Load(root); return false; } catch (Exception) { return true; } }
    public static void Run(Action<bool, string> check, string temp)
    {
        string root = Path.Combine(temp, "installed-binding-fixture"); Directory.CreateDirectory(Path.Combine(root, "assets"));
        string profile = "{\"schemaVersion\":1,\"profile\":\"Balanced\",\"experimental\":true,\"residentMiB\":768,\"inFlightMiB\":64,\"concurrentRequests\":2,\"startsPerFrame\":1";
        File.WriteAllText(Path.Combine(root, "profile.json"), profile + "}");
        var disabled = OwnedMaterialRegistry.Load(root);
        check(!disabled.Enabled, "old profile defaults to replacement disabled without opening catalog");
        File.WriteAllText(Path.Combine(root, "profile.json"), profile + ",\"enableGameReplacement\":true}");
        byte[] bytes = Encoding.ASCII.GetBytes("UnityFS\0owned-fixture");
        File.WriteAllBytes(Path.Combine(root, "assets/stone.bundle"), bytes);
        string catalog = "{\"schemaVersion\":1,\"editorVersion\":\"6000.0.75f1\",\"target\":\"StandaloneLinux64\",\"nativeReadback\":true,\"textures\":[{\"id\":\"stone\",\"path\":\"stone.bundle\",\"assetName\":\"assets/stone.asset\",\"sha256\":\"" + Fingerprint.Hex(bytes) + "\",\"payloadSha256\":\"" + new string('b', 64) + "\",\"width\":4,\"height\":4,\"mipCount\":3,\"payloadBytes\":48,\"isSrgb\":true}]}";
        string binding = "{\"id\":\"stone-slot\",\"materialName\":\"Rock\",\"shaderName\":\"Custom/StaticRock\",\"textureProperty\":\"_MainTex\",\"originalTextureName\":\"rock_256\",\"originalWidth\":512,\"originalHeight\":512,\"ownedTextureId\":\"stone\"}";
        string mappings = "{\"schemaVersion\":1,\"bindings\":[" + binding + "]}";
        File.WriteAllText(Path.Combine(root, "assets/catalog.json"), catalog);
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), mappings);
        var good = OwnedMaterialRegistry.Load(root);
        check(good.Enabled && good.Rules.Count == 1 && good.Catalog.Count == 1 && good.Policy.ResidentBudgetBytes == 805306368 && good.Policy.PendingBudgetBytes == 67108864,
            "installed registry verifies mapped owned bundle and consumes explicit profile budgets");
        string cutoutState = "\"cutout\":{\"mode\":1,\"cutoff\":0.69,\"cull\":0,\"zWrite\":1,\"srcBlend\":1,\"dstBlend\":0,\"renderQueue\":2000,\"alphaTest\":false}";
        string cutoutBinding = binding.Replace("\"Rock\"", "\"straw_roof_alpha\"").Replace("Custom/StaticRock", "Custom/Piece");
        cutoutBinding = cutoutBinding.Substring(0, cutoutBinding.Length - 1) + "," + cutoutState + "}";
        string cutoutMappings = "{\"schemaVersion\":2,\"bindings\":[" + cutoutBinding + "]}";
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), cutoutMappings);
        check(!Reject(root), "schema 2 accepts an explicit exact Custom/Piece cutout state without alpha blend");
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), cutoutMappings.Replace("\"schemaVersion\":2", "\"schemaVersion\":1"));
        check(Reject(root), "schema 1 cannot silently accept cutout semantics unknown to older runtimes");
        int invalidState = 0;
        foreach (string invalid in new[] {
            cutoutMappings.Replace("\"mode\":1", "\"mode\":2"),
            cutoutMappings.Replace("\"cutoff\":0.69,", ""),
            cutoutMappings.Replace("\"cutoff\":0.69", "\"cutoff\":0"),
            cutoutMappings.Replace("\"cull\":0", "\"cull\":7"),
            cutoutMappings.Replace("\"zWrite\":1", "\"zWrite\":0"),
            cutoutMappings.Replace("\"srcBlend\":1", "\"srcBlend\":5"),
            cutoutMappings.Replace("\"dstBlend\":0", "\"dstBlend\":10"),
            cutoutMappings.Replace("\"renderQueue\":2000", "\"renderQueue\":3000"),
            cutoutMappings.Replace("Custom/Piece", "Unknown/Cutout"),
            cutoutMappings.Replace(cutoutState, "\"cutout\":null"),
            cutoutMappings.Replace(cutoutState, "\"cutout\":null").Replace("\"schemaVersion\":2", "\"schemaVersion\":1") })
        {
            File.WriteAllText(Path.Combine(root, "assets/bindings.json"), invalid);
            check(Reject(root), "cutout manifest rejects incomplete, blended or unsupported state case " + (++invalidState));
        }
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), mappings.Replace("\"schemaVersion\":1", "\"schemaVersion\":2"));
        check(!Reject(root), "schema 2 retains ordinary opaque rules when the cutout opt-in is absent");
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), mappings.Replace("\"ownedTextureId\":\"stone\"", "\"ownedTextureId\":\"absent\""));
        check(Reject(root), "registry rejects unknown owned alias before replacement can activate");
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), "{\"schemaVersion\":1,\"bindings\":[" + binding + "," + binding.Replace("stone-slot", "duplicate-slot") + "]}");
        check(Reject(root), "registry rejects two rules targeting the same material shader slot");
        File.WriteAllText(Path.Combine(root, "assets/bindings.json"), mappings);
        File.WriteAllText(Path.Combine(root, "assets/catalog.json"), catalog.Replace("stone.bundle", "../outside.bundle"));
        check(Reject(root), "registry rejects bundle path escape before opening it");
        File.WriteAllText(Path.Combine(root, "assets/catalog.json"), catalog.Replace("\"nativeReadback\":true", "\"nativeReadback\":false"));
        check(Reject(root), "registry requires native validated catalog");
        File.WriteAllText(Path.Combine(root, "assets/catalog.json"), catalog);
        File.WriteAllBytes(Path.Combine(root, "assets/stone.bundle"), Encoding.ASCII.GetBytes("UnityFS\0changed-content"));
        check(Reject(root), "registry rejects changed archive bytes");
        File.WriteAllBytes(Path.Combine(root, "assets/stone.bundle"), bytes);
        File.WriteAllText(Path.Combine(root, "profile.json"), profile.Replace("\"startsPerFrame\":1", "\"startsPerFrame\":2") + ",\"enableGameReplacement\":true}");
        check(Reject(root), "registry cannot relax single engine start per frame");
    }
}
