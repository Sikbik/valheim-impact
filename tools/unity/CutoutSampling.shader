Shader "Hidden/Valheim Impact/Cutout Sampling"
{
    Properties
    {
        _Source ("Owned texture", 2D) = "white" {}
        _Mip ("Explicit mip", Float) = 0
        _Cutoff ("Alpha cutoff", Float) = 0.69
        _Clip ("Output clip mask", Float) = 0
    }
    SubShader
    {
        Cull Off ZWrite Off ZTest Always
        Pass
        {
            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #pragma target 3.0
            #include "UnityCG.cginc"
            sampler2D _Source;
            float _Mip, _Cutoff, _Clip;
            float4 frag(v2f_img input) : SV_Target
            {
                float4 value = tex2Dlod(_Source, float4(input.uv, 0, _Mip));
                if (_Clip > 0.5)
                {
                    // Zero outside the cutout, one inside. This avoids an
                    // undefined render-target clear value after discard.
                    return step(_Cutoff, value.a).xxxx;
                }
                return value;
            }
            ENDCG
        }
    }
}
