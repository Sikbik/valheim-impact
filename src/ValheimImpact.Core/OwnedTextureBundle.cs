using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace ValheimImpact.Core
{
    // Authored single-texture bundle descriptor, independent of legacy pack records.
    // This validates an envelope, not Unity serialization or shader compatibility.
    public sealed class OwnedTextureBundle
    {
        public string Path { get; private set; }
        public string AssetName { get; private set; }
        public string Sha256 { get; private set; }
        public int Width { get; private set; }
        public int Height { get; private set; }
        public bool IsSrgb { get; private set; }
        public int MipCount { get; private set; }
        public long PayloadBytes { get; private set; }

        public OwnedTextureBundle(string path, string assetName, string sha256, int width, int height, bool isSrgb)
        {
            if (string.IsNullOrWhiteSpace(path) || string.IsNullOrWhiteSpace(assetName))
                throw new ArgumentException("A bundle path and exact asset selector are required");
            if (sha256 == null || sha256.Length != 64) throw new ArgumentException("Expected SHA256 digest");
            foreach (char c in sha256)
                if (!Uri.IsHexDigit(c)) throw new ArgumentException("Expected hexadecimal SHA256 digest");
            if (!TextureIndex.IsPowerOfTwo(width) || !TextureIndex.IsPowerOfTwo(height) || width > 16384 || height > 16384)
                throw new ArgumentException("Expected power-of-two dimensions up to 16384");
            Path = System.IO.Path.GetFullPath(path); AssetName = assetName; Sha256 = sha256.ToLowerInvariant();
            Width = width; Height = height; IsSrgb = isSrgb;
            int dimension = Math.Max(width, height); MipCount = 1;
            while (dimension > 1) { dimension >>= 1; MipCount++; }
            PayloadBytes = TextureIndex.Dxt5Bytes(width, height);
        }

        // Perform during offline preparation, not a frame-time critical demand.
        public void ValidateFile()
        {
            using (var stream = File.OpenRead(Path))
            {
                byte[] header = new byte[8];
                if (stream.Read(header, 0, 8) != 8 || Encoding.ASCII.GetString(header) != "UnityFS\0")
                    throw new InvalidDataException("Expected an authored UnityFS bundle");
                stream.Position = 0;
                using (var sha = SHA256.Create())
                {
                    string actual = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
                    if (actual != Sha256) throw new InvalidDataException("Authored bundle digest mismatch");
                }
            }
        }
    }
}
