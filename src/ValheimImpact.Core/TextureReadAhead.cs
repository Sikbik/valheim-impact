using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace ValheimImpact.Core
{
    public sealed class PreparedTexture
    {
        public byte[] Bytes;
        public string Content;
        public double ReadMs, HashMs, WaitMs;
        public bool Waited;

        public static void Validate(TextureEntry entry)
        {
            using (var stream = File.OpenRead(entry.Path)) Validate(entry, stream);
        }

        private static void Validate(TextureEntry entry, FileStream stream)
        {
            if (stream.Length != entry.SourceBytes || File.GetLastWriteTimeUtc(entry.Path).Ticks != entry.SourceWriteTicks)
                throw new InvalidDataException("Texture bundle changed while running; restart after updating the pack: " + entry.Path);
        }

        public static PreparedTexture Read(TextureEntry entry, string knownContent, Func<byte[], string> fingerprint)
        {
            var result = new PreparedTexture();
            var timer = Stopwatch.StartNew();
            using (var stream = File.OpenRead(entry.Path))
            {
                Validate(entry, stream);
                result.Bytes = new byte[checked((int)entry.Length)];
                stream.Position = entry.Offset;
                int filled = 0;
                while (filled < result.Bytes.Length)
                {
                    int n = stream.Read(result.Bytes, filled, result.Bytes.Length - filled);
                    if (n == 0) throw new InvalidDataException("Truncated texture payload: " + entry.Name);
                    filled += n;
                }
                Validate(entry, stream);
            }
            result.ReadMs = timer.Elapsed.TotalMilliseconds;
            timer.Restart();
            result.Content = knownContent ?? (entry.Width + ":" + entry.Height + ":" + entry.IsSrgb + ":" + fingerprint(result.Bytes));
            result.HashMs = knownContent == null ? timer.Elapsed.TotalMilliseconds : 0;
            return result;
        }
    }

    // Only immutable bundle metadata, byte arrays and fingerprints cross to the worker.
    // Main-thread consumers never wait behind a different queued texture.
    public sealed class TextureReadAhead : IDisposable
    {
        private sealed class Job
        {
            internal TextureEntry Entry;
            internal string KnownContent;
            internal LinkedListNode<Job> Node;
            internal int State; // 0 queued, 1 reading, 2 complete (including errors)
            internal double Created, Priority;
            internal PreparedTexture Result;
            internal Exception Error;
        }
        private readonly object gate = new object();
        private readonly Dictionary<TextureEntry, Job> jobs = new Dictionary<TextureEntry, Job>();
        private readonly LinkedList<Job> queue = new LinkedList<Job>();
        private readonly Dictionary<TextureEntry, string> completedFingerprints = new Dictionary<TextureEntry, string>();
        private readonly Dictionary<TextureEntry, double> retryAfter = new Dictionary<TextureEntry, double>();
        private readonly long budget;
        private readonly Func<byte[], string> fingerprint;
        private readonly Func<double> clock;
        private bool worker, disposed;
        private long reserved, peak;
        private int readyHits, waitHits, errors, expired, preempted, rejected;
        public long ReservedBytes { get { lock (gate) return reserved; } }
        public long PeakBytes { get { lock (gate) return peak; } }
        public int Preempted { get { lock (gate) return preempted; } }
        public int Rejected { get { lock (gate) return rejected; } }
        public int ReadyHits { get { lock (gate) return readyHits; } }
        public int WaitHits { get { lock (gate) return waitHits; } }
        public int Errors { get { lock (gate) return errors; } }
        public int Expired { get { lock (gate) return expired; } }
        public int ReadyCount
        {
            get { lock (gate) { int n = 0; foreach (var j in jobs.Values) if (j.State == 2) n++; return n; } }
        }

        public TextureReadAhead(long budget, Func<byte[], string> fingerprint = null, Func<double> clock = null)
        {
            if (budget <= 0) throw new ArgumentOutOfRangeException("budget");
            this.budget = budget;
            this.fingerprint = fingerprint ?? Fingerprint.Hex;
            this.clock = clock ?? (() => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency);
        }

        public bool Offer(TextureEntry entry, string knownContent, double priority = 1)
        {
            lock (gate)
            {
                ExpireLocked();
                if (disposed) return false;
                Job pending;
                if (jobs.TryGetValue(entry, out pending))
                { pending.Priority = Math.Min(pending.Priority, priority); return true; }
                double retry;
                if (priority >= 1000000 && retryAfter.TryGetValue(entry, out retry) && clock() < retry) return false;
                if (entry.Length <= 0 || entry.Length > budget) { rejected++; return false; }
                if (entry.Length > budget - reserved)
                {
                    var victims = new List<Job>();
                    long possible = budget - reserved;
                    foreach (var candidate in jobs.Values)
                        if (candidate.State != 1 && candidate.Priority > priority)
                        { victims.Add(candidate); possible += candidate.Entry.Length; }
                    if (possible < entry.Length) { rejected++; return false; }
                    victims.Sort((a, b) => b.Priority.CompareTo(a.Priority));
                    foreach (var victim in victims)
                    {
                        if (entry.Length <= budget - reserved) break;
                        Remove(victim); preempted++;
                    }
                }
                if (knownContent == null) completedFingerprints.TryGetValue(entry, out knownContent);
                var job = new Job { Entry = entry, KnownContent = knownContent, Created = clock(), Priority = priority };
                job.Node = queue.AddLast(job);
                jobs.Add(entry, job);
                reserved += entry.Length;
                peak = Math.Max(peak, reserved);
                if (!worker)
                {
                    worker = true;
                    Task.Run((Action)Pump);
                }
                return true;
            }
        }

        private void Pump()
        {
            while (true)
            {
                Job job;
                lock (gate)
                {
                    if (queue.Count == 0 || disposed)
                    { worker = false; Monitor.PulseAll(gate); return; }
                    job = queue.First.Value;
                    foreach (var queued in queue) if (queued.Priority < job.Priority) job = queued;
                    queue.Remove(job.Node);
                    job.Node = null;
                    job.State = 1;
                }
                PreparedTexture result = null;
                Exception error = null;
                try { result = PreparedTexture.Read(job.Entry, job.KnownContent, fingerprint); }
                catch (Exception ex) { error = ex; }
                lock (gate)
                {
                    job.Result = result;
                    job.Error = error;
                    job.State = 2;
                    if (result != null) completedFingerprints[job.Entry] = result.Content;
                    if (error != null) errors++;
                    if (disposed) Remove(job);
                    Monitor.PulseAll(gate);
                }
            }
        }

        public bool Take(TextureEntry entry, out PreparedTexture result)
        {
            result = null;
            Job job;
            lock (gate)
            {
                if (disposed || !jobs.TryGetValue(entry, out job)) return false;
                if (job.State == 0) { Remove(job); return false; }
                bool waited = job.State == 1;
                if (waited) waitHits++; else readyHits++;
                var timer = Stopwatch.StartNew();
                while (job.State == 1) Monitor.Wait(gate);
                result = job.Result;
                Remove(job);
                if (job.Error != null) throw new IOException("Texture preparation failed: " + entry.Name, job.Error);
                result.Waited = waited;
                result.WaitMs = waited ? timer.Elapsed.TotalMilliseconds : 0;
            }
            // Also detect a replacement after the worker completed but before demand.
            PreparedTexture.Validate(entry);
            return true;
        }

        private void Remove(Job job)
        {
            if (!jobs.Remove(job.Entry)) return;
            if (job.Node != null) { queue.Remove(job.Node); job.Node = null; }
            reserved -= job.Entry.Length;
            job.Result = null;
        }

        private void ExpireLocked()
        {
            double now = clock();
            List<Job> stale = null;
            foreach (var job in jobs.Values)
                if (job.State != 1 && now - job.Created >= 10)
                { if (stale == null) stale = new List<Job>(); stale.Add(job); }
            if (stale != null) foreach (var job in stale)
            {
                if (job.Priority >= 1000000) retryAfter[job.Entry] = now + 30;
                Remove(job); expired++;
            }
        }
        public void Expire() { lock (gate) ExpireLocked(); }

        public void Dispose()
        {
            lock (gate)
            {
                disposed = true;
                foreach (var job in new List<Job>(jobs.Values)) if (job.State != 1) Remove(job);
                // The sole worker finishes its active file read before releasing its reservation.
                while (worker) Monitor.Wait(gate);
                completedFingerprints.Clear(); retryAfter.Clear();
            }
        }
    }
}
