using System;
using System.Threading;
using UnityEngine;
using ValheimImpact.Core;

namespace ValheimImpact.Unity
{
    // Construct and pump on Unity's main thread. Disposal requests asynchronous
    // draining and never throws merely because an engine operation is unfinished.
    public sealed class OwnedBundleLoad : IOwnedTextureLoad<Texture2D>
    {
        private readonly OwnedTextureBundle spec;
        private readonly int threadId;
        private AssetBundleCreateRequest opening;
        private AssetBundle bundle;
        private AssetBundleRequest loading;
        private AsyncOperation unloading;
        private Texture2D value;
        private bool transferred, cancelRequested, disposeRequested, done, released;
        private Exception error;

        public OwnedBundleLoad(OwnedTextureBundle spec)
        {
            if (spec == null) throw new ArgumentNullException(nameof(spec));
            this.spec = spec;
            threadId = Thread.CurrentThread.ManagedThreadId;
            // ValidateFile belongs to offline preparation. Construction only starts
            // this engine operation, whose start slot the scheduler already reserved.
            try
            {
                opening = AssetBundle.LoadFromFileAsync(spec.Path);
                if (opening == null) throw new InvalidOperationException("Cannot start authored bundle load");
            }
            catch (Exception ex) { error = ex; done = true; disposeRequested = true; }
        }
        private void CheckThread()
        {
            if (Thread.CurrentThread.ManagedThreadId != threadId)
                throw new InvalidOperationException("Use the engine thread that started this load");
        }
        public bool IsDone { get { CheckThread(); return done; } }
        public bool IsReleased { get { CheckThread(); return released; } }
        public Exception Error { get { CheckThread(); return error; } }

        public bool Pump(bool allowEngineStart)
        {
            CheckThread();
            if (released) return false;
            bool started = false;
            try
            {
                if (unloading != null)
                {
                    if (unloading.isDone)
                    {
                        unloading = null; bundle = null; loading = null; value = null; released = true;
                    }
                    return false;
                }
                if (opening != null)
                {
                    if (!opening.isDone) return false;
                    bundle = opening.assetBundle; opening = null;
                    if (bundle == null) throw new InvalidOperationException("Cannot open authored bundle");
                }
                if (loading != null)
                {
                    if (!loading.isDone) return false;
                    if (!done && !cancelRequested)
                    {
                        value = loading.asset as Texture2D;
                        if (value == null || value.width != spec.Width || value.height != spec.Height ||
                            value.mipmapCount != spec.MipCount || value.format != TextureFormat.DXT5 ||
                            value.isDataSRGB != spec.IsSrgb || value.isReadable)
                            throw new InvalidOperationException("Authored texture does not match its build contract");
                    }
                    done = true;
                }
                if (disposeRequested)
                {
                    done = true;
                    if (bundle != null)
                    {
                        // Completion acknowledges bundle ownership release. Unload(false)
                        // preserves a transferred texture for scheduler-managed retirement.
                        unloading = bundle.UnloadAsync(!transferred);
                        if (unloading == null) throw new InvalidOperationException("Cannot start authored bundle unload");
                    }
                    else released = true;
                    return false;
                }
                if (!done && bundle != null && loading == null && allowEngineStart)
                {
                    // Opening and loading are two separate engine starts, each admitted
                    // by the same one-start-per-frame scheduler gate.
                    started = true;
                    loading = bundle.LoadAssetAsync<Texture2D>(spec.AssetName);
                    if (loading == null) throw new InvalidOperationException("Cannot start authored texture load");
                }
            }
            catch (Exception ex)
            {
                if (error == null) error = ex;
                done = true; cancelRequested = true; disposeRequested = true;
                // Keep every request and bundle reference. Future pumps drain or retry
                // cleanup; no failure path forgets an in-flight engine allocation.
            }
            return started;
        }
        public Texture2D Take()
        {
            CheckThread();
            if (!done || error != null || cancelRequested || disposeRequested || transferred || value == null)
                throw new InvalidOperationException("Authored texture is not available for ownership transfer");
            transferred = true; return value;
        }
        public void Cancel()
        {
            CheckThread(); cancelRequested = true; disposeRequested = true;
        }
        public void Dispose()
        {
            CheckThread();
            // The scheduler retains and pumps this handle until IsReleased. A transfer
            // is permanent: later cancellation/disposal cannot destroy that texture.
            if (!transferred) cancelRequested = true;
            disposeRequested = true;
        }
    }
}
