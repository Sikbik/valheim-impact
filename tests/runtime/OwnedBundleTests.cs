using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using ValheimImpact.Core;

internal static class OwnedBundleTests
{
    internal static void Run(Action<bool, string> check, string dir)
    {
        string file = Path.Combine(dir, "authored.bundle");
        // Deliberately synthetic header fixture, not an engine-loadable AssetBundle.
        byte[] bytes = Encoding.ASCII.GetBytes("UnityFS\0synthetic-test-only");
        File.WriteAllBytes(file, bytes);
        string hash;
        using (var sha = SHA256.Create()) hash = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        var spec = new OwnedTextureBundle(file, "assets/authored/stone.png", hash, 8, 4, true);
        spec.ValidateFile();
        check(spec.IsSrgb && spec.MipCount == 4 && spec.PayloadBytes == TextureIndex.Dxt5Bytes(8, 4), "owned bundle has explicit sRGB and full mip contract");
        bool rejected = false;
        try { new OwnedTextureBundle(file, "", hash, 8, 4, true); } catch (ArgumentException) { rejected = true; }
        check(rejected, "owned bundle rejects empty asset selector");
        rejected = false;
        try { new OwnedTextureBundle(file, "stone", hash, 7, 4, true); } catch (ArgumentException) { rejected = true; }
        check(rejected, "owned bundle rejects unsupported texture dimensions");
        bytes[bytes.Length - 1] ^= 1; File.WriteAllBytes(file, bytes);
        rejected = false;
        try { spec.ValidateFile(); } catch (InvalidDataException) { rejected = true; }
        check(rejected, "owned bundle rejects changed content before engine loading");
        bytes[0] = 0; File.WriteAllBytes(file, bytes);
        using (var sha = SHA256.Create()) hash = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        rejected = false;
        try { new OwnedTextureBundle(file, "stone", hash, 8, 4, false).ValidateFile(); } catch (InvalidDataException) { rejected = true; }
        check(rejected, "owned bundle rejects invalid UnityFS header despite matching digest");
    }
}
