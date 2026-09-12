using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using ValheimImpact.Core;

internal static class CoreTests
{
    private static int failures;
    private static void Check(bool condition, string name)
    {
        Console.WriteLine((condition ? "PASS " : "FAIL ") + name);
        if (!condition) failures++;
    }

    private static string Bundle(string dir, string file, string name, byte fill, bool linear)
    {
        string path = Path.Combine(dir, file);
        byte[] bytes = new byte[TextureIndex.Dxt5Bytes(8, 4)];
        for (int i = 0; i < bytes.Length; i++) bytes[i] = fill;
        using (var writer = new BinaryWriter(File.Create(path)))
        {
            writer.Write(Encoding.ASCII.GetBytes("BVTB\0"));
            writer.Write(1);
            writer.Write(Encoding.UTF8.GetBytes(name + "\0"));
            writer.Write(8); writer.Write(4); writer.Write(linear);
            writer.Write((long)(9 + Encoding.UTF8.GetByteCount(name) + 1 + 25));
            writer.Write((long)bytes.Length);
            writer.Write(bytes);
        }
        return path;
    }

    public static int Main(string[] args)
    {
        string dir = Path.Combine(Path.GetTempPath(), "valheim-impact-test-" + Guid.NewGuid());
        Directory.CreateDirectory(dir);
        try
        {
            FrameTimingTests.Run(Check);
            OwnedBundleTests.Run(Check, dir);
            OwnedStreamingTests.Run(Check);
            MaterialBindingTests.Run(Check);
            OwnedMaterialRegistryTests.Run(Check, dir);
            string a = Bundle(dir, "main.dat", "shared", 19, true);
            string b = Bundle(dir, "override.dat", "shared", 31, true);
            TextureIndex index = TextureIndex.ReadLegacyBvtb(new[] { a, b });
            Check(index.Entries.Count == 1, "later override replaces earlier name");
            Check(index.Entries["shared"].Path == b, "override source is retained");
            var cache = new FullResolutionCache<object>(index);
            Check(cache.UploadCount == 0 && cache.ResidentBytes == 0, "indexing allocates no textures");
            int factoryCalls = 0;
            object tex = cache.Get("shared", (entry, raw) =>
            {
                factoryCalls++;
                Check(entry.Width == 8 && entry.Height == 4, "original dimensions retained");
                Check(raw.Length == TextureIndex.Dxt5Bytes(8, 4) && raw[0] == 31 && raw[raw.Length-1] == 31,
                    "all original compressed mip bytes retained");
                return new object();
            });
            Check(ReferenceEquals(tex, cache.Get("shared", (e, raw) => { throw new Exception("uploaded twice"); })),
                "second request reuses GPU resource");
            string c = Bundle(dir, "alias.dat", "alias", 31, true);
            string d = Bundle(dir, "different-color.dat", "linear", 31, false);
            index = TextureIndex.ReadLegacyBvtb(new[] { b, c, d });
            NativeTests.Run(Check, index);
            // Mono may round sub-microsecond file timestamps when restoring the
            // deliberately modified temporary source. Start the next test afresh.
            index = TextureIndex.ReadLegacyBvtb(new[] { b, c, d });
            cache = new FullResolutionCache<object>(index);
            object first = cache.Get("shared", (e, raw) => new object());
            object same = cache.Get("alias", (e, raw) => new object());
            object different = cache.Get("linear", (e, raw) => new object());
            Check(ReferenceEquals(first, same), "identical content shares a resource across names");
            Check(!ReferenceEquals(first, different), "different color spaces remain separate");
            Check(cache.UploadCount == 2, "only two distinct GPU uploads occurred");
            Check(cache.ResidentBytes == 2 * TextureIndex.Dxt5Bytes(8, 4), "resident accounting excludes reused data");
            // Eviction must release a shared allocation only after its last observed use.
            double clock = 0;
            cache = new FullResolutionCache<object>(index, () => clock);
            first = cache.Get("shared", (e, raw) => new object());
            same = cache.Get("alias", (e, raw) => new object());
            different = cache.Get("linear", (e, raw) => new object());
            cache.Pin(different);
            int released = 0;
            clock = 59;
            Check(cache.Sweep(clock, 60, (resource, names) => { released++; return true; }) == 0,
                "unused resources retain the full grace period");
            cache.Observe(same, clock);
            clock = 100;
            Check(cache.Sweep(clock, 60, (resource, names) => { released++; return true; }) == 0,
                "observing an alias protects the shared allocation");
            clock = 120;
            Check(cache.Sweep(clock, 60, (resource, names) => false) == 0 && cache.ResidentCount == 2,
                "release veto preserves aliases and residency");
            bool releaseFailed = false;
            try { cache.Sweep(clock, 60, (resource, names) => { throw new IOException("release failed"); }); }
            catch (IOException) { releaseFailed = true; }
            Check(releaseFailed && cache.ResidentCount == 2 && cache.EvictionCount == 0,
                "release exception preserves cache accounting");
            Check(cache.Sweep(clock, 60, (resource, names) =>
            {
                Check(ReferenceEquals(resource, first) && names.Count == 2 && names.Contains("shared") && names.Contains("alias"),
                    "release includes every alias exactly once");
                released++;
                return true;
            }) == 1 && released == 1, "unused shared allocation is released once");
            Check(cache.ResidentCount == 1 && cache.EvictionCount == 1 && cache.ResidentBytes == TextureIndex.Dxt5Bytes(8, 4),
                "eviction subtracts only the released allocation");
            clock = 200;
            Check(cache.Sweep(clock, 60, (resource, names) => { throw new Exception("pinned resource evicted"); }) == 0,
                "pinned color-space resource remains resident");
            object reloaded = cache.Get("alias", (entry, raw) =>
            {
                Check(entry.Width == 8 && entry.Height == 4 && raw.Length == TextureIndex.Dxt5Bytes(8, 4) && raw[0] == 31,
                    "evicted alias reloads its complete original payload");
                return new object();
            });
            Check(!ReferenceEquals(first, reloaded), "evicted content is uploaded as a new resource");
            Check(ReferenceEquals(reloaded, cache.Get("shared", (e, raw) => { throw new Exception("content alias survived eviction"); })),
                "all name aliases and content identity rebuild after eviction");
            clock = 259;
            Check(cache.Sweep(clock, 60, (resource, names) => true) == 0, "reload restarts grace period");
            Check(cache.UploadCount == 3 && cache.ReloadCount == 1, "upload and reload totals distinguish residency from lifetime work");
            object vanilla = new object(), hd = new object(), external = new object();
            object assigned = hd;
            var binding = new RestorableBinding<object>("shared", vanilla, hd);
            Check(binding.Release(() => assigned, value => assigned = value) && ReferenceEquals(assigned, vanilla),
                "release restores original material binding before disposal");
            Check(binding.Evicted, "released material remembers that its HD binding needs reload");
            int reloads = 0;
            Check(binding.Restore(() => assigned, value => assigned = value, name =>
            { reloads++; Check(name == "shared", "binding reload uses exact requested alias"); return reloaded; }),
                "returning object restores its evicted material");
            Check(ReferenceEquals(assigned, reloaded) && !binding.Evicted && reloads == 1,
                "returning object receives new full-resolution resource once");
            assigned = external;
            Check(!binding.Release(() => assigned, value => assigned = value) && ReferenceEquals(assigned, external),
                "eviction does not overwrite another mod's material change");
            assigned = reloaded;
            binding.Release(() => assigned, value => assigned = value);
            assigned = external;
            Check(!binding.Restore(() => assigned, value => assigned = value, name => { throw new Exception("external binding changed"); }),
                "reload preserves a material changed after eviction");
            assigned = vanilla;
            bool restoreFailed = false;
            try { binding.Restore(() => assigned, value => assigned = value, name => { throw new IOException("read failed"); }); }
            catch (IOException) { restoreFailed = true; }
            Check(restoreFailed && binding.Evicted && ReferenceEquals(assigned, vanilla),
                "failed reload leaves the vanilla material usable and retryable");
            clock = 0;
            cache = new FullResolutionCache<object>(index, () => clock);
            first = cache.Get("shared", (e, raw) => new object());
            different = cache.Get("linear", (e, raw) => new object());
            var scan = new EvictionScan<object>(5);
            scan.Protected.Add(first);
            clock = 100;
            Check(scan.Complete(6, cache, clock, 60, (resource, names) => { throw new Exception("stale snapshot released a texture"); }) == -1,
                "spawn or material changes invalidate an incremental census");
            Check(cache.ResidentCount == 2 && cache.EvictionCount == 0, "aborted census preserves every allocation");
            scan = new EvictionScan<object>(6);
            scan.Protected.Add(first);
            Check(scan.Complete(6, cache, clock, 60, (resource, names) => ReferenceEquals(resource, different)) == 1,
                "stable census releases only unobserved resources");
            Check(cache.Contains(first) && !cache.Contains(different), "stable census keeps the referenced full-resolution texture");
            Check(Fingerprint.Hex(Encoding.ASCII.GetBytes("abc")) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                "fast fingerprint matches the standard SHA256 vector");
            byte[] sample = new byte[1024 * 1024 + 7];
            new Random(1234).NextBytes(sample);
            using (var sha = System.Security.Cryptography.SHA256.Create())
                Check(Fingerprint.Hex(sample) == BitConverter.ToString(sha.ComputeHash(sample)).Replace("-", "").ToLowerInvariant(),
                    "native fingerprint matches managed SHA256 for a full buffer");
            int hashCalls = 0;
            cache = new FullResolutionCache<object>(index, () => clock, raw => { hashCalls++; return Fingerprint.Hex(raw); });
            first = cache.Get("shared", (e, raw) => new object());
            clock += 100;
            cache.Sweep(clock, 60, (resource, names) => true);
            reloaded = cache.Get("shared", (e, raw) =>
            { Check(raw[0] == 31 && raw.Length == TextureIndex.Dxt5Bytes(8, 4), "fingerprint reuse still reloads every original byte"); return new object(); });
            Check(hashCalls == 1 && !ReferenceEquals(first, reloaded), "eviction retains only the fingerprint and avoids rehashing reloads");
            cache.Get("alias", (e, raw) => { throw new Exception("alias not reused"); });
            Check(hashCalls == 2, "a previously unseen alias is fingerprinted before sharing");
            clock += 100;
            cache.Sweep(clock, 60, (resource, names) => true);
            File.SetLastWriteTimeUtc(b, DateTime.UtcNow.AddSeconds(2));
            bool changedSourceRejected = false;
            try { cache.Get("shared", (e, raw) => { throw new Exception("changed bundle uploaded"); }); }
            catch (InvalidDataException) { changedSourceRejected = true; }
            Check(changedSourceRejected && cache.ResidentCount == 0,
                "changed bundle cannot reuse a stale fingerprint after eviction");
            Console.WriteLine("Fingerprint backend: " + Fingerprint.Backend);
            // Read-ahead owns only bounded CPU payloads until the real request uploads them.
            string pa = Bundle(dir, "prefetch-a.dat", "prefetch-a", 73, true);
            string pb = Bundle(dir, "prefetch-b.dat", "prefetch-b", 91, true);
            var pi = TextureIndex.ReadLegacyBvtb(new[] { pa, pb });
            long payloadSize = TextureIndex.Dxt5Bytes(8, 4);
            double prefetchClock = 0;
            using (var ahead = new TextureReadAhead(payloadSize, Fingerprint.Hex, () => prefetchClock))
            {
                var pc = new FullResolutionCache<object>(pi, () => prefetchClock, Fingerprint.Hex, ahead);
                Check(pc.Prefetch("prefetch-a"), "nearby texture accepts background preparation");
                Check(!pc.Prefetch("prefetch-b"), "queued and ready bytes cannot exceed preparation budget");
                Check(SpinWait.SpinUntil(() => ahead.ReadyCount == 1, 3000), "real file preparation finishes on worker");
                Check(pc.ResidentBytes == 0 && pc.UploadCount == 0 && ahead.ReservedBytes == payloadSize,
                    "prepared payload creates no GPU resource and remains accounted");
                int requestThread = Thread.CurrentThread.ManagedThreadId;
                pc.Get("prefetch-a", (e, raw) =>
                {
                    Check(Thread.CurrentThread.ManagedThreadId == requestThread, "texture factory stays on requesting thread");
                    Check(raw.Length == payloadSize && raw[0] == 73 && raw[raw.Length-1] == 73 && e.Width == 8,
                        "prepared upload preserves exact bytes and dimensions");
                    return new object();
                });
                Check(pc.LastPreparation == "ready" && ahead.ReadyHits == 1 && ahead.ReservedBytes == 0,
                    "request consumes prepared data and releases reservation");
                Check(!pc.Prefetch("prefetch-a"), "resident resource is never prefetched again");
                Check(pc.Prefetch("prefetch-b"), "consumed buffer frees budget for another texture");
                Check(SpinWait.SpinUntil(() => ahead.ReadyCount == 1, 3000), "second preparation completes");
                prefetchClock = 11;
                ahead.Expire();
                Check(ahead.ReservedBytes == 0 && ahead.ReadyCount == 0, "unused prepared buffers expire after ten seconds");
                pc.Prefetch("prefetch-b");
                Check(SpinWait.SpinUntil(() => ahead.ReadyCount == 1, 3000), "expired preparation can be requested again");
                File.SetLastWriteTimeUtc(pb, DateTime.UtcNow.AddSeconds(4));
                bool stale = false;
                try { pc.Get("prefetch-b", (e, raw) => { throw new Exception("stale bytes uploaded"); }); }
                catch (InvalidDataException) { stale = true; }
                Check(stale && ahead.ReservedBytes == 0 && pc.ResidentCount == 1,
                    "source changed after preparation is rejected before upload");
            }
            // Hold only the active checksum to prove a queued demand does not wait behind it.
            using (var started = new ManualResetEventSlim())
            using (var finish = new ManualResetEventSlim())
            using (var ahead = new TextureReadAhead(payloadSize * 2, raw =>
                { started.Set(); if (!finish.Wait(3000)) throw new TimeoutException(); return Fingerprint.Hex(raw); }))
            {
                pi = TextureIndex.ReadLegacyBvtb(new[] { pa, pb });
                var pc = new FullResolutionCache<object>(pi, () => 0, Fingerprint.Hex, ahead);
                pc.Prefetch("prefetch-a");
                Check(started.Wait(3000), "background read enters fingerprint step");
                pc.Prefetch("prefetch-b");
                pc.Get("prefetch-b", (e, raw) => { Check(raw[0] == 91, "queued demand reads its own bytes"); return new object(); });
                Check(pc.LastPreparation == "sync" && ahead.ReservedBytes == payloadSize,
                    "queued demand runs immediately without waiting for unrelated active read");
                var pendingDemand = Task.Run(() => pc.Get("prefetch-a", (e, raw) => new object()));
                try
                {
                    Check(SpinWait.SpinUntil(() => ahead.WaitHits == 1, 2000), "demand joins exactly its active read");
                    Check(!pendingDemand.IsCompleted && ahead.ReservedBytes == payloadSize,
                        "active read retains reservation until demand can consume it");
                }
                finally { finish.Set(); }
                Check(pendingDemand.Wait(3000), "joined read completes and uploads after worker finishes");
                Check(ahead.ReservedBytes == 0 && pc.UploadCount == 2, "active read joins safely without duplicate upload");
            }
            // An imminent large request must be able to replace speculative ready data.
            prefetchClock = 0;
            int backgroundHashes = 0;
            using (var ahead = new TextureReadAhead(payloadSize, raw =>
                { Interlocked.Increment(ref backgroundHashes); return Fingerprint.Hex(raw); }, () => prefetchClock))
            {
                Check(ahead.Offer(pi.Entries["prefetch-a"], null, 1000000), "speculative outer-area preparation is accepted");
                Check(SpinWait.SpinUntil(() => ahead.ReadyCount == 1, 3000), "speculative payload becomes ready");
                Check(ahead.Offer(pi.Entries["prefetch-b"], null, 0), "imminent request replaces lower-priority ready bytes within the cap");
                Check(ahead.Preempted == 1 && ahead.PeakBytes <= payloadSize, "priority replacement never expands the CPU buffer limit");
                PreparedTexture payload;
                Check(!ahead.Take(pi.Entries["prefetch-a"], out payload), "preempted speculative data is no longer retained");
                Check(SpinWait.SpinUntil(() => ahead.ReadyCount == 1, 3000), "imminent replacement finishes");
                Check(ahead.Take(pi.Entries["prefetch-b"], out payload) && payload.Bytes[0] == 91,
                    "priority request receives its own exact bytes");
                ahead.Offer(pi.Entries["prefetch-a"], null, 1000000);
                Check(SpinWait.SpinUntil(() => ahead.ReadyCount == 1, 3000), "speculative bytes can prepare again");
                Check(backgroundHashes == 2, "discarded payload fingerprints survive without retaining raw data");
                prefetchClock = 11; ahead.Expire();
                Check(!ahead.Offer(pi.Entries["prefetch-a"], null, 1000000), "unused distant payload is not reread every expiry cycle");
                Check(ahead.Offer(pi.Entries["prefetch-a"], null, 0), "imminent demand bypasses distant retry cooldown");
            }
            var disposedAhead = new TextureReadAhead(payloadSize);
            disposedAhead.Offer(pi.Entries["prefetch-a"], null);
            disposedAhead.Dispose();
            Check(disposedAhead.ReservedBytes == 0 && !disposedAhead.Offer(pi.Entries["prefetch-b"], null),
                "disposal finishes active work, releases buffers and rejects new work");
            using (var ahead = new TextureReadAhead(payloadSize, raw => { throw new IOException("worker hash failed"); }))
            {
                ahead.Offer(pi.Entries["prefetch-a"], null);
                Check(SpinWait.SpinUntil(() => ahead.ReadyCount == 1, 3000), "worker failure completes rather than stranding request");
                bool failed = false;
                try { PreparedTexture ignored; ahead.Take(pi.Entries["prefetch-a"], out ignored); }
                catch (IOException) { failed = true; }
                Check(failed && ahead.ReservedBytes == 0, "worker error reaches demand and releases budget");
                ahead.Offer(pi.Entries["prefetch-b"], null);
            }
            using (var f = new FileStream(c, FileMode.Open, FileAccess.Write)) f.SetLength(10);
            bool rejected = false;
            try { TextureIndex.ReadLegacyBvtb(new[] { c }); } catch (InvalidDataException) { rejected = true; }
            Check(rejected, "truncated directory rejected");

        }
        finally { Directory.Delete(dir, true); }
        Console.WriteLine("Failures: " + failures);
        return failures == 0 ? 0 : 1;
    }
}
