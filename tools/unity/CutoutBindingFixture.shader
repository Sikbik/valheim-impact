// Owned diagnostic shader only. Stage beside MaterialBindingProbe in the Editor.
// The four saved mode/blend/depth floats are deliberately absent from Properties
// to characterize the public material getter behavior needed by Custom/Piece.
Shader "Valheim Impact/Cutout Binding Fixture"
{
    Properties
    {
        _MainTex ("Albedo", 2D) = "white" {}
        _BumpMap ("Unrelated normal channel", 2D) = "bump" {}
        _Cutoff ("Alpha Cutoff", Range(0,1)) = 0.69
        _Cull ("Cull", Float) = 0
    }
    SubShader
    {
        Tags { "Queue"="Geometry" "RenderType"="Opaque" }
        Cull [_Cull]
        ZWrite On
        Blend One Zero
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_local _ _ALPHATEST_ON
            #pragma multi_compile_local _ _ALPHABLEND_ON
            #pragma multi_compile_local _ _ALPHAPREMULTIPLY_ON
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            float4 _MainTex_ST;
            float _Cutoff;
            struct Input { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct Output { float4 vertex : SV_POSITION; float2 uv : TEXCOORD0; };
            Output vert(Input value)
            {
                Output result;
                result.vertex = UnityObjectToClipPos(value.vertex);
                result.uv = TRANSFORM_TEX(value.uv, _MainTex);
                return result;
            }
            fixed4 frag(Output value) : SV_Target
            {
                fixed4 color = tex2D(_MainTex, value.uv);
                clip(color.a - _Cutoff);
                return color;
            }
            ENDCG
        }
    }
}
