// Editor-only, fixed-lighting comparison of two mip limits from the same authored art.
using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

public static class GraniteQualityProbe
{
    static Texture2D Texture(string path, int level, bool linear)
    {
        byte[] dds = File.ReadAllBytes(path);
        if (dds.Length < 128 || System.Text.Encoding.ASCII.GetString(dds, 84, 4) != "DXT5" ||
            BitConverter.ToInt32(dds, 12) != 1024 || BitConverter.ToInt32(dds, 16) != 1024)
            throw new InvalidDataException("Expected the owned 1024 BC3 source");
        int offset = 128, size = 1024;
        for (int mip = 0; mip < level; mip++) { offset += size * size; size /= 2; }
        var payload = new byte[dds.Length - offset]; Buffer.BlockCopy(dds, offset, payload, 0, payload.Length);
        var texture = new Texture2D(size, size, TextureFormat.DXT5, true, linear);
        texture.LoadRawTextureData(payload); texture.Apply(false, true);
        texture.filterMode = FilterMode.Trilinear; texture.anisoLevel = 4;
        return texture;
    }

    [MenuItem("Valheim Impact/Capture granite quality comparison")]
    public static void Capture()
    {
        if (SystemInfo.graphicsDeviceType != GraphicsDeviceType.Vulkan || QualitySettings.activeColorSpace != ColorSpace.Linear)
            throw new InvalidOperationException("Comparison requires Vulkan and Linear color space");
        var previousScene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
        bool previousAsyncCompilation = ShaderUtil.allowAsyncCompilation;
        ShaderUtil.allowAsyncCompilation = false;
        var scene = EditorSceneManager.NewPreviewScene();
        var owned = new System.Collections.Generic.List<UnityEngine.Object>();
        RenderTexture target = null;
        RenderTexture previous = RenderTexture.active;
        try
        {
            string root = Directory.GetParent(Application.dataPath).FullName;
            var cameraObject = new GameObject("Owned comparison camera");
            UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(cameraObject, scene);
            var camera = cameraObject.AddComponent<Camera>(); camera.scene = scene;
            camera.transform.position = new Vector3(0, 0, -4); camera.transform.LookAt(Vector3.zero);
            camera.orthographic = true; camera.orthographicSize = 1.55f; camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.1f, 0.14f, 0.2f); camera.nearClipPlane = 0.1f; camera.farClipPlane = 20;
            var shader = Shader.Find("Unlit/Texture");
            if (shader == null) throw new InvalidOperationException("Built-in Unlit/Texture shader is required");
            // Unlit avoids different spherical UV coverage and isolates resolution from lighting.
            for (int side = 0; side < 2; side++)
            {
                int level = side == 0 ? 2 : 0;
                var texture = Texture(Path.Combine(root, "OwnedInputs/granite_hd_albedo-unity.dds"), level, false); owned.Add(texture);
                var material = new Material(shader) { mainTexture = texture }; owned.Add(material);
                ShaderUtil.CompilePass(material, 0, true);
                var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
                quad.name = side == 0 ? "Same art at 256" : "Same art at 1024";
                UnityEngine.SceneManagement.SceneManager.MoveGameObjectToScene(quad, scene);
                quad.transform.position = new Vector3(side == 0 ? -1.4f : 1.4f, 0, 0);
                quad.transform.localScale = new Vector3(2.65f, 2.65f, 1);
                quad.GetComponent<Renderer>().sharedMaterial = material;
            }
            target = new RenderTexture(3840, 2160, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
            camera.targetTexture = target; camera.Render(); RenderTexture.active = target;
            var pixels = new Texture2D(3840, 2160, TextureFormat.RGBA32, false); owned.Add(pixels);
            pixels.ReadPixels(new Rect(0, 0, 3840, 2160), 0, 0); pixels.Apply();
            string output = Path.Combine(root, "Assets/Captures/granite-256-vs-1024-4k.png");
            Directory.CreateDirectory(Path.GetDirectoryName(output)); File.WriteAllBytes(output, pixels.EncodeToPNG());
            Debug.Log("Captured same authored granite: left 256, right 1024, fixed 4K unlit view. Not a game screenshot or preset benchmark.");
        }
        finally
        {
            RenderTexture.active = previous;
            ShaderUtil.allowAsyncCompilation = previousAsyncCompilation;
            EditorSceneManager.ClosePreviewScene(scene);
            if (target != null) { target.Release(); UnityEngine.Object.DestroyImmediate(target); }
            foreach (var item in owned) if (item != null) UnityEngine.Object.DestroyImmediate(item);
            if (previousScene.IsValid()) UnityEngine.SceneManagement.SceneManager.SetActiveScene(previousScene);
        }
    }
}
