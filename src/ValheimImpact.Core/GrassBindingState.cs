using System.Runtime.Serialization;

namespace ValheimImpact.Core
{
    public struct GrassMaterialState
    {
        public bool RequiredPropertiesPresent, FixedStatePropertiesAbsent, Instancing;
        public bool AlphaTest, AlphaBlend, AlphaPremultiply, NormalMapBound, EmissionMapBound;
        public int RenderQueue;
        public float Cutoff, TerrainColorScale, BumpScale, NormalHack, TwoSidedNormals;
        public float Height, SwaySpeed, SwayDistance, PushDistance, CamCull;
        public float ColorR, ColorG, ColorB, ColorA;
    }

    // This policy describes fixed shader passes, not missing material floats.
    [DataContract]
    public sealed class GrassBindingState
    {
        [DataMember(IsRequired = true)] public string fixedPasses;
        [DataMember(IsRequired = true)] public float cutoff;
        [DataMember(IsRequired = true)] public int renderQueue;
        [DataMember(IsRequired = true)] public string terrainTextureName;
        [DataMember(IsRequired = true)] public int terrainWidth;
        [DataMember(IsRequired = true)] public int terrainHeight;
        [DataMember(IsRequired = true)] public float terrainColorScale;
        [DataMember(IsRequired = true)] public float swayDistance;
        [DataMember(IsRequired = true)] public float pushDistance;

        public bool Matches(GrassMaterialState actual)
        {
            return IsSupported && actual.RequiredPropertiesPresent && actual.FixedStatePropertiesAbsent && actual.Instancing &&
                actual.RenderQueue == renderQueue && actual.Cutoff == cutoff && actual.TerrainColorScale == terrainColorScale &&
                !actual.AlphaTest && !actual.AlphaBlend && !actual.AlphaPremultiply && !actual.NormalMapBound && !actual.EmissionMapBound &&
                actual.BumpScale == 0 && actual.NormalHack == 0 && actual.TwoSidedNormals == 0 && actual.Height == .5f &&
                actual.SwaySpeed == 60 && actual.SwayDistance == swayDistance && actual.PushDistance == pushDistance && actual.CamCull == 1 &&
                actual.ColorR == 1 && actual.ColorG == 1 && actual.ColorB == 1 && actual.ColorA == 1;
        }

        public bool IsSupported
        {
            get
            {
                return fixedPasses == "Custom/Grass-v1" && cutoff == .46f && renderQueue == 2000 &&
                    terrainTextureName == "grass_terrain_color" && terrainWidth == 1024 && terrainHeight == 1024 &&
                    terrainColorScale == .01f && ((swayDistance == 2.3f && pushDistance == 2) ||
                    (swayDistance == 1 && pushDistance == .5f));
            }
        }
        public bool MatchesIdentity(MaterialBindingRule rule)
        {
            if (!IsSupported || rule == null || rule.shaderName != "Custom/Grass" || rule.textureProperty != "_MainTex") return false;
            return (rule.materialName == "grasscross_meadows" && rule.originalTextureName == "grass_meadows" &&
                rule.originalWidth == 128 && rule.originalHeight == 128 && swayDistance == 2.3f && pushDistance == 2) ||
                (rule.materialName == "grasscross_meadows_short" && rule.originalTextureName == "grass_meadows_short" &&
                rule.originalWidth == 64 && rule.originalHeight == 64 && swayDistance == 1 && pushDistance == .5f);
        }
    }
}
