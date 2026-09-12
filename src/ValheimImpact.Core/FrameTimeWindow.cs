using System;
namespace ValheimImpact.Core
{
    public sealed class FrameTimeSummary
    {
        public int Count;
        public long Observed;
        public double P50Ms, P95Ms, P99Ms, MaxMs;
    }

    // Single-threaded fixed-size ring. Adding a sample performs no allocation or IO.
    public sealed class FrameTimeWindow
    {
        private readonly double[] samples;
        private int next, count;
        private long observed;
        public FrameTimeWindow(int capacity = 4096)
        {
            if (capacity < 1 || capacity > 65536) throw new ArgumentOutOfRangeException(nameof(capacity));
            samples = new double[capacity];
        }
        public void AddSeconds(double seconds)
        {
            if (double.IsNaN(seconds) || double.IsInfinity(seconds) || seconds < 0 || seconds > double.MaxValue / 1000) return;
            samples[next] = seconds * 1000;
            next = (next + 1) % samples.Length;
            count = Math.Min(count + 1, samples.Length); observed++;
        }
        public FrameTimeSummary Summarize()
        {
            var result = new FrameTimeSummary { Count = count, Observed = observed };
            if (count == 0) return result;
            var sorted = new double[count]; Array.Copy(samples, sorted, count); Array.Sort(sorted);
            result.P50Ms = sorted[(int)Math.Ceiling(count * 0.50) - 1];
            result.P95Ms = sorted[(int)Math.Ceiling(count * 0.95) - 1];
            result.P99Ms = sorted[(int)Math.Ceiling(count * 0.99) - 1];
            result.MaxMs = sorted[count - 1];
            return result;
        }
    }
}
