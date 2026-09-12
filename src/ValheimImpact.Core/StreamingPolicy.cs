using System;

namespace ValheimImpact.Core
{
    // Component payload limits, not total VRAM or system RAM limits.
    public sealed class StreamingPolicy
    {
        public readonly long ResidentBudgetBytes, PendingBudgetBytes;
        public readonly int MaxConcurrentLoads, MaxTrackedEntries, MaxLeases;
        public readonly double IdleSeconds;
        public const int MaxStartsPerFrame = 1;
        private const long MiB = 1024 * 1024;
        public static StreamingPolicy Compact { get { return new StreamingPolicy(384 * MiB, 32 * MiB, 1); } }
        public static StreamingPolicy Balanced { get { return new StreamingPolicy(768 * MiB, 64 * MiB, 2); } }
        public static StreamingPolicy High { get { return new StreamingPolicy(1536 * MiB, 128 * MiB, 2); } }
        public StreamingPolicy(long residentBudgetBytes, long pendingBudgetBytes, int maxConcurrentLoads,
            double idleSeconds = 60, int maxTrackedEntries = 256, int maxLeases = 4096)
        {
            if (residentBudgetBytes <= 0 || pendingBudgetBytes <= 0 || maxConcurrentLoads <= 0 ||
                idleSeconds < 0 || double.IsNaN(idleSeconds) || double.IsInfinity(idleSeconds) ||
                maxTrackedEntries <= 0 || maxLeases <= 0) throw new ArgumentOutOfRangeException("policy");
            ResidentBudgetBytes = residentBudgetBytes; PendingBudgetBytes = pendingBudgetBytes;
            MaxConcurrentLoads = maxConcurrentLoads; IdleSeconds = idleSeconds;
            MaxTrackedEntries = maxTrackedEntries; MaxLeases = maxLeases;
        }
    }
}
