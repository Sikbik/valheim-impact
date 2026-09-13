using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

// Owned blockout only. No Valheim geometry, shaders, bindings or installation access.
public static class MeadowsBuild
{
    [Serializable] public class Input { public string id, unity_dds, unity_dds_sha256, role, wrap_mode; public int[] dimensions; public int mip_count, compressed_payload_bytes; public bool srgb; }
    [Serializable] public class Inputs { public Input[] assets; }
    [Serializable] public class Descriptor { public string id, path, assetName, sha256, payloadSha256, gpuReadback, gpuReadbackSha256, wrapMode; public int width, height, mipCount, payloadBytes; public bool isSrgb; }
    [Serializable] public class Catalog { public int schemaVersion = 1; public bool nativeReadback; public string editorVersion, graphicsApi, colorSpace, target = "StandaloneLinux64", validation = "Editor native readback and base-mip GPU sampling; game binding and representative performance untested"; public Descriptor[] textures; }
    static string Hash(byte[] bytes) { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }

    [MenuItem("Valheim Impact/Build owned Meadows probes")]
    public static void Build()
    {
        if (Application.unityVersion != "6000.0.75f1") throw new InvalidOperationException("Use the matching 6000.0.75f1 Editor");
        if (SystemInfo.graphicsDeviceType != GraphicsDeviceType.Vulkan || QualitySettings.activeColorSpace != ColorSpace.Linear)
            throw new InvalidOperationException("Native GPU validation requires Vulkan graphics and Linear color space");
        for (int i = 0; i < UnityEngine.SceneManagement.SceneManager.sceneCount; i++)
            if (UnityEngine.SceneManagement.SceneManager.GetSceneAt(i).isDirty)
                throw new InvalidOperationException("Save your open scenes before rebuilding the owned probes");
        string root = Directory.GetParent(Application.dataPath).FullName;
        var inputs = JsonUtility.FromJson<Inputs>(File.ReadAllText(Path.Combine(root, "OwnedInputs/manifest.json")));
        if (inputs == null || inputs.assets == null || inputs.assets.Length == 0)
            throw new InvalidDataException("Expected nonempty authored inputs");
        foreach (var item in inputs.assets)
            if (item == null || (item.wrap_mode != "repeat" && item.wrap_mode != "clamp"))
                throw new InvalidDataException("Staged wrap_mode must be repeat or clamp; regenerate the authored inputs");
        Directory.CreateDirectory("Assets/Owned");
        Directory.CreateDirectory("Assets/Probes");
        string output = Path.Combine(root, "Bundles");
        Directory.CreateDirectory(output);
        // Invalidate prior successful catalog before any operation that can fail.
        string catalogPath = Path.Combine(output, "catalog.json");
        if (File.Exists(catalogPath)) File.Delete(catalogPath);
        var builds = new List<AssetBundleBuild>();
        var records = new List<Descriptor>();
        foreach (var item in inputs.assets)
        {
            if (!System.Text.RegularExpressions.Regex.IsMatch(item.id, "^[a-z][a-z0-9_]*$") || item.unity_dds != item.id + "-unity.dds") throw new InvalidDataException("Unsafe input name");
            byte[] dds = File.ReadAllBytes(Path.Combine(root, "OwnedInputs", item.unity_dds));
            if (Hash(dds) != item.unity_dds_sha256 || dds.Length != item.compressed_payload_bytes + 128 || System.Text.Encoding.ASCII.GetString(dds, 84, 4) != "DXT5") throw new InvalidDataException("Payload mismatch");
            byte[] payload = new byte[dds.Length - 128];
            Buffer.BlockCopy(dds, 128, payload, 0, payload.Length);
            var texture = new Texture2D(item.dimensions[0], item.dimensions[1], TextureFormat.DXT5, true, !item.srgb);
            texture.name = item.id;
            texture.wrapMode = item.wrap_mode == "clamp" ? TextureWrapMode.Clamp : TextureWrapMode.Repeat;
            texture.filterMode = FilterMode.Trilinear;
            texture.anisoLevel = 4;
            texture.mipMapBias = 0;
            texture.LoadRawTextureData(payload);
            texture.Apply(false, true); // Preserve supplied DXT5nm channels and every supplied mip.
            if (texture.mipmapCount != item.mip_count) throw new InvalidDataException("Mip mismatch");
            string asset = "Assets/Owned/" + item.id + ".asset";
            AssetDatabase.DeleteAsset(asset);
            AssetDatabase.CreateAsset(texture, asset);
            string selector = asset.ToLowerInvariant();
            string bundle = item.id + ".bundle";
            builds.Add(new AssetBundleBuild { assetBundleName = bundle, assetNames = new[] { asset }, addressableNames = new[] { selector } });
            records.Add(new Descriptor { id = item.id, path = bundle, assetName = selector, width = texture.width, height = texture.height, mipCount = texture.mipmapCount, payloadBytes = payload.Length, isSrgb = item.srgb, payloadSha256 = Hash(payload), wrapMode = item.wrap_mode });
        }
        AssetDatabase.SaveAssets();
        BuildScene(records.Exists(r => r.id == "granite_hd_albedo"), records.Exists(r => r.id == "timber_hd_albedo"));
        // Rebuild the explicit owned set so a prior build with different enabled
        // engine modules cannot leave cached bundles that fail native readback.
        var result = BuildPipeline.BuildAssetBundles(output, builds.ToArray(), BuildAssetBundleOptions.ChunkBasedCompression | BuildAssetBundleOptions.StrictMode | BuildAssetBundleOptions.ForceRebuildAssetBundle, BuildTarget.StandaloneLinux64);
        if (result == null) throw new InvalidOperationException("Native bundle build failed");
        foreach (var record in records)
        {
            string file = Path.Combine(output, record.path);
            record.sha256 = Hash(File.ReadAllBytes(file));
            var bundle = AssetBundle.LoadFromFile(file);
            if (bundle == null) throw new InvalidDataException("Cannot read built bundle");
            try
            {
                var names = bundle.GetAllAssetNames();
                var texture = bundle.LoadAsset<Texture2D>(record.assetName);
                if (names.Length != 1 || names[0] != record.assetName || texture == null || texture.width != record.width || texture.height != record.height || texture.format != TextureFormat.DXT5 || texture.mipmapCount != record.mipCount || texture.isReadable || texture.isDataSRGB != record.isSrgb) throw new InvalidDataException("Built texture violates OwnedTextureBundle contract");
                var expectedWrap = record.wrapMode == "clamp" ? TextureWrapMode.Clamp : TextureWrapMode.Repeat;
                if (texture.wrapModeU != expectedWrap || texture.wrapModeV != expectedWrap || texture.wrapModeW != expectedWrap || texture.filterMode != FilterMode.Trilinear || texture.anisoLevel != 4 || texture.mipMapBias != 0)
                    throw new InvalidDataException("Built texture sampler differs from its recipe");
                record.gpuReadback = "readback/" + record.id + ".png";
                record.gpuReadbackSha256 = SaveGpuReadback(texture, Path.Combine(output, record.gpuReadback));
            }
            finally { bundle.Unload(true); }
        }
        File.WriteAllText(catalogPath, JsonUtility.ToJson(new Catalog { nativeReadback = true, editorVersion = Application.unityVersion, graphicsApi = SystemInfo.graphicsDeviceType.ToString(), colorSpace = QualitySettings.activeColorSpace.ToString(), textures = records.ToArray() }, true));
        Debug.Log("Built owned texture bundles, native GPU readbacks and BLOCKOUT probe. Game binding and performance validation remain pending.");
    }

