using System;
using System.Collections.Generic;
using ValheimImpact.Core;

internal static class OwnedStreamingTests
{
    // Engine operations are an external boundary. The scheduler and accounting are real.
    private sealed class Texture { internal bool DestroyRequested, Released; }
    private sealed class Load : IOwnedTextureLoad<Texture>
    {
        internal readonly Texture Value = new Texture();
        internal bool Opened = false, HoldRelease = false;
        internal bool Finish, Cancelled, Released, Transferred, DisposeRequested;
        internal int AssetStarts;
        internal Exception Failure = null;
        public bool IsDone { get { return Finish; } }
        public bool IsReleased { get { return Released; } }
        public Exception Error { get { return Failure; } }
        public bool Pump(bool allowEngineStart)
        {
            bool started = false;
            if (Opened && !Cancelled && AssetStarts == 0 && allowEngineStart) { AssetStarts++; started = true; }
            if (DisposeRequested && Finish && !HoldRelease) { Released = true; if (!Transferred) Value.Released = true; }
            return started;
        }
        public Texture Take()
        {
            if (!Finish || Failure != null || Cancelled || Transferred) throw new InvalidOperationException("Unsafe transfer");
            Transferred = true; return Value;
        }
        public void Cancel() { Cancelled = true; DisposeRequested = true; }
        public void Dispose() { DisposeRequested = true; }
    }
    private sealed class Rig
    {
        internal readonly List<Load> Loads = new List<Load>();
        internal readonly List<Texture> Retired = new List<Texture>();
        internal readonly OwnedTextureScheduler<Texture> Scheduler;
        internal long Frame;
        internal double Time;
        internal Rig(long resident = 128, long pending = 128, int concurrent = 2,
            double idle = 60, int tracked = 256, int leases = 4096)
        {
            var a = Request('a'); var b = Request('b');
            var catalog = new Dictionary<string, OwnedTextureRequest> { {"a", a}, {"alias", a}, {"b", b},
                {"linear", Request('a', false)}, {"wide", Request('a', true, 8, 4)} };
            Scheduler = new OwnedTextureScheduler<Texture>(catalog, spec => { var load = new Load(); Loads.Add(load); return load; },
                value => { value.DestroyRequested = true; Retired.Add(value); }, value => value.Released,
                new StreamingPolicy(resident, pending, concurrent, idle, tracked, leases));
        }
        internal void Tick(double? now = null) { if (now.HasValue) Time = now.Value; Scheduler.Tick(++Frame, Time); }
        internal void Complete(int index = 0) { Loads[index].Finish = true; Tick(); Tick(); }
    }
    private static OwnedTextureRequest Request(char hash, bool srgb = true, int width = 4, int height = 4)
    { return new OwnedTextureRequest(new OwnedTextureBundle("/synthetic/" + hash + ".bundle", "texture", new string(hash, 64), width, height, srgb), new string(hash, 64)); }
    private static void Scenario(Action<bool, string> check, string name, Action body)
    { try { body(); } catch (Exception e) { check(false, name + ": " + e.Message); } }
    internal static void Run(Action<bool, string> check)
    {
        Scenario(check, "owned demand lifecycle", () => {
            var rig = new Rig(); var a = rig.Scheduler.Acquire("a"); var alias = rig.Scheduler.Acquire("alias"); Texture tex;
            check(a != null && alias != null && !a.TryGet(out tex) && rig.Loads.Count == 0, "owned demand never starts or waits for an engine load");
            rig.Tick(); rig.Tick();
            check(rig.Loads.Count == 1 && rig.Scheduler.PendingBytes == 48, "owned aliases share one in-flight full-mip allocation");
            rig.Complete(); Texture same;
            check(a.TryGet(out tex) && alias.TryGet(out same) && ReferenceEquals(tex, same), "owned aliases share the completed resident texture");
            check(rig.Scheduler.ResidentBytes == 48 && rig.Scheduler.PendingBytes == 0 && !tex.DestroyRequested,
                "owned transfer disposes the request without destroying its texture");
            a.Dispose(); rig.Tick(120);
            check(rig.Scheduler.ResidentBytes == 48 && rig.Retired.Count == 0, "owned final demand reference protects resident texture");
            alias.Dispose(); rig.Tick(179);
            check(rig.Retired.Count == 0, "owned idle grace begins on final lease release");
            rig.Tick(180);
            check(rig.Scheduler.ResidentBytes == 0 && rig.Scheduler.RetiringBytes == 48 && rig.Retired.Count == 1,
                "owned eviction retains budget while destruction is deferred");
            tex.Released = true; rig.Tick();
            check(rig.Scheduler.AllocatedBytes == 0 && rig.Scheduler.EvictedCount == 1, "owned retirement releases accounting only after acknowledgement");
        });
        Scenario(check, "owned engine admission", () => {
            var rig = new Rig(resident: 144, pending: 96, concurrent: 2);
            rig.Scheduler.Acquire("a"); rig.Scheduler.Acquire("b"); rig.Scheduler.Acquire("linear");
            rig.Tick(); rig.Scheduler.Tick(rig.Frame, rig.Time);
            check(rig.Loads.Count == 1, "owned repeated ticks in one frame start only one engine operation");
            rig.Loads[0].Opened = true; rig.Tick();
            check(rig.Loads[0].AssetStarts == 1 && rig.Loads.Count == 1, "owned asset phase consumes the same per-frame start slot as bundle opening");
            rig.Tick(); rig.Tick();
            check(rig.Loads.Count == 2 && rig.Scheduler.PendingBytes == 96 && rig.Scheduler.QueuedCount == 1,
                "owned simultaneous work respects pending bytes and engine concurrency");
        });
        Scenario(check, "owned color and dimensions", () => {
            var rig = new Rig(resident: 512, pending: 512, concurrent: 4);
            var a = rig.Scheduler.Acquire("a"); var linear = rig.Scheduler.Acquire("linear"); var wide = rig.Scheduler.Acquire("wide");
            rig.Tick(); rig.Tick(); rig.Tick();
            for (int i = 0; i < 3; i++) rig.Loads[i].Finish = true;
            rig.Tick(); rig.Tick(); Texture x, y, z;
            check(a.TryGet(out x) && linear.TryGet(out y) && wide.TryGet(out z) &&
                !ReferenceEquals(x, y) && !ReferenceEquals(x, z) && rig.Scheduler.ResidentBytes == 176,
                "owned content sharing includes color interpretation and dimensions");
        });
        Scenario(check, "owned retirement pressure and reload", () => {
            var rig = new Rig(resident: 48, pending: 48, idle: 0);
            var a = rig.Scheduler.Acquire("a"); var b = rig.Scheduler.Acquire("b");
            rig.Tick(); rig.Complete(); Texture old; a.TryGet(out old); rig.Tick();
            check(rig.Loads.Count == 1 && rig.Scheduler.QueuedCount == 1, "owned full resident budget defers replacement while demanded texture is protected");
            a.Dispose(); rig.Tick();
            check(rig.Loads.Count == 1 && rig.Scheduler.AllocatedBytes == 48, "owned retirement pressure cannot admit an overlapping allocation");
            old.Released = true; rig.Tick(); rig.Complete(1); Texture other; b.TryGet(out other);
            check(rig.Loads.Count == 2 && rig.Scheduler.ResidentBytes == 48, "owned acknowledged eviction admits deferred demand");
            b.Dispose(); rig.Tick(); other.Released = true; rig.Tick();
            var again = rig.Scheduler.Acquire("alias"); rig.Tick(); rig.Complete(2); Texture reloaded;
            check(again.TryGet(out reloaded) && !ReferenceEquals(old, reloaded) && rig.Scheduler.ReloadedCount == 1,
                "owned return demand reloads the retired payload exactly once");
        });
        Scenario(check, "owned cancel and reacquire", () => {
            var rig = new Rig(); var first = rig.Scheduler.Acquire("a"); rig.Tick(); first.Dispose(); rig.Tick();
            check(rig.Loads[0].Cancelled && rig.Scheduler.PendingBytes == 48 && rig.Scheduler.ActiveCount == 1,
                "owned canceled work remains pending until the engine releases ownership");
            var again = rig.Scheduler.Acquire("alias"); rig.Tick();
            check(rig.Loads.Count == 1, "owned reacquire does not duplicate a canceled request that is still draining");
            rig.Loads[0].Finish = true; rig.Tick(); rig.Tick();
            check(rig.Loads.Count == 2 && rig.Loads[0].Value.Released, "owned reacquire starts only after canceled request release");
            rig.Complete(1); Texture value;
            check(again.TryGet(out value) && rig.Scheduler.CancelledCount == 1, "owned canceled alias can recover through a fresh asynchronous load");
        });
        Scenario(check, "owned stop drain and lease protection", () => {
            var rig = new Rig(); var a = rig.Scheduler.Acquire("a"); rig.Tick(); rig.Complete(); Texture texture; a.TryGet(out texture);
            var b = rig.Scheduler.Acquire("b"); rig.Tick(); rig.Scheduler.Stop(); rig.Scheduler.Dispose(); rig.Tick();
            check(rig.Scheduler.Acquire("alias") == null && !rig.Scheduler.IsDrained && !texture.DestroyRequested,
                "owned stop rejects demand and protects textures until bindings release leases");
            rig.Loads[1].Finish = true; rig.Tick(); rig.Tick();
            check(rig.Scheduler.PendingBytes == 0 && rig.Scheduler.ResidentBytes == 48, "owned stop drains unfinished requests without destroying leased residents");
            a.Dispose(); a.Dispose(); b.Dispose(); rig.Tick(); texture.Released = true; rig.Tick();
            check(rig.Scheduler.IsDrained && rig.Scheduler.AllocatedBytes == 0 && rig.Scheduler.LeaseCount == 0,
                "owned repeated disposal drains every owned allocation after caller restoration");
        });
        Scenario(check, "owned bounded queue and failure", () => {
            var rig = new Rig(tracked: 1, leases: 2); var a = rig.Scheduler.Acquire("a"); var alias = rig.Scheduler.Acquire("alias");
            check(rig.Scheduler.Acquire("b") == null && rig.Scheduler.Acquire("a") == null && rig.Scheduler.TrackedCount == 1,
                "owned queued identities and demand lease count have independent hard bounds");
            rig.Tick(); rig.Loads[0].Failure = new InvalidOperationException("engine failure"); rig.Loads[0].Finish = true; rig.Tick(); rig.Tick();
            Texture original = new Texture(), assigned = original, replacement;
            if (a.TryGet(out replacement)) assigned = replacement;
            check(ReferenceEquals(assigned, original) && rig.Scheduler.ErrorCount == 1 && rig.Scheduler.AllocatedBytes == 0,
                "owned engine failure drains allocation and preserves the original binding");
            rig.Tick(); check(rig.Loads.Count == 1, "owned failed live demand does not create a retry storm");
            a.Dispose(); alias.Dispose(); rig.Tick();
            check(rig.Scheduler.Acquire("b") != null, "owned failed demand releases bounded queue capacity");
        });
        Scenario(check, "owned canceled queued demand", () => {
            var rig = new Rig(); var a = rig.Scheduler.Acquire("a"); a.Dispose(); rig.Tick();
            check(rig.Loads.Count == 0 && rig.Scheduler.TrackedCount == 0 && rig.Scheduler.AllocatedBytes == 0,
                "owned abandoned queued demand never starts an engine request");
            var tooSmall = new Rig(resident: 47, pending: 47);
            check(tooSmall.Scheduler.Acquire("a") == null && tooSmall.Scheduler.AllocatedBytes == 0,
                "owned oversized payload defers to originals without entering the queue");
        });
        Scenario(check, "owned transferred request retirement", () => {
            var rig = new Rig(resident: 48, pending: 48, idle: 0);
            var a = rig.Scheduler.Acquire("a"); rig.Tick(); rig.Loads[0].HoldRelease = true;
            rig.Loads[0].Finish = true; rig.Tick(); Texture texture;
            check(!a.TryGet(out texture) && rig.Scheduler.PendingBytes == 48 && rig.Scheduler.ResidentBytes == 0,
                "owned transferred result remains reserved until its request finishes unloading");
            a.Dispose(); rig.Scheduler.Stop(); rig.Tick();
            check(rig.Scheduler.PendingBytes == 48 && !rig.Loads[0].Value.Released && !rig.Scheduler.IsDrained,
                "owned stop cannot destroy or forget a transferred result during request unload");
            rig.Loads[0].HoldRelease = false; rig.Tick();
            check(rig.Scheduler.RetiringBytes == 48 && rig.Retired.Count == 1 && !rig.Loads[0].Value.Released,
                "owned canceled transferred result retires through the scheduler exactly once");
            rig.Retired[0].Released = true; rig.Tick();
            check(rig.Scheduler.IsDrained, "owned transferred shutdown reaches acknowledged zero allocation");
        });
        Scenario(check, "owned factory failure", () => {
            var scheduler = new OwnedTextureScheduler<Texture>(new Dictionary<string, OwnedTextureRequest> { {"a", Request('a')} },
                spec => { throw new InvalidOperationException("request did not start"); }, texture => { }, texture => true);
            var lease = scheduler.Acquire("a"); scheduler.Tick(1, 0); Texture value;
            check(!lease.TryGet(out value) && scheduler.AllocatedBytes == 0 && scheduler.ActiveCount == 0 && scheduler.ErrorCount == 1,
                "owned factory failure restores reservations and leaves original binding available");
        });
    }
}
