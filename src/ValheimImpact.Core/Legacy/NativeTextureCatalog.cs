using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace ValheimImpact.Core
{
    public sealed class NativeTextureRecord
    {
        public TextureEntry Entry;
        public string Content, BundlePath;
    }

    public sealed class NativeTextureCatalog
    {
        public readonly Dictionary<string, NativeTextureRecord> Records = new Dictionary<string, NativeTextureRecord>(StringComparer.Ordinal);
        public bool TryMatch(TextureEntry entry, out NativeTextureRecord record)
        {
            if (!Records.TryGetValue(entry.Name, out record)) return false;
            TextureEntry other = record.Entry;
            return other.Path == entry.Path && other.Offset == entry.Offset && other.Length == entry.Length &&
                other.SourceBytes == entry.SourceBytes && other.SourceWriteTicks == entry.SourceWriteTicks &&
                other.Width == entry.Width && other.Height == entry.Height && other.IsSrgb == entry.IsSrgb;
        }

        private static string ReadText(BinaryReader reader)
        {
            int size = reader.ReadInt32();
            if (size < 0 || size > 32768) throw new InvalidDataException("Invalid native catalog string length");
            byte[] data = reader.ReadBytes(size);
            if (data.Length != size) throw new EndOfStreamException();
            return new UTF8Encoding(false, true).GetString(data);
        }

        public static NativeTextureCatalog ReadLegacyCatalog(string path, TextureIndex index)
        {
            var result = new NativeTextureCatalog();
            string root = Path.GetDirectoryName(Path.GetFullPath(path));
            using (var reader = new BinaryReader(File.OpenRead(path)))
            {
                if (Encoding.ASCII.GetString(reader.ReadBytes(5)) != "NVTX1") throw new InvalidDataException("Invalid native catalog header");
                int count = reader.ReadInt32();
                if (count != index.Entries.Count) throw new InvalidDataException("Native catalog does not match this pack");
                for (int i = 0; i < count; i++)
                {
                    var e = new TextureEntry { Name = ReadText(reader), Path = ReadText(reader),
                        SourceBytes = reader.ReadInt64(), SourceWriteTicks = reader.ReadInt64(),
                        Offset = reader.ReadInt64(), Length = reader.ReadInt64(), Width = reader.ReadInt32(),
                        Height = reader.ReadInt32(), IsSrgb = reader.ReadBoolean() };
                    string hash = ReadText(reader), file = ReadText(reader);
                    if (hash.Length != 64) throw new InvalidDataException("Invalid content fingerprint");
                    foreach (char c in hash) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
                        throw new InvalidDataException("Invalid content fingerprint");
                    if (file != Path.GetFileName(file) || !file.EndsWith(".bundle", StringComparison.Ordinal))
                        throw new InvalidDataException("Invalid metadata bundle path");
                    var record = new NativeTextureRecord { Entry = e, Content = e.Width + ":" + e.Height + ":" + e.IsSrgb + ":" + hash,
                        BundlePath = Path.Combine(root, file) };
                    result.Records.Add(e.Name, record);
                    TextureEntry current; NativeTextureRecord matched;
                    if (!index.Entries.TryGetValue(e.Name, out current) || !result.TryMatch(current, out matched) || !File.Exists(record.BundlePath))
                        throw new InvalidDataException("Native metadata is stale or missing: " + e.Name);
                }
                if (reader.BaseStream.Position != reader.BaseStream.Length) throw new InvalidDataException("Trailing native catalog data");
            }
            return result;
        }
    }
}
