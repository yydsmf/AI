#!/usr/bin/env python3
"""Build a compact, self-contained GLB library for the Blender director stage.

Run with Blender 2.93 or newer:
    blender --background --python scripts/build_three_kingdoms_asset_library.py -- \
        --source-root /path/to/source_packs --library-root /path/to/library
"""

import argparse
import csv
import json
import os
import shutil
import sys
import traceback
import uuid
from datetime import datetime
from pathlib import Path


CATEGORY_NAMES = {
    "architecture": "\u57ce\u6c60\u5efa\u7b51",
    "dungeon": "\u5730\u4e0b\u7a7a\u95f4",
    "furniture": "\u5ba4\u5185\u9648\u8bbe",
    "terrain": "\u5730\u5f62\u6c34\u7cfb",
    "vegetation": "\u6811\u6728\u690d\u88ab",
    "rocks": "\u5c71\u77f3\u5047\u5c71",
    "animals": "\u9a6c\u5339\u52a8\u7269",
    "props": "\u8425\u5e10\u4e0e\u9053\u5177",
}

PACKS = (
    {
        "id": "kaykit_medieval",
        "name": "KayKit Medieval Hexagon Pack",
        "root": "KayKit-Medieval-Hexagon-Pack-1.0",
        "patterns": ("**/*.obj",),
        "default_category": "architecture",
        "license": "CC0-1.0",
        "source_url": "https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0",
    },
    {
        "id": "kaykit_dungeon",
        "name": "KayKit Dungeon Remastered",
        "root": "KayKit-Dungeon-Remastered-1.0",
        "patterns": ("**/*.glb",),
        "default_category": "dungeon",
        "license": "CC0-1.0",
        "source_url": "https://github.com/KayKit-Game-Assets/KayKit-Dungeon-Remastered-1.0",
    },
    {
        "id": "kaykit_furniture",
        "name": "KayKit Furniture Bits",
        "root": "KayKit-Furniture-Bits-1.0",
        "patterns": ("**/*.gltf",),
        "default_category": "furniture",
        "license": "CC0-1.0",
        "source_url": "https://github.com/KayKit-Game-Assets/KayKit-Furniture-Bits-1.0",
    },
    {
        "id": "kenney_nature",
        "name": "Kenney Nature Kit",
        "root": "Kenney-Nature-Kit",
        # Blender 2.93 cannot read the pack's legacy ASCII FBX files. The STL
        # variants preserve the blocking geometry and are converted to GLB.
        "patterns": ("Models/STL format/**/*.stl",),
        "default_category": "terrain",
        "license": "CC0-1.0",
        "source_url": "https://kenney.nl/assets/nature-kit",
    },
    {
        "id": "quaternius_horses",
        "name": "Quaternius Ultimate Animated Animals - Horses",
        "root": "Quaternius-Ultimate-Animated-Animals-Horses",
        "patterns": ("*.gltf", "*.glb"),
        "default_category": "animals",
        "license": "CC0-1.0",
        "source_url": "https://quaternius.com/packs/ultimateanimatedanimal.html",
    },
)

VEGETATION_WORDS = (
    "tree", "bush", "grass", "plant", "flower", "crop", "bamboo",
    "moss", "mushroom", "cactus", "leaf", "pine", "palm",
)
ROCK_WORDS = ("rock", "stone", "boulder")
TERRAIN_WORDS = (
    "ground", "river", "water", "cliff", "platform", "path", "beach",
    "hill", "slope", "cave",
)
ARCHITECTURE_WORDS = (
    "building", "wall", "tower", "gate", "bridge", "house", "market",
    "tavern", "stage", "scaffold", "castle", "roof", "stairs",
)


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--library-root", required=True)
    parser.add_argument("--max-per-pack", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def category_for(pack, source_path):
    text = (source_path.stem + " " + str(source_path.parent)).lower()
    if pack["id"] == "quaternius_horses":
        return "animals"
    if any(word in text for word in VEGETATION_WORDS):
        return "vegetation"
    if any(word in text for word in ROCK_WORDS):
        return "rocks"
    if any(word in text for word in TERRAIN_WORDS):
        return "terrain"
    if any(word in text for word in ARCHITECTURE_WORDS):
        return "architecture"
    if pack["id"] == "kenney_nature":
        return "props"
    return pack["default_category"]


def discover_pack_files(source_root, pack):
    pack_root = source_root / pack["root"]
    paths = []
    for pattern in pack["patterns"]:
        paths.extend(pack_root.glob(pattern))
    unique = []
    seen = set()
    for path in sorted(paths):
        resolved = str(path.resolve())
        if not path.is_file() or resolved in seen:
            continue
        if "/.git/" in resolved.replace(os.sep, "/"):
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def reset_blender_scene(bpy):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.curves, bpy.data.armatures,
                       bpy.data.materials, bpy.data.images, bpy.data.actions):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def import_asset(bpy, source_path):
    lower = source_path.name.lower()
    if lower.endswith((".gltf", ".glb")):
        bpy.ops.import_scene.gltf(filepath=str(source_path))
    elif lower.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=str(source_path))
    elif lower.endswith(".obj"):
        bpy.ops.import_scene.obj(filepath=str(source_path))
    elif lower.endswith(".stl"):
        bpy.ops.import_mesh.stl(filepath=str(source_path))
    else:
        raise RuntimeError("Unsupported source format: " + source_path.suffix)


def export_glb(bpy, target_path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(target_path),
        export_format="GLB",
        export_animations=True,
    )