    static string SaveGpuReadback(Texture2D source, string path)
    {
        var previous = RenderTexture.active;
        bool previousWrite = GL.sRGBWrite;
        var target = RenderTexture.GetTemporary(source.width, source.height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
        var pixels = new Texture2D(source.width, source.height, TextureFormat.RGBA32, false, true);
        try
        {
            GL.sRGBWrite = false;
            Graphics.Blit(source, target);
            RenderTexture.active = target;
            pixels.ReadPixels(new Rect(0, 0, source.width, source.height), 0, 0);
            pixels.Apply(false, false);
            byte[] png = pixels.EncodeToPNG();
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllBytes(path, png);
            return Hash(png);
        }
        finally
        {
            RenderTexture.active = previous;
            GL.sRGBWrite = previousWrite;
            RenderTexture.ReleaseTemporary(target);
            UnityEngine.Object.DestroyImmediate(pixels);
        }
    }

    static Material Material(string name, string texture = null, bool cutout = false)
    {
        var shader = Shader.Find("Standard");
        if (shader == null) throw new InvalidOperationException("Built-in Standard shader is required");
        var material = new Material(shader) { name = name };
        material.SetFloat("_Glossiness", 0.12f);
        if (texture != null)
        {
            material.mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/Owned/" + texture + "_albedo.asset");
            material.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/Owned/" + texture + "_normal.asset"));
            material.EnableKeyword("_NORMALMAP");
            material.SetFloat("_BumpScale", 0.5f);
        }
        if (cutout) { material.SetFloat("_Mode", 1); material.SetFloat("_Cutoff", 0.5f); material.EnableKeyword("_ALPHATEST_ON"); material.SetOverrideTag("RenderType", "TransparentCutout"); material.renderQueue = 2450; }
        string path = "Assets/Probes/" + name + ".mat";
        AssetDatabase.DeleteAsset(path); AssetDatabase.CreateAsset(material, path);
        return material;
    }
    static GameObject Shape(string name, PrimitiveType kind, Vector3 pos, Vector3 scale, Material material)
    {
        var obj = GameObject.CreatePrimitive(kind); obj.name = name; obj.transform.position = pos; obj.transform.localScale = scale;
        obj.GetComponent<Renderer>().sharedMaterial = material;
        return obj;
    }
    static void BuildScene(bool highDetailGranite, bool highDetailWood)
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var grass = Material("Grass", "grass"); var earth = Material("Earth", "earth"); var wood = Material("Timber", highDetailWood ? "timber_hd" : "timber");
        var stone = Material("Granite", highDetailGranite ? "granite_hd" : "granite"); var roof = Material("Thatch", highDetailWood ? "thatch_hd" : "thatch"); var leaves = Material("TreeCard", "beech_card", true);
        var water = Material("WaterStudy"); water.color = new Color(0.15f, 0.4f, 0.52f); water.SetFloat("_Glossiness", 0.7f);
        var proxy = Material("ScaleProxy"); proxy.color = new Color(0.5f, 0.26f, 0.17f);
        Shape("BLOCKOUT: owned geometry, not Valheim rendering", PrimitiveType.Cube, new Vector3(0, -0.25f, 0), new Vector3(20, 0.5f, 16), grass);
        Shape("Earth path", PrimitiveType.Cube, new Vector3(0, 0.015f, 1), new Vector3(2.5f, 0.03f, 10), earth);
        Shape("Timber house blockout", PrimitiveType.Cube, new Vector3(-3, 1.25f, 2), new Vector3(4, 2.5f, 4), wood);
        var a = Shape("Thatch roof west", PrimitiveType.Cube, new Vector3(-4.1f, 3, 2), new Vector3(3.1f, 0.2f, 4.8f), roof); a.transform.rotation = Quaternion.Euler(0, 0, 35);
        var b = Shape("Thatch roof east", PrimitiveType.Cube, new Vector3(-1.9f, 3, 2), new Vector3(3.1f, 0.2f, 4.8f), roof); b.transform.rotation = Quaternion.Euler(0, 0, -35);
        Shape("Boulder study", PrimitiveType.Sphere, new Vector3(3, 0.65f, 1), new Vector3(2.5f, 1.6f, 2), stone);
        Shape("Tree trunk blockout", PrimitiveType.Cylinder, new Vector3(4, 1.5f, 5), new Vector3(0.45f, 1.5f, 0.45f), wood);
        var card = Shape("Authored alpha tree card", PrimitiveType.Quad, new Vector3(4, 3.1f, 5), new Vector3(4, 4, 1), leaves); card.transform.rotation = Quaternion.Euler(0, -20, 0);
        Shape("Shoreline study", PrimitiveType.Cube, new Vector3(0, -0.1f, -7), new Vector3(20, 0.3f, 2), earth);
        Shape("Static opaque water study", PrimitiveType.Cube, new Vector3(0, -0.08f, -11), new Vector3(24, 0.1f, 6), water);
        Shape("1.8 metre scale proxy", PrimitiveType.Capsule, new Vector3(0, 0.9f, 1), new Vector3(0.6f, 0.9f, 0.6f), proxy);
        var camera = new GameObject("Fixed comparison camera").AddComponent<Camera>(); camera.tag = "MainCamera"; camera.transform.position = new Vector3(12, 8, -17); camera.transform.LookAt(new Vector3(0, 1.3f, 1)); camera.fieldOfView = 48;
        var sun = new GameObject("Study sun").AddComponent<Light>(); sun.type = LightType.Directional; sun.shadows = LightShadows.Soft;
        RenderSettings.ambientMode = AmbientMode.Flat; RenderSettings.fog = true; RenderSettings.fogMode = FogMode.ExponentialSquared; RenderSettings.fogDensity = 0.012f;
        foreach (string variant in new[] { "Daylight", "Sunset", "Night" })
        {
            bool night = variant == "Night", sunset = variant == "Sunset";
            sun.transform.rotation = Quaternion.Euler(night ? 25 : sunset ? 12 : 48, -30, 0);
            sun.intensity = night ? 0.35f : sunset ? 0.8f : 1.1f;
            sun.color = night ? new Color(0.55f, 0.65f, 1) : sunset ? new Color(1, 0.62f, 0.35f) : new Color(1, 0.95f, 0.83f);
            RenderSettings.ambientLight = night ? new Color(0.2f, 0.25f, 0.38f) : sunset ? new Color(0.25f, 0.22f, 0.35f) : new Color(0.48f, 0.58f, 0.68f);
            RenderSettings.fogColor = RenderSettings.ambientLight; camera.clearFlags = CameraClearFlags.SolidColor; camera.backgroundColor = RenderSettings.fogColor;
            EditorSceneManager.SaveScene(scene, "Assets/Probes/MeadowsBlockout" + variant + ".unity");
        }
        AssetDatabase.SaveAssets();
    }
}
