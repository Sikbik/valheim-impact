#!/usr/bin/env python3
"""Inspect configured biome membership without loading or modifying the game.

Run from the repository root with the inspection Python environment. All output
stays under local/. The supplied immutable inventory pins known bundle bytes;
new location bundles from the regular manifest are reported separately.

The extractor retains selected serialized bundle readers and hierarchy metadata
until exit; inspection memory scales with those inputs. It never decodes
original texture pixels or mesh vertex buffers. Configuration is not proof of
active spawning, artwork approval, or biome completion.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current directory)",
    )
    parser.add_argument("--inventory", type=Path, help="Immutable local inventory JSON")
    parser.add_argument(
        "--game",
        type=Path,
        help="Game installation root; defaults to inventory game_root",
    )
    parser.add_argument(
        "--output", type=Path, help="Output directory under repository local/"
    )
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    sys.path.insert(0, str(root))
    import UnityPy
    from tools.texture_inventory import pointer_key, parse_manifest, validate_output

    inventory_path = (
        (args.inventory or root / "local/texture-inventory/complete/inventory.json")
        .expanduser()
        .resolve()
    )
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = hashlib.sha256(inventory_bytes).hexdigest()
    inventory = json.loads(inventory_bytes)
    game_root = (args.game or Path(inventory["game_root"])).expanduser().resolve()
    game = game_root / "valheim_Data/StreamingAssets/SoftRef/Bundles"
    output = validate_output(args.output or root / "local/biome-inventory", game_root)
    if not output.is_relative_to(root / "local"):
        raise ValueError("Keep inspection outputs under local/")
    catalog_path = root / "assets/status/catalog.json"
    catalog_bytes = catalog_path.read_bytes()
    catalog_sha256 = hashlib.sha256(catalog_bytes).hexdigest()
    catalog_document = json.loads(catalog_bytes)
    if catalog_document["inventory_sha256"] != inventory_sha256:
        raise ValueError("Catalog and supplied inventory identities differ")
    output.mkdir(parents=True, exist_ok=True)
    for filename in (
        "configured-associations.json",
        "counts.json",
        "membership-sources.json",
        "discovery-evidence.json",
    ):
        destination = output / filename
        if destination.is_symlink() or (
            destination.exists() and not destination.is_file()
        ):
            raise ValueError("Expected a regular local output file")
    known_bundles = {b["name"]: b for b in inventory["input_bundles"]}
    bundle_evidence = []
    catalog = {a["id"] for a in catalog_document["assets"]}
    biomes = {
        1: "meadows",
        2: "swamp",
        4: "mountains",
        8: "black-forest",
        16: "plains",
        32: "ashlands",
        64: "deep-north",
        256: "ocean",
        512: "mistlands",
    }
    # Labels and masks verified from serialized m_biomes and m_biomeEnvironments.
    files = {}
    loaded_environments = []
    rows = []
    trees = {}
    parent = {}
    go_names = {}
    go_components = {}
    containers = {}
    cab_bundles = {}
    renderer_trees = {}
    for key in ("renderers", "textures", "meshes", "materials"):
        for r in inventory[key]:
            cab_bundles.setdefault(r["serialized_file"], r["sources"][0])

    def load(name):
        if name in [n for n, e in loaded_environments]:
            return
        if not name or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in name
        ):
            raise ValueError("Unsafe bundle name")
        bundle = game / name
        if not bundle.is_file() or bundle.is_symlink():
            raise ValueError("Expected a regular bundle")
        h = hashlib.sha256()
        with bundle.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                h.update(chunk)
        expected = known_bundles.get(name, {}).get("sha256")
        if expected is not None and h.hexdigest() != expected:
            raise ValueError("Bundle differs from pinned inventory: " + name)
        bundle_evidence.append(
            {
                "name": name,
                "sha256": h.hexdigest(),
                "in_prior_inventory": expected is not None,
            }
        )
        print("LOAD", name, flush=True)
        env = UnityPy.load(str(bundle))
        loaded_environments.append((name, env))
        for o in env.objects:
            cab = o.assets_file.name
            files[cab] = o.assets_file
            if o.type.name not in (
                "GameObject",
                "Transform",
                "RectTransform",
                "MonoBehaviour",
                "MeshRenderer",
                "SkinnedMeshRenderer",
                "ParticleSystemRenderer",
                "MeshFilter",
            ):
                continue
            d = o.read_typetree()
            key = f"{cab}:{o.path_id}"
            trees[key] = d
            if o.type.name in (
                "MeshRenderer",
                "SkinnedMeshRenderer",
                "ParticleSystemRenderer",
            ):
                renderer_trees[key] = d
            if o.type.name == "GameObject":
                go_names[key] = d["m_Name"]
                go_components[key] = [
                    pointer_key(o.assets_file, c["component"]) for c in d["m_Component"]
                ]
            if o.type.name in ("Transform", "RectTransform"):
                parent[key] = pointer_key(o.assets_file, d.get("m_Father"))
        for path, p in env.container.items():
            containers[path] = f"{p.assetsfile.name}:{p.path_id}"
        print("LOADED", name, len(trees), flush=True)

    def pointer(cab, p):
        return pointer_key(files[cab], p)

    system_bundles = {
        a["bundle"]
        for a in inventory["manifest_assets"]
        if a["path"]
        in (
            "Assets/Systems/_ZoneSystem.prefab",
            "Assets/Systems/_GameMain.prefab",
            "Assets/Systems/_ZoneCtrl.prefab",
        )
    }
    if not system_bundles:
        raise ValueError("System prefabs are absent from the inventory manifest")
    for name in sorted(system_bundles):
        load(name)

    # A recursive walk finds spawn records nested in named list wrappers too.
    def walk(d, path=""):
        if isinstance(d, dict):
            if isinstance(d.get("m_biome"), int) and (
                "m_prefab" in d or "m_prefabName" in d
            ):
                yield path, d
            for k, v in d.items():
                yield from walk(v, path + "/" + k)
        elif isinstance(d, list):
            for i, v in enumerate(d):
                yield from walk(v, path + "/" + str(i))

    system_cabs = {
        containers[path].rsplit(":", 1)[0]
        for path in (
            "Assets/Systems/_ZoneSystem.prefab",
            "Assets/Systems/_GameMain.prefab",
        )
    }
    zone_control = containers["Assets/Systems/_ZoneCtrl.prefab"]
    spawn_lists = set()
    for component in go_components[zone_control]:
        cd = trees.get(component, {})
        for ptr in cd.get("m_spawnLists", []):
            spawn_lists.add(pointer(component.rsplit(":", 1)[0], ptr))
    for key, d in list(trees.items()):
        if "m_Script" not in d:
            continue
        if key.rsplit(":", 1)[0] not in system_cabs and key not in spawn_lists:
            continue
        go = pointer(key.rsplit(":", 1)[0], d["m_GameObject"])
        label = go_names.get(go, "")
        # Prefer the standalone catalogued ZoneSystem. The second serialized clone
        # is retained separately in discovery, avoiding duplicate configuration rows.
        if (
            "m_vegetation" in d
            and label == "_ZoneSystem"
            and go != containers["Assets/Systems/_ZoneSystem.prefab"]
        ):
            continue
        for path, a in walk(d):
            mask = a["m_biome"]
            names = [name for bit, name in biomes.items() if mask & bit]
            if not names:
                continue
            if "vegetation" in path.lower():
                kind = "vegetation"
            elif "/m_clutter/" in path:
                kind = "clutter"
            elif "location" in path.lower() or "m_prefabName" in a:
                kind = "location"
            else:
                kind = "spawn"
            prefab = a.get("m_prefab", {})
            target = (
                pointer(key.rsplit(":", 1)[0], prefab) if "m_PathID" in prefab else None
            )
            if key in spawn_lists:
                context = "ordinary spawn list"
            elif "/m_alts/" in path:
                context = "alternate configuration"
            elif "/m_events/" in path:
                context = "event spawn list"
            else:
                context = "configured " + kind
            rows.append(
                dict(
                    id=key + path,
                    kind=kind,
                    label=label
                    + " ("
                    + context
                    + "): "
                    + a.get("m_name", a.get("m_prefabName", path)),
                    biomes=names,
                    asset_ids=[],
                    enabled=bool(a.get("m_enable", a.get("m_enabled", True)))
                    and not bool(a.get("m_devDisabled", False)),
                    dev_disabled=bool(a.get("m_devDisabled", False)),
                    prefab_id=target,
                    soft_reference=prefab if target is None else None,
                    biome_mask=mask,
                )
            )
    manifest_path = game.parent / "manifest"
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    soft_assets = {
        a["asset_id"]: a for a in parse_manifest(manifest_bytes.decode("utf-8-sig"))
    }
    for row in rows:
        if (
            not row["prefab_id"]
            and row["soft_reference"]
            and "m_assetID" in row["soft_reference"]
        ):
            raw = row["soft_reference"]["m_assetID"]
            guid = "".join(f"{raw[k]:08x}" for k in ("v3", "v2", "v1", "v0"))
            mapped = soft_assets.get(guid)
            if mapped:
                load(mapped["bundle"])
                row["prefab_id"] = containers.get(mapped["path"])
                row["softref_guid"] = guid
                row["softref_path"] = mapped["path"]
    for cab in sorted(
        {r["prefab_id"].rsplit(":", 1)[0] for r in rows if r["prefab_id"]}
    ):
        if cab not in files:
            load(cab_bundles[cab])
    # Match renderer GameObjects to every ancestor using exact Transform PPtrs.
    go_transform = {}
    for key, d in trees.items():
        if "m_Father" in d and "m_GameObject" in d:
            go_transform[pointer(key.rsplit(":", 1)[0], d["m_GameObject"])] = key
    renderers = defaultdict(list)
    all_renderers = {r["id"]: r for r in inventory["renderers"]}
    for key, d in renderer_trees.items():
        cab = key.rsplit(":", 1)[0]
        go = pointer(cab, d["m_GameObject"])
        mesh = d.get("m_Mesh")
        if mesh is None:
            for component in go_components.get(go, []):
                cd = trees.get(component, {})
                if "m_Mesh" in cd:
                    mesh = cd["m_Mesh"]
                    break
        all_renderers[key] = {
            "id": key,
            "game_object_id": go,
            "mesh_id": pointer(cab, mesh) if mesh else None,
            "material_ids": [pointer(cab, m) for m in d.get("m_Materials", [])],
        }
    for r in all_renderers.values():
        go = r["game_object_id"]
        tr = go_transform.get(go)
        seen = set()
        while tr and tr not in seen:
            seen.add(tr)
            d = trees.get(tr)
            if d is None:
                break
            renderers[pointer(tr.rsplit(":", 1)[0], d["m_GameObject"])].append(r)
            tr = parent.get(tr)
    materials = {m["id"]: m for m in inventory["materials"]}

    def refs(d, cab):
        if isinstance(d, dict):
            if "m_PathID" in d and "m_FileID" in d:
                yield pointer(cab, d)
            else:
                for value in d.values():
                    yield from refs(value, cab)
        elif isinstance(d, list):
            for value in d:
                yield from refs(value, cab)

    direct = defaultdict(set)
    for key, d in trees.items():
        if "m_GameObject" not in d:
            continue
        cab = key.rsplit(":", 1)[0]
        go = pointer(cab, d["m_GameObject"])
        assets = set()
        for ref in refs(d, cab):
            if ref in catalog:
                assets.add(ref)
            if ref in materials:
                assets.update(
                    t["texture_id"]
                    for t in materials[ref]["textures"]
                    if t["texture_id"] in catalog
                )
        tr = go_transform.get(go)
        seen = set()
        while tr and tr not in seen:
            seen.add(tr)
            td = trees.get(tr)
            if td is None:
                break
            direct[pointer(tr.rsplit(":", 1)[0], td["m_GameObject"])].update(assets)
            tr = parent.get(tr)
    for row in rows:
        assets = set(direct.get(row["prefab_id"], []))
        for r in renderers.get(row["prefab_id"], []):
            if r["mesh_id"] in catalog:
                assets.add(r["mesh_id"])
            for mat in r["material_ids"]:
                for t in materials.get(mat, {}).get("textures", []):
                    if t["texture_id"] in catalog:
                        assets.add(t["texture_id"])
        row["asset_ids"] = sorted(assets)
        row["renderer_count"] = len(renderers.get(row["prefab_id"], []))
    report = {
        "schema_version": 1,
        "catalog_sha256": catalog_sha256,
        "softref_manifest_sha256": manifest_sha256,
        "inventory_sha256": inventory_sha256,
        "scope": "Serialized configured biome associations, including disabled entries. No runtime or artwork approval. Unresolved soft references remain explicit.",
        "sources": rows,
    }
    (output / "configured-associations.json").write_text(json.dumps(report, indent=2))
    summary = {
        "rows": len(rows),
        "with_assets": sum(bool(r["asset_ids"]) for r in rows),
        "kinds": dict(Counter(r["kind"] for r in rows)),
        "biomes": {
            b: len({a for r in rows if b in r["biomes"] for a in r["asset_ids"]})
            for b in biomes.values()
        },
        "unresolved_soft": sum(r["prefab_id"] is None for r in rows),
    }
    (output / "counts.json").write_text(json.dumps(summary, indent=2))
    print(summary, flush=True)

    projection = {
        k: report[k]
        for k in ("schema_version", "catalog_sha256", "inventory_sha256", "scope")
    }
    projection["sources"] = [
        {k: r[k] for k in ("id", "kind", "label", "biomes", "asset_ids")}
        for r in rows
        if r["asset_ids"]
    ]
    (output / "membership-sources.json").write_text(
        json.dumps(projection, indent=2) + "\n"
    )
    evidence = {
        k: report[k]
        for k in (
            "schema_version",
            "catalog_sha256",
            "inventory_sha256",
            "softref_manifest_sha256",
        )
    }
    evidence.update(
        ordinary_spawn_lists=sorted(spawn_lists),
        bundles=sorted(bundle_evidence, key=lambda b: b["name"]),
        configured_rows=len(rows),
        joined_rows=len(projection["sources"]),
        disabled_rows=sum(not r["enabled"] for r in rows),
        distinct_assets=len({a for r in rows for a in r["asset_ids"]}),
        unresolved_rows=[
            {
                "id": r["id"],
                "kind": r["kind"],
                "label": r["label"],
                "enabled": r["enabled"],
                "prefab_id": r["prefab_id"],
                "reason": (
                    "Unresolved prefab reference"
                    if r["prefab_id"] is None
                    else "No catalog texture or mesh reference reached"
                ),
            }
            for r in rows
            if not r["asset_ids"]
        ],
        limitations=[
            "Configured references include disabled and alternate-biome content. They do not prove active spawning.",
            "Membership uses direct descendant renderer and component mesh, texture, and material references. It does not recursively classify item drops or arbitrary gameplay prefab links.",
            "A catalog asset may participate in several biomes. Membership does not grant artwork or runtime approval.",
        ],
    )
    (output / "discovery-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
