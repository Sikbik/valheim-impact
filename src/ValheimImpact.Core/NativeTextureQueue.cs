using System;
using System.Collections.Generic;

namespace ValheimImpact.Core
{
    public interface ITextureSource<T> where T : class
    {
        bool TryGetContent(TextureEntry entry, out string content);
        bool Prefetch(TextureEntry entry, double priority);
        T Load(TextureEntry entry, out string mode);
    }
    public interface ITextureLoad<T> : IDisposable where T : class
    {
        bool Ready { get; }
        T Complete();
    }

    // Unity calls and ownership transitions run on the main thread. Source bytes are
    // streamed by the engine. The queue never holds managed texture payloads.
    public sealed class NativeTextureQueue<T> : ITextureSource<T>, IDisposable where T : class
    {
        private sealed class Job
        {
            internal NativeTextureRecord Record;
            internal double Created, Priority;
            internal ITextureLoad<T> Load;
            internal T Value;
        }
        private struct Retired { internal long Bytes; internal int Frame; }
        private readonly NativeTextureCatalog catalog;
        private readonly long budget;
        private readonly Func<NativeTextureRecord, bool, ITextureLoad<T>> begin;
        private readonly Action<T> destroy;
        private readonly Func<double> clock;
        private readonly Func<int> frame;
        private readonly Action<TextureEntry> validate;
        private readonly Action<string> error;
        private readonly Dictionary<string, Job> jobs = new Dictionary<string, Job>(StringComparer.Ordinal);
        private readonly HashSet<string> failed = new HashSet<string>(StringComparer.Ordinal);
        private readonly Dictionary<string, double> retryAfter = new Dictionary<string, double>(StringComparer.Ordinal);
        private readonly List<Retired> retired = new List<Retired>();
        private readonly List<Job> scratch = new List<Job>();
        private bool disposed;
        private int lastStartFrame = -1;
        public long ReservedBytes { get; private set; }
        public long PeakBytes { get; private set; }
        public int ReadyHits { get; private set; }
        public int UrgentHits { get; private set; }
        public int SyncLoads { get; private set; }
        public int Errors { get; private set; }
        public int Expired { get; private set; }
        public int Preempted { get; private set; }
        public int Rejected { get; private set; }
        public int ActiveCount { get { int n = 0; foreach (Job job in jobs.Values) if (job.Load != null) n++; return n; } }
        public NativeTextureQueue(NativeTextureCatalog catalog, long budget,
            Func<NativeTextureRecord, bool, ITextureLoad<T>> begin, Action<T> destroy,
            Func<double> clock, Func<int> frame, Action<TextureEntry> validate = null, Action<string> error = null)
        {
            if (budget <= 0) throw new ArgumentOutOfRangeException("budget");
            this.catalog = catalog; this.budget = budget; this.begin = begin; this.destroy = destroy;
            this.clock = clock; this.frame = frame; this.validate = validate ?? (entry => PreparedTexture.Validate(entry)); this.error = error;
        }

        public bool TryGetContent(TextureEntry entry, out string content)
        {
            NativeTextureRecord record;
            bool match = catalog.TryMatch(entry, out record);
            content = match ? record.Content : null;
            return match;
        }

        public bool Prefetch(TextureEntry entry, double priority)
        {
            NativeTextureRecord record;
            if (disposed || !catalog.TryMatch(entry, out record) || failed.Contains(record.Content)) return false;
            Job pending;
            if (jobs.TryGetValue(record.Content, out pending))
            { pending.Priority = Math.Min(pending.Priority, priority); return true; }
            double retry;
            if (priority >= 1000000 && retryAfter.TryGetValue(record.Content, out retry) && clock() < retry) return false;
            if (entry.Length <= 0 || entry.Length > budget) { Rejected++; return false; }
            if (entry.Length > budget - ReservedBytes)
            {
                var victims = new List<Job>(); long possible = budget - ReservedBytes;
                foreach (Job candidate in jobs.Values)
                    if (candidate.Load == null && candidate.Priority > priority)
                    { victims.Add(candidate); possible += candidate.Record.Entry.Length; }
                if (possible < entry.Length) { Rejected++; return false; }
                victims.Sort((a, b) => b.Priority.CompareTo(a.Priority));
                foreach (Job victim in victims)
                {
                    if (entry.Length <= budget - ReservedBytes) break;
                    Discard(victim); Preempted++;
                }
                // GPU destruction is deferred. A later offer can claim its reservation.
                if (entry.Length > budget - ReservedBytes) { Rejected++; return false; }
            }
            jobs.Add(record.Content, new Job { Record = record, Created = clock(), Priority = priority });
            ReservedBytes += entry.Length; PeakBytes = Math.Max(PeakBytes, ReservedBytes);
            return true;
        }

