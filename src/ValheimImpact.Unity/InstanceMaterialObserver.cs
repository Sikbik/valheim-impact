using System;
using System.Linq.Expressions;
using System.Reflection;
using UnityEngine;

namespace ValheimImpact.Unity
{
    internal interface IBoundedMaterialObserver
    {
        int MaximumWork { get; }
        int Observe(GameObject gameObject, out bool complete);
    }

    internal sealed class InstanceMaterialObserver : IBoundedMaterialObserver
    {
        private const int MaxComponents = 8;
        private readonly Type type;
        private readonly Func<Component, Material> material;
        private readonly Func<Component, Mesh> mesh;
        private readonly Action<Material> observe;
        public int MaximumWork { get { return MaxComponents + 1; } }

        internal static IBoundedMaterialObserver TryCreate(Action<Material> observe, Action<string> log)
        {
            try
            {
                Type type = Type.GetType("InstanceRenderer, assembly_valheim", false);
                if (type == null || type.FullName != "InstanceRenderer" || type.Assembly.GetName().Name != "assembly_valheim")
                    throw new InvalidOperationException("reviewed component type unavailable");
                return new InstanceMaterialObserver(type, observe);
            }
            catch (Exception error)
            {
                log("Instanced grass observation unavailable; ordinary Renderer bindings continue: " + error.Message);
                return null;
            }
        }

        // The internal constructor also accepts an inert fixture component type.
        // Production can reach it only through the exact assembly/type factory.
        internal InstanceMaterialObserver(Type type, Action<Material> observe)
        {
            if (type == null || type.IsAbstract || !typeof(MonoBehaviour).IsAssignableFrom(type) || observe == null)
                throw new ArgumentException("Concrete MonoBehaviour source and observation callback required");
            this.type = type; this.observe = observe;
            material = Getter<Material>(type, "m_material"); mesh = Getter<Mesh>(type, "m_mesh");
        }
        private static Func<Component, T> Getter<T>(Type type, string name) where T : UnityEngine.Object
        {
            FieldInfo field = type.GetField(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
            if (field == null || field.IsStatic || field.FieldType != typeof(T))
                throw new InvalidOperationException("Reviewed component field differs: " + name);
            var value = Expression.Parameter(typeof(Component), "component");
            return Expression.Lambda<Func<Component, T>>(Expression.Field(Expression.Convert(value, type), field), value).Compile();
        }
        public int Observe(GameObject gameObject, out bool complete)
        {
            complete = true;
            if (gameObject == null || !gameObject.activeInHierarchy) return 1;
            Component first;
            if (!gameObject.TryGetComponent(type, out first)) return 1;
            int count = gameObject.GetComponentCount();
            if (count < 1 || count > MaxComponents) { complete = false; return 1; }
            try
            {
                for (int index = 0; index < count; index++)
                {
                    Component component = gameObject.GetComponentAtIndex(index);
                    if (component == null || component.GetType() != type) continue;
                    var behaviour = component as Behaviour;
                    if (behaviour == null || !behaviour.isActiveAndEnabled) continue;
                    Mesh source = mesh(component);
                    if (source == null || source.subMeshCount < 1) continue;
                    Material value = material(component);
                    if (value != null) observe(value);
                }
                if (gameObject == null || gameObject.GetComponentCount() != count) complete = false;
            }
            catch (MissingReferenceException) { complete = false; }
            catch (ArgumentOutOfRangeException) { complete = false; }
            return count + 1;
        }
    }
}
