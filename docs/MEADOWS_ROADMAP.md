# Meadows material roadmap

Meadows work is organized into five bounded batches, with current progress and remaining gates below. Exact serialized identities define each starting scope. A matching name or directory does not establish placed Meadows use or approval.

## 1. Beech bark family

Start from material `CAB-8923bd833c4171316cf3c761b642c1c8:3590192218068893260`. It binds albedo `CAB-8923bd833c4171316cf3c761b642c1c8:-7789706379099817400`, normal `CAB-8923bd833c4171316cf3c761b642c1c8:-3552050549463384350`, and shared moss `CAB-8923bd833c4171316cf3c761b642c1c8:-3043036005615678986`.

An authored 1024px atlas now fits the near and middle gameplay-tree bark slots, including the underside cap. These scopes have UV and native texture evidence. Correct affine UV inspection found that the 95px cut-end patch overlaps 9,025 distant trunk texels, so the distant mesh keeps original bark. Resolve that conflict and review logs, stumps, small trees, moss and normals before adding a shared binding. The standalone imported beech model has different material assignments and is not the gameplay tree. See [beech material candidates](BEECH_MATERIALS.md).

## 2. Meadows grass cards

Resolve materials `CAB-8923bd833c4171316cf3c761b642c1c8:1669900682560515117` and `CAB-8923bd833c4171316cf3c761b642c1c8:2753016777081159198` with albedos `CAB-8923bd833c4171316cf3c761b642c1c8:-6685763419340257079` and `CAB-8923bd833c4171316cf3c761b642c1c8:8723292681815040943`. Both use terrain color texture `CAB-8923bd833c4171316cf3c761b642c1c8:5952445177512870087`. Identify card meshes and cutoff state, then validate compressed alpha, both faces, wind, tint modulation, and distance transitions.

## 3. Beech leaf cards and LODs

Target material `CAB-8923bd833c4171316cf3c761b642c1c8:-695329477639400634`, albedo `CAB-8923bd833c4171316cf3c761b642c1c8:-3647773947989605833`, and normal `CAB-8923bd833c4171316cf3c761b642c1c8:3954888016727907068`. Review the three known blob meshes `CAB-8923bd833c4171316cf3c761b642c1c8:5636204498416708811`, `CAB-8923bd833c4171316cf3c761b642c1c8:-719559034922650275`, and `CAB-8923bd833c4171316cf3c761b642c1c8:521127269846282531`. A shared authored branch now produces 1024px and 512px candidates. All three large-tree and four small-tree/imported meshes have scoped front/rear UV review; both sizes pass native texture and diagnostic cutout sampling. Small foliage albedo `CAB-8923bd833c4171316cf3c761b642c1c8:-5355041863167301984` is included.

Remaining gates are companion normals, the unhealthy sapling cutoff 0.26 and tint, actual game shader, two-sided lighting, wind, and every LOD transition. The final 1x1 mip is transparent and fractional tail coverage falls, so distant appearance is not approved. Geometry is retained, not newly authored.

## 4. Terrain arrays

The live diffuse target is Texture2DArray `CAB-8923bd833c4171316cf3c761b642c1c8:-4418745866935824791`; its companion normal array is `CAB-8923bd833c4171316cf3c761b642c1c8:-3717166463683967554`. Current runtime replacement handles Texture2D albedo, so it cannot bind these arrays correctly. Determine slice order and exact Meadows layer semantics, then add explicit diffuse and normal Texture2DArray construction, loading, residency, restoration, and validation. Individual terrain source tiles are array-generation inputs, not substitutes for the serialized arrays.

## 5. Shoreline water discovery

Resolve the active water material and property roles before authoring or binding. Candidate exact textures are `CAB-8923bd833c4171316cf3c761b642c1c8:-189505297896212411`, `CAB-8923bd833c4171316cf3c761b642c1c8:-3900716686149641043`, `CAB-8923bd833c4171316cf3c761b642c1c8:-5943394016187327904`, `CAB-8923bd833c4171316cf3c761b642c1c8:-7324807522022545953`, `CAB-8923bd833c4171316cf3c761b642c1c8:-4427533950003945355`, `CAB-8923bd833c4171316cf3c761b642c1c8:-305452523777261620`, `CAB-8923bd833c4171316cf3c761b642c1c8:6475928566198691941`, and `CAB-8923bd833c4171316cf3c761b642c1c8:-1916312239383379176`. Record transforms, animation, foam roles, reflections, refraction, and shared global scope.

These batches advance material coverage without claiming a playable biome. Placed-world scope, companion channels, actual shaders, weather, streaming, measured performance, and final art review remain separate acceptance work.
