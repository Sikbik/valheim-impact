// Finite native ownership fixture. Compile with the current Core and Unity binder sources.
// The injected component is inert; no original game script or world is executed.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using ValheimImpact.Core;
using ValheimImpact.Unity;
using Object = UnityEngine.Object;

public sealed class GrassBindingFixtureSource : MonoBehaviour { public Material m_material; public Mesh m_mesh; }
public sealed class GrassBindingFixtureExtra : MonoBehaviour { }

public static class GrassBindingProbe
{
    const string BundleSha = "b18650b25088aeeffda57f11b8b29e3021856d27377574626d06e1b5d3e150c3";
    [Serializable] public sealed class Config { public string sourceBundle; public Dictionary<string,string> sourceHashes; }
    sealed class Load : IOwnedTextureLoad<Texture> {
        internal Texture Value; internal bool Ready=true, Released, Transferred;
        public bool IsDone { get { return Ready; } } public bool IsReleased { get { return Released; } }
        public Exception Error { get { return null; } } public bool Pump(bool allow) { return false; }
        public Texture Take() { Transferred=true; return Value; } public void Cancel() { Dispose(); } public void Dispose() { if(!Transferred && Value!=null)Object.DestroyImmediate(Value);Released=true; }
    }
    sealed class Case : IDisposable {
        internal OwnedMaterialBinder Binder; internal readonly List<GameObject> Objects=new List<GameObject>();
        internal readonly List<Object> Owned=new List<Object>(); internal readonly List<Load> Loads=new List<Load>();
        internal bool Ready=true; internal long Frame; internal double Seconds; internal readonly Scene Scene;
        internal Case(OwnedMaterialRegistry registry, Scene scene, bool observer=true) {
            Scene=scene;
            Binder=new OwnedMaterialBinder(registry,_=>{},spec=>{
                var texture=new Texture2D(4,4,TextureFormat.RGBA32,true,false) { name="owned grass fixture",hideFlags=HideFlags.HideAndDontSave };
                Owned.Add(texture); var load=new Load { Value=texture,Ready=Ready }; Loads.Add(load); return load;
            },texture=>Object.DestroyImmediate(texture),texture=>texture==null,
              observer?(Func<Action<Material>,IBoundedMaterialObserver>)(callback=>new InstanceMaterialObserver(typeof(GrassBindingFixtureSource),callback)):(callback=>null));
        }
        internal Material Copy(Material source) { var copy=new Material(source) { name=source.name,hideFlags=HideFlags.HideAndDontSave };Owned.Add(copy);return copy; }
        internal GameObject NewObject() { var value=new GameObject("Grass binding fixture") { hideFlags=HideFlags.HideAndDontSave };SceneManager.MoveGameObjectToScene(value,Scene);Objects.Add(value);return value; }
        internal GrassBindingFixtureSource Add(Material material,Mesh mesh,GameObject target=null) { if(target==null)target=NewObject();var source=target.AddComponent<GrassBindingFixtureSource>();source.m_material=material;source.m_mesh=mesh;return source; }
        internal Renderer Renderer(Material material) { var renderer=NewObject().AddComponent<MeshRenderer>();renderer.sharedMaterial=material;return renderer; }
        internal void Census() { foreach(var value in Objects) if(value!=null) Binder.ObserveGameObject(value);Binder.CompleteObservationPass(Seconds); }
        internal void Pump(int count=8) { for(int i=0;i<count;i++) { Frame++;Seconds+=.02;Binder.Tick(Frame,Seconds,false); } }
        public void Dispose() {
            Binder.Stop();Pump(16);bool normalDrain=Binder.IsDrained;
            foreach(var value in Objects)if(value!=null)Object.DestroyImmediate(value);
            for(int i=Owned.Count-1;i>=0;i--)if(Owned[i] is Material && Owned[i]!=null)Object.DestroyImmediate(Owned[i]);
            if(!normalDrain)Pump(16);
            for(int i=Owned.Count-1;i>=0;i--)if(Owned[i]!=null)Object.DestroyImmediate(Owned[i]);
            if(!normalDrain || !Binder.IsDrained)throw new InvalidOperationException("Fixture binder required emergency object cleanup instead of ordinary drain.");
        }
    }
    static Dictionary<string,object> Record(params object[] fields) { var result=new Dictionary<string,object>();for(int i=0;i<fields.Length;i+=2)result.Add((string)fields[i],fields[i+1]);return result; }
    static void Require(bool value,string message) { if(!value)throw new InvalidDataException(message); }
    static void Check(List<object> checks,string name,bool value) { checks.Add(Record("name",name,"passed",value));Require(value,name); }
    public static string Run(string configPath)
    {
        string output=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(configPath)),"binding-runs",DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffZ")+"-"+Guid.NewGuid().ToString("N").Substring(0,8));Directory.CreateDirectory(output);
        var checks=new List<object>();var errors=new List<string>();var warnings=new List<string>();
        var result=Record("passed",false,"checks",checks,"errors",errors,"warnings",warnings,"outputDirectory",output,"scope","Native material-slot ownership with original grass material clones and injected inert components. Diagnostic texture provider; no production bundle load, draw, game, world or art approval.");
        int[] sceneHandles=Enumerable.Range(0,SceneManager.sceneCount).Select(i=>SceneManager.GetSceneAt(i).handle).ToArray();
        bool[] dirty=Enumerable.Range(0,SceneManager.sceneCount).Select(i=>SceneManager.GetSceneAt(i).isDirty).ToArray();
        int activeScene=SceneManager.GetActiveScene().handle;int[] selection=Selection.instanceIDs.ToArray();int previewCount=EditorSceneManager.previewSceneCount;
        var bundlesBefore=new HashSet<int>(AssetBundle.GetAllLoadedAssetBundles().Select(b=>b.GetInstanceID()));
        RenderTexture target=RenderTexture.active;bool srgb=GL.sRGBWrite;Scene preview=default(Scene);AssetBundle ownedBundle=null;Material tall=null,shortGrass=null;
        Application.LogCallback log=(message,stack,type)=>{if(type==LogType.Error||type==LogType.Exception||type==LogType.Assert)errors.Add(message);else if(type==LogType.Warning)warnings.Add(message);};Application.logMessageReceived+=log;
        bool testsPassed=false;
        try {
            Require(!EditorApplication.isPlayingOrWillChangePlaymode && !EditorApplication.isCompiling && !EditorApplication.isUpdating,"Idle Edit Mode required.");
            Require(Application.unityVersion=="6000.0.75f1" && SystemInfo.graphicsDeviceType==GraphicsDeviceType.Vulkan && QualitySettings.activeColorSpace==ColorSpace.Linear && GraphicsSettings.currentRenderPipeline==null,"Reviewed native setup required.");
            Config config=JsonConvert.DeserializeObject<Config>(File.ReadAllText(configPath));Require(config!=null && config.sourceHashes!=null && config.sourceHashes.Count>0,"Pinned implementation sources required.");
            foreach(var source in config.sourceHashes)Require(Hash(source.Key)==source.Value,"Implementation source changed: "+source.Key);
            Require(Hash(config.sourceBundle)==BundleSha,"Original source bundle hash differs.");result["sourceHashes"]=config.sourceHashes;
            var loaded=AssetBundle.LoadFromFile(config.sourceBundle);Require(loaded!=null && !bundlesBefore.Contains(loaded.GetInstanceID()),"Cannot acquire an unborrowed source bundle.");ownedBundle=loaded;
            string tallPath=ExactName(ownedBundle,"assets/world/props/ground_clutter/models/materials/grasscross_meadows.mat");
            string shortPath=ExactName(ownedBundle,"assets/world/props/ground_clutter/models/materials/grasscross_meadows_short.mat");
            string meshPath=ExactName(ownedBundle,"assets/world/props/ground_clutter/models/grasscross_even.obj");
            tall=ownedBundle.LoadAsset<Material>(tallPath);shortGrass=ownedBundle.LoadAsset<Material>(shortPath);
            Mesh[] meshes=ownedBundle.LoadAssetWithSubAssets<Mesh>(meshPath);
            result["sourceIdentities"]=Record("tallPath",tallPath,"shortPath",shortPath,"meshPath",meshPath,
                "tall",MaterialIdentity(tall),"short",MaterialIdentity(shortGrass),"sameShader",tall!=null && shortGrass!=null && tall.shader==shortGrass.shader,
                "meshes",meshes==null?null:meshes.Select(value=>value==null?Record("null",true):Record("name",value.name,"vertices",value.vertexCount,"submeshes",value.subMeshCount)).ToArray());
            Require(tall!=null,"Tall material missing.");Require(shortGrass!=null,"Short material missing.");
            Require(tall.shader!=null && tall.shader==shortGrass.shader,"Original shader dependencies missing or different.");
            Require(tall.shader.name=="Custom/Grass" && tall.shader.isSupported,"Original shader name or native support differs.");
            Require(meshes!=null && meshes.Length==1 && meshes[0]!=null,"Expected one original mesh at exact OBJ selector.");
            Require(meshes[0].vertexCount==48 && meshes[0].subMeshCount==1 && meshes[0].GetIndexCount(0)==108 && meshes[0].GetBaseVertex(0)==0,"Original mesh topology differs from inspected source.");Mesh mesh=meshes[0];
            Texture originalTall=tall.GetTexture("_MainTex"), originalShort=shortGrass.GetTexture("_MainTex"), originalTerrain=tall.GetTexture("_TerrainColorTex");
            OwnedMaterialRegistry registry=Registry(output);preview=EditorSceneManager.NewPreviewScene();
            using(var run=new Case(registry,preview)) {
                Material a=run.Copy(tall),b=run.Copy(shortGrass);var one=run.Add(a,mesh);run.Add(b,mesh,one.gameObject);run.Census();run.Pump();
                Check(checks,"duplicate inert components admit both exact grass materials without a Renderer",a.GetTexture("_MainTex")!=originalTall && b.GetTexture("_MainTex")!=originalShort && run.Binder.Scheduler.LeaseCount==2);
                Check(checks,"shared owned payload uses one resident request",run.Loads.Count==1);
                var renderer=run.Renderer(a);one.enabled=false;run.Objects[0].GetComponentAtIndex<GrassBindingFixtureSource>(2).enabled=false;run.Census();run.Pump();
                Check(checks,"ordinary Renderer keeps the shared material demanded after instancer disable",a.GetTexture("_MainTex")!=originalTall && b.GetTexture("_MainTex")==originalShort && run.Binder.Scheduler.LeaseCount==1);
                renderer.enabled=false;run.Census();run.Pump();
                Check(checks,"last complete consumer census restores exact original slots",a.GetTexture("_MainTex")==originalTall && run.Binder.Scheduler.LeaseCount==0);
            }
            using(var run=new Case(registry,preview)) {
                Material a=run.Copy(tall);var source=run.Add(a,mesh);run.Census();run.Pump();Texture owned=a.GetTexture("_MainTex");
                source.enabled=false;var heavy=run.Add(a,mesh);for(int i=0;i<7;i++)heavy.gameObject.AddComponent<GrassBindingFixtureExtra>();run.Census();run.Pump();
                Check(checks,"an oversized instancer node cannot release unseen material ownership",a.GetTexture("_MainTex")==owned && run.Binder.Scheduler.LeaseCount==1 && run.Binder.SkippedCensusCount==1);
                run.Census();run.Pump();Check(checks,"recurring incomplete census retains bounded residency",a.GetTexture("_MainTex")==owned && run.Binder.Scheduler.LeaseCount==1 && run.Binder.SkippedCensusCount==2);
                heavy.gameObject.SetActive(false);run.Census();run.Pump();Check(checks,"a later complete census releases the retained demand",a.GetTexture("_MainTex")==originalTall && run.Binder.Scheduler.LeaseCount==0);
            }
            using(var run=new Case(registry,preview)) {
                Material a=run.Copy(tall),b=run.Copy(shortGrass);var source=run.Add(a,mesh);run.Census();run.Pump();source.m_material=b;run.Census();run.Pump();
                Check(checks,"component material reassignment restores the old material and adopts the new one",a.GetTexture("_MainTex")==originalTall && b.GetTexture("_MainTex")!=originalShort && run.Binder.Scheduler.LeaseCount==1);
            }
            foreach(bool beforeApply in new[]{true,false}) using(var run=new Case(registry,preview)) {
                run.Ready=!beforeApply;Material a=run.Copy(tall);run.Add(a,mesh);run.Census();run.Pump();a.SetFloat("_Cutoff",.5f);foreach(var load in run.Loads)load.Ready=true;run.Pump();
                Check(checks,"cutoff change "+(beforeApply?"before":"after")+" readiness preserves the changed state and original fallback",a.GetTexture("_MainTex")==originalTall && a.GetFloat("_Cutoff")==.5f && run.Binder.Scheduler.LeaseCount==0);
            }
            using(var run=new Case(registry,preview)) {
                Material a=run.Copy(tall);run.Add(a,mesh);run.Census();run.Pump();var foreign=new Texture2D(4,4);run.Owned.Add(foreign);a.SetTexture("_TerrainColorTex",foreign);run.Pump();
                Check(checks,"foreign terrain texture is preserved while only the owned MainTex is restored",a.GetTexture("_TerrainColorTex")==foreign && a.GetTexture("_MainTex")==originalTall && run.Binder.Scheduler.LeaseCount==0);
                a.SetTexture("_TerrainColorTex",originalTerrain);run.Census();run.Pump();Check(checks,"foreign suppression prevents automatic re-adoption",a.GetTexture("_MainTex")==originalTall && run.Binder.Scheduler.LeaseCount==0);
            }
            foreach(bool beforeApply in new[]{true,false}) using(var run=new Case(registry,preview)) {
                run.Ready=!beforeApply;Material a=run.Copy(tall);run.Add(a,mesh);run.Census();run.Pump();var foreign=new Texture2D(4,4);run.Owned.Add(foreign);a.SetTexture("_MainTex",foreign);foreach(var load in run.Loads)load.Ready=true;run.Pump();
                Check(checks,"foreign MainTex "+(beforeApply?"before":"after")+" readiness is never overwritten",a.GetTexture("_MainTex")==foreign && run.Binder.Scheduler.LeaseCount==0);
            }
            using(var run=new Case(registry,preview)) {
                Material a=run.Copy(tall);run.Add(a,mesh);run.Census();run.Pump();a.SetTextureOffset("_TerrainColorTex",new Vector2(.25f,0));run.Pump();
                Check(checks,"terrain UV changes release only the owned texture slot",a.GetTexture("_MainTex")==originalTall && a.GetTextureOffset("_TerrainColorTex").x==.25f && run.Binder.Scheduler.LeaseCount==0);
            }
            using(var run=new Case(registry,preview,false)) {
                Material a=run.Copy(tall);run.Add(a,mesh);var original=new Texture2D(4,4) { name="fixture_original" };run.Owned.Add(original);
                var opaque=new Material(Shader.Find("Standard")) { name="OpaqueFixture",hideFlags=HideFlags.HideAndDontSave };run.Owned.Add(opaque);opaque.SetTexture("_MainTex",original);run.Renderer(opaque);run.Census();run.Pump();
                Check(checks,"unavailable instancer support leaves ordinary Renderer binding operational",a.GetTexture("_MainTex")==originalTall && opaque.GetTexture("_MainTex")!=original && run.Binder.Scheduler.LeaseCount==1);
            }
            using(var run=new Case(registry,preview)) {
                var source=run.Add(run.Copy(tall),mesh);int observations=0;var observer=new InstanceMaterialObserver(typeof(GrassBindingFixtureSource),_=>observations++);bool complete;
                for(int i=0;i<32;i++)observer.Observe(source.gameObject,out complete);
                long before=GC.GetAllocatedBytesForCurrentThread();int largest=0;bool allComplete=true;
                for(int i=0;i<512;i++){int work=observer.Observe(source.gameObject,out complete);if(work>largest)largest=work;allComplete &= complete;}
                long allocated=GC.GetAllocatedBytesForCurrentThread()-before;result["observerAllocationBytesAfterWarmup"]=allocated;result["observerMaximumWork"]=largest;
                Check(checks,"steady observer scans remain complete and bounded",allComplete && largest<=observer.MaximumWork && observations==544);
                Check(checks,"steady observer scans allocate no managed bytes after warm-up",allocated==0);
            }
            Check(checks,"original loaded materials and dependencies remain unchanged",tall.GetTexture("_MainTex")==originalTall && shortGrass.GetTexture("_MainTex")==originalShort && tall.GetTexture("_TerrainColorTex")==originalTerrain && shortGrass.GetTexture("_TerrainColorTex")==originalTerrain && tall.GetFloat("_Cutoff")==.46f && shortGrass.GetFloat("_Cutoff")==.46f);
            testsPassed=errors.Count==0;
        }catch(Exception error){result["error"]=error.ToString();}
        finally {
            try { if(preview.IsValid())EditorSceneManager.ClosePreviewScene(preview); }catch(Exception error){errors.Add("Cleanup: "+error);}
            try { if(ownedBundle!=null)ownedBundle.Unload(true); }catch(Exception error){errors.Add("Cleanup: "+error);}
            Application.logMessageReceived-=log;
            bool scenesSame=sceneHandles.SequenceEqual(Enumerable.Range(0,SceneManager.sceneCount).Select(i=>SceneManager.GetSceneAt(i).handle)) && dirty.SequenceEqual(Enumerable.Range(0,SceneManager.sceneCount).Select(i=>SceneManager.GetSceneAt(i).isDirty)) && SceneManager.GetActiveScene().handle==activeScene;
            bool bundlesSame=bundlesBefore.SetEquals(AssetBundle.GetAllLoadedAssetBundles().Select(b=>b.GetInstanceID()));
            bool cleanup=scenesSame && bundlesSame && selection.SequenceEqual(Selection.instanceIDs) && EditorSceneManager.previewSceneCount==previewCount && RenderTexture.active==target && GL.sRGBWrite==srgb && tall==null && shortGrass==null;
            result["cleanupPassed"]=cleanup;result["passed"]=testsPassed && cleanup && errors.Count==0;File.WriteAllText(Path.Combine(output,"report.json"),JsonConvert.SerializeObject(result,Newtonsoft.Json.Formatting.Indented));
        }
        return JsonConvert.SerializeObject(result,Newtonsoft.Json.Formatting.Indented);
    }
    static OwnedMaterialRegistry Registry(string output)
    {
        string root=Path.Combine(output,"registry");Directory.CreateDirectory(Path.Combine(root,"assets"));string file=Path.Combine(root,"assets/fixture.bundle");File.WriteAllBytes(file,Encoding.ASCII.GetBytes("UnityFS\0private ownership provider fixture"));
        File.WriteAllText(Path.Combine(root,"profile.json"),JsonConvert.SerializeObject(Record("schemaVersion",1,"profile","Balanced","experimental",true,"enableGameReplacement",true,"residentMiB",16,"inFlightMiB",8,"concurrentRequests",1,"startsPerFrame",1)));
        File.WriteAllText(Path.Combine(root,"assets/catalog.json"),JsonConvert.SerializeObject(Record("schemaVersion",1,"editorVersion","6000.0.75f1","target","StandaloneLinux64","nativeReadback",true,"textures",new[]{Record("id","fixture","path","fixture.bundle","assetName","assets/fixture.asset","sha256",Hash(file),"payloadSha256",new string('a',64),"width",4,"height",4,"mipCount",3,"payloadBytes",48,"isSrgb",true)})));
        var rules=new List<object>();foreach(bool shortGrass in new[]{false,true}) {
            string suffix=shortGrass?"_short":"";int size=shortGrass?64:128;
            rules.Add(Record("id","grass"+suffix,"materialName","grasscross_meadows"+suffix,"shaderName","Custom/Grass","textureProperty","_MainTex","originalTextureName","grass_meadows"+suffix,"originalWidth",size,"originalHeight",size,"ownedTextureId","fixture","grass",Record("fixedPasses","Custom/Grass-v1","cutoff",.46,"renderQueue",2000,"terrainTextureName","grass_terrain_color","terrainWidth",1024,"terrainHeight",1024,"terrainColorScale",.01,"swayDistance",shortGrass?1:2.3,"pushDistance",shortGrass?.5:2)));
        }
        rules.Add(Record("id","ordinary","materialName","OpaqueFixture","shaderName","Standard","textureProperty","_MainTex","originalTextureName","fixture_original","originalWidth",4,"originalHeight",4,"ownedTextureId","fixture"));
        File.WriteAllText(Path.Combine(root,"assets/bindings.json"),JsonConvert.SerializeObject(Record("schemaVersion",3,"bindings",rules)));return OwnedMaterialRegistry.Load(root);
    }
    static string Hash(string path) { using(var stream=File.OpenRead(path))using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant(); }
    static object MaterialIdentity(Material value) { return value==null?Record("null",true):Record("name",value.name,"shader",value.shader==null?null:value.shader.name,"shaderSupported",value.shader!=null && value.shader.isSupported,"passes",value.passCount,"queue",value.renderQueue,"instancing",value.enableInstancing); }
    static string ExactName(AssetBundle bundle,string wanted) { string[] matches=bundle.GetAllAssetNames().Where(value=>string.Equals(value,wanted,StringComparison.OrdinalIgnoreCase)).ToArray();Require(matches.Length==1,"Exact container selector missing or ambiguous: "+wanted);return matches[0]; }
}
