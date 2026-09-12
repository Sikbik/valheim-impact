#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

// Finite owned-texture sampling fixture. No game shader, geometry or installation.
public static class CutoutSamplingProbe
{
    [Serializable] private sealed class Catalog { public Entry[] textures; }
    [Serializable] private sealed class Entry
    {
        public string id, path, assetName, sha256;
        public int width, height, mipCount;
        public bool isSrgb;
    }
    [Serializable] private sealed class Sample
    {
        public float lod;
        public string filter, colorFile, colorSha256, maskFile, maskSha256;
        public int width, height, passingPixels;
    }
    [Serializable] private sealed class Report
    {
        public int schemaVersion = 1;
        public string textureId, bundleSha256, editorVersion, graphicsApi, colorSpace;
        public float cutoff;
        public bool complete, ownedObjectsDestroyed, gameShaderValidated;
        public string scope = "Explicit native mip sampling and cutoff masks of an owned BC3 texture. Point samples validate texels; fractional trilinear samples are diagnostics. No game shader, mesh, world or performance approval.";
        public List<Sample> samples = new List<Sample>();
    }
    private static string Hash(byte[] bytes)
    {
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }
    private static string Contained(string root, string relative)
    {
        if (string.IsNullOrEmpty(relative) || Path.IsPathRooted(relative))
            throw new InvalidDataException("Expected a relative owned input");
        var path = Path.GetFullPath(Path.Combine(root, relative));
        if (!path.StartsWith(Path.GetFullPath(root) + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new InvalidDataException("Owned input escapes its root");
        for (var item = new FileInfo(path) as FileSystemInfo; item != null; item = new DirectoryInfo(Path.GetDirectoryName(item.FullName)))
        {
            if (item.Exists && (item.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Linked owned inputs are forbidden");
            if (item.FullName == Path.GetPathRoot(item.FullName)) break;
        }
        return path;
    }
    public static string Run(string textureId, float cutoff)
    {
        if (!Regex.IsMatch(textureId ?? "", "^[a-z][a-z0-9_]{0,79}$") || float.IsNaN(cutoff) || cutoff <= 0 || cutoff >= 1)
            throw new ArgumentException("Expected an owned texture identifier and cutoff between zero and one");
        if (Application.unityVersion != "6000.0.75f1" || SystemInfo.graphicsDeviceType != GraphicsDeviceType.Vulkan || QualitySettings.activeColorSpace != ColorSpace.Linear || EditorApplication.isPlayingOrWillChangePlaymode)
            throw new InvalidOperationException("Use the stopped matching Vulkan/Linear Editor");
        string project = Directory.GetParent(Application.dataPath).FullName;
        string bundles = Path.Combine(project, "Bundles");
        string root = Directory.GetParent(project).FullName;
        string output = Contained(root, "local/meadows-pass/native-cutout/" + textureId);
        Directory.CreateDirectory(output);
        string reportPath = Contained(output, "report.json");
        if (File.Exists(reportPath)) File.Delete(reportPath);
        var catalog = JsonUtility.FromJson<Catalog>(File.ReadAllText(Contained(bundles, "catalog.json")));
        var entries = Array.FindAll(catalog.textures, item => item.id == textureId);
        if (entries.Length != 1) throw new InvalidDataException("Expected one catalog identity");
        var entry = entries[0];
        string bundlePath = Contained(bundles, entry.path);
        if (Hash(File.ReadAllBytes(bundlePath)) != entry.sha256) throw new InvalidDataException("Bundle hash mismatch");
        var report = new Report { textureId = textureId, bundleSha256 = entry.sha256, cutoff = cutoff,
            editorVersion = Application.unityVersion, graphicsApi = SystemInfo.graphicsDeviceType.ToString(), colorSpace = QualitySettings.activeColorSpace.ToString() };
        AssetBundle bundle = null;
        Texture2D texture = null;
        Material material = null;
        try
        {
            var shader = Shader.Find("Hidden/Valheim Impact/Cutout Sampling");
            if (shader == null || !shader.isSupported) throw new InvalidOperationException("Stage the supported owned sampling shader");
            bundle = AssetBundle.LoadFromFile(bundlePath);
            if (bundle == null) throw new InvalidDataException("Native bundle load failed");
            texture = bundle.LoadAsset<Texture2D>(entry.assetName);
            var names = bundle.GetAllAssetNames();
            if (names.Length != 1 || names[0] != entry.assetName || texture == null || texture.isReadable || !entry.isSrgb || !texture.isDataSRGB || texture.format != TextureFormat.DXT5 || texture.width != entry.width || texture.height != entry.height || texture.mipmapCount != entry.mipCount || entry.width > 2048 || entry.height > 2048)
                throw new InvalidDataException("Native owned texture contract failed");
            material = new Material(shader);
            material.SetTexture("_Source", texture);
            material.SetFloat("_Cutoff", cutoff);
            for (int level = 0; level < texture.mipmapCount; level++)
                report.samples.Add(Capture(texture, material, output, level, FilterMode.Point, Math.Max(1, texture.width >> level), Math.Max(1, texture.height >> level)));
            for (int level = 0; level < texture.mipmapCount - 1; level++)
                report.samples.Add(Capture(texture, material, output, level + .5f, FilterMode.Trilinear, 128, 128));
        }
        finally
        {
            if (material != null) UnityEngine.Object.DestroyImmediate(material);
            if (bundle != null) bundle.Unload(true);
        }
        report.ownedObjectsDestroyed = material == null && texture == null && bundle == null;
        if (!report.ownedObjectsDestroyed) throw new InvalidOperationException("Owned fixture objects did not drain");
        report.complete = true;
        File.WriteAllText(reportPath, JsonUtility.ToJson(report, true));
        return "Validated " + report.samples.Count + " native sample pairs; owned objects destroyed";
    }
    private static Sample Capture(Texture2D texture, Material material, string output, float lod, FilterMode filter, int width, int height)
    {
        texture.filterMode = filter;
        texture.anisoLevel = 1;
        material.SetFloat("_Mip", lod);
        var sample = new Sample { lod = lod, filter = filter.ToString(), width = width, height = height };
        string stem = "mip-" + lod.ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + "-" + filter;
        sample.colorFile = stem + "-color.png";
        sample.maskFile = stem + "-mask.png";
        var previous = RenderTexture.active;
        bool previousWrite = GL.sRGBWrite;
        RenderTexture target = null;
        Texture2D readback = null;
        try
        {
            target = RenderTexture.GetTemporary(width, height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
            readback = new Texture2D(width, height, TextureFormat.RGBA32, false, true);
            GL.sRGBWrite = false;
            for (int mask = 0; mask < 2; mask++)
            {
                material.SetFloat("_Clip", mask);
                Graphics.Blit(texture, target, material);
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                readback.Apply(false, false);
                byte[] bytes = readback.EncodeToPNG();
                File.WriteAllBytes(Contained(output, mask == 0 ? sample.colorFile : sample.maskFile), bytes);
                if (mask == 0) sample.colorSha256 = Hash(bytes);
                else
                {
                    sample.maskSha256 = Hash(bytes);
                    foreach (Color32 pixel in readback.GetPixels32())
                    {
                        if ((pixel.r != 0 && pixel.r != 255) || pixel.r != pixel.g || pixel.r != pixel.b || pixel.r != pixel.a)
                            throw new InvalidDataException("Expected a binary native cutout mask");
                        if (pixel.r == 255) sample.passingPixels++;
                    }
                }
            }
            return sample;
        }
        finally
        {
            RenderTexture.active = previous;
            GL.sRGBWrite = previousWrite;
            if (target != null) RenderTexture.ReleaseTemporary(target);
            if (readback != null) UnityEngine.Object.DestroyImmediate(readback);
        }
    }
}
#endif
