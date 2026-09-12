using System;
using System.Collections.Generic;
using System.IO;
using ValheimImpact.Core;

internal static class MaterialBindingTests
{
    private sealed class Load : IOwnedTextureLoad<object>
    {
        public readonly object Value = new object();
        public bool Ready, Released;
        public bool IsDone { get { return Ready; } }
        public bool IsReleased { get { return Released; } }
        public Exception Error { get { return null; } }
        public bool Pump(bool allow) { return false; }
        public object Take() { return Value; }
        public void Cancel() { Released = true; }
        public void Dispose() { Released = true; }
    }
    public static void Run(Action<bool, string> check)
    {
        var cutout = new CutoutBindingState { mode = 1, cutoff = .69f, cull = 0, zWrite = 1, srcBlend = 1, dstBlend = 0, renderQueue = 2000, alphaTest = false };
        check(cutout.Matches(1, .69f, 0, 1, 1, 0, 2000, false, false, false), "cutout matches explicit stored state without inventing alpha keywords");
        check(!cutout.Matches(2, .69f, 0, 1, 1, 0, 2000, false, false, false) && !cutout.Matches(3, .69f, 0, 1, 1, 0, 2000, false, false, false),
            "cutout rejects fade and transparent material modes");
        check(!cutout.Matches(1, .7f, 0, 1, 1, 0, 2000, false, false, false) && !cutout.Matches(1, float.NaN, 0, 1, 1, 0, 2000, false, false, false),
            "cutout threshold comparison rejects changed and unknown values");
        check(!cutout.Matches(1, .69f, 2, 1, 1, 0, 2000, false, false, false) && !cutout.Matches(1, .69f, 0, 0, 1, 0, 2000, false, false, false),
            "cutout preserves the exact culling and depth-write state");
        check(!cutout.Matches(1, .69f, 0, 1, 5, 0, 2000, false, false, false) && !cutout.Matches(1, .69f, 0, 1, 1, 10, 2000, false, false, false),
            "cutout cannot accept alpha blending factors");
        check(!cutout.Matches(1, .69f, 0, 1, 1, 0, 2450, false, false, false) && !cutout.Matches(1, .69f, 0, 1, 1, 0, 3000, false, false, false),
            "cutout requires its explicit render queue even within the opaque range");
        check(!cutout.Matches(1, .69f, 0, 1, 1, 0, 2000, true, false, false) && !cutout.Matches(1, .69f, 0, 1, 1, 0, 2000, false, true, false) &&
            !cutout.Matches(1, .69f, 0, 1, 1, 0, 2000, false, false, true), "cutout rejects changed alpha-test, blend and premultiply keywords");
        cutout.alphaTest = true;
        check(cutout.Matches(1, .69f, 0, 1, 1, 0, 2000, true, false, false) && !cutout.Matches(1, .69f, 0, 1, 1, 0, 2000, false, false, false),
            "an enabled alpha-test keyword is accepted only when explicitly expected");
        var rule = new MaterialBindingRule { id = "stone", materialName = "Rock", shaderName = "Custom/StaticRock",
            textureProperty = "_MainTex", originalTextureName = "rock_diffuse", originalWidth = 1024,
            originalHeight = 512, ownedTextureId = "stone-owned" };
        check(rule.Matches("Rock", "Custom/StaticRock", "_MainTex", "rock_diffuse", 1024, 512), "binding matches the complete exact identity");
        check(!rule.Matches("Rock (Instance)", "Custom/StaticRock", "_MainTex", "rock_diffuse", 1024, 512) &&
            !rule.Matches("rock", "Custom/StaticRock", "_MainTex", "rock_diffuse", 1024, 512) &&
            !rule.Matches("Rock", "Standard", "_MainTex", "rock_diffuse", 1024, 512) &&
            !rule.Matches("Rock", "Custom/StaticRock", "_BumpMap", "rock_diffuse", 1024, 512) &&
            !rule.Matches("Rock", "Custom/StaticRock", "_MainTex", "other", 1024, 512) &&
            !rule.Matches("Rock", "Custom/StaticRock", "_MainTex", "rock_diffuse", 512, 512), "binding rejects names, shader, channel, or dimensions that differ");
        var spec = new OwnedTextureBundle("/tmp/material-fixture.bundle", "fixture", new string('a', 64), 4, 4, true);
        var load = new Load();
        var scheduler = new OwnedTextureScheduler<object>(new Dictionary<string, OwnedTextureRequest> {
            { "stone-owned", new OwnedTextureRequest(spec, new string('b', 64)) } }, _ => load, _ => {}, _ => true,
            new StreamingPolicy(1024, 1024, 1, 0));
        object original = new object(), foreign = new object(), assigned = original;
        var binding = new OwnedMaterialLease<object>(original, scheduler.Acquire("stone-owned"));
        check(!binding.ApplyReady(() => assigned, value => assigned = value, () => true) && ReferenceEquals(assigned, original) && scheduler.StartedCount == 0,
            "binding preserves original while demand remains asynchronous");
        scheduler.Tick(1, 0); load.Ready = true; scheduler.Tick(2, 1); scheduler.Tick(3, 2);
        check(binding.ApplyReady(() => assigned, value => assigned = value, () => true) && ReferenceEquals(assigned, load.Value), "binding adopts the ready scheduler resource");
        scheduler.Stop(); scheduler.Tick(4, 3);
        check(scheduler.ResidentBytes > 0 && scheduler.LeaseCount == 1, "applied material lease protects resident during stop");
        bool restoredBeforeRelease = false;
        check(binding.RestoreAndRelease(() => assigned, value => { restoredBeforeRelease = scheduler.LeaseCount == 1; assigned = value; }, () => true) &&
            restoredBeforeRelease && ReferenceEquals(assigned, original) && scheduler.LeaseCount == 0, "binding restores original before releasing ownership");
        scheduler.Tick(5, 4); scheduler.Tick(6, 5);
        check(scheduler.IsDrained, "restored stopped material scheduler drains");
        load = new Load { Ready = true };
        scheduler = new OwnedTextureScheduler<object>(new Dictionary<string, OwnedTextureRequest> {
            { "stone-owned", new OwnedTextureRequest(spec, new string('b', 64)) } }, _ => load, _ => {}, _ => true,
            new StreamingPolicy(1024, 1024, 1, 0));
        assigned = original;
        binding = new OwnedMaterialLease<object>(original, scheduler.Acquire("stone-owned"));
        scheduler.Tick(1, 0); scheduler.Tick(2, 1); scheduler.Tick(3, 2);
        check(!binding.ApplyReady(() => assigned, value => assigned = value, () => false) && ReferenceEquals(assigned, original),
            "binding revalidates shader and identity before first assignment");
        assigned = foreign;
        check(!binding.ApplyReady(() => assigned, value => assigned = value, () => true) && ReferenceEquals(assigned, foreign),
            "foreign replacement before async completion is preserved");
        check(binding.RestoreAndRelease(() => assigned, value => assigned = value, () => true) && ReferenceEquals(assigned, foreign),
            "foreign replacement before apply releases lease without writes");
        assigned = original;
        binding = new OwnedMaterialLease<object>(original, scheduler.Acquire("stone-owned"));
        binding.ApplyReady(() => assigned, value => assigned = value, () => true);
        check(!binding.RestoreAndRelease(() => assigned, value => assigned = value, () => false) && scheduler.LeaseCount == 1,
            "missing fallback cannot release a still-bound owned texture");
        assigned = foreign;
        check(binding.RestoreAndRelease(() => assigned, value => assigned = value, () => false) && ReferenceEquals(assigned, foreign) && scheduler.LeaseCount == 0,
            "foreign replacement after apply is never overwritten and releases demand");
        check(binding.RestoreAndRelease(() => assigned, value => assigned = value, () => true), "material release is idempotent");
        scheduler.Stop(); scheduler.Tick(4, 3); scheduler.Tick(5, 4);
    }
}
