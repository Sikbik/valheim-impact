using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using ValheimImpact.Core;

namespace ValheimImpact.Unity
{
    internal sealed class GrassMaterialGuard
    {
        private readonly Texture2D terrain;
        private static readonly int Main = Shader.PropertyToID("_MainTex"), Terrain = Shader.PropertyToID("_TerrainColorTex"),
            ColorId = Shader.PropertyToID("_Color"), Normal = Shader.PropertyToID("_BumpMap"), Emission = Shader.PropertyToID("_EmissiveTex");
        private static readonly int[] Absent = Ids("_Mode", "_Cull", "_ZWrite", "_SrcBlend", "_DstBlend");
        private static readonly int[] Scalars = Ids("_Cutoff", "_TerrainColorScale", "_BumpScale", "_NormalHack", "_TwoSidedNormals",
            "_Height", "_SwaySpeed", "_SwayDistance", "_PushDistance", "_CamCull");
        private static int[] Ids(params string[] names)
        { var ids = new int[names.Length]; for (int i = 0; i < ids.Length; i++) ids[i] = Shader.PropertyToID(names[i]); return ids; }
        private GrassMaterialGuard(Texture2D terrain) { this.terrain = terrain; }

        internal static GrassMaterialGuard Capture(Material material, GrassBindingState expected)
        {
            Texture2D main = material.GetTexture(Main) as Texture2D;
            Texture2D terrain = material.GetTexture(Terrain) as Texture2D;
            if (!Eligible(material, expected) || main == null || main.format != TextureFormat.BC7 || main.mipmapCount != 1 || !main.isDataSRGB ||
                terrain == null || terrain.name != expected.terrainTextureName || terrain.width != expected.terrainWidth || terrain.height != expected.terrainHeight ||
                terrain.mipmapCount != 11 || terrain.format != TextureFormat.DXT1 || !terrain.isDataSRGB) return null;
            var guard = new GrassMaterialGuard(terrain);
            return guard.Matches(material) ? guard : null;
        }
        internal bool Matches(Material material)
        {
            return material != null && terrain != null && ReferenceEquals(material.GetTexture(Terrain), terrain) &&
                terrain.width == 1024 && terrain.height == 1024 && terrain.mipmapCount == 11 && terrain.format == TextureFormat.DXT1 && terrain.isDataSRGB &&
                IdentityUv(material, Main) && IdentityUv(material, Terrain);
        }
        private static bool IdentityUv(Material material, int property)
        {
            Vector2 scale = material.GetTextureScale(property), offset = material.GetTextureOffset(property);
            return scale.x == 1 && scale.y == 1 && offset.x == 0 && offset.y == 0;
        }
        internal static bool Eligible(Material material, GrassBindingState expected)
        {
            if (material == null || material.shader == null || !material.shader.isSupported || material.shader.renderQueue != 2000 || material.passCount != 4) return false;
            var actual = new GrassMaterialState { RequiredPropertiesPresent = material.HasProperty(Main) && material.HasProperty(Terrain) &&
                material.HasProperty(ColorId) && material.HasProperty(Normal) && material.HasProperty(Emission), FixedStatePropertiesAbsent = true };
            for (int i = 0; i < Absent.Length; i++) actual.FixedStatePropertiesAbsent &= !material.HasFloat(Absent[i]) && !material.HasProperty(Absent[i]);
            for (int i = 0; i < Scalars.Length; i++) actual.RequiredPropertiesPresent &= material.HasFloat(Scalars[i]);
            if (!actual.RequiredPropertiesPresent || !actual.FixedStatePropertiesAbsent) return false;
            Color color = material.GetColor(ColorId);
            actual.ColorR = color.r; actual.ColorG = color.g; actual.ColorB = color.b; actual.ColorA = color.a;
            actual.Instancing = material.enableInstancing; actual.RenderQueue = material.renderQueue;
            actual.AlphaTest = material.IsKeywordEnabled("_ALPHATEST_ON"); actual.AlphaBlend = material.IsKeywordEnabled("_ALPHABLEND_ON");
            actual.AlphaPremultiply = material.IsKeywordEnabled("_ALPHAPREMULTIPLY_ON");
            actual.NormalMapBound = material.GetTexture(Normal) != null; actual.EmissionMapBound = material.GetTexture(Emission) != null;
            actual.Cutoff = material.GetFloat(Scalars[0]); actual.TerrainColorScale = material.GetFloat(Scalars[1]);
            actual.BumpScale = material.GetFloat(Scalars[2]); actual.NormalHack = material.GetFloat(Scalars[3]); actual.TwoSidedNormals = material.GetFloat(Scalars[4]);
            actual.Height = material.GetFloat(Scalars[5]); actual.SwaySpeed = material.GetFloat(Scalars[6]); actual.SwayDistance = material.GetFloat(Scalars[7]);
            actual.PushDistance = material.GetFloat(Scalars[8]); actual.CamCull = material.GetFloat(Scalars[9]);
            return expected.Matches(actual) && material.GetShaderPassEnabled("FORWARD") && material.GetShaderPassEnabled("DEFERRED") && material.GetShaderPassEnabled("ShadowCaster");
        }
    }

    internal sealed class GrassShaderContracts
    {
        private sealed class Entry { internal Shader Shader; internal bool Valid; }
        private readonly Dictionary<int, Entry> shaders = new Dictionary<int, Entry>();
        private static readonly string[] Names = { "_Color", "_MainTex", "_TerrainColorTex", "_TerrainColorScale", "_BumpMap", "_BumpScale",
            "_NormalHack", "_TwoSidedNormals", "_EmissiveTex", "_EmissionColor", "_Glossiness", "_Metallic", "_Cutoff", "_FadeDistanceMin",
            "_FadeDistanceMax", "_Height", "_SwaySpeed", "_SwayDistance", "_PushDistance", "_DistanceScale", "_CamCull" };
        private static readonly ShaderPropertyType[] Types = { ShaderPropertyType.Color, ShaderPropertyType.Texture, ShaderPropertyType.Texture,
            ShaderPropertyType.Float, ShaderPropertyType.Texture, ShaderPropertyType.Float, ShaderPropertyType.Float, ShaderPropertyType.Float,
            ShaderPropertyType.Texture, ShaderPropertyType.Color, ShaderPropertyType.Range, ShaderPropertyType.Range, ShaderPropertyType.Range,
            ShaderPropertyType.Float, ShaderPropertyType.Float, ShaderPropertyType.Float, ShaderPropertyType.Float, ShaderPropertyType.Float,
            ShaderPropertyType.Float, ShaderPropertyType.Float, ShaderPropertyType.Float };
        internal bool Matches(Material material)
        {
            Shader shader = material.shader;
            if (shader == null) return false;
            int key = shader.GetInstanceID(); Entry previous;
            if (shaders.TryGetValue(key, out previous) && ReferenceEquals(shader, previous.Shader)) return previous.Valid;
            if (!shaders.ContainsKey(key) && shaders.Count >= 16) return false;
            bool valid = shader.name == "Custom/Grass" && shader.renderQueue == 2000 && shader.GetPropertyCount() == Names.Length && material.passCount == 4;
            for (int i = 0; valid && i < Names.Length; i++) valid &= shader.GetPropertyName(i) == Names[i] && shader.GetPropertyType(i) == Types[i];
            valid = valid && material.GetPassName(0) == "FORWARD" && material.GetPassName(1) == "FORWARD" &&
                material.GetPassName(2) == "DEFERRED" && material.GetPassName(3) == "ShadowCaster";
            shaders[key] = new Entry { Shader = shader, Valid = valid }; return valid;
        }
    }
}
