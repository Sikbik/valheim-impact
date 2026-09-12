using System;
using System.Runtime.Serialization;

namespace ValheimImpact.Core
{
    [DataContract]
    public sealed class MaterialBindingRule
    {
        [DataMember(IsRequired = true)] public string id;
        [DataMember(IsRequired = true)] public string materialName;
        [DataMember(IsRequired = true)] public string shaderName;
        [DataMember(IsRequired = true)] public string textureProperty;
        [DataMember(IsRequired = true)] public string originalTextureName;
        [DataMember(IsRequired = true)] public string ownedTextureId;
        [DataMember(IsRequired = true)] public int originalWidth;
        [DataMember(IsRequired = true)] public int originalHeight;
        private CutoutBindingState cutoutState;
        public bool CutoutSpecified { get; private set; }
        [DataMember(EmitDefaultValue = false)] public CutoutBindingState cutout
        {
            get { return cutoutState; }
            set { CutoutSpecified = true; cutoutState = value; }
        }
        public bool Matches(string material, string shader, string property, string texture, int width, int height)
        {
            return string.Equals(material, materialName, StringComparison.Ordinal) &&
                string.Equals(shader, shaderName, StringComparison.Ordinal) &&
                string.Equals(property, textureProperty, StringComparison.Ordinal) &&
                string.Equals(texture, originalTextureName, StringComparison.Ordinal) &&
                width == originalWidth && height == originalHeight;
        }
    }
    [DataContract]
    public sealed class CutoutBindingState
    {
        [DataMember(IsRequired = true)] public float mode;
        [DataMember(IsRequired = true)] public float cutoff;
        [DataMember(IsRequired = true)] public float cull;
        [DataMember(IsRequired = true)] public float zWrite;
        [DataMember(IsRequired = true)] public float srcBlend;
        [DataMember(IsRequired = true)] public float dstBlend;
        [DataMember(IsRequired = true)] public int renderQueue;
        [DataMember(IsRequired = true)] public bool alphaTest;
        public bool IsSupported
        {
            get
            {
                return mode == 1 && cutoff > 0 && cutoff < 1 && (cull == 0 || cull == 2) &&
                    zWrite == 1 && srcBlend == 1 && dstBlend == 0 && renderQueue >= 1000 && renderQueue <= 2500;
            }
        }
        public bool Matches(float actualMode, float actualCutoff, float actualCull, float actualZWrite,
            float actualSrcBlend, float actualDstBlend, int actualQueue, bool actualAlphaTest, bool alphaBlend, bool alphaPremultiply)
        {
            return IsSupported && actualMode == mode && actualCutoff == cutoff && actualCull == cull && actualZWrite == zWrite &&
                actualSrcBlend == srcBlend && actualDstBlend == dstBlend && actualQueue == renderQueue && actualAlphaTest == alphaTest &&
                !alphaBlend && !alphaPremultiply;
        }
    }
    // Writes only a texture slot whose exact object is still ours. The engine
    // adapter supplies liveness, shader and identity checks and never edits UVs.
    public sealed class OwnedMaterialLease<T> where T : class
    {
        private readonly T original;
        private OwnedTextureScheduler<T>.Lease lease;
        private T replacement;
        public bool IsReleased { get { return lease == null; } }
        public bool IsApplied { get { return replacement != null && lease != null; } }
        public OwnedMaterialLease(T original, OwnedTextureScheduler<T>.Lease lease)
        {
            if (original == null || lease == null) throw new ArgumentNullException("material lease");
            this.original = original; this.lease = lease;
        }
        public bool StillOwns(Func<T> read)
        { return lease != null && ReferenceEquals(read(), replacement ?? original); }
        public bool ApplyReady(Func<T> read, Action<T> write, Func<bool> canApply)
        {
            if (lease == null || replacement != null || !ReferenceEquals(read(), original) || !canApply()) return false;
            T value;
            if (!lease.TryGet(out value)) return false;
            write(value); replacement = value; return true;
        }
        public bool RestoreAndRelease(Func<T> read, Action<T> write, Func<bool> canRestore)
        {
            if (lease == null) return true;
            if (replacement != null && ReferenceEquals(read(), replacement))
            {
                if (!canRestore()) return false;
                write(original);
            }
            lease.Dispose(); lease = null; return true;
        }
    }
}
