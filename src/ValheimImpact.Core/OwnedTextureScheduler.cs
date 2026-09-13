using System;
using System.Collections.Generic;
using System.Globalization;
using System.Threading;

namespace ValheimImpact.Core
{
    // All members run on the creating engine thread. A factory starts at most one
    // engine request and must return its handle after starting, even on later failure.
    public interface IOwnedTextureLoad<T> : IDisposable where T : class
    {
        bool IsDone { get; }
        bool IsReleased { get; }
        Exception Error { get; }
        // Never waits. Return true only when a new engine request was started.
        bool Pump(bool allowEngineStart);
        // Transfers exactly once after successful completion. Dispose preserves it.
        T Take();
        // Cancellation and disposal request draining; callers keep pumping until released.
        void Cancel();
    }

    public sealed class OwnedTextureRequest
    {
        public readonly OwnedTextureBundle Bundle;
        public readonly string Identity;
        public OwnedTextureRequest(OwnedTextureBundle bundle, string payloadSha256)
        {
            if (bundle == null) throw new ArgumentNullException(nameof(bundle));
            if (payloadSha256 == null || payloadSha256.Length != 64) throw new ArgumentException("Expected payload SHA256");
            foreach (char c in payloadSha256) if (!Uri.IsHexDigit(c)) throw new ArgumentException("Expected hexadecimal payload SHA256");
            Bundle = bundle;
            // The current owned build contract supports DXT5 with a full mip chain.
            Identity = payloadSha256.ToLowerInvariant() + ":DXT5:" + bundle.Width.ToString(CultureInfo.InvariantCulture) + ":" +
                bundle.Height.ToString(CultureInfo.InvariantCulture) + ":" + bundle.MipCount.ToString(CultureInfo.InvariantCulture) + ":" +
                (bundle.IsSrgb ? "srgb" : "linear") +
                (bundle.WrapMode == null
                    ? ":sampler-unknown:" + bundle.Sha256 + ":" + bundle.AssetName
                    : ":sampler:" + bundle.WrapMode + ":trilinear:aniso4:bias0");
        }
    }

    // Owns replacement textures only. A caller must restore bindings before releasing
    // the corresponding leases, including shutdown. Demand never invokes the engine.
    public sealed class OwnedTextureScheduler<T> : IDisposable where T : class
    {
        internal sealed class Job
        {
            internal OwnedTextureRequest Request;
            internal long Order;
            internal int References;
            internal double IdleSince;
            internal IOwnedTextureLoad<T> Load;
            internal T Value;
            internal bool Retiring, Cancelled, Failed, DisposeRequested;
        }
        public sealed class Lease : IDisposable
        {
            private OwnedTextureScheduler<T> owner;
            private readonly Job job;
            internal Lease(OwnedTextureScheduler<T> owner, Job job) { this.owner = owner; this.job = job; }
            public bool TryGet(out T texture)
            {
                texture = null;
                if (owner == null) return false;
                owner.CheckThread();
                if (job.Value == null || job.Retiring || job.Load != null) return false;
                texture = job.Value; return true;
            }
            public void Dispose()
            {
                if (owner == null) return;
                owner.CheckThread();
                job.References--; owner.LeaseCount--;
                if (job.References == 0) job.IdleSince = owner.now;
                owner = null;
            }
        }
        private readonly Dictionary<string, OwnedTextureRequest> catalog = new Dictionary<string, OwnedTextureRequest>(StringComparer.Ordinal);
        private readonly Dictionary<string, Job> jobs = new Dictionary<string, Job>(StringComparer.Ordinal);
        private readonly HashSet<string> previouslyLoaded = new HashSet<string>(StringComparer.Ordinal);
        private readonly List<Job> scratch = new List<Job>();
        private readonly Func<OwnedTextureBundle, IOwnedTextureLoad<T>> begin;
        private readonly Action<T> retire;
        private readonly Func<T, bool> isReleased;
        private readonly StreamingPolicy policy;
        private readonly int threadId;
        private long order, lastStartFrame = long.MinValue, lastFrame = long.MinValue;
        private double now;
        private bool stopping, ticking;
        public long PendingBytes { get; private set; }
        public long ResidentBytes { get; private set; }
        public long RetiringBytes { get; private set; }
        public long AllocatedBytes { get { return PendingBytes + ResidentBytes + RetiringBytes; } }
        public long PeakAllocatedBytes { get; private set; }
        public long PeakPendingBytes { get; private set; }
        public int ActiveCount { get; private set; }
        public int ResidentCount { get; private set; }
        public int RetiringCount { get; private set; }
        public int TrackedCount { get { return jobs.Count; } }
        public int LeaseCount { get; private set; }
        public int QueuedCount
        {
            get { int count = 0; foreach (Job j in jobs.Values) if (Queued(j)) count++; return count; }
        }
        public long StartedCount { get; private set; }
        public long EngineStartCount { get; private set; }
        public long CompletedCount { get; private set; }
        public long EvictedCount { get; private set; }
        public long ReloadedCount { get; private set; }
        public long CancelledCount { get; private set; }
        public long ErrorCount { get; private set; }
        public long RejectedCount { get; private set; }
        public string LastError { get; private set; }
        public bool IsStopping { get { return stopping; } }
        public bool IsDrained { get { return AllocatedBytes == 0 && QueuedCount == 0; } }

