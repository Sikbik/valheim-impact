using System;
using ValheimImpact.Core;
internal static class FrameTimingTests
{
    internal static void Run(Action<bool, string> check)
    {
        var timing = new FrameTimeWindow(4);
        timing.AddSeconds(0.001); timing.AddSeconds(0.002); timing.AddSeconds(0.003); timing.AddSeconds(0.004);
        var s = timing.Summarize();
        check(s.Count == 4 && s.P50Ms == 2 && s.P95Ms == 4 && s.P99Ms == 4 && s.MaxMs == 4,
            "frame summary uses nearest-rank percentiles and milliseconds");
        timing.AddSeconds(0.005); s = timing.Summarize();
        check(s.Count == 4 && s.Observed == 5 && s.P50Ms == 3 && s.MaxMs == 5,
            "bounded frame window retains newest samples and total observed count");
        timing.AddSeconds(double.NaN); timing.AddSeconds(-1); timing.AddSeconds(double.PositiveInfinity);
        check(timing.Summarize().Observed == 5, "invalid frame deltas are rejected from timing evidence");
    }
}
