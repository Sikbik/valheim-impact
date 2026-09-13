# Meadows material roadmap

Meadows work is organized into five bounded batches, with current progress and remaining gates below. Exact serialized identities define each starting scope. A matching name or directory does not establish placed Meadows use or approval.

## 1. Beech bark family

Start from material `CAB-8923bd833c4171316cf3c761b642c1c8:3590192218068893260`. It binds albedo `CAB-8923bd833c4171316cf3c761b642c1c8:-7789706379099817400`, normal `CAB-8923bd833c4171316cf3c761b642c1c8:-3552050549463384350`, and shared moss `CAB-8923bd833c4171316cf3c761b642c1c8:-3043036005615678986`.

Follow-up inspection resolves 20 consumers across ten meshes. The earlier patch sits on a downward root cap; the exposed stump top occupies a different island. New 1024px studies separate continuous standing-tree bark from a fitted stump atlas, avoiding a shared cut patch that bleeds into distant trunk mips. Logs use their own albedo and material and form a separate work batch. Original alpha, moss, companion normals and material-specific runtime binding remain open. The standalone imported beech model has different material assignments and is not the gameplay tree. See [beech material candidates](BEECH_MATERIALS.md).

The separate log batch now has a fitted 1024px source and 1024/512px candidates
for albedo `CAB-8923bd833c4171316cf3c761b642c1c8:410654931012585407`. Both log
variants share one material and one retained mesh. Their side seam and two end
islands are mapped explicitly. Twelve original-material frames cover both
scales and quality candidates at 1080p and 4K. The original normal remains a
comparison control, with an authored companion and world review still pending.
The other 165 users of the mesh remain outside scope. See
[beech logs](BEECH_LOGS.md) for fitting and remaining acceptance work.

## 2. Meadows grass cards

Resolved materials `CAB-8923bd833c4171316cf3c761b642c1c8:1669900682560515117` and `CAB-8923bd833c4171316cf3c761b642c1c8:2753016777081159198` use albedos `CAB-8923bd833c4171316cf3c761b642c1c8:-6685763419340257079` and `CAB-8923bd833c4171316cf3c761b642c1c8:8723292681815040943`. Authored neutral-white cutouts now fit their six-card mesh, with tall 512/256px and short 256/128px candidates. Both use terrain color texture `CAB-8923bd833c4171316cf3c761b642c1c8:5952445177512870087`, cutoff 0.46 and an instanced drawing path. Review instanced integration, compressed alpha, both faces under the actual shader, wind, tint modulation and distance transitions. See [Meadows grass](MEADOWS_GRASS.md).

## 3. Beech leaf cards and LODs

Target material `CAB-8923bd833c4171316cf3c761b642c1c8:-695329477639400634`, albedo `CAB-8923bd833c4171316cf3c761b642c1c8:-3647773947989605833`, and normal `CAB-8923bd833c4171316cf3c761b642c1c8:3954888016727907068`. Review the three known blob meshes `CAB-8923bd833c4171316cf3c761b642c1c8:5636204498416708811`, `CAB-8923bd833c4171316cf3c761b642c1c8:-719559034922650275`, and `CAB-8923bd833c4171316cf3c761b642c1c8:521127269846282531`. A shared authored branch now produces 1024px and 512px candidates. All three large-tree and four small-tree/imported meshes have scoped front/rear UV review; both sizes pass native texture and diagnostic cutout sampling. Small foliage albedo `CAB-8923bd833c4171316cf3c761b642c1c8:-5355041863167301984` is included.

Remaining gates are companion normals, the unhealthy sapling cutoff 0.26 and tint, actual game shader, two-sided lighting, wind, and every LOD transition. The final 1x1 mip is transparent and fractional tail coverage falls, so distant appearance is not approved. Geometry is retained, not newly authored.

## 4. Terrain arrays

The live diffuse target is Texture2DArray `CAB-8923bd833c4171316cf3c761b642c1c8:-4418745866935824791`; its companion normal array is `CAB-8923bd833c4171316cf3c761b642c1c8:-3717166463683967554`. Current runtime replacement handles Texture2D albedo, so it cannot bind these arrays correctly. Determine slice order and exact Meadows layer semantics, then add explicit diffuse and normal Texture2DArray construction, loading, residency, restoration, and validation. Individual terrain source tiles are array-generation inputs, not substitutes for the serialized arrays.

## 5. Shoreline water discovery

Resolve the active water material and property roles before authoring or binding. Candidate exact textures are `CAB-8923bd833c4171316cf3c761b642c1c8:-189505297896212411`, `CAB-8923bd833c4171316cf3c761b642c1c8:-3900716686149641043`, `CAB-8923bd833c4171316cf3c761b642c1c8:-5943394016187327904`, `CAB-8923bd833c4171316cf3c761b642c1c8:-7324807522022545953`, `CAB-8923bd833c4171316cf3c761b642c1c8:-4427533950003945355`, `CAB-8923bd833c4171316cf3c761b642c1c8:-305452523777261620`, `CAB-8923bd833c4171316cf3c761b642c1c8:6475928566198691941`, and `CAB-8923bd833c4171316cf3c761b642c1c8:-1916312239383379176`. Record transforms, animation, foam roles, reflections, refraction, and shared global scope.

These batches advance material coverage without claiming a playable biome. Placed-world scope, companion channels, actual shaders, weather, streaming, measured performance, and final art review remain separate acceptance work.
