using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace ValheimImpact.Core
{
    public sealed class TextureEntry
    {
        public string Name, Path;
        public int Width, Height;
        public bool IsSrgb;
        public long Offset, Length, SourceBytes, SourceWriteTicks;
    }

    public sealed class TextureIndex
    {
        public readonly Dictionary<string, TextureEntry> Entries = new Dictionary<string, TextureEntry>(StringComparer.Ordinal);
        public int SkippedEntries, SupersededEntries;

        public static bool IsPowerOfTwo(int n) { return n > 0 && (n & (n - 1)) == 0; }

        public static long Dxt5Bytes(int width, int height)
        {
            if (width <= 0 || height <= 0) throw new ArgumentOutOfRangeException();
            long total = 0;
            while (true)
            {
                total = checked(total + (long)Math.Max(1, (width + 3) / 4) * Math.Max(1, (height + 3) / 4) * 16);
                if (width == 1 && height == 1) return total;
                width = Math.Max(1, width / 2); height = Math.Max(1, height / 2);
            }
        }

        public static TextureIndex ReadLegacyBvtb(IEnumerable<string> paths)
        {
            var result = new TextureIndex();
            foreach (string path in paths)
            {
                try
                {
                    using (var stream = File.OpenRead(path))
                    using (var reader = new BinaryReader(stream))
                    {
                        if (Encoding.ASCII.GetString(reader.ReadBytes(5)) != "BVTB\0")
                            throw new InvalidDataException("Invalid texture bundle header: " + path);
                        long sourceWriteTicks = File.GetLastWriteTimeUtc(path).Ticks;
                        int count = reader.ReadInt32();
                        if (count < 0 || count > 100000) throw new InvalidDataException("Invalid texture count");
                        var bundleEntries = new List<TextureEntry>();
                        for (int i = 0; i < count; i++)
                        {
                            var chars = new List<byte>();
                            byte b;
                            while ((b = reader.ReadByte()) != 0)
                            {
                                chars.Add(b);
                                if (chars.Count > 4096) throw new InvalidDataException("Unterminated texture name");
                            }
                            var entry = new TextureEntry {
                                Name = Encoding.UTF8.GetString(chars.ToArray()), Path = path,
                                Width = reader.ReadInt32(), Height = reader.ReadInt32(), IsSrgb = reader.ReadBoolean(),
                                Offset = reader.ReadInt64(), Length = reader.ReadInt64(),
                                SourceBytes = stream.Length, SourceWriteTicks = sourceWriteTicks
                            };
                            if (entry.Offset < 0 || entry.Length < 0 || entry.Length > int.MaxValue ||
                                entry.Offset > stream.Length || entry.Length > stream.Length - entry.Offset)
                                throw new InvalidDataException("Texture exceeds bundle bounds: " + entry.Name);
                            bundleEntries.Add(entry);
                        }
                        if (File.GetLastWriteTimeUtc(path).Ticks != sourceWriteTicks)
                            throw new InvalidDataException("Texture bundle changed during indexing: " + path);
                        foreach (TextureEntry entry in bundleEntries)
                        {
                            if (entry.Offset < stream.Position) throw new InvalidDataException("Texture overlaps directory");
                            if (!IsPowerOfTwo(entry.Width) || !IsPowerOfTwo(entry.Height))
                            { result.SkippedEntries++; continue; }
                            if (entry.Length != Dxt5Bytes(entry.Width, entry.Height))
                                throw new InvalidDataException("Incomplete DXT5 mip chain: " + entry.Name);
                            if (result.Entries.ContainsKey(entry.Name)) result.SupersededEntries++;
                            result.Entries[entry.Name] = entry;
                        }
                    }
                }
                catch (EndOfStreamException ex) { throw new InvalidDataException("Truncated texture bundle: " + path, ex); }
            }
            return result;
        }
    }
}
