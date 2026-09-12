using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;

namespace ValheimImpact.Core
{
    public sealed class FullResolutionCache<T> where T : class
    {
        private sealed class Resource
        {
            internal T Value;
            internal string Content;
            internal readonly List<string> Names = new List<string>();
            internal long Bytes;
            internal double LastUsed;
            internal bool Pinned;
        }
        private sealed class Identity : IEqualityComparer<T>
        {
            public bool Equals(T a, T b) { return ReferenceEquals(a, b); }
            public int GetHashCode(T value) { return RuntimeHelpers.GetHashCode(value); }
        }
        private readonly TextureIndex index;
        private readonly Func<double> clock;
        private readonly Func<byte[], string> fingerprint;
        private readonly TextureReadAhead readAhead;
        private readonly ITextureSource<T> source;
        public string LastPreparation { get; private set; }
        public double LastWaitMs { get; private set; }
        private readonly Dictionary<string, string> fingerprints = new Dictionary<string, string>(StringComparer.Ordinal);
        public int FingerprintsComputed { get; private set; }
        public double LastReadMs { get; private set; }
        public double LastHashMs { get; private set; }
        public double LastUploadMs { get; private set; }
        private readonly Dictionary<string, Resource> byName = new Dictionary<string, Resource>(StringComparer.Ordinal);
        private readonly Dictionary<string, Resource> byContent = new Dictionary<string, Resource>(StringComparer.Ordinal);
        private readonly Dictionary<T, Resource> byResource = new Dictionary<T, Resource>(new Identity());
        private readonly HashSet<string> uploadedContent = new HashSet<string>(StringComparer.Ordinal);
        public int UploadCount { get; private set; }
        public int ReuseCount { get; private set; }
        public int ReloadCount { get; private set; }
        public int EvictionCount { get; private set; }
        public int ResidentCount { get { return byContent.Count; } }
        public long ResidentBytes { get; private set; }
        public FullResolutionCache(TextureIndex index) : this(index, () => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency) { }
        public FullResolutionCache(TextureIndex index, Func<double> clock) : this(index, clock, Fingerprint.Hex) { }
        public FullResolutionCache(TextureIndex index, Func<double> clock, Func<byte[], string> fingerprint)
            : this(index, clock, fingerprint, null) { }
        public FullResolutionCache(TextureIndex index, Func<double> clock, Func<byte[], string> fingerprint, TextureReadAhead readAhead,
            ITextureSource<T> source = null)
        { this.index = index; this.clock = clock; this.fingerprint = fingerprint; this.readAhead = readAhead; this.source = source; }

        public bool Prefetch(string name, double priority = 1)
        {
            TextureEntry entry;
            if (byName.ContainsKey(name) || !index.Entries.TryGetValue(name, out entry)) return false;
            string known;
            fingerprints.TryGetValue(name, out known);
            if (known == null && source != null) source.TryGetContent(entry, out known);
            if (known != null && byContent.ContainsKey(known)) return false;
            if (source != null) return source.Prefetch(entry, priority);
            return readAhead != null && readAhead.Offer(entry, known, priority);
        }

        public bool Contains(T value) { return value != null && byResource.ContainsKey(value); }
        public long BytesFor(T value) { Resource r; return value != null && byResource.TryGetValue(value, out r) ? r.Bytes : 0; }
        public bool IsPinned(T value) { Resource r; return value != null && byResource.TryGetValue(value, out r) && r.Pinned; }
        public void Pin(T value) { Resource r; if (value != null && byResource.TryGetValue(value, out r)) r.Pinned = true; }
        public void Observe(T value, double now)
        { Resource r; if (value != null && byResource.TryGetValue(value, out r)) r.LastUsed = Math.Max(now, r.LastUsed); }
        public List<T> Snapshot() { return new List<T>(byResource.Keys); }

        public T Get(string name, Func<TextureEntry, byte[], T> create)
        {
            LastReadMs = LastHashMs = LastUploadMs = LastWaitMs = 0;
            LastPreparation = "resident";
            Resource existing;
            if (byName.TryGetValue(name, out existing))
            { existing.LastUsed = clock(); return existing.Value; }
            TextureEntry entry = index.Entries[name];
            string content;
            bool known = fingerprints.TryGetValue(name, out content);
            if (!known && source != null && source.TryGetContent(entry, out content))
            { fingerprints.Add(name, content); known = true; }
            if (known && byContent.TryGetValue(content, out existing))
            {
                PreparedTexture.Validate(entry);
                existing.LastUsed = clock();
                existing.Names.Add(name);
                byName.Add(name, existing);
                ReuseCount++;
                return existing.Value;
            }
            if (source != null && known)
            {
                PreparedTexture.Validate(entry);
                var nativeTimer = Stopwatch.StartNew();
                string mode;
                T native = source.Load(entry, out mode);
                if (native != null)
                {
                    LastPreparation = mode; LastUploadMs = nativeTimer.Elapsed.TotalMilliseconds;
                    return Adopt(name, entry, content, native);
                }
            }
            PreparedTexture prepared;
            if (readAhead != null && readAhead.Take(entry, out prepared))
                LastPreparation = prepared.Waited ? "wait" : "ready";
            else
            {
                prepared = PreparedTexture.Read(entry, known ? content : null, fingerprint);
                LastPreparation = "sync";
            }
            byte[] bytes = prepared.Bytes;
            LastReadMs = prepared.ReadMs;
            LastHashMs = prepared.HashMs;
            LastWaitMs = prepared.WaitMs;
            content = prepared.Content;
            if (!known) { fingerprints.Add(name, content); FingerprintsComputed++; }
            var timer = Stopwatch.StartNew();
            if (!byContent.TryGetValue(content, out existing))
            {
                timer.Restart();
                T value = create(entry, bytes);
                LastUploadMs = timer.Elapsed.TotalMilliseconds;
                return Adopt(name, entry, content, value);
            }
            else ReuseCount++;
            existing.LastUsed = clock();
            existing.Names.Add(name);
            byName.Add(name, existing);
            return existing.Value;
        }

        private T Adopt(string name, TextureEntry entry, string content, T value)
        {
            if (value == null) throw new InvalidOperationException("Texture factory returned null: " + name);
            var resource = new Resource { Value = value, Content = content, Bytes = entry.Length, LastUsed = clock() };
            resource.Names.Add(name);
            byContent.Add(content, resource); byResource.Add(value, resource); byName.Add(name, resource);
            if (!uploadedContent.Add(content)) ReloadCount++;
            UploadCount++; ResidentBytes += entry.Length;
            return value;
        }

        // The caller first protects observed uses, then restores external references in release.
        // A veto or exception leaves this allocation and all its aliases owned by the cache.
        public int Sweep(double now, double graceSeconds, Func<T, IList<string>, bool> release)
        {
            if (graceSeconds < 0) throw new ArgumentOutOfRangeException("graceSeconds");
            var candidates = new List<Resource>(byContent.Values);
            candidates.Sort((a, b) => a.LastUsed.CompareTo(b.LastUsed));
            int count = 0;
            foreach (Resource r in candidates)
            {
                if (r.Pinned || now - r.LastUsed < graceSeconds) continue;
                if (!release(r.Value, r.Names.AsReadOnly())) continue;
                foreach (string name in r.Names) byName.Remove(name);
                byContent.Remove(r.Content);
                byResource.Remove(r.Value);
                ResidentBytes -= r.Bytes;
                EvictionCount++;
                count++;
            }
            return count;
        }
    }
}
