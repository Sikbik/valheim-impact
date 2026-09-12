using System;
using System.Collections.Generic;
using System.IO;
using ValheimImpact.Core;

internal static class NativeTests
{
    private sealed class Load : ITextureLoad<object>
    {
        public bool Ready { get; set; }
        internal object Value = new object();
        internal bool Fail, Disposed;
        internal int Completions;
        public object Complete()
        { Completions++; if (Fail) throw new IOException("native failure"); Ready = true; return Value; }
        public void Dispose() { Disposed = true; }
    }

    internal static void Run(Action<bool, string> check, TextureIndex index)
    {
        var catalog = new NativeTextureCatalog();
        foreach (var entry in index.Entries.Values)
            catalog.Records.Add(entry.Name, new NativeTextureRecord {
                Entry = entry, Content = PreparedTexture.Read(entry, null, Fingerprint.Hex).Content,
                BundlePath = entry.Path + ".bundle" });
        long size = index.Entries["shared"].Length;
        double now = 0; int frame = 0;
        var loads = new List<Load>(); var destroyed = new HashSet<object>();
        Func<NativeTextureRecord, bool, ITextureLoad<object>> begin = (record, async) =>
        { var result = new Load { Ready = !async }; loads.Add(result); return result; };
        var queue = new NativeTextureQueue<object>(catalog, size * 2, begin,
            value => { check(destroyed.Add(value), "speculative allocation destroyed only once"); }, () => now, () => frame);
        var cache = new FullResolutionCache<object>(index, () => now, raw => { throw new Exception("runtime hashing"); }, null, queue);
        check(cache.Prefetch("shared", 10) && cache.Prefetch("alias", 0) && queue.ReservedBytes == size,
            "native aliases reserve one payload and do not allocate until a tick");
        check(loads.Count == 0, "native offers do no engine work");
        queue.Tick();
        check(loads.Count == 1 && queue.ActiveCount == 1, "native scheduler starts one async request");
        loads[0].Ready = true; frame++; queue.Tick();
        object first = cache.Get("alias", (e, b) => { throw new Exception("raw fallback on ready native"); });
        check(ReferenceEquals(first, loads[0].Value) && loads[0].Disposed && queue.ReservedBytes == 0,
            "ready native texture transfers ownership and releases its bundle and reservation");
        check(cache.LastPreparation == "native-ready" && cache.ResidentBytes == size,
            "cache counts original bytes after native adoption");
        check(ReferenceEquals(first, cache.Get("shared", (e, b) => { throw new Exception("duplicate alias"); })) && loads.Count == 1,
            "catalog identity reuses resident aliases without native or raw duplicate");
        check(!cache.Prefetch("shared") && !cache.Prefetch("alias"), "resident native content is not prepared again");
        now = 61; cache.Sweep(now, 60, (value, names) => true);
        cache.Prefetch("shared", 0); frame++; queue.Tick();
        object second = cache.Get("alias", (e, b) => { throw new Exception("urgent fallback"); });
        check(ReferenceEquals(second, loads[1].Value) && loads[1].Completions == 1 && loads[1].Disposed,
            "urgent alias completes the same active native request once");
        check(cache.ReloadCount == 1 && cache.LastPreparation == "native-urgent", "native eviction reload is counted and labeled");
        object linear = cache.Get("linear", (e, b) => { throw new Exception("native sync fallback"); });
        check(!ReferenceEquals(second, linear) && cache.ResidentCount == 2 && cache.LastPreparation == "native-sync",
            "same bytes with different color interpretation stay separate");
        queue.Dispose();
        check(!destroyed.Contains(first) && !destroyed.Contains(second) && !destroyed.Contains(linear),
            "disposing preparation does not destroy textures transferred to residency");

        // Budget and priorities use distinct content, including a larger imminent request.
        var fake = new NativeTextureCatalog();
        foreach (string name in new[] { "distant", "near", "large" })
            fake.Records.Add(name, new NativeTextureRecord { Entry = new TextureEntry {
                Name = name, Length = name == "large" ? size * 2 : size }, Content = name });
        loads.Clear(); destroyed.Clear(); now = 0; frame = 0;
        queue = new NativeTextureQueue<object>(fake, size * 2, begin, value => destroyed.Add(value), () => now, () => frame, entry => { });
        queue.Prefetch(fake.Records["distant"].Entry, 1000000);
        queue.Prefetch(fake.Records["near"].Entry, 1);
        check(queue.Prefetch(fake.Records["large"].Entry, 0) && queue.Preempted == 2 && queue.ReservedBytes == size * 2,
            "imminent large payload preempts queued guesses within budget");
        queue.Tick();
        check(!queue.Prefetch(fake.Records["near"].Entry, 0) && queue.ActiveCount == 1,
            "active native load is never preempted");
        loads[0].Ready = true; frame++; queue.Tick();
        now = 11; frame++; queue.Tick();
        check(destroyed.Count == 1 && queue.ReservedBytes == size * 2,
            "expired GPU payload retains reservation during deferred destruction");
        frame++; queue.Tick();
        check(queue.ReservedBytes == size * 2, "reservation remains for a full intervening frame");
        frame++; queue.Tick();
        check(queue.ReservedBytes == 0 && queue.PeakBytes <= size * 2, "deferred destruction eventually releases bounded budget");
        queue.Prefetch(fake.Records["distant"].Entry, 1000000); frame++; queue.Tick();
        loads[1].Ready = true; frame++; queue.Tick();
        now = 22; frame++; queue.Tick(); frame += 2; queue.Tick();
        check(!queue.Prefetch(fake.Records["distant"].Entry, 1000000) && queue.Prefetch(fake.Records["distant"].Entry, 0),
            "expired distant guesses cool down while imminent demand bypasses cooldown");
        queue.Dispose();

        loads.Clear(); destroyed.Clear(); now = 0; frame = 0;
        queue = new NativeTextureQueue<object>(fake, size * 4, begin, value => destroyed.Add(value), () => now, () => frame, entry => { });
        queue.Prefetch(fake.Records["distant"].Entry, 1000000);
        queue.Prefetch(fake.Records["near"].Entry, 1);
        queue.Prefetch(fake.Records["large"].Entry, 0);
        queue.Tick(); queue.Tick();
        check(loads.Count == 1, "repeated ticks in one frame cannot start additional native requests");
        frame++; queue.Tick(); frame++; queue.Tick();
        check(loads.Count == 2 && queue.ActiveCount == 2, "native concurrency is limited to two active requests");
        string mode;
        object direct = queue.Load(fake.Records["distant"].Entry, out mode);
        check(mode == "native-sync" && direct != null && !loads[0].Ready && !loads[1].Ready,
            "queued demand completes itself without requiring unrelated active requests to finish");
        queue.Dispose();
        check(loads[0].Disposed && loads[1].Disposed && !destroyed.Contains(direct),
            "disposal releases active native handles and preserves transferred resources");

        loads.Clear(); destroyed.Clear(); frame = 0;
        queue = new NativeTextureQueue<object>(fake, size, begin, value => destroyed.Add(value), () => now, () => frame, entry => { });
        queue.Prefetch(fake.Records["distant"].Entry, 1000000); queue.Tick();
        loads[0].Ready = true; frame++; queue.Tick();
        check(!queue.Prefetch(fake.Records["near"].Entry, 0) && destroyed.Count == 1 && queue.ReservedBytes == size,
            "preempting a ready GPU texture waits for deferred destruction before replacement");
        frame += 2; queue.Tick();
        check(queue.Prefetch(fake.Records["near"].Entry, 0) && queue.PeakBytes == size,
            "replacement is admitted after deferred GPU retirement within the same budget");
        queue.Dispose();

        loads.Clear(); destroyed.Clear(); now = 0;
        queue = new NativeTextureQueue<object>(catalog, size * 2, begin, value => destroyed.Add(value), () => now, () => frame);
        cache = new FullResolutionCache<object>(index, () => now, Fingerprint.Hex, null, queue);
        cache.Prefetch("shared"); queue.Tick(); loads[0].Fail = true; loads[0].Ready = true;
        frame++; queue.Tick();
        int fallbacks = 0;
        object recovered = cache.Get("shared", (e, raw) => { fallbacks++; return new object(); });
        check(recovered != null && fallbacks == 1 && queue.Errors == 1 && loads[0].Disposed,
            "native failure cleans up and falls back to full original raw data");
        check(!cache.Prefetch("alias"), "native failure cannot prepare a duplicate resident fallback");
        queue.Dispose();

        // A corrupt catalog must not substitute a different source range.
        var record = catalog.Records["shared"];
        long previous = record.Entry.Offset;
        var wrong = new TextureEntry { Name = record.Entry.Name, Path = record.Entry.Path,
            Width = record.Entry.Width, Height = record.Entry.Height, IsSrgb = record.Entry.IsSrgb,
            Offset = previous + 1, Length = record.Entry.Length, SourceBytes = record.Entry.SourceBytes,
            SourceWriteTicks = record.Entry.SourceWriteTicks };
        NativeTextureRecord ignored;
        check(!catalog.TryMatch(wrong, out ignored), "catalog rejects a different source offset");
        string file = index.Entries["shared"].Path;
        DateTime stamp = File.GetLastWriteTimeUtc(file);
        queue = new NativeTextureQueue<object>(catalog, size * 2, begin, value => destroyed.Add(value), () => now, () => frame);
        cache = new FullResolutionCache<object>(index, () => now, Fingerprint.Hex, null, queue);
        cache.Prefetch("shared"); queue.Tick(); loads[loads.Count-1].Ready = true; frame++; queue.Tick();
        File.SetLastWriteTimeUtc(file, stamp.AddSeconds(1));
        bool rejected = false;
        try { cache.Get("shared", (e, raw) => { throw new Exception("changed source accepted"); }); }
        catch (InvalidDataException) { rejected = true; }
        finally { File.SetLastWriteTimeUtc(file, stamp); queue.Dispose(); }
        check(rejected, "source changed after native preparation is rejected before material adoption");
    }
}