        public OwnedTextureScheduler(IEnumerable<KeyValuePair<string, OwnedTextureRequest>> catalog,
            Func<OwnedTextureBundle, IOwnedTextureLoad<T>> begin, Action<T> retire, Func<T, bool> isReleased,
            StreamingPolicy policy = null)
        {
            if (catalog == null || begin == null || retire == null || isReleased == null) throw new ArgumentNullException("scheduler dependency");
            this.begin = begin; this.retire = retire; this.isReleased = isReleased;
            this.policy = policy ?? StreamingPolicy.Balanced;
            threadId = Thread.CurrentThread.ManagedThreadId;
            foreach (var pair in catalog)
            {
                if (string.IsNullOrWhiteSpace(pair.Key) || pair.Value == null) throw new ArgumentException("Invalid catalog alias");
                this.catalog.Add(pair.Key, pair.Value);
            }
        }
        private void CheckThread()
        {
            if (Thread.CurrentThread.ManagedThreadId != threadId) throw new InvalidOperationException("Use the scheduler's creating engine thread");
        }
        private bool Queued(Job job)
        { return !stopping && job.References > 0 && !job.Failed && job.Value == null && job.Load == null; }

        public Lease Acquire(string alias)
        {
            CheckThread();
            OwnedTextureRequest request;
            if (stopping || alias == null || !catalog.TryGetValue(alias, out request) || LeaseCount >= policy.MaxLeases)
            { RejectedCount++; return null; }
            long bytes = request.Bundle.PayloadBytes;
            if (bytes > policy.ResidentBudgetBytes || bytes > policy.PendingBudgetBytes) { RejectedCount++; return null; }
            Job job;
            if (!jobs.TryGetValue(request.Identity, out job))
            {
                if (jobs.Count >= policy.MaxTrackedEntries) { RejectedCount++; return null; }
                job = new Job { Request = request, Order = order++, IdleSince = now };
                jobs.Add(request.Identity, job);
            }
            job.References++; LeaseCount++;
            return new Lease(this, job);
        }
        private void Failure(Job job, Exception error)
        {
            if (!job.Failed) { ErrorCount++; LastError = error.Message; }
            job.Failed = true;
        }
        private void Cancel(Job job)
        {
            if (job.Cancelled) return;
            // The handle remains retained and budgeted until its release acknowledgement.
            job.Load.Cancel(); job.Cancelled = true; CancelledCount++;
        }
        private void Pump(Job job, long frame)
        {
            if (stopping || job.References == 0 || job.Failed) Cancel(job);
            bool permitted = !job.Cancelled && lastStartFrame != frame;
            if (job.Load.Pump(permitted))
            {
                lastStartFrame = frame; EngineStartCount++;
                if (!permitted) throw new InvalidOperationException("Load provider exceeded its engine start permission");
            }
            if (job.Load.Error != null) { Failure(job, job.Load.Error); Cancel(job); }
            if (job.Load.IsDone && !job.Cancelled && !job.DisposeRequested)
            {
                job.Value = job.Load.Take();
                if (job.Value == null) throw new InvalidOperationException("Owned load returned no texture");
                job.DisposeRequested = true;
                job.Load.Dispose();
            }
            if (!job.Load.IsReleased) return;
            PendingBytes -= job.Request.Bundle.PayloadBytes; ActiveCount--; job.Load = null;
            job.Cancelled = false; job.DisposeRequested = false;
            if (job.Value != null)
            {
                ResidentBytes += job.Request.Bundle.PayloadBytes; ResidentCount++; CompletedCount++;
                if (!previouslyLoaded.Add(job.Request.Identity)) ReloadedCount++;
                job.IdleSince = now;
            }
        }
        private void Sweep(Job job)
        {
            long bytes = job.Request.Bundle.PayloadBytes;
            if (job.Retiring)
            {
                if (!isReleased(job.Value)) return;
                RetiringBytes -= bytes; RetiringCount--; job.Retiring = false; job.Value = null;
            }
            if (job.Value != null && job.Load == null && job.References == 0 && (stopping || now - job.IdleSince >= policy.IdleSeconds))
            {
                retire(job.Value);
                job.Retiring = true; ResidentCount--; ResidentBytes -= bytes;
                RetiringCount++; RetiringBytes += bytes; EvictedCount++;
            }
            if (job.Load == null && job.Value == null && job.References == 0) jobs.Remove(job.Request.Identity);
        }
        public void Tick(long frame, double nowSeconds)
        {
            CheckThread();
            if (ticking) throw new InvalidOperationException("Owned scheduler Tick cannot reenter");
            if (frame < lastFrame || nowSeconds < now || double.IsNaN(nowSeconds) || double.IsInfinity(nowSeconds))
                throw new ArgumentOutOfRangeException("Monotonic frame and time are required");
            ticking = true; now = nowSeconds; lastFrame = frame;
            try
            {
                scratch.Clear(); scratch.AddRange(jobs.Values);
                foreach (Job job in scratch)
                {
                    try { if (job.Load != null) Pump(job, frame); Sweep(job); }
                    catch (Exception error)
                    {
                        Failure(job, error);
                        // Do not forget a handle or decrement reservations on a provider failure.
                        // A later pump may still acknowledge release.
                        if (job.Load != null) { try { Cancel(job); } catch (Exception) { } }
                    }
                }
                if (stopping || lastStartFrame == frame || ActiveCount >= policy.MaxConcurrentLoads) return;
                Job next = null;
                foreach (Job job in jobs.Values)
                {
                    long bytes = job.Request.Bundle.PayloadBytes;
                    if (Queued(job) && bytes <= policy.PendingBudgetBytes - PendingBytes &&
                        bytes <= policy.ResidentBudgetBytes - AllocatedBytes && (next == null || job.Order < next.Order)) next = job;
                }
                if (next == null) return;
                lastStartFrame = frame; EngineStartCount++;
                long size = next.Request.Bundle.PayloadBytes;
                PendingBytes += size; ActiveCount++;
                PeakPendingBytes = Math.Max(PeakPendingBytes, PendingBytes);
                PeakAllocatedBytes = Math.Max(PeakAllocatedBytes, AllocatedBytes);
                try
                {
                    next.Load = begin(next.Request.Bundle);
                    if (next.Load == null) throw new InvalidOperationException("Owned load factory returned no handle");
                    StartedCount++;
                }
                catch (Exception error)
                {
                    // A factory that throws must not have orphaned an engine request.
                    PendingBytes -= size; ActiveCount--; Failure(next, error);
                }
            }
            finally { scratch.Clear(); ticking = false; }
        }
        public void Stop() { CheckThread(); stopping = true; }
        public void Dispose() { Stop(); }
    }
}
