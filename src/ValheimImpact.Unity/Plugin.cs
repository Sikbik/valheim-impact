using System.IO;
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;

namespace ValheimImpact.Unity
{
    [BepInPlugin("org.valheimimpact.diagnostics", "Valheim Impact", "0.2.0")]
    public sealed class Plugin : BaseUnityPlugin
    {
        private OwnedMaterialHost host;
        private ConfigEntry<bool> replacement;
        private void Awake()
        {
            var diagnostics = Config.Bind("Diagnostics", "Enabled", false,
                "Emit runtime/GPU evidence and bounded frame-delta summaries every 30 seconds.");
            replacement = Config.Bind("GameReplacement", "Enabled", true,
                "Allow the explicitly enabled installed profile to replace validated material slots. Disabling restores originals and drains owned textures.");
            var pump = new GameObject("Valheim Impact owned material pump");
            DontDestroyOnLoad(pump);
            host = pump.AddComponent<OwnedMaterialHost>();
            host.Initialize(Path.GetDirectoryName(typeof(Plugin).Assembly.Location), diagnostics.Value,
                message => Logger.LogInfo(message), message => Logger.LogError(message));
            host.SetReplacementEnabled(replacement.Value);
            Logger.LogInfo("Valheim Impact runtime; unity=" + Application.unityVersion +
                "; api=" + SystemInfo.graphicsDeviceType + "; gpu=" + SystemInfo.graphicsDeviceName +
                "; reportedVramMiB=" + SystemInfo.graphicsMemorySize +
                "; shaderLevel=" + SystemInfo.graphicsShaderLevel +
                "; asyncUploadBufferMiB=" + QualitySettings.asyncUploadBufferSize +
                "; asyncUploadTimeSliceMs=" + QualitySettings.asyncUploadTimeSlice +
                "; colorSpace=" + QualitySettings.activeColorSpace);
        }
        private void Update() { if (host != null) host.SetReplacementEnabled(replacement.Value); }
        private void OnEnable() { if (host != null && replacement != null) host.SetReplacementEnabled(replacement.Value); }
        private void OnDisable() { if (host != null) host.SetReplacementEnabled(false); }
        private void OnDestroy() { if (host != null) host.CloseWhenDrained(); }
    }
}