        public T Load(TextureEntry entry, out string mode)
        {
            mode = "native-sync";
            NativeTextureRecord record;
            if (disposed || !catalog.TryMatch(entry, out record) || failed.Contains(record.Content)) return null;
            validate(entry);
            Job job;
            bool reserved = jobs.TryGetValue(record.Content, out job);
            if (!reserved) job = new Job { Record = record };
            try
            {
                if (job.Value != null) { ReadyHits++; mode = "native-ready"; }
                else
                {
                    if (job.Load != null) { UrgentHits++; mode = "native-urgent"; }
                    else { SyncLoads++; job.Load = begin(record, false); }
                    Finish(job);
                }
                validate(entry);
                T result = job.Value;
                if (reserved) { jobs.Remove(record.Content); ReservedBytes -= job.Record.Entry.Length; }
                job.Value = null; // Ownership transfers to FullResolutionCache.
                return result;
            }
            catch (Exception ex)
            {
                Failure(job, ex);
                if (reserved) Discard(job); else Cleanup(job);
                return null;
            }
        }

        private void Finish(Job job)
        {
            job.Value = job.Load.Complete();
            if (job.Value == null) throw new InvalidOperationException("Native texture request returned null");
            job.Load.Dispose(); job.Load = null;
        }

        public void Tick()
        {
            if (disposed) return;
            int currentFrame = frame();
            for (int i = retired.Count - 1; i >= 0; i--)
                if (currentFrame >= retired[i].Frame) { ReservedBytes -= retired[i].Bytes; retired.RemoveAt(i); }
            scratch.Clear(); scratch.AddRange(jobs.Values);
            foreach (Job job in scratch)
            {
                try
                {
                    if (job.Load != null && job.Load.Ready) Finish(job);
                    if (job.Load == null && clock() - job.Created >= 10)
                    {
                        if (job.Priority >= 1000000) retryAfter[job.Record.Content] = clock() + 30;
                        Discard(job); Expired++;
                    }
                }
                catch (Exception ex) { Failure(job, ex); Discard(job); }
            }
            if (lastStartFrame == currentFrame || ActiveCount >= 2) return;
            Job next = null;
            foreach (Job job in jobs.Values)
                if (job.Value == null && job.Load == null && (next == null || job.Priority < next.Priority)) next = job;
            if (next == null) return;
            lastStartFrame = currentFrame;
            try { validate(next.Record.Entry); next.Load = begin(next.Record, true); }
            catch (Exception ex) { Failure(next, ex); Discard(next); }
        }

        private void Failure(Job job, Exception ex)
        {
            failed.Add(job.Record.Content); Errors++;
            if (error != null) error("Native texture failed; raw loading retained for " + job.Record.Entry.Name + ": " + ex);
        }
        private void Cleanup(Job job)
        {
            if (job.Load != null) { job.Load.Dispose(); job.Load = null; }
            if (job.Value != null) { destroy(job.Value); job.Value = null; }
        }
        private void Discard(Job job)
        {
            if (!jobs.Remove(job.Record.Content)) return;
            bool allocated = job.Load != null || job.Value != null;
            Cleanup(job);
            if (allocated) retired.Add(new Retired { Bytes = job.Record.Entry.Length, Frame = frame() + 2 });
            else ReservedBytes -= job.Record.Entry.Length;
        }
        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            foreach (Job job in jobs.Values) Cleanup(job);
            jobs.Clear(); retired.Clear(); retryAfter.Clear(); failed.Clear(); ReservedBytes = 0;
        }
    }
}
