using System;
using System.Collections.Generic;

namespace ValheimImpact.Core
{
    public sealed class EvictionScan<T> where T : class
    {
        private readonly long revision;
        public readonly HashSet<T> Protected = new HashSet<T>();
        public EvictionScan(long revision) { this.revision = revision; }
        public int Complete(long currentRevision, FullResolutionCache<T> cache, double now, double grace,
            Func<T, IList<string>, bool> release)
        {
            if (revision != currentRevision) return -1;
            foreach (T resource in Protected) cache.Observe(resource, now);
            return cache.Sweep(now, grace, release);
        }
    }
}