def apply_blocking_material(bpy, category_id, source_path):
    source_name = source_path.stem.lower()
    colors = {
        "architecture": (0.34, 0.28, 0.22, 1.0),
        "dungeon": (0.24, 0.25, 0.27, 1.0),
        "furniture": (0.32, 0.20, 0.12, 1.0),
        "terrain": (0.28, 0.21, 0.12, 1.0),
        "vegetation": (0.14, 0.36, 0.10, 1.0),
        "rocks": (0.32, 0.34, 0.36, 1.0),
        "animals": (0.28, 0.16, 0.08, 1.0),
        "props": (0.30, 0.20, 0.11, 1.0),
    }
    color = colors.get(category_id, (0.35, 0.35, 0.35, 1.0))
    if "river" in source_name or "water" in source_name:
        color = (0.08, 0.28, 0.48, 1.0)
    material = bpy.data.materials.new("GPT_Blocking_" + category_id)
    material.diffuse_color = color
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if obj.data.materials:
            obj.data.materials[0] = material
        else:
            obj.data.materials.append(material)


def convert_asset(bpy, source_path, target_path, category_id):
    reset_blender_scene(bpy)
    import_asset(bpy, source_path)
    if not bpy.data.objects:
        raise RuntimeError("Import created no Blender objects")
    if source_path.suffix.lower() == ".stl":
        apply_blocking_material(bpy, category_id, source_path)
    export_glb(bpy, target_path)
    return {
        "object_count": len(bpy.data.objects),
        "mesh_count": len(bpy.data.meshes),
        "armature_count": len(bpy.data.armatures),
        "action_count": len(bpy.data.actions),
    }


def write_catalog_file(library_root):
    lines = ["VERSION 1", ""]
    for key, name in CATEGORY_NAMES.items():
        catalog_id = uuid.uuid5(uuid.NAMESPACE_URL, "gpt-toolbox-three-kingdoms/" + key)
        lines.append(f"{catalog_id}:{name}:{name}")
    (library_root / "blender_assets.cats.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def copy_license_files(source_root, library_root):
    target_dir = library_root / "LICENSES"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for pack in PACKS:
        pack_root = source_root / pack["root"]
        candidates = sorted(
            path for path in pack_root.rglob("*")
            if path.is_file() and ("license" in path.name.lower() or "copying" in path.name.lower())
        )
        if not candidates:
            continue
        source = candidates[0]
        target = target_dir / (pack["id"] + source.suffix.lower())
        shutil.copy2(str(source), str(target))
        copied.append(str(target))
    return copied


def write_manifests(library_root, records, errors, licenses):
    summary = {
        "library_name": "GPT Toolbox Three Kingdoms Blocking Assets",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "format": "GLB",
        "blender_compatibility": ">=2.93",
        "asset_count": len(records),
        "error_count": len(errors),
        "total_bytes": sum(int(item.get("size") or 0) for item in records),
        "licenses": licenses,
        "categories": {
            CATEGORY_NAMES[key]: sum(1 for item in records if item.get("category_id") == key)
            for key in CATEGORY_NAMES
        },
        "assets": records,
        "errors": errors,
    }
    (library_root / "asset_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fieldnames = (
        "display_name", "category", "pack", "license", "format", "size",
        "object_count", "mesh_count", "armature_count", "action_count",
        "relative_path", "source_path", "source_url",
    )
    with (library_root / "asset_manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in fieldnames})
    return summary


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[sys.argv.index("--") + 1:])
    source_root = Path(args.source_root).expanduser().resolve()
    library_root = Path(args.library_root).expanduser().resolve()
    library_root.mkdir(parents=True, exist_ok=True)

    import bpy

    records = []
    errors = []
    for pack in PACKS:
        paths = discover_pack_files(source_root, pack)
        if args.max_per_pack > 0:
            paths = paths[:args.max_per_pack]
        print(f"ASSET_PACK {pack['id']} {len(paths)}", flush=True)
        for index, source_path in enumerate(paths, 1):
            category_id = category_for(pack, source_path)
            category_name = CATEGORY_NAMES[category_id]
            target_name = pack["id"] + "__" + source_path.stem + ".glb"
            target_path = library_root / category_name / target_name
            try:
                stats = {}
                if target_path.exists() and target_path.stat().st_size > 0 and not args.force:
                    status = "existing"
                elif source_path.suffix.lower() == ".glb":
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(source_path), str(target_path))
                    status = "copied"
                else:
                    stats = convert_asset(bpy, source_path, target_path, category_id)
                    status = "converted"
                record = {
                    "id": pack["id"] + "__" + source_path.stem,
                    "display_name": source_path.stem,
                    "category_id": category_id,
                    "category": category_name,
                    "pack": pack["name"],
                    "pack_id": pack["id"],
                    "license": pack["license"],
                    "format": "glb",
                    "size": target_path.stat().st_size,
                    "relative_path": str(target_path.relative_to(library_root)),
                    "source_path": str(source_path),
                    "source_url": pack["source_url"],
                    "status": status,
                }
                record.update(stats)
                records.append(record)
                print(f"ASSET_OK {pack['id']} {index}/{len(paths)} {source_path.name}", flush=True)
            except Exception as exc:
                errors.append({
                    "pack_id": pack["id"],
                    "source_path": str(source_path),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                })
                print(f"ASSET_ERROR {pack['id']} {source_path.name}: {exc}", flush=True)

    write_catalog_file(library_root)
    licenses = copy_license_files(source_root, library_root)
    summary = write_manifests(library_root, records, errors, licenses)
    print("ASSET_SUMMARY " + json.dumps({
        "asset_count": summary["asset_count"],
        "error_count": summary["error_count"],
        "total_bytes": summary["total_bytes"],
        "categories": summary["categories"],
    }, ensure_ascii=False), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
