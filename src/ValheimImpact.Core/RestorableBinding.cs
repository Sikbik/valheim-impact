using System;
using System.Collections.Generic;

namespace ValheimImpact.Core
{
    public sealed class RestorableBinding<T> where T : class
    {
        public readonly string Name;
        public readonly T Fallback;
        public T Current { get; private set; }
        public bool Evicted { get; private set; }
        public RestorableBinding(string name, T fallback, T current)
        { Name = name; Fallback = fallback; Current = current; }
        public bool Release(Func<T> read, Action<T> write)
        {
            if (Evicted || !EqualityComparer<T>.Default.Equals(read(), Current)) return false;
            write(Fallback);
            Evicted = true;
            return true;
        }
        public bool Restore(Func<T> read, Action<T> write, Func<string, T> load)
        {
            if (!Evicted || !EqualityComparer<T>.Default.Equals(read(), Fallback)) return false;
            T texture = load(Name);
            if (texture == null) throw new InvalidOperationException("Texture reload returned null: " + Name);
            write(texture);
            Current = texture;
            Evicted = false;
            return true;
        }
    }
}
