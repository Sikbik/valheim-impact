using System;
using ValheimImpact.Core;

internal static class GrassBindingTests
{
    public static void Run(Action<bool,string> check)
    {
        var rule=new GrassBindingState { fixedPasses="Custom/Grass-v1",cutoff=.46f,renderQueue=2000,
            terrainTextureName="grass_terrain_color",terrainWidth=1024,terrainHeight=1024,terrainColorScale=.01f,swayDistance=2.3f,pushDistance=2 };
        var original=new GrassMaterialState { RequiredPropertiesPresent=true, FixedStatePropertiesAbsent=true, Instancing=true,
            RenderQueue=2000,Cutoff=.46f,TerrainColorScale=.01f,SwayDistance=2.3f,PushDistance=2,Height=.5f,SwaySpeed=60,CamCull=1,
            ColorR=1,ColorG=1,ColorB=1,ColorA=1 };
        check(rule.Matches(original),"grass admits the measured fixed shader state without fabricated mode or cull values");
        var altered=original; altered.FixedStatePropertiesAbsent=false;
        check(!rule.Matches(altered),"grass rejects unexpected material-controlled pass properties");
        altered=original; altered.RequiredPropertiesPresent=false;
        check(!rule.Matches(altered),"grass rejects missing typed properties before their default reads can be accepted");
        altered=original; altered.Instancing=false;
        check(!rule.Matches(altered),"grass requires the original instancing state");
        altered=original; altered.RenderQueue=2450;
        check(!rule.Matches(altered),"grass rejects a changed queue even inside an opaque range");
        altered=original; altered.Cutoff=.5f;
        check(!rule.Matches(altered),"grass rejects a changed cutout silhouette threshold");
        altered=original; altered.Cutoff=float.NaN;
        check(!rule.Matches(altered),"grass rejects nonfinite threshold state");
        altered=original; altered.TerrainColorScale=.02f;
        check(!rule.Matches(altered),"grass rejects a changed world terrain-color sampling scale");
        altered=original; altered.AlphaTest=true;
        check(!rule.Matches(altered),"grass rejects an actually enabled alpha-test keyword");
        altered=original; altered.AlphaBlend=true;
        check(!rule.Matches(altered),"grass rejects an actually enabled alpha-blend keyword");
        altered=original; altered.AlphaPremultiply=true;
        check(!rule.Matches(altered),"grass rejects an actually enabled premultiply keyword");
        altered=original; altered.ColorA=.5f;
        check(!rule.Matches(altered),"grass rejects a material alpha change that changes cutoff coverage");
        altered=original; altered.ColorG=.5f;
        check(!rule.Matches(altered),"grass rejects a material color change outside its reviewed multiplication");
        altered=original; altered.NormalMapBound=true;
        check(!rule.Matches(altered),"grass does not adopt a material with an added normal map");
        altered=original; altered.EmissionMapBound=true;
        check(!rule.Matches(altered),"grass does not adopt a material with an added emission map");
        altered=original; altered.BumpScale=.1f;
        check(!rule.Matches(altered),"grass rejects a changed normal scale");
        altered=original; altered.NormalHack=1;
        check(!rule.Matches(altered),"grass rejects a changed normal direction policy");
        altered=original; altered.TwoSidedNormals=1;
        check(!rule.Matches(altered),"grass rejects changed two-sided normal treatment");
        altered=original; altered.Height=1;
        check(!rule.Matches(altered),"grass rejects a changed wind bend-height parameter");
        altered=original; altered.SwaySpeed=10;
        check(!rule.Matches(altered),"grass rejects changed sway speed");
        altered=original; altered.SwayDistance=1;
        check(!rule.Matches(altered),"tall grass rejects the short variant sway parameter");
        altered=original; altered.PushDistance=.5f;
        check(!rule.Matches(altered),"tall grass rejects the short variant push parameter");
        altered=original; altered.CamCull=0;
        check(!rule.Matches(altered),"grass rejects changed near-camera culling behavior");
    }
}
