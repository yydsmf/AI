import csv
import hashlib
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from html import escape
from pathlib import Path

from .core import APP_DIR
from .optional_components import (
    OptionalComponentError,
    blender_asset_cache_path,
    ensure_blender_assets,
)


DIRECTOR_PROJECT_ROOT = os.path.join(APP_DIR, "blender_director_projects")
BUNDLED_MANNEQUIN_FILENAME = "wooden_mannequin_rigged_293.blend"
BUNDLED_MANNEQUIN_ATTRIBUTION_FILENAME = "WOODEN_MANNEQUIN_ATTRIBUTION.md"
BUNDLED_FURNITURE_FILENAME = "modern_furniture_pack_293.blend"
BUNDLED_FURNITURE_ATTRIBUTION_FILENAME = "MODERN_FURNITURE_ATTRIBUTION.md"
BUNDLED_FURNITURE_SOFA_COLLECTION = "Director Modern Sofa"
BUNDLED_FURNITURE_TABLE_COLLECTION = "Director Modern Coffee Table"


def _default_shared_director_asset_library():
    candidates = [
        str(os.environ.get("GPT_TOOLBOX_SHARED_ASSET_LIBRARY") or "").strip(),
        "/srv/gpt-data/assets/three_kingdoms/library",
    ]
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return ""


def _local_blender_resource_path(filename):
    filename = str(filename or "").strip()
    package_path = Path(__file__).resolve().parent / "resources" / "blender" / filename
    candidates = [package_path]
    bundle_root = str(getattr(sys, "_MEIPASS", "") or "").strip()
    if bundle_root:
        candidates.insert(0, Path(bundle_root) / "gpt_desktop" / "resources" / "blender" / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return package_path


def _bundled_blender_resource_path(filename, progress_callback=None):
    local_path = _local_blender_resource_path(filename)
    if local_path.exists():
        return local_path
    cached_path = blender_asset_cache_path(filename)
    if cached_path.exists():
        return cached_path
    try:
        ensure_blender_assets(progress_callback=progress_callback)
    except OptionalComponentError as exc:
        raise RuntimeError(f"准备 Blender 导演台资源失败：{exc}") from exc
    return blender_asset_cache_path(filename)


def blender_director_resources_available():
    return all(
        _local_blender_resource_path(filename).exists()
        or blender_asset_cache_path(filename).exists()
        for filename in (
            BUNDLED_MANNEQUIN_FILENAME,
            BUNDLED_MANNEQUIN_ATTRIBUTION_FILENAME,
            BUNDLED_FURNITURE_FILENAME,
            BUNDLED_FURNITURE_ATTRIBUTION_FILENAME,
        )
    )


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_bundled_mannequin_assets(character_assets_dir, progress_callback=None):
    character_assets_dir = str(character_assets_dir or "").strip()
    if not character_assets_dir:
        raise RuntimeError("导演台人物资产目录不可用。")
    os.makedirs(character_assets_dir, exist_ok=True)
    source_blend = _bundled_blender_resource_path(BUNDLED_MANNEQUIN_FILENAME, progress_callback)
    source_attribution = _bundled_blender_resource_path(BUNDLED_MANNEQUIN_ATTRIBUTION_FILENAME, progress_callback)
    if not source_blend.exists():
        raise RuntimeError("缺少内置骨骼人偶资源：" + str(source_blend))
    target_blend = Path(character_assets_dir) / BUNDLED_MANNEQUIN_FILENAME
    target_attribution = Path(character_assets_dir) / BUNDLED_MANNEQUIN_ATTRIBUTION_FILENAME
    if not target_blend.exists() or _file_sha256(source_blend) != _file_sha256(target_blend):
        shutil.copy2(source_blend, target_blend)
    if source_attribution.exists():
        if not target_attribution.exists() or source_attribution.read_bytes() != target_attribution.read_bytes():
            shutil.copy2(source_attribution, target_attribution)
    return {
        "path": str(target_blend),
        "attribution_path": str(target_attribution),
        "source_path": str(source_blend),
        "sha256": _file_sha256(target_blend),
    }


def _copy_bundled_furniture_assets(prop_assets_dir, progress_callback=None):
    prop_assets_dir = str(prop_assets_dir or "").strip()
    if not prop_assets_dir:
        raise RuntimeError("导演台道具资产目录不可用。")
    os.makedirs(prop_assets_dir, exist_ok=True)
    source_blend = _bundled_blender_resource_path(BUNDLED_FURNITURE_FILENAME, progress_callback)
    source_attribution = _bundled_blender_resource_path(BUNDLED_FURNITURE_ATTRIBUTION_FILENAME, progress_callback)
    if not source_blend.exists():
        raise RuntimeError("缺少内置现代家具资源：" + str(source_blend))
    target_blend = Path(prop_assets_dir) / BUNDLED_FURNITURE_FILENAME
    target_attribution = Path(prop_assets_dir) / BUNDLED_FURNITURE_ATTRIBUTION_FILENAME
    if not target_blend.exists() or _file_sha256(source_blend) != _file_sha256(target_blend):
        shutil.copy2(source_blend, target_blend)
    if source_attribution.exists():
        if not target_attribution.exists() or source_attribution.read_bytes() != target_attribution.read_bytes():
            shutil.copy2(source_attribution, target_attribution)
    return {
        "path": str(target_blend),
        "attribution_path": str(target_attribution),
        "source_path": str(source_blend),
        "sha256": _file_sha256(target_blend),
    }


def _default_director_asset_pack():
    return [
        {
            "id": "builtin_blue_mannequin",
            "name": "蓝色 IK/FK 骨骼人偶",
            "type": "character",
            "format": "blend",
            "license": "CC-BY",
            "author": "jgilhutton / Juan Ignacio",
            "source_url": "https://blendswap.com/blend/13034",
            "controls": ["root_empty", "viewport_control_ring", "armature", "ik_fk", "hand_foot_controls", "object_mode_pose_proxies", "color_coded_controls", "object_motion", "pose_snapshot"],
            "description": "Blender 2.93 骨骼人偶，保留手脚 IK、肘膝 Pole、IK/FK、骨盆、胸腔和头部控制器，并提供对象模式可直接拖动的彩色控制器。",
        },
        {
            "id": "builtin_red_mannequin",
            "name": "红色 IK/FK 骨骼人偶",
            "type": "character",
            "format": "blend",
            "license": "CC-BY",
            "author": "jgilhutton / Juan Ignacio",
            "source_url": "https://blendswap.com/blend/13034",
            "controls": ["root_empty", "viewport_control_ring", "armature", "ik_fk", "hand_foot_controls", "object_mode_pose_proxies", "color_coded_controls", "object_motion", "pose_snapshot"],
            "description": "用于正反打、对话和对峙分镜的第二演员位，可在对象模式直接拖动彩色手脚与肘膝控制器摆姿势。",
        },
        {
            "id": "builtin_lounge_set",
            "name": "专业双人沙发茶几布景",
            "type": "scene",
            "format": "blend",
            "license": "CC0",
            "author": "LauroVictorDesign / Neobox",
            "source_url": "https://blendswap.com/blend/26538 | https://blendswap.com/blend/27096",
            "controls": ["set_package", "scene_preset", "object_template"],
            "description": "一键搭出双人对话场景：真实软包双人沙发、几何茶几、深色网格导演台、三点布光和可调机位。",
        },
        {
            "id": "builtin_sofa_table_props",
            "name": "现代软包沙发与几何茶几",
            "type": "prop",
            "format": "blend",
            "license": "CC0",
            "author": "LauroVictorDesign / Neobox",
            "source_url": "https://blendswap.com/blend/26538 | https://blendswap.com/blend/27096",
            "controls": ["select_asset", "register_selected_asset", "object_template"],
            "description": "Blender 2.93 原生材质家具，可通过根控制器直接拖动、旋转、缩放，也可登记为工程道具资产。",
        },
    ]


def _default_open_asset_source_profiles():
    return [
        {
            "id": "blenderkit",
            "name": "BlenderKit / 本地 BlenderKit 缓存",
            "formats": ["blend", "fbx", "obj", "glb", "gltf", "stl", "ply", "abc", "usd", "usdz"],
            "route": "把下载后的本地目录作为资产库扫描；保留原始授权信息。",
        },
        {
            "id": "blender_asset_browser",
            "name": "Blender Asset Browser / 本地资产库",
            "formats": ["blend"],
            "route": "扫描 Blender 原生资产库目录，读取 blender_assets.cats.txt 目录编目并保留 Catalog 信息。",
        },
        {
            "id": "poly_haven",
            "name": "Poly Haven / HDRI 与 CC0 资产",
            "formats": ["blend", "fbx", "obj", "glb", "gltf", "stl", "ply", "abc", "usd", "usdz", "hdr", "exr"],
            "route": "用于场景、灯光、HDRI、材质目录的本地导入和归档。",
        },
        {
            "id": "ambientcg",
            "name": "ambientCG / CC0 材质",
            "formats": ["png", "jpg", "exr", "blend"],
            "route": "作为材质贴图目录管理，后续可绑定到材质模板。",
        },
        {
            "id": "mixamo",
            "name": "Mixamo / 角色动作",
            "formats": ["fbx", "bvh"],
            "route": "作为动作库扫描，导入后可套到选中演员骨骼或记录为动作资产。",
        },
        {
            "id": "sketchfab_opengameart",
            "name": "Sketchfab / OpenGameArt 本地下载库",
            "formats": ["blend", "fbx", "obj", "glb", "gltf", "stl", "ply", "abc", "usd", "usdz"],
            "route": "作为人物、道具、场景资产库扫描；按目录关键词自动推断资产类型。",
        },
    ]


def _merge_default_records(existing, defaults):
    existing = existing if isinstance(existing, list) else []
    merged = [dict(item) for item in existing if isinstance(item, dict)]
    seen = {str(item.get("id") or "") for item in merged if isinstance(item, dict)}
    for item in defaults:
        item_id = str(item.get("id") or "")
        if item_id and item_id in seen:
            continue
        merged.append(dict(item))
        if item_id:
            seen.add(item_id)
    return merged


def _safe_name(text, fallback="director_project"):
    text = str(text or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._ ")
    return text[:48] or fallback


def _safe_project_id(project_id):
    project_id = re.sub(r"[^a-zA-Z0-9_-]+", "", str(project_id or ""))
    return project_id[:64] or uuid.uuid4().hex


def prepare_blender_director_project(project_id="", project_name="", plan=None, component_progress=None):
    """Create/update the local Blender director project bridge files."""
    project_id = _safe_project_id(project_id)
    project_name = str(project_name or "").strip() or "AI短剧导演台"
    plan = plan if isinstance(plan, dict) else {}

    project_dir = os.path.join(DIRECTOR_PROJECT_ROOT, project_id)
    scripts_dir = os.path.join(project_dir, "scripts")
    renders_dir = os.path.join(project_dir, "renders")
    assets_dir = os.path.join(project_dir, "assets")
    shots_dir = os.path.join(project_dir, "shots")
    presets_dir = os.path.join(project_dir, "presets")
    set_packages_dir = os.path.join(project_dir, "set_packages")
    asset_dirs = {
        "characters": os.path.join(assets_dir, "characters"),
        "props": os.path.join(assets_dir, "props"),
        "scenes": os.path.join(assets_dir, "scenes"),
        "actions": os.path.join(assets_dir, "actions"),
        "models": os.path.join(assets_dir, "models"),
        "materials": os.path.join(assets_dir, "materials"),
        "textures": os.path.join(assets_dir, "textures"),
        "hdris": os.path.join(assets_dir, "hdris"),
    }
    for path in (project_dir, scripts_dir, renders_dir, assets_dir, shots_dir, presets_dir, set_packages_dir, *asset_dirs.values()):
        os.makedirs(path, exist_ok=True)
    bundled_mannequin = _copy_bundled_mannequin_assets(
        asset_dirs["characters"], progress_callback=component_progress
    )
    bundled_furniture = _copy_bundled_furniture_assets(
        asset_dirs["props"], progress_callback=component_progress
    )
    default_asset_library_path = _default_shared_director_asset_library()

    blend_path = os.path.join(project_dir, f"{_safe_name(project_name)}.blend")
    meta_path = os.path.join(project_dir, "director_project.json")
    addon_path = os.path.join(scripts_dir, "gpt_director_panel.py")
    bootstrap_path = os.path.join(scripts_dir, "open_director_project.py")
    batch_render_script_path = os.path.join(scripts_dir, "run_pending_renders.py")
    batch_render_command_path = os.path.join(project_dir, "batch_render_command.json")
    batch_render_command_report_path = os.path.join(project_dir, "batch_render_command.html")

    metadata = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                metadata.update(loaded)
        except Exception:
            metadata = {}
    metadata.update(
        {
            "project_id": project_id,
            "project_name": project_name,
            "blend_path": blend_path,
            "project_dir": project_dir,
            "assets_dir": assets_dir,
            "asset_dirs": asset_dirs,
            "shots_dir": shots_dir,
            "presets_dir": presets_dir,
            "set_packages_dir": set_packages_dir,
            "renders_dir": renders_dir,
            "addon_path": addon_path,
            "bootstrap_path": bootstrap_path,
            "batch_render_script_path": batch_render_script_path,
            "batch_render_command_path": batch_render_command_path,
            "batch_render_command_report_path": batch_render_command_report_path,
            "bundled_mannequin": bundled_mannequin,
            "bundled_furniture": bundled_furniture,
            "default_asset_library_path": default_asset_library_path,
            "plan": plan,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    if not isinstance(metadata.get("shots"), list):
        metadata["shots"] = []
    if not isinstance(metadata.get("shot_packages"), list):
        metadata["shot_packages"] = []
    if not isinstance(metadata.get("set_packages"), list):
        metadata["set_packages"] = []
    if not isinstance(metadata.get("assets"), list):
        metadata["assets"] = []
    if not isinstance(metadata.get("actors"), list):
        metadata["actors"] = []
    if not isinstance(metadata.get("asset_libraries"), list):
        metadata["asset_libraries"] = []
    if not isinstance(metadata.get("asset_library_items"), list):
        metadata["asset_library_items"] = []
    if not isinstance(metadata.get("asset_sources"), list):
        metadata["asset_sources"] = []
    if not isinstance(metadata.get("shot_asset_preparations"), list):
        metadata["shot_asset_preparations"] = []
    if not isinstance(metadata.get("ai_workflow_results"), list):
        metadata["ai_workflow_results"] = []
    if not isinstance(metadata.get("renders"), list):
        metadata["renders"] = []
    if not isinstance(metadata.get("render_templates"), list):
        metadata["render_templates"] = []
    if not isinstance(metadata.get("action_applications"), list):
        metadata["action_applications"] = []
    if not isinstance(metadata.get("action_clips"), list):
        metadata["action_clips"] = []
    if not isinstance(metadata.get("retarget_profiles"), list):
        metadata["retarget_profiles"] = []
    if not isinstance(metadata.get("retarget_applications"), list):
        metadata["retarget_applications"] = []
    if not isinstance(metadata.get("pose_templates"), list):
        metadata["pose_templates"] = []
    if not isinstance(metadata.get("animation_templates"), list):
        metadata["animation_templates"] = []
    if not isinstance(metadata.get("material_templates"), list):
        metadata["material_templates"] = []
    if not isinstance(metadata.get("material_applications"), list):
        metadata["material_applications"] = []
    if not isinstance(metadata.get("light_templates"), list):
        metadata["light_templates"] = []
    if not isinstance(metadata.get("camera_motions"), list):
        metadata["camera_motions"] = []
    if not isinstance(metadata.get("camera_templates"), list):
        metadata["camera_templates"] = []
    if not isinstance(metadata.get("object_templates"), list):
        metadata["object_templates"] = []
    if not isinstance(metadata.get("object_motions"), list):
        metadata["object_motions"] = []
    if not isinstance(metadata.get("scene_presets"), list):
        metadata["scene_presets"] = []
    metadata.pop("depth_estimator_script_path", None)
    metadata.pop("scene_references", None)
    metadata["builtin_asset_pack"] = _merge_default_records(
        metadata.get("builtin_asset_pack"),
        _default_director_asset_pack(),
    )
    metadata["open_asset_source_profiles"] = _merge_default_records(
        metadata.get("open_asset_source_profiles"),
        _default_open_asset_source_profiles(),
    )
    metadata["director_capabilities"] = {
        "version": 2,
        "mode": "real_blender_director_stage",
        "asset_formats": ["blend", "glb", "gltf", "fbx", "obj", "bvh", "stl", "ply", "abc", "usd", "usdz", "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "exr", "hdr"],
        "asset_kinds": ["character", "prop", "scene", "action", "model", "material", "texture", "hdri"],
        "control_model": ["root_empty", "viewport_control_ring", "armature", "ik_fk", "hand_foot_controls", "object_mode_pose_proxies", "color_coded_controls", "actor_slots", "object_templates", "camera_templates", "texture_materials", "action_clips", "retarget_profiles"],
        "built_in_scene_operator": "gpt_director.add_dialogue_lounge_scene",
        "open_ecosystem": [item["id"] for item in _default_open_asset_source_profiles()],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    with open(addon_path, "w", encoding="utf-8") as f:
        f.write(
            _director_panel_script(
                meta_path,
                blend_path,
                renders_dir,
                assets_dir,
                shots_dir,
                presets_dir,
                set_packages_dir,
                asset_dirs,
                default_asset_library_path,
            )
        )
    with open(bootstrap_path, "w", encoding="utf-8") as f:
        f.write(_director_bootstrap_script(blend_path, addon_path, meta_path))
    with open(batch_render_script_path, "w", encoding="utf-8") as f:
        f.write(_director_batch_render_script(blend_path, addon_path, meta_path))
    legacy_depth_script = os.path.join(scripts_dir, "generate_scene_depth_map.py")
    if os.path.exists(legacy_depth_script):
        try:
            os.remove(legacy_depth_script)
        except OSError:
            pass
    write_blender_director_batch_render_command(metadata)

    return {
        "project_id": project_id,
        "project_name": project_name,
        "project_dir": project_dir,
        "blend_path": blend_path,
        "meta_path": meta_path,
        "addon_path": addon_path,
        "bootstrap_path": bootstrap_path,
        "batch_render_script_path": batch_render_script_path,
        "batch_render_command_path": batch_render_command_path,
        "batch_render_command_report_path": batch_render_command_report_path,
        "renders_dir": renders_dir,
        "assets_dir": assets_dir,
        "shots_dir": shots_dir,
        "presets_dir": presets_dir,
        "set_packages_dir": set_packages_dir,
        "asset_dirs": asset_dirs,
        "mannequin_asset_path": bundled_mannequin.get("path", ""),
        "mannequin_attribution_path": bundled_mannequin.get("attribution_path", ""),
        "furniture_asset_path": bundled_furniture.get("path", ""),
        "furniture_attribution_path": bundled_furniture.get("attribution_path", ""),
    }


def load_blender_director_metadata(project):
    meta_path = ""
    if isinstance(project, dict):
        meta_path = str(project.get("meta_path") or "").strip()
    else:
        meta_path = str(project or "").strip()
    if not meta_path or not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_preview_image_path(path):
    path = str(path or "").strip().lower()
    return path.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))


def build_blender_director_storyboard(metadata):
    if not isinstance(metadata, dict):
        return []
    shots = metadata.get("shots") if isinstance(metadata.get("shots"), list) else []
    renders = metadata.get("renders") if isinstance(metadata.get("renders"), list) else []
    renders_by_shot = {}
    for render in renders:
        if not isinstance(render, dict):
            continue
        shot_id = str(render.get("shot_id") or "").strip()
        if shot_id:
            renders_by_shot[shot_id] = render

    entries = []
    for index, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("id") or "").strip()
        render = renders_by_shot.get(shot_id, {})
        preview_path = ""
        output_path = ""
        layer_paths = {}
        manifest_path = ""
        if isinstance(render, dict) and render:
            preview_path = str(render.get("preview_path") or "").strip()
            path = str(render.get("path") or "").strip()
            output_path = str(render.get("output_path") or path).strip()
            layer_paths = render.get("layer_paths") if isinstance(render.get("layer_paths"), dict) else {}
            manifest_path = str(render.get("manifest_path") or "").strip()
            if not preview_path and _is_preview_image_path(path):
                preview_path = path
        entries.append(
            {
                "index": index,
                "shot_id": shot_id,
                "shot_name": str(shot.get("name") or shot_id or f"镜头{index:02d}"),
                "note": str(shot.get("note") or ""),
                "episode_number": str(shot.get("episode_number") or shot.get("episode") or ""),
                "episode_name": str(shot.get("episode_name") or ""),
                "scene_number": str(shot.get("scene_number") or ""),
                "scene_location": str(shot.get("scene_location") or ""),
                "scene_environment": str(shot.get("scene_environment") or ""),
                "scene_environment_label": str(shot.get("scene_environment_label") or shot.get("scene_environment") or ""),
                "scene_time": str(shot.get("scene_time") or ""),
                "scene_time_label": str(shot.get("scene_time_label") or shot.get("scene_time") or ""),
                "shot_status": str(shot.get("shot_status") or ""),
                "shot_status_label": str(shot.get("shot_status_label") or shot.get("shot_status") or ""),
                "frame": shot.get("frame"),
                "frame_start": shot.get("frame_start"),
                "frame_end": shot.get("frame_end"),
                "fps": shot.get("fps"),
                "fps_base": shot.get("fps_base"),
                "output_type": str(shot.get("output_type") or ""),
                "output_label": str(shot.get("output_label") or shot.get("output_type") or ""),
                "camera": shot.get("camera") if isinstance(shot.get("camera"), dict) else {},
                "actors": shot.get("actors") if isinstance(shot.get("actors"), list) else [],
                "assets": shot.get("assets") if isinstance(shot.get("assets"), list) else [],
                "preview_path": preview_path,
                "output_path": output_path,
                "layer_paths": layer_paths,
                "manifest_path": manifest_path,
                "render_version": render.get("render_version") if isinstance(render, dict) else None,
                "last_rendered_at": str(render.get("created_at") or shot.get("last_rendered_at") or "")
                if isinstance(render, dict)
                else str(shot.get("last_rendered_at") or ""),
            }
        )
    return entries


def _storyboard_project_dir(metadata):
    if not isinstance(metadata, dict):
        return ""
    project_dir = str(metadata.get("project_dir") or "").strip()
    if not project_dir:
        meta_path = str(metadata.get("meta_path") or "").strip()
        if meta_path:
            project_dir = os.path.dirname(meta_path)
    return project_dir


def _file_uri(path):
    path = str(path or "").strip()
    if not path:
        return ""
    try:
        return Path(path).expanduser().resolve().as_uri()
    except Exception:
        return ""


def _batch_render_launcher_paths(metadata):
    metadata = metadata if isinstance(metadata, dict) else {}
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return {}
    scripts_dir = str(metadata.get("scripts_dir") or os.path.join(project_dir, "scripts"))
    return {
        "project_dir": project_dir,
        "scripts_dir": scripts_dir,
        "script_path": str(metadata.get("batch_render_script_path") or os.path.join(scripts_dir, "run_pending_renders.py")),
        "command_path": str(metadata.get("batch_render_command_path") or os.path.join(project_dir, "batch_render_command.json")),
        "report_path": str(metadata.get("batch_render_command_report_path") or os.path.join(project_dir, "batch_render_command.html")),
        "addon_path": str(metadata.get("addon_path") or os.path.join(scripts_dir, "gpt_director_panel.py")),
        "blend_path": str(metadata.get("blend_path") or ""),
        "meta_path": str(metadata.get("meta_path") or os.path.join(project_dir, "director_project.json")),
    }


def build_blender_director_batch_render_command(metadata):
    paths = _batch_render_launcher_paths(metadata)
    if not paths:
        return {}
    jobs = build_blender_director_batch_render_jobs(metadata if isinstance(metadata, dict) else {})
    command_template = '"<Blender可执行文件>" --background "{blend_path}" --python "{script_path}"'.format(
        blend_path=paths.get("blend_path") or "",
        script_path=paths.get("script_path") or "",
    )
    return {
        "project_id": str((metadata or {}).get("project_id") or "") if isinstance(metadata, dict) else "",
        "project_name": str((metadata or {}).get("project_name") or "Blender 导演台工程") if isinstance(metadata, dict) else "Blender 导演台工程",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "pending",
        "script_path": paths.get("script_path") or "",
        "command_path": paths.get("command_path") or "",
        "report_path": paths.get("report_path") or "",
        "blend_path": paths.get("blend_path") or "",
        "addon_path": paths.get("addon_path") or "",
        "meta_path": paths.get("meta_path") or "",
        "command_template": command_template,
        "job_count": int(jobs.get("job_count") or 0),
        "ready_count": int(jobs.get("ready_count") or 0),
        "blocked_count": int(jobs.get("blocked_count") or 0),
    }


def write_blender_director_batch_render_command(metadata):
    paths = _batch_render_launcher_paths(metadata)
    if not paths:
        return {}
    os.makedirs(paths["scripts_dir"], exist_ok=True)
    os.makedirs(paths["project_dir"], exist_ok=True)
    script_path = paths["script_path"]
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(_director_batch_render_script(paths.get("blend_path") or "", paths.get("addon_path") or "", paths.get("meta_path") or ""))
    data = build_blender_director_batch_render_command(metadata)
    command_path = paths["command_path"]
    with open(command_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    command_text = str(data.get("command_template") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 后台批量渲染命令</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .muted {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    pre {{ white-space: pre-wrap; word-break: break-all; background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; margin-top: 14px; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 后台批量渲染命令</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('job_count') or 0)}</strong>待渲染任务</div>
      <div class="stat"><strong>{int(data.get('ready_count') or 0)}</strong>可渲染</div>
      <div class="stat"><strong>{int(data.get('blocked_count') or 0)}</strong>需补信息</div>
    </div>
    <div class="muted">将 &lt;Blender可执行文件&gt; 替换成当前机器的 Blender 程序路径即可后台渲染待渲染镜头。</div>
    <pre>{escape(command_text)}</pre>
    <table>
      <thead><tr><th>文件</th><th>路径</th></tr></thead>
      <tbody>
        <tr><td>后台脚本</td><td>{escape(str(data.get('script_path') or ''))}</td></tr>
        <tr><td>Blender 工程</td><td>{escape(str(data.get('blend_path') or ''))}</td></tr>
        <tr><td>元数据</td><td>{escape(str(data.get('meta_path') or ''))}</td></tr>
      </tbody>
    </table>
  </main>
</body>
</html>
"""
    report_path = paths["report_path"]
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    data["script_path"] = script_path
    data["command_path"] = command_path
    data["report_path"] = report_path
    return data


def write_blender_director_storyboard_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "storyboard_manifest.json")
    data = {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entries": build_blender_director_storyboard(metadata),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_storyboard_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    entries = build_blender_director_storyboard(metadata)
    project_name = str(metadata.get("project_name") or "Blender 导演台工程")
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for item in entries:
        preview_path = str(item.get("preview_path") or "").strip()
        output_path = str(item.get("output_path") or "").strip()
        preview_uri = _file_uri(preview_path) if preview_path and os.path.exists(preview_path) else ""
        output_uri = _file_uri(output_path) if output_path and os.path.exists(output_path) else ""
        preview_html = (
            f'<a href="{escape(preview_uri)}"><img src="{escape(preview_uri)}" alt="preview"></a>'
            if preview_uri
            else '<span class="muted">无预览</span>'
        )
        output_html = (
            f'<a href="{escape(output_uri)}">{escape(os.path.basename(output_path) or output_path)}</a>'
            if output_uri
            else escape(output_path or "未输出")
        )
        layer_paths = item.get("layer_paths") if isinstance(item.get("layer_paths"), dict) else {}
        layer_labels = []
        for layer_name, layer_path in layer_paths.items():
            layer_name = str(layer_name or "").strip()
            layer_path = str(layer_path or "").strip()
            if not layer_name:
                continue
            layer_uri = _file_uri(layer_path) if layer_path and os.path.exists(layer_path) else ""
            if layer_uri:
                layer_labels.append(f'<a href="{escape(layer_uri)}">{escape(layer_name)}</a>')
            else:
                layer_labels.append(escape(layer_name))
        manifest_path = str(item.get("manifest_path") or "").strip()
        manifest_uri = _file_uri(manifest_path) if manifest_path and os.path.exists(manifest_path) else ""
        if manifest_uri:
            layer_labels.append(f'<a href="{escape(manifest_uri)}">manifest</a>')
        elif manifest_path:
            layer_labels.append("manifest")
        layer_text = "、".join(layer_labels)
        frame_start = item.get("frame_start")
        frame_end = item.get("frame_end")
        frame_text = f"{frame_start}-{frame_end}" if frame_start is not None and frame_end is not None else ""
        status_text = str(item.get("shot_status_label") or item.get("shot_status") or "")
        render_version = item.get("render_version")
        if render_version not in (None, ""):
            status_text = (status_text + " · " if status_text else "") + "v" + escape(str(render_version))
        actors = item.get("actors") if isinstance(item.get("actors"), list) else []
        actor_labels = []
        for actor in actors:
            if not isinstance(actor, dict):
                continue
            name = str(actor.get("name") or actor.get("id") or "").strip()
            role = str(actor.get("role") or "").strip()
            if name and role:
                actor_labels.append(f"{name}（{role}）")
            elif name:
                actor_labels.append(name)
        actor_text = "、".join(actor_labels)
        assets = item.get("assets") if isinstance(item.get("assets"), list) else []
        asset_labels = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or asset.get("id") or "").strip()
            asset_type = str(asset.get("type") or "").strip()
            if name and asset_type:
                asset_labels.append(f"{name}（{asset_type}）")
            elif name:
                asset_labels.append(name)
        asset_text = "、".join(asset_labels)
        rows.append(
            "<tr>"
            f"<td>{int(item.get('index') or 0)}</td>"
            f"<td><strong>{escape(str(item.get('shot_name') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('scene_number') or ''))}<div class=\"id\">{escape(str(item.get('scene_location') or ''))}</div></td>"
            f"<td>{escape(str(item.get('note') or ''))}</td>"
            f"<td>{escape(status_text)}</td>"
            f"<td>{escape(actor_text)}</td>"
            f"<td>{escape(asset_text)}</td>"
            f"<td>{escape(frame_text)}</td>"
            f"<td>{escape(str(item.get('output_label') or item.get('output_type') or ''))}</td>"
            f"<td>{layer_text}</td>"
            f"<td>{preview_html}</td>"
            f"<td>{output_html}</td>"
            f"<td>{escape(str(item.get('last_rendered_at') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="13" class="empty">暂无镜头，请先在 Blender 导演台保存镜头。</td></tr>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 分镜表</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta {{ color: #96a3b7; margin-bottom: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; position: sticky; top: 0; }}
    img {{ width: 180px; max-height: 105px; object-fit: contain; background: #0b0e13; border: 1px solid #313948; }}
    a {{ color: #7dc4ff; text-decoration: none; }}
    .id, .muted {{ color: #8b96a8; font-size: 12px; margin-top: 4px; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 32px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 分镜表</h1>
    <div class="meta">镜头 {len(entries)} 个 · 更新于 {escape(updated_at)}</div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>镜头</th>
          <th>场次/地点</th>
          <th>备注</th>
          <th>状态/版本</th>
          <th>演员</th>
          <th>资产</th>
          <th>帧段</th>
          <th>输出</th>
          <th>素材层</th>
          <th>预览</th>
          <th>文件</th>
          <th>渲染时间</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "storyboard_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def write_blender_director_storyboard_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "storyboard.csv")
    entries = build_blender_director_storyboard(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "序号",
                "镜头ID",
                "镜头名",
                "场次",
                "地点",
                "内外景",
                "日夜",
                "备注",
                "状态",
                "演员",
                "资产",
                "起始帧",
                "结束帧",
                "输出类型",
                "预览图",
                "输出文件",
                "渲染时间",
            ]
        )
        for item in entries:
            actors = item.get("actors") if isinstance(item.get("actors"), list) else []
            actor_text = "、".join(
                str(actor.get("name") or actor.get("id") or "").strip()
                for actor in actors
                if isinstance(actor, dict) and str(actor.get("name") or actor.get("id") or "").strip()
            )
            assets = item.get("assets") if isinstance(item.get("assets"), list) else []
            asset_text = "、".join(
                str(asset.get("name") or asset.get("id") or "").strip()
                for asset in assets
                if isinstance(asset, dict) and str(asset.get("name") or asset.get("id") or "").strip()
            )
            writer.writerow(
                [
                    item.get("index") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("scene_number") or "",
                    item.get("scene_location") or "",
                    item.get("scene_environment_label") or item.get("scene_environment") or "",
                    item.get("scene_time_label") or item.get("scene_time") or "",
                    item.get("note") or "",
                    item.get("shot_status_label") or item.get("shot_status") or "",
                    actor_text,
                    asset_text,
                    item.get("frame_start") if item.get("frame_start") is not None else "",
                    item.get("frame_end") if item.get("frame_end") is not None else "",
                    item.get("output_label") or item.get("output_type") or "",
                    item.get("preview_path") or "",
                    item.get("output_path") or "",
                    item.get("last_rendered_at") or "",
                ]
            )
    return path


def build_blender_director_render_queue(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    entries = []
    rendered_count = 0
    pending_count = 0
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        preview_path = str(item.get("preview_path") or "").strip()
        output_path = str(item.get("output_path") or "").strip()
        rendered = bool(output_path or preview_path or item.get("last_rendered_at"))
        if rendered:
            rendered_count += 1
        else:
            pending_count += 1
        frame_start = item.get("frame_start")
        frame_end = item.get("frame_end")
        duration_frames = None
        if frame_start is not None and frame_end is not None:
            try:
                duration_frames = max(0, int(frame_end) - int(frame_start) + 1)
            except Exception:
                duration_frames = None
        actors = item.get("actors") if isinstance(item.get("actors"), list) else []
        assets = item.get("assets") if isinstance(item.get("assets"), list) else []
        entries.append(
            {
                "index": item.get("index") or len(entries) + 1,
                "shot_id": str(item.get("shot_id") or ""),
                "shot_name": str(item.get("shot_name") or ""),
                "note": str(item.get("note") or ""),
                "queue_status": "done" if rendered else "pending",
                "queue_status_label": "已渲染" if rendered else "待渲染",
                "shot_status": str(item.get("shot_status") or ""),
                "shot_status_label": str(item.get("shot_status_label") or item.get("shot_status") or ""),
                "frame_start": frame_start,
                "frame_end": frame_end,
                "duration_frames": duration_frames,
                "output_type": str(item.get("output_type") or ""),
                "output_label": str(item.get("output_label") or item.get("output_type") or ""),
                "render_version": item.get("render_version"),
                "last_rendered_at": str(item.get("last_rendered_at") or ""),
                "preview_path": preview_path,
                "output_path": output_path,
                "actor_count": len(actors),
                "asset_count": len(assets),
            }
        )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shot_count": len(entries),
        "rendered_count": rendered_count,
        "pending_count": pending_count,
        "entries": entries,
    }


def write_blender_director_render_queue_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "render_queue.json")
    data = build_blender_director_render_queue(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_render_queue_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "render_queue.csv")
    queue = build_blender_director_render_queue(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "序号",
                "镜头ID",
                "镜头名",
                "队列状态",
                "镜头状态",
                "起始帧",
                "结束帧",
                "帧数",
                "输出类型",
                "版本",
                "演员数",
                "资产数",
                "预览图",
                "输出文件",
                "渲染时间",
                "备注",
            ]
        )
        for item in queue.get("entries", []):
            if not isinstance(item, dict):
                continue
            render_version = item.get("render_version")
            writer.writerow(
                [
                    item.get("index") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("queue_status_label") or "",
                    item.get("shot_status_label") or item.get("shot_status") or "",
                    item.get("frame_start") if item.get("frame_start") is not None else "",
                    item.get("frame_end") if item.get("frame_end") is not None else "",
                    item.get("duration_frames") if item.get("duration_frames") is not None else "",
                    item.get("output_label") or item.get("output_type") or "",
                    ("v" + str(render_version)) if render_version not in (None, "") else "",
                    item.get("actor_count") or 0,
                    item.get("asset_count") or 0,
                    item.get("preview_path") or "",
                    item.get("output_path") or "",
                    item.get("last_rendered_at") or "",
                    item.get("note") or "",
                ]
            )
    return path


def write_blender_director_render_queue_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    queue = build_blender_director_render_queue(metadata)
    project_name = str(queue.get("project_name") or "Blender 导演台工程")
    rows = []
    for item in queue.get("entries", []):
        if not isinstance(item, dict):
            continue
        render_version = item.get("render_version")
        version_text = ("v" + str(render_version)) if render_version not in (None, "") else ""
        frame_start = item.get("frame_start")
        frame_end = item.get("frame_end")
        frame_text = f"{frame_start}-{frame_end}" if frame_start is not None and frame_end is not None else ""
        rows.append(
            "<tr>"
            f"<td>{int(item.get('index') or 0)}</td>"
            f"<td><strong>{escape(str(item.get('shot_name') or item.get('shot_id') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('queue_status_label') or ''))}</td>"
            f"<td>{escape(str(item.get('shot_status_label') or item.get('shot_status') or ''))}</td>"
            f"<td>{escape(frame_text)}</td>"
            f"<td>{escape(str(item.get('duration_frames') or ''))}</td>"
            f"<td>{escape(str(item.get('output_label') or item.get('output_type') or ''))}</td>"
            f"<td>{escape(version_text)}</td>"
            f"<td>{int(item.get('actor_count') or 0)} / {int(item.get('asset_count') or 0)}</td>"
            f"<td>{escape(str(item.get('last_rendered_at') or ''))}</td>"
            f"<td>{escape(str(item.get('note') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="11" class="empty">暂无镜头，请先在 Blender 导演台保存镜头。</td></tr>')
    updated_at = str(queue.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 渲染队列</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; position: sticky; top: 0; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 渲染队列</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(queue.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(queue.get('rendered_count') or 0)}</strong>已渲染</div>
      <div class="stat"><strong>{int(queue.get('pending_count') or 0)}</strong>待渲染</div>
    </div>
    <table>
      <thead><tr><th>#</th><th>镜头</th><th>队列</th><th>镜头状态</th><th>帧段</th><th>帧数</th><th>输出</th><th>版本</th><th>演员/资产</th><th>渲染时间</th><th>备注</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "render_queue.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_batch_render_jobs(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    fallback_fps = _effective_fps(metadata.get("fps"), metadata.get("fps_base"), 24.0)
    jobs = []
    skipped_rendered = 0
    blocked_count = 0
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        rendered = bool(item.get("output_path") or item.get("preview_path") or item.get("last_rendered_at"))
        if rendered:
            skipped_rendered += 1
            continue
        duration_frames = _duration_frames_from_range(item.get("frame_start"), item.get("frame_end"))
        fps = _effective_fps(item.get("fps"), item.get("fps_base"), fallback_fps)
        blocked_reasons = []
        if duration_frames is None:
            blocked_reasons.append("缺少帧段")
        elif int(duration_frames) <= 0:
            blocked_reasons.append("帧段无效")
        if not str(item.get("shot_id") or "").strip():
            blocked_reasons.append("缺少镜头ID")
        if not str(item.get("output_type") or "").strip():
            blocked_reasons.append("缺少输出类型")
        if blocked_reasons:
            blocked_count += 1
        jobs.append(
            {
                "job_index": len(jobs) + 1,
                "priority": len(jobs) + 1,
                "shot_id": str(item.get("shot_id") or ""),
                "shot_name": str(item.get("shot_name") or ""),
                "episode_number": str(item.get("episode_number") or item.get("episode") or metadata.get("episode_number") or "未分集"),
                "episode_name": str(item.get("episode_name") or metadata.get("episode_name") or ""),
                "scene_number": str(item.get("scene_number") or "未分场"),
                "scene_location": str(item.get("scene_location") or ""),
                "frame_start": item.get("frame_start"),
                "frame_end": item.get("frame_end"),
                "duration_frames": duration_frames,
                "duration_seconds": round(duration_frames / fps, 3) if duration_frames is not None and fps else None,
                "fps": fps,
                "output_type": str(item.get("output_type") or ""),
                "output_label": str(item.get("output_label") or item.get("output_type") or ""),
                "status": "blocked" if blocked_reasons else "ready",
                "status_label": "需补信息" if blocked_reasons else "可渲染",
                "blocked_reasons": blocked_reasons,
            }
        )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "job_count": len(jobs),
        "ready_count": len(jobs) - blocked_count,
        "blocked_count": blocked_count,
        "skipped_rendered_count": skipped_rendered,
        "jobs": jobs,
    }


def write_blender_director_batch_render_jobs_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "batch_render_jobs.json")
    data = build_blender_director_batch_render_jobs(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_batch_render_jobs_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "batch_render_jobs.csv")
    data = build_blender_director_batch_render_jobs(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["优先级", "状态", "分集", "场次", "地点", "镜头ID", "镜头名", "起始帧", "结束帧", "帧数", "输出类型", "阻断原因"])
        for item in data.get("jobs", []):
            if not isinstance(item, dict):
                continue
            writer.writerow(
                [
                    item.get("priority") or "",
                    item.get("status_label") or "",
                    item.get("episode_number") or "",
                    item.get("scene_number") or "",
                    item.get("scene_location") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("frame_start") if item.get("frame_start") is not None else "",
                    item.get("frame_end") if item.get("frame_end") is not None else "",
                    item.get("duration_frames") if item.get("duration_frames") is not None else "",
                    item.get("output_label") or item.get("output_type") or "",
                    "、".join(str(reason) for reason in item.get("blocked_reasons", []) if str(reason).strip()),
                ]
            )
    return path


def write_blender_director_batch_render_jobs_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_batch_render_jobs(metadata)
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    rows = []
    for item in data.get("jobs", []):
        if not isinstance(item, dict):
            continue
        frame_text = ""
        if item.get("frame_start") is not None and item.get("frame_end") is not None:
            frame_text = f"{item.get('frame_start')}-{item.get('frame_end')}"
        scene_text = " / ".join(
            part
            for part in (
                str(item.get("episode_number") or "").strip(),
                str(item.get("scene_number") or "").strip(),
                str(item.get("scene_location") or "").strip(),
            )
            if part
        )
        reason_text = "、".join(str(reason) for reason in item.get("blocked_reasons", []) if str(reason).strip())
        status_class = "bad" if item.get("status") == "blocked" else "ok"
        rows.append(
            "<tr>"
            f"<td>{int(item.get('priority') or 0)}</td>"
            f"<td class=\"{status_class}\">{escape(str(item.get('status_label') or ''))}</td>"
            f"<td>{escape(scene_text)}</td>"
            f"<td><strong>{escape(str(item.get('shot_name') or item.get('shot_id') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(frame_text)}</td>"
            f"<td>{escape(str(item.get('duration_frames') if item.get('duration_frames') is not None else ''))}</td>"
            f"<td>{escape(str(item.get('output_label') or item.get('output_type') or ''))}</td>"
            f"<td>{escape(reason_text)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="8" class="empty">暂无待渲染镜头。</td></tr>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 批量渲染任务</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .ok {{ color: #86efac; }}
    .bad {{ color: #ff9f9f; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 批量渲染任务</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('job_count') or 0)}</strong>待渲染任务</div>
      <div class="stat"><strong>{int(data.get('ready_count') or 0)}</strong>可渲染</div>
      <div class="stat"><strong>{int(data.get('blocked_count') or 0)}</strong>需补信息</div>
      <div class="stat"><strong>{int(data.get('skipped_rendered_count') or 0)}</strong>已跳过已渲染</div>
    </div>
    <table>
      <thead><tr><th>优先级</th><th>状态</th><th>分集/场次</th><th>镜头</th><th>帧段</th><th>帧数</th><th>输出</th><th>阻断原因</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "batch_render_jobs.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_render_versions(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    renders = metadata.get("renders") if isinstance(metadata.get("renders"), list) else []
    storyboard_by_shot = {
        str(item.get("shot_id") or ""): item
        for item in build_blender_director_storyboard(metadata)
        if isinstance(item, dict) and str(item.get("shot_id") or "").strip()
    }
    entries = []
    latest_by_shot = {}
    for index, render in enumerate(renders, 1):
        if not isinstance(render, dict):
            continue
        shot_id = str(render.get("shot_id") or "").strip()
        shot = storyboard_by_shot.get(shot_id, {})
        shot_name = str(render.get("shot_name") or shot.get("shot_name") or shot_id or f"输出{index}").strip()
        output_path = str(render.get("output_path") or render.get("path") or "").strip()
        preview_path = str(render.get("preview_path") or render.get("path") or "").strip()
        manifest_path = str(render.get("manifest_path") or "").strip()
        layer_paths = render.get("layer_paths") if isinstance(render.get("layer_paths"), dict) else {}
        file_paths = [output_path, preview_path, manifest_path]
        file_paths.extend(str(path or "").strip() for path in layer_paths.values())
        existing_files = [path for path in file_paths if path and os.path.exists(path)]
        entry = {
            "index": index,
            "shot_id": shot_id,
            "shot_name": shot_name,
            "render_version": render.get("render_version"),
            "output_type": str(render.get("output_type") or shot.get("output_type") or ""),
            "output_label": str(render.get("output_label") or shot.get("output_label") or render.get("output_type") or shot.get("output_type") or ""),
            "created_at": str(render.get("created_at") or render.get("last_rendered_at") or ""),
            "path": str(render.get("path") or ""),
            "preview_path": preview_path,
            "output_path": output_path,
            "manifest_path": manifest_path,
            "layer_count": len(layer_paths),
            "file_count": len([path for path in file_paths if path]),
            "existing_file_count": len(existing_files),
            "missing_file_count": max(0, len([path for path in file_paths if path]) - len(existing_files)),
            "is_latest_for_shot": False,
        }
        entries.append(entry)
        latest_by_shot[shot_id or f"render:{index}"] = len(entries) - 1
    for latest_index in latest_by_shot.values():
        try:
            entries[int(latest_index)]["is_latest_for_shot"] = True
        except Exception:
            pass
    shot_ids = {str(item.get("shot_id") or f"render:{item.get('index')}") for item in entries}
    missing_file_count = sum(int(item.get("missing_file_count") or 0) for item in entries)
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "render_count": len(entries),
        "shot_count": len(shot_ids),
        "missing_file_count": missing_file_count,
        "entries": entries,
    }


def write_blender_director_render_versions_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "render_versions.json")
    data = build_blender_director_render_versions(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_render_versions_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "render_versions.csv")
    data = build_blender_director_render_versions(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "镜头ID", "镜头名", "版本", "是否最新", "输出类型", "文件数", "缺失文件", "预览图", "输出文件", "分层清单", "时间"])
        for item in data.get("entries", []):
            if not isinstance(item, dict):
                continue
            version = item.get("render_version")
            writer.writerow(
                [
                    item.get("index") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    ("v" + str(version)) if version not in (None, "") else "",
                    "是" if item.get("is_latest_for_shot") else "",
                    item.get("output_label") or item.get("output_type") or "",
                    item.get("file_count") or 0,
                    item.get("missing_file_count") or 0,
                    item.get("preview_path") or "",
                    item.get("output_path") or "",
                    item.get("manifest_path") or "",
                    item.get("created_at") or "",
                ]
            )
    return path


def write_blender_director_render_versions_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_render_versions(metadata)
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    rows = []
    for item in data.get("entries", []):
        if not isinstance(item, dict):
            continue
        version = item.get("render_version")
        version_text = ("v" + str(version)) if version not in (None, "") else ""
        latest_text = "最新" if item.get("is_latest_for_shot") else ""
        rows.append(
            "<tr>"
            f"<td>{int(item.get('index') or 0)}</td>"
            f"<td><strong>{escape(str(item.get('shot_name') or item.get('shot_id') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(version_text)}</td>"
            f"<td>{escape(latest_text)}</td>"
            f"<td>{escape(str(item.get('output_label') or item.get('output_type') or ''))}</td>"
            f"<td>{int(item.get('file_count') or 0)} / {int(item.get('missing_file_count') or 0)}</td>"
            f"<td>{escape(str(item.get('preview_path') or ''))}</td>"
            f"<td>{escape(str(item.get('output_path') or ''))}</td>"
            f"<td>{escape(str(item.get('created_at') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="9" class="empty">暂无渲染版本记录，请先在 Blender 导演台渲染或同步输出。</td></tr>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 镜头版本索引</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 镜头版本索引</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('render_count') or 0)}</strong>渲染记录</div>
      <div class="stat"><strong>{int(data.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(data.get('missing_file_count') or 0)}</strong>缺失文件</div>
    </div>
    <table>
      <thead><tr><th>#</th><th>镜头</th><th>版本</th><th>标记</th><th>输出</th><th>文件/缺失</th><th>预览</th><th>输出文件</th><th>时间</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "render_versions.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _duration_frames_from_range(frame_start, frame_end):
    if frame_start is None or frame_end is None:
        return None
    try:
        return max(0, int(frame_end) - int(frame_start) + 1)
    except Exception:
        return None


def _effective_fps(value=None, fps_base=None, fallback=24.0):
    try:
        fps = float(value)
        base = float(fps_base) if fps_base not in (None, "") else 1.0
        if fps > 0 and base > 0:
            return fps / base
    except Exception:
        pass
    return float(fallback or 24.0)


def build_blender_director_duration_summary(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    fallback_fps = _effective_fps(metadata.get("fps"), metadata.get("fps_base"), 24.0)
    entries = []
    total_frames = 0
    total_seconds = 0.0
    shots_with_duration = 0
    shots_without_duration = 0
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        duration_frames = _duration_frames_from_range(item.get("frame_start"), item.get("frame_end"))
        fps = _effective_fps(item.get("fps"), item.get("fps_base"), fallback_fps)
        duration_seconds = None
        if duration_frames is None:
            shots_without_duration += 1
        else:
            shots_with_duration += 1
            total_frames += duration_frames
            duration_seconds = duration_frames / fps if fps else 0.0
            total_seconds += duration_seconds
        entries.append(
            {
                "index": item.get("index") or len(entries) + 1,
                "shot_id": str(item.get("shot_id") or ""),
                "shot_name": str(item.get("shot_name") or ""),
                "frame_start": item.get("frame_start"),
                "frame_end": item.get("frame_end"),
                "duration_frames": duration_frames,
                "fps": fps,
                "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
                "shot_status_label": str(item.get("shot_status_label") or item.get("shot_status") or ""),
                "queue_status_label": "已渲染"
                if (item.get("output_path") or item.get("preview_path") or item.get("last_rendered_at"))
                else "待渲染",
            }
        )
    average_seconds = total_seconds / shots_with_duration if shots_with_duration else 0.0
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fps": fallback_fps,
        "shot_count": len(entries),
        "shots_with_duration": shots_with_duration,
        "shots_without_duration": shots_without_duration,
        "total_frames": total_frames,
        "total_seconds": round(total_seconds, 3),
        "average_shot_seconds": round(average_seconds, 3),
        "entries": entries,
    }


def write_blender_director_duration_summary(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "duration_summary.json")
    data = build_blender_director_duration_summary(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _format_timeline_time(seconds):
    try:
        seconds = max(0.0, float(seconds))
    except Exception:
        seconds = 0.0
    minutes = int(seconds // 60)
    remain = seconds - minutes * 60
    return f"{minutes:02d}:{remain:06.3f}"


def _format_edl_timecode(frame_number, fps):
    try:
        fps_int = int(round(float(fps)))
    except Exception:
        fps_int = 24
    fps_int = max(1, fps_int)
    try:
        total_frames = max(0, int(round(float(frame_number))))
    except Exception:
        total_frames = 0
    frames = total_frames % fps_int
    total_seconds = total_frames // fps_int
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def _edl_reel_name(value, fallback="AX"):
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9_]+", "_", text)
    text = text.strip("_")
    return (text[:8] or fallback)[:8]


def _edl_comment_text(value):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text


def build_blender_director_edit_timeline(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    fallback_fps = _effective_fps(metadata.get("fps"), metadata.get("fps_base"), 24.0)
    entries = []
    current_seconds = 0.0
    total_frames = 0
    missing_duration_count = 0
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        duration_frames = _duration_frames_from_range(item.get("frame_start"), item.get("frame_end"))
        fps = _effective_fps(item.get("fps"), item.get("fps_base"), fallback_fps)
        if duration_frames is None:
            duration_seconds = 0.0
            missing_duration_count += 1
        else:
            duration_seconds = duration_frames / fps if fps else 0.0
            total_frames += duration_frames
        timeline_start = current_seconds
        timeline_end = current_seconds + duration_seconds
        current_seconds = timeline_end
        rendered = bool(item.get("output_path") or item.get("preview_path") or item.get("last_rendered_at"))
        actors = item.get("actors") if isinstance(item.get("actors"), list) else []
        actor_names = []
        for actor in actors:
            if not isinstance(actor, dict):
                continue
            name = str(actor.get("name") or actor.get("id") or "").strip()
            role = str(actor.get("role") or "").strip()
            if name and role:
                actor_names.append(f"{name}（{role}）")
            elif name:
                actor_names.append(name)
        entries.append(
            {
                "index": item.get("index") or len(entries) + 1,
                "shot_id": str(item.get("shot_id") or ""),
                "shot_name": str(item.get("shot_name") or ""),
                "scene_number": str(item.get("scene_number") or ""),
                "scene_location": str(item.get("scene_location") or ""),
                "scene_environment_label": str(item.get("scene_environment_label") or item.get("scene_environment") or ""),
                "scene_time_label": str(item.get("scene_time_label") or item.get("scene_time") or ""),
                "timeline_start_seconds": round(timeline_start, 3),
                "timeline_end_seconds": round(timeline_end, 3),
                "timeline_start": _format_timeline_time(timeline_start),
                "timeline_end": _format_timeline_time(timeline_end),
                "duration_frames": duration_frames,
                "duration_seconds": round(duration_seconds, 3) if duration_frames is not None else None,
                "fps": fps,
                "frame_start": item.get("frame_start"),
                "frame_end": item.get("frame_end"),
                "queue_status": "done" if rendered else "pending",
                "queue_status_label": "已渲染" if rendered else "待渲染",
                "shot_status_label": str(item.get("shot_status_label") or item.get("shot_status") or ""),
                "output_type": str(item.get("output_type") or ""),
                "output_label": str(item.get("output_label") or item.get("output_type") or ""),
                "preview_path": str(item.get("preview_path") or ""),
                "output_path": str(item.get("output_path") or ""),
                "actor_text": "、".join(actor_names),
                "note": str(item.get("note") or ""),
            }
        )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fps": fallback_fps,
        "shot_count": len(entries),
        "total_frames": total_frames,
        "total_seconds": round(current_seconds, 3),
        "missing_duration_count": missing_duration_count,
        "entries": entries,
    }


def build_blender_director_edit_decision_list(metadata):
    metadata = metadata if isinstance(metadata, dict) else {}
    timeline = build_blender_director_edit_timeline(metadata)
    fps = _effective_fps(timeline.get("fps"), None, 24.0)
    fps_int = max(1, int(round(fps)))
    project_name = str(timeline.get("project_name") or "Blender Director Project")
    title = _edl_comment_text(project_name) or "Blender Director Project"
    entries = []
    record_frame = 0
    for item in timeline.get("entries", []):
        if not isinstance(item, dict):
            continue
        duration_frames = item.get("duration_frames")
        if duration_frames is None:
            try:
                duration_seconds = float(item.get("duration_seconds") or 0)
                duration_frames = int(round(duration_seconds * fps_int))
            except Exception:
                duration_frames = 0
        try:
            duration_frames = max(0, int(duration_frames))
        except Exception:
            duration_frames = 0
        source_in = 0
        source_out = duration_frames
        record_in = record_frame
        record_out = record_frame + duration_frames
        record_frame = record_out
        shot_id = str(item.get("shot_id") or item.get("index") or "").strip()
        output_path = str(item.get("output_path") or item.get("preview_path") or "").strip()
        reel_seed = shot_id or Path(output_path).stem or f"SHOT{int(item.get('index') or len(entries) + 1):03d}"
        entry = {
            "index": int(item.get("index") or len(entries) + 1),
            "shot_id": shot_id,
            "shot_name": str(item.get("shot_name") or ""),
            "reel": _edl_reel_name(reel_seed),
            "track": "V",
            "transition": "C",
            "source_in": _format_edl_timecode(source_in, fps_int),
            "source_out": _format_edl_timecode(source_out, fps_int),
            "record_in": _format_edl_timecode(record_in, fps_int),
            "record_out": _format_edl_timecode(record_out, fps_int),
            "duration_frames": duration_frames,
            "output_path": output_path,
        }
        entries.append(entry)
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": project_name,
        "title": title,
        "fps": fps_int,
        "shot_count": len(entries),
        "total_frames": record_frame,
        "total_timecode": _format_edl_timecode(record_frame, fps_int),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entries": entries,
    }


def write_blender_director_edit_decision_list(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    edl = build_blender_director_edit_decision_list(metadata)
    path = os.path.join(project_dir, "edit_timeline.edl")
    lines = [
        f"TITLE: {edl.get('title') or 'Blender Director Project'}",
        "FCM: NON-DROP FRAME",
        "",
    ]
    for entry in edl.get("entries", []):
        if not isinstance(entry, dict):
            continue
        index = int(entry.get("index") or 0)
        lines.append(
            f"{index:03d}  {entry.get('reel') or 'AX':<8} {entry.get('track') or 'V':<5} {entry.get('transition') or 'C':<8} "
            f"{entry.get('source_in') or '00:00:00:00'} {entry.get('source_out') or '00:00:00:00'} "
            f"{entry.get('record_in') or '00:00:00:00'} {entry.get('record_out') or '00:00:00:00'}"
        )
        shot_name = _edl_comment_text(entry.get("shot_name"))
        shot_id = _edl_comment_text(entry.get("shot_id"))
        output_path = _edl_comment_text(entry.get("output_path"))
        if shot_name:
            lines.append(f"* FROM CLIP NAME: {shot_name}")
        if shot_id:
            lines.append(f"* SHOT ID: {shot_id}")
        if output_path:
            lines.append(f"* SOURCE FILE: {output_path}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return path


def _fcpx_time_from_frames(frame_number, fps):
    try:
        fps_int = int(round(float(fps)))
    except Exception:
        fps_int = 24
    fps_int = max(1, fps_int)
    try:
        frames = max(0, int(round(float(frame_number))))
    except Exception:
        frames = 0
    if frames <= 0:
        return "0s"
    return f"{frames}/{fps_int}s"


def _preferred_edit_source_path(item):
    output_path = str(item.get("output_path") or "").strip() if isinstance(item, dict) else ""
    preview_path = str(item.get("preview_path") or "").strip() if isinstance(item, dict) else ""
    for path in (output_path, preview_path):
        if path and os.path.isfile(path):
            return path
    return output_path or preview_path


def write_blender_director_final_cut_xml(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    metadata = metadata if isinstance(metadata, dict) else {}
    os.makedirs(project_dir, exist_ok=True)
    timeline = build_blender_director_edit_timeline(metadata)
    fps = max(1, int(round(_effective_fps(timeline.get("fps"), None, 24.0))))
    project_name = str(timeline.get("project_name") or "Blender 导演台工程")
    try:
        width = max(1, int(metadata.get("resolution_x") or 1920))
    except Exception:
        width = 1920
    try:
        height = max(1, int(metadata.get("resolution_y") or 1080))
    except Exception:
        height = 1080

    root = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": f"FFVideoFormat{height}p{fps}",
            "frameDuration": f"1/{fps}s",
            "width": str(width),
            "height": str(height),
        },
    )
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": project_name})
    project = ET.SubElement(event, "project", {"name": project_name})
    total_frames = int(timeline.get("total_frames") or 0)
    sequence_duration = _fcpx_time_from_frames(max(1, total_frames), fps)
    sequence = ET.SubElement(project, "sequence", {"duration": sequence_duration, "format": "r1", "tcStart": "0s", "tcFormat": "NDF"})
    spine = ET.SubElement(sequence, "spine")

    asset_ids = {}
    for item in timeline.get("entries", []):
        if not isinstance(item, dict):
            continue
        source_path = _preferred_edit_source_path(item)
        source_uri = _file_uri(source_path)
        if not source_uri:
            continue
        if source_path in asset_ids:
            continue
        asset_id = f"r{len(asset_ids) + 2}"
        asset_ids[source_path] = asset_id
        duration_frames = item.get("duration_frames")
        try:
            duration_frames = max(1, int(duration_frames))
        except Exception:
            duration_frames = 1
        ET.SubElement(
            resources,
            "asset",
            {
                "id": asset_id,
                "name": str(item.get("shot_name") or item.get("shot_id") or Path(source_path).stem or "shot"),
                "src": source_uri,
                "start": "0s",
                "duration": _fcpx_time_from_frames(duration_frames, fps),
                "hasVideo": "1",
                "format": "r1",
            },
        )

    for item in timeline.get("entries", []):
        if not isinstance(item, dict):
            continue
        try:
            duration_frames = max(1, int(item.get("duration_frames") or 0))
        except Exception:
            duration_frames = 1
        try:
            offset_frames = max(0, int(round(float(item.get("timeline_start_seconds") or 0) * fps)))
        except Exception:
            offset_frames = 0
        duration = _fcpx_time_from_frames(duration_frames, fps)
        attrs = {
            "name": str(item.get("shot_name") or item.get("shot_id") or "未命名镜头"),
            "offset": _fcpx_time_from_frames(offset_frames, fps),
            "duration": duration,
            "start": "0s",
        }
        source_path = _preferred_edit_source_path(item)
        asset_id = asset_ids.get(source_path)
        if asset_id:
            attrs["ref"] = asset_id
            ET.SubElement(spine, "asset-clip", attrs)
        else:
            ET.SubElement(spine, "gap", attrs)

    path = os.path.join(project_dir, "edit_timeline.fcpxml")
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def write_blender_director_edit_timeline_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "edit_timeline.json")
    data = build_blender_director_edit_timeline(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_edit_timeline_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "edit_timeline.csv")
    timeline = build_blender_director_edit_timeline(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "序号",
                "镜头ID",
                "镜头名",
                "场次",
                "地点",
                "时间线开始",
                "时间线结束",
                "时长秒",
                "时长帧",
                "渲染状态",
                "输出类型",
                "输出文件",
                "演员",
                "备注",
            ]
        )
        for item in timeline.get("entries", []):
            if not isinstance(item, dict):
                continue
            writer.writerow(
                [
                    item.get("index") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("scene_number") or "",
                    item.get("scene_location") or "",
                    item.get("timeline_start") or "",
                    item.get("timeline_end") or "",
                    item.get("duration_seconds") if item.get("duration_seconds") is not None else "",
                    item.get("duration_frames") if item.get("duration_frames") is not None else "",
                    item.get("queue_status_label") or "",
                    item.get("output_label") or item.get("output_type") or "",
                    item.get("output_path") or item.get("preview_path") or "",
                    item.get("actor_text") or "",
                    item.get("note") or "",
                ]
            )
    return path


def write_blender_director_edit_timeline_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    timeline = build_blender_director_edit_timeline(metadata)
    project_name = str(timeline.get("project_name") or "Blender 导演台工程")
    rows = []
    for item in timeline.get("entries", []):
        if not isinstance(item, dict):
            continue
        scene_text = " / ".join(
            part
            for part in (
                str(item.get("scene_number") or "").strip(),
                str(item.get("scene_location") or "").strip(),
                str(item.get("scene_environment_label") or "").strip(),
                str(item.get("scene_time_label") or "").strip(),
            )
            if part
        )
        rows.append(
            "<tr>"
            f"<td>{int(item.get('index') or 0)}</td>"
            f"<td><strong>{escape(str(item.get('shot_name') or item.get('shot_id') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(scene_text)}</td>"
            f"<td>{escape(str(item.get('timeline_start') or ''))}</td>"
            f"<td>{escape(str(item.get('timeline_end') or ''))}</td>"
            f"<td>{escape(str(item.get('duration_seconds') if item.get('duration_seconds') is not None else ''))}</td>"
            f"<td>{escape(str(item.get('duration_frames') if item.get('duration_frames') is not None else ''))}</td>"
            f"<td>{escape(str(item.get('queue_status_label') or ''))}</td>"
            f"<td>{escape(str(item.get('output_label') or item.get('output_type') or ''))}</td>"
            f"<td>{escape(str(item.get('actor_text') or ''))}</td>"
            f"<td>{escape(str(item.get('output_path') or item.get('preview_path') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="11" class="empty">暂无镜头，请先在 Blender 导演台保存镜头。</td></tr>')
    updated_at = str(timeline.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 剪辑时间线</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; position: sticky; top: 0; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 剪辑时间线</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(timeline.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{float(timeline.get('total_seconds') or 0):.1f}</strong>总秒数</div>
      <div class="stat"><strong>{int(timeline.get('total_frames') or 0)}</strong>总帧数</div>
      <div class="stat"><strong>{int(timeline.get('missing_duration_count') or 0)}</strong>缺时长镜头</div>
    </div>
    <table>
      <thead><tr><th>#</th><th>镜头</th><th>场次</th><th>开始</th><th>结束</th><th>秒</th><th>帧</th><th>渲染</th><th>输出</th><th>演员</th><th>文件</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "edit_timeline.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_post_handoff(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    timeline = build_blender_director_edit_timeline(metadata)
    timeline_by_shot = {
        str(item.get("shot_id") or ""): item
        for item in timeline.get("entries", [])
        if isinstance(item, dict) and str(item.get("shot_id") or "").strip()
    }
    entries = []
    rendered_count = 0
    missing_file_count = 0
    layered_count = 0
    transparent_count = 0
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        timeline_item = timeline_by_shot.get(shot_id, {})
        output_path = str(item.get("output_path") or "").strip()
        preview_path = str(item.get("preview_path") or "").strip()
        manifest_path = str(item.get("manifest_path") or "").strip()
        layer_paths = item.get("layer_paths") if isinstance(item.get("layer_paths"), dict) else {}
        output_exists = bool(output_path and os.path.exists(output_path))
        preview_exists = bool(preview_path and os.path.exists(preview_path))
        manifest_exists = bool(manifest_path and os.path.exists(manifest_path))
        layer_rows = []
        for layer_name, layer_path in layer_paths.items():
            layer_name = str(layer_name or "").strip()
            layer_path = str(layer_path or "").strip()
            if not layer_name and not layer_path:
                continue
            exists = bool(layer_path and os.path.exists(layer_path))
            if layer_name == "transparent" and exists:
                transparent_count += 1
            layer_rows.append({"name": layer_name, "path": layer_path, "exists": exists})
        rendered = bool(output_path or preview_path or item.get("last_rendered_at"))
        if rendered:
            rendered_count += 1
        missing_files = []
        if output_path and not output_exists:
            missing_files.append(output_path)
        if preview_path and not preview_exists:
            missing_files.append(preview_path)
        if manifest_path and not manifest_exists:
            missing_files.append(manifest_path)
        for layer in layer_rows:
            if layer.get("path") and not layer.get("exists"):
                missing_files.append(str(layer.get("path") or ""))
        if missing_files:
            missing_file_count += 1
        if str(item.get("output_type") or "") == "layered" or layer_rows:
            layered_count += 1
        entries.append(
            {
                "index": item.get("index") or len(entries) + 1,
                "shot_id": shot_id,
                "shot_name": str(item.get("shot_name") or ""),
                "scene_number": str(item.get("scene_number") or ""),
                "scene_location": str(item.get("scene_location") or ""),
                "timeline_start": str(timeline_item.get("timeline_start") or ""),
                "timeline_end": str(timeline_item.get("timeline_end") or ""),
                "duration_seconds": timeline_item.get("duration_seconds"),
                "output_type": str(item.get("output_type") or ""),
                "output_label": str(item.get("output_label") or item.get("output_type") or ""),
                "render_version": item.get("render_version"),
                "rendered": rendered,
                "output_path": output_path,
                "output_exists": output_exists,
                "preview_path": preview_path,
                "preview_exists": preview_exists,
                "manifest_path": manifest_path,
                "manifest_exists": manifest_exists,
                "layers": layer_rows,
                "missing_files": missing_files,
                "last_rendered_at": str(item.get("last_rendered_at") or ""),
            }
        )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shot_count": len(entries),
        "rendered_count": rendered_count,
        "pending_count": max(0, len(entries) - rendered_count),
        "layered_count": layered_count,
        "transparent_count": transparent_count,
        "missing_file_shot_count": missing_file_count,
        "entries": entries,
    }


def write_blender_director_post_handoff_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "post_handoff.json")
    data = build_blender_director_post_handoff(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_post_handoff_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "post_handoff.csv")
    handoff = build_blender_director_post_handoff(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "序号",
                "镜头ID",
                "镜头名",
                "场次",
                "地点",
                "开始",
                "结束",
                "时长秒",
                "输出类型",
                "版本",
                "主输出",
                "预览图",
                "分层素材",
                "manifest",
                "缺失文件",
                "渲染时间",
            ]
        )
        for item in handoff.get("entries", []):
            if not isinstance(item, dict):
                continue
            layers = item.get("layers") if isinstance(item.get("layers"), list) else []
            layer_text = "、".join(
                f"{layer.get('name') or 'layer'}:{layer.get('path') or ''}"
                for layer in layers
                if isinstance(layer, dict)
            )
            render_version = item.get("render_version")
            writer.writerow(
                [
                    item.get("index") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("scene_number") or "",
                    item.get("scene_location") or "",
                    item.get("timeline_start") or "",
                    item.get("timeline_end") or "",
                    item.get("duration_seconds") if item.get("duration_seconds") is not None else "",
                    item.get("output_label") or item.get("output_type") or "",
                    ("v" + str(render_version)) if render_version not in (None, "") else "",
                    item.get("output_path") or "",
                    item.get("preview_path") or "",
                    layer_text,
                    item.get("manifest_path") or "",
                    "、".join(item.get("missing_files") if isinstance(item.get("missing_files"), list) else []),
                    item.get("last_rendered_at") or "",
                ]
            )
    return path


def write_blender_director_post_handoff_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    handoff = build_blender_director_post_handoff(metadata)
    project_name = str(handoff.get("project_name") or "Blender 导演台工程")
    rows = []
    for item in handoff.get("entries", []):
        if not isinstance(item, dict):
            continue
        render_version = item.get("render_version")
        version_text = ("v" + str(render_version)) if render_version not in (None, "") else ""
        layers = item.get("layers") if isinstance(item.get("layers"), list) else []
        layer_links = []
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            name = str(layer.get("name") or "layer")
            path = str(layer.get("path") or "")
            uri = _file_uri(path) if path and os.path.exists(path) else ""
            if uri:
                layer_links.append(f'<a href="{escape(uri)}">{escape(name)}</a>')
            elif path:
                layer_links.append(escape(name))
        output_path = str(item.get("output_path") or "")
        output_uri = _file_uri(output_path) if output_path and os.path.exists(output_path) else ""
        output_html = f'<a href="{escape(output_uri)}">主输出</a>' if output_uri else escape(output_path or "未输出")
        missing_text = "、".join(str(path) for path in item.get("missing_files", []) if str(path).strip())
        rows.append(
            "<tr>"
            f"<td>{int(item.get('index') or 0)}</td>"
            f"<td><strong>{escape(str(item.get('shot_name') or item.get('shot_id') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('scene_number') or ''))}<div class=\"id\">{escape(str(item.get('scene_location') or ''))}</div></td>"
            f"<td>{escape(str(item.get('timeline_start') or ''))} - {escape(str(item.get('timeline_end') or ''))}</td>"
            f"<td>{escape(str(item.get('output_label') or item.get('output_type') or ''))}<div class=\"id\">{escape(version_text)}</div></td>"
            f"<td>{output_html}</td>"
            f"<td>{'、'.join(layer_links)}</td>"
            f"<td>{escape(missing_text)}</td>"
            f"<td>{escape(str(item.get('last_rendered_at') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="9" class="empty">暂无镜头输出</td></tr>')
    updated_at = str(handoff.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 后期交接清单</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; position: sticky; top: 0; }}
    a {{ color: #7dc4ff; text-decoration: none; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 后期交接清单</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(handoff.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(handoff.get('rendered_count') or 0)}</strong>已输出</div>
      <div class="stat"><strong>{int(handoff.get('layered_count') or 0)}</strong>分层镜头</div>
      <div class="stat"><strong>{int(handoff.get('transparent_count') or 0)}</strong>透明层</div>
      <div class="stat"><strong>{int(handoff.get('missing_file_shot_count') or 0)}</strong>缺文件镜头</div>
    </div>
    <table>
      <thead><tr><th>#</th><th>镜头</th><th>场次</th><th>时间线</th><th>输出</th><th>主文件</th><th>分层素材</th><th>缺失文件</th><th>渲染时间</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "post_handoff.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_scene_breakdown(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    scenes = {}
    unassigned = []
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        scene_number = str(item.get("scene_number") or "").strip()
        scene_location = str(item.get("scene_location") or "").strip()
        scene_environment = str(item.get("scene_environment") or "").strip()
        scene_environment_label = str(item.get("scene_environment_label") or scene_environment).strip()
        scene_time = str(item.get("scene_time") or "").strip()
        scene_time_label = str(item.get("scene_time_label") or scene_time).strip()
        duration_frames = _duration_frames_from_range(item.get("frame_start"), item.get("frame_end"))
        rendered = bool(item.get("output_path") or item.get("preview_path") or item.get("last_rendered_at"))
        shot = {
            "index": item.get("index") or "",
            "shot_id": str(item.get("shot_id") or ""),
            "shot_name": str(item.get("shot_name") or ""),
            "shot_status": str(item.get("shot_status") or ""),
            "shot_status_label": str(item.get("shot_status_label") or item.get("shot_status") or ""),
            "queue_status": "done" if rendered else "pending",
            "queue_status_label": "已渲染" if rendered else "待渲染",
            "frame_start": item.get("frame_start"),
            "frame_end": item.get("frame_end"),
            "duration_frames": duration_frames,
            "output_type": str(item.get("output_type") or ""),
            "output_label": str(item.get("output_label") or item.get("output_type") or ""),
        }
        key = "|".join([scene_number, scene_location, scene_environment, scene_time])
        if not any((scene_number, scene_location, scene_environment, scene_time)):
            unassigned.append(shot)
            continue
        scene = scenes.setdefault(
            key,
            {
                "scene_number": scene_number,
                "scene_location": scene_location,
                "scene_environment": scene_environment,
                "scene_environment_label": scene_environment_label,
                "scene_time": scene_time,
                "scene_time_label": scene_time_label,
                "shot_count": 0,
                "rendered_shot_count": 0,
                "pending_shot_count": 0,
                "total_frames": 0,
                "shots": [],
            },
        )
        scene["shot_count"] += 1
        if rendered:
            scene["rendered_shot_count"] += 1
        else:
            scene["pending_shot_count"] += 1
        if duration_frames is not None:
            scene["total_frames"] += duration_frames
        scene["shots"].append(shot)
    scene_rows = sorted(
        scenes.values(),
        key=lambda item: (
            str(item.get("scene_number") or ""),
            str(item.get("scene_location") or ""),
            str(item.get("scene_environment") or ""),
            str(item.get("scene_time") or ""),
        ),
    )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scene_count": len(scene_rows),
        "unassigned_shot_count": len(unassigned),
        "scenes": scene_rows,
        "unassigned_shots": unassigned,
    }


def write_blender_director_scene_breakdown_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "scene_breakdown.json")
    data = build_blender_director_scene_breakdown(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_scene_breakdown_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "scene_breakdown.csv")
    breakdown = build_blender_director_scene_breakdown(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["场次", "地点", "内外景", "日夜", "镜头数", "已渲染", "待渲染", "总帧数", "镜头"])
        for scene in breakdown.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            shots = scene.get("shots") if isinstance(scene.get("shots"), list) else []
            shot_names = "、".join(
                str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
                for shot in shots
                if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            )
            writer.writerow(
                [
                    scene.get("scene_number") or "",
                    scene.get("scene_location") or "",
                    scene.get("scene_environment_label") or scene.get("scene_environment") or "",
                    scene.get("scene_time_label") or scene.get("scene_time") or "",
                    scene.get("shot_count") or 0,
                    scene.get("rendered_shot_count") or 0,
                    scene.get("pending_shot_count") or 0,
                    scene.get("total_frames") or 0,
                    shot_names,
                ]
            )
    return path


def write_blender_director_scene_breakdown_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    breakdown = build_blender_director_scene_breakdown(metadata)
    project_name = str(breakdown.get("project_name") or "Blender 导演台工程")
    rows = []
    for scene in breakdown.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        shots = scene.get("shots") if isinstance(scene.get("shots"), list) else []
        shot_labels = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            name = str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            status = str(shot.get("queue_status_label") or "").strip()
            if name and status:
                shot_labels.append(f"{name}（{status}）")
            elif name:
                shot_labels.append(name)
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(scene.get('scene_number') or '未命名场次'))}</strong></td>"
            f"<td>{escape(str(scene.get('scene_location') or ''))}</td>"
            f"<td>{escape(str(scene.get('scene_environment_label') or scene.get('scene_environment') or ''))}</td>"
            f"<td>{escape(str(scene.get('scene_time_label') or scene.get('scene_time') or ''))}</td>"
            f"<td>{int(scene.get('shot_count') or 0)}</td>"
            f"<td>{int(scene.get('rendered_shot_count') or 0)}</td>"
            f"<td>{int(scene.get('pending_shot_count') or 0)}</td>"
            f"<td>{int(scene.get('total_frames') or 0)}</td>"
            f"<td>{escape('、'.join(shot_labels))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="9" class="empty">暂无分场记录，请先在 Blender 导演台保存带场次的镜头。</td></tr>')
    unassigned_rows = []
    for shot in breakdown.get("unassigned_shots", []):
        if not isinstance(shot, dict):
            continue
        unassigned_rows.append(
            "<tr>"
            f"<td>{escape(str(shot.get('shot_name') or shot.get('shot_id') or '未命名镜头'))}</td>"
            f"<td>{escape(str(shot.get('queue_status_label') or ''))}</td>"
            f"<td>{escape(str(shot.get('frame_start') or ''))}-{escape(str(shot.get('frame_end') or ''))}</td>"
            "</tr>"
        )
    if not unassigned_rows:
        unassigned_rows.append('<tr><td colspan="3" class="empty">没有未分场镜头</td></tr>')
    updated_at = str(breakdown.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 分场表</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 24px 0 10px; font-size: 18px; }}
    .meta {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 分场表</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(breakdown.get('scene_count') or 0)}</strong>场次</div>
      <div class="stat"><strong>{int(breakdown.get('unassigned_shot_count') or 0)}</strong>未分场镜头</div>
    </div>
    <h2>场次镜头表</h2>
    <table>
      <thead><tr><th>场次</th><th>地点</th><th>内外景</th><th>日夜</th><th>镜头</th><th>已渲染</th><th>待渲染</th><th>总帧数</th><th>镜头列表</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <h2>未分场镜头</h2>
    <table>
      <thead><tr><th>镜头</th><th>渲染状态</th><th>帧段</th></tr></thead>
      <tbody>{''.join(unassigned_rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "scene_breakdown.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_episode_delivery(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    episodes = {}
    total_shots = 0
    total_frames = 0
    rendered_count = 0
    pending_count = 0

    def unique_push(items, seen, record):
        key = str(record.get("id") or record.get("name") or "").strip()
        if not key or key in seen:
            return
        items.append(record)
        seen.add(key)

    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        total_shots += 1
        episode_number = str(
            item.get("episode_number")
            or item.get("episode")
            or metadata.get("episode_number")
            or ""
        ).strip()
        episode_name = str(item.get("episode_name") or metadata.get("episode_name") or "").strip()
        if not episode_number and not episode_name:
            episode_number = "未分集"
        episode_key = "|".join(part for part in (episode_number, episode_name) if part) or "未分集"
        episode = episodes.setdefault(
            episode_key,
            {
                "episode_key": episode_key,
                "episode_number": episode_number or "未分集",
                "episode_name": episode_name,
                "shot_count": 0,
                "rendered_shot_count": 0,
                "pending_shot_count": 0,
                "total_frames": 0,
                "scene_count": 0,
                "actor_count": 0,
                "asset_count": 0,
                "actors": [],
                "assets": [],
                "scenes": [],
                "_scene_map": {},
                "_actor_seen": set(),
                "_asset_seen": set(),
            },
        )
        scene_number = str(item.get("scene_number") or "").strip() or "未分场"
        scene_location = str(item.get("scene_location") or "").strip()
        scene_environment = str(item.get("scene_environment_label") or item.get("scene_environment") or "").strip()
        scene_time = str(item.get("scene_time_label") or item.get("scene_time") or "").strip()
        scene_key = "|".join(part for part in (scene_number, scene_location, scene_environment, scene_time) if part) or "未分场"
        scene = episode["_scene_map"].setdefault(
            scene_key,
            {
                "scene_key": scene_key,
                "scene_number": scene_number,
                "scene_location": scene_location,
                "scene_environment": scene_environment,
                "scene_time": scene_time,
                "shot_count": 0,
                "rendered_shot_count": 0,
                "pending_shot_count": 0,
                "total_frames": 0,
                "actors": [],
                "assets": [],
                "shots": [],
                "_actor_seen": set(),
                "_asset_seen": set(),
            },
        )
        duration_frames = _duration_frames_from_range(item.get("frame_start"), item.get("frame_end"))
        rendered = bool(item.get("output_path") or item.get("preview_path") or item.get("last_rendered_at"))
        if rendered:
            rendered_count += 1
        else:
            pending_count += 1
        episode["shot_count"] += 1
        scene["shot_count"] += 1
        if rendered:
            episode["rendered_shot_count"] += 1
            scene["rendered_shot_count"] += 1
        else:
            episode["pending_shot_count"] += 1
            scene["pending_shot_count"] += 1
        if duration_frames is not None:
            episode["total_frames"] += duration_frames
            scene["total_frames"] += duration_frames
            total_frames += duration_frames
        for actor in item.get("actors") if isinstance(item.get("actors"), list) else []:
            if not isinstance(actor, dict):
                continue
            record = {
                "id": str(actor.get("id") or "").strip(),
                "name": str(actor.get("name") or actor.get("id") or "").strip(),
                "role": str(actor.get("role") or "").strip(),
            }
            unique_push(episode["actors"], episode["_actor_seen"], record)
            unique_push(scene["actors"], scene["_actor_seen"], record)
        for asset in item.get("assets") if isinstance(item.get("assets"), list) else []:
            if not isinstance(asset, dict):
                continue
            record = {
                "id": str(asset.get("id") or "").strip(),
                "name": str(asset.get("name") or asset.get("id") or "").strip(),
                "type": str(asset.get("type") or "").strip(),
            }
            unique_push(episode["assets"], episode["_asset_seen"], record)
            unique_push(scene["assets"], scene["_asset_seen"], record)
        scene["shots"].append(
            {
                "index": item.get("index") or "",
                "shot_id": str(item.get("shot_id") or ""),
                "shot_name": str(item.get("shot_name") or ""),
                "queue_status": "done" if rendered else "pending",
                "queue_status_label": "已渲染" if rendered else "待渲染",
                "frame_start": item.get("frame_start"),
                "frame_end": item.get("frame_end"),
                "duration_frames": duration_frames,
                "output_label": str(item.get("output_label") or item.get("output_type") or ""),
            }
        )
    episode_rows = []
    for episode in episodes.values():
        scenes = sorted(
            episode["_scene_map"].values(),
            key=lambda scene: (
                str(scene.get("scene_number") or ""),
                str(scene.get("scene_location") or ""),
                str(scene.get("scene_environment") or ""),
                str(scene.get("scene_time") or ""),
            ),
        )
        for scene in scenes:
            scene.pop("_actor_seen", None)
            scene.pop("_asset_seen", None)
        episode["scenes"] = scenes
        episode["scene_count"] = len(scenes)
        episode["actor_count"] = len(episode.get("actors", []))
        episode["asset_count"] = len(episode.get("assets", []))
        episode.pop("_scene_map", None)
        episode.pop("_actor_seen", None)
        episode.pop("_asset_seen", None)
        episode_rows.append(episode)
    episode_rows = sorted(
        episode_rows,
        key=lambda item: (str(item.get("episode_number") or ""), str(item.get("episode_name") or "")),
    )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "episode_count": len(episode_rows),
        "shot_count": total_shots,
        "rendered_shot_count": rendered_count,
        "pending_shot_count": pending_count,
        "total_frames": total_frames,
        "episodes": episode_rows,
    }


def write_blender_director_episode_delivery_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "episode_delivery.json")
    data = build_blender_director_episode_delivery(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_episode_delivery_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "episode_delivery.csv")
    data = build_blender_director_episode_delivery(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["分集", "分集名", "场次", "地点", "镜头数", "已渲染", "待渲染", "总帧数", "演员", "资产", "镜头"])
        for episode in data.get("episodes", []):
            if not isinstance(episode, dict):
                continue
            for scene in episode.get("scenes", []) if isinstance(episode.get("scenes"), list) else []:
                if not isinstance(scene, dict):
                    continue
                actors = scene.get("actors") if isinstance(scene.get("actors"), list) else []
                assets = scene.get("assets") if isinstance(scene.get("assets"), list) else []
                shots = scene.get("shots") if isinstance(scene.get("shots"), list) else []
                actor_text = "、".join(str(actor.get("name") or actor.get("id") or "").strip() for actor in actors if isinstance(actor, dict) and str(actor.get("name") or actor.get("id") or "").strip())
                asset_text = "、".join(str(asset.get("name") or asset.get("id") or "").strip() for asset in assets if isinstance(asset, dict) and str(asset.get("name") or asset.get("id") or "").strip())
                shot_text = "、".join(str(shot.get("shot_name") or shot.get("shot_id") or "").strip() for shot in shots if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip())
                writer.writerow(
                    [
                        episode.get("episode_number") or "",
                        episode.get("episode_name") or "",
                        scene.get("scene_number") or "",
                        scene.get("scene_location") or "",
                        scene.get("shot_count") or 0,
                        scene.get("rendered_shot_count") or 0,
                        scene.get("pending_shot_count") or 0,
                        scene.get("total_frames") or 0,
                        actor_text,
                        asset_text,
                        shot_text,
                    ]
                )
    return path


def write_blender_director_episode_delivery_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_episode_delivery(metadata)
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    rows = []
    for episode in data.get("episodes", []):
        if not isinstance(episode, dict):
            continue
        episode_label = " / ".join(
            part for part in (str(episode.get("episode_number") or "").strip(), str(episode.get("episode_name") or "").strip()) if part
        ) or "未分集"
        for scene in episode.get("scenes", []) if isinstance(episode.get("scenes"), list) else []:
            if not isinstance(scene, dict):
                continue
            shots = scene.get("shots") if isinstance(scene.get("shots"), list) else []
            actors = scene.get("actors") if isinstance(scene.get("actors"), list) else []
            assets = scene.get("assets") if isinstance(scene.get("assets"), list) else []
            shot_text = "、".join(str(shot.get("shot_name") or shot.get("shot_id") or "").strip() for shot in shots if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip())
            actor_text = "、".join(str(actor.get("name") or actor.get("id") or "").strip() for actor in actors if isinstance(actor, dict) and str(actor.get("name") or actor.get("id") or "").strip())
            asset_text = "、".join(str(asset.get("name") or asset.get("id") or "").strip() for asset in assets if isinstance(asset, dict) and str(asset.get("name") or asset.get("id") or "").strip())
            scene_label = " / ".join(
                part
                for part in (
                    str(scene.get("scene_number") or "").strip(),
                    str(scene.get("scene_location") or "").strip(),
                    str(scene.get("scene_environment") or "").strip(),
                    str(scene.get("scene_time") or "").strip(),
                )
                if part
            ) or "未分场"
            rows.append(
                "<tr>"
                f"<td>{escape(episode_label)}</td>"
                f"<td>{escape(scene_label)}</td>"
                f"<td>{int(scene.get('shot_count') or 0)}</td>"
                f"<td>{int(scene.get('rendered_shot_count') or 0)}</td>"
                f"<td>{int(scene.get('pending_shot_count') or 0)}</td>"
                f"<td>{int(scene.get('total_frames') or 0)}</td>"
                f"<td>{escape(actor_text)}</td>"
                f"<td>{escape(asset_text)}</td>"
                f"<td>{escape(shot_text)}</td>"
                "</tr>"
            )
    if not rows:
        rows.append('<tr><td colspan="9" class="empty">暂无镜头，请先在 Blender 导演台保存镜头。</td></tr>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 分集交付清单</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 分集交付清单</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('episode_count') or 0)}</strong>分集</div>
      <div class="stat"><strong>{int(data.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(data.get('rendered_shot_count') or 0)}</strong>已渲染</div>
      <div class="stat"><strong>{int(data.get('pending_shot_count') or 0)}</strong>待渲染</div>
      <div class="stat"><strong>{int(data.get('total_frames') or 0)}</strong>总帧数</div>
    </div>
    <table>
      <thead><tr><th>分集</th><th>场次</th><th>镜头</th><th>已渲染</th><th>待渲染</th><th>帧数</th><th>演员</th><th>资产</th><th>镜头列表</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "episode_delivery.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_call_sheet(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    scenes = {}
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        scene_number = str(item.get("scene_number") or "").strip()
        scene_location = str(item.get("scene_location") or "").strip()
        scene_environment = str(item.get("scene_environment") or "").strip()
        scene_environment_label = str(item.get("scene_environment_label") or scene_environment).strip()
        scene_time = str(item.get("scene_time") or "").strip()
        scene_time_label = str(item.get("scene_time_label") or scene_time).strip()
        key = "|".join([scene_number, scene_location, scene_environment, scene_time]) or "__unassigned__"
        scene = scenes.setdefault(
            key,
            {
                "scene_number": scene_number or "未分场",
                "scene_location": scene_location,
                "scene_environment": scene_environment,
                "scene_environment_label": scene_environment_label,
                "scene_time": scene_time,
                "scene_time_label": scene_time_label,
                "shot_count": 0,
                "rendered_shot_count": 0,
                "pending_shot_count": 0,
                "total_frames": 0,
                "actors": [],
                "assets": [],
                "shots": [],
            },
        )
        duration_frames = _duration_frames_from_range(item.get("frame_start"), item.get("frame_end"))
        rendered = bool(item.get("output_path") or item.get("preview_path") or item.get("last_rendered_at"))
        scene["shot_count"] += 1
        if rendered:
            scene["rendered_shot_count"] += 1
        else:
            scene["pending_shot_count"] += 1
        if duration_frames is not None:
            scene["total_frames"] += duration_frames
        actor_seen = {str(actor.get("id") or actor.get("name") or "") for actor in scene["actors"] if isinstance(actor, dict)}
        for actor in item.get("actors") if isinstance(item.get("actors"), list) else []:
            if not isinstance(actor, dict):
                continue
            actor_id = str(actor.get("id") or "").strip()
            actor_name = str(actor.get("name") or actor_id).strip()
            key_actor = actor_id or actor_name
            if key_actor and key_actor not in actor_seen:
                scene["actors"].append(
                    {
                        "id": actor_id,
                        "name": actor_name,
                        "role": str(actor.get("role") or "").strip(),
                    }
                )
                actor_seen.add(key_actor)
        asset_seen = {str(asset.get("id") or asset.get("name") or "") for asset in scene["assets"] if isinstance(asset, dict)}
        for asset in item.get("assets") if isinstance(item.get("assets"), list) else []:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get("id") or "").strip()
            asset_name = str(asset.get("name") or asset_id).strip()
            key_asset = asset_id or asset_name
            if key_asset and key_asset not in asset_seen:
                scene["assets"].append(
                    {
                        "id": asset_id,
                        "name": asset_name,
                        "type": str(asset.get("type") or "").strip(),
                    }
                )
                asset_seen.add(key_asset)
        scene["shots"].append(
            {
                "index": item.get("index") or "",
                "shot_id": str(item.get("shot_id") or ""),
                "shot_name": str(item.get("shot_name") or ""),
                "queue_status": "done" if rendered else "pending",
                "queue_status_label": "已渲染" if rendered else "待渲染",
                "frame_start": item.get("frame_start"),
                "frame_end": item.get("frame_end"),
                "duration_frames": duration_frames,
                "output_label": str(item.get("output_label") or item.get("output_type") or ""),
            }
        )
    rows = sorted(
        scenes.values(),
        key=lambda item: (
            str(item.get("scene_number") or ""),
            str(item.get("scene_location") or ""),
            str(item.get("scene_environment") or ""),
            str(item.get("scene_time") or ""),
        ),
    )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scene_count": len(rows),
        "shot_count": sum(int(item.get("shot_count") or 0) for item in rows),
        "pending_shot_count": sum(int(item.get("pending_shot_count") or 0) for item in rows),
        "total_frames": sum(int(item.get("total_frames") or 0) for item in rows),
        "scenes": rows,
    }


def write_blender_director_call_sheet_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "call_sheet.json")
    data = build_blender_director_call_sheet(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_call_sheet_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "call_sheet.csv")
    call_sheet = build_blender_director_call_sheet(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["场次", "地点", "内外景", "日夜", "镜头数", "待渲染", "总帧数", "演员", "资产", "镜头"])
        for scene in call_sheet.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            actors = scene.get("actors") if isinstance(scene.get("actors"), list) else []
            actor_text = "、".join(
                str(actor.get("name") or actor.get("id") or "").strip()
                for actor in actors
                if isinstance(actor, dict) and str(actor.get("name") or actor.get("id") or "").strip()
            )
            assets = scene.get("assets") if isinstance(scene.get("assets"), list) else []
            asset_text = "、".join(
                str(asset.get("name") or asset.get("id") or "").strip()
                for asset in assets
                if isinstance(asset, dict) and str(asset.get("name") or asset.get("id") or "").strip()
            )
            shots = scene.get("shots") if isinstance(scene.get("shots"), list) else []
            shot_text = "、".join(
                str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
                for shot in shots
                if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            )
            writer.writerow(
                [
                    scene.get("scene_number") or "",
                    scene.get("scene_location") or "",
                    scene.get("scene_environment_label") or scene.get("scene_environment") or "",
                    scene.get("scene_time_label") or scene.get("scene_time") or "",
                    scene.get("shot_count") or 0,
                    scene.get("pending_shot_count") or 0,
                    scene.get("total_frames") or 0,
                    actor_text,
                    asset_text,
                    shot_text,
                ]
            )
    return path


def write_blender_director_call_sheet_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    call_sheet = build_blender_director_call_sheet(metadata)
    project_name = str(call_sheet.get("project_name") or "Blender 导演台工程")
    rows = []
    for scene in call_sheet.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        actors = scene.get("actors") if isinstance(scene.get("actors"), list) else []
        actor_text = "、".join(
            str(actor.get("name") or actor.get("id") or "").strip()
            for actor in actors
            if isinstance(actor, dict) and str(actor.get("name") or actor.get("id") or "").strip()
        )
        assets = scene.get("assets") if isinstance(scene.get("assets"), list) else []
        asset_text = "、".join(
            str(asset.get("name") or asset.get("id") or "").strip()
            for asset in assets
            if isinstance(asset, dict) and str(asset.get("name") or asset.get("id") or "").strip()
        )
        shots = scene.get("shots") if isinstance(scene.get("shots"), list) else []
        shot_labels = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            name = str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            status = str(shot.get("queue_status_label") or "").strip()
            if name and status:
                shot_labels.append(f"{name}（{status}）")
            elif name:
                shot_labels.append(name)
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(scene.get('scene_number') or '未分场'))}</strong></td>"
            f"<td>{escape(str(scene.get('scene_location') or ''))}</td>"
            f"<td>{escape(str(scene.get('scene_environment_label') or scene.get('scene_environment') or ''))}</td>"
            f"<td>{escape(str(scene.get('scene_time_label') or scene.get('scene_time') or ''))}</td>"
            f"<td>{int(scene.get('shot_count') or 0)}</td>"
            f"<td>{int(scene.get('pending_shot_count') or 0)}</td>"
            f"<td>{int(scene.get('total_frames') or 0)}</td>"
            f"<td>{escape(actor_text)}</td>"
            f"<td>{escape(asset_text)}</td>"
            f"<td>{escape('、'.join(shot_labels))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="10" class="empty">暂无拍摄单内容</td></tr>')
    updated_at = str(call_sheet.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 拍摄单</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 拍摄单</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(call_sheet.get('scene_count') or 0)}</strong>场次</div>
      <div class="stat"><strong>{int(call_sheet.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(call_sheet.get('pending_shot_count') or 0)}</strong>待渲染</div>
      <div class="stat"><strong>{int(call_sheet.get('total_frames') or 0)}</strong>总帧数</div>
    </div>
    <table>
      <thead><tr><th>场次</th><th>地点</th><th>内外景</th><th>日夜</th><th>镜头</th><th>待渲染</th><th>总帧数</th><th>演员</th><th>资产</th><th>镜头列表</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "call_sheet.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_actor_schedule(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    actors_by_key = {}
    unassigned_shots = []
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        preview_path = str(item.get("preview_path") or "").strip()
        output_path = str(item.get("output_path") or "").strip()
        rendered = bool(output_path or preview_path or item.get("last_rendered_at"))
        frame_start = item.get("frame_start")
        frame_end = item.get("frame_end")
        duration_frames = None
        if frame_start is not None and frame_end is not None:
            try:
                duration_frames = max(0, int(frame_end) - int(frame_start) + 1)
            except Exception:
                duration_frames = None
        actors = item.get("actors") if isinstance(item.get("actors"), list) else []
        if not actors:
            unassigned_shots.append(
                {
                    "shot_id": str(item.get("shot_id") or ""),
                    "shot_name": str(item.get("shot_name") or ""),
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                    "duration_frames": duration_frames,
                    "queue_status": "done" if rendered else "pending",
                    "queue_status_label": "已渲染" if rendered else "待渲染",
                }
            )
            continue
        for actor in actors:
            if not isinstance(actor, dict):
                continue
            actor_id = str(actor.get("id") or "").strip()
            name = str(actor.get("name") or actor_id or "").strip()
            role = str(actor.get("role") or "").strip()
            key = actor_id or f"name:{name}" or f"role:{role}"
            if not key:
                continue
            row = actors_by_key.setdefault(
                key,
                {
                    "id": actor_id,
                    "name": name or role or actor_id,
                    "role": role,
                    "shot_count": 0,
                    "rendered_shot_count": 0,
                    "pending_shot_count": 0,
                    "total_frames": 0,
                    "shots": [],
                },
            )
            row["shot_count"] += 1
            if rendered:
                row["rendered_shot_count"] += 1
            else:
                row["pending_shot_count"] += 1
            if duration_frames is not None:
                row["total_frames"] += duration_frames
            row["shots"].append(
                {
                    "index": item.get("index") or "",
                    "shot_id": str(item.get("shot_id") or ""),
                    "shot_name": str(item.get("shot_name") or ""),
                    "shot_status": str(item.get("shot_status") or ""),
                    "shot_status_label": str(item.get("shot_status_label") or item.get("shot_status") or ""),
                    "queue_status": "done" if rendered else "pending",
                    "queue_status_label": "已渲染" if rendered else "待渲染",
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                    "duration_frames": duration_frames,
                    "output_type": str(item.get("output_type") or ""),
                    "output_label": str(item.get("output_label") or item.get("output_type") or ""),
                    "render_version": item.get("render_version"),
                    "last_rendered_at": str(item.get("last_rendered_at") or ""),
                }
            )
    actors = sorted(
        actors_by_key.values(),
        key=lambda item: (-int(item.get("shot_count") or 0), str(item.get("name") or item.get("id") or "")),
    )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "actor_count": len(actors),
        "unassigned_shot_count": len(unassigned_shots),
        "actors": actors,
        "unassigned_shots": unassigned_shots,
    }


def write_blender_director_actor_schedule_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "actor_schedule.json")
    data = build_blender_director_actor_schedule(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_actor_schedule_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "actor_schedule.csv")
    schedule = build_blender_director_actor_schedule(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "演员ID",
                "演员名",
                "角色",
                "镜头数",
                "已渲染镜头",
                "待渲染镜头",
                "总帧数",
                "引用镜头",
            ]
        )
        for actor in schedule.get("actors", []):
            if not isinstance(actor, dict):
                continue
            shots = actor.get("shots") if isinstance(actor.get("shots"), list) else []
            shot_text = "、".join(
                str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
                for shot in shots
                if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            )
            writer.writerow(
                [
                    actor.get("id") or "",
                    actor.get("name") or "",
                    actor.get("role") or "",
                    actor.get("shot_count") or 0,
                    actor.get("rendered_shot_count") or 0,
                    actor.get("pending_shot_count") or 0,
                    actor.get("total_frames") or 0,
                    shot_text,
                ]
            )
    return path


def write_blender_director_actor_schedule_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    schedule = build_blender_director_actor_schedule(metadata)
    project_name = str(schedule.get("project_name") or "Blender 导演台工程")
    rows = []
    for actor in schedule.get("actors", []):
        if not isinstance(actor, dict):
            continue
        shots = actor.get("shots") if isinstance(actor.get("shots"), list) else []
        shot_labels = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            name = str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            status = str(shot.get("queue_status_label") or "").strip()
            if name and status:
                shot_labels.append(f"{name}（{status}）")
            elif name:
                shot_labels.append(name)
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(actor.get('name') or actor.get('id') or '未命名演员'))}</strong><div class=\"id\">{escape(str(actor.get('id') or ''))}</div></td>"
            f"<td>{escape(str(actor.get('role') or ''))}</td>"
            f"<td>{int(actor.get('shot_count') or 0)}</td>"
            f"<td>{int(actor.get('rendered_shot_count') or 0)}</td>"
            f"<td>{int(actor.get('pending_shot_count') or 0)}</td>"
            f"<td>{int(actor.get('total_frames') or 0)}</td>"
            f"<td>{escape('、'.join(shot_labels))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="7" class="empty">暂无演员记录，请先在 Blender 导演台保存带演员的镜头。</td></tr>')
    unassigned_rows = []
    for shot in schedule.get("unassigned_shots", []):
        if not isinstance(shot, dict):
            continue
        unassigned_rows.append(
            "<tr>"
            f"<td>{escape(str(shot.get('shot_name') or shot.get('shot_id') or '未命名镜头'))}</td>"
            f"<td>{escape(str(shot.get('queue_status_label') or ''))}</td>"
            f"<td>{escape(str(shot.get('frame_start') or ''))}-{escape(str(shot.get('frame_end') or ''))}</td>"
            "</tr>"
        )
    if not unassigned_rows:
        unassigned_rows.append('<tr><td colspan="3" class="empty">没有未绑定演员的镜头</td></tr>')
    updated_at = str(schedule.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 演员调度</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 24px 0 10px; font-size: 18px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 演员调度</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(schedule.get('actor_count') or 0)}</strong>演员/角色</div>
      <div class="stat"><strong>{int(schedule.get('unassigned_shot_count') or 0)}</strong>未绑定演员镜头</div>
    </div>
    <h2>演员镜头表</h2>
    <table>
      <thead><tr><th>演员</th><th>角色</th><th>镜头</th><th>已渲染</th><th>待渲染</th><th>总帧数</th><th>引用镜头</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <h2>未绑定演员镜头</h2>
    <table>
      <thead><tr><th>镜头</th><th>渲染状态</th><th>帧段</th></tr></thead>
      <tbody>{''.join(unassigned_rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "actor_schedule.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_production_manifest(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    storyboard = build_blender_director_storyboard(metadata)
    assets = metadata.get("assets") if isinstance(metadata.get("assets"), list) else []
    renders = metadata.get("renders") if isinstance(metadata.get("renders"), list) else []
    used_asset_ids = set()
    used_asset_names = set()
    asset_usage_map = {}
    shot_rows = []
    rendered_count = 0
    approved_count = 0
    layered_count = 0
    for entry in storyboard:
        if not isinstance(entry, dict):
            continue
        output_path = str(entry.get("output_path") or "").strip()
        preview_path = str(entry.get("preview_path") or "").strip()
        rendered = bool(output_path or preview_path or entry.get("last_rendered_at"))
        if rendered:
            rendered_count += 1
        if str(entry.get("shot_status") or "") == "approved" or str(entry.get("shot_status_label") or "") == "已定稿":
            approved_count += 1
        if str(entry.get("output_type") or "") == "layered":
            layered_count += 1
        entry_assets = entry.get("assets") if isinstance(entry.get("assets"), list) else []
        for asset in entry_assets:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get("id") or "").strip()
            asset_name = str(asset.get("name") or "").strip()
            if asset_id:
                used_asset_ids.add(asset_id)
            if asset_name:
                used_asset_names.add(asset_name)
            usage_key = asset_id or f"name:{asset_name}"
            if usage_key:
                usage = asset_usage_map.setdefault(
                    usage_key,
                    {
                        "id": asset_id,
                        "name": asset_name,
                        "type": str(asset.get("type") or ""),
                        "shots": [],
                    },
                )
                usage["shots"].append(
                    {
                        "shot_id": str(entry.get("shot_id") or ""),
                        "shot_name": str(entry.get("shot_name") or ""),
                    }
                )
        shot_rows.append(
            {
                "shot_id": str(entry.get("shot_id") or ""),
                "shot_name": str(entry.get("shot_name") or ""),
                "shot_status": str(entry.get("shot_status") or ""),
                "shot_status_label": str(entry.get("shot_status_label") or entry.get("shot_status") or ""),
                "rendered": rendered,
                "render_version": entry.get("render_version"),
                "output_type": str(entry.get("output_type") or ""),
                "output_label": str(entry.get("output_label") or entry.get("output_type") or ""),
                "asset_count": len(entry_assets),
                "assets": entry_assets,
                "preview_path": preview_path,
                "output_path": output_path,
                "last_rendered_at": str(entry.get("last_rendered_at") or ""),
            }
        )
    asset_rows = []
    unused_assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("id") or "").strip()
        asset_name = str(asset.get("name") or asset.get("file_name") or asset_id).strip()
        used = bool((asset_id and asset_id in used_asset_ids) or (asset_name and asset_name in used_asset_names))
        row = {
            "id": asset_id,
            "name": asset_name,
            "type": str(asset.get("type") or ""),
            "format": str(asset.get("format") or ""),
            "used": used,
            "used_by_shots": asset_usage_map.get(asset_id or f"name:{asset_name}", {}).get("shots", []),
            "path": str(asset.get("path") or ""),
            "library_item_id": str(asset.get("library_item_id") or ""),
            "library_relative_path": str(asset.get("library_relative_path") or ""),
        }
        asset_rows.append(row)
        if not used:
            unused_assets.append(row)
    shot_count = len(storyboard)
    render_count = len(renders)
    retarget_summary = build_blender_director_retarget_summary(metadata)
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shot_count": shot_count,
        "rendered_shot_count": rendered_count,
        "pending_shot_count": max(0, shot_count - rendered_count),
        "approved_shot_count": approved_count,
        "render_count": render_count,
        "layered_output_count": layered_count,
        "asset_count": len(asset_rows),
        "used_asset_count": len(asset_rows) - len(unused_assets),
        "unused_asset_count": len(unused_assets),
        "shots": shot_rows,
        "assets": asset_rows,
        "asset_usage": sorted(
            asset_usage_map.values(),
            key=lambda item: str(item.get("name") or item.get("id") or ""),
        ),
        "unused_assets": unused_assets,
        "retarget_summary": retarget_summary,
    }


def write_blender_director_production_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "production_manifest.json")
    data = build_blender_director_production_manifest(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_production_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    manifest = build_blender_director_production_manifest(metadata)
    project_name = str(manifest.get("project_name") or "Blender 导演台工程")
    shot_rows = []
    for shot in manifest.get("shots", []):
        if not isinstance(shot, dict):
            continue
        assets = shot.get("assets") if isinstance(shot.get("assets"), list) else []
        asset_names = []
        for asset in assets:
            if isinstance(asset, dict):
                name = str(asset.get("name") or asset.get("id") or "").strip()
                if name:
                    asset_names.append(name)
        render_version = shot.get("render_version")
        version_text = ("v" + str(render_version)) if render_version not in (None, "") else ""
        shot_rows.append(
            "<tr>"
            f"<td>{escape(str(shot.get('shot_name') or shot.get('shot_id') or '未命名镜头'))}<div class=\"id\">{escape(str(shot.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(str(shot.get('shot_status_label') or shot.get('shot_status') or ''))}</td>"
            f"<td>{'已渲染' if shot.get('rendered') else '未渲染'}</td>"
            f"<td>{escape(version_text)}</td>"
            f"<td>{escape(str(shot.get('output_label') or shot.get('output_type') or ''))}</td>"
            f"<td>{escape('、'.join(asset_names))}</td>"
            f"<td>{escape(str(shot.get('last_rendered_at') or ''))}</td>"
            "</tr>"
        )
    if not shot_rows:
        shot_rows.append('<tr><td colspan="7" class="empty">暂无镜头</td></tr>')
    asset_rows = []
    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict):
            continue
        asset_rows.append(
            "<tr>"
            f"<td>{escape(str(asset.get('name') or asset.get('id') or '未命名资产'))}<div class=\"id\">{escape(str(asset.get('id') or ''))}</div></td>"
            f"<td>{escape(str(asset.get('type') or ''))}</td>"
            f"<td>{escape(str(asset.get('format') or ''))}</td>"
            f"<td>{'已使用' if asset.get('used') else '未使用'}</td>"
            f"<td>{escape('、'.join(str(shot.get('shot_name') or shot.get('shot_id') or '') for shot in asset.get('used_by_shots', []) if isinstance(shot, dict)))}</td>"
            f"<td>{escape(str(asset.get('library_relative_path') or asset.get('path') or ''))}</td>"
            "</tr>"
        )
    if not asset_rows:
        asset_rows.append('<tr><td colspan="6" class="empty">暂无工程资产</td></tr>')
    retarget_summary = manifest.get("retarget_summary") if isinstance(manifest.get("retarget_summary"), dict) else {}
    retarget_clip_rows = []
    for clip in retarget_summary.get("action_clips", []):
        if not isinstance(clip, dict):
            continue
        retarget_clip_rows.append(
            "<tr>"
            f"<td>{escape(str(clip.get('name') or clip.get('id') or '重定向动作片段'))}<div class=\"id\">{escape(str(clip.get('id') or ''))}</div></td>"
            f"<td>{escape(str(clip.get('retarget_profile_name') or ''))}</td>"
            f"<td>{escape(str(clip.get('target_armature') or ''))}</td>"
            f"<td>{int(clip.get('mapped_bone_count') or 0)} / 源缺 {int(clip.get('unmapped_source_count') or 0)} / 目标缺 {int(clip.get('unmapped_target_count') or 0)}</td>"
            f"<td>{float(clip.get('rest_pose_max_angle_degrees') or 0):.1f}° / {int(clip.get('rest_pose_mismatch_bone_count') or 0)} 根</td>"
            f"<td>{float(clip.get('root_motion_scale') or 1.0):.3f}</td>"
            f"<td>{int(clip.get('copied_fcurve_count') or 0)} / 跳过 {int(clip.get('skipped_fcurve_count') or 0)}</td>"
            "</tr>"
        )
    if not retarget_clip_rows:
        retarget_clip_rows.append('<tr><td colspan="7" class="empty">暂无已生成的重定向动作片段</td></tr>')
    updated_at = str(manifest.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 制作清单</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 22px 0 10px; font-size: 18px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 制作清单</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(manifest.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(manifest.get('rendered_shot_count') or 0)}</strong>已渲染镜头</div>
      <div class="stat"><strong>{int(manifest.get('pending_shot_count') or 0)}</strong>待渲染镜头</div>
      <div class="stat"><strong>{int(manifest.get('approved_shot_count') or 0)}</strong>已定稿镜头</div>
      <div class="stat"><strong>{int(manifest.get('asset_count') or 0)}</strong>工程资产</div>
      <div class="stat"><strong>{int(manifest.get('unused_asset_count') or 0)}</strong>未使用资产</div>
      <div class="stat"><strong>{int(retarget_summary.get('ready_clip_count') or 0)}</strong>重定向动作片段</div>
      <div class="stat"><strong>{int(retarget_summary.get('failure_count') or 0)}</strong>重定向失败</div>
    </div>
    <h2>镜头进度</h2>
    <table>
      <thead><tr><th>镜头</th><th>状态</th><th>渲染</th><th>版本</th><th>输出</th><th>资产</th><th>渲染时间</th></tr></thead>
      <tbody>{''.join(shot_rows)}</tbody>
    </table>
    <h2>资产使用</h2>
    <table>
      <thead><tr><th>资产</th><th>类型</th><th>格式</th><th>使用状态</th><th>引用镜头</th><th>来源</th></tr></thead>
      <tbody>{''.join(asset_rows)}</tbody>
    </table>
    <h2>重定向动作质量</h2>
    <table>
      <thead><tr><th>动作片段</th><th>档案</th><th>目标骨骼</th><th>骨骼映射</th><th>Rest Pose 差异</th><th>根运动比例</th><th>曲线</th></tr></thead>
      <tbody>{''.join(retarget_clip_rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "production_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def write_blender_director_asset_usage_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "asset_usage.csv")
    manifest = build_blender_director_production_manifest(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["资产ID", "资产名", "类型", "格式", "使用状态", "引用镜头", "来源"])
        for asset in manifest.get("assets", []):
            if not isinstance(asset, dict):
                continue
            shots = asset.get("used_by_shots") if isinstance(asset.get("used_by_shots"), list) else []
            shot_names = "、".join(
                str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
                for shot in shots
                if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            )
            writer.writerow(
                [
                    asset.get("id") or "",
                    asset.get("name") or "",
                    asset.get("type") or "",
                    asset.get("format") or "",
                    "已使用" if asset.get("used") else "未使用",
                    shot_names,
                    asset.get("library_relative_path") or asset.get("path") or "",
                ]
            )
    return path


def _asset_ecosystem_license_hint(profile_id="", profile_name="", record=None):
    record = record if isinstance(record, dict) else {}
    explicit = str(
        record.get("license")
        or record.get("license_label")
        or record.get("usage_rights")
        or record.get("authorization")
        or record.get("rights")
        or ""
    ).strip()
    if explicit:
        return explicit, "ok"
    profile_text = (str(profile_id or "") + " " + str(profile_name or "")).lower()
    if "poly_haven" in profile_text or "poly haven" in profile_text or "ambientcg" in profile_text:
        return "CC0 / 可商用（按来源说明归档）", "ok"
    if "mixamo" in profile_text:
        return "Mixamo / Adobe 使用条款，需保留来源", "review"
    if "blender_asset_browser" in profile_text or "asset browser" in profile_text:
        return "Blender Asset Browser 本地库，需逐项保留原始授权", "review"
    if "blenderkit" in profile_text:
        return "BlenderKit 原资产授权，需逐项保留", "review"
    if "sketchfab" in profile_text or "opengameart" in profile_text or "open game art" in profile_text:
        return "按原始下载页授权，需逐项核对", "review"
    return "未标注授权来源", "missing"


def _asset_ecosystem_kind_label(kind):
    labels = {
        "character": "人物/角色",
        "prop": "物品/道具",
        "scene": "场景/布景",
        "action": "动作/动画",
        "model": "通用模型",
        "material": "材质",
        "texture": "贴图",
        "hdri": "HDRI",
    }
    return labels.get(str(kind or ""), str(kind or "未分类"))


def build_blender_director_asset_ecosystem(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    profiles = metadata.get("open_asset_source_profiles") if isinstance(metadata.get("open_asset_source_profiles"), list) else []
    profile_by_id = {}
    for profile in _default_open_asset_source_profiles() + [item for item in profiles if isinstance(item, dict)]:
        profile_id = str(profile.get("id") or "").strip()
        if profile_id:
            profile_by_id[profile_id] = profile
    sources = metadata.get("asset_sources") if isinstance(metadata.get("asset_sources"), list) else []
    libraries = metadata.get("asset_libraries") if isinstance(metadata.get("asset_libraries"), list) else []
    items = metadata.get("asset_library_items") if isinstance(metadata.get("asset_library_items"), list) else []
    assets = metadata.get("assets") if isinstance(metadata.get("assets"), list) else []
    imported_library_ids = set()
    imported_source_paths = set()
    imported_asset_paths = set()
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        for key in ("library_item_id",):
            value = str(asset.get(key) or "").strip()
            if value:
                imported_library_ids.add(value)
        for key in ("source_path", "path"):
            value = str(asset.get(key) or "").strip()
            if value:
                imported_source_paths.add(os.path.abspath(value))
                imported_asset_paths.add(os.path.abspath(value))
        for path in asset.get("source_texture_paths") if isinstance(asset.get("source_texture_paths"), list) else []:
            value = str(path or "").strip()
            if value:
                imported_source_paths.add(os.path.abspath(value))
    source_rows = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_path = str(source.get("path") or "").strip()
        profile_id = str(source.get("profile_id") or source.get("source_profile_id") or "").strip()
        profile_name = str(source.get("profile_name") or source.get("source_profile_name") or profile_by_id.get(profile_id, {}).get("name") or "").strip()
        license_label, license_status = _asset_ecosystem_license_hint(profile_id, profile_name, source)
        source_rows.append(
            {
                "id": str(source.get("id") or ""),
                "name": str(source.get("name") or os.path.basename(source_path) or "资产源"),
                "path": source_path,
                "exists": bool(source_path and os.path.isdir(source_path)),
                "profile_id": profile_id,
                "profile_name": profile_name or "通用本地资产库",
                "license_label": license_label,
                "license_status": license_status,
                "item_count": int(source.get("item_count") or 0),
                "scanned_at": str(source.get("scanned_at") or ""),
                "route": str(source.get("route") or profile_by_id.get(profile_id, {}).get("route") or ""),
            }
        )
    library_rows = []
    for library in libraries:
        if not isinstance(library, dict):
            continue
        library_path = str(library.get("path") or "").strip()
        profile_id = str(library.get("source_profile_id") or "").strip()
        profile_name = str(library.get("source_profile_name") or profile_by_id.get(profile_id, {}).get("name") or "").strip()
        license_label, license_status = _asset_ecosystem_license_hint(profile_id, profile_name, library)
        library_rows.append(
            {
                "id": str(library.get("id") or ""),
                "name": str(library.get("name") or os.path.basename(library_path) or "资产库"),
                "path": library_path,
                "exists": bool(library_path and os.path.isdir(library_path)),
                "source_profile_id": profile_id,
                "source_profile_name": profile_name,
                "license_label": license_label,
                "license_status": license_status,
                "item_count": int(library.get("item_count") or 0),
                "asset_browser_catalog_count": int(library.get("asset_browser_catalog_count") or 0),
                "asset_browser_catalog_path": str(library.get("asset_browser_catalog_path") or ""),
                "scanned_at": str(library.get("scanned_at") or ""),
            }
        )
    item_rows = []
    kind_counts = {}
    format_counts = {}
    source_counts = {}
    missing_file_count = 0
    missing_license_count = 0
    favorite_count = 0
    tagged_count = 0
    imported_count = 0
    controllable_asset_count = 0
    action_item_count = 0
    ready_action_count = 0
    unclassified_count = 0
    asset_browser_catalog_paths = set()
    total_size = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_path = str(item.get("path") or "").strip()
        abs_path = os.path.abspath(item_path) if item_path else ""
        exists = bool(item_path and os.path.isfile(item_path))
        if not exists:
            missing_file_count += 1
        kind = str(item.get("kind_hint") or item.get("type") or "model").strip() or "model"
        if not kind:
            unclassified_count += 1
        file_format = str(item.get("format") or os.path.splitext(item_path)[1].lstrip(".").lower()).strip().lower()
        profile_id = str(item.get("source_profile_id") or "").strip()
        profile_name = str(item.get("source_profile_name") or profile_by_id.get(profile_id, {}).get("name") or "").strip()
        license_label, license_status = _asset_ecosystem_license_hint(profile_id, profile_name, item)
        if license_status == "missing":
            missing_license_count += 1
        imported = bool(
            str(item.get("id") or "") in imported_library_ids
            or (abs_path and abs_path in imported_source_paths)
        )
        if imported:
            imported_count += 1
        favorite = bool(item.get("favorite"))
        if favorite:
            favorite_count += 1
        tagged = bool(str(item.get("tags") or "").strip() or str(item.get("usage_note") or "").strip())
        if tagged:
            tagged_count += 1
        try:
            usage_count = int(item.get("usage_count") or 0)
        except Exception:
            usage_count = 0
        if kind == "action":
            action_item_count += 1
            if imported or usage_count > 0:
                ready_action_count += 1
        try:
            size = int(item.get("size") or 0)
        except Exception:
            size = 0
        total_size += max(0, size)
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if file_format:
            format_counts[file_format] = format_counts.get(file_format, 0) + 1
        source_key = profile_name or profile_id or "未标注来源"
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        catalog_path = str(item.get("asset_browser_catalog_path") or "").strip()
        if catalog_path:
            asset_browser_catalog_paths.add(catalog_path)
        status_parts = []
        if not exists:
            status_parts.append("缺文件")
        if license_status == "missing":
            status_parts.append("缺授权来源")
        elif license_status == "review":
            status_parts.append("需核对授权")
        if not tagged:
            status_parts.append("未打标")
        if imported:
            status_parts.append("已导入")
        item_rows.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or item.get("file_name") or item.get("id") or "资产"),
                "file_name": str(item.get("file_name") or os.path.basename(item_path)),
                "path": item_path,
                "relative_path": str(item.get("relative_path") or ""),
                "library_id": str(item.get("library_id") or ""),
                "library_path": str(item.get("library_path") or ""),
                "exists": exists,
                "kind": kind,
                "kind_label": _asset_ecosystem_kind_label(kind),
                "format": file_format,
                "size": size,
                "source_profile_id": profile_id,
                "source_profile_name": profile_name,
                "asset_browser_catalog_id": str(item.get("asset_browser_catalog_id") or ""),
                "asset_browser_catalog_path": str(item.get("asset_browser_catalog_path") or ""),
                "asset_browser_catalog_name": str(item.get("asset_browser_catalog_name") or ""),
                "license_label": license_label,
                "license_status": license_status,
                "favorite": favorite,
                "tags": str(item.get("tags") or ""),
                "usage_note": str(item.get("usage_note") or ""),
                "usage_count": usage_count,
                "imported": imported,
                "status_label": " / ".join(status_parts) if status_parts else "可用",
                "modified_at": str(item.get("modified_at") or ""),
                "scanned_at": str(item.get("scanned_at") or ""),
            }
        )
    imported_rows = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        path = str(asset.get("path") or "").strip()
        source_path = str(asset.get("source_path") or "").strip()
        library_item_id = str(asset.get("library_item_id") or "").strip()
        profile_id = str(asset.get("source_profile_id") or "").strip()
        profile_name = str(asset.get("source_profile_name") or profile_by_id.get(profile_id, {}).get("name") or "").strip()
        license_label, license_status = _asset_ecosystem_license_hint(profile_id, profile_name, asset)
        controls = asset.get("controls") if isinstance(asset.get("controls"), list) else []
        control_objects = asset.get("control_objects") if isinstance(asset.get("control_objects"), list) else []
        control_root = str(asset.get("control_root") or "").strip()
        controllable = bool(control_root or control_objects or controls)
        if controllable:
            controllable_asset_count += 1
        imported_rows.append(
            {
                "id": str(asset.get("id") or ""),
                "name": str(asset.get("name") or asset.get("file_name") or asset.get("id") or "工程资产"),
                "type": str(asset.get("type") or ""),
                "kind_label": _asset_ecosystem_kind_label(asset.get("type") or ""),
                "format": str(asset.get("format") or ""),
                "path": path,
                "exists": bool(path and os.path.exists(path)),
                "source_path": source_path,
                "source_exists": bool(source_path and os.path.exists(source_path)),
                "library_item_id": library_item_id,
                "library_relative_path": str(asset.get("library_relative_path") or ""),
                "source_profile_id": profile_id,
                "source_profile_name": profile_name,
                "license_label": license_label,
                "license_status": license_status,
                "imported_at": str(asset.get("imported_at") or ""),
                "object_count": len(asset.get("objects")) if isinstance(asset.get("objects"), list) else 0,
                "action_count": len(asset.get("actions")) if isinstance(asset.get("actions"), list) else 0,
                "controllable": controllable,
                "control_root": control_root,
                "control_count": len(control_objects),
                "controls": controls,
            }
        )
    health_warnings = []
    if missing_file_count:
        health_warnings.append(f"库资产缺文件 {missing_file_count} 个")
    if missing_license_count:
        health_warnings.append(f"缺授权来源 {missing_license_count} 个")
    if unclassified_count:
        health_warnings.append(f"未分类资产 {unclassified_count} 个")
    if action_item_count and ready_action_count < action_item_count:
        health_warnings.append(f"动作资产待导入 {action_item_count - ready_action_count} 个")
    return {
        "profile_catalog_count": len(profile_by_id),
        "source_count": len(source_rows),
        "library_count": len(library_rows),
        "library_item_count": len(item_rows),
        "available_item_count": len(item_rows) - missing_file_count,
        "missing_file_count": missing_file_count,
        "missing_license_count": missing_license_count,
        "favorite_count": favorite_count,
        "tagged_count": tagged_count,
        "imported_item_count": imported_count,
        "imported_asset_count": len(imported_rows),
        "controllable_asset_count": controllable_asset_count,
        "action_item_count": action_item_count,
        "ready_action_count": ready_action_count,
        "unclassified_count": unclassified_count,
        "asset_browser_catalog_count": len(asset_browser_catalog_paths),
        "total_size": total_size,
        "kind_counts": [
            {"kind": key, "kind_label": _asset_ecosystem_kind_label(key), "count": value}
            for key, value in sorted(kind_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "format_counts": [
            {"format": key, "count": value}
            for key, value in sorted(format_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "source_counts": [
            {"source": key, "count": value}
            for key, value in sorted(source_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "health_warnings": health_warnings,
        "sources": source_rows,
        "libraries": library_rows,
        "items": item_rows,
        "imported_assets": imported_rows,
    }


def write_blender_director_asset_ecosystem_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "asset_ecosystem.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_blender_director_asset_ecosystem(metadata), f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_asset_ecosystem_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "asset_ecosystem.csv")
    data = build_blender_director_asset_ecosystem(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["类型", "名称", "分类", "格式", "来源", "Blender Catalog", "授权", "状态", "路径", "使用次数", "标签", "备注"])
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            writer.writerow(
                [
                    "库资产",
                    item.get("name") or "",
                    item.get("kind_label") or "",
                    item.get("format") or "",
                    item.get("source_profile_name") or "",
                    item.get("asset_browser_catalog_path") or item.get("asset_browser_catalog_name") or "",
                    item.get("license_label") or "",
                    item.get("status_label") or "",
                    item.get("relative_path") or item.get("path") or "",
                    item.get("usage_count") or 0,
                    item.get("tags") or "",
                    item.get("usage_note") or "",
                ]
            )
        for asset in data.get("imported_assets", []):
            if not isinstance(asset, dict):
                continue
            writer.writerow(
                [
                    "工程资产",
                    asset.get("name") or "",
                    asset.get("kind_label") or asset.get("type") or "",
                    asset.get("format") or "",
                    asset.get("source_profile_name") or "",
                    asset.get("asset_browser_catalog_path") or asset.get("asset_browser_catalog_name") or "",
                    asset.get("license_label") or "",
                    ("已导入" if asset.get("exists") else "工程文件缺失") + (" / 可控" if asset.get("controllable") else ""),
                    asset.get("library_relative_path") or asset.get("path") or "",
                    "",
                    "",
                    "",
                ]
            )
    return path


def write_blender_director_asset_ecosystem_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_asset_ecosystem(metadata)
    project_name = str((metadata or {}).get("project_name") or "Blender 导演台工程")

    def empty_row(columns, text):
        return f'<tr><td colspan="{columns}" class="empty">{escape(text)}</td></tr>'

    source_rows = []
    for source in data.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_rows.append(
            "<tr>"
            f"<td>{escape(str(source.get('name') or source.get('id') or '资产源'))}<div class=\"id\">{escape(str(source.get('profile_name') or ''))}</div></td>"
            f"<td>{'可用' if source.get('exists') else '目录缺失'}</td>"
            f"<td>{escape(str(source.get('license_label') or ''))}</td>"
            f"<td>{int(source.get('item_count') or 0)}</td>"
            f"<td>{escape(str(source.get('route') or ''))}</td>"
            f"<td>{escape(str(source.get('path') or ''))}</td>"
            "</tr>"
        )
    if not source_rows:
        source_rows.append(empty_row(6, "暂无资产源，请先扫描本地开源资产库"))

    item_rows = []
    for item in data.get("items", [])[:300]:
        if not isinstance(item, dict):
            continue
        item_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('name') or item.get('id') or '库资产'))}<div class=\"id\">{escape(str(item.get('relative_path') or item.get('file_name') or ''))}</div></td>"
            f"<td>{escape(str(item.get('kind_label') or ''))}</td>"
            f"<td>{escape(str(item.get('format') or '').upper())}</td>"
            f"<td>{escape(str(item.get('source_profile_name') or '未标注来源'))}</td>"
            f"<td>{escape(str(item.get('asset_browser_catalog_path') or item.get('asset_browser_catalog_name') or '—'))}</td>"
            f"<td>{escape(str(item.get('license_label') or ''))}</td>"
            f"<td>{escape(str(item.get('status_label') or ''))}</td>"
            f"<td>{'★' if item.get('favorite') else ''}</td>"
            f"<td>{escape(str(item.get('tags') or item.get('usage_note') or ''))}</td>"
            "</tr>"
        )
    if not item_rows:
        item_rows.append(empty_row(9, "暂无库资产文件"))

    imported_rows = []
    for asset in data.get("imported_assets", [])[:300]:
        if not isinstance(asset, dict):
            continue
        imported_rows.append(
            "<tr>"
            f"<td>{escape(str(asset.get('name') or asset.get('id') or '工程资产'))}<div class=\"id\">{escape(str(asset.get('id') or ''))}</div></td>"
            f"<td>{escape(str(asset.get('kind_label') or asset.get('type') or ''))}</td>"
            f"<td>{'可用' if asset.get('exists') else '文件缺失'}</td>"
            f"<td>{escape(str(asset.get('source_profile_name') or ''))}</td>"
            f"<td>{escape(str(asset.get('license_label') or ''))}</td>"
            f"<td>{escape(str(asset.get('library_relative_path') or asset.get('source_path') or ''))}</td>"
            f"<td>{int(asset.get('object_count') or 0)} / {int(asset.get('action_count') or 0)}</td>"
            f"<td>{'可控' if asset.get('controllable') else '—'}<div class=\"id\">{escape(str(asset.get('control_root') or ''))}</div></td>"
            "</tr>"
        )
    if not imported_rows:
        imported_rows.append(empty_row(8, "暂无已导入工程资产"))

    warning_text = "；".join(str(item or "") for item in data.get("health_warnings", []) if str(item or "").strip()) or "暂无关键风险"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 资产生态报告</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 22px 0 10px; font-size: 18px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 130px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    .warning {{ background: #2a1d16; border: 1px solid #6b3f25; color: #ffd2ad; padding: 10px 12px; border-radius: 8px; margin: 14px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; margin-bottom: 18px; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 24px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 资产生态报告</h1>
    <div class="meta">追踪开源生态来源、授权提示、库文件可用性、收藏标签、导入记录和动作资产准备度。</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('source_count') or 0)}</strong>资产源</div>
      <div class="stat"><strong>{int(data.get('library_count') or 0)}</strong>资产库</div>
      <div class="stat"><strong>{int(data.get('library_item_count') or 0)}</strong>库资产</div>
      <div class="stat"><strong>{int(data.get('available_item_count') or 0)}</strong>文件可用</div>
      <div class="stat"><strong>{int(data.get('missing_file_count') or 0)}</strong>缺文件</div>
      <div class="stat"><strong>{int(data.get('missing_license_count') or 0)}</strong>缺授权来源</div>
      <div class="stat"><strong>{int(data.get('favorite_count') or 0)}</strong>收藏</div>
      <div class="stat"><strong>{int(data.get('tagged_count') or 0)}</strong>已打标</div>
      <div class="stat"><strong>{int(data.get('imported_item_count') or 0)}</strong>已从库导入</div>
      <div class="stat"><strong>{int(data.get('controllable_asset_count') or 0)}</strong>可控工程资产</div>
      <div class="stat"><strong>{int(data.get('ready_action_count') or 0)}/{int(data.get('action_item_count') or 0)}</strong>动作准备</div>
    </div>
    <div class="warning">{escape(warning_text)}</div>
    <h2>资产源</h2>
    <table><thead><tr><th>来源</th><th>目录</th><th>授权提示</th><th>文件数</th><th>接入方式</th><th>路径</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table>
    <h2>库资产</h2>
    <table><thead><tr><th>资产</th><th>分类</th><th>格式</th><th>来源</th><th>Blender Catalog</th><th>授权</th><th>状态</th><th>收藏</th><th>标签/备注</th></tr></thead><tbody>{''.join(item_rows)}</tbody></table>
    <h2>已导入工程资产</h2>
    <table><thead><tr><th>资产</th><th>类型</th><th>文件</th><th>来源</th><th>授权</th><th>库路径</th><th>对象/动作</th><th>控制</th></tr></thead><tbody>{''.join(imported_rows)}</tbody></table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "asset_ecosystem.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _asset_preflight_issue(severity, code, title, suggestion):
    return {
        "severity": str(severity or "info"),
        "code": str(code or ""),
        "title": str(title or ""),
        "suggestion": str(suggestion or ""),
    }


def _asset_preflight_texture_roles(items):
    roles_by_dir = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        kind = str(item.get("kind") or item.get("kind_hint") or "").strip()
        if kind not in {"material", "texture"}:
            continue
        role = str(item.get("texture_role") or "").strip()
        if not role:
            lower = os.path.basename(path).lower()
            if "normal" in lower:
                role = "normal"
            elif "rough" in lower:
                role = "roughness"
            elif "metal" in lower:
                role = "metallic"
            elif "height" in lower or "disp" in lower:
                role = "height"
            else:
                role = "base_color"
        roles_by_dir.setdefault(os.path.dirname(path), set()).add(role)
    return roles_by_dir


def build_blender_director_asset_preflight(metadata):
    ecosystem = build_blender_director_asset_ecosystem(metadata)
    items = ecosystem.get("items") if isinstance(ecosystem.get("items"), list) else []
    imported_assets = ecosystem.get("imported_assets") if isinstance(ecosystem.get("imported_assets"), list) else []
    texture_roles = _asset_preflight_texture_roles(items)
    rows = []
    issue_rows = []
    error_count = 0
    warning_count = 0
    info_count = 0
    ready_count = 0
    review_count = 0
    blocked_count = 0
    supported_formats = {
        "blend", "glb", "gltf", "fbx", "obj", "bvh", "stl", "ply", "abc", "usd", "usdz",
        "png", "jpg", "jpeg", "tif", "tiff", "exr", "hdr",
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        issues = []
        kind = str(item.get("kind") or "").strip() or "model"
        file_format = str(item.get("format") or "").strip().lower()
        path = str(item.get("path") or "").strip()
        if not item.get("exists"):
            issues.append(_asset_preflight_issue("error", "missing_file", "库资产文件不存在", "重新扫描资产库，或把源文件恢复到原路径后再导入。"))
        if file_format and file_format not in supported_formats:
            issues.append(_asset_preflight_issue("error", "unsupported_format", "暂不支持该文件格式", "转换为 blend/glb/gltf/fbx/obj/bvh/stl/ply/abc/usd/usdz 或常见贴图/HDRI 格式。"))
        try:
            size = int(item.get("size") or 0)
        except Exception:
            size = 0
        if item.get("exists") and size <= 0:
            issues.append(_asset_preflight_issue("warning", "empty_file", "文件大小为 0", "确认文件是否下载完整，必要时重新下载。"))
        license_status = str(item.get("license_status") or "")
        if license_status == "missing":
            issues.append(_asset_preflight_issue("warning", "missing_license", "缺授权来源", "补充 license/usage_rights 字段，或在备注里写明下载页授权。"))
        elif license_status == "review":
            issues.append(_asset_preflight_issue("warning", "license_review", "授权需人工复核", "导入商用工程前核对原始下载页授权和署名要求。"))
        if kind == "model":
            issues.append(_asset_preflight_issue("info", "confirm_asset_kind", "资产分类需要确认", "导入前选择人物、道具或场景分类，方便进入对应集合和报告。"))
        if kind in {"character", "prop", "scene", "model"} and not str(item.get("preview_path") or item.get("thumbnail_path") or "").strip():
            issues.append(_asset_preflight_issue("info", "no_preview", "没有预览图", "可稍后生成缩略图或登记预览，方便导演台选资产。"))
        if kind == "action":
            if not item.get("imported") and int(item.get("usage_count") or 0) <= 0:
                issues.append(_asset_preflight_issue("warning", "action_not_prepared", "动作尚未导入/验证", "导入到目标骨骼或建立重定向档案后再用于分镜匹配。"))
            if file_format not in {"fbx", "bvh"}:
                issues.append(_asset_preflight_issue("warning", "action_format_review", "动作格式需确认", "优先使用 FBX/BVH 动作文件；其他格式请先在 Blender 内确认包含 Action。"))
        if kind in {"material", "texture"}:
            roles = texture_roles.get(os.path.dirname(path), set())
            if "base_color" in roles and not ({"normal", "roughness"} & roles):
                issues.append(_asset_preflight_issue("info", "incomplete_texture_set", "贴图组不完整", "如需 PBR 材质，补齐 normal/roughness/metallic 等贴图。"))
        if kind == "hdri" and file_format not in {"hdr", "exr"}:
            issues.append(_asset_preflight_issue("warning", "hdri_format_review", "HDRI 格式需确认", "建议使用 HDR/EXR 环境光贴图，避免普通图片误作 HDRI。"))
        severity_rank = {"error": 3, "warning": 2, "info": 1}
        max_severity = "ready"
        if issues:
            max_issue = max(issues, key=lambda issue: severity_rank.get(issue.get("severity"), 0))
            max_severity = str(max_issue.get("severity") or "info")
        if max_severity == "error":
            blocked_count += 1
        elif max_severity == "warning":
            review_count += 1
        else:
            ready_count += 1
        for issue in issues:
            severity = str(issue.get("severity") or "info")
            if severity == "error":
                error_count += 1
            elif severity == "warning":
                warning_count += 1
            else:
                info_count += 1
            issue_rows.append(
                {
                    "asset_id": str(item.get("id") or ""),
                    "asset_name": str(item.get("name") or ""),
                    "kind": kind,
                    "kind_label": str(item.get("kind_label") or _asset_ecosystem_kind_label(kind)),
                    "severity": severity,
                    "code": str(issue.get("code") or ""),
                    "title": str(issue.get("title") or ""),
                    "suggestion": str(issue.get("suggestion") or ""),
                    "path": path,
                }
            )
        rows.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or item.get("file_name") or "库资产"),
                "kind": kind,
                "kind_label": str(item.get("kind_label") or _asset_ecosystem_kind_label(kind)),
                "format": file_format,
                "source_profile_name": str(item.get("source_profile_name") or ""),
                "license_label": str(item.get("license_label") or ""),
                "path": path,
                "relative_path": str(item.get("relative_path") or ""),
                "imported": bool(item.get("imported")),
                "preflight_status": max_severity,
                "preflight_status_label": {
                    "error": "阻断",
                    "warning": "需复核",
                    "info": "可导入（有建议）",
                    "ready": "可导入",
                }.get(max_severity, max_severity),
                "issue_count": len(issues),
                "issues": issues,
            }
        )
    imported_issue_rows = []
    for asset in imported_assets:
        if not isinstance(asset, dict):
            continue
        if not asset.get("exists"):
            imported_issue_rows.append(
                {
                    "asset_id": str(asset.get("id") or ""),
                    "asset_name": str(asset.get("name") or ""),
                    "severity": "error",
                    "code": "imported_file_missing",
                    "title": "工程资产文件缺失",
                    "suggestion": "重新导入资产或恢复工程资产文件。",
                    "path": str(asset.get("path") or ""),
                }
            )
            error_count += 1
        if asset.get("source_path") and not asset.get("source_exists"):
            imported_issue_rows.append(
                {
                    "asset_id": str(asset.get("id") or ""),
                    "asset_name": str(asset.get("name") or ""),
                    "severity": "warning",
                    "code": "source_file_missing",
                    "title": "原始源文件缺失",
                    "suggestion": "如需重新导入或溯源，请恢复原始下载文件或更新来源路径。",
                    "path": str(asset.get("source_path") or ""),
                }
            )
            warning_count += 1
    issue_rows.extend(imported_issue_rows)
    return {
        "library_item_count": len(rows),
        "ready_count": ready_count,
        "review_count": review_count,
        "blocked_count": blocked_count,
        "issue_count": len(issue_rows),
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "imported_asset_issue_count": len(imported_issue_rows),
        "items": rows,
        "issues": issue_rows,
    }


def write_blender_director_asset_preflight_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "asset_preflight.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_blender_director_asset_preflight(metadata), f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_asset_preflight_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "asset_preflight.csv")
    data = build_blender_director_asset_preflight(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["资产ID", "资产名", "分类", "格式", "预检状态", "问题数", "问题级别", "问题", "修复建议", "路径"])
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            issues = item.get("issues") if isinstance(item.get("issues"), list) else []
            if not issues:
                writer.writerow([
                    item.get("id") or "",
                    item.get("name") or "",
                    item.get("kind_label") or "",
                    item.get("format") or "",
                    item.get("preflight_status_label") or "",
                    0,
                    "",
                    "",
                    "",
                    item.get("relative_path") or item.get("path") or "",
                ])
                continue
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                writer.writerow([
                    item.get("id") or "",
                    item.get("name") or "",
                    item.get("kind_label") or "",
                    item.get("format") or "",
                    item.get("preflight_status_label") or "",
                    item.get("issue_count") or 0,
                    issue.get("severity") or "",
                    issue.get("title") or "",
                    issue.get("suggestion") or "",
                    item.get("relative_path") or item.get("path") or "",
                ])
    return path


def write_blender_director_asset_preflight_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_asset_preflight(metadata)
    project_name = str((metadata or {}).get("project_name") or "Blender 导演台工程")
    item_rows = []
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        issues = item.get("issues") if isinstance(item.get("issues"), list) else []
        issue_text = "；".join(
            str(issue.get("title") or "")
            for issue in issues
            if isinstance(issue, dict) and str(issue.get("title") or "").strip()
        )
        suggestion_text = "；".join(
            str(issue.get("suggestion") or "")
            for issue in issues
            if isinstance(issue, dict) and str(issue.get("suggestion") or "").strip()
        )
        item_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('name') or item.get('id') or '库资产'))}<div class=\"id\">{escape(str(item.get('relative_path') or item.get('id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('kind_label') or ''))}</td>"
            f"<td>{escape(str(item.get('format') or '').upper())}</td>"
            f"<td>{escape(str(item.get('preflight_status_label') or ''))}</td>"
            f"<td>{escape(issue_text or '无阻断问题')}</td>"
            f"<td>{escape(suggestion_text or '可直接导入')}</td>"
            "</tr>"
        )
    if not item_rows:
        item_rows.append('<tr><td colspan="6" class="empty">暂无可预检的库资产</td></tr>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 资产导入预检</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 130px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 24px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 资产导入预检</h1>
    <div class="meta">导入前检查文件、授权、分类、动作准备度、预览和贴图组完整性，并给出修复建议。</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('library_item_count') or 0)}</strong>库资产</div>
      <div class="stat"><strong>{int(data.get('ready_count') or 0)}</strong>可导入</div>
      <div class="stat"><strong>{int(data.get('review_count') or 0)}</strong>需复核</div>
      <div class="stat"><strong>{int(data.get('blocked_count') or 0)}</strong>阻断</div>
      <div class="stat"><strong>{int(data.get('error_count') or 0)}</strong>错误</div>
      <div class="stat"><strong>{int(data.get('warning_count') or 0)}</strong>提醒</div>
      <div class="stat"><strong>{int(data.get('info_count') or 0)}</strong>建议</div>
    </div>
    <table>
      <thead><tr><th>资产</th><th>分类</th><th>格式</th><th>预检状态</th><th>问题</th><th>修复建议</th></tr></thead>
      <tbody>{''.join(item_rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "asset_preflight.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_retarget_summary(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    profiles = metadata.get("retarget_profiles") if isinstance(metadata.get("retarget_profiles"), list) else []
    applications = metadata.get("retarget_applications") if isinstance(metadata.get("retarget_applications"), list) else []
    action_clips = metadata.get("action_clips") if isinstance(metadata.get("action_clips"), list) else []
    retarget_clips = [
        clip
        for clip in action_clips
        if isinstance(clip, dict) and str(clip.get("generated_by") or "") == "retarget"
    ]
    profile_rows = []
    mapped_bones = 0
    unmapped_source = 0
    unmapped_target = 0
    max_rest_angle = 0.0
    mismatch_bones = 0
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        rest_pose = profile.get("rest_pose_alignment") if isinstance(profile.get("rest_pose_alignment"), dict) else {}
        root_motion = profile.get("root_motion") if isinstance(profile.get("root_motion"), dict) else {}
        try:
            mapped = int(profile.get("mapped_bone_count") or 0)
        except Exception:
            mapped = 0
        try:
            source_missing = int(profile.get("unmapped_source_count") or 0)
        except Exception:
            source_missing = 0
        try:
            target_missing = int(profile.get("unmapped_target_count") or 0)
        except Exception:
            target_missing = 0
        try:
            angle = float(rest_pose.get("max_angle_degrees") or 0.0)
        except Exception:
            angle = 0.0
        try:
            profile_mismatch = int(rest_pose.get("mismatch_bone_count") or 0)
        except Exception:
            profile_mismatch = 0
        mapped_bones += mapped
        unmapped_source += source_missing
        unmapped_target += target_missing
        max_rest_angle = max(max_rest_angle, angle)
        mismatch_bones += profile_mismatch
        profile_rows.append(
            {
                "id": str(profile.get("id") or ""),
                "name": str(profile.get("name") or profile.get("id") or ""),
                "source_armature": str(profile.get("source_armature") or ""),
                "target_armature": str(profile.get("target_armature") or ""),
                "mapped_bone_count": mapped,
                "unmapped_source_count": source_missing,
                "unmapped_target_count": target_missing,
                "rest_pose_enabled": bool(rest_pose.get("enabled", True)),
                "rest_pose_mismatch_bone_count": profile_mismatch,
                "rest_pose_max_angle_degrees": round(angle, 3),
                "root_motion_enabled": bool(root_motion.get("enabled", True)),
                "root_motion_scale": float(root_motion.get("effective_scale") or root_motion.get("automatic_scale") or 1.0),
                "saved_at": str(profile.get("saved_at") or ""),
            }
        )
    application_rows = []
    success_count = 0
    failure_count = 0
    copied_fcurves = 0
    skipped_fcurves = 0
    latest_at = ""
    matched_requirements = 0
    match_requirements = 0
    for record in applications:
        if not isinstance(record, dict):
            continue
        status = str(record.get("status") or "")
        if status == "applied":
            success_count += 1
        elif status == "failed":
            failure_count += 1
        try:
            copied = int(record.get("copied_fcurve_count") or 0)
        except Exception:
            copied = 0
        try:
            skipped = int(record.get("skipped_fcurve_count") or 0)
        except Exception:
            skipped = 0
        copied_fcurves += copied
        skipped_fcurves += skipped
        applied_at = str(record.get("applied_at") or "")
        if applied_at > latest_at:
            latest_at = applied_at
        match_data = record.get("action_matches") if isinstance(record.get("action_matches"), dict) else {}
        matched_requirements = max(matched_requirements, int(match_data.get("matched_count") or 0))
        match_requirements = max(match_requirements, int(match_data.get("requirement_count") or 0))
        action_clip = record.get("action_clip") if isinstance(record.get("action_clip"), dict) else {}
        application_rows.append(
            {
                "profile_name": str(record.get("profile_name") or ""),
                "source_action": str(record.get("source_action") or ""),
                "target_action": str(record.get("target_action") or ""),
                "target_armature": str(record.get("target_armature") or ""),
                "status": status,
                "message": str(record.get("message") or ""),
                "copied_fcurve_count": copied,
                "skipped_fcurve_count": skipped,
                "root_motion_scale": float(record.get("root_motion_scale") or 1.0),
                "action_clip_id": str(action_clip.get("id") or ""),
                "action_clip_name": str(action_clip.get("name") or ""),
                "applied_at": applied_at,
            }
        )
    clip_rows = []
    for clip in retarget_clips:
        quality = clip.get("retarget_quality") if isinstance(clip.get("retarget_quality"), dict) else {}
        clip_rows.append(
            {
                "id": str(clip.get("id") or ""),
                "name": str(clip.get("name") or ""),
                "action": str(clip.get("action") or ""),
                "target_armature": str(clip.get("target_armature") or ""),
                "source_action_clip_id": str(clip.get("source_action_clip_id") or ""),
                "retarget_profile_name": str(clip.get("retarget_profile_name") or ""),
                "copied_fcurve_count": int(quality.get("copied_fcurve_count") or 0),
                "skipped_fcurve_count": int(quality.get("skipped_fcurve_count") or 0),
                "mapped_bone_count": int(quality.get("mapped_bone_count") or 0),
                "unmapped_source_count": int(quality.get("unmapped_source_count") or 0),
                "unmapped_target_count": int(quality.get("unmapped_target_count") or 0),
                "rest_pose_mismatch_bone_count": int(quality.get("rest_pose_mismatch_bone_count") or 0),
                "rest_pose_max_angle_degrees": float(quality.get("rest_pose_max_angle_degrees") or 0.0),
                "root_motion_scale": float(quality.get("root_motion_scale") or 1.0),
                "status": str(clip.get("status") or ""),
            }
        )
    return {
        "profile_count": len(profile_rows),
        "application_count": len(application_rows),
        "success_count": success_count,
        "failure_count": failure_count,
        "ready_clip_count": len(clip_rows),
        "mapped_bone_count": mapped_bones,
        "unmapped_source_count": unmapped_source,
        "unmapped_target_count": unmapped_target,
        "rest_pose_mismatch_bone_count": mismatch_bones,
        "rest_pose_max_angle_degrees": round(max_rest_angle, 3),
        "copied_fcurve_count": copied_fcurves,
        "skipped_fcurve_count": skipped_fcurves,
        "matched_requirement_count": matched_requirements,
        "match_requirement_count": match_requirements,
        "latest_application_at": latest_at,
        "profiles": profile_rows,
        "applications": application_rows,
        "action_clips": clip_rows,
    }


def write_blender_director_retarget_summary_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "retarget_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_blender_director_retarget_summary(metadata), f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_retarget_summary_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "retarget_summary.csv")
    data = build_blender_director_retarget_summary(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["类型", "名称", "档案", "目标骨骼", "状态", "映射骨骼", "源未映射", "目标未映射", "Rest Pose差异骨骼", "最大轴向差", "根运动比例", "复制曲线", "跳过曲线", "时间"])
        for clip in data.get("action_clips", []):
            if not isinstance(clip, dict):
                continue
            writer.writerow(
                [
                    "动作片段",
                    clip.get("name") or clip.get("id") or "",
                    clip.get("retarget_profile_name") or "",
                    clip.get("target_armature") or "",
                    clip.get("status") or "",
                    clip.get("mapped_bone_count") or 0,
                    clip.get("unmapped_source_count") or 0,
                    clip.get("unmapped_target_count") or 0,
                    clip.get("rest_pose_mismatch_bone_count") or 0,
                    clip.get("rest_pose_max_angle_degrees") or 0,
                    clip.get("root_motion_scale") or 1.0,
                    clip.get("copied_fcurve_count") or 0,
                    clip.get("skipped_fcurve_count") or 0,
                    "",
                ]
            )
        for record in data.get("applications", []):
            if not isinstance(record, dict):
                continue
            writer.writerow(
                [
                    "应用记录",
                    record.get("target_action") or "",
                    record.get("profile_name") or "",
                    record.get("target_armature") or "",
                    record.get("status") or "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    record.get("root_motion_scale") or 1.0,
                    record.get("copied_fcurve_count") or 0,
                    record.get("skipped_fcurve_count") or 0,
                    record.get("applied_at") or "",
                ]
            )
    return path


def write_blender_director_retarget_summary_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_retarget_summary(metadata)
    project_name = str((metadata or {}).get("project_name") or "Blender 导演台工程")

    def empty_row(columns, text):
        return f'<tr><td colspan="{columns}" class="empty">{escape(text)}</td></tr>'

    profile_rows = []
    for profile in data.get("profiles", []):
        if not isinstance(profile, dict):
            continue
        profile_rows.append(
            "<tr>"
            f"<td>{escape(str(profile.get('name') or profile.get('id') or '重定向档案'))}<div class=\"id\">{escape(str(profile.get('id') or ''))}</div></td>"
            f"<td>{escape(str(profile.get('source_armature') or ''))} → {escape(str(profile.get('target_armature') or ''))}</td>"
            f"<td>{int(profile.get('mapped_bone_count') or 0)}</td>"
            f"<td>{int(profile.get('unmapped_source_count') or 0)} / {int(profile.get('unmapped_target_count') or 0)}</td>"
            f"<td>{int(profile.get('rest_pose_mismatch_bone_count') or 0)} 根 / {float(profile.get('rest_pose_max_angle_degrees') or 0):.1f}°</td>"
            f"<td>{float(profile.get('root_motion_scale') or 1.0):.3f}</td>"
            f"<td>{escape(str(profile.get('saved_at') or ''))}</td>"
            "</tr>"
        )
    if not profile_rows:
        profile_rows.append(empty_row(7, "暂无重定向档案"))

    clip_rows = []
    for clip in data.get("action_clips", []):
        if not isinstance(clip, dict):
            continue
        clip_rows.append(
            "<tr>"
            f"<td>{escape(str(clip.get('name') or clip.get('id') or '重定向动作片段'))}<div class=\"id\">{escape(str(clip.get('id') or ''))}</div></td>"
            f"<td>{escape(str(clip.get('retarget_profile_name') or ''))}</td>"
            f"<td>{escape(str(clip.get('target_armature') or ''))}</td>"
            f"<td>{int(clip.get('mapped_bone_count') or 0)}</td>"
            f"<td>{int(clip.get('unmapped_source_count') or 0)} / {int(clip.get('unmapped_target_count') or 0)}</td>"
            f"<td>{float(clip.get('rest_pose_max_angle_degrees') or 0):.1f}° / {int(clip.get('rest_pose_mismatch_bone_count') or 0)} 根</td>"
            f"<td>{float(clip.get('root_motion_scale') or 1.0):.3f}</td>"
            f"<td>{int(clip.get('copied_fcurve_count') or 0)} / {int(clip.get('skipped_fcurve_count') or 0)}</td>"
            "</tr>"
        )
    if not clip_rows:
        clip_rows.append(empty_row(8, "暂无已生成的重定向动作片段"))

    application_rows = []
    for record in data.get("applications", []):
        if not isinstance(record, dict):
            continue
        application_rows.append(
            "<tr>"
            f"<td>{escape(str(record.get('profile_name') or ''))}</td>"
            f"<td>{escape(str(record.get('source_action') or ''))} → {escape(str(record.get('target_action') or ''))}</td>"
            f"<td>{escape(str(record.get('target_armature') or ''))}</td>"
            f"<td>{escape(str(record.get('status') or ''))}</td>"
            f"<td>{int(record.get('copied_fcurve_count') or 0)} / {int(record.get('skipped_fcurve_count') or 0)}</td>"
            f"<td>{float(record.get('root_motion_scale') or 1.0):.3f}</td>"
            f"<td>{escape(str(record.get('action_clip_name') or record.get('action_clip_id') or ''))}</td>"
            f"<td>{escape(str(record.get('applied_at') or ''))}</td>"
            "</tr>"
        )
    if not application_rows:
        application_rows.append(empty_row(8, "暂无重定向应用记录"))

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 重定向质量报告</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 22px 0 10px; font-size: 18px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 130px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; margin-bottom: 18px; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 24px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 重定向质量报告</h1>
    <div class="meta">用于复核跨骨骼动作适配、Rest Pose 校正、根运动比例和分镜动作片段可用性。</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('profile_count') or 0)}</strong>重定向档案</div>
      <div class="stat"><strong>{int(data.get('success_count') or 0)}</strong>成功应用</div>
      <div class="stat"><strong>{int(data.get('failure_count') or 0)}</strong>失败记录</div>
      <div class="stat"><strong>{int(data.get('ready_clip_count') or 0)}</strong>可用动作片段</div>
      <div class="stat"><strong>{int(data.get('mapped_bone_count') or 0)}</strong>映射骨骼</div>
      <div class="stat"><strong>{int(data.get('unmapped_source_count') or 0)}</strong>源未映射</div>
      <div class="stat"><strong>{int(data.get('unmapped_target_count') or 0)}</strong>目标未映射</div>
      <div class="stat"><strong>{float(data.get('rest_pose_max_angle_degrees') or 0):.1f}°</strong>最大轴向差</div>
      <div class="stat"><strong>{int(data.get('copied_fcurve_count') or 0)}</strong>复制曲线</div>
      <div class="stat"><strong>{int(data.get('matched_requirement_count') or 0)}/{int(data.get('match_requirement_count') or 0)}</strong>动作匹配</div>
    </div>
    <h2>重定向档案</h2>
    <table><thead><tr><th>档案</th><th>骨骼</th><th>映射</th><th>未映射</th><th>Rest Pose</th><th>根运动</th><th>保存时间</th></tr></thead><tbody>{''.join(profile_rows)}</tbody></table>
    <h2>可用动作片段</h2>
    <table><thead><tr><th>片段</th><th>档案</th><th>目标骨骼</th><th>映射</th><th>未映射</th><th>Rest Pose</th><th>根运动</th><th>曲线</th></tr></thead><tbody>{''.join(clip_rows)}</tbody></table>
    <h2>应用记录</h2>
    <table><thead><tr><th>档案</th><th>动作</th><th>目标骨骼</th><th>状态</th><th>曲线</th><th>根运动</th><th>动作片段</th><th>时间</th></tr></thead><tbody>{''.join(application_rows)}</tbody></table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "retarget_summary.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _requirement_key(kind, item):
    if not isinstance(item, dict):
        return ""
    item_id = str(item.get("id") or "").strip()
    item_name = str(item.get("name") or item.get("role") or "").strip()
    if item_id:
        return f"{kind}:id:{item_id}"
    if item_name:
        return f"{kind}:name:{item_name}"
    return ""


def _asset_requirement_normalized_text(value):
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item or "") for item in value)
    elif isinstance(value, dict):
        value = " ".join(str(item or "") for item in value.values())
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _asset_requirement_tokens(value):
    text = _asset_requirement_normalized_text(value)
    parts = re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", text)
    return [part for part in parts if len(part) >= 2]


def _asset_requirement_target_type(requirement):
    if not isinstance(requirement, dict):
        return ""
    if requirement.get("kind") == "actor":
        return "character"
    kind = str(requirement.get("type") or "").strip().lower()
    aliases = {
        "actor": "character",
        "person": "character",
        "human": "character",
        "role": "character",
        "object": "prop",
        "set": "scene",
        "environment": "scene",
    }
    return aliases.get(kind, kind)


def _asset_library_candidate_text(item):
    if not isinstance(item, dict):
        return ""
    return _asset_requirement_normalized_text(
        [
            item.get("id"),
            item.get("name"),
            item.get("file_name"),
            item.get("relative_path"),
            item.get("path"),
            item.get("kind_hint"),
            item.get("tags"),
            item.get("usage_note"),
            item.get("source_profile_name"),
        ]
    )


def _asset_library_candidate_supported(path):
    supported = (
        ".blend",
        ".glb",
        ".gltf",
        ".fbx",
        ".obj",
        ".bvh",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".exr",
        ".hdr",
    )
    return str(path or "").lower().endswith(supported)


def _score_asset_library_candidate(requirement, item):
    if not isinstance(requirement, dict) or not isinstance(item, dict):
        return None
    path = str(item.get("path") or "").strip()
    if not path or not os.path.exists(path) or not _asset_library_candidate_supported(path):
        return None
    target_type = _asset_requirement_target_type(requirement)
    item_kind = str(item.get("kind_hint") or item.get("type") or "model").strip().lower()
    req_name = str(requirement.get("name") or requirement.get("id") or "").strip()
    req_text = _asset_requirement_normalized_text(
        [requirement.get("id"), requirement.get("name"), requirement.get("type"), requirement.get("kind_label")]
    )
    candidate_text = _asset_library_candidate_text(item)
    score = 0.0
    reasons = []
    if target_type and item_kind == target_type:
        score += 0.36
        reasons.append("类型匹配：" + _asset_ecosystem_kind_label(target_type))
    elif target_type == "character" and item_kind == "model":
        score += 0.18
        reasons.append("通用模型可作为人物候选")
    elif target_type in ("prop", "scene") and item_kind == "model":
        score += 0.16
        reasons.append("通用模型可作为" + _asset_ecosystem_kind_label(target_type) + "候选")
    elif not target_type and item_kind in {"character", "prop", "scene", "model"}:
        score += 0.12
        reasons.append("可作为镜头资产候选")
    normalized_name = _asset_requirement_normalized_text(req_name)
    if normalized_name and (normalized_name in candidate_text or candidate_text in normalized_name):
        score += 0.42
        reasons.append("名称匹配")
    shared_tokens = []
    for token in _asset_requirement_tokens(req_text):
        if token in candidate_text and token not in shared_tokens:
            shared_tokens.append(token)
    if shared_tokens:
        score += min(0.24, 0.08 * len(shared_tokens))
        reasons.append("关键词：" + "、".join(shared_tokens[:4]))
    if bool(item.get("favorite")):
        score += 0.04
        reasons.append("已收藏")
    try:
        usage_count = int(item.get("usage_count") or 0)
    except Exception:
        usage_count = 0
    if usage_count > 0:
        score += min(0.05, usage_count * 0.01)
        reasons.append("历史使用 " + str(usage_count) + " 次")
    if score <= 0:
        return None
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("file_name") or item.get("id") or "库资产"),
        "kind": item_kind,
        "kind_label": _asset_ecosystem_kind_label(item_kind),
        "format": str(item.get("format") or os.path.splitext(path)[1].lstrip(".").lower()),
        "path": path,
        "relative_path": str(item.get("relative_path") or ""),
        "library_id": str(item.get("library_id") or ""),
        "library_path": str(item.get("library_path") or ""),
        "source_profile_id": str(item.get("source_profile_id") or ""),
        "source_profile_name": str(item.get("source_profile_name") or ""),
        "favorite": bool(item.get("favorite")),
        "usage_count": usage_count,
        "score": round(min(score, 1.0), 4),
        "reasons": reasons,
    }


def _asset_requirement_library_candidates(metadata, requirement, limit=5):
    if not isinstance(metadata, dict) or not isinstance(requirement, dict):
        return []
    rows = []
    items = metadata.get("asset_library_items") if isinstance(metadata.get("asset_library_items"), list) else []
    for item in items:
        candidate = _score_asset_library_candidate(requirement, item)
        if candidate:
            rows.append(candidate)
    rows.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("name") or ""), str(item.get("id") or "")))
    return rows[: max(1, int(limit or 1))]


def build_blender_director_asset_requirements(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    assets = metadata.get("assets") if isinstance(metadata.get("assets"), list) else []
    actors = metadata.get("actors") if isinstance(metadata.get("actors"), list) else []
    asset_keys = set()
    character_asset_keys = set()
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("id") or "").strip()
        asset_name = str(asset.get("name") or asset.get("file_name") or "").strip()
        for key in (asset_id, asset_name):
            if key:
                asset_keys.add(key)
                if str(asset.get("type") or "").lower() in {"character", "actor", "person", "human"}:
                    character_asset_keys.add(key)
    actor_keys_with_objects = set()
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        has_objects = bool(actor.get("objects") if isinstance(actor.get("objects"), list) else [])
        if not has_objects:
            continue
        actor_id = str(actor.get("id") or "").strip()
        actor_name = str(actor.get("name") or "").strip()
        for key in (actor_id, actor_name):
            if key:
                actor_keys_with_objects.add(key)

    requirements = {}

    def add_requirement(kind, item, shot, available, status_note, asset_type=""):
        key = _requirement_key(kind, item)
        if not key:
            return
        row = requirements.setdefault(
            key,
            {
                "kind": kind,
                "kind_label": "演员模型" if kind == "actor" else "镜头资产",
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or item.get("role") or item.get("id") or "").strip(),
                "type": str(asset_type or item.get("type") or "").strip(),
                "available": bool(available),
                "status_label": "已具备" if available else "缺素材",
                "status_note": str(status_note or ""),
                "shot_count": 0,
                "shots": [],
            },
        )
        if available and not row.get("available"):
            row["available"] = True
            row["status_label"] = "已具备"
            row["status_note"] = str(status_note or "")
        shot_id = str((shot or {}).get("shot_id") or "").strip()
        shot_name = str((shot or {}).get("shot_name") or shot_id).strip()
        seen = {str(existing.get("shot_id") or existing.get("shot_name") or "") for existing in row.get("shots", []) if isinstance(existing, dict)}
        shot_key = shot_id or shot_name
        if shot_key and shot_key not in seen:
            row["shots"].append({"shot_id": shot_id, "shot_name": shot_name})
            row["shot_count"] += 1

    for shot in build_blender_director_storyboard(metadata):
        if not isinstance(shot, dict):
            continue
        for actor in shot.get("actors") if isinstance(shot.get("actors"), list) else []:
            if not isinstance(actor, dict):
                continue
            actor_id = str(actor.get("id") or "").strip()
            actor_name = str(actor.get("name") or "").strip()
            available = bool(
                (actor_id and actor_id in actor_keys_with_objects)
                or (actor_name and actor_name in actor_keys_with_objects)
                or (actor_id and actor_id in character_asset_keys)
                or (actor_name and actor_name in character_asset_keys)
            )
            add_requirement(
                "actor",
                actor,
                shot,
                available,
                "已有演员槽位/人物资产" if available else "镜头需要该演员，但工程里还没有可复用的人物模型记录",
                "character",
            )
        for asset in shot.get("assets") if isinstance(shot.get("assets"), list) else []:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get("id") or "").strip()
            asset_name = str(asset.get("name") or "").strip()
            available = bool((asset_id and asset_id in asset_keys) or (asset_name and asset_name in asset_keys))
            add_requirement(
                "asset",
                asset,
                shot,
                available,
                "已在工程资产中" if available else "镜头引用了该资产，但工程资产列表里没有匹配记录",
                str(asset.get("type") or ""),
            )
    rows = sorted(
        requirements.values(),
        key=lambda item: (0 if not item.get("available") else 1, str(item.get("kind_label") or ""), str(item.get("name") or item.get("id") or "")),
    )
    missing_with_candidate_count = 0
    candidate_total = 0
    for row in rows:
        candidates = _asset_requirement_library_candidates(metadata, row, limit=5)
        row["library_candidates"] = candidates
        row["library_candidate_count"] = len(candidates)
        row["best_library_candidate"] = candidates[0] if candidates else {}
        candidate_total += len(candidates)
        if not row.get("available") and candidates:
            missing_with_candidate_count += 1
    missing_count = sum(1 for item in rows if not item.get("available"))
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "requirement_count": len(rows),
        "available_count": len(rows) - missing_count,
        "missing_count": missing_count,
        "missing_with_candidate_count": missing_with_candidate_count,
        "library_candidate_count": candidate_total,
        "requirements": rows,
    }


def write_blender_director_asset_requirements_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "asset_requirements.json")
    data = build_blender_director_asset_requirements(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_asset_requirements_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "asset_requirements.csv")
    data = build_blender_director_asset_requirements(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["类型", "名称", "ID", "资产类型", "状态", "引用镜头数", "引用镜头", "本地库候选", "最佳候选", "匹配分", "说明"])
        for item in data.get("requirements", []):
            if not isinstance(item, dict):
                continue
            shots = item.get("shots") if isinstance(item.get("shots"), list) else []
            shot_text = "、".join(
                str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
                for shot in shots
                if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            )
            best_candidate = item.get("best_library_candidate") if isinstance(item.get("best_library_candidate"), dict) else {}
            writer.writerow(
                [
                    item.get("kind_label") or "",
                    item.get("name") or "",
                    item.get("id") or "",
                    item.get("type") or "",
                    item.get("status_label") or "",
                    item.get("shot_count") or 0,
                    shot_text,
                    item.get("library_candidate_count") or 0,
                    best_candidate.get("name") or "",
                    best_candidate.get("score") or "",
                    item.get("status_note") or "",
                ]
            )
    return path


def write_blender_director_asset_requirements_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_asset_requirements(metadata)
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    rows = []
    for item in data.get("requirements", []):
        if not isinstance(item, dict):
            continue
        shots = item.get("shots") if isinstance(item.get("shots"), list) else []
        shot_text = "、".join(
            str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
            for shot in shots
            if isinstance(shot, dict) and str(shot.get("shot_name") or shot.get("shot_id") or "").strip()
        )
        status_class = "ok" if item.get("available") else "bad"
        best_candidate = item.get("best_library_candidate") if isinstance(item.get("best_library_candidate"), dict) else {}
        candidate_text = ""
        if best_candidate:
            reasons = best_candidate.get("reasons") if isinstance(best_candidate.get("reasons"), list) else []
            candidate_text = (
                str(best_candidate.get("name") or "")
                + " · "
                + str(best_candidate.get("kind_label") or best_candidate.get("kind") or "")
                + " · "
                + str(best_candidate.get("score") or "")
            )
            if reasons:
                candidate_text += "｜" + "；".join(str(reason or "") for reason in reasons[:3])
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('kind_label') or ''))}</td>"
            f"<td><strong>{escape(str(item.get('name') or item.get('id') or '未命名需求'))}</strong><div class=\"id\">{escape(str(item.get('id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('type') or ''))}</td>"
            f"<td class=\"{status_class}\">{escape(str(item.get('status_label') or ''))}</td>"
            f"<td>{int(item.get('shot_count') or 0)}</td>"
            f"<td>{escape(shot_text)}</td>"
            f"<td>{escape(candidate_text or '—')}</td>"
            f"<td>{escape(str(item.get('status_note') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="8" class="empty">暂无资产需求，请先在 Blender 导演台保存带演员或资产的镜头。</td></tr>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 资产需求清单</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .ok {{ color: #86efac; }}
    .bad {{ color: #ff9f9f; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 资产需求清单</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('requirement_count') or 0)}</strong>需求</div>
      <div class="stat"><strong>{int(data.get('available_count') or 0)}</strong>已具备</div>
      <div class="stat"><strong>{int(data.get('missing_count') or 0)}</strong>缺素材</div>
      <div class="stat"><strong>{int(data.get('missing_with_candidate_count') or 0)}</strong>缺项有本地候选</div>
    </div>
    <table>
      <thead><tr><th>类型</th><th>名称</th><th>资产类型</th><th>状态</th><th>镜头数</th><th>引用镜头</th><th>本地库最佳候选</th><th>说明</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "asset_requirements.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


_ACTION_MATCH_GROUPS = (
    ("走路", ("走路", "行走", "走入", "走进", "进入", "进门", "走到", "步行", "walk", "walking")),
    ("跑步", ("跑步", "奔跑", "冲向", "跑向", "逃跑", "run", "running", "sprint")),
    ("坐下", ("坐下", "落座", "入座", "坐到", "sit", "sitting")),
    ("站起", ("站起", "起身", "站起来", "stand up", "standing up")),
    ("转身", ("转身", "回头", "转向", "扭头", "turn", "turning")),
    ("挥手", ("挥手", "招手", "挥别", "告别", "wave", "waving")),
    ("打斗", ("打斗", "搏斗", "攻击", "出拳", "拳击", "踢打", "fight", "punch", "attack", "kick")),
    ("跌倒", ("跌倒", "摔倒", "倒地", "倒下", "fall", "falling")),
    ("说话", ("说话", "对话", "交谈", "争吵", "演讲", "talk", "talking", "speak", "dialogue")),
    ("停顿", ("停顿", "停下", "站定", "待机", "静止", "idle", "pause", "stop")),
    ("开门", ("开门", "推门", "拉门", "open door", "door open")),
    ("关门", ("关门", "合门", "close door", "door close")),
    ("拿取", ("拿起", "拿着", "拾取", "抓住", "取出", "pick up", "grab", "hold")),
    ("放下", ("放下", "放回", "搁下", "put down", "drop")),
    ("鞠躬", ("鞠躬", "弯腰致意", "bow", "bowing")),
    ("跳跃", ("跳跃", "跳起", "跃起", "jump", "jumping")),
    ("拥抱", ("拥抱", "抱住", "相拥", "hug", "hugging")),
)


def _action_match_text(value):
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item or "") for item in value)
    elif isinstance(value, dict):
        value = " ".join(str(item or "") for item in value.values())
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _action_match_keywords(text):
    normalized = _action_match_text(text)
    keywords = []
    matched_terms = {}
    for label, terms in _ACTION_MATCH_GROUPS:
        hits = [term for term in terms if term.lower() in normalized]
        if hits:
            keywords.append(label)
            matched_terms[label] = hits
    return keywords, matched_terms


def _action_match_actor_ref(actor):
    if not isinstance(actor, dict):
        return {}
    return {
        "id": str(actor.get("id") or "").strip(),
        "name": str(actor.get("name") or "").strip(),
        "role": str(actor.get("role") or "").strip(),
    }


def _action_match_candidate(item, origin, index):
    if not isinstance(item, dict):
        return {}
    candidate_id = str(item.get("id") or item.get("asset_id") or item.get("library_item_id") or "").strip()
    name = str(item.get("name") or item.get("file_name") or item.get("action") or candidate_id or f"动作{index:03d}").strip()
    action = str(item.get("action") or name).strip()
    actor = _action_match_actor_ref(item.get("actor"))
    tags = item.get("tags") if isinstance(item.get("tags"), (list, tuple, set, str)) else ""
    text_parts = [
        name,
        action,
        item.get("note"),
        tags,
        item.get("usage_note"),
        item.get("relative_path"),
        item.get("library_relative_path"),
        item.get("path"),
        item.get("source_profile_name"),
        item.get("retarget_profile_name"),
        item.get("retarget_source_action"),
        item.get("retarget_source_clip_name"),
    ]
    search_text = _action_match_text(text_parts)
    keywords, matched_terms = _action_match_keywords(search_text)
    usage_count = item.get("usage_count")
    try:
        usage_count = max(0, int(usage_count or 0))
    except Exception:
        usage_count = 0
    return {
        "id": candidate_id or f"{origin}_{index:03d}",
        "name": name,
        "action": action,
        "origin": origin,
        "origin_label": {
            "action_clip": "工程动作片段",
            "asset_library": "动作库资产",
            "asset": "工程动作资产",
        }.get(origin, origin),
        "actor": actor,
        "target_armature": str(item.get("target_armature") or "").strip(),
        "frame_start": item.get("frame_start"),
        "frame_end": item.get("frame_end"),
        "frame_count": item.get("frame_count"),
        "source_profile_id": str(item.get("source_profile_id") or "").strip(),
        "source_profile_name": str(item.get("source_profile_name") or "").strip(),
        "library_item_id": str(item.get("library_item_id") or "").strip(),
        "library_path": str(item.get("library_path") or "").strip(),
        "library_relative_path": str(item.get("library_relative_path") or item.get("relative_path") or "").strip(),
        "path": str(item.get("path") or item.get("source_path") or "").strip(),
        "format": str(item.get("format") or "").strip(),
        "favorite": bool(item.get("favorite")),
        "usage_count": usage_count,
        "generated_by": str(item.get("generated_by") or "").strip(),
        "retarget_profile_id": str(item.get("retarget_profile_id") or "").strip(),
        "retarget_profile_name": str(item.get("retarget_profile_name") or "").strip(),
        "retarget_source_action": str(item.get("retarget_source_action") or "").strip(),
        "retarget_source_clip_name": str(item.get("retarget_source_clip_name") or "").strip(),
        "retarget_quality": item.get("retarget_quality") if isinstance(item.get("retarget_quality"), dict) else {},
        "keywords": keywords,
        "matched_terms": matched_terms,
        "_search_text": search_text,
    }


def _build_action_match_candidates(metadata):
    candidates = []
    collections = (
        ("action_clip", metadata.get("action_clips") if isinstance(metadata.get("action_clips"), list) else []),
        (
            "asset_library",
            [
                item
                for item in (metadata.get("asset_library_items") if isinstance(metadata.get("asset_library_items"), list) else [])
                if isinstance(item, dict) and str(item.get("kind_hint") or "").strip().lower() == "action"
            ],
        ),
        (
            "asset",
            [
                item
                for item in (metadata.get("assets") if isinstance(metadata.get("assets"), list) else [])
                if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "action"
            ],
        ),
    )
    seen = set()
    index = 0
    for origin, items in collections:
        for item in items:
            index += 1
            candidate = _action_match_candidate(item, origin, index)
            if not candidate:
                continue
            key = (origin, str(candidate.get("id") or ""), str(candidate.get("path") or ""), str(candidate.get("action") or ""))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def _score_action_match(requirement, candidate):
    requirement_keywords = set(requirement.get("keywords") if isinstance(requirement.get("keywords"), list) else [])
    candidate_keywords = set(candidate.get("keywords") if isinstance(candidate.get("keywords"), list) else [])
    shared_keywords = sorted(requirement_keywords & candidate_keywords)
    score = min(0.64, 0.32 * len(shared_keywords))
    reasons = []
    if shared_keywords:
        reasons.append("动作词：" + "、".join(shared_keywords))

    query_text = _action_match_text(requirement.get("query"))
    candidate_name = _action_match_text(candidate.get("name"))
    candidate_action = _action_match_text(candidate.get("action"))
    candidate_source_clip_name = _action_match_text(candidate.get("retarget_source_clip_name"))
    phrase_hit = False
    for phrase in (candidate_name, candidate_action, candidate_source_clip_name):
        if len(phrase) >= 2 and (phrase in query_text or query_text in phrase):
            phrase_hit = True
            break
    if phrase_hit:
        score += 0.2
        reasons.append("镜头描述与动作名称直接对应")

    requirement_actor = requirement.get("actor") if isinstance(requirement.get("actor"), dict) else {}
    candidate_actor = candidate.get("actor") if isinstance(candidate.get("actor"), dict) else {}
    requirement_actor_keys = {
        str(requirement_actor.get("id") or "").strip(),
        str(requirement_actor.get("name") or "").strip(),
        str(requirement_actor.get("role") or "").strip(),
    } - {""}
    candidate_actor_keys = {
        str(candidate_actor.get("id") or "").strip(),
        str(candidate_actor.get("name") or "").strip(),
        str(candidate_actor.get("role") or "").strip(),
    } - {""}
    if requirement_actor_keys and candidate_actor_keys and requirement_actor_keys & candidate_actor_keys:
        score += 0.18
        reasons.append("演员绑定：" + str(requirement_actor.get("name") or requirement_actor.get("role") or requirement_actor.get("id") or "已匹配"))

    origin = str(candidate.get("origin") or "")
    if origin == "action_clip":
        score += 0.08
        reasons.append("优先复用工程动作片段")
    elif origin == "asset_library":
        score += 0.04
        reasons.append("来自动作资产库")

    source_name = str(candidate.get("source_profile_name") or "")
    if "mixamo" in source_name.lower():
        score += 0.03
        reasons.append("来源：Mixamo 动作生态")
    if str(candidate.get("generated_by") or "") == "retarget":
        score += 0.05
        reasons.append("已完成目标骨骼重定向")
    if candidate.get("favorite"):
        score += 0.03
        reasons.append("已收藏")
    usage_count = int(candidate.get("usage_count") or 0)
    if usage_count > 0:
        score += min(0.05, usage_count * 0.01)
        reasons.append(f"已有 {usage_count} 次使用记录")

    if not shared_keywords and not phrase_hit:
        return 0.0, [], []
    score = round(min(1.0, max(0.0, score)), 3)
    return score, reasons, shared_keywords


def _public_action_match_candidate(candidate, score=0.0, reasons=None, shared_keywords=None):
    return {
        key: value
        for key, value in {
            "id": candidate.get("id") or "",
            "name": candidate.get("name") or "",
            "action": candidate.get("action") or "",
            "origin": candidate.get("origin") or "",
            "origin_label": candidate.get("origin_label") or "",
            "actor": candidate.get("actor") if isinstance(candidate.get("actor"), dict) else {},
            "target_armature": candidate.get("target_armature") or "",
            "frame_start": candidate.get("frame_start"),
            "frame_end": candidate.get("frame_end"),
            "frame_count": candidate.get("frame_count"),
            "source_profile_id": candidate.get("source_profile_id") or "",
            "source_profile_name": candidate.get("source_profile_name") or "",
            "library_item_id": candidate.get("library_item_id") or "",
            "library_path": candidate.get("library_path") or "",
            "library_relative_path": candidate.get("library_relative_path") or "",
            "path": candidate.get("path") or "",
            "format": candidate.get("format") or "",
            "favorite": bool(candidate.get("favorite")),
            "usage_count": int(candidate.get("usage_count") or 0),
            "generated_by": candidate.get("generated_by") or "",
            "retarget_profile_id": candidate.get("retarget_profile_id") or "",
            "retarget_profile_name": candidate.get("retarget_profile_name") or "",
            "retarget_source_action": candidate.get("retarget_source_action") or "",
            "retarget_source_clip_name": candidate.get("retarget_source_clip_name") or "",
            "retarget_quality": candidate.get("retarget_quality") if isinstance(candidate.get("retarget_quality"), dict) else {},
            "keywords": candidate.get("keywords") if isinstance(candidate.get("keywords"), list) else [],
            "score": score,
            "reasons": reasons or [],
            "shared_keywords": shared_keywords or [],
        }.items()
    }


def build_blender_director_action_matches(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    candidates = _build_action_match_candidates(metadata)
    requirements = []
    for shot_index, shot in enumerate(build_blender_director_storyboard(metadata), 1):
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("shot_id") or f"shot_{shot_index:03d}").strip()
        shot_name = str(shot.get("shot_name") or shot_id or f"镜头{shot_index:02d}").strip()
        note = str(shot.get("note") or "").strip()
        query_parts = [
            shot_name,
            note,
            str(shot.get("scene_location") or "").strip(),
            str(shot.get("scene_environment_label") or shot.get("scene_environment") or "").strip(),
        ]
        query = "；".join(part for part in query_parts if part)
        keywords, matched_terms = _action_match_keywords(query)
        actors = [item for item in (shot.get("actors") if isinstance(shot.get("actors"), list) else []) if isinstance(item, dict)]
        actor_rows = actors or [{}]
        for actor_index, actor in enumerate(actor_rows, 1):
            actor_ref = _action_match_actor_ref(actor)
            requirement_id = "_".join(
                part
                for part in (
                    "action_requirement",
                    re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", shot_id),
                    re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(actor_ref.get("id") or actor_ref.get("name") or actor_index)),
                )
                if part
            )
            requirement = {
                "id": requirement_id,
                "shot_id": shot_id,
                "shot_name": shot_name,
                "shot_index": shot_index,
                "note": note,
                "scene_location": str(shot.get("scene_location") or ""),
                "actor": actor_ref,
                "query": query,
                "keywords": keywords,
                "matched_terms": matched_terms,
            }
            scored = []
            for candidate in candidates:
                score, reasons, shared_keywords = _score_action_match(requirement, candidate)
                scored.append((score, candidate, reasons, shared_keywords))
            scored.sort(
                key=lambda row: (
                    -row[0],
                    0 if str(row[1].get("origin") or "") == "action_clip" else 1,
                    str(row[1].get("name") or ""),
                )
            )
            best = scored[0] if scored and scored[0][0] >= 0.28 else None
            alternatives = [
                _public_action_match_candidate(candidate, score, reasons, shared)
                for score, candidate, reasons, shared in scored
                if score >= 0.18 and (best is None or candidate is not best[1])
            ][:3]
            if best is not None:
                best_match = _public_action_match_candidate(best[1], best[0], best[2], best[3])
                status = "matched"
                status_label = "已匹配"
            else:
                best_match = {}
                status = "unmatched"
                status_label = "待补动作"
            requirement.update(
                {
                    "status": status,
                    "status_label": status_label,
                    "best_match": best_match,
                    "alternatives": alternatives,
                    "candidate_count": len(candidates),
                    "match_note": (
                        "动作片段已完成目标骨骼重定向，可直接进入镜头验证。"
                        if best_match and str(best_match.get("generated_by") or "") == "retarget"
                        else "动作片段可直接复用；跨骨架资产仍需后续人工确认或骨骼重定向。"
                    )
                    if best_match
                    else "现有动作片段和动作资产库没有达到匹配阈值，请补充动作或人工指定。",
                }
            )
            requirements.append(requirement)

    matched_count = sum(1 for item in requirements if item.get("status") == "matched")
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shot_count": len({str(item.get("shot_id") or "") for item in requirements}),
        "candidate_count": len(candidates),
        "requirement_count": len(requirements),
        "matched_count": matched_count,
        "unmatched_count": len(requirements) - matched_count,
        "requirements": requirements,
    }


def write_blender_director_action_matches_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "action_matches.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_blender_director_action_matches(metadata), f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_action_matches_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "action_matches.csv")
    data = build_blender_director_action_matches(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["镜头", "镜头ID", "演员", "角色", "动作需求", "动作关键词", "状态", "最佳动作", "Blender Action", "分数", "来源", "帧段", "匹配依据", "备选动作", "说明"])
        for item in data.get("requirements", []):
            if not isinstance(item, dict):
                continue
            actor = item.get("actor") if isinstance(item.get("actor"), dict) else {}
            best = item.get("best_match") if isinstance(item.get("best_match"), dict) else {}
            alternatives = item.get("alternatives") if isinstance(item.get("alternatives"), list) else []
            frame_text = ""
            if best.get("frame_start") is not None and best.get("frame_end") is not None:
                frame_text = f"{best.get('frame_start')}-{best.get('frame_end')}"
            writer.writerow(
                [
                    item.get("shot_name") or "",
                    item.get("shot_id") or "",
                    actor.get("name") or actor.get("id") or "",
                    actor.get("role") or "",
                    item.get("query") or "",
                    "、".join(str(keyword) for keyword in item.get("keywords", []) if str(keyword).strip()),
                    item.get("status_label") or "",
                    best.get("name") or "",
                    best.get("action") or "",
                    best.get("score") if best else "",
                    best.get("source_profile_name") or best.get("origin_label") or "",
                    frame_text,
                    "；".join(str(reason) for reason in best.get("reasons", []) if str(reason).strip()),
                    "、".join(str(alt.get("name") or "") for alt in alternatives if isinstance(alt, dict) and str(alt.get("name") or "").strip()),
                    item.get("match_note") or "",
                ]
            )
    return path


def write_blender_director_action_matches_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_action_matches(metadata)
    rows = []
    for item in data.get("requirements", []):
        if not isinstance(item, dict):
            continue
        actor = item.get("actor") if isinstance(item.get("actor"), dict) else {}
        best = item.get("best_match") if isinstance(item.get("best_match"), dict) else {}
        alternatives = item.get("alternatives") if isinstance(item.get("alternatives"), list) else []
        actor_label = str(actor.get("name") or actor.get("role") or actor.get("id") or "未指定演员")
        keyword_text = "、".join(str(keyword) for keyword in item.get("keywords", []) if str(keyword).strip()) or "未识别明确动作词"
        status_class = "ok" if best else "bad"
        score_text = f"{float(best.get('score') or 0):.2f}" if best else "—"
        source_text = str(best.get("source_profile_name") or best.get("origin_label") or "")
        frame_text = ""
        if best.get("frame_start") is not None and best.get("frame_end") is not None:
            frame_text = f" · 帧 {best.get('frame_start')}-{best.get('frame_end')}"
        reason_text = "；".join(str(reason) for reason in best.get("reasons", []) if str(reason).strip())
        alternative_text = "、".join(
            f"{str(alt.get('name') or '')}（{float(alt.get('score') or 0):.2f}）"
            for alt in alternatives
            if isinstance(alt, dict) and str(alt.get("name") or "").strip()
        )
        best_html = (
            f"<strong>{escape(str(best.get('name') or best.get('action') or ''))}</strong>"
            f"<div class=\"id\">{escape(str(best.get('action') or ''))}{escape(frame_text)}</div>"
            f"<div class=\"id\">{escape(source_text)}</div>"
            if best
            else '<span class="bad">无合适候选</span>'
        )
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(item.get('shot_name') or item.get('shot_id') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(actor_label)}</td>"
            f"<td>{escape(str(item.get('query') or ''))}<div class=\"id\">关键词：{escape(keyword_text)}</div></td>"
            f"<td class=\"{status_class}\">{escape(str(item.get('status_label') or ''))}</td>"
            f"<td>{best_html}</td>"
            f"<td>{escape(score_text)}</td>"
            f"<td>{escape(reason_text or str(item.get('match_note') or ''))}</td>"
            f"<td>{escape(alternative_text or '—')}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="8" class="empty">暂无镜头动作需求，请先保存分镜或镜头备注。</td></tr>')
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 动作匹配清单</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .notice {{ margin: 12px 0; padding: 10px 12px; border: 1px solid #755f2c; border-radius: 8px; color: #f6d78b; background: #1d1a12; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .ok {{ color: #86efac; }}
    .bad {{ color: #ff9f9f; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 动作匹配清单</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}</div>
    <div class="notice">当前能力负责动作需求提取、动作片段复用和动作资产推荐；不同骨架之间仍需人工确认或后续骨骼重定向。</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('requirement_count') or 0)}</strong>动作需求</div>
      <div class="stat"><strong>{int(data.get('candidate_count') or 0)}</strong>候选动作</div>
      <div class="stat"><strong>{int(data.get('matched_count') or 0)}</strong>已匹配</div>
      <div class="stat"><strong>{int(data.get('unmatched_count') or 0)}</strong>待补动作</div>
    </div>
    <table>
      <thead><tr><th>镜头</th><th>演员</th><th>动作需求</th><th>状态</th><th>最佳动作</th><th>分数</th><th>匹配依据</th><th>备选</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "action_matches.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


AI_WORKFLOW_TASK_LABELS = {
    "text_to_image_reference": "文生图/首帧参考",
    "image_to_video": "图生视频/镜头延展",
    "asset_generation": "资产生成/替换",
    "motion_generation": "动作生成/重定向",
}

AI_WORKFLOW_RESULT_LABELS = {
    "image": "图片/首帧",
    "video": "视频",
    "asset": "模型资产",
    "motion": "动作",
    "attachment": "附件",
}

AI_WORKFLOW_TARGET_LABELS = {
    "render": "镜头输出",
    "asset": "工程资产",
    "attachment": "附件",
}


def _ai_workflow_status_label(status):
    labels = {
        "ready": "可执行",
        "ready_with_reference": "参考图就绪",
        "ready_with_candidates": "有本地候选",
        "needs_generation": "需生成",
        "needs_motion": "需补动作",
        "review": "需复核",
        "blocked": "阻断",
    }
    return labels.get(str(status or ""), str(status or "未定"))


def _ai_workflow_existing_file(path):
    path = str(path or "").strip()
    return bool(path and os.path.exists(path))


def _ai_workflow_file_ref(path):
    path = str(path or "").strip()
    return {
        "path": path,
        "exists": _ai_workflow_existing_file(path),
        "name": os.path.basename(path) if path else "",
    }


def _ai_workflow_names(items):
    names = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("role") or item.get("id") or "").strip()
        if name:
            names.append(name)
    return names


def _ai_workflow_shot_prompt(project_name, shot):
    if not isinstance(shot, dict):
        return ""
    actors = "、".join(_ai_workflow_names(shot.get("actors")))
    assets = "、".join(_ai_workflow_names(shot.get("assets")))
    camera = shot.get("camera") if isinstance(shot.get("camera"), dict) else {}
    camera_parts = []
    if camera.get("lens") not in (None, ""):
        camera_parts.append(str(camera.get("lens")) + "mm")
    if camera.get("location"):
        camera_parts.append("机位 " + str(camera.get("location")))
    parts = [
        "项目：" + str(project_name or "AI短剧"),
        "镜头：" + str(shot.get("shot_name") or shot.get("shot_id") or ""),
        "场次：" + str(shot.get("scene_number") or ""),
        "地点：" + str(shot.get("scene_location") or ""),
        "环境：" + str(shot.get("scene_environment_label") or shot.get("scene_environment") or ""),
        "时间：" + str(shot.get("scene_time_label") or shot.get("scene_time") or ""),
        "内容：" + str(shot.get("note") or ""),
        "演员：" + actors,
        "资产：" + assets,
        "机位：" + "，".join(camera_parts),
        "输出：" + str(shot.get("output_label") or shot.get("output_type") or ""),
    ]
    return "；".join(part for part in parts if part and not part.endswith("："))


def _ai_workflow_requirements_by_shot(asset_requirements):
    by_shot = {}
    for item in asset_requirements.get("requirements", []) if isinstance(asset_requirements, dict) else []:
        if not isinstance(item, dict):
            continue
        shots = item.get("shots") if isinstance(item.get("shots"), list) else []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("shot_id") or "").strip()
            if not shot_id:
                continue
            by_shot.setdefault(shot_id, []).append(item)
    return by_shot


def _ai_workflow_actions_by_shot(action_matches):
    by_shot = {}
    for item in action_matches.get("requirements", []) if isinstance(action_matches, dict) else []:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        by_shot.setdefault(shot_id, []).append(item)
    return by_shot


def _ai_workflow_task(task_id, task_type, status, shot, prompt, inputs=None, notes=None):
    inputs = inputs if isinstance(inputs, dict) else {}
    notes = notes if isinstance(notes, list) else ([] if notes in (None, "") else [str(notes)])
    return {
        "id": _safe_name(task_id, "ai_task"),
        "type": task_type,
        "type_label": AI_WORKFLOW_TASK_LABELS.get(task_type, task_type),
        "status": status,
        "status_label": _ai_workflow_status_label(status),
        "shot_id": str(shot.get("shot_id") or ""),
        "shot_name": str(shot.get("shot_name") or ""),
        "scene_number": str(shot.get("scene_number") or ""),
        "scene_location": str(shot.get("scene_location") or ""),
        "frame_start": shot.get("frame_start"),
        "frame_end": shot.get("frame_end"),
        "output_type": str(shot.get("output_type") or ""),
        "output_label": str(shot.get("output_label") or shot.get("output_type") or ""),
        "prompt": prompt,
        "inputs": inputs,
        "notes": notes,
    }


def build_blender_director_ai_workflow_tasks(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    project_name = str(metadata.get("project_name") or "Blender 导演台工程")
    storyboard = build_blender_director_storyboard(metadata)
    asset_requirements = build_blender_director_asset_requirements(metadata)
    action_matches = build_blender_director_action_matches(metadata)
    requirements_by_shot = _ai_workflow_requirements_by_shot(asset_requirements)
    actions_by_shot = _ai_workflow_actions_by_shot(action_matches)
    tasks = []
    ready_count = 0
    review_count = 0
    blocked_count = 0
    task_type_counts = {}
    for shot in storyboard:
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("shot_id") or f"shot_{len(tasks) + 1:03d}").strip()
        prompt = _ai_workflow_shot_prompt(project_name, shot)
        preview_path = str(shot.get("preview_path") or "").strip()
        output_path = str(shot.get("output_path") or "").strip()
        reference_exists = _ai_workflow_existing_file(preview_path)
        visual_type = "image_to_video" if reference_exists else "text_to_image_reference"
        visual_status = "ready_with_reference" if reference_exists else "ready"
        visual_notes = []
        if not reference_exists:
            visual_notes.append("没有可用预览图，建议先由文本生成首帧参考，或先执行 Blender 渲染。")
        if str(shot.get("output_type") or "") == "video":
            visual_notes.append("目标输出为视频，可用于图生视频或镜头延展。")
        tasks.append(
            _ai_workflow_task(
                "ai_visual_" + shot_id,
                visual_type,
                visual_status if prompt else "blocked",
                shot,
                prompt,
                {
                    "reference_image": _ai_workflow_file_ref(preview_path),
                    "render_output": _ai_workflow_file_ref(output_path),
                    "layer_paths": shot.get("layer_paths") if isinstance(shot.get("layer_paths"), dict) else {},
                    "actors": shot.get("actors") if isinstance(shot.get("actors"), list) else [],
                    "assets": shot.get("assets") if isinstance(shot.get("assets"), list) else [],
                },
                visual_notes,
            )
        )
        shot_requirements = requirements_by_shot.get(shot_id, [])
        missing_requirements = [item for item in shot_requirements if isinstance(item, dict) and not item.get("available")]
        if missing_requirements:
            with_candidates = [
                item
                for item in missing_requirements
                if isinstance(item.get("best_library_candidate"), dict) and item.get("best_library_candidate")
            ]
            tasks.append(
                _ai_workflow_task(
                    "ai_assets_" + shot_id,
                    "asset_generation",
                    "ready_with_candidates" if with_candidates else "needs_generation",
                    shot,
                    prompt,
                    {
                        "missing_requirements": missing_requirements,
                        "candidate_count": sum(int(item.get("library_candidate_count") or 0) for item in missing_requirements if isinstance(item, dict)),
                    },
                    [
                        "优先复用本地库候选；没有候选的条目可进入资产生成、模型修复或人工建模流程。"
                    ],
                )
            )
        shot_actions = actions_by_shot.get(shot_id, [])
        if shot_actions:
            unmatched = [item for item in shot_actions if isinstance(item, dict) and item.get("status") != "matched"]
            matched = [item for item in shot_actions if isinstance(item, dict) and item.get("status") == "matched"]
            tasks.append(
                _ai_workflow_task(
                    "ai_motion_" + shot_id,
                    "motion_generation",
                    "needs_motion" if unmatched else "review",
                    shot,
                    prompt,
                    {
                        "action_requirements": shot_actions,
                        "matched_count": len(matched),
                        "unmatched_count": len(unmatched),
                    },
                    [
                        "已匹配动作可进入重定向/验证；待补动作可进入动作生成或动作库补充流程。"
                    ],
                )
            )
    for task in tasks:
        status = str(task.get("status") or "")
        task_type = str(task.get("type") or "")
        task_type_counts[task_type] = task_type_counts.get(task_type, 0) + 1
        if status == "blocked":
            blocked_count += 1
        elif status in {"review", "needs_generation", "needs_motion"}:
            review_count += 1
        else:
            ready_count += 1
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": project_name,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shot_count": len(storyboard),
        "task_count": len(tasks),
        "ready_count": ready_count,
        "review_count": review_count,
        "blocked_count": blocked_count,
        "task_type_counts": [
            {"type": key, "type_label": AI_WORKFLOW_TASK_LABELS.get(key, key), "count": value}
            for key, value in sorted(task_type_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "asset_requirement_summary": {
            "missing_count": int(asset_requirements.get("missing_count") or 0),
            "missing_with_candidate_count": int(asset_requirements.get("missing_with_candidate_count") or 0),
        },
        "action_match_summary": {
            "requirement_count": int(action_matches.get("requirement_count") or 0),
            "matched_count": int(action_matches.get("matched_count") or 0),
            "unmatched_count": int(action_matches.get("unmatched_count") or 0),
        },
        "tasks": tasks,
    }


def write_blender_director_ai_workflow_tasks_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "ai_workflow_tasks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_blender_director_ai_workflow_tasks(metadata), f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_ai_workflow_tasks_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "ai_workflow_tasks.csv")
    data = build_blender_director_ai_workflow_tasks(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["任务ID", "任务类型", "状态", "镜头ID", "镜头名", "场次", "地点", "帧段", "输出", "参考图", "渲染输出", "提示词", "备注"])
        for item in data.get("tasks", []):
            if not isinstance(item, dict):
                continue
            inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
            reference = inputs.get("reference_image") if isinstance(inputs.get("reference_image"), dict) else {}
            render_output = inputs.get("render_output") if isinstance(inputs.get("render_output"), dict) else {}
            frame_text = ""
            if item.get("frame_start") is not None and item.get("frame_end") is not None:
                frame_text = str(item.get("frame_start")) + "-" + str(item.get("frame_end"))
            writer.writerow(
                [
                    item.get("id") or "",
                    item.get("type_label") or item.get("type") or "",
                    item.get("status_label") or item.get("status") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("scene_number") or "",
                    item.get("scene_location") or "",
                    frame_text,
                    item.get("output_label") or item.get("output_type") or "",
                    reference.get("path") or "",
                    render_output.get("path") or "",
                    item.get("prompt") or "",
                    "；".join(str(note or "") for note in item.get("notes", []) if str(note or "").strip()),
                ]
            )
    return path


def write_blender_director_ai_workflow_tasks_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_ai_workflow_tasks(metadata)
    rows = []
    for item in data.get("tasks", []):
        if not isinstance(item, dict):
            continue
        inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
        reference = inputs.get("reference_image") if isinstance(inputs.get("reference_image"), dict) else {}
        render_output = inputs.get("render_output") if isinstance(inputs.get("render_output"), dict) else {}
        ref_text = str(reference.get("path") or "")
        if ref_text:
            ref_text += "（可用）" if reference.get("exists") else "（缺失）"
        output_text = str(render_output.get("path") or "")
        if output_text:
            output_text += "（可用）" if render_output.get("exists") else "（缺失）"
        notes = "；".join(str(note or "") for note in item.get("notes", []) if str(note or "").strip())
        status_class = "bad" if item.get("status") == "blocked" else ("warn" if item.get("status") in {"review", "needs_generation", "needs_motion"} else "ok")
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(item.get('type_label') or item.get('type') or ''))}</strong><div class=\"id\">{escape(str(item.get('id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('shot_name') or item.get('shot_id') or ''))}<div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td class=\"{status_class}\">{escape(str(item.get('status_label') or item.get('status') or ''))}</td>"
            f"<td>{escape(ref_text or '—')}</td>"
            f"<td>{escape(output_text or '—')}</td>"
            f"<td>{escape(str(item.get('prompt') or ''))}</td>"
            f"<td>{escape(notes or '—')}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="7" class="empty">暂无 AI 工作流任务，请先保存镜头和资产需求。</td></tr>')
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - AI 工作流任务包</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 130px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .ok {{ color: #86efac; }}
    .warn {{ color: #f6d78b; }}
    .bad {{ color: #ff9f9f; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - AI 工作流任务包</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}。本文件只整理本地任务，不调用外部 AI 服务。</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(data.get('task_count') or 0)}</strong>AI任务</div>
      <div class="stat"><strong>{int(data.get('ready_count') or 0)}</strong>可执行</div>
      <div class="stat"><strong>{int(data.get('review_count') or 0)}</strong>需生成/复核</div>
      <div class="stat"><strong>{int(data.get('blocked_count') or 0)}</strong>阻断</div>
      <div class="stat"><strong>{int(data.get('asset_requirement_summary', {}).get('missing_with_candidate_count') or 0)}</strong>缺素材有候选</div>
      <div class="stat"><strong>{int(data.get('action_match_summary', {}).get('unmatched_count') or 0)}</strong>待补动作</div>
    </div>
    <table>
      <thead><tr><th>任务</th><th>镜头</th><th>状态</th><th>参考图</th><th>渲染输出</th><th>提示词</th><th>备注</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "ai_workflow_tasks.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


AI_WORKFLOW_EXPECTED_OUTPUTS = {
    "text_to_image_reference": {
        "label": "首帧/参考图",
        "extensions": ["png", "jpg", "jpeg", "webp", "exr"],
        "drop_hint": "把文生图或首帧参考图放入 results 目录，回 Blender 后登记为图片/首帧。",
    },
    "image_to_video": {
        "label": "视频镜头",
        "extensions": ["mp4", "mov", "avi", "mkv"],
        "drop_hint": "把图生视频或镜头延展结果放入 results 目录，回 Blender 后登记为视频。",
    },
    "asset_generation": {
        "label": "模型/资产",
        "extensions": ["blend", "glb", "gltf", "fbx", "obj", "stl", "ply", "abc", "usd", "usdz"],
        "drop_hint": "把生成或修复后的模型资产放入 results 目录，回 Blender 后登记为模型资产。",
    },
    "motion_generation": {
        "label": "动作文件",
        "extensions": ["bvh", "fbx"],
        "drop_hint": "把动作生成结果放入 results 目录，回 Blender 后登记为动作。",
    },
}


def _ai_workflow_task_input_files(task):
    files = []
    inputs = task.get("inputs") if isinstance(task.get("inputs"), dict) else {}

    def add_file(label, value):
        path = str(value or "").strip()
        if not path:
            return
        files.append(
            {
                "label": label,
                "path": path,
                "exists": bool(os.path.exists(path)),
            }
        )

    reference = inputs.get("reference_image") if isinstance(inputs.get("reference_image"), dict) else {}
    render_output = inputs.get("render_output") if isinstance(inputs.get("render_output"), dict) else {}
    add_file("参考图", reference.get("path"))
    add_file("渲染输出", render_output.get("path"))
    layer_paths = inputs.get("layer_paths") if isinstance(inputs.get("layer_paths"), dict) else {}
    for label, path in sorted(layer_paths.items()):
        add_file("分层素材：" + str(label), path)
    for actor in inputs.get("actors", []) if isinstance(inputs.get("actors"), list) else []:
        if isinstance(actor, dict):
            add_file("演员资产：" + str(actor.get("name") or actor.get("id") or ""), actor.get("path"))
    for asset in inputs.get("assets", []) if isinstance(inputs.get("assets"), list) else []:
        if isinstance(asset, dict):
            add_file("镜头资产：" + str(asset.get("name") or asset.get("id") or ""), asset.get("path"))
    return files


def build_blender_director_ai_workflow_handoff(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    project_dir = _storyboard_project_dir(metadata)
    task_data = build_blender_director_ai_workflow_tasks(metadata)
    handoff_dir = os.path.join(project_dir, "ai_workflow_handoff") if project_dir else ""
    jobs = []
    ready_count = 0
    review_count = 0
    blocked_count = 0
    for index, task in enumerate(task_data.get("tasks", []) if isinstance(task_data, dict) else [], start=1):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or f"ai_task_{index:03d}").strip()
        task_dir_name = _safe_name(task_id, f"ai_task_{index:03d}")
        job_dir = os.path.join(handoff_dir, task_dir_name) if handoff_dir else ""
        result_dir = os.path.join(job_dir, "results") if job_dir else ""
        task_type = str(task.get("type") or "")
        expected = AI_WORKFLOW_EXPECTED_OUTPUTS.get(
            task_type,
            {
                "label": "AI 结果文件",
                "extensions": [],
                "drop_hint": "把外部 AI 输出文件放入 results 目录，回 Blender 后批量登记。",
            },
        )
        status = str(task.get("status") or "")
        if status == "blocked":
            blocked_count += 1
        elif status in {"review", "needs_generation", "needs_motion"}:
            review_count += 1
        else:
            ready_count += 1
        jobs.append(
            {
                "id": task_id,
                "task_id": task_id,
                "task_type": task_type,
                "task_type_label": str(task.get("type_label") or AI_WORKFLOW_TASK_LABELS.get(task_type, task_type)),
                "status": status,
                "status_label": str(task.get("status_label") or _ai_workflow_status_label(status)),
                "shot_id": str(task.get("shot_id") or ""),
                "shot_name": str(task.get("shot_name") or ""),
                "scene_number": str(task.get("scene_number") or ""),
                "scene_location": str(task.get("scene_location") or ""),
                "frame_start": task.get("frame_start"),
                "frame_end": task.get("frame_end"),
                "prompt": str(task.get("prompt") or ""),
                "notes": task.get("notes") if isinstance(task.get("notes"), list) else [],
                "input_files": _ai_workflow_task_input_files(task),
                "expected_output": expected,
                "job_dir": job_dir,
                "result_dir": result_dir,
                "task_manifest_path": os.path.join(job_dir, "task.json") if job_dir else "",
                "prompt_path": os.path.join(job_dir, "prompt.txt") if job_dir else "",
                "notes_path": os.path.join(job_dir, "notes.txt") if job_dir else "",
                "result_readme_path": os.path.join(result_dir, "README.txt") if result_dir else "",
                "suggested_result_name": task_dir_name + "_result",
            }
        )
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "handoff_dir": handoff_dir,
        "manifest_path": os.path.join(handoff_dir, "handoff_manifest.json") if handoff_dir else "",
        "report_path": os.path.join(handoff_dir, "handoff.html") if handoff_dir else "",
        "csv_path": os.path.join(handoff_dir, "handoff.csv") if handoff_dir else "",
        "readme_path": os.path.join(handoff_dir, "README.txt") if handoff_dir else "",
        "task_count": len(jobs),
        "ready_count": ready_count,
        "review_count": review_count,
        "blocked_count": blocked_count,
        "result_inbox_count": len(jobs),
        "jobs": jobs,
    }


def write_blender_director_ai_workflow_handoff_package(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return {}
    data = build_blender_director_ai_workflow_handoff(metadata)
    handoff_dir = data.get("handoff_dir")
    if not handoff_dir:
        return data
    os.makedirs(handoff_dir, exist_ok=True)
    for job in data.get("jobs", []):
        if not isinstance(job, dict):
            continue
        job_dir = str(job.get("job_dir") or "").strip()
        result_dir = str(job.get("result_dir") or "").strip()
        if not job_dir or not result_dir:
            continue
        os.makedirs(result_dir, exist_ok=True)
        task_manifest = {
            "project_id": data.get("project_id") or "",
            "project_name": data.get("project_name") or "",
            "task_id": job.get("task_id") or "",
            "task_type": job.get("task_type") or "",
            "task_type_label": job.get("task_type_label") or "",
            "status": job.get("status") or "",
            "status_label": job.get("status_label") or "",
            "shot_id": job.get("shot_id") or "",
            "shot_name": job.get("shot_name") or "",
            "scene_number": job.get("scene_number") or "",
            "scene_location": job.get("scene_location") or "",
            "frame_start": job.get("frame_start"),
            "frame_end": job.get("frame_end"),
            "prompt": job.get("prompt") or "",
            "notes": job.get("notes") if isinstance(job.get("notes"), list) else [],
            "input_files": job.get("input_files") if isinstance(job.get("input_files"), list) else [],
            "expected_output": job.get("expected_output") if isinstance(job.get("expected_output"), dict) else {},
            "result_dir": result_dir,
            "suggested_result_name": job.get("suggested_result_name") or "",
        }
        with open(job.get("task_manifest_path"), "w", encoding="utf-8") as f:
            json.dump(task_manifest, f, ensure_ascii=False, indent=2)
        with open(job.get("prompt_path"), "w", encoding="utf-8") as f:
            f.write(str(job.get("prompt") or "").strip() + "\n")
        notes = [str(note or "") for note in job.get("notes", []) if str(note or "").strip()]
        with open(job.get("notes_path"), "w", encoding="utf-8") as f:
            f.write("\n".join(notes) + ("\n" if notes else ""))
        expected = job.get("expected_output") if isinstance(job.get("expected_output"), dict) else {}
        with open(job.get("result_readme_path"), "w", encoding="utf-8") as f:
            f.write(
                "AI 结果收件箱\n"
                "任务ID：" + str(job.get("task_id") or "") + "\n"
                "任务类型：" + str(job.get("task_type_label") or job.get("task_type") or "") + "\n"
                "建议输出：" + str(expected.get("label") or "AI 结果文件") + "\n"
                "建议扩展名：" + "、".join(str(ext) for ext in expected.get("extensions", []) if str(ext).strip()) + "\n"
                + str(expected.get("drop_hint") or "把外部 AI 输出文件放在这里，然后回 Blender 批量登记。")
                + "\n"
            )
    with open(data.get("manifest_path"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(data.get("csv_path"), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["任务ID", "任务类型", "状态", "镜头ID", "镜头名", "结果目录", "提示词文件", "建议输出", "建议扩展名"])
        for job in data.get("jobs", []):
            if not isinstance(job, dict):
                continue
            expected = job.get("expected_output") if isinstance(job.get("expected_output"), dict) else {}
            writer.writerow(
                [
                    job.get("task_id") or "",
                    job.get("task_type_label") or job.get("task_type") or "",
                    job.get("status_label") or job.get("status") or "",
                    job.get("shot_id") or "",
                    job.get("shot_name") or "",
                    job.get("result_dir") or "",
                    job.get("prompt_path") or "",
                    expected.get("label") or "",
                    "、".join(str(ext) for ext in expected.get("extensions", []) if str(ext).strip()),
                ]
            )
    rows = []
    for job in data.get("jobs", []):
        if not isinstance(job, dict):
            continue
        expected = job.get("expected_output") if isinstance(job.get("expected_output"), dict) else {}
        status_class = "bad" if job.get("status") == "blocked" else ("warn" if job.get("status") in {"review", "needs_generation", "needs_motion"} else "ok")
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(job.get('task_type_label') or job.get('task_type') or ''))}</strong><div class=\"id\">{escape(str(job.get('task_id') or ''))}</div></td>"
            f"<td>{escape(str(job.get('shot_name') or job.get('shot_id') or ''))}</td>"
            f"<td class=\"{status_class}\">{escape(str(job.get('status_label') or job.get('status') or ''))}</td>"
            f"<td>{escape(str(expected.get('label') or 'AI 结果文件'))}<div class=\"id\">{escape('、'.join(str(ext) for ext in expected.get('extensions', []) if str(ext).strip()))}</div></td>"
            f"<td>{escape(str(job.get('result_dir') or ''))}</td>"
            f"<td>{escape(str(job.get('prompt') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6" class="empty">暂无 AI 工作包任务。</td></tr>')
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - AI 工作包与结果收件箱</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 130px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .ok {{ color: #86efac; }}
    .warn {{ color: #f6d78b; }}
    .bad {{ color: #ff9f9f; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - AI 工作包与结果收件箱</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}。每个任务都有独立 prompt、task.json 和 results 目录；外部 AI 工具输出后可回 Blender 批量登记。</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('task_count') or 0)}</strong>工作包任务</div>
      <div class="stat"><strong>{int(data.get('ready_count') or 0)}</strong>可执行</div>
      <div class="stat"><strong>{int(data.get('review_count') or 0)}</strong>需生成/复核</div>
      <div class="stat"><strong>{int(data.get('blocked_count') or 0)}</strong>阻断</div>
      <div class="stat"><strong>{int(data.get('result_inbox_count') or 0)}</strong>结果收件箱</div>
    </div>
    <table>
      <thead><tr><th>任务</th><th>镜头</th><th>状态</th><th>建议输出</th><th>结果目录</th><th>提示词</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    with open(data.get("report_path"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(data.get("readme_path"), "w", encoding="utf-8") as f:
        f.write(
            "AI 工作包与结果收件箱\n"
            "1. 打开每个任务目录里的 prompt.txt 或 task.json。\n"
            "2. 用任意外部 AI 工具生成图片、视频、模型或动作。\n"
            "3. 把结果文件放进对应任务的 results 目录。\n"
            "4. 回到 Blender 导演台，使用“批量登记AI结果目录”登记 results 或整个 ai_workflow_handoff 目录。\n"
        )
    if isinstance(metadata, dict):
        metadata["ai_workflow_handoff_dir"] = data.get("handoff_dir") or ""
        metadata["ai_workflow_handoff_manifest_path"] = data.get("manifest_path") or ""
        metadata["ai_workflow_handoff_report_path"] = data.get("report_path") or ""
        metadata["ai_workflow_handoff_csv_path"] = data.get("csv_path") or ""
        metadata["ai_workflow_handoff_readme_path"] = data.get("readme_path") or ""
    return data


def _ai_workflow_result_type_from_path(path, fallback="attachment"):
    lower = str(path or "").lower()
    if lower.endswith((".mp4", ".mov", ".avi", ".mkv")):
        return "video"
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".exr", ".hdr")):
        return "image"
    if lower.endswith(".bvh"):
        return "motion"
    if lower.endswith((".blend", ".glb", ".gltf", ".fbx", ".obj", ".stl", ".ply", ".abc", ".usd", ".usdz")):
        return "asset"
    return str(fallback or "attachment")


def _ai_workflow_result_task_lookup(metadata):
    task_data = metadata.get("ai_workflow_tasks") if isinstance(metadata.get("ai_workflow_tasks"), dict) else {}
    tasks = task_data.get("tasks") if isinstance(task_data.get("tasks"), list) else []
    if not tasks:
        try:
            task_data = build_blender_director_ai_workflow_tasks(metadata)
            tasks = task_data.get("tasks") if isinstance(task_data.get("tasks"), list) else []
        except Exception:
            tasks = []
    return {
        str(task.get("id") or ""): task
        for task in tasks
        if isinstance(task, dict) and str(task.get("id") or "").strip()
    }


def _ai_workflow_normalize_result(item, task_lookup, source="registered"):
    if not isinstance(item, dict):
        item = {}
    task_id = str(item.get("task_id") or item.get("ai_task_id") or "").strip()
    task = task_lookup.get(task_id, {}) if task_id else {}
    path = str(item.get("path") or item.get("output_path") or item.get("preview_path") or "").strip()
    result_type = str(item.get("result_type") or item.get("ai_result_type") or "").strip()
    if not result_type:
        result_type = _ai_workflow_result_type_from_path(path)
    target_type = str(item.get("target_type") or "").strip()
    if not target_type:
        target_type = "render" if source == "render" else ("asset" if source == "asset" else "attachment")
    payload_id = str(item.get("payload_id") or item.get("shot_id") or item.get("id") or "").strip()
    payload_name = str(item.get("payload_name") or item.get("shot_name") or item.get("name") or os.path.basename(path) or "").strip()
    shot_id = str(item.get("shot_id") or task.get("shot_id") or "").strip()
    shot_name = str(item.get("shot_name") or task.get("shot_name") or "").strip()
    result_id = str(item.get("id") or "").strip()
    if not result_id:
        result_id = _safe_name("ai_result_" + (task_id or payload_id or os.path.basename(path) or source), "ai_result")
    return {
        "id": result_id,
        "task_id": task_id,
        "task_type": str(task.get("type") or ""),
        "task_type_label": str(task.get("type_label") or AI_WORKFLOW_TASK_LABELS.get(str(task.get("type") or ""), "")),
        "shot_id": shot_id,
        "shot_name": shot_name,
        "result_type": result_type,
        "result_type_label": AI_WORKFLOW_RESULT_LABELS.get(result_type, result_type),
        "target_type": target_type,
        "target_type_label": AI_WORKFLOW_TARGET_LABELS.get(target_type, target_type),
        "path": path,
        "path_exists": bool(path and os.path.exists(path)),
        "payload_id": payload_id,
        "payload_name": payload_name,
        "note": str(item.get("note") or item.get("ai_result_note") or ""),
        "registered_at": str(item.get("registered_at") or item.get("created_at") or ""),
        "source": source,
    }


def build_blender_director_ai_workflow_results(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    task_lookup = _ai_workflow_result_task_lookup(metadata)
    entries = []
    seen = set()

    def add(item, source):
        entry = _ai_workflow_normalize_result(item, task_lookup, source)
        if entry.get("path"):
            key = (
                "path",
                entry.get("task_id") or "",
                entry.get("target_type") or "",
                entry.get("result_type") or "",
                entry.get("path") or "",
            )
        else:
            key = ("id", entry.get("id") or "", entry.get("task_id") or "", entry.get("target_type") or "")
        if key in seen:
            return
        seen.add(key)
        entries.append(entry)

    for item in metadata.get("ai_workflow_results", []) if isinstance(metadata.get("ai_workflow_results"), list) else []:
        if isinstance(item, dict):
            add(item, "registered")
    for item in metadata.get("renders", []) if isinstance(metadata.get("renders"), list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("mode") == "ai_workflow_result" or item.get("ai_task_id") or item.get("ai_result_type"):
            add(item, "render")
    for item in metadata.get("assets", []) if isinstance(metadata.get("assets"), list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("generated_by") == "ai_workflow" or item.get("ai_task_id") or item.get("ai_result_type"):
            add(item, "asset")

    result_type_counts = {}
    target_type_counts = {}
    file_exists_count = 0
    for entry in entries:
        result_type = str(entry.get("result_type") or "attachment")
        target_type = str(entry.get("target_type") or "attachment")
        result_type_counts[result_type] = result_type_counts.get(result_type, 0) + 1
        target_type_counts[target_type] = target_type_counts.get(target_type, 0) + 1
        if entry.get("path_exists"):
            file_exists_count += 1

    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "result_count": len(entries),
        "file_exists_count": file_exists_count,
        "missing_file_count": max(0, len(entries) - file_exists_count),
        "render_count": int(target_type_counts.get("render") or 0),
        "asset_count": int(target_type_counts.get("asset") or 0),
        "attachment_count": int(target_type_counts.get("attachment") or 0),
        "result_type_counts": [
            {"type": key, "type_label": AI_WORKFLOW_RESULT_LABELS.get(key, key), "count": value}
            for key, value in sorted(result_type_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "target_type_counts": [
            {"type": key, "type_label": AI_WORKFLOW_TARGET_LABELS.get(key, key), "count": value}
            for key, value in sorted(target_type_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "results": entries,
    }


def write_blender_director_ai_workflow_results_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "ai_workflow_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_blender_director_ai_workflow_results(metadata), f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_ai_workflow_results_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "ai_workflow_results.csv")
    data = build_blender_director_ai_workflow_results(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["结果ID", "任务ID", "任务类型", "镜头ID", "镜头名", "结果类型", "去向", "文件状态", "路径", "名称", "备注", "登记时间"])
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            writer.writerow(
                [
                    item.get("id") or "",
                    item.get("task_id") or "",
                    item.get("task_type_label") or item.get("task_type") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("result_type_label") or item.get("result_type") or "",
                    item.get("target_type_label") or item.get("target_type") or "",
                    "可用" if item.get("path_exists") else "缺失",
                    item.get("path") or "",
                    item.get("payload_name") or "",
                    item.get("note") or "",
                    item.get("registered_at") or "",
                ]
            )
    return path


def write_blender_director_ai_workflow_results_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_ai_workflow_results(metadata)
    rows = []
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        status_class = "ok" if item.get("path_exists") else "bad"
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(item.get('result_type_label') or item.get('result_type') or ''))}</strong><div class=\"id\">{escape(str(item.get('id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('target_type_label') or item.get('target_type') or ''))}</td>"
            f"<td>{escape(str(item.get('task_type_label') or item.get('task_id') or '—'))}<div class=\"id\">{escape(str(item.get('task_id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('shot_name') or item.get('shot_id') or '—'))}<div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td class=\"{status_class}\">{'可用' if item.get('path_exists') else '缺失'}</td>"
            f"<td>{escape(str(item.get('path') or '—'))}</td>"
            f"<td>{escape(str(item.get('payload_name') or '—'))}</td>"
            f"<td>{escape(str(item.get('note') or '—'))}</td>"
            f"<td>{escape(str(item.get('registered_at') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="9" class="empty">暂无已登记的 AI 工作流结果。</td></tr>')
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - AI 结果回填台账</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 130px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .ok {{ color: #86efac; }}
    .bad {{ color: #ff9f9f; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - AI 结果回填台账</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}。记录外部 AI 输出回填到 Blender 镜头、资产、动作或附件的情况。</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('result_count') or 0)}</strong>已登记结果</div>
      <div class="stat"><strong>{int(data.get('render_count') or 0)}</strong>镜头输出</div>
      <div class="stat"><strong>{int(data.get('asset_count') or 0)}</strong>工程资产/动作</div>
      <div class="stat"><strong>{int(data.get('attachment_count') or 0)}</strong>附件</div>
      <div class="stat"><strong>{int(data.get('file_exists_count') or 0)}</strong>文件可用</div>
      <div class="stat"><strong>{int(data.get('missing_file_count') or 0)}</strong>文件缺失</div>
    </div>
    <table>
      <thead><tr><th>结果</th><th>去向</th><th>任务</th><th>镜头</th><th>文件</th><th>路径</th><th>名称</th><th>备注</th><th>登记时间</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "ai_workflow_results.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_production_check(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    entries = build_blender_director_storyboard(metadata)
    issues = []
    seen_ids = {}
    seen_names = {}

    def add_issue(severity, code, label, shot, detail):
        issues.append(
            {
                "severity": severity,
                "code": code,
                "label": label,
                "shot_id": str((shot or {}).get("shot_id") or ""),
                "shot_name": str((shot or {}).get("shot_name") or ""),
                "detail": str(detail or ""),
            }
        )

    previous = None
    for item in entries:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        shot_name = str(item.get("shot_name") or "").strip()
        if shot_id:
            if shot_id in seen_ids:
                add_issue("error", "duplicate_shot_id", "镜头ID重复", item, f"与 {seen_ids[shot_id]} 重复")
            seen_ids[shot_id] = shot_name or shot_id
        if shot_name:
            if shot_name in seen_names:
                add_issue("warning", "duplicate_shot_name", "镜头名重复", item, f"与 {seen_names[shot_name]} 重复")
            seen_names[shot_name] = shot_id or shot_name
        if not shot_id:
            add_issue("warning", "missing_shot_id", "缺少镜头ID", item, "镜头没有稳定 ID，后续更新和引用不够稳。")
        if not shot_name:
            add_issue("warning", "missing_shot_name", "缺少镜头名", item, "镜头名为空。")
        if not str(item.get("scene_number") or "").strip() and not str(item.get("scene_location") or "").strip():
            add_issue("warning", "missing_scene", "缺少分场信息", item, "未填写场次或地点。")
        actors = item.get("actors") if isinstance(item.get("actors"), list) else []
        if not actors:
            add_issue("warning", "missing_actors", "缺少演员记录", item, "镜头没有记录演员。")
        assets = item.get("assets") if isinstance(item.get("assets"), list) else []
        if not assets:
            add_issue("warning", "missing_assets", "缺少资产依赖", item, "镜头没有记录使用的资产。")
        camera = item.get("camera") if isinstance(item.get("camera"), dict) else {}
        if not camera:
            add_issue("warning", "missing_camera", "缺少相机快照", item, "镜头没有保存相机数据。")
        frame_start = item.get("frame_start")
        frame_end = item.get("frame_end")
        duration_frames = _duration_frames_from_range(frame_start, frame_end)
        if duration_frames is None:
            add_issue("warning", "missing_frame_range", "缺少帧段", item, "镜头没有完整起止帧。")
        elif int(duration_frames) <= 0:
            add_issue("error", "invalid_frame_range", "帧段无效", item, f"起止帧：{frame_start}-{frame_end}")
        if previous and duration_frames is not None:
            try:
                prev_end = int(previous.get("frame_end"))
                start = int(frame_start)
                if start <= prev_end:
                    add_issue("warning", "frame_overlap", "帧段重叠", item, f"上一镜头结束帧 {prev_end}，当前起始帧 {start}")
                elif start > prev_end + 1:
                    add_issue("info", "frame_gap", "帧段有空隙", item, f"上一镜头结束帧 {prev_end}，当前起始帧 {start}")
            except Exception:
                pass
        if frame_end is not None:
            previous = {"frame_end": frame_end}
        output_path = str(item.get("output_path") or "").strip()
        preview_path = str(item.get("preview_path") or "").strip()
        if output_path and not os.path.exists(output_path):
            add_issue("error", "missing_output_file", "输出文件不存在", item, output_path)
        if preview_path and not os.path.exists(preview_path):
            add_issue("warning", "missing_preview_file", "预览文件不存在", item, preview_path)
        if not (output_path or preview_path or item.get("last_rendered_at")):
            add_issue("info", "not_rendered", "尚未渲染", item, "镜头还没有渲染输出。")
        status = str(item.get("shot_status") or "")
        status_label = str(item.get("shot_status_label") or "")
        if status != "approved" and status_label != "已定稿":
            add_issue("info", "not_approved", "镜头未定稿", item, status_label or status or "未设置状态")

    error_count = sum(1 for item in issues if item.get("severity") == "error")
    warning_count = sum(1 for item in issues if item.get("severity") == "warning")
    info_count = sum(1 for item in issues if item.get("severity") == "info")
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shot_count": len(entries),
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "ready_for_delivery": error_count == 0,
        "issues": issues,
    }


def write_blender_director_production_check_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "production_check.json")
    data = build_blender_director_production_check(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_production_check_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "production_check.csv")
    check = build_blender_director_production_check(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["级别", "问题", "代码", "镜头ID", "镜头名", "详情"])
        for item in check.get("issues", []):
            if not isinstance(item, dict):
                continue
            writer.writerow(
                [
                    item.get("severity") or "",
                    item.get("label") or "",
                    item.get("code") or "",
                    item.get("shot_id") or "",
                    item.get("shot_name") or "",
                    item.get("detail") or "",
                ]
            )
    return path


def write_blender_director_production_check_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    check = build_blender_director_production_check(metadata)
    project_name = str(check.get("project_name") or "Blender 导演台工程")
    rows = []
    severity_labels = {"error": "错误", "warning": "提醒", "info": "信息"}
    for item in check.get("issues", []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "")
        rows.append(
            "<tr>"
            f"<td class=\"sev-{escape(severity)}\">{escape(severity_labels.get(severity, severity))}</td>"
            f"<td>{escape(str(item.get('label') or ''))}<div class=\"id\">{escape(str(item.get('code') or ''))}</div></td>"
            f"<td>{escape(str(item.get('shot_name') or item.get('shot_id') or ''))}<div class=\"id\">{escape(str(item.get('shot_id') or ''))}</div></td>"
            f"<td>{escape(str(item.get('detail') or ''))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="4" class="empty">没有发现制作数据问题</td></tr>')
    updated_at = str(check.get("updated_at") or "")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 制作问题检查</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .sev-error {{ color: #ff9f9f; font-weight: 700; }}
    .sev-warning {{ color: #ffd166; font-weight: 700; }}
    .sev-info {{ color: #8fd3ff; font-weight: 700; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 制作问题检查</h1>
    <div class="meta">更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(check.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(check.get('error_count') or 0)}</strong>错误</div>
      <div class="stat"><strong>{int(check.get('warning_count') or 0)}</strong>提醒</div>
      <div class="stat"><strong>{int(check.get('info_count') or 0)}</strong>信息</div>
    </div>
    <table>
      <thead><tr><th>级别</th><th>问题</th><th>镜头</th><th>详情</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "production_check.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_continuity_check(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    scenes = {}
    shot_count = 0
    issue_count = 0
    for item in build_blender_director_storyboard(metadata):
        if not isinstance(item, dict):
            continue
        shot_count += 1
        scene_number = str(item.get("scene_number") or "").strip()
        scene_location = str(item.get("scene_location") or "").strip()
        scene_environment = str(item.get("scene_environment_label") or item.get("scene_environment") or "").strip()
        scene_time = str(item.get("scene_time_label") or item.get("scene_time") or "").strip()
        scene_key = "|".join(part for part in (scene_number, scene_location, scene_environment, scene_time) if part) or "未分场"
        scene = scenes.setdefault(
            scene_key,
            {
                "scene_key": scene_key,
                "scene_number": scene_number or "未分场",
                "scene_location": scene_location,
                "scene_environment": scene_environment,
                "scene_time": scene_time,
                "shot_count": 0,
                "issue_count": 0,
                "shots": [],
            },
        )
        issues = []
        actors = item.get("actors") if isinstance(item.get("actors"), list) else []
        assets = item.get("assets") if isinstance(item.get("assets"), list) else []
        frame_start = item.get("frame_start")
        frame_end = item.get("frame_end")
        duration_frames = _duration_frames_from_range(frame_start, frame_end)
        rendered = bool(item.get("output_path") or item.get("preview_path") or item.get("last_rendered_at"))
        if scene_key == "未分场":
            issues.append("缺少分场")
        if not actors:
            issues.append("缺少演员")
        if not assets:
            issues.append("缺少资产")
        if duration_frames is None:
            issues.append("缺少帧段")
        elif int(duration_frames) <= 0:
            issues.append("帧段无效")
        if not rendered:
            issues.append("尚未渲染")
        issue_count += len(issues)
        scene["shot_count"] += 1
        scene["issue_count"] += len(issues)
        scene["shots"].append(
            {
                "index": item.get("index") or "",
                "shot_id": str(item.get("shot_id") or ""),
                "shot_name": str(item.get("shot_name") or ""),
                "frame_start": frame_start,
                "frame_end": frame_end,
                "duration_frames": duration_frames,
                "actor_count": len(actors),
                "asset_count": len(assets),
                "rendered": rendered,
                "queue_status_label": "已渲染" if rendered else "待渲染",
                "issues": issues,
                "issue_count": len(issues),
            }
        )
    rows = sorted(scenes.values(), key=lambda item: str(item.get("scene_key") or ""))
    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scene_count": len(rows),
        "shot_count": shot_count,
        "issue_count": issue_count,
        "scenes": rows,
    }


def write_blender_director_continuity_check_manifest(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "continuity_check.json")
    data = build_blender_director_continuity_check(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_continuity_check_csv(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "continuity_check.csv")
    data = build_blender_director_continuity_check(metadata)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["场次", "地点", "内外景", "日夜", "镜头ID", "镜头名", "帧段", "演员数", "资产数", "渲染", "问题"])
        for scene in data.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            for shot in scene.get("shots", []) if isinstance(scene.get("shots"), list) else []:
                if not isinstance(shot, dict):
                    continue
                frame_text = ""
                if shot.get("frame_start") is not None and shot.get("frame_end") is not None:
                    frame_text = f"{shot.get('frame_start')}-{shot.get('frame_end')}"
                writer.writerow(
                    [
                        scene.get("scene_number") or "",
                        scene.get("scene_location") or "",
                        scene.get("scene_environment") or "",
                        scene.get("scene_time") or "",
                        shot.get("shot_id") or "",
                        shot.get("shot_name") or "",
                        frame_text,
                        shot.get("actor_count") or 0,
                        shot.get("asset_count") or 0,
                        shot.get("queue_status_label") or "",
                        "、".join(str(issue) for issue in shot.get("issues", []) if str(issue).strip()),
                    ]
                )
    return path


def write_blender_director_continuity_check_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    data = build_blender_director_continuity_check(metadata)
    project_name = str(data.get("project_name") or "Blender 导演台工程")
    rows = []
    for scene in data.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        scene_label = " / ".join(
            part
            for part in (
                str(scene.get("scene_number") or "").strip(),
                str(scene.get("scene_location") or "").strip(),
                str(scene.get("scene_environment") or "").strip(),
                str(scene.get("scene_time") or "").strip(),
            )
            if part
        ) or "未分场"
        for shot in scene.get("shots", []) if isinstance(scene.get("shots"), list) else []:
            if not isinstance(shot, dict):
                continue
            frame_text = ""
            if shot.get("frame_start") is not None and shot.get("frame_end") is not None:
                frame_text = f"{shot.get('frame_start')}-{shot.get('frame_end')}"
            issues = "、".join(str(issue) for issue in shot.get("issues", []) if str(issue).strip())
            status_class = "bad" if issues else "ok"
            rows.append(
                "<tr>"
                f"<td>{escape(scene_label)}</td>"
                f"<td><strong>{escape(str(shot.get('shot_name') or shot.get('shot_id') or '未命名镜头'))}</strong><div class=\"id\">{escape(str(shot.get('shot_id') or ''))}</div></td>"
                f"<td>{escape(frame_text)}</td>"
                f"<td>{int(shot.get('actor_count') or 0)}</td>"
                f"<td>{int(shot.get('asset_count') or 0)}</td>"
                f"<td>{escape(str(shot.get('queue_status_label') or ''))}</td>"
                f"<td class=\"{status_class}\">{escape(issues or '通过')}</td>"
                "</tr>"
            )
    if not rows:
        rows.append('<tr><td colspan="7" class="empty">暂无镜头，请先在 Blender 导演台保存镜头。</td></tr>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 连续性检查</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .id {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    .ok {{ color: #86efac; }}
    .bad {{ color: #ff9f9f; }}
    .empty {{ color: #96a3b7; text-align: center; padding: 26px; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 连续性检查</h1>
    <div class="meta">更新于 {escape(str(data.get('updated_at') or ''))}</div>
    <div class="stats">
      <div class="stat"><strong>{int(data.get('scene_count') or 0)}</strong>场次</div>
      <div class="stat"><strong>{int(data.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(data.get('issue_count') or 0)}</strong>问题</div>
    </div>
    <table>
      <thead><tr><th>场次</th><th>镜头</th><th>帧段</th><th>演员</th><th>资产</th><th>渲染</th><th>问题</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "continuity_check.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def write_blender_director_project_dashboard(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    if not isinstance(metadata, dict):
        metadata = {}
    os.makedirs(project_dir, exist_ok=True)
    production = build_blender_director_production_manifest(metadata)
    queue = build_blender_director_render_queue(metadata)
    batch_render_jobs = build_blender_director_batch_render_jobs(metadata)
    batch_render_command = build_blender_director_batch_render_command(metadata)
    render_versions = build_blender_director_render_versions(metadata)
    scene_breakdown = build_blender_director_scene_breakdown(metadata)
    episode_delivery = build_blender_director_episode_delivery(metadata)
    call_sheet = build_blender_director_call_sheet(metadata)
    actor_schedule = build_blender_director_actor_schedule(metadata)
    duration = build_blender_director_duration_summary(metadata)
    edit_timeline = build_blender_director_edit_timeline(metadata)
    asset_requirements = build_blender_director_asset_requirements(metadata)
    asset_ecosystem = build_blender_director_asset_ecosystem(metadata)
    asset_preflight = build_blender_director_asset_preflight(metadata)
    action_matches = build_blender_director_action_matches(metadata)
    ai_workflow_tasks = build_blender_director_ai_workflow_tasks(metadata)
    ai_workflow_handoff = build_blender_director_ai_workflow_handoff(metadata)
    ai_workflow_results = build_blender_director_ai_workflow_results(metadata)
    retarget_summary = build_blender_director_retarget_summary(metadata)
    production_check = build_blender_director_production_check(metadata)
    post_handoff = build_blender_director_post_handoff(metadata)
    continuity_check = build_blender_director_continuity_check(metadata)
    project_name = str(metadata.get("project_name") or production.get("project_name") or "Blender 导演台工程")
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def link_row(label, path, note=""):
        path = str(path or "").strip()
        uri = _file_uri(path) if path and os.path.exists(path) else ""
        file_label = os.path.basename(path) if path else "未生成"
        if uri:
            file_html = f'<a href="{escape(uri)}">{escape(file_label)}</a>'
        else:
            file_html = f'<span class="muted">{escape(file_label)}</span>'
        return (
            "<tr>"
            f"<td>{escape(label)}</td>"
            f"<td>{file_html}</td>"
            f"<td>{escape(note)}</td>"
            "</tr>"
        )

    links = [
        link_row("分镜表", metadata.get("storyboard_report_path") or os.path.join(project_dir, "storyboard_report.html"), "镜头预览、演员、资产、输出文件"),
        link_row("分镜 CSV", metadata.get("storyboard_csv_path") or os.path.join(project_dir, "storyboard.csv"), "用于表格、剪辑或制片流转"),
        link_row("渲染队列", metadata.get("render_queue_report_path") or os.path.join(project_dir, "render_queue.html"), "已渲染/待渲染、帧段、版本"),
        link_row("渲染队列 CSV", metadata.get("render_queue_csv_path") or os.path.join(project_dir, "render_queue.csv"), "用于批量渲染排期"),
        link_row("批量渲染任务", metadata.get("batch_render_jobs_report_path") or os.path.join(project_dir, "batch_render_jobs.html"), "待渲染镜头、帧段、输出类型、阻断原因"),
        link_row("批量渲染 CSV", metadata.get("batch_render_jobs_csv_path") or os.path.join(project_dir, "batch_render_jobs.csv"), "用于后续 Blender 批处理执行"),
        link_row("后台渲染命令", metadata.get("batch_render_command_report_path") or os.path.join(project_dir, "batch_render_command.html"), "Blender 后台渲染待渲染镜头的命令说明"),
        link_row("镜头版本索引", metadata.get("render_versions_report_path") or os.path.join(project_dir, "render_versions.html"), "每个镜头的渲染版本、输出文件、最新记录"),
        link_row("镜头版本 CSV", metadata.get("render_versions_csv_path") or os.path.join(project_dir, "render_versions.csv"), "用于后期核对版本文件"),
        link_row("分场表", metadata.get("scene_breakdown_report_path") or os.path.join(project_dir, "scene_breakdown.html"), "场次、地点、内外景、日夜"),
        link_row("分场 CSV", metadata.get("scene_breakdown_csv_path") or os.path.join(project_dir, "scene_breakdown.csv"), "用于拍摄排期或场景核对"),
        link_row("分集交付清单", metadata.get("episode_delivery_report_path") or os.path.join(project_dir, "episode_delivery.html"), "按分集和场次汇总镜头、演员、资产、渲染状态"),
        link_row("分集交付 CSV", metadata.get("episode_delivery_csv_path") or os.path.join(project_dir, "episode_delivery.csv"), "用于短剧分集交付和分集排期"),
        link_row("分集交付包", metadata.get("episode_delivery_packages_report_path") or os.path.join(project_dir, "episode_delivery_packages.html"), "按分集生成单独 zip 交付包"),
        link_row("分集交付包 CSV", metadata.get("episode_delivery_packages_csv_path") or os.path.join(project_dir, "episode_delivery_packages.csv"), "用于核对每集交付包路径"),
        link_row("拍摄单", metadata.get("call_sheet_report_path") or os.path.join(project_dir, "call_sheet.html"), "按场次汇总演员、资产、镜头和待渲染"),
        link_row("拍摄单 CSV", metadata.get("call_sheet_csv_path") or os.path.join(project_dir, "call_sheet.csv"), "用于现场调度或制片核对"),
        link_row("演员调度", metadata.get("actor_schedule_report_path") or os.path.join(project_dir, "actor_schedule.html"), "角色出镜、待渲染镜头、总帧数"),
        link_row("演员调度 CSV", metadata.get("actor_schedule_csv_path") or os.path.join(project_dir, "actor_schedule.csv"), "用于排戏或角色资产检查"),
        link_row("剪辑时间线", metadata.get("edit_timeline_report_path") or os.path.join(project_dir, "edit_timeline.html"), "成片起止时间、镜头时长、输出文件"),
        link_row("剪辑时间线 CSV", metadata.get("edit_timeline_csv_path") or os.path.join(project_dir, "edit_timeline.csv"), "用于剪辑流转或后期排片"),
        link_row("剪辑 EDL", metadata.get("edit_timeline_edl_path") or os.path.join(project_dir, "edit_timeline.edl"), "用于导入剪辑软件的基础时间线"),
        link_row("剪辑 FCPXML", metadata.get("edit_timeline_fcpxml_path") or os.path.join(project_dir, "edit_timeline.fcpxml"), "用于导入剪辑软件的媒体时间线"),
        link_row("后期交接清单", metadata.get("post_handoff_report_path") or os.path.join(project_dir, "post_handoff.html"), "剪辑/合成需要的输出、分层素材和缺失文件"),
        link_row("后期交接 CSV", metadata.get("post_handoff_csv_path") or os.path.join(project_dir, "post_handoff.csv"), "用于交给后期表格核对"),
        link_row("连续性检查", metadata.get("continuity_check_report_path") or os.path.join(project_dir, "continuity_check.html"), "按场次核对演员、资产、帧段、渲染状态"),
        link_row("连续性 CSV", metadata.get("continuity_check_csv_path") or os.path.join(project_dir, "continuity_check.csv"), "用于逐场核对制作遗漏"),
        link_row("制作问题检查", metadata.get("production_check_report_path") or os.path.join(project_dir, "production_check.html"), "重复镜头、缺字段、帧段问题、缺文件"),
        link_row("制作问题 CSV", metadata.get("production_check_csv_path") or os.path.join(project_dir, "production_check.csv"), "用于批量核对制作问题"),
        link_row("时长统计", metadata.get("duration_summary_path") or os.path.join(project_dir, "duration_summary.json"), "总帧数、估算秒数、平均镜头时长"),
        link_row("制作清单", metadata.get("production_report_path") or os.path.join(project_dir, "production_report.html"), "镜头进度、资产使用与重定向动作质量"),
        link_row("资产使用 CSV", metadata.get("asset_usage_csv_path") or os.path.join(project_dir, "asset_usage.csv"), "资产反查引用镜头"),
        link_row("资产需求清单", metadata.get("asset_requirements_report_path") or os.path.join(project_dir, "asset_requirements.html"), "演员模型、镜头资产、缺素材核对"),
        link_row("资产需求 CSV", metadata.get("asset_requirements_csv_path") or os.path.join(project_dir, "asset_requirements.csv"), "用于采购、建模或资产整理"),
        link_row("资产生态报告", metadata.get("asset_ecosystem_report_path") or os.path.join(project_dir, "asset_ecosystem.html"), "开源来源、授权提示、库文件可用性和导入记录"),
        link_row("资产生态 CSV", metadata.get("asset_ecosystem_csv_path") or os.path.join(project_dir, "asset_ecosystem.csv"), "用于资产库整理、授权复核和缺文件排查"),
        link_row("资产导入预检", metadata.get("asset_preflight_report_path") or os.path.join(project_dir, "asset_preflight.html"), "导入前风险、动作准备度、贴图完整性与修复建议"),
        link_row("资产导入预检 CSV", metadata.get("asset_preflight_csv_path") or os.path.join(project_dir, "asset_preflight.csv"), "用于批量修复资产库问题"),
        link_row("动作匹配清单", metadata.get("action_matches_report_path") or os.path.join(project_dir, "action_matches.html"), "按镜头和演员匹配工程动作片段与动作库资产"),
        link_row("动作匹配 CSV", metadata.get("action_matches_csv_path") or os.path.join(project_dir, "action_matches.csv"), "用于动作采购、动画调度和人工复核"),
        link_row("AI 工作流任务包", metadata.get("ai_workflow_tasks_report_path") or os.path.join(project_dir, "ai_workflow_tasks.html"), "图生视频、资产生成/修复、动作生成/重定向的本地任务清单"),
        link_row("AI 工作流 CSV", metadata.get("ai_workflow_tasks_csv_path") or os.path.join(project_dir, "ai_workflow_tasks.csv"), "用于桥接外部 AI 工具或批处理脚本"),
        link_row("AI 工作包与结果收件箱", metadata.get("ai_workflow_handoff_report_path") or os.path.join(project_dir, "ai_workflow_handoff", "handoff.html"), "每个 AI 任务的 prompt、task.json 与 results 投递目录"),
        link_row("AI 工作包 CSV", metadata.get("ai_workflow_handoff_csv_path") or os.path.join(project_dir, "ai_workflow_handoff", "handoff.csv"), "用于外部 AI 工具批处理和结果投递核对"),
        link_row("AI 结果回填台账", metadata.get("ai_workflow_results_report_path") or os.path.join(project_dir, "ai_workflow_results.html"), "外部 AI 生成结果回填到镜头、资产、动作或附件的登记记录"),
        link_row("AI 结果回填 CSV", metadata.get("ai_workflow_results_csv_path") or os.path.join(project_dir, "ai_workflow_results.csv"), "用于核对 AI 输出文件、任务归属和回填去向"),
        link_row("重定向质量报告", metadata.get("retarget_summary_report_path") or os.path.join(project_dir, "retarget_summary.html"), "跨骨骼动作适配、Rest Pose、根运动和动作片段质量"),
        link_row("重定向质量 CSV", metadata.get("retarget_summary_csv_path") or os.path.join(project_dir, "retarget_summary.csv"), "用于动画质检和动作资产复核"),
        link_row("交付检查", metadata.get("delivery_audit_report_path") or os.path.join(project_dir, "delivery_audit.html"), "缺失文件与未渲染镜头检查"),
        link_row("最近交付包", metadata.get("delivery_package_path"), str(metadata.get("delivery_package_created_at") or "")),
    ]
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 工程总览</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 24px 0 10px; font-size: 18px; }}
    .meta, .muted {{ color: #96a3b7; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; }}
    .stat strong {{ display: block; font-size: 22px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    a {{ color: #7dc4ff; text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 工程总览</h1>
    <div class="meta">{escape(summarize_blender_director_metadata(metadata))} · 更新于 {escape(updated_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{int(production.get('shot_count') or 0)}</strong>镜头</div>
      <div class="stat"><strong>{int(queue.get('rendered_count') or 0)}</strong>已渲染</div>
      <div class="stat"><strong>{int(queue.get('pending_count') or 0)}</strong>待渲染</div>
      <div class="stat"><strong>{int(batch_render_jobs.get('ready_count') or 0)}</strong>可批量渲染</div>
      <div class="stat"><strong>{int(batch_render_command.get('ready_count') or 0)}</strong>后台任务</div>
      <div class="stat"><strong>{int(render_versions.get('render_count') or 0)}</strong>版本记录</div>
      <div class="stat"><strong>{int(production.get('approved_shot_count') or 0)}</strong>已定稿</div>
      <div class="stat"><strong>{int(scene_breakdown.get('scene_count') or 0)}</strong>场次</div>
      <div class="stat"><strong>{int(episode_delivery.get('episode_count') or 0)}</strong>分集</div>
      <div class="stat"><strong>{int(scene_breakdown.get('unassigned_shot_count') or 0)}</strong>未分场镜头</div>
      <div class="stat"><strong>{int(call_sheet.get('pending_shot_count') or 0)}</strong>拍摄单待渲染</div>
      <div class="stat"><strong>{int(actor_schedule.get('actor_count') or 0)}</strong>演员/角色</div>
      <div class="stat"><strong>{int(actor_schedule.get('unassigned_shot_count') or 0)}</strong>未绑定演员镜头</div>
      <div class="stat"><strong>{float(duration.get('total_seconds') or 0):.1f}</strong>估算秒数</div>
      <div class="stat"><strong>{float(edit_timeline.get('total_seconds') or 0):.1f}</strong>剪辑秒数</div>
      <div class="stat"><strong>{int(post_handoff.get('layered_count') or 0)}</strong>分层镜头</div>
      <div class="stat"><strong>{int(post_handoff.get('missing_file_shot_count') or 0)}</strong>交接缺文件</div>
      <div class="stat"><strong>{int(continuity_check.get('issue_count') or 0)}</strong>连续性问题</div>
      <div class="stat"><strong>{int(production_check.get('error_count') or 0)}</strong>制作错误</div>
      <div class="stat"><strong>{int(production_check.get('warning_count') or 0)}</strong>制作提醒</div>
      <div class="stat"><strong>{int(asset_requirements.get('missing_count') or 0)}</strong>缺素材</div>
      <div class="stat"><strong>{int(asset_requirements.get('missing_with_candidate_count') or 0)}</strong>缺项有候选</div>
      <div class="stat"><strong>{int(asset_ecosystem.get('library_item_count') or 0)}</strong>库资产</div>
      <div class="stat"><strong>{int(asset_ecosystem.get('asset_browser_catalog_count') or 0)}</strong>Blender Catalog</div>
      <div class="stat"><strong>{int(asset_ecosystem.get('controllable_asset_count') or 0)}</strong>可控工程资产</div>
      <div class="stat"><strong>{int(asset_ecosystem.get('missing_file_count') or 0)}</strong>资产库缺文件</div>
      <div class="stat"><strong>{int(asset_ecosystem.get('missing_license_count') or 0)}</strong>缺授权来源</div>
      <div class="stat"><strong>{int(asset_preflight.get('blocked_count') or 0)}</strong>导入阻断</div>
      <div class="stat"><strong>{int(asset_preflight.get('review_count') or 0)}</strong>导入需复核</div>
      <div class="stat"><strong>{int(action_matches.get('matched_count') or 0)}</strong>动作已匹配</div>
      <div class="stat"><strong>{int(action_matches.get('unmatched_count') or 0)}</strong>待补动作</div>
      <div class="stat"><strong>{int(ai_workflow_tasks.get('task_count') or 0)}</strong>AI工作流任务</div>
      <div class="stat"><strong>{int(ai_workflow_tasks.get('ready_count') or 0)}</strong>AI任务可执行</div>
      <div class="stat"><strong>{int(ai_workflow_handoff.get('result_inbox_count') or 0)}</strong>AI结果收件箱</div>
      <div class="stat"><strong>{int(ai_workflow_results.get('result_count') or 0)}</strong>AI结果回填</div>
      <div class="stat"><strong>{int(ai_workflow_results.get('missing_file_count') or 0)}</strong>AI结果缺文件</div>
      <div class="stat"><strong>{int(retarget_summary.get('ready_clip_count') or 0)}</strong>重定向动作片段</div>
      <div class="stat"><strong>{int(retarget_summary.get('rest_pose_mismatch_bone_count') or 0)}</strong>Rest Pose 差异骨骼</div>
      <div class="stat"><strong>{int(retarget_summary.get('failure_count') or 0)}</strong>重定向失败</div>
      <div class="stat"><strong>{int(duration.get('total_frames') or 0)}</strong>总帧数</div>
      <div class="stat"><strong>{int(production.get('asset_count') or 0)}</strong>工程资产</div>
      <div class="stat"><strong>{int(production.get('unused_asset_count') or 0)}</strong>未使用资产</div>
    </div>
    <h2>制作文件</h2>
    <table>
      <thead><tr><th>文件</th><th>打开</th><th>用途</th></tr></thead>
      <tbody>{''.join(links)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "project_dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def build_blender_director_delivery_audit(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    production = build_blender_director_production_manifest(metadata)
    missing_files = []
    warnings = []

    def add_missing(kind, label, path):
        path = str(path or "").strip()
        if not path:
            return
        if not os.path.exists(path):
            missing_files.append({"kind": kind, "label": str(label or ""), "path": path})

    add_missing("工程", "Blender 工程文件", metadata.get("blend_path"))
    assets = metadata.get("assets") if isinstance(metadata.get("assets"), list) else []
    for index, asset in enumerate(assets, 1):
        if not isinstance(asset, dict):
            continue
        label = str(asset.get("name") or asset.get("file_name") or asset.get("id") or f"资产{index}")
        add_missing("资产", label, asset.get("path"))

    renders = metadata.get("renders") if isinstance(metadata.get("renders"), list) else []
    for index, render in enumerate(renders, 1):
        if not isinstance(render, dict):
            continue
        label = str(render.get("shot_name") or render.get("shot_id") or f"输出{index}")
        for key, key_label in (
            ("path", "输出文件"),
            ("preview_path", "预览图"),
            ("output_path", "输出目录/文件"),
            ("manifest_path", "分层清单"),
        ):
            add_missing("渲染", f"{label} {key_label}", render.get(key))
        layer_paths = render.get("layer_paths") if isinstance(render.get("layer_paths"), dict) else {}
        for layer_name, layer_path in layer_paths.items():
            add_missing("分层素材", f"{label} {layer_name}", layer_path)

    pending_shots = []
    unapproved_shots = []
    shots_without_assets = []
    shots_without_actors = []
    for shot in production.get("shots", []):
        if not isinstance(shot, dict):
            continue
        shot_name = str(shot.get("shot_name") or shot.get("shot_id") or "未命名镜头")
        if not shot.get("rendered"):
            pending_shots.append(
                {
                    "shot_id": str(shot.get("shot_id") or ""),
                    "shot_name": shot_name,
                    "status": str(shot.get("shot_status_label") or shot.get("shot_status") or ""),
                }
            )
        if str(shot.get("shot_status") or "") != "approved" and str(shot.get("shot_status_label") or "") != "已定稿":
            unapproved_shots.append(
                {
                    "shot_id": str(shot.get("shot_id") or ""),
                    "shot_name": shot_name,
                    "status": str(shot.get("shot_status_label") or shot.get("shot_status") or ""),
                }
            )
        if int(shot.get("asset_count") or 0) <= 0:
            shots_without_assets.append({"shot_id": str(shot.get("shot_id") or ""), "shot_name": shot_name})

    storyboard = build_blender_director_storyboard(metadata)
    for entry in storyboard:
        if not isinstance(entry, dict):
            continue
        actors = entry.get("actors") if isinstance(entry.get("actors"), list) else []
        if not actors:
            shots_without_actors.append(
                {
                    "shot_id": str(entry.get("shot_id") or ""),
                    "shot_name": str(entry.get("shot_name") or entry.get("shot_id") or "未命名镜头"),
                }
            )

    if production.get("unused_asset_count"):
        warnings.append(f"有 {int(production.get('unused_asset_count') or 0)} 个工程资产尚未被任何镜头引用。")
    if shots_without_assets:
        warnings.append(f"有 {len(shots_without_assets)} 个镜头没有记录资产依赖。")
    if shots_without_actors:
        warnings.append(f"有 {len(shots_without_actors)} 个镜头没有记录演员。")
    if unapproved_shots:
        warnings.append(f"有 {len(unapproved_shots)} 个镜头还不是已定稿状态。")

    return {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ready_for_delivery": not missing_files and not pending_shots,
        "blocking_issue_count": len(missing_files) + len(pending_shots),
        "warning_count": len(warnings),
        "missing_files": missing_files,
        "pending_shots": pending_shots,
        "unapproved_shots": unapproved_shots,
        "shots_without_assets": shots_without_assets,
        "shots_without_actors": shots_without_actors,
        "warnings": warnings,
        "production": production,
    }


def write_blender_director_delivery_audit(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "delivery_audit.json")
    data = build_blender_director_delivery_audit(metadata)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_blender_director_delivery_audit_report(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    os.makedirs(project_dir, exist_ok=True)
    audit = build_blender_director_delivery_audit(metadata)
    project_name = str(audit.get("project_name") or "Blender 导演台工程")
    status_text = "可交付" if audit.get("ready_for_delivery") else "需处理"

    def rows(items, columns, empty_text):
        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            out.append(
                "<tr>"
                + "".join(f"<td>{escape(str(item.get(column) or ''))}</td>" for column in columns)
                + "</tr>"
            )
        if not out:
            out.append(f'<tr><td colspan="{len(columns)}" class="empty">{escape(empty_text)}</td></tr>')
        return "".join(out)

    warning_rows = "".join(f"<li>{escape(str(item))}</li>" for item in audit.get("warnings", []) if str(item).strip())
    if not warning_rows:
        warning_rows = '<li class="empty">暂无提醒</li>'
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 交付检查</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin: 22px 0 10px; font-size: 18px; }}
    .meta, .empty {{ color: #96a3b7; }}
    .status {{ display: inline-block; margin: 12px 0; padding: 8px 12px; border-radius: 8px; background: #17202d; border: 1px solid #2d3440; }}
    .bad {{ color: #ff9f9f; }}
    .ok {{ color: #86efac; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
    ul {{ background: #151a22; border: 1px solid #2d3440; padding: 14px 18px 14px 28px; }}
    li {{ margin: 6px 0; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 交付检查</h1>
    <div class="meta">更新于 {escape(str(audit.get('updated_at') or ''))}</div>
    <div class="status {'ok' if audit.get('ready_for_delivery') else 'bad'}">{escape(status_text)} · 阻断项 {int(audit.get('blocking_issue_count') or 0)} 个 · 提醒 {int(audit.get('warning_count') or 0)} 个</div>

    <h2>缺失文件</h2>
    <table>
      <thead><tr><th>类型</th><th>名称</th><th>路径</th></tr></thead>
      <tbody>{rows(audit.get('missing_files', []), ('kind', 'label', 'path'), '没有发现缺失文件')}</tbody>
    </table>

    <h2>未渲染镜头</h2>
    <table>
      <thead><tr><th>镜头ID</th><th>镜头</th><th>状态</th></tr></thead>
      <tbody>{rows(audit.get('pending_shots', []), ('shot_id', 'shot_name', 'status'), '没有未渲染镜头')}</tbody>
    </table>

    <h2>提醒</h2>
    <ul>{warning_rows}</ul>
  </main>
</body>
</html>
"""
    path = os.path.join(project_dir, "delivery_audit.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _delivery_archive_name(path, project_dir):
    path = str(path or "").strip()
    if not path:
        return ""
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception:
        return ""
    project_root = None
    if project_dir:
        try:
            project_root = Path(project_dir).expanduser().resolve()
        except Exception:
            project_root = None
    if project_root:
        try:
            rel = resolved.relative_to(project_root)
            return str(rel).replace(os.sep, "/")
        except Exception:
            pass
    digest = hashlib.sha1(str(resolved).encode("utf-8", errors="ignore")).hexdigest()[:10]
    name = _safe_name(resolved.name or "external_file", "external_file")
    return f"external_files/{digest}_{name}"


def write_blender_director_episode_delivery_packages(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return {}
    if not isinstance(metadata, dict):
        metadata = {}
    os.makedirs(project_dir, exist_ok=True)
    episode_data = build_blender_director_episode_delivery(metadata)
    storyboard = build_blender_director_storyboard(metadata)
    storyboard_by_id = {
        str(item.get("shot_id") or ""): item
        for item in storyboard
        if isinstance(item, dict) and str(item.get("shot_id") or "").strip()
    }
    package_dir = os.path.join(project_dir, "delivery_packages", "episodes")
    os.makedirs(package_dir, exist_ok=True)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    delivery_real = os.path.realpath(os.path.join(project_dir, "delivery_packages"))

    asset_lookup = {}
    for asset in metadata.get("assets", []) if isinstance(metadata.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        for key in (str(asset.get("id") or "").strip(), str(asset.get("name") or asset.get("file_name") or "").strip()):
            if key and key not in asset_lookup:
                asset_lookup[key] = asset

    def add_file(zf, included, added, file_path):
        file_path = str(file_path or "").strip()
        if not file_path or not os.path.isfile(file_path):
            return
        real = os.path.realpath(file_path)
        if real in added:
            return
        archive_name = _delivery_archive_name(file_path, project_dir)
        if not archive_name:
            return
        zf.write(file_path, archive_name)
        added.add(real)
        included.append(archive_name)

    def add_path(zf, included, added, path):
        path = str(path or "").strip()
        if not path or not os.path.exists(path):
            return
        if os.path.isfile(path):
            add_file(zf, included, added, path)
            return
        if not os.path.isdir(path):
            return
        root_real = os.path.realpath(path)
        if root_real == delivery_real:
            return
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(
                d
                for d in dirs
                if os.path.realpath(os.path.join(root, d)) != delivery_real
                and d not in {"__pycache__"}
            )
            for name in sorted(files):
                if name == ".DS_Store":
                    continue
                add_file(zf, included, added, os.path.join(root, name))

    package_rows = []
    for index, episode in enumerate(episode_data.get("episodes", []), 1):
        if not isinstance(episode, dict):
            continue
        episode_number = str(episode.get("episode_number") or f"episode_{index:02d}").strip()
        episode_name = str(episode.get("episode_name") or "").strip()
        base_name = _safe_name("_".join(part for part in (episode_number, episode_name) if part), f"episode_{index:02d}")
        package_path = os.path.join(package_dir, f"{base_name}.zip")
        shot_ids = []
        for scene in episode.get("scenes", []) if isinstance(episode.get("scenes"), list) else []:
            if not isinstance(scene, dict):
                continue
            for shot in scene.get("shots", []) if isinstance(scene.get("shots"), list) else []:
                if not isinstance(shot, dict):
                    continue
                shot_id = str(shot.get("shot_id") or "").strip()
                if shot_id:
                    shot_ids.append(shot_id)
        included_files = []
        added_paths = set()
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            episode_manifest = {
                "project_id": str(metadata.get("project_id") or ""),
                "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
                "created_at": created_at,
                "episode": episode,
                "shot_ids": shot_ids,
            }
            zf.writestr("episode_manifest.json", json.dumps(episode_manifest, ensure_ascii=False, indent=2))
            rows = [["分集", "分集名", "场次", "地点", "镜头ID", "镜头名", "渲染", "帧段"]]
            for scene in episode.get("scenes", []) if isinstance(episode.get("scenes"), list) else []:
                if not isinstance(scene, dict):
                    continue
                for shot in scene.get("shots", []) if isinstance(scene.get("shots"), list) else []:
                    if not isinstance(shot, dict):
                        continue
                    frame_text = ""
                    if shot.get("frame_start") is not None and shot.get("frame_end") is not None:
                        frame_text = f"{shot.get('frame_start')}-{shot.get('frame_end')}"
                    rows.append(
                        [
                            episode_number,
                            episode_name,
                            scene.get("scene_number") or "",
                            scene.get("scene_location") or "",
                            shot.get("shot_id") or "",
                            shot.get("shot_name") or "",
                            shot.get("queue_status_label") or "",
                            frame_text,
                        ]
                    )
            csv_text = "\n".join(",".join('"' + str(cell).replace('"', '""') + '"' for cell in row) for row in rows)
            zf.writestr("episode_delivery.csv", "\ufeff" + csv_text)
            for shot_id in shot_ids:
                item = storyboard_by_id.get(shot_id, {})
                if not isinstance(item, dict):
                    continue
                for key in ("preview_path", "output_path", "manifest_path"):
                    add_path(zf, included_files, added_paths, item.get(key))
                layer_paths = item.get("layer_paths") if isinstance(item.get("layer_paths"), dict) else {}
                for layer_path in layer_paths.values():
                    add_path(zf, included_files, added_paths, layer_path)
            for asset in episode.get("assets", []) if isinstance(episode.get("assets"), list) else []:
                if not isinstance(asset, dict):
                    continue
                asset_record = asset_lookup.get(str(asset.get("id") or "").strip()) or asset_lookup.get(str(asset.get("name") or "").strip()) or {}
                if isinstance(asset_record, dict):
                    add_path(zf, included_files, added_paths, asset_record.get("path"))
        package_rows.append(
            {
                "episode_number": episode_number,
                "episode_name": episode_name,
                "shot_count": int(episode.get("shot_count") or 0),
                "rendered_shot_count": int(episode.get("rendered_shot_count") or 0),
                "pending_shot_count": int(episode.get("pending_shot_count") or 0),
                "total_frames": int(episode.get("total_frames") or 0),
                "package_path": package_path,
                "archive_name": _delivery_archive_name(package_path, project_dir),
                "included_file_count": len(included_files),
                "included_files": included_files,
            }
        )

    index_data = {
        "project_id": str(metadata.get("project_id") or ""),
        "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
        "created_at": created_at,
        "episode_count": len(package_rows),
        "packages": package_rows,
    }
    index_path = os.path.join(project_dir, "episode_delivery_packages.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    csv_path = os.path.join(project_dir, "episode_delivery_packages.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["分集", "分集名", "镜头数", "已渲染", "待渲染", "总帧数", "文件数", "交付包"])
        for item in package_rows:
            writer.writerow(
                [
                    item.get("episode_number") or "",
                    item.get("episode_name") or "",
                    item.get("shot_count") or 0,
                    item.get("rendered_shot_count") or 0,
                    item.get("pending_shot_count") or 0,
                    item.get("total_frames") or 0,
                    item.get("included_file_count") or 0,
                    item.get("package_path") or "",
                ]
            )
    rows_html = []
    for item in package_rows:
        rows_html.append(
            "<tr>"
            f"<td>{escape(str(item.get('episode_number') or ''))}</td>"
            f"<td>{escape(str(item.get('episode_name') or ''))}</td>"
            f"<td>{int(item.get('shot_count') or 0)}</td>"
            f"<td>{int(item.get('rendered_shot_count') or 0)}</td>"
            f"<td>{int(item.get('pending_shot_count') or 0)}</td>"
            f"<td>{int(item.get('included_file_count') or 0)}</td>"
            f"<td>{escape(str(item.get('package_path') or ''))}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html.append('<tr><td colspan="7" class="empty">暂无分集交付包。</td></tr>')
    project_name = str(index_data.get("project_name") or "Blender 导演台工程")
    report_path = os.path.join(project_dir, "episode_delivery_packages.html")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(project_name)} - 分集交付包</title>
  <style>
    body {{ margin: 0; background: #0f1218; color: #e8edf5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ padding: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    .meta, .empty {{ color: #96a3b7; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0; }}
    .stat {{ background: #151a22; border: 1px solid #2d3440; border-radius: 8px; padding: 10px 12px; min-width: 120px; }}
    .stat strong {{ display: block; font-size: 20px; color: #ffffff; }}
    table {{ width: 100%; border-collapse: collapse; background: #151a22; border: 1px solid #2d3440; }}
    th, td {{ border-bottom: 1px solid #2d3440; padding: 10px; vertical-align: top; text-align: left; }}
    th {{ color: #b9c6d8; background: #1d2430; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(project_name)} - 分集交付包</h1>
    <div class="meta">生成于 {escape(created_at)}</div>
    <div class="stats">
      <div class="stat"><strong>{len(package_rows)}</strong>分集包</div>
    </div>
    <table>
      <thead><tr><th>分集</th><th>分集名</th><th>镜头</th><th>已渲染</th><th>待渲染</th><th>文件数</th><th>交付包</th></tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>
  </main>
</body>
</html>
"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    index_data["manifest_path"] = index_path
    index_data["report_path"] = report_path
    index_data["csv_path"] = csv_path
    return index_data


def write_blender_director_delivery_package(metadata):
    project_dir = _storyboard_project_dir(metadata)
    if not project_dir:
        return ""
    if not isinstance(metadata, dict):
        metadata = {}
    os.makedirs(project_dir, exist_ok=True)
    storyboard_manifest_path = write_blender_director_storyboard_manifest(metadata)
    storyboard_report_path = write_blender_director_storyboard_report(metadata)
    storyboard_csv_path = write_blender_director_storyboard_csv(metadata)
    render_queue_manifest_path = write_blender_director_render_queue_manifest(metadata)
    render_queue_report_path = write_blender_director_render_queue_report(metadata)
    render_queue_csv_path = write_blender_director_render_queue_csv(metadata)
    batch_render_jobs_manifest_path = write_blender_director_batch_render_jobs_manifest(metadata)
    batch_render_jobs_report_path = write_blender_director_batch_render_jobs_report(metadata)
    batch_render_jobs_csv_path = write_blender_director_batch_render_jobs_csv(metadata)
    batch_render_command = write_blender_director_batch_render_command(metadata)
    render_versions_manifest_path = write_blender_director_render_versions_manifest(metadata)
    render_versions_report_path = write_blender_director_render_versions_report(metadata)
    render_versions_csv_path = write_blender_director_render_versions_csv(metadata)
    scene_breakdown_manifest_path = write_blender_director_scene_breakdown_manifest(metadata)
    scene_breakdown_report_path = write_blender_director_scene_breakdown_report(metadata)
    scene_breakdown_csv_path = write_blender_director_scene_breakdown_csv(metadata)
    episode_delivery_manifest_path = write_blender_director_episode_delivery_manifest(metadata)
    episode_delivery_report_path = write_blender_director_episode_delivery_report(metadata)
    episode_delivery_csv_path = write_blender_director_episode_delivery_csv(metadata)
    episode_delivery_packages = write_blender_director_episode_delivery_packages(metadata)
    call_sheet_manifest_path = write_blender_director_call_sheet_manifest(metadata)
    call_sheet_report_path = write_blender_director_call_sheet_report(metadata)
    call_sheet_csv_path = write_blender_director_call_sheet_csv(metadata)
    actor_schedule_manifest_path = write_blender_director_actor_schedule_manifest(metadata)
    actor_schedule_report_path = write_blender_director_actor_schedule_report(metadata)
    actor_schedule_csv_path = write_blender_director_actor_schedule_csv(metadata)
    edit_timeline_manifest_path = write_blender_director_edit_timeline_manifest(metadata)
    edit_timeline_report_path = write_blender_director_edit_timeline_report(metadata)
    edit_timeline_csv_path = write_blender_director_edit_timeline_csv(metadata)
    edit_timeline_edl_path = write_blender_director_edit_decision_list(metadata)
    edit_timeline_fcpxml_path = write_blender_director_final_cut_xml(metadata)
    post_handoff_manifest_path = write_blender_director_post_handoff_manifest(metadata)
    post_handoff_report_path = write_blender_director_post_handoff_report(metadata)
    post_handoff_csv_path = write_blender_director_post_handoff_csv(metadata)
    continuity_check_manifest_path = write_blender_director_continuity_check_manifest(metadata)
    continuity_check_report_path = write_blender_director_continuity_check_report(metadata)
    continuity_check_csv_path = write_blender_director_continuity_check_csv(metadata)
    production_check_manifest_path = write_blender_director_production_check_manifest(metadata)
    production_check_report_path = write_blender_director_production_check_report(metadata)
    production_check_csv_path = write_blender_director_production_check_csv(metadata)
    duration_summary_path = write_blender_director_duration_summary(metadata)
    production_manifest_path = write_blender_director_production_manifest(metadata)
    production_report_path = write_blender_director_production_report(metadata)
    asset_usage_csv_path = write_blender_director_asset_usage_csv(metadata)
    asset_requirements_manifest_path = write_blender_director_asset_requirements_manifest(metadata)
    asset_requirements_report_path = write_blender_director_asset_requirements_report(metadata)
    asset_requirements_csv_path = write_blender_director_asset_requirements_csv(metadata)
    asset_ecosystem_manifest_path = write_blender_director_asset_ecosystem_manifest(metadata)
    asset_ecosystem_report_path = write_blender_director_asset_ecosystem_report(metadata)
    asset_ecosystem_csv_path = write_blender_director_asset_ecosystem_csv(metadata)
    asset_preflight_manifest_path = write_blender_director_asset_preflight_manifest(metadata)
    asset_preflight_report_path = write_blender_director_asset_preflight_report(metadata)
    asset_preflight_csv_path = write_blender_director_asset_preflight_csv(metadata)
    action_matches_manifest_path = write_blender_director_action_matches_manifest(metadata)
    action_matches_report_path = write_blender_director_action_matches_report(metadata)
    action_matches_csv_path = write_blender_director_action_matches_csv(metadata)
    ai_workflow_tasks_manifest_path = write_blender_director_ai_workflow_tasks_manifest(metadata)
    ai_workflow_tasks_report_path = write_blender_director_ai_workflow_tasks_report(metadata)
    ai_workflow_tasks_csv_path = write_blender_director_ai_workflow_tasks_csv(metadata)
    ai_workflow_handoff = write_blender_director_ai_workflow_handoff_package(metadata)
    ai_workflow_results_manifest_path = write_blender_director_ai_workflow_results_manifest(metadata)
    ai_workflow_results_report_path = write_blender_director_ai_workflow_results_report(metadata)
    ai_workflow_results_csv_path = write_blender_director_ai_workflow_results_csv(metadata)
    retarget_summary_manifest_path = write_blender_director_retarget_summary_manifest(metadata)
    retarget_summary_report_path = write_blender_director_retarget_summary_report(metadata)
    retarget_summary_csv_path = write_blender_director_retarget_summary_csv(metadata)
    delivery_audit_path = write_blender_director_delivery_audit(metadata)
    delivery_audit_report_path = write_blender_director_delivery_audit_report(metadata)

    metadata["storyboard_manifest_path"] = storyboard_manifest_path
    metadata["storyboard_report_path"] = storyboard_report_path
    metadata["storyboard_csv_path"] = storyboard_csv_path
    metadata["render_queue_manifest_path"] = render_queue_manifest_path
    metadata["render_queue_report_path"] = render_queue_report_path
    metadata["render_queue_csv_path"] = render_queue_csv_path
    metadata["batch_render_jobs_manifest_path"] = batch_render_jobs_manifest_path
    metadata["batch_render_jobs_report_path"] = batch_render_jobs_report_path
    metadata["batch_render_jobs_csv_path"] = batch_render_jobs_csv_path
    metadata["batch_render_script_path"] = batch_render_command.get("script_path") or metadata.get("batch_render_script_path", "")
    metadata["batch_render_command_path"] = batch_render_command.get("command_path") or metadata.get("batch_render_command_path", "")
    metadata["batch_render_command_report_path"] = batch_render_command.get("report_path") or metadata.get("batch_render_command_report_path", "")
    metadata["render_versions_manifest_path"] = render_versions_manifest_path
    metadata["render_versions_report_path"] = render_versions_report_path
    metadata["render_versions_csv_path"] = render_versions_csv_path
    metadata["scene_breakdown_manifest_path"] = scene_breakdown_manifest_path
    metadata["scene_breakdown_report_path"] = scene_breakdown_report_path
    metadata["scene_breakdown_csv_path"] = scene_breakdown_csv_path
    metadata["episode_delivery_manifest_path"] = episode_delivery_manifest_path
    metadata["episode_delivery_report_path"] = episode_delivery_report_path
    metadata["episode_delivery_csv_path"] = episode_delivery_csv_path
    metadata["episode_delivery_packages_manifest_path"] = episode_delivery_packages.get("manifest_path") or ""
    metadata["episode_delivery_packages_report_path"] = episode_delivery_packages.get("report_path") or ""
    metadata["episode_delivery_packages_csv_path"] = episode_delivery_packages.get("csv_path") or ""
    metadata["episode_delivery_packages"] = episode_delivery_packages.get("packages") or []
    metadata["call_sheet_manifest_path"] = call_sheet_manifest_path
    metadata["call_sheet_report_path"] = call_sheet_report_path
    metadata["call_sheet_csv_path"] = call_sheet_csv_path
    metadata["actor_schedule_manifest_path"] = actor_schedule_manifest_path
    metadata["actor_schedule_report_path"] = actor_schedule_report_path
    metadata["actor_schedule_csv_path"] = actor_schedule_csv_path
    metadata["edit_timeline_manifest_path"] = edit_timeline_manifest_path
    metadata["edit_timeline_report_path"] = edit_timeline_report_path
    metadata["edit_timeline_csv_path"] = edit_timeline_csv_path
    metadata["edit_timeline_edl_path"] = edit_timeline_edl_path
    metadata["edit_timeline_fcpxml_path"] = edit_timeline_fcpxml_path
    metadata["post_handoff_manifest_path"] = post_handoff_manifest_path
    metadata["post_handoff_report_path"] = post_handoff_report_path
    metadata["post_handoff_csv_path"] = post_handoff_csv_path
    metadata["continuity_check_manifest_path"] = continuity_check_manifest_path
    metadata["continuity_check_report_path"] = continuity_check_report_path
    metadata["continuity_check_csv_path"] = continuity_check_csv_path
    metadata["production_check_manifest_path"] = production_check_manifest_path
    metadata["production_check_report_path"] = production_check_report_path
    metadata["production_check_csv_path"] = production_check_csv_path
    metadata["duration_summary_path"] = duration_summary_path
    metadata["production_manifest_path"] = production_manifest_path
    metadata["production_report_path"] = production_report_path
    metadata["asset_usage_csv_path"] = asset_usage_csv_path
    metadata["asset_requirements_manifest_path"] = asset_requirements_manifest_path
    metadata["asset_requirements_report_path"] = asset_requirements_report_path
    metadata["asset_requirements_csv_path"] = asset_requirements_csv_path
    metadata["asset_ecosystem_manifest_path"] = asset_ecosystem_manifest_path
    metadata["asset_ecosystem_report_path"] = asset_ecosystem_report_path
    metadata["asset_ecosystem_csv_path"] = asset_ecosystem_csv_path
    metadata["asset_preflight_manifest_path"] = asset_preflight_manifest_path
    metadata["asset_preflight_report_path"] = asset_preflight_report_path
    metadata["asset_preflight_csv_path"] = asset_preflight_csv_path
    metadata["action_matches_manifest_path"] = action_matches_manifest_path
    metadata["action_matches_report_path"] = action_matches_report_path
    metadata["action_matches_csv_path"] = action_matches_csv_path
    metadata["ai_workflow_tasks_manifest_path"] = ai_workflow_tasks_manifest_path
    metadata["ai_workflow_tasks_report_path"] = ai_workflow_tasks_report_path
    metadata["ai_workflow_tasks_csv_path"] = ai_workflow_tasks_csv_path
    metadata["ai_workflow_handoff_dir"] = ai_workflow_handoff.get("handoff_dir") or ""
    metadata["ai_workflow_handoff_manifest_path"] = ai_workflow_handoff.get("manifest_path") or ""
    metadata["ai_workflow_handoff_report_path"] = ai_workflow_handoff.get("report_path") or ""
    metadata["ai_workflow_handoff_csv_path"] = ai_workflow_handoff.get("csv_path") or ""
    metadata["ai_workflow_handoff_readme_path"] = ai_workflow_handoff.get("readme_path") or ""
    metadata["ai_workflow_results_manifest_path"] = ai_workflow_results_manifest_path
    metadata["ai_workflow_results_report_path"] = ai_workflow_results_report_path
    metadata["ai_workflow_results_csv_path"] = ai_workflow_results_csv_path
    metadata["retarget_summary_manifest_path"] = retarget_summary_manifest_path
    metadata["retarget_summary_report_path"] = retarget_summary_report_path
    metadata["retarget_summary_csv_path"] = retarget_summary_csv_path
    metadata["delivery_audit_path"] = delivery_audit_path
    metadata["delivery_audit_report_path"] = delivery_audit_report_path

    package_dir = os.path.join(project_dir, "delivery_packages")
    os.makedirs(package_dir, exist_ok=True)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name = str(metadata.get("project_name") or "Blender导演台工程")
    package_path = os.path.join(package_dir, f"{_safe_name(project_name, 'blender_director')}_{stamp}.zip")
    metadata["delivery_package_path"] = package_path
    metadata["delivery_package_created_at"] = created_at
    project_dashboard_path = write_blender_director_project_dashboard(metadata)
    metadata["project_dashboard_path"] = project_dashboard_path
    asset_ecosystem = build_blender_director_asset_ecosystem(metadata)
    asset_preflight = build_blender_director_asset_preflight(metadata)
    ai_workflow_tasks = build_blender_director_ai_workflow_tasks(metadata)
    ai_workflow_results = build_blender_director_ai_workflow_results(metadata)
    retarget_summary = build_blender_director_retarget_summary(metadata)
    metadata["ai_workflow_tasks"] = ai_workflow_tasks
    metadata["ai_workflow_results_summary"] = {
        "result_count": int(ai_workflow_results.get("result_count") or 0),
        "file_exists_count": int(ai_workflow_results.get("file_exists_count") or 0),
        "missing_file_count": int(ai_workflow_results.get("missing_file_count") or 0),
        "render_count": int(ai_workflow_results.get("render_count") or 0),
        "asset_count": int(ai_workflow_results.get("asset_count") or 0),
        "attachment_count": int(ai_workflow_results.get("attachment_count") or 0),
    }
    metadata["retarget_summary"] = retarget_summary

    meta_path = str(metadata.get("meta_path") or "").strip()
    if not meta_path:
        meta_path = os.path.join(project_dir, "director_project.json")
        metadata["meta_path"] = meta_path
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    package_real = os.path.realpath(package_path)
    delivery_real = os.path.realpath(package_dir)
    added_paths = set()
    added_names = set()
    included_files = []

    def add_file(zf, file_path):
        file_path = str(file_path or "").strip()
        if not file_path or not os.path.isfile(file_path):
            return
        real = os.path.realpath(file_path)
        if real == package_real or real in added_paths:
            return
        archive_name = _delivery_archive_name(file_path, project_dir)
        if not archive_name or archive_name in added_names:
            return
        zf.write(file_path, archive_name)
        added_paths.add(real)
        added_names.add(archive_name)
        included_files.append(archive_name)

    def add_path(zf, path):
        path = str(path or "").strip()
        if not path or not os.path.exists(path):
            return
        if os.path.isfile(path):
            add_file(zf, path)
            return
        if not os.path.isdir(path):
            return
        root_real = os.path.realpath(path)
        if root_real == delivery_real:
            return
        for root, dirs, files in os.walk(path):
            root_walk_real = os.path.realpath(root)
            dirs[:] = sorted(
                d
                for d in dirs
                if os.path.realpath(os.path.join(root, d)) != delivery_real
                and d not in {"__pycache__"}
            )
            for name in sorted(files):
                if name == ".DS_Store":
                    continue
                add_file(zf, os.path.join(root, name))

    base_paths = [
        meta_path,
        metadata.get("blend_path"),
        os.path.join(project_dir, "scripts"),
        metadata.get("assets_dir"),
        metadata.get("shots_dir"),
        metadata.get("presets_dir"),
        metadata.get("set_packages_dir"),
        metadata.get("renders_dir"),
        storyboard_manifest_path,
        storyboard_report_path,
        storyboard_csv_path,
        render_queue_manifest_path,
        render_queue_report_path,
        render_queue_csv_path,
        batch_render_jobs_manifest_path,
        batch_render_jobs_report_path,
        batch_render_jobs_csv_path,
        batch_render_command.get("script_path"),
        batch_render_command.get("command_path"),
        batch_render_command.get("report_path"),
        render_versions_manifest_path,
        render_versions_report_path,
        render_versions_csv_path,
        scene_breakdown_manifest_path,
        scene_breakdown_report_path,
        scene_breakdown_csv_path,
        episode_delivery_manifest_path,
        episode_delivery_report_path,
        episode_delivery_csv_path,
        episode_delivery_packages.get("manifest_path"),
        episode_delivery_packages.get("report_path"),
        episode_delivery_packages.get("csv_path"),
        call_sheet_manifest_path,
        call_sheet_report_path,
        call_sheet_csv_path,
        actor_schedule_manifest_path,
        actor_schedule_report_path,
        actor_schedule_csv_path,
        edit_timeline_manifest_path,
        edit_timeline_report_path,
        edit_timeline_csv_path,
        edit_timeline_edl_path,
        edit_timeline_fcpxml_path,
        post_handoff_manifest_path,
        post_handoff_report_path,
        post_handoff_csv_path,
        continuity_check_manifest_path,
        continuity_check_report_path,
        continuity_check_csv_path,
        production_check_manifest_path,
        production_check_report_path,
        production_check_csv_path,
        duration_summary_path,
        production_manifest_path,
        production_report_path,
        asset_usage_csv_path,
        asset_requirements_manifest_path,
        asset_requirements_report_path,
        asset_requirements_csv_path,
        asset_ecosystem_manifest_path,
        asset_ecosystem_report_path,
        asset_ecosystem_csv_path,
        asset_preflight_manifest_path,
        asset_preflight_report_path,
        asset_preflight_csv_path,
        action_matches_manifest_path,
        action_matches_report_path,
        action_matches_csv_path,
        ai_workflow_tasks_manifest_path,
        ai_workflow_tasks_report_path,
        ai_workflow_tasks_csv_path,
        ai_workflow_handoff.get("handoff_dir"),
        ai_workflow_handoff.get("manifest_path"),
        ai_workflow_handoff.get("report_path"),
        ai_workflow_handoff.get("csv_path"),
        ai_workflow_handoff.get("readme_path"),
        ai_workflow_results_manifest_path,
        ai_workflow_results_report_path,
        ai_workflow_results_csv_path,
        retarget_summary_manifest_path,
        retarget_summary_report_path,
        retarget_summary_csv_path,
        delivery_audit_path,
        delivery_audit_report_path,
        project_dashboard_path,
    ]
    asset_dirs = metadata.get("asset_dirs") if isinstance(metadata.get("asset_dirs"), dict) else {}
    base_paths.extend(asset_dirs.values())
    for item in episode_delivery_packages.get("packages", []):
        if isinstance(item, dict):
            base_paths.append(item.get("package_path"))
    for collection_name in ("assets", "asset_library_items", "renders", "ai_workflow_results"):
        collection = metadata.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            for key in ("path", "preview_path", "output_path", "manifest_path"):
                base_paths.append(item.get(key))
            texture_paths = item.get("texture_paths") if isinstance(item.get("texture_paths"), list) else []
            base_paths.extend(texture_paths)
            layer_paths = item.get("layer_paths") if isinstance(item.get("layer_paths"), dict) else {}
            base_paths.extend(layer_paths.values())

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in base_paths:
            add_path(zf, path)
        delivery_manifest = {
            "project_id": str(metadata.get("project_id") or ""),
            "project_name": str(metadata.get("project_name") or "Blender 导演台工程"),
            "created_at": created_at,
            "storyboard_report": _delivery_archive_name(storyboard_report_path, project_dir),
            "storyboard_csv": _delivery_archive_name(storyboard_csv_path, project_dir),
            "render_queue_report": _delivery_archive_name(render_queue_report_path, project_dir),
            "render_queue_csv": _delivery_archive_name(render_queue_csv_path, project_dir),
            "batch_render_jobs_report": _delivery_archive_name(batch_render_jobs_report_path, project_dir),
            "batch_render_jobs_csv": _delivery_archive_name(batch_render_jobs_csv_path, project_dir),
            "batch_render_command": _delivery_archive_name(batch_render_command.get("command_path"), project_dir),
            "batch_render_command_report": _delivery_archive_name(batch_render_command.get("report_path"), project_dir),
            "batch_render_script": _delivery_archive_name(batch_render_command.get("script_path"), project_dir),
            "render_versions_report": _delivery_archive_name(render_versions_report_path, project_dir),
            "render_versions_csv": _delivery_archive_name(render_versions_csv_path, project_dir),
            "scene_breakdown_report": _delivery_archive_name(scene_breakdown_report_path, project_dir),
            "scene_breakdown_csv": _delivery_archive_name(scene_breakdown_csv_path, project_dir),
            "episode_delivery_report": _delivery_archive_name(episode_delivery_report_path, project_dir),
            "episode_delivery_csv": _delivery_archive_name(episode_delivery_csv_path, project_dir),
            "episode_delivery_packages_report": _delivery_archive_name(episode_delivery_packages.get("report_path"), project_dir),
            "episode_delivery_packages_csv": _delivery_archive_name(episode_delivery_packages.get("csv_path"), project_dir),
            "call_sheet_report": _delivery_archive_name(call_sheet_report_path, project_dir),
            "call_sheet_csv": _delivery_archive_name(call_sheet_csv_path, project_dir),
            "actor_schedule_report": _delivery_archive_name(actor_schedule_report_path, project_dir),
            "actor_schedule_csv": _delivery_archive_name(actor_schedule_csv_path, project_dir),
            "edit_timeline_report": _delivery_archive_name(edit_timeline_report_path, project_dir),
            "edit_timeline_csv": _delivery_archive_name(edit_timeline_csv_path, project_dir),
            "edit_timeline_edl": _delivery_archive_name(edit_timeline_edl_path, project_dir),
            "edit_timeline_fcpxml": _delivery_archive_name(edit_timeline_fcpxml_path, project_dir),
            "post_handoff_report": _delivery_archive_name(post_handoff_report_path, project_dir),
            "post_handoff_csv": _delivery_archive_name(post_handoff_csv_path, project_dir),
            "continuity_check_report": _delivery_archive_name(continuity_check_report_path, project_dir),
            "continuity_check_csv": _delivery_archive_name(continuity_check_csv_path, project_dir),
            "production_check_report": _delivery_archive_name(production_check_report_path, project_dir),
            "production_check_csv": _delivery_archive_name(production_check_csv_path, project_dir),
            "duration_summary": _delivery_archive_name(duration_summary_path, project_dir),
            "production_report": _delivery_archive_name(production_report_path, project_dir),
            "asset_usage_csv": _delivery_archive_name(asset_usage_csv_path, project_dir),
            "asset_requirements_report": _delivery_archive_name(asset_requirements_report_path, project_dir),
            "asset_requirements_csv": _delivery_archive_name(asset_requirements_csv_path, project_dir),
            "asset_ecosystem_manifest": _delivery_archive_name(asset_ecosystem_manifest_path, project_dir),
            "asset_ecosystem_report": _delivery_archive_name(asset_ecosystem_report_path, project_dir),
            "asset_ecosystem_csv": _delivery_archive_name(asset_ecosystem_csv_path, project_dir),
            "asset_preflight_manifest": _delivery_archive_name(asset_preflight_manifest_path, project_dir),
            "asset_preflight_report": _delivery_archive_name(asset_preflight_report_path, project_dir),
            "asset_preflight_csv": _delivery_archive_name(asset_preflight_csv_path, project_dir),
            "asset_ecosystem": {
                "source_count": int(asset_ecosystem.get("source_count") or 0),
                "library_count": int(asset_ecosystem.get("library_count") or 0),
                "library_item_count": int(asset_ecosystem.get("library_item_count") or 0),
                "available_item_count": int(asset_ecosystem.get("available_item_count") or 0),
                "missing_file_count": int(asset_ecosystem.get("missing_file_count") or 0),
                "missing_license_count": int(asset_ecosystem.get("missing_license_count") or 0),
                "imported_item_count": int(asset_ecosystem.get("imported_item_count") or 0),
                "controllable_asset_count": int(asset_ecosystem.get("controllable_asset_count") or 0),
                "asset_browser_catalog_count": int(asset_ecosystem.get("asset_browser_catalog_count") or 0),
                "ready_action_count": int(asset_ecosystem.get("ready_action_count") or 0),
                "action_item_count": int(asset_ecosystem.get("action_item_count") or 0),
                "health_warnings": asset_ecosystem.get("health_warnings") if isinstance(asset_ecosystem.get("health_warnings"), list) else [],
                "kind_counts": asset_ecosystem.get("kind_counts") if isinstance(asset_ecosystem.get("kind_counts"), list) else [],
            },
            "asset_preflight": {
                "library_item_count": int(asset_preflight.get("library_item_count") or 0),
                "ready_count": int(asset_preflight.get("ready_count") or 0),
                "review_count": int(asset_preflight.get("review_count") or 0),
                "blocked_count": int(asset_preflight.get("blocked_count") or 0),
                "error_count": int(asset_preflight.get("error_count") or 0),
                "warning_count": int(asset_preflight.get("warning_count") or 0),
                "issue_count": int(asset_preflight.get("issue_count") or 0),
            },
            "action_matches_report": _delivery_archive_name(action_matches_report_path, project_dir),
            "action_matches_csv": _delivery_archive_name(action_matches_csv_path, project_dir),
            "ai_workflow_tasks_manifest": _delivery_archive_name(ai_workflow_tasks_manifest_path, project_dir),
            "ai_workflow_tasks_report": _delivery_archive_name(ai_workflow_tasks_report_path, project_dir),
            "ai_workflow_tasks_csv": _delivery_archive_name(ai_workflow_tasks_csv_path, project_dir),
            "ai_workflow_tasks": {
                "task_count": int(ai_workflow_tasks.get("task_count") or 0),
                "ready_count": int(ai_workflow_tasks.get("ready_count") or 0),
                "review_count": int(ai_workflow_tasks.get("review_count") or 0),
                "blocked_count": int(ai_workflow_tasks.get("blocked_count") or 0),
            },
            "ai_workflow_handoff_manifest": _delivery_archive_name(ai_workflow_handoff.get("manifest_path"), project_dir),
            "ai_workflow_handoff_report": _delivery_archive_name(ai_workflow_handoff.get("report_path"), project_dir),
            "ai_workflow_handoff_csv": _delivery_archive_name(ai_workflow_handoff.get("csv_path"), project_dir),
            "ai_workflow_handoff_readme": _delivery_archive_name(ai_workflow_handoff.get("readme_path"), project_dir),
            "ai_workflow_handoff": {
                "task_count": int(ai_workflow_handoff.get("task_count") or 0),
                "ready_count": int(ai_workflow_handoff.get("ready_count") or 0),
                "review_count": int(ai_workflow_handoff.get("review_count") or 0),
                "blocked_count": int(ai_workflow_handoff.get("blocked_count") or 0),
                "result_inbox_count": int(ai_workflow_handoff.get("result_inbox_count") or 0),
            },
            "ai_workflow_results_manifest": _delivery_archive_name(ai_workflow_results_manifest_path, project_dir),
            "ai_workflow_results_report": _delivery_archive_name(ai_workflow_results_report_path, project_dir),
            "ai_workflow_results_csv": _delivery_archive_name(ai_workflow_results_csv_path, project_dir),
            "ai_workflow_results": {
                "result_count": int(ai_workflow_results.get("result_count") or 0),
                "file_exists_count": int(ai_workflow_results.get("file_exists_count") or 0),
                "missing_file_count": int(ai_workflow_results.get("missing_file_count") or 0),
                "render_count": int(ai_workflow_results.get("render_count") or 0),
                "asset_count": int(ai_workflow_results.get("asset_count") or 0),
                "attachment_count": int(ai_workflow_results.get("attachment_count") or 0),
            },
            "retarget_summary_manifest": _delivery_archive_name(retarget_summary_manifest_path, project_dir),
            "retarget_summary_report": _delivery_archive_name(retarget_summary_report_path, project_dir),
            "retarget_summary_csv": _delivery_archive_name(retarget_summary_csv_path, project_dir),
            "retarget_summary": retarget_summary,
            "delivery_audit_report": _delivery_archive_name(delivery_audit_report_path, project_dir),
            "project_dashboard": _delivery_archive_name(project_dashboard_path, project_dir),
            "episode_delivery_packages": [
                _delivery_archive_name(item.get("package_path"), project_dir)
                for item in episode_delivery_packages.get("packages", [])
                if isinstance(item, dict) and item.get("package_path")
            ],
            "file_count": len(included_files),
            "files": included_files,
        }
        zf.writestr("delivery_manifest.json", json.dumps(delivery_manifest, ensure_ascii=False, indent=2))
    return package_path


def summarize_blender_director_metadata(metadata):
    if not isinstance(metadata, dict):
        metadata = {}
    assets = metadata.get("assets") if isinstance(metadata.get("assets"), list) else []
    actors = metadata.get("actors") if isinstance(metadata.get("actors"), list) else []
    asset_sources = metadata.get("asset_sources") if isinstance(metadata.get("asset_sources"), list) else []
    asset_libraries = metadata.get("asset_libraries") if isinstance(metadata.get("asset_libraries"), list) else []
    asset_library_items = (
        metadata.get("asset_library_items") if isinstance(metadata.get("asset_library_items"), list) else []
    )
    shots = metadata.get("shots") if isinstance(metadata.get("shots"), list) else []
    shot_packages = metadata.get("shot_packages") if isinstance(metadata.get("shot_packages"), list) else []
    set_packages = metadata.get("set_packages") if isinstance(metadata.get("set_packages"), list) else []
    renders = metadata.get("renders") if isinstance(metadata.get("renders"), list) else []
    ai_workflow_results = metadata.get("ai_workflow_results") if isinstance(metadata.get("ai_workflow_results"), list) else []
    ai_workflow_results_summary = (
        metadata.get("ai_workflow_results_summary")
        if isinstance(metadata.get("ai_workflow_results_summary"), dict)
        else {}
    )
    render_templates = metadata.get("render_templates") if isinstance(metadata.get("render_templates"), list) else []
    scene_presets = metadata.get("scene_presets") if isinstance(metadata.get("scene_presets"), list) else []
    action_applications = metadata.get("action_applications") if isinstance(metadata.get("action_applications"), list) else []
    action_clips = metadata.get("action_clips") if isinstance(metadata.get("action_clips"), list) else []
    retarget_profiles = metadata.get("retarget_profiles") if isinstance(metadata.get("retarget_profiles"), list) else []
    retarget_applications = metadata.get("retarget_applications") if isinstance(metadata.get("retarget_applications"), list) else []
    pose_templates = metadata.get("pose_templates") if isinstance(metadata.get("pose_templates"), list) else []
    animation_templates = metadata.get("animation_templates") if isinstance(metadata.get("animation_templates"), list) else []
    material_templates = metadata.get("material_templates") if isinstance(metadata.get("material_templates"), list) else []
    material_applications = metadata.get("material_applications") if isinstance(metadata.get("material_applications"), list) else []
    light_templates = metadata.get("light_templates") if isinstance(metadata.get("light_templates"), list) else []
    camera_motions = metadata.get("camera_motions") if isinstance(metadata.get("camera_motions"), list) else []
    camera_templates = metadata.get("camera_templates") if isinstance(metadata.get("camera_templates"), list) else []
    object_templates = metadata.get("object_templates") if isinstance(metadata.get("object_templates"), list) else []
    object_motions = metadata.get("object_motions") if isinstance(metadata.get("object_motions"), list) else []
    layered_renders = [
        item
        for item in renders
        if isinstance(item, dict) and str(item.get("output_type") or "") == "layered"
    ]
    updated_at = str(metadata.get("last_saved_from_blender") or metadata.get("updated_at") or "").strip()
    summary = f"资产 {len(assets)} 个 · 镜头 {len(shots)} 个 · 输出 {len(renders)} 个"
    if layered_renders:
        summary += f" · 分层素材包 {len(layered_renders)} 个"
    ai_workflow_result_count = int(ai_workflow_results_summary.get("result_count") or len(ai_workflow_results))
    if ai_workflow_result_count:
        summary += f" · AI结果回填 {ai_workflow_result_count} 个"
    if actors:
        summary += f" · 演员位 {len(actors)} 个"
    if shot_packages:
        summary += f" · 镜头包 {len(shot_packages)} 个"
    if set_packages:
        summary += f" · 布景包 {len(set_packages)} 个"
    if asset_sources:
        summary += f" · 资产源 {len(asset_sources)} 个"
    if asset_libraries:
        summary += f" · 资产库 {len(asset_libraries)} 个"
    if asset_library_items:
        summary += f" · 库资产 {len(asset_library_items)} 个"
    if scene_presets:
        summary += f" · 场景预设 {len(scene_presets)} 个"
    if render_templates:
        summary += f" · 渲染模板 {len(render_templates)} 个"
    if action_applications:
        summary += f" · 动作记录 {len(action_applications)} 条"
    if action_clips:
        summary += f" · 动作片段 {len(action_clips)} 个"
    retarget_action_clips = [
        clip
        for clip in action_clips
        if isinstance(clip, dict) and str(clip.get("generated_by") or "") == "retarget"
    ]
    if retarget_action_clips:
        summary += f" · 重定向动作片段 {len(retarget_action_clips)} 个"
    if retarget_profiles:
        summary += f" · 重定向档案 {len(retarget_profiles)} 个"
    if retarget_applications:
        summary += f" · 重定向记录 {len(retarget_applications)} 条"
    if pose_templates:
        summary += f" · 姿势模板 {len(pose_templates)} 个"
    if animation_templates:
        summary += f" · 动画片段 {len(animation_templates)} 个"
    if material_templates:
        summary += f" · 材质模板 {len(material_templates)} 个"
    if material_applications:
        summary += f" · 材质应用 {len(material_applications)} 条"
    if light_templates:
        summary += f" · 灯光模板 {len(light_templates)} 个"
    if camera_motions:
        summary += f" · 镜头运动 {len(camera_motions)} 条"
    if camera_templates:
        summary += f" · 机位模板 {len(camera_templates)} 个"
    if object_templates:
        summary += f" · 站位模板 {len(object_templates)} 个"
    if object_motions:
        summary += f" · 角色走位 {len(object_motions)} 条"
    if updated_at:
        summary += f" · {updated_at}"
    return summary


def launch_blender_director_project(blender_executable, project):
    executable = str(blender_executable or "").strip()
    bootstrap_path = str((project or {}).get("bootstrap_path") or "").strip()
    if not executable or not os.path.exists(executable):
        raise RuntimeError("没有找到可用的 Blender。")
    if not bootstrap_path or not os.path.exists(bootstrap_path):
        raise RuntimeError("导演台工程启动脚本不存在。")
    popen_kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen([executable, "--python", bootstrap_path], **popen_kwargs)


def _json_literal(value):
    return json.dumps(str(value or ""), ensure_ascii=False)


def _director_bootstrap_script(blend_path, addon_path, meta_path):
    return f"""# -*- coding: utf-8 -*-
import os
import sys
import types
import traceback

import bpy

BLEND_PATH = {_json_literal(blend_path)}
ADDON_PATH = {_json_literal(addon_path)}
META_PATH = {_json_literal(meta_path)}


def _load_director_panel():
    module_name = "gpt_director_panel_runtime"
    module = types.ModuleType(module_name)
    module.__file__ = ADDON_PATH
    sys.modules[module_name] = module
    namespace = module.__dict__
    with open(ADDON_PATH, "r", encoding="utf-8") as f:
        code = compile(f.read(), ADDON_PATH, "exec")
    exec(code, namespace)
    namespace["register"]()
    return namespace


try:
    created = False
    if os.path.exists(BLEND_PATH):
        bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    else:
        # Start from an empty scene without resetting language, theme, or keymap preferences.
        bpy.ops.wm.read_homefile(use_empty=True)
        created = True
    panel = _load_director_panel()
    migrated = 0
    try:
        migrated = int(panel["_ensure_independent_mannequin_instances"]() or 0)
    except Exception:
        traceback.print_exc()
    if created:
        try:
            bpy.ops.gpt_director.add_dialogue_lounge_scene()
        except Exception:
            bpy.ops.gpt_director.init_scene()
    try:
        panel["_set_director_simple_view"](bpy.context, True)
    except Exception:
        pass
    if created or migrated:
        bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    print("GPT_DIRECTOR_PROJECT_READY", BLEND_PATH)
except Exception:
    traceback.print_exc()
"""


def _director_batch_render_script(blend_path, addon_path, meta_path):
    return f"""# -*- coding: utf-8 -*-
import os
import sys
import types
import traceback

import bpy

BLEND_PATH = {_json_literal(blend_path)}
ADDON_PATH = {_json_literal(addon_path)}
META_PATH = {_json_literal(meta_path)}


def _load_director_panel():
    module_name = "gpt_director_panel_batch_runtime"
    module = types.ModuleType(module_name)
    module.__file__ = ADDON_PATH
    sys.modules[module_name] = module
    namespace = module.__dict__
    with open(ADDON_PATH, "r", encoding="utf-8") as f:
        code = compile(f.read(), ADDON_PATH, "exec")
    exec(code, namespace)
    namespace["register"]()
    return namespace


try:
    if BLEND_PATH and os.path.exists(BLEND_PATH):
        bpy.ops.wm.open_mainfile(filepath=BLEND_PATH)
    _load_director_panel()
    result = bpy.ops.gpt_director.render_pending_shots()
    try:
        if BLEND_PATH:
            bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    except Exception:
        pass
    print("GPT_DIRECTOR_PENDING_BATCH_RENDER_DONE", result)
except Exception:
    traceback.print_exc()
    raise
"""


def _director_panel_script(
    meta_path,
    blend_path,
    renders_dir,
    assets_dir,
    shots_dir,
    presets_dir,
    set_packages_dir,
    asset_dirs,
    default_asset_library_path="",
):
    return f'''# -*- coding: utf-8 -*-
bl_info = {{
    "name": "GPT Director Panel",
    "author": "GPT Desktop",
    "version": (0, 1, 0),
    "blender": (2, 93, 0),
    "location": "View3D > Sidebar > Director",
    "description": "AI短剧导演台：场景、人物、道具、镜头与渲染桥接面板",
    "category": "3D View",
}}

import csv
import json
import hashlib
import math
import os
import re
import shutil
from datetime import datetime

import bpy
import blf
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras import view3d_utils
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Quaternion, Vector

META_PATH = {_json_literal(meta_path)}
BLEND_PATH = {_json_literal(blend_path)}
RENDERS_DIR = {_json_literal(renders_dir)}
ASSETS_DIR = {_json_literal(assets_dir)}
SHOTS_DIR = {_json_literal(shots_dir)}
PRESETS_DIR = {_json_literal(presets_dir)}
SET_PACKAGES_DIR = {_json_literal(set_packages_dir)}
DEFAULT_ASSET_LIBRARY_PATH = {_json_literal(default_asset_library_path)}
ASSET_DIRS = json.loads({json.dumps(json.dumps(asset_dirs or {}, ensure_ascii=False), ensure_ascii=False)})
MANNEQUIN_TEMPLATE_PATH = {_json_literal(os.path.join((asset_dirs or {}).get("characters", ""), BUNDLED_MANNEQUIN_FILENAME))}
MANNEQUIN_ATTRIBUTION_PATH = {_json_literal(os.path.join((asset_dirs or {}).get("characters", ""), BUNDLED_MANNEQUIN_ATTRIBUTION_FILENAME))}
FURNITURE_TEMPLATE_PATH = {_json_literal(os.path.join((asset_dirs or {}).get("props", ""), BUNDLED_FURNITURE_FILENAME))}
FURNITURE_ATTRIBUTION_PATH = {_json_literal(os.path.join((asset_dirs or {}).get("props", ""), BUNDLED_FURNITURE_ATTRIBUTION_FILENAME))}
FURNITURE_SOFA_COLLECTION_NAME = {_json_literal(BUNDLED_FURNITURE_SOFA_COLLECTION)}
FURNITURE_TABLE_COLLECTION_NAME = {_json_literal(BUNDLED_FURNITURE_TABLE_COLLECTION)}
BUILTIN_DIRECTOR_ASSET_PACK = json.loads({json.dumps(json.dumps(_default_director_asset_pack(), ensure_ascii=False), ensure_ascii=False)})
OPEN_ASSET_SOURCE_PROFILES = json.loads({json.dumps(json.dumps(_default_open_asset_source_profiles(), ensure_ascii=False), ensure_ascii=False)})
ASSET_KIND_DIR_KEYS = {{
    "character": "characters",
    "prop": "props",
    "scene": "scenes",
    "action": "actions",
    "model": "models",
    "material": "materials",
    "texture": "textures",
    "hdri": "hdris",
}}
ASSET_KIND_COLLECTIONS = {{
    "character": "Director Characters",
    "prop": "Director Props",
    "scene": "Director Scenes",
    "action": "Director Actions",
    "model": "Director Imported Assets",
    "material": "Director Materials",
    "texture": "Director Textures",
    "hdri": "Director HDRI",
}}
RENDER_OUTPUT_LABELS = {{
    "still": "普通图",
    "transparent": "透明图",
    "sequence": "图片序列",
    "video": "视频",
    "layered": "分层素材包",
}}
SHOT_STATUS_LABELS = {{
    "draft": "草稿",
    "review": "待调整",
    "approved": "已定稿",
}}
SCENE_ENVIRONMENT_LABELS = {{
    "unspecified": "未指定",
    "interior": "内景",
    "exterior": "外景",
    "mixed": "内外景",
}}
SCENE_TIME_LABELS = {{
    "unspecified": "未指定",
    "day": "日",
    "night": "夜",
    "dawn": "晨",
    "dusk": "昏",
}}
CAMERA_MOTION_LABELS = {{
    "push_in": "推近",
    "pull_out": "拉远",
    "truck_left": "左移",
    "truck_right": "右移",
    "rise": "升起",
    "descend": "下降",
}}
OBJECT_MOTION_LABELS = {{
    "forward": "前进",
    "backward": "后退",
    "left": "左移",
    "right": "右移",
    "rise": "升起",
    "descend": "下降",
}}
SUPPORTED_ASSET_EXTENSIONS = (".blend", ".glb", ".gltf", ".fbx", ".obj", ".bvh", ".stl", ".ply", ".abc", ".usd", ".usdz")
SUPPORTED_TEXTURE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr")
SUPPORTED_HDRI_EXTENSIONS = (".hdr",)
SUPPORTED_LIBRARY_EXTENSIONS = SUPPORTED_ASSET_EXTENSIONS + SUPPORTED_TEXTURE_EXTENSIONS
ASSET_KIND_RULES = (
    ("hdri", ("hdri", "hdris", "environment", "environments", "sky", "skies", "world", "studio_light", "环境光", "天空", "全景光")),
    ("material", ("material", "materials", "texture_set", "textureset", "ambientcg", "polyhaven", "pbr", "basecolor", "base_color", "albedo", "diffuse", "roughness", "normal", "材质", "贴图材质", "纹理集")),
    ("texture", ("texture", "textures", "tex", "image", "map", "maps", "贴图", "纹理")),
    ("action", ("action", "actions", "animation", "animations", "anim", "motion", "mocap", "pose", "poses", "walk", "run", "动作", "动画", "姿势", "走路", "行走")),
    ("character", ("character", "characters", "actor", "actors", "avatar", "avatars", "people", "person", "human", "mannequin", "rig", "人物", "角色", "演员", "人偶", "主角", "反派")),
    ("scene", ("scene", "scenes", "set", "sets", "environment", "environments", "room", "street", "stage", "building", "house", "场景", "房间", "街道", "舞台", "建筑", "室内", "室外")),
    ("prop", ("prop", "props", "object", "objects", "furniture", "vehicle", "vehicles", "weapon", "weapons", "道具", "物件", "家具", "车辆", "武器", "桌", "椅")),
)


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _load_meta():
    if not os.path.exists(META_PATH):
        return {{}}
    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {{}}
    except Exception:
        return {{}}


def _save_meta(data):
    _ensure_dir(os.path.dirname(META_PATH))
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _remove_legacy_depth_scene_data():
    removed = 0
    for obj in list(bpy.data.objects):
        try:
            is_legacy_depth = bool(obj.get("gpt_director_scene_reference"))
        except Exception:
            is_legacy_depth = False
        if not is_legacy_depth:
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        except Exception:
            pass
    data = _load_meta()
    changed = "scene_references" in data or "depth_estimator_script_path" in data
    data.pop("scene_references", None)
    data.pop("depth_estimator_script_path", None)
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    filtered_assets = [
        item for item in assets
        if not (
            str((item or {{}}).get("type") or "") == "scene_reference"
            or str((item or {{}}).get("imported_as") or "").startswith("scene_reference_")
        )
    ]
    if len(filtered_assets) != len(assets):
        data["assets"] = filtered_assets
        changed = True
    if changed:
        _save_meta(data)
    return removed


def _safe_id(text, fallback="shot"):
    text = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text or ""))
    text = "_".join(part for part in text.split("_") if part)
    return text[:48] or fallback


def _path_based_id(path, fallback="item"):
    raw_path = os.path.abspath(str(path or ""))
    digest = hashlib.sha1(raw_path.encode("utf-8", "ignore")).hexdigest()[:10]
    base = os.path.splitext(os.path.basename(raw_path))[0] or fallback
    return _safe_id(base + "_" + digest, fallback)


def _copy_asset_into_project(filepath, asset_kind):
    source = str(filepath or "")
    dir_key = ASSET_KIND_DIR_KEYS.get(asset_kind, "models")
    target_dir = ASSET_DIRS.get(dir_key) or ASSETS_DIR
    _ensure_dir(target_dir)
    name = os.path.basename(source)
    stem, ext = os.path.splitext(name)
    target = os.path.join(target_dir, name)
    if os.path.abspath(source) == os.path.abspath(target):
        return target
    index = 1
    while os.path.exists(target):
        target = os.path.join(target_dir, f"{{stem}}_{{index}}{{ext}}")
        index += 1
    try:
        shutil.copy2(source, target)
        return target
    except Exception:
        return source


def _is_texture_asset_path(path):
    return str(path or "").lower().endswith(SUPPORTED_TEXTURE_EXTENSIONS)


def _texture_role_from_path(path):
    stem = os.path.splitext(os.path.basename(str(path or "").lower()))[0]
    normalized = stem.replace("-", "_").replace(" ", "_").replace(".", "_")
    role_rules = (
        ("normal", ("normalgl", "normaldx", "normal", "_nrm", "_nor", "_n_")),
        ("roughness", ("roughness", "rough", "_rgh", "_rough")),
        ("metallic", ("metallic", "metalness", "metal", "_mtl")),
        ("alpha", ("opacity", "alpha", "transparency", "mask")),
        ("height", ("height", "displacement", "disp", "bump")),
        ("base_color", ("basecolor", "base_color", "albedo", "diffuse", "color", "colour", "_col")),
        ("ambient_occlusion", ("ambientocclusion", "ambient_occlusion", "_ao", " occlusion")),
    )
    for role, keywords in role_rules:
        for keyword in keywords:
            if keyword and keyword in normalized:
                return role
    return "base_color"


def _asset_kind_from_path(path, source_profile=None):
    lower = str(path or "").lower().replace("\\\\", "/")
    if lower.endswith(".bvh"):
        return "action"
    profile = source_profile if isinstance(source_profile, dict) else {{}}
    profile_text = (str(profile.get("id") or "") + " " + str(profile.get("name") or "")).lower()
    if _is_texture_asset_path(path):
        hdri_keywords = ("hdri", "hdris", "environment", "environments", "sky", "skies", "world", "studio_light", "环境光", "天空")
        if lower.endswith(SUPPORTED_HDRI_EXTENSIONS) or (lower.endswith(".exr") and any(keyword in lower for keyword in hdri_keywords)):
            return "hdri"
        material_keywords = ("ambientcg", "material", "materials", "texture_set", "textureset", "pbr", "basecolor", "base_color", "albedo", "diffuse", "roughness", "normal", "材质", "纹理集")
        if "ambientcg" in profile_text or any(keyword in lower for keyword in material_keywords):
            return "material"
        return "texture"
    for kind, keywords in ASSET_KIND_RULES:
        if kind in ("hdri", "material", "texture"):
            continue
        for keyword in keywords:
            if keyword and keyword in lower:
                return kind
    return "model"


def _asset_paths_from_directory(directory, recursive=True):
    directory = str(directory or "").strip()
    if not directory or not os.path.isdir(directory):
        return []
    paths = []
    if recursive:
        for root, _dirs, files in os.walk(directory):
            for name in files:
                path = os.path.join(root, name)
                if path.lower().endswith(SUPPORTED_LIBRARY_EXTENSIONS):
                    paths.append(path)
    else:
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path) and path.lower().endswith(SUPPORTED_LIBRARY_EXTENSIONS):
                paths.append(path)
    return sorted(paths)


def _library_key_for_path(path):
    return _path_based_id(path, "library")


def _source_profile_by_id(profile_id):
    profile_id = str(profile_id or "").strip()
    for profile in OPEN_ASSET_SOURCE_PROFILES:
        if isinstance(profile, dict) and str(profile.get("id") or "") == profile_id:
            return dict(profile)
    return {{}}


def _active_asset_source_profile():
    scene = bpy.context.scene
    profile_id = str(getattr(scene, "gpt_director_asset_source_profile", "") or "").strip()
    return profile_id if profile_id and profile_id != "__generic__" else ""


def _asset_source_profile_enum_items(self, context):
    items = [("__generic__", "通用本地资产库", "不绑定具体生态来源，只按目录和文件名推断资产类型")]
    seen = set(["__generic__"])
    for profile in OPEN_ASSET_SOURCE_PROFILES:
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id") or "").strip()
        if not profile_id or profile_id in seen:
            continue
        name = str(profile.get("name") or profile_id).strip()
        formats = profile.get("formats") if isinstance(profile.get("formats"), list) else []
        route = str(profile.get("route") or "").strip()
        detail = " / ".join(str(item).upper() for item in formats[:6])
        if route:
            detail = (detail + " · " if detail else "") + route
        items.append((profile_id, name, detail or "开源资产生态来源"))
        seen.add(profile_id)
    return items


def _read_blender_asset_catalogs(library_path):
    library_path = os.path.abspath(str(library_path or ""))
    catalog_path = os.path.join(library_path, "blender_assets.cats.txt")
    catalogs = []
    if not os.path.isfile(catalog_path):
        return catalogs, ""
    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return catalogs, catalog_path
    for line in lines:
        text = str(line or "").strip()
        if not text or text.startswith("#") or text.upper().startswith("VERSION"):
            continue
        parts = text.split(":")
        if len(parts) < 3:
            continue
        catalog_id = parts[0].strip()
        catalog_path_value = parts[1].strip().strip("/")
        catalog_name = ":".join(parts[2:]).strip() or os.path.basename(catalog_path_value)
        if not catalog_id or not catalog_path_value:
            continue
        catalogs.append({{
            "id": catalog_id,
            "path": catalog_path_value,
            "name": catalog_name,
        }})
    return catalogs, catalog_path


def _catalog_for_library_item(relative_path, catalogs):
    relative_dir = os.path.dirname(str(relative_path or "")).replace(os.sep, "/").strip("/")
    if not relative_dir:
        return {{}}
    best = {{}}
    best_len = -1
    rel_lower = relative_dir.lower()
    for catalog in catalogs if isinstance(catalogs, list) else []:
        if not isinstance(catalog, dict):
            continue
        catalog_path = str(catalog.get("path") or "").replace("\\\\", "/").strip("/")
        if not catalog_path:
            continue
        catalog_lower = catalog_path.lower()
        matched = rel_lower == catalog_lower or rel_lower.startswith(catalog_lower + "/") or catalog_lower.endswith("/" + rel_lower)
        if matched and len(catalog_path) > best_len:
            best = catalog
            best_len = len(catalog_path)
    return dict(best) if best else {{}}


def _library_item_from_path(path, library_path="", source_profile=None, catalogs=None):
    path = str(path or "").strip()
    if not path:
        return {{}}
    source_profile = source_profile if isinstance(source_profile, dict) else {{}}
    try:
        size = os.path.getsize(path)
    except Exception:
        size = 0
    try:
        modified_at = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        modified_at = ""
    file_name = os.path.basename(path)
    library_path = str(library_path or "").strip()
    relative_path = ""
    if library_path:
        try:
            relative_path = os.path.relpath(path, library_path)
        except Exception:
            relative_path = file_name
    catalog = _catalog_for_library_item(relative_path, catalogs)
    kind_hint = _asset_kind_from_path(path, source_profile)
    item = {{
        "id": _path_based_id(path, "library_asset"),
        "path": path,
        "library_path": library_path,
        "relative_path": relative_path,
        "name": os.path.splitext(file_name)[0] or file_name,
        "file_name": file_name,
        "format": os.path.splitext(path)[1].lstrip(".").lower(),
        "kind_hint": kind_hint,
        "size": int(size or 0),
        "modified_at": modified_at,
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_profile_id": str(source_profile.get("id") or ""),
        "source_profile_name": str(source_profile.get("name") or ""),
        "asset_browser_catalog_id": str(catalog.get("id") or ""),
        "asset_browser_catalog_path": str(catalog.get("path") or ""),
        "asset_browser_catalog_name": str(catalog.get("name") or ""),
    }}
    if kind_hint in ("material", "texture", "hdri"):
        item["texture_role"] = _texture_role_from_path(path)
    return item


def _upsert_asset_source(data, directory, profile_id="", item_count=0, catalog_count=0):
    sources = data.get("asset_sources")
    if not isinstance(sources, list):
        sources = []
    directory = os.path.abspath(str(directory or ""))
    profile = _source_profile_by_id(profile_id)
    profile_id = str(profile.get("id") or profile_id or "").strip()
    source_key = _safe_id((profile_id or "generic") + "_" + _library_key_for_path(directory), "asset_source")
    record = {{
        "id": source_key,
        "path": directory,
        "name": os.path.basename(directory) or directory,
        "profile_id": profile_id,
        "profile_name": str(profile.get("name") or "通用本地资产库"),
        "formats": profile.get("formats") if isinstance(profile.get("formats"), list) else [],
        "route": str(profile.get("route") or ""),
        "item_count": int(item_count or 0),
        "asset_browser_catalog_count": int(catalog_count or 0),
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    replaced = False
    for idx, source in enumerate(sources):
        if isinstance(source, dict) and (source.get("id") == source_key or (os.path.abspath(str(source.get("path") or "")) == directory and str(source.get("profile_id") or "") == profile_id)):
            sources[idx] = record
            replaced = True
            break
    if not replaced:
        sources.append(record)
    data["asset_sources"] = sources[-100:]
    return record


def _upsert_asset_library(data, directory, item_count=0, profile_id="", catalog_count=0, catalog_path=""):
    libraries = data.get("asset_libraries")
    if not isinstance(libraries, list):
        libraries = []
    directory = os.path.abspath(str(directory or ""))
    profile = _source_profile_by_id(profile_id)
    key = _library_key_for_path(directory)
    record = {{
        "id": key,
        "path": directory,
        "name": os.path.basename(directory) or directory,
        "item_count": int(item_count or 0),
        "asset_browser_catalog_count": int(catalog_count or 0),
        "asset_browser_catalog_path": str(catalog_path or ""),
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_profile_id": str(profile.get("id") or profile_id or ""),
        "source_profile_name": str(profile.get("name") or ""),
    }}
    replaced = False
    for idx, library in enumerate(libraries):
        if isinstance(library, dict) and (library.get("id") == key or os.path.abspath(str(library.get("path") or "")) == directory):
            libraries[idx] = record
            replaced = True
            break
    if not replaced:
        libraries.append(record)
    data["asset_libraries"] = libraries[-100:]
    return record


def _scan_asset_library(data, directory, profile_id=""):
    directory = os.path.abspath(str(directory or ""))
    paths = _asset_paths_from_directory(directory, recursive=True)
    profile = _source_profile_by_id(profile_id)
    catalogs, catalog_path = _read_blender_asset_catalogs(directory)
    _upsert_asset_source(data, directory, profile_id, len(paths), len(catalogs))
    library = _upsert_asset_library(data, directory, len(paths), profile_id, len(catalogs), catalog_path)
    library_id = str(library.get("id") or _library_key_for_path(directory))
    old_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    old_by_key = {{}}
    for old in old_items:
        if not isinstance(old, dict):
            continue
        for key in (str(old.get("id") or ""), str(old.get("path") or "")):
            if key:
                old_by_key[key] = old
    kept = [
        item
        for item in old_items
        if isinstance(item, dict) and str(item.get("library_id") or "") != library_id
    ]
    new_items = []
    for path in paths:
        item = _library_item_from_path(path, directory, profile, catalogs)
        if not item:
            continue
        item["library_id"] = library_id
        old = old_by_key.get(str(item.get("id") or "")) or old_by_key.get(str(item.get("path") or ""))
        if isinstance(old, dict):
            if bool(old.get("favorite")):
                item["favorite"] = True
                item["favorited_at"] = str(old.get("favorited_at") or "")
            for field in ("tags", "usage_note", "metadata_updated_at", "last_used_at"):
                value = str(old.get(field) or "").strip()
                if value:
                    item[field] = value
            try:
                usage_count = int(old.get("usage_count") or 0)
                if usage_count > 0:
                    item["usage_count"] = usage_count
            except Exception:
                pass
        _copy_asset_preflight_fields(item, _asset_preflight_for_library_item(data, item))
        new_items.append(item)
    data["asset_library_items"] = (kept + new_items)[-3000:]
    return library, new_items


def _asset_library_signature(directory):
    manifest_path = os.path.join(str(directory or ""), "asset_manifest.json")
    try:
        stat = os.stat(manifest_path)
        return str(int(stat.st_mtime)) + ":" + str(int(stat.st_size))
    except Exception:
        return ""


def _ensure_default_asset_library():
    directory = os.path.abspath(str(DEFAULT_ASSET_LIBRARY_PATH or "").strip())
    if not directory or not os.path.isdir(directory):
        return 0
    try:
        bpy.context.scene.gpt_director_asset_library_path = directory
    except Exception:
        pass
    data = _load_meta()
    signature = _asset_library_signature(directory)
    previous_signature = str(data.get("default_asset_library_signature") or "")
    items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    existing = [
        item for item in items
        if isinstance(item, dict) and os.path.abspath(str(item.get("library_path") or "")) == directory
    ]
    if existing and signature and signature == previous_signature:
        return len(existing)
    _library, scanned = _scan_asset_library(data, directory, "")
    data["default_asset_library_path"] = directory
    data["default_asset_library_signature"] = signature
    _save_meta(data)
    return len(scanned)


def _asset_library_search_text():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_asset_library_search", "") or "").strip().lower()


def _asset_library_catalog_filter():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_asset_library_catalog", "__all__") or "__all__").strip()


def _asset_library_catalog_enum_items(self, context):
    items = [("__all__", "全部分类", "显示资产库中的全部分类")]
    data = _load_meta()
    library_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    catalogs = {{}}
    for item in library_items:
        if not isinstance(item, dict):
            continue
        catalog_id = str(item.get("asset_browser_catalog_id") or "").strip()
        catalog_path = str(item.get("asset_browser_catalog_path") or "").strip()
        catalog_name = str(item.get("asset_browser_catalog_name") or catalog_path or "").strip()
        if catalog_id and catalog_id not in catalogs:
            catalogs[catalog_id] = (catalog_name or catalog_id, catalog_path)
    for catalog_id, values in sorted(catalogs.items(), key=lambda pair: pair[1][0]):
        items.append((catalog_id, values[0], values[1] or "资产分类"))
    return items


def _asset_library_favorites_only():
    scene = bpy.context.scene
    return bool(getattr(scene, "gpt_director_library_favorites_only", False))


def _library_item_matches_filters(item):
    if not isinstance(item, dict):
        return False
    if _asset_library_favorites_only() and not bool(item.get("favorite")):
        return False
    catalog_filter = _asset_library_catalog_filter()
    if catalog_filter != "__all__" and str(item.get("asset_browser_catalog_id") or "") != catalog_filter:
        return False
    query = _asset_library_search_text()
    if not query:
        return True
    fields = [
        item.get("name"),
        item.get("file_name"),
        item.get("relative_path"),
        item.get("path"),
        item.get("format"),
        item.get("kind_hint"),
        item.get("tags"),
        item.get("usage_note"),
        item.get("asset_browser_catalog_path"),
        item.get("asset_browser_catalog_name"),
    ]
    haystack = " ".join(str(part or "") for part in fields).lower()
    return query in haystack


def _library_asset_enum_items(self, context):
    items = [("__manual__", "未选择库资产", "先扫描资产库，再从这里选择要导入的资产")]
    data = _load_meta()
    library_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    seen = set(["__manual__"])
    for item in library_items:
        if not isinstance(item, dict):
            continue
        if not _library_item_matches_filters(item):
            continue
        key = str(item.get("id") or "").strip()
        if not key or key in seen:
            continue
        name = str(item.get("name") or item.get("file_name") or key).strip()
        file_format = str(item.get("format") or "").strip().upper()
        relative = str(item.get("relative_path") or "").strip()
        modified_at = str(item.get("modified_at") or "").strip()
        tags = str(item.get("tags") or "").strip()
        usage_note = str(item.get("usage_note") or "").strip()
        usage_count = item.get("usage_count")
        last_used_at = str(item.get("last_used_at") or "").strip()
        favorite = bool(item.get("favorite"))
        preflight_label = str(item.get("preflight_status_label") or "").strip()
        catalog_label = str(item.get("asset_browser_catalog_path") or item.get("asset_browser_catalog_name") or "").strip()
        detail_parts = [file_format, relative]
        if catalog_label:
            detail_parts.append("Catalog：" + catalog_label)
        if preflight_label:
            detail_parts.append("预检：" + preflight_label)
        if usage_count not in (None, ""):
            detail_parts.append("使用 " + str(usage_count) + " 次" + (("：" + last_used_at) if last_used_at else ""))
        if tags:
            detail_parts.append("标签：" + tags)
        if usage_note:
            detail_parts.append("备注：" + usage_note[:40])
        if modified_at:
            detail_parts.append(modified_at)
        detail = " · ".join(part for part in detail_parts if part)
        catalog_name = str(item.get("asset_browser_catalog_name") or "").strip()
        label = ("★ " if favorite else "") + ((catalog_name + " / ") if catalog_name else "") + name + (" · " + file_format if file_format else "")
        items.append((key, label, detail or "资产库文件"))
        seen.add(key)
    return items


def _library_asset_key_values(item):
    return [
        str(item.get("id") or ""),
        str(item.get("path") or ""),
        str(item.get("name") or ""),
        str(item.get("file_name") or ""),
        str(item.get("relative_path") or ""),
    ]


def _library_asset_matches_key(item, key):
    return key in _library_asset_key_values(item)


def _find_library_asset(data, key):
    key = str(key or "").strip()
    if not key or key == "__manual__":
        return {{}}
    library_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    for item in library_items:
        if not isinstance(item, dict):
            continue
        if _library_asset_matches_key(item, key):
            return dict(item)
    return {{}}


def _asset_preflight_issue(severity, code, title, suggestion):
    return {{
        "severity": str(severity or "info"),
        "code": str(code or ""),
        "title": str(title or ""),
        "suggestion": str(suggestion or ""),
    }}


def _asset_preflight_license_hint(profile_id="", profile_name="", record=None):
    record = record if isinstance(record, dict) else {{}}
    explicit = str(
        record.get("license")
        or record.get("license_label")
        or record.get("usage_rights")
        or record.get("authorization")
        or record.get("rights")
        or ""
    ).strip()
    if explicit:
        return explicit, "ok"
    profile_text = (str(profile_id or "") + " " + str(profile_name or "")).lower()
    if "poly_haven" in profile_text or "poly haven" in profile_text or "ambientcg" in profile_text:
        return "CC0 / 可商用（按来源说明归档）", "ok"
    if "mixamo" in profile_text:
        return "Mixamo / Adobe 使用条款，需保留来源", "review"
    if "blender_asset_browser" in profile_text or "asset browser" in profile_text:
        return "Blender Asset Browser 本地库，需逐项保留原始授权", "review"
    if "blenderkit" in profile_text:
        return "BlenderKit 原资产授权，需逐项保留", "review"
    if "sketchfab" in profile_text or "opengameart" in profile_text or "open game art" in profile_text:
        return "按原始下载页授权，需逐项核对", "review"
    return "未标注授权来源", "missing"


def _library_item_import_record(data, item):
    if not isinstance(data, dict) or not isinstance(item, dict):
        return {{}}
    item_id = str(item.get("id") or "").strip()
    source_path = os.path.abspath(str(item.get("path") or "")) if item.get("path") else ""
    relative_path = str(item.get("relative_path") or "").strip()
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if item_id and str(asset.get("library_item_id") or "") == item_id:
            return dict(asset)
        asset_source = os.path.abspath(str(asset.get("source_path") or "")) if asset.get("source_path") else ""
        if source_path and asset_source and asset_source == source_path:
            return dict(asset)
        if relative_path and str(asset.get("library_relative_path") or "") == relative_path:
            return dict(asset)
    return {{}}


def _asset_preflight_texture_roles(data, item):
    roles = set()
    if not isinstance(item, dict):
        return roles
    path = str(item.get("path") or "").strip()
    base_dir = os.path.dirname(os.path.abspath(path)) if path else ""
    library_id = str(item.get("library_id") or "")
    items = data.get("asset_library_items") if isinstance(data, dict) and isinstance(data.get("asset_library_items"), list) else []
    for candidate in items:
        if not isinstance(candidate, dict):
            continue
        candidate_path = str(candidate.get("path") or "").strip()
        if not candidate_path or not _is_texture_asset_path(candidate_path):
            continue
        same_library = library_id and str(candidate.get("library_id") or "") == library_id
        same_dir = base_dir and os.path.dirname(os.path.abspath(candidate_path)) == base_dir
        if not same_library and not same_dir:
            continue
        role = str(candidate.get("texture_role") or _texture_role_from_path(candidate_path) or "").strip()
        if role:
            roles.add(role)
    if not roles and _is_texture_asset_path(path):
        roles.add(str(item.get("texture_role") or _texture_role_from_path(path) or "base_color"))
    return roles


def _asset_preflight_status(issues):
    issues = issues if isinstance(issues, list) else []
    error_count = sum(1 for issue in issues if isinstance(issue, dict) and issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if isinstance(issue, dict) and issue.get("severity") == "warning")
    info_count = sum(1 for issue in issues if isinstance(issue, dict) and issue.get("severity") == "info")
    if error_count:
        return "error", "阻断", error_count, warning_count, info_count
    if warning_count:
        return "warning", "需复核", error_count, warning_count, info_count
    if info_count:
        return "info", "可导入（有建议）", error_count, warning_count, info_count
    return "ready", "可导入", error_count, warning_count, info_count


def _asset_preflight_for_library_item(data, item):
    item = item if isinstance(item, dict) else {{}}
    path = str(item.get("path") or "").strip()
    file_format = str(item.get("format") or os.path.splitext(path)[1].lstrip(".").lower()).strip().lower()
    lower_path = path.lower()
    kind = str(item.get("kind_hint") or _asset_kind_from_path(path, item) or "model").strip()
    issues = []
    exists = bool(path and os.path.exists(path))
    supported = bool(lower_path and lower_path.endswith(SUPPORTED_LIBRARY_EXTENSIONS))
    if not path or not exists:
        issues.append(_asset_preflight_issue("error", "missing_file", "库资产文件不存在", "重新扫描资产库，或把源文件恢复到原路径后再导入。"))
    if path and not supported:
        issues.append(_asset_preflight_issue("error", "unsupported_format", "暂不支持该文件格式", "转换为 blend/glb/gltf/fbx/obj/bvh/stl/ply/abc/usd/usdz 或常见贴图/HDRI 格式。"))
    if exists:
        try:
            if os.path.getsize(path) <= 0:
                issues.append(_asset_preflight_issue("warning", "empty_file", "文件大小为 0", "确认文件是否下载完整，必要时重新下载。"))
        except Exception:
            pass
    profile_id = str(item.get("source_profile_id") or "").strip()
    profile_name = str(item.get("source_profile_name") or "").strip()
    license_label, license_status = _asset_preflight_license_hint(profile_id, profile_name, item)
    if license_status == "missing":
        issues.append(_asset_preflight_issue("warning", "missing_license", "缺授权来源", "补充 license/usage_rights 字段，或在备注里写明下载页授权。"))
    elif license_status == "review":
        issues.append(_asset_preflight_issue("warning", "license_review", "授权需人工复核", "导入商用工程前核对原始下载页授权和署名要求。"))
    if kind == "model":
        issues.append(_asset_preflight_issue("info", "confirm_asset_kind", "资产分类需要确认", "导入前选择人物、道具或场景分类，方便进入对应集合和报告。"))
    preview = str(item.get("preview") or item.get("preview_path") or item.get("thumbnail") or item.get("thumbnail_path") or "").strip()
    if not preview:
        issues.append(_asset_preflight_issue("info", "no_preview", "没有预览图", "可稍后生成缩略图或登记预览，方便导演台选资产。"))
    imported = _library_item_import_record(data, item)
    if kind == "action":
        if not imported:
            issues.append(_asset_preflight_issue("warning", "action_not_prepared", "动作尚未导入/验证", "导入到目标骨骼或建立重定向档案后再用于分镜匹配。"))
        if file_format not in ("fbx", "bvh"):
            issues.append(_asset_preflight_issue("warning", "action_format_review", "动作格式需确认", "优先使用 FBX/BVH 动作文件；其他格式请先在 Blender 内确认包含 Action。"))
    if kind in ("material", "texture"):
        roles = _asset_preflight_texture_roles(data, item)
        has_base = "base_color" in roles or "diffuse" in roles or "albedo" in roles
        has_pbr = bool(roles.intersection(set(["normal", "roughness", "metallic"])))
        if has_base and not has_pbr:
            issues.append(_asset_preflight_issue("info", "incomplete_texture_set", "贴图组不完整", "如需 PBR 材质，补齐 normal/roughness/metallic 等贴图。"))
    if kind == "hdri" and file_format not in ("hdr", "exr"):
        issues.append(_asset_preflight_issue("warning", "hdri_format_review", "HDRI 格式需确认", "建议使用 HDR/EXR 环境光贴图，避免普通图片误作 HDRI。"))
    status, status_label, error_count, warning_count, info_count = _asset_preflight_status(issues)
    return {{
        "status": status,
        "status_label": status_label,
        "blocked": status == "error",
        "issues": issues,
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "kind": kind,
        "format": file_format,
        "license_label": license_label,
        "license_status": license_status,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _copy_asset_preflight_fields(item, preflight):
    if not isinstance(item, dict) or not isinstance(preflight, dict):
        return item
    item["preflight_status"] = str(preflight.get("status") or "")
    item["preflight_status_label"] = str(preflight.get("status_label") or "")
    item["preflight_issue_count"] = int(preflight.get("issue_count") or 0)
    item["preflight_error_count"] = int(preflight.get("error_count") or 0)
    item["preflight_warning_count"] = int(preflight.get("warning_count") or 0)
    item["preflight_issues"] = preflight.get("issues") if isinstance(preflight.get("issues"), list) else []
    item["preflight_updated_at"] = str(preflight.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    item["license_label"] = str(preflight.get("license_label") or item.get("license_label") or "")
    item["license_status"] = str(preflight.get("license_status") or item.get("license_status") or "")
    return item


def _set_library_asset_preflight(data, key, preflight):
    key = str(key or "").strip()
    if not key or key == "__manual__":
        return {{}}
    library_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    for item in library_items:
        if not isinstance(item, dict):
            continue
        if not _library_asset_matches_key(item, key):
            continue
        _copy_asset_preflight_fields(item, preflight)
        return dict(item)
    return {{}}


def _asset_preflight_error_message(preflight):
    issues = preflight.get("issues") if isinstance(preflight, dict) and isinstance(preflight.get("issues"), list) else []
    titles = [
        str(issue.get("title") or issue.get("code") or "").strip()
        for issue in issues
        if isinstance(issue, dict) and issue.get("severity") == "error"
    ]
    titles = [title for title in titles if title]
    if titles:
        return "资产预检阻断：" + "；".join(titles[:3])
    return "资产预检阻断：请先修复资产文件或格式"


def _draw_library_asset_preflight(layout, context):
    key = str(getattr(context.scene, "gpt_director_library_asset_choice", "") or "").strip()
    if not key or key == "__manual__":
        return
    data = _load_meta()
    item = _find_library_asset(data, key)
    if not item:
        return
    preflight = _asset_preflight_for_library_item(data, item)
    status = str(preflight.get("status") or "ready")
    icon = "CHECKMARK"
    if status == "error":
        icon = "ERROR"
    elif status == "warning":
        icon = "INFO"
    elif status == "info":
        icon = "QUESTION"
    box = layout.box()
    box.label(text="资产预检：" + str(preflight.get("status_label") or "可导入"), icon=icon)
    detail = "类型 " + str(preflight.get("kind") or "model")
    if preflight.get("format"):
        detail += " · 格式 " + str(preflight.get("format")).upper()
    if preflight.get("license_label"):
        detail += " · 授权 " + str(preflight.get("license_label"))
    box.label(text=detail[:120])
    issues = preflight.get("issues") if isinstance(preflight.get("issues"), list) else []
    if not issues:
        box.label(text="未发现阻断项，可以导入。")
        return
    for issue in issues[:3]:
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity") or "info")
        issue_icon = "ERROR" if severity == "error" else "INFO"
        title = str(issue.get("title") or issue.get("code") or "预检建议").strip()
        suggestion = str(issue.get("suggestion") or "").strip()
        box.label(text=title[:90], icon=issue_icon)
        if suggestion:
            box.label(text=suggestion[:110])


def _set_library_asset_favorite(data, key, favorite):
    key = str(key or "").strip()
    if not key or key == "__manual__":
        return {{}}
    library_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    for item in library_items:
        if not isinstance(item, dict):
            continue
        if not _library_asset_matches_key(item, key):
            continue
        item["favorite"] = bool(favorite)
        if favorite:
            item["favorited_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            item.pop("favorited_at", None)
        return dict(item)
    return {{}}


def _set_library_asset_metadata(data, key, tags="", usage_note=""):
    key = str(key or "").strip()
    if not key or key == "__manual__":
        return {{}}
    tags = str(tags or "").strip()
    usage_note = str(usage_note or "").strip()
    library_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    for item in library_items:
        if not isinstance(item, dict):
            continue
        if not _library_asset_matches_key(item, key):
            continue
        if tags:
            item["tags"] = tags
        else:
            item.pop("tags", None)
        if usage_note:
            item["usage_note"] = usage_note
        else:
            item.pop("usage_note", None)
        item["metadata_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return dict(item)
    return {{}}


def _mark_library_asset_used(data, key):
    key = str(key or "").strip()
    if not key or key == "__manual__":
        return {{}}
    library_items = data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []
    for item in library_items:
        if not isinstance(item, dict):
            continue
        if not _library_asset_matches_key(item, key):
            continue
        try:
            item["usage_count"] = int(item.get("usage_count") or 0) + 1
        except Exception:
            item["usage_count"] = 1
        item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return dict(item)
    return {{}}


def _import_asset_paths(asset_paths, asset_kind, asset_label="", target_armature=None):
    data = _load_meta()
    actor, actor_armature = _active_action_target(data)
    if target_armature is None:
        target_armature = actor_armature
    imported = 0
    failed = 0
    for path in asset_paths:
        path = str(path or "").strip()
        if not path or not os.path.exists(path):
            continue
        kind = "action" if path.lower().endswith(".bvh") else asset_kind
        if kind == "model":
            hinted_kind = _asset_kind_from_path(path)
            if hinted_kind in ASSET_KIND_COLLECTIONS:
                kind = hinted_kind
        label = asset_label or os.path.basename(path)
        try:
            record = _import_director_asset(path, kind, label, target_armature if kind == "action" else None)
            if kind == "action":
                _record_action_application(
                    data,
                    record.get("target_armature", target_armature.name if target_armature else ""),
                    (record.get("actions") or [""])[-1] if isinstance(record.get("actions"), list) else "",
                    record.get("auto_apply_status", "not_applied"),
                    record.get("auto_apply_message", ""),
                    actor,
                )
                _upsert_action_clip_from_asset_record(data, record, actor, target_armature)
            _append_asset_record(data, record)
            imported += 1
        except Exception as exc:
            failed += 1
            print("GPT_DIRECTOR_ASSET_IMPORT_FAILED", path, exc)
    _save_meta(data)
    return imported, failed


def _camera_snapshot(camera):
    if not camera:
        return {{}}
    return {{
        "name": camera.name,
        "location": [round(v, 4) for v in camera.location],
        "rotation": [round(v, 4) for v in camera.rotation_euler],
        "lens": round(float(getattr(camera.data, "lens", 0) or 0), 4),
        "sensor_width": round(float(getattr(camera.data, "sensor_width", 0) or 0), 4),
    }}


def _apply_camera_snapshot(camera_data):
    if not isinstance(camera_data, dict):
        return None
    camera_name = str(camera_data.get("name") or "").strip()
    camera = bpy.data.objects.get(camera_name) if camera_name else None
    if camera is None or camera.type != "CAMERA":
        camera = bpy.context.scene.camera
    if camera is None or camera.type != "CAMERA":
        camera = _add_camera(name=camera_name or "Director Camera")
    location = camera_data.get("location")
    rotation = camera_data.get("rotation")
    if isinstance(location, list) and len(location) >= 3:
        camera.location = (float(location[0]), float(location[1]), float(location[2]))
    if isinstance(rotation, list) and len(rotation) >= 3:
        camera.rotation_euler = (float(rotation[0]), float(rotation[1]), float(rotation[2]))
    lens = camera_data.get("lens")
    sensor_width = camera_data.get("sensor_width")
    if lens not in (None, ""):
        camera.data.lens = float(lens)
    if sensor_width not in (None, ""):
        camera.data.sensor_width = float(sensor_width)
    bpy.context.scene.camera = camera
    return camera


def _active_camera_template_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_camera_template_name", "") or "").strip()
    return name or "未命名机位模板"


def _active_camera_template_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_camera_template_note", "") or "").strip()


def _camera_template_from_current_scene(scene, template_id, template_name, template_note):
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        camera = _add_camera()
    return {{
        "id": template_id,
        "name": template_name,
        "note": template_note,
        "camera": _camera_snapshot(camera),
        "frame": int(scene.frame_current),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_camera_template(data, template):
    templates = data.get("camera_templates")
    if not isinstance(templates, list):
        templates = []
    template_id = template.get("id")
    replaced = False
    for idx, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("id") == template_id:
            merged = dict(existing)
            merged.update(template)
            templates[idx] = merged
            replaced = True
            break
    if not replaced:
        templates.append(template)
    data["camera_templates"] = templates[-500:]
    return data


def _active_camera_template_key(scene):
    choice = str(getattr(scene, "gpt_director_camera_template_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_camera_template", "") or "").strip()


def _camera_template_enum_items(self, context):
    items = [("__manual__", "手动输入/当前机位", "使用下方机位模板ID/名称输入框")]
    data = _load_meta()
    templates = data.get("camera_templates") if isinstance(data.get("camera_templates"), list) else []
    seen = set(["__manual__"])
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        name = str(template.get("name") or template_id).strip()
        camera = template.get("camera") if isinstance(template.get("camera"), dict) else {{}}
        lens = camera.get("lens")
        note = str(template.get("note") or "").strip()
        detail_parts = []
        if lens not in (None, ""):
            detail_parts.append("焦距 " + str(lens))
        camera_name = str(camera.get("name") or "").strip()
        if camera_name:
            detail_parts.append(camera_name)
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "机位模板"
        items.append((template_id, name, description))
        seen.add(template_id)
    return items


def _find_camera_template(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_camera_template_name()
    templates = data.get("camera_templates") if isinstance(data.get("camera_templates"), list) else []
    for template in reversed(templates):
        if not isinstance(template, dict):
            continue
        if key in (str(template.get("id") or ""), str(template.get("name") or "")):
            return dict(template)
    return {{}}


def _delete_camera_template(data, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    templates = data.get("camera_templates") if isinstance(data.get("camera_templates"), list) else []
    kept = []
    removed = False
    for item in templates:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (template_id and str(item.get("id") or "") == template_id) or (template_name and str(item.get("name") or "") == template_name):
            removed = True
            continue
        kept.append(item)
    data["camera_templates"] = kept
    return removed


def _apply_camera_template(context, template):
    if not isinstance(template, dict):
        return None
    camera = _apply_camera_snapshot(template.get("camera") or {{}})
    try:
        context.scene.frame_current = int(template.get("frame") or context.scene.frame_current)
    except Exception:
        pass
    return camera


def _object_snapshot(obj):
    if not obj:
        return {{}}
    return {{
        "name": obj.name,
        "type": obj.type,
        "location": [round(v, 4) for v in obj.location],
        "rotation": [round(v, 4) for v in obj.rotation_euler],
        "scale": [round(v, 4) for v in obj.scale],
        "hide_viewport": bool(getattr(obj, "hide_viewport", False)),
        "hide_render": bool(getattr(obj, "hide_render", False)),
    }}


def _scene_object_snapshots(scene):
    objects = []
    for obj in scene.objects:
        if obj.type == "CAMERA":
            continue
        objects.append(_object_snapshot(obj))
    return objects


def _apply_object_snapshots(objects):
    if not isinstance(objects, list):
        return 0
    applied = 0
    for item in objects:
        if not isinstance(item, dict):
            continue
        obj_name = str(item.get("name") or "").strip()
        obj = bpy.data.objects.get(obj_name) if obj_name else None
        if obj is None:
            continue
        location = item.get("location")
        rotation = item.get("rotation")
        scale = item.get("scale")
        if isinstance(location, list) and len(location) >= 3:
            obj.location = (float(location[0]), float(location[1]), float(location[2]))
        if isinstance(rotation, list) and len(rotation) >= 3:
            obj.rotation_euler = (float(rotation[0]), float(rotation[1]), float(rotation[2]))
        if isinstance(scale, list) and len(scale) >= 3:
            obj.scale = (float(scale[0]), float(scale[1]), float(scale[2]))
        if "hide_viewport" in item:
            obj.hide_viewport = bool(item.get("hide_viewport"))
        if "hide_render" in item:
            obj.hide_render = bool(item.get("hide_render"))
        applied += 1
    return applied


def _active_object_template_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_object_template_name", "") or "").strip()
    return name or "未命名站位模板"


def _active_object_template_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_object_template_note", "") or "").strip()


def _selected_object_snapshots(context):
    selected = [obj for obj in (context.selected_objects or []) if obj and obj.type != "CAMERA"]
    if not selected:
        raise RuntimeError("请先选中要保存站位的角色或道具")
    return [_object_snapshot(obj) for obj in selected]


def _object_template_from_selected_objects(context, template_id, template_name, template_note):
    objects = _selected_object_snapshots(context)
    return {{
        "id": template_id,
        "name": template_name,
        "note": template_note,
        "objects": objects,
        "frame": int(context.scene.frame_current),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_object_template(data, template):
    templates = data.get("object_templates")
    if not isinstance(templates, list):
        templates = []
    template_id = template.get("id")
    replaced = False
    for idx, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("id") == template_id:
            merged = dict(existing)
            merged.update(template)
            templates[idx] = merged
            replaced = True
            break
    if not replaced:
        templates.append(template)
    data["object_templates"] = templates[-500:]
    return data


def _active_object_template_key(scene):
    choice = str(getattr(scene, "gpt_director_object_template_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_object_template", "") or "").strip()


def _object_template_enum_items(self, context):
    items = [("__manual__", "手动输入/当前选中对象", "使用下方站位模板ID/名称输入框")]
    data = _load_meta()
    templates = data.get("object_templates") if isinstance(data.get("object_templates"), list) else []
    seen = set(["__manual__"])
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        name = str(template.get("name") or template_id).strip()
        objects = template.get("objects") if isinstance(template.get("objects"), list) else []
        object_names = [str(item.get("name") or "").strip() for item in objects if isinstance(item, dict)]
        object_names = [item for item in object_names if item]
        detail_parts = []
        if object_names:
            label = "、".join(object_names[:4])
            if len(object_names) > 4:
                label += " 等 " + str(len(object_names)) + " 个"
            detail_parts.append(label)
        note = str(template.get("note") or "").strip()
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "站位模板"
        items.append((template_id, name, description))
        seen.add(template_id)
    return items


def _find_object_template(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_object_template_name()
    templates = data.get("object_templates") if isinstance(data.get("object_templates"), list) else []
    for template in reversed(templates):
        if not isinstance(template, dict):
            continue
        if key in (str(template.get("id") or ""), str(template.get("name") or "")):
            return dict(template)
    return {{}}


def _delete_object_template(data, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    templates = data.get("object_templates") if isinstance(data.get("object_templates"), list) else []
    kept = []
    removed = False
    for item in templates:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (template_id and str(item.get("id") or "") == template_id) or (template_name and str(item.get("name") or "") == template_name):
            removed = True
            continue
        kept.append(item)
    data["object_templates"] = kept
    return removed


def _apply_object_template(context, template):
    if not isinstance(template, dict):
        return 0
    applied = _apply_object_snapshots(template.get("objects") or [])
    try:
        context.scene.frame_current = int(template.get("frame") or context.scene.frame_current)
    except Exception:
        pass
    try:
        bpy.ops.object.select_all(action="DESELECT")
        for item in template.get("objects") or []:
            if not isinstance(item, dict):
                continue
            obj_name = str(item.get("name") or "").strip()
            obj = bpy.data.objects.get(obj_name) if obj_name else None
            if obj:
                obj.select_set(True)
                context.view_layer.objects.active = obj
    except Exception:
        pass
    return applied


def _active_actor_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_actor_name", "") or "").strip()
    return name or "未命名演员"


def _active_actor_role():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_actor_role", "") or "").strip()


def _active_actor_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_actor_note", "") or "").strip()


def _selected_actor_objects(context):
    selected = [obj for obj in (context.selected_objects or []) if obj and obj.type not in {{"CAMERA", "LIGHT"}}]
    if not selected:
        raise RuntimeError("请先选中要登记为演员位的人物对象")
    return selected


def _actor_from_selected_objects(context, actor_id, actor_name, actor_role, actor_note):
    selected = _selected_actor_objects(context)
    object_names = sorted(set(obj.name for obj in selected if obj and obj.name))
    return {{
        "id": actor_id,
        "name": actor_name,
        "role": actor_role,
        "note": actor_note,
        "objects": [_object_snapshot(obj) for obj in selected],
        "object_names": object_names,
        "object_count": len(object_names),
        "actions": _actions_from_objects(selected),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_actor(data, actor):
    actors = data.get("actors")
    if not isinstance(actors, list):
        actors = []
    actor_id = str(actor.get("id") or "").strip()
    replaced = False
    for idx, existing in enumerate(actors):
        if isinstance(existing, dict) and str(existing.get("id") or "") == actor_id:
            merged = dict(existing)
            merged.update(actor)
            actors[idx] = merged
            replaced = True
            break
    if not replaced:
        actors.append(actor)
    data["actors"] = actors[-500:]
    return data


def _active_actor_key(scene):
    choice = str(getattr(scene, "gpt_director_actor_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_actor", "") or "").strip()


def _actor_object_names(actor):
    names = []
    raw_names = actor.get("object_names") if isinstance(actor, dict) else []
    if isinstance(raw_names, list):
        names.extend(str(name or "").strip() for name in raw_names)
    objects = actor.get("objects") if isinstance(actor, dict) and isinstance(actor.get("objects"), list) else []
    for item in objects:
        if isinstance(item, dict):
            names.append(str(item.get("name") or "").strip())
    seen = set()
    clean = []
    for name in names:
        if name and name not in seen:
            clean.append(name)
            seen.add(name)
    return clean


def _actor_enum_items(self, context):
    items = [("__manual__", "手动输入/当前选中对象", "使用下方演员ID/名称输入框")]
    data = _load_meta()
    actors = data.get("actors") if isinstance(data.get("actors"), list) else []
    seen = set(["__manual__"])
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        actor_id = str(actor.get("id") or "").strip()
        if not actor_id or actor_id in seen:
            continue
        name = str(actor.get("name") or actor_id).strip()
        role = str(actor.get("role") or "").strip()
        note = str(actor.get("note") or "").strip()
        object_names = _actor_object_names(actor)
        detail_parts = []
        if role:
            detail_parts.append(role)
        if object_names:
            label = "、".join(object_names[:4])
            if len(object_names) > 4:
                label += " 等 " + str(len(object_names)) + " 个"
            detail_parts.append(label)
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "演员位"
        items.append((actor_id, name, description))
        seen.add(actor_id)
    return items


def _find_actor(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_actor_name()
    actors = data.get("actors") if isinstance(data.get("actors"), list) else []
    for actor in reversed(actors):
        if not isinstance(actor, dict):
            continue
        if key in (str(actor.get("id") or ""), str(actor.get("name") or "")):
            return dict(actor)
    return {{}}


def _delete_actor(data, actor):
    if not isinstance(actor, dict):
        return False
    actor_id = str(actor.get("id") or "").strip()
    actor_name = str(actor.get("name") or "").strip()
    actors = data.get("actors") if isinstance(data.get("actors"), list) else []
    kept = []
    removed = False
    for item in actors:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (actor_id and str(item.get("id") or "") == actor_id) or (actor_name and str(item.get("name") or "") == actor_name):
            removed = True
            continue
        kept.append(item)
    data["actors"] = kept
    return removed


def _select_actor_objects(actor):
    return _select_objects_by_names(_actor_object_names(actor))


def _objects_from_actor(actor):
    objects = []
    seen = set()
    for name in _actor_object_names(actor):
        obj = bpy.data.objects.get(name)
        if obj is None or obj.name in seen:
            continue
        objects.append(obj)
        seen.add(obj.name)
    return objects


def _armature_from_actor(actor):
    objects = _objects_from_actor(actor)
    for obj in objects:
        if obj and obj.type == "ARMATURE":
            return obj
    for obj in objects:
        parent = getattr(obj, "parent", None)
        if parent and parent.type == "ARMATURE":
            return parent
    return None


def _actor_reference(actor):
    if not isinstance(actor, dict) or not actor:
        return {{}}
    actor_id = str(actor.get("id") or "").strip()
    actor_name = str(actor.get("name") or actor_id).strip()
    if not actor_id and not actor_name:
        return {{}}
    return {{
        "id": actor_id,
        "name": actor_name,
        "role": str(actor.get("role") or "").strip(),
        "object_names": _actor_object_names(actor),
    }}


def _active_actor(data):
    key = _active_actor_key(bpy.context.scene)
    if not key:
        return {{}}
    actor = _find_actor(data, key)
    return actor if isinstance(actor, dict) and actor else {{}}


def _active_action_target(data):
    actor = _active_actor(data)
    armature = _armature_from_actor(actor) if actor else None
    if armature:
        return actor, armature
    return actor, _active_armature()


def _actors_for_object_snapshots(data, object_snapshots):
    if not isinstance(data, dict) or not isinstance(object_snapshots, list):
        return []
    scene_object_names = set()
    for item in object_snapshots:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            scene_object_names.add(name)
    if not scene_object_names:
        return []
    actors = data.get("actors") if isinstance(data.get("actors"), list) else []
    matched = []
    seen = set()
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        actor_id = str(actor.get("id") or "").strip()
        actor_name = str(actor.get("name") or actor_id).strip()
        actor_key = actor_id or actor_name
        if not actor_key or actor_key in seen:
            continue
        object_names = _actor_object_names(actor)
        overlap = sorted(name for name in object_names if name in scene_object_names)
        if not overlap:
            continue
        matched.append({{
            "id": actor_id,
            "name": actor_name,
            "role": str(actor.get("role") or "").strip(),
            "object_names": overlap,
        }})
        seen.add(actor_key)
    return matched


def _assets_for_object_snapshots(data, object_snapshots):
    if not isinstance(data, dict) or not isinstance(object_snapshots, list):
        return []
    scene_object_names = set()
    for item in object_snapshots:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            scene_object_names.add(name)
    if not scene_object_names:
        return []
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    matched = []
    seen = set()
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        object_names = asset.get("objects") if isinstance(asset.get("objects"), list) else []
        asset_objects = set(str(name or "").strip() for name in object_names if str(name or "").strip())
        overlap = sorted(scene_object_names.intersection(asset_objects))
        if not overlap:
            continue
        asset_id = str(asset.get("id") or "").strip()
        asset_name = str(asset.get("name") or asset.get("file_name") or asset_id).strip()
        key = asset_id or asset_name
        if not key or key in seen:
            continue
        seen.add(key)
        matched.append({{
            "id": asset_id,
            "name": asset_name,
            "type": str(asset.get("type") or ""),
            "format": str(asset.get("format") or ""),
            "path": str(asset.get("path") or ""),
            "library_item_id": str(asset.get("library_item_id") or ""),
            "library_relative_path": str(asset.get("library_relative_path") or ""),
            "object_names": overlap,
        }})
    return matched


def _active_preset_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_preset_name", "") or "").strip()
    return name or "未命名场景预设"


def _active_preset_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_preset_note", "") or "").strip()


def _scene_preset_from_current_scene(scene, preset_id, preset_name, preset_note):
    frame_start, frame_end = _active_frame_range(scene)
    output_type = _active_render_output()
    return {{
        "id": preset_id,
        "name": preset_name,
        "note": preset_note,
        "camera": _camera_snapshot(scene.camera),
        "objects": _scene_object_snapshots(scene),
        "frame": int(scene.frame_current),
        "frame_start": int(frame_start),
        "frame_end": int(frame_end),
        "output_type": output_type,
        "output_label": RENDER_OUTPUT_LABELS.get(output_type, output_type),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_scene_preset(data, preset):
    presets = data.get("scene_presets")
    if not isinstance(presets, list):
        presets = []
    preset_id = preset.get("id")
    replaced = False
    for idx, existing in enumerate(presets):
        if isinstance(existing, dict) and existing.get("id") == preset_id:
            merged = dict(existing)
            merged.update(preset)
            presets[idx] = merged
            replaced = True
            break
    if not replaced:
        presets.append(preset)
    data["scene_presets"] = presets[-500:]
    return data


def _active_scene_preset_key(scene):
    choice = str(getattr(scene, "gpt_director_preset_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_preset", "") or "").strip()


def _scene_preset_enum_items(self, context):
    items = [("__manual__", "手动输入/当前场景", "使用下方场景预设ID/名称输入框")]
    data = _load_meta()
    presets = data.get("scene_presets") if isinstance(data.get("scene_presets"), list) else []
    seen = set(["__manual__"])
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        preset_id = str(preset.get("id") or "").strip()
        if not preset_id or preset_id in seen:
            continue
        name = str(preset.get("name") or preset_id).strip()
        frame_start = preset.get("frame_start")
        frame_end = preset.get("frame_end")
        object_count = len(preset.get("objects")) if isinstance(preset.get("objects"), list) else 0
        description_parts = []
        if object_count:
            description_parts.append("对象 " + str(object_count))
        if frame_start is not None and frame_end is not None:
            description_parts.append("帧：" + str(frame_start) + "-" + str(frame_end))
        note = str(preset.get("note") or "").strip()
        if note:
            description_parts.append(note)
        description = "｜".join(description_parts) if description_parts else "场景预设"
        items.append((preset_id, name, description))
        seen.add(preset_id)
    return items


def _find_scene_preset(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_preset_name()
    presets = data.get("scene_presets") if isinstance(data.get("scene_presets"), list) else []
    for preset in reversed(presets):
        if not isinstance(preset, dict):
            continue
        if key in (str(preset.get("id") or ""), str(preset.get("name") or "")):
            return dict(preset)
    preset_file = os.path.join(PRESETS_DIR, _safe_id(key, "preset") + ".json")
    if os.path.exists(preset_file):
        try:
            with open(preset_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {{}}


def _save_scene_preset_file(preset):
    if not isinstance(preset, dict):
        return
    preset_id = _safe_id(preset.get("id") or preset.get("name") or "preset", "preset")
    _ensure_dir(PRESETS_DIR)
    path = os.path.join(PRESETS_DIR, preset_id + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(preset, f, ensure_ascii=False, indent=2)


def _delete_scene_preset_file(preset):
    if not isinstance(preset, dict):
        return
    preset_id = _safe_id(preset.get("id") or preset.get("name") or "preset", "preset")
    path = os.path.join(PRESETS_DIR, preset_id + ".json")
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _delete_scene_preset(data, preset):
    if not isinstance(preset, dict):
        return False
    preset_id = str(preset.get("id") or "").strip()
    preset_name = str(preset.get("name") or "").strip()
    presets = data.get("scene_presets") if isinstance(data.get("scene_presets"), list) else []
    kept = []
    removed = False
    for item in presets:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (preset_id and str(item.get("id") or "") == preset_id) or (preset_name and str(item.get("name") or "") == preset_name):
            removed = True
            continue
        kept.append(item)
    data["scene_presets"] = kept
    return removed


def _apply_scene_preset(context, preset):
    if not isinstance(preset, dict):
        return 0
    _apply_camera_snapshot(preset.get("camera") or {{}})
    applied = _apply_object_snapshots(preset.get("objects") or [])
    scene = context.scene
    try:
        scene.frame_current = int(preset.get("frame") or scene.frame_current)
    except Exception:
        pass
    try:
        scene.gpt_director_frame_start = int(preset.get("frame_start") or scene.gpt_director_frame_start)
        scene.gpt_director_frame_end = int(preset.get("frame_end") or scene.gpt_director_frame_end)
        scene.frame_start = int(scene.gpt_director_frame_start)
        scene.frame_end = int(scene.gpt_director_frame_end)
    except Exception:
        pass
    output_type = str(preset.get("output_type") or "")
    if output_type in RENDER_OUTPUT_LABELS:
        scene.gpt_director_render_output = output_type
    return applied


def _shot_from_current_scene(scene, shot_id, shot_name, shot_note, data=None):
    frame_start, frame_end = _active_frame_range(scene)
    output_type = _active_render_output()
    shot_status = _active_shot_status()
    scene_environment = _active_scene_environment()
    scene_time = _active_scene_time()
    objects = _scene_object_snapshots(scene)
    return {{
        "id": shot_id,
        "name": shot_name,
        "note": shot_note,
        "scene_number": _active_scene_number(),
        "scene_location": _active_scene_location(),
        "scene_environment": scene_environment,
        "scene_environment_label": SCENE_ENVIRONMENT_LABELS.get(scene_environment, scene_environment),
        "scene_time": scene_time,
        "scene_time_label": SCENE_TIME_LABELS.get(scene_time, scene_time),
        "camera": _camera_snapshot(scene.camera),
        "objects": objects,
        "actors": _actors_for_object_snapshots(data or {{}}, objects),
        "assets": _assets_for_object_snapshots(data or {{}}, objects),
        "shot_status": shot_status,
        "shot_status_label": SHOT_STATUS_LABELS.get(shot_status, shot_status),
        "frame": int(scene.frame_current),
        "frame_start": int(frame_start),
        "frame_end": int(frame_end),
        "output_type": output_type,
        "output_label": RENDER_OUTPUT_LABELS.get(output_type, output_type),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _active_shot_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_shot_name", "") or "").strip()
    return name or "未命名镜头"


def _active_shot_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_shot_note", "") or "").strip()


def _active_scene_number():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_scene_number", "") or "").strip()


def _active_scene_location():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_scene_location", "") or "").strip()


def _active_scene_environment():
    value = str(getattr(bpy.context.scene, "gpt_director_scene_environment", "unspecified") or "unspecified")
    return value if value in SCENE_ENVIRONMENT_LABELS else "unspecified"


def _active_scene_time():
    value = str(getattr(bpy.context.scene, "gpt_director_scene_time", "unspecified") or "unspecified")
    return value if value in SCENE_TIME_LABELS else "unspecified"


def _active_shot_status():
    value = str(getattr(bpy.context.scene, "gpt_director_shot_status", "draft") or "draft")
    return value if value in SHOT_STATUS_LABELS else "draft"


def _active_render_output():
    value = str(getattr(bpy.context.scene, "gpt_director_render_output", "still") or "still")
    return value if value in RENDER_OUTPUT_LABELS else "still"


def _active_frame_range(scene):
    try:
        start = int(getattr(scene, "gpt_director_frame_start", scene.frame_start) or scene.frame_start)
    except Exception:
        start = int(scene.frame_start)
    try:
        end = int(getattr(scene, "gpt_director_frame_end", scene.frame_end) or scene.frame_end)
    except Exception:
        end = int(scene.frame_end)
    if end < start:
        end = start
    return start, end


def _active_render_template_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_render_template_name", "") or "").strip()
    return name or "未命名渲染模板"


def _active_render_template_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_render_template_note", "") or "").strip()


def _render_template_from_scene(scene, template_id, template_name, template_note):
    frame_start, frame_end = _active_frame_range(scene)
    output_type = _active_render_output()
    render = scene.render
    image_settings = render.image_settings
    template = {{
        "id": template_id,
        "name": template_name,
        "note": template_note,
        "output_type": output_type,
        "output_label": RENDER_OUTPUT_LABELS.get(output_type, output_type),
        "frame_start": int(frame_start),
        "frame_end": int(frame_end),
        "resolution_x": int(getattr(render, "resolution_x", 0) or 0),
        "resolution_y": int(getattr(render, "resolution_y", 0) or 0),
        "resolution_percentage": int(getattr(render, "resolution_percentage", 100) or 100),
        "fps": int(getattr(render, "fps", 24) or 24),
        "fps_base": float(getattr(render, "fps_base", 1.0) or 1.0),
        "engine": str(getattr(render, "engine", "") or ""),
        "file_format": str(getattr(image_settings, "file_format", "") or ""),
        "color_mode": str(getattr(image_settings, "color_mode", "") or ""),
        "film_transparent": bool(getattr(render, "film_transparent", False)),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    try:
        template["cycles_samples"] = int(scene.cycles.samples)
        template["cycles_device"] = str(getattr(scene.cycles, "device", "") or "")
    except Exception:
        pass
    try:
        template["eevee_taa_render_samples"] = int(scene.eevee.taa_render_samples)
    except Exception:
        pass
    try:
        template["ffmpeg_format"] = str(getattr(render.ffmpeg, "format", "") or "")
        template["ffmpeg_codec"] = str(getattr(render.ffmpeg, "codec", "") or "")
        template["ffmpeg_crf"] = str(getattr(render.ffmpeg, "constant_rate_factor", "") or "")
    except Exception:
        pass
    return template


def _upsert_render_template(data, template):
    templates = data.get("render_templates")
    if not isinstance(templates, list):
        templates = []
    template_id = template.get("id")
    replaced = False
    for idx, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("id") == template_id:
            merged = dict(existing)
            merged.update(template)
            templates[idx] = merged
            replaced = True
            break
    if not replaced:
        templates.append(template)
    data["render_templates"] = templates[-500:]
    return data


def _active_render_template_key(scene):
    choice = str(getattr(scene, "gpt_director_render_template_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_render_template", "") or "").strip()


def _render_template_enum_items(self, context):
    items = [("__manual__", "手动输入/当前渲染设置", "使用下方渲染模板ID/名称输入框")]
    data = _load_meta()
    templates = data.get("render_templates") if isinstance(data.get("render_templates"), list) else []
    seen = set(["__manual__"])
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        name = str(template.get("name") or template_id).strip()
        output_label = str(template.get("output_label") or template.get("output_type") or "").strip()
        width = template.get("resolution_x")
        height = template.get("resolution_y")
        fps = template.get("fps")
        frame_start = template.get("frame_start")
        frame_end = template.get("frame_end")
        description_parts = []
        if output_label:
            description_parts.append(output_label)
        if width and height:
            description_parts.append(str(width) + "x" + str(height))
        if fps:
            description_parts.append(str(fps) + "fps")
        if frame_start is not None and frame_end is not None:
            description_parts.append("帧：" + str(frame_start) + "-" + str(frame_end))
        note = str(template.get("note") or "").strip()
        if note:
            description_parts.append(note)
        description = "｜".join(description_parts) if description_parts else "渲染模板"
        items.append((template_id, name, description))
        seen.add(template_id)
    return items


def _find_render_template(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_render_template_name()
    templates = data.get("render_templates") if isinstance(data.get("render_templates"), list) else []
    for template in reversed(templates):
        if not isinstance(template, dict):
            continue
        if key in (str(template.get("id") or ""), str(template.get("name") or "")):
            return dict(template)
    return {{}}


def _delete_render_template(data, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    templates = data.get("render_templates") if isinstance(data.get("render_templates"), list) else []
    kept = []
    removed = False
    for item in templates:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (template_id and str(item.get("id") or "") == template_id) or (template_name and str(item.get("name") or "") == template_name):
            removed = True
            continue
        kept.append(item)
    data["render_templates"] = kept
    return removed


def _apply_render_template(scene, template):
    if not isinstance(template, dict):
        return False
    output_type = str(template.get("output_type") or "")
    if output_type in RENDER_OUTPUT_LABELS:
        scene.gpt_director_render_output = output_type
    try:
        scene.gpt_director_frame_start = int(template.get("frame_start") or scene.gpt_director_frame_start)
        scene.gpt_director_frame_end = int(template.get("frame_end") or scene.gpt_director_frame_end)
        scene.frame_start = int(scene.gpt_director_frame_start)
        scene.frame_end = int(scene.gpt_director_frame_end)
    except Exception:
        pass
    render = scene.render
    for attr in ("resolution_x", "resolution_y", "resolution_percentage", "fps"):
        if attr not in template:
            continue
        try:
            setattr(render, attr, int(template.get(attr)))
        except Exception:
            pass
    if "fps_base" in template:
        try:
            render.fps_base = float(template.get("fps_base"))
        except Exception:
            pass
    engine = str(template.get("engine") or "").strip()
    if engine:
        try:
            render.engine = engine
        except Exception:
            pass
    try:
        if "file_format" in template and template.get("file_format"):
            render.image_settings.file_format = str(template.get("file_format"))
        if "color_mode" in template and template.get("color_mode"):
            render.image_settings.color_mode = str(template.get("color_mode"))
    except Exception:
        pass
    if "film_transparent" in template:
        try:
            render.film_transparent = bool(template.get("film_transparent"))
        except Exception:
            pass
    try:
        if "cycles_samples" in template:
            scene.cycles.samples = int(template.get("cycles_samples"))
        if "cycles_device" in template and template.get("cycles_device"):
            scene.cycles.device = str(template.get("cycles_device"))
    except Exception:
        pass
    try:
        if "eevee_taa_render_samples" in template:
            scene.eevee.taa_render_samples = int(template.get("eevee_taa_render_samples"))
    except Exception:
        pass
    try:
        if "ffmpeg_format" in template and template.get("ffmpeg_format"):
            render.ffmpeg.format = str(template.get("ffmpeg_format"))
        if "ffmpeg_codec" in template and template.get("ffmpeg_codec"):
            render.ffmpeg.codec = str(template.get("ffmpeg_codec"))
        if "ffmpeg_crf" in template and template.get("ffmpeg_crf"):
            render.ffmpeg.constant_rate_factor = str(template.get("ffmpeg_crf"))
    except Exception:
        pass
    return True


def _upsert_shot(data, shot):
    shots = data.get("shots")
    if not isinstance(shots, list):
        shots = []
    shot_id = shot.get("id")
    replaced = False
    for idx, existing in enumerate(shots):
        if isinstance(existing, dict) and existing.get("id") == shot_id:
            merged = dict(existing)
            merged.update(shot)
            shots[idx] = merged
            replaced = True
            break
    if not replaced:
        shots.append(shot)
    data["shots"] = shots[-500:]
    return data


def _find_shot(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_shot_name()
    shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    for shot in reversed(shots):
        if not isinstance(shot, dict):
            continue
        if key in (str(shot.get("id") or ""), str(shot.get("name") or "")):
            return dict(shot)
    shot_file = os.path.join(SHOTS_DIR, _safe_id(key, "shot") + ".json")
    if os.path.exists(shot_file):
        try:
            with open(shot_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {{}}


def _active_shot_key(scene):
    choice = str(getattr(scene, "gpt_director_shot_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_shot", "") or "").strip()


def _shot_enum_items(self, context):
    items = [("__manual__", "手动输入/当前镜头", "使用下方镜头ID/名称输入框")]
    data = _load_meta()
    shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    seen = set(["__manual__"])
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("id") or "").strip()
        if not shot_id or shot_id in seen:
            continue
        name = str(shot.get("name") or shot_id).strip()
        output_label = str(shot.get("output_label") or shot.get("output_type") or "").strip()
        frame_start = shot.get("frame_start")
        frame_end = shot.get("frame_end")
        description_parts = []
        if output_label:
            description_parts.append(output_label)
        if frame_start is not None and frame_end is not None:
            description_parts.append("帧：" + str(frame_start) + "-" + str(frame_end))
        note = str(shot.get("note") or "").strip()
        if note:
            description_parts.append(note)
        description = "｜".join(description_parts) if description_parts else "保存镜头"
        label = name + (" · " + output_label if output_label else "")
        items.append((shot_id, label, description))
        seen.add(shot_id)
    return items


def _director_asset_kind_label(kind):
    labels = {{
        "character": "人物/角色",
        "prop": "物品/道具",
        "scene": "场景/布景",
        "action": "动作/动画",
        "model": "通用模型",
        "material": "材质",
        "texture": "贴图",
        "hdri": "HDRI",
    }}
    return labels.get(str(kind or ""), str(kind or "未分类"))


def _shot_asset_normalized_text(value):
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item or "") for item in value)
    elif isinstance(value, dict):
        value = " ".join(str(item or "") for item in value.values())
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _shot_asset_tokens(value):
    text = _shot_asset_normalized_text(value)
    parts = re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", text)
    return [part for part in parts if len(part) >= 2]


def _shot_asset_target_type(requirement):
    if not isinstance(requirement, dict):
        return ""
    if str(requirement.get("kind") or "") == "actor":
        return "character"
    asset_type = str(requirement.get("type") or "").strip().lower()
    aliases = {{
        "actor": "character",
        "person": "character",
        "human": "character",
        "role": "character",
        "object": "prop",
        "set": "scene",
        "environment": "scene",
    }}
    return aliases.get(asset_type, asset_type)


def _shot_asset_requirement_records(shot):
    requirements = []
    seen = set()
    if not isinstance(shot, dict):
        return requirements
    for actor in shot.get("actors") if isinstance(shot.get("actors"), list) else []:
        if not isinstance(actor, dict):
            continue
        key = "actor:" + str(actor.get("id") or actor.get("name") or actor.get("role") or "").strip()
        if key in seen or key == "actor:":
            continue
        seen.add(key)
        requirements.append({{
            "kind": "actor",
            "kind_label": "演员模型",
            "id": str(actor.get("id") or "").strip(),
            "name": str(actor.get("name") or actor.get("role") or actor.get("id") or "").strip(),
            "type": "character",
        }})
    for asset in shot.get("assets") if isinstance(shot.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        key = "asset:" + str(asset.get("id") or asset.get("name") or "").strip()
        if key in seen or key == "asset:":
            continue
        seen.add(key)
        asset_type = str(asset.get("type") or "").strip()
        requirements.append({{
            "kind": "asset",
            "kind_label": "镜头资产",
            "id": str(asset.get("id") or "").strip(),
            "name": str(asset.get("name") or asset.get("id") or "").strip(),
            "type": asset_type,
        }})
    return requirements


def _shot_asset_available(data, requirement):
    if not isinstance(data, dict) or not isinstance(requirement, dict):
        return False
    req_id = str(requirement.get("id") or "").strip()
    req_name = str(requirement.get("name") or "").strip()
    target_type = _shot_asset_target_type(requirement)
    if requirement.get("kind") == "actor":
        for actor in data.get("actors") if isinstance(data.get("actors"), list) else []:
            if not isinstance(actor, dict):
                continue
            has_objects = bool(actor.get("objects") if isinstance(actor.get("objects"), list) else [])
            if not has_objects:
                continue
            if req_id and req_id == str(actor.get("id") or ""):
                return True
            if req_name and req_name == str(actor.get("name") or ""):
                return True
    for asset in data.get("assets") if isinstance(data.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        asset_type = str(asset.get("type") or "").strip().lower()
        if target_type and asset_type and target_type != asset_type:
            if not (target_type == "character" and asset_type in ("actor", "person", "human")):
                continue
        if req_id and req_id == str(asset.get("id") or ""):
            return True
        if req_name and req_name == str(asset.get("name") or asset.get("file_name") or ""):
            return True
    return False


def _shot_asset_candidate_text(item):
    if not isinstance(item, dict):
        return ""
    return _shot_asset_normalized_text([
        item.get("id"),
        item.get("name"),
        item.get("file_name"),
        item.get("relative_path"),
        item.get("path"),
        item.get("kind_hint"),
        item.get("tags"),
        item.get("usage_note"),
        item.get("source_profile_name"),
        item.get("asset_browser_catalog_path"),
        item.get("asset_browser_catalog_name"),
    ])


def _score_shot_asset_candidate(data, requirement, item):
    if not isinstance(requirement, dict) or not isinstance(item, dict):
        return {{}}
    path = str(item.get("path") or "").strip()
    if not path or not os.path.exists(path) or not path.lower().endswith(SUPPORTED_LIBRARY_EXTENSIONS):
        return {{}}
    preflight = _asset_preflight_for_library_item(data, item)
    if preflight.get("blocked"):
        return {{}}
    target_type = _shot_asset_target_type(requirement)
    item_kind = str(item.get("kind_hint") or _asset_kind_from_path(path, item) or "model").strip().lower()
    req_name = str(requirement.get("name") or requirement.get("id") or "").strip()
    req_text = _shot_asset_normalized_text([requirement.get("id"), requirement.get("name"), requirement.get("type"), requirement.get("kind_label")])
    candidate_text = _shot_asset_candidate_text(item)
    score = 0.0
    reasons = []
    if target_type and item_kind == target_type:
        score += 0.36
        reasons.append("类型匹配：" + _director_asset_kind_label(target_type))
    elif target_type == "character" and item_kind == "model":
        score += 0.18
        reasons.append("通用模型可作人物候选")
    elif target_type in ("prop", "scene") and item_kind == "model":
        score += 0.16
        reasons.append("通用模型可作" + _director_asset_kind_label(target_type) + "候选")
    elif not target_type and item_kind in ("character", "prop", "scene", "model"):
        score += 0.12
        reasons.append("可作为镜头资产候选")
    normalized_name = _shot_asset_normalized_text(req_name)
    if normalized_name and (normalized_name in candidate_text or candidate_text in normalized_name):
        score += 0.42
        reasons.append("名称匹配")
    shared_tokens = []
    for token in _shot_asset_tokens(req_text):
        if token in candidate_text and token not in shared_tokens:
            shared_tokens.append(token)
    if shared_tokens:
        score += min(0.24, 0.08 * len(shared_tokens))
        reasons.append("关键词：" + "、".join(shared_tokens[:4]))
    if bool(item.get("favorite")):
        score += 0.04
        reasons.append("已收藏")
    try:
        usage_count = int(item.get("usage_count") or 0)
    except Exception:
        usage_count = 0
    if usage_count > 0:
        score += min(0.05, usage_count * 0.01)
        reasons.append("历史使用 " + str(usage_count) + " 次")
    if score <= 0:
        return {{}}
    return {{
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or item.get("file_name") or item.get("id") or "库资产"),
        "kind": item_kind,
        "kind_label": _director_asset_kind_label(item_kind),
        "format": str(item.get("format") or os.path.splitext(path)[1].lstrip(".").lower()),
        "path": path,
        "relative_path": str(item.get("relative_path") or ""),
        "library_id": str(item.get("library_id") or ""),
        "library_path": str(item.get("library_path") or ""),
        "source_profile_id": str(item.get("source_profile_id") or ""),
        "source_profile_name": str(item.get("source_profile_name") or ""),
        "score": round(min(score, 1.0), 4),
        "reasons": reasons,
        "preflight_status": str(preflight.get("status") or ""),
        "preflight_status_label": str(preflight.get("status_label") or ""),
    }}


def _shot_asset_candidates(data, requirement, limit=5):
    rows = []
    for item in data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []:
        candidate = _score_shot_asset_candidate(data, requirement, item)
        if candidate:
            rows.append(candidate)
    rows.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("name") or ""), str(item.get("id") or "")))
    return rows[:max(1, int(limit or 1))]


def _shot_asset_plan(data, shot):
    requirements = []
    ready_count = 0
    missing_count = 0
    candidate_count = 0
    for requirement in _shot_asset_requirement_records(shot):
        available = _shot_asset_available(data, requirement)
        candidates = _shot_asset_candidates(data, requirement, limit=5)
        row = dict(requirement)
        row["available"] = bool(available)
        row["status_label"] = "已具备" if available else "缺素材"
        row["library_candidates"] = candidates
        row["library_candidate_count"] = len(candidates)
        row["best_library_candidate"] = candidates[0] if candidates else {{}}
        candidate_count += len(candidates)
        if available:
            ready_count += 1
        else:
            missing_count += 1
        requirements.append(row)
    return {{
        "shot_id": str(shot.get("id") or ""),
        "shot_name": str(shot.get("name") or shot.get("id") or ""),
        "requirement_count": len(requirements),
        "ready_count": ready_count,
        "missing_count": missing_count,
        "library_candidate_count": candidate_count,
        "requirements": requirements,
    }}


def _active_shot_asset_plan(context):
    data = _load_meta()
    shot = _find_shot(data, _active_shot_key(context.scene))
    if not shot:
        return data, {{}}, {{}}
    return data, shot, _shot_asset_plan(data, shot)


def _draw_shot_asset_plan(layout, context):
    data, shot, plan = _active_shot_asset_plan(context)
    if not shot or not plan:
        return
    box = layout.box()
    box.label(text="镜头资产准备：" + str(plan.get("shot_name") or plan.get("shot_id") or "当前镜头"), icon="ASSET_MANAGER")
    box.label(text="已具备 " + str(plan.get("ready_count") or 0) + " / 缺 " + str(plan.get("missing_count") or 0) + " / 本地候选 " + str(plan.get("library_candidate_count") or 0))
    rows = plan.get("requirements") if isinstance(plan.get("requirements"), list) else []
    if not rows:
        box.label(text="当前镜头没有记录演员或资产依赖。")
        return
    for row_data in rows[:5]:
        if not isinstance(row_data, dict):
            continue
        icon = "CHECKMARK" if row_data.get("available") else "ERROR"
        label = str(row_data.get("name") or row_data.get("id") or "资产需求")
        box.label(text=str(row_data.get("kind_label") or "") + "：" + label + " · " + str(row_data.get("status_label") or ""), icon=icon)
        best = row_data.get("best_library_candidate") if isinstance(row_data.get("best_library_candidate"), dict) else {{}}
        if best and not row_data.get("available"):
            box.label(text="候选：" + str(best.get("name") or "") + " · " + str(best.get("kind_label") or best.get("kind") or "") + " · 匹配 " + str(best.get("score") or ""))


def _append_shot_asset_preparation(data, record):
    records = data.get("shot_asset_preparations")
    if not isinstance(records, list):
        records = []
    records.append(record)
    data["shot_asset_preparations"] = records[-500:]
    return record


AI_WORKFLOW_TASK_LABELS = {{
    "text_to_image_reference": "文生图/首帧参考",
    "image_to_video": "图生视频/镜头延展",
    "asset_generation": "资产生成/替换",
    "motion_generation": "动作生成/重定向",
}}


def _ai_status_label(status):
    labels = {{
        "ready": "可执行",
        "ready_with_reference": "参考图就绪",
        "ready_with_candidates": "有本地候选",
        "needs_generation": "需生成",
        "needs_motion": "需补动作",
        "review": "需复核",
        "blocked": "阻断",
    }}
    return labels.get(str(status or ""), str(status or "未定"))


def _ai_file_ref(path):
    path = str(path or "").strip()
    return {{
        "path": path,
        "exists": bool(path and os.path.exists(path)),
        "name": os.path.basename(path) if path else "",
    }}


def _ai_html_escape(text):
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _ai_item_names(items):
    names = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("role") or item.get("id") or "").strip()
        if name:
            names.append(name)
    return names


def _ai_prompt_for_shot(data, shot):
    project_name = str(data.get("project_name") or "AI短剧")
    actors = "、".join(_ai_item_names(shot.get("actors") if isinstance(shot, dict) else []))
    assets = "、".join(_ai_item_names(shot.get("assets") if isinstance(shot, dict) else []))
    parts = [
        "项目：" + project_name,
        "镜头：" + str(shot.get("name") or shot.get("id") or ""),
        "场次：" + str(shot.get("scene_number") or ""),
        "地点：" + str(shot.get("scene_location") or ""),
        "环境：" + str(shot.get("scene_environment_label") or shot.get("scene_environment") or ""),
        "时间：" + str(shot.get("scene_time_label") or shot.get("scene_time") or ""),
        "内容：" + str(shot.get("note") or ""),
        "演员：" + actors,
        "资产：" + assets,
        "输出：" + str(shot.get("output_label") or shot.get("output_type") or ""),
    ]
    return "；".join(part for part in parts if part and not part.endswith("："))


def _ai_renders_by_shot(data):
    renders_by_shot = {{}}
    for render in data.get("renders") if isinstance(data.get("renders"), list) else []:
        if not isinstance(render, dict):
            continue
        shot_id = str(render.get("shot_id") or "").strip()
        if shot_id:
            renders_by_shot[shot_id] = render
    return renders_by_shot


def _ai_actions_by_shot(data):
    match_data = _refresh_action_matches(data if isinstance(data, dict) else {{}})
    rows = {{}}
    for item in match_data.get("requirements", []) if isinstance(match_data, dict) else []:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if shot_id:
            rows.setdefault(shot_id, []).append(item)
    return rows, match_data


def _ai_task(task_id, task_type, status, shot, prompt, inputs=None, notes=None):
    inputs = inputs if isinstance(inputs, dict) else {{}}
    notes = notes if isinstance(notes, list) else ([] if notes in (None, "") else [str(notes)])
    return {{
        "id": _safe_id(task_id, "ai_task"),
        "type": task_type,
        "type_label": AI_WORKFLOW_TASK_LABELS.get(task_type, task_type),
        "status": status,
        "status_label": _ai_status_label(status),
        "shot_id": str(shot.get("id") or ""),
        "shot_name": str(shot.get("name") or shot.get("id") or ""),
        "scene_number": str(shot.get("scene_number") or ""),
        "scene_location": str(shot.get("scene_location") or ""),
        "frame_start": shot.get("frame_start"),
        "frame_end": shot.get("frame_end"),
        "output_type": str(shot.get("output_type") or ""),
        "output_label": str(shot.get("output_label") or shot.get("output_type") or ""),
        "prompt": prompt,
        "inputs": inputs,
        "notes": notes,
    }}


def _build_ai_workflow_tasks(data):
    data = data if isinstance(data, dict) else {{}}
    renders_by_shot = _ai_renders_by_shot(data)
    actions_by_shot, match_data = _ai_actions_by_shot(data)
    tasks = []
    type_counts = {{}}
    ready_count = 0
    review_count = 0
    blocked_count = 0
    for shot in data.get("shots") if isinstance(data.get("shots"), list) else []:
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("id") or "").strip()
        render = renders_by_shot.get(shot_id, {{}})
        preview_path = ""
        output_path = ""
        layer_paths = {{}}
        if isinstance(render, dict):
            preview_path = str(render.get("preview_path") or "").strip()
            path = str(render.get("path") or "").strip()
            output_path = str(render.get("output_path") or path).strip()
            if not preview_path and path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                preview_path = path
            layer_paths = render.get("layer_paths") if isinstance(render.get("layer_paths"), dict) else {{}}
        prompt = _ai_prompt_for_shot(data, shot)
        has_reference = bool(preview_path and os.path.exists(preview_path))
        visual_type = "image_to_video" if has_reference else "text_to_image_reference"
        visual_status = "ready_with_reference" if has_reference else "ready"
        visual_notes = []
        if not has_reference:
            visual_notes.append("没有可用预览图，可先生成首帧参考或执行 Blender 渲染。")
        if str(shot.get("output_type") or "") == "video":
            visual_notes.append("目标输出为视频，可用于图生视频或镜头延展。")
        tasks.append(_ai_task(
            "ai_visual_" + (shot_id or str(len(tasks) + 1)),
            visual_type,
            visual_status if prompt else "blocked",
            shot,
            prompt,
            {{
                "reference_image": _ai_file_ref(preview_path),
                "render_output": _ai_file_ref(output_path),
                "layer_paths": layer_paths,
                "actors": shot.get("actors") if isinstance(shot.get("actors"), list) else [],
                "assets": shot.get("assets") if isinstance(shot.get("assets"), list) else [],
            }},
            visual_notes,
        ))
        plan = _shot_asset_plan(data, shot)
        requirements = plan.get("requirements") if isinstance(plan.get("requirements"), list) else []
        missing = [item for item in requirements if isinstance(item, dict) and not item.get("available")]
        if missing:
            with_candidates = [
                item
                for item in missing
                if isinstance(item.get("best_library_candidate"), dict) and item.get("best_library_candidate")
            ]
            tasks.append(_ai_task(
                "ai_assets_" + (shot_id or str(len(tasks) + 1)),
                "asset_generation",
                "ready_with_candidates" if with_candidates else "needs_generation",
                shot,
                prompt,
                {{
                    "missing_requirements": missing,
                    "candidate_count": sum(int(item.get("library_candidate_count") or 0) for item in missing if isinstance(item, dict)),
                }},
                ["优先复用本地库候选；无候选条目可进入资产生成、模型修复或人工建模流程。"],
            ))
        shot_actions = actions_by_shot.get(shot_id, [])
        if shot_actions:
            unmatched = [item for item in shot_actions if isinstance(item, dict) and item.get("status") != "matched"]
            matched = [item for item in shot_actions if isinstance(item, dict) and item.get("status") == "matched"]
            tasks.append(_ai_task(
                "ai_motion_" + (shot_id or str(len(tasks) + 1)),
                "motion_generation",
                "needs_motion" if unmatched else "review",
                shot,
                prompt,
                {{
                    "action_requirements": shot_actions,
                    "matched_count": len(matched),
                    "unmatched_count": len(unmatched),
                }},
                ["已匹配动作可进入重定向/验证；待补动作可进入动作生成或动作库补充流程。"],
            ))
    for task in tasks:
        task_type = str(task.get("type") or "")
        status = str(task.get("status") or "")
        type_counts[task_type] = type_counts.get(task_type, 0) + 1
        if status == "blocked":
            blocked_count += 1
        elif status in ("review", "needs_generation", "needs_motion"):
            review_count += 1
        else:
            ready_count += 1
    return {{
        "project_id": str(data.get("project_id") or ""),
        "project_name": str(data.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shot_count": len(data.get("shots") if isinstance(data.get("shots"), list) else []),
        "task_count": len(tasks),
        "ready_count": ready_count,
        "review_count": review_count,
        "blocked_count": blocked_count,
        "task_type_counts": [
            {{"type": key, "type_label": AI_WORKFLOW_TASK_LABELS.get(key, key), "count": value}}
            for key, value in sorted(type_counts.items(), key=lambda row: (-row[1], row[0]))
        ],
        "action_match_summary": {{
            "requirement_count": int(match_data.get("requirement_count") or 0),
            "matched_count": int(match_data.get("matched_count") or 0),
            "unmatched_count": int(match_data.get("unmatched_count") or 0),
        }},
        "tasks": tasks,
    }}


def _write_ai_workflow_tasks(data):
    project_dir = os.path.dirname(META_PATH)
    _ensure_dir(project_dir)
    task_data = _build_ai_workflow_tasks(data)
    manifest_path = os.path.join(project_dir, "ai_workflow_tasks.json")
    report_path = os.path.join(project_dir, "ai_workflow_tasks.html")
    csv_path = os.path.join(project_dir, "ai_workflow_tasks.csv")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["任务ID", "任务类型", "状态", "镜头ID", "镜头名", "场次", "地点", "帧段", "输出", "参考图", "渲染输出", "提示词", "备注"])
        for task in task_data.get("tasks", []):
            if not isinstance(task, dict):
                continue
            inputs = task.get("inputs") if isinstance(task.get("inputs"), dict) else {{}}
            reference = inputs.get("reference_image") if isinstance(inputs.get("reference_image"), dict) else {{}}
            render_output = inputs.get("render_output") if isinstance(inputs.get("render_output"), dict) else {{}}
            frame_text = ""
            if task.get("frame_start") is not None and task.get("frame_end") is not None:
                frame_text = str(task.get("frame_start")) + "-" + str(task.get("frame_end"))
            writer.writerow([
                task.get("id") or "",
                task.get("type_label") or task.get("type") or "",
                task.get("status_label") or task.get("status") or "",
                task.get("shot_id") or "",
                task.get("shot_name") or "",
                task.get("scene_number") or "",
                task.get("scene_location") or "",
                frame_text,
                task.get("output_label") or task.get("output_type") or "",
                reference.get("path") or "",
                render_output.get("path") or "",
                task.get("prompt") or "",
                "；".join(str(note or "") for note in task.get("notes", []) if str(note or "").strip()),
            ])
    rows = []
    for task in task_data.get("tasks", []):
        if not isinstance(task, dict):
            continue
        inputs = task.get("inputs") if isinstance(task.get("inputs"), dict) else {{}}
        reference = inputs.get("reference_image") if isinstance(inputs.get("reference_image"), dict) else {{}}
        render_output = inputs.get("render_output") if isinstance(inputs.get("render_output"), dict) else {{}}
        notes = "；".join(str(note or "") for note in task.get("notes", []) if str(note or "").strip())
        rows.append(
            "<tr>"
            "<td><strong>" + _ai_html_escape(task.get("type_label") or task.get("type") or "") + "</strong><div>" + _ai_html_escape(task.get("id") or "") + "</div></td>"
            "<td>" + _ai_html_escape(task.get("shot_name") or task.get("shot_id") or "") + "</td>"
            "<td>" + _ai_html_escape(task.get("status_label") or task.get("status") or "") + "</td>"
            "<td>" + _ai_html_escape(reference.get("path") or "—") + "</td>"
            "<td>" + _ai_html_escape(render_output.get("path") or "—") + "</td>"
            "<td>" + _ai_html_escape(task.get("prompt") or "") + "</td>"
            "<td>" + _ai_html_escape(notes or "—") + "</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="7">暂无 AI 工作流任务。</td></tr>')
    html = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>AI 工作流任务包</title></head>
<body>
<h1>AI 工作流任务包</h1>
<p>本文件只整理本地任务，不调用外部 AI 服务。更新于 """ + _ai_html_escape(task_data.get("updated_at") or "") + """。</p>
<p>镜头 """ + str(task_data.get("shot_count") or 0) + """ 个，任务 """ + str(task_data.get("task_count") or 0) + """ 个，可执行 """ + str(task_data.get("ready_count") or 0) + """ 个，需生成/复核 """ + str(task_data.get("review_count") or 0) + """ 个。</p>
<table border="1" cellspacing="0" cellpadding="6">
<thead><tr><th>任务</th><th>镜头</th><th>状态</th><th>参考图</th><th>渲染输出</th><th>提示词</th><th>备注</th></tr></thead>
<tbody>""" + "".join(rows) + """</tbody>
</table>
</body>
</html>
"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    data["ai_workflow_tasks"] = task_data
    data["ai_workflow_tasks_manifest_path"] = manifest_path
    data["ai_workflow_tasks_report_path"] = report_path
    data["ai_workflow_tasks_csv_path"] = csv_path
    data["ai_workflow_tasks_updated_at"] = str(task_data.get("updated_at") or "")
    return task_data, manifest_path, report_path, csv_path


AI_WORKFLOW_EXPECTED_OUTPUTS = {{
    "text_to_image_reference": {{"label": "首帧/参考图", "extensions": ["png", "jpg", "jpeg", "webp", "exr"], "drop_hint": "把文生图或首帧参考图放入 results 目录，回 Blender 后登记为图片/首帧。"}},
    "image_to_video": {{"label": "视频镜头", "extensions": ["mp4", "mov", "avi", "mkv"], "drop_hint": "把图生视频或镜头延展结果放入 results 目录，回 Blender 后登记为视频。"}},
    "asset_generation": {{"label": "模型/资产", "extensions": ["blend", "glb", "gltf", "fbx", "obj", "stl", "ply", "abc", "usd", "usdz"], "drop_hint": "把生成或修复后的模型资产放入 results 目录，回 Blender 后登记为模型资产。"}},
    "motion_generation": {{"label": "动作文件", "extensions": ["bvh", "fbx"], "drop_hint": "把动作生成结果放入 results 目录，回 Blender 后登记为动作。"}},
}}


def _write_ai_workflow_handoff(data):
    project_dir = os.path.dirname(META_PATH)
    handoff_dir = os.path.join(project_dir, "ai_workflow_handoff")
    _ensure_dir(handoff_dir)
    task_data = data.get("ai_workflow_tasks") if isinstance(data.get("ai_workflow_tasks"), dict) else {{}}
    if not task_data.get("tasks"):
        task_data, _, _, _ = _write_ai_workflow_tasks(data)
    jobs = []
    for index, task in enumerate(task_data.get("tasks", []), start=1):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or ("ai_task_" + str(index))).strip()
        task_dir_name = _safe_id(task_id, "ai_task_" + str(index))
        job_dir = os.path.join(handoff_dir, task_dir_name)
        result_dir = os.path.join(job_dir, "results")
        _ensure_dir(result_dir)
        expected = AI_WORKFLOW_EXPECTED_OUTPUTS.get(str(task.get("type") or ""), {{"label": "AI 结果文件", "extensions": [], "drop_hint": "把外部 AI 输出文件放入 results 目录，回 Blender 后批量登记。"}})
        job = {{
            "task_id": task_id,
            "task_type": str(task.get("type") or ""),
            "task_type_label": str(task.get("type_label") or task.get("type") or ""),
            "status": str(task.get("status") or ""),
            "status_label": str(task.get("status_label") or task.get("status") or ""),
            "shot_id": str(task.get("shot_id") or ""),
            "shot_name": str(task.get("shot_name") or ""),
            "prompt": str(task.get("prompt") or ""),
            "notes": task.get("notes") if isinstance(task.get("notes"), list) else [],
            "expected_output": expected,
            "job_dir": job_dir,
            "result_dir": result_dir,
            "task_manifest_path": os.path.join(job_dir, "task.json"),
            "prompt_path": os.path.join(job_dir, "prompt.txt"),
            "notes_path": os.path.join(job_dir, "notes.txt"),
            "result_readme_path": os.path.join(result_dir, "README.txt"),
        }}
        with open(job["task_manifest_path"], "w", encoding="utf-8") as f:
            json.dump({{"task": task, "expected_output": expected, "result_dir": result_dir}}, f, ensure_ascii=False, indent=2)
        with open(job["prompt_path"], "w", encoding="utf-8") as f:
            f.write(str(task.get("prompt") or "").strip() + "\\n")
        with open(job["notes_path"], "w", encoding="utf-8") as f:
            f.write("\\n".join(str(note or "") for note in job["notes"] if str(note or "").strip()))
        with open(job["result_readme_path"], "w", encoding="utf-8") as f:
            f.write("AI 结果收件箱\\n任务ID：" + task_id + "\\n建议输出：" + str(expected.get("label") or "") + "\\n建议扩展名：" + "、".join(str(ext) for ext in expected.get("extensions", [])) + "\\n" + str(expected.get("drop_hint") or "") + "\\n")
        jobs.append(job)
    manifest = {{
        "project_id": str(data.get("project_id") or ""),
        "project_name": str(data.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "handoff_dir": handoff_dir,
        "task_count": len(jobs),
        "result_inbox_count": len(jobs),
        "jobs": jobs,
    }}
    manifest_path = os.path.join(handoff_dir, "handoff_manifest.json")
    report_path = os.path.join(handoff_dir, "handoff.html")
    csv_path = os.path.join(handoff_dir, "handoff.csv")
    readme_path = os.path.join(handoff_dir, "README.txt")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["任务ID", "任务类型", "状态", "镜头", "结果目录", "提示词文件", "建议输出"])
        for job in jobs:
            writer.writerow([job.get("task_id") or "", job.get("task_type_label") or "", job.get("status_label") or "", job.get("shot_name") or job.get("shot_id") or "", job.get("result_dir") or "", job.get("prompt_path") or "", (job.get("expected_output") or {{}}).get("label") or ""])
    rows = []
    for job in jobs:
        rows.append("<tr><td>" + _ai_html_escape(job.get("task_type_label") or job.get("task_id") or "") + "<div>" + _ai_html_escape(job.get("task_id") or "") + "</div></td><td>" + _ai_html_escape(job.get("shot_name") or job.get("shot_id") or "") + "</td><td>" + _ai_html_escape(job.get("status_label") or "") + "</td><td>" + _ai_html_escape((job.get("expected_output") or {{}}).get("label") or "") + "</td><td>" + _ai_html_escape(job.get("result_dir") or "") + "</td></tr>")
    if not rows:
        rows.append('<tr><td colspan="5">暂无 AI 工作包任务。</td></tr>')
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("<!doctype html><html lang=\\"zh-CN\\"><head><meta charset=\\"utf-8\\"><title>AI 工作包与结果收件箱</title></head><body><h1>AI 工作包与结果收件箱</h1><p>每个任务目录包含 prompt.txt、task.json 和 results 收件箱。</p><table border=\\"1\\" cellspacing=\\"0\\" cellpadding=\\"6\\"><thead><tr><th>任务</th><th>镜头</th><th>状态</th><th>建议输出</th><th>结果目录</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></body></html>")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("AI 工作包与结果收件箱\\n把外部 AI 输出文件放入各任务 results 目录，然后使用“批量登记AI结果目录”。\\n")
    data["ai_workflow_handoff_dir"] = handoff_dir
    data["ai_workflow_handoff_manifest_path"] = manifest_path
    data["ai_workflow_handoff_report_path"] = report_path
    data["ai_workflow_handoff_csv_path"] = csv_path
    data["ai_workflow_handoff_readme_path"] = readme_path
    return manifest, manifest_path, report_path, csv_path, readme_path


AI_RESULT_EXTENSIONS = (".blend", ".glb", ".gltf", ".fbx", ".obj", ".bvh", ".stl", ".ply", ".abc", ".usd", ".usdz", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4", ".mov", ".avi", ".mkv", ".exr", ".hdr")
AI_RESULT_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".exr", ".hdr")
AI_RESULT_VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv")


def _ai_result_type_from_path(path, selected_type="auto"):
    selected_type = str(selected_type or "auto")
    if selected_type and selected_type != "auto":
        return selected_type
    lower = str(path or "").lower()
    if lower.endswith((".blend", ".glb", ".gltf", ".fbx", ".obj", ".stl", ".ply", ".abc", ".usd", ".usdz")):
        return "asset"
    if lower.endswith(".bvh"):
        return "motion"
    if lower.endswith(AI_RESULT_VIDEO_EXTENSIONS):
        return "video"
    if lower.endswith(AI_RESULT_IMAGE_EXTENSIONS):
        return "image"
    return "attachment"


def _active_ai_task_id(scene):
    return str(getattr(scene, "gpt_director_ai_task_id", "") or "").strip()


def _active_ai_result_note(scene):
    return str(getattr(scene, "gpt_director_ai_result_note", "") or "").strip()


def _append_ai_workflow_result(data, record):
    results = data.get("ai_workflow_results")
    if not isinstance(results, list):
        results = []
    results.append(record)
    data["ai_workflow_results"] = results[-500:]
    return record


def _find_ai_task(data, task_id):
    task_id = str(task_id or "").strip()
    task_data = data.get("ai_workflow_tasks") if isinstance(data.get("ai_workflow_tasks"), dict) else {{}}
    tasks = task_data.get("tasks") if isinstance(task_data.get("tasks"), list) else []
    for task in tasks:
        if isinstance(task, dict) and task_id and str(task.get("id") or "") == task_id:
            return dict(task)
    # If the in-memory task package is stale or absent, rebuild from the current project state.
    try:
        rebuilt = _build_ai_workflow_tasks(data)
        for task in rebuilt.get("tasks", []):
            if isinstance(task, dict) and task_id and str(task.get("id") or "") == task_id:
                data["ai_workflow_tasks"] = rebuilt
                return dict(task)
    except Exception:
        pass
    return {{}}


def _ai_result_task_id_from_path(data, filepath, fallback=""):
    fallback = str(fallback or "").strip()
    if fallback:
        return fallback
    filename = os.path.basename(str(filepath or "")).lower()
    if not filename:
        return ""
    task_data = data.get("ai_workflow_tasks") if isinstance(data.get("ai_workflow_tasks"), dict) else {{}}
    tasks = task_data.get("tasks") if isinstance(task_data.get("tasks"), list) else []
    if not tasks:
        try:
            task_data = _build_ai_workflow_tasks(data)
            data["ai_workflow_tasks"] = task_data
            tasks = task_data.get("tasks") if isinstance(task_data.get("tasks"), list) else []
        except Exception:
            tasks = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or "").strip()
        if task_id and task_id.lower() in filename:
            return task_id
    return ""


def _ai_result_target_shot(data, task_id):
    task = _find_ai_task(data, task_id)
    shot_id = str(task.get("shot_id") or "").strip()
    shot_name = str(task.get("shot_name") or "").strip()
    if shot_id or shot_name:
        shot = _find_shot(data, shot_id or shot_name)
        if shot:
            return shot, task
    return {{}}, task


def _register_ai_render_result(data, filepath, result_type, task_id="", note=""):
    shot, task = _ai_result_target_shot(data, task_id)
    shot_id = str(shot.get("id") or task.get("shot_id") or "").strip()
    shot_name = str(shot.get("name") or task.get("shot_name") or "").strip()
    output_type = "video" if result_type == "video" else "still"
    output_label = RENDER_OUTPUT_LABELS.get(output_type, output_type)
    render_version = _next_render_version(data, shot_id) if shot_id else 1
    record = {{
        "path": filepath,
        "output_path": filepath,
        "preview_path": filepath if result_type == "image" else "",
        "output_type": output_type,
        "output_label": output_label,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "ai_workflow_result",
        "shot_id": shot_id,
        "shot_name": shot_name,
        "render_version": render_version,
        "ai_task_id": str(task_id or ""),
        "ai_result_type": result_type,
        "note": str(note or ""),
    }}
    if result_type == "video":
        task_inputs = task.get("inputs") if isinstance(task.get("inputs"), dict) else {{}}
        reference = task_inputs.get("reference_image") if isinstance(task_inputs.get("reference_image"), dict) else {{}}
        record["preview_path"] = str(reference.get("path") or "")
    _record_render(data, record)
    if shot:
        updated = dict(shot)
        updated["last_rendered_at"] = record["created_at"]
        updated["render_version"] = render_version
        if result_type == "image":
            updated["preview_path"] = filepath
        updated["output_type"] = output_type
        updated["output_label"] = output_label
        _upsert_shot(data, updated)
        _save_shot_file(updated)
    return record


def _register_ai_asset_result(data, filepath, result_type, task_id="", note=""):
    shot, task = _ai_result_target_shot(data, task_id)
    actor, target_armature = _active_action_target(data)
    asset_kind = "action" if result_type == "motion" or str(filepath).lower().endswith(".bvh") else _asset_kind_from_path(filepath)
    label = str(task.get("shot_name") or os.path.basename(filepath))
    record = _import_director_asset(filepath, asset_kind, label, target_armature if asset_kind == "action" else None)
    record["generated_by"] = "ai_workflow"
    record["ai_task_id"] = str(task_id or "")
    record["ai_result_type"] = result_type
    record["ai_result_note"] = str(note or "")
    record["prepared_for_shot_id"] = str(shot.get("id") or task.get("shot_id") or "")
    record["prepared_for_shot_name"] = str(shot.get("name") or task.get("shot_name") or "")
    if asset_kind == "action":
        _record_action_application(
            data,
            record.get("target_armature", target_armature.name if target_armature else ""),
            (record.get("actions") or [""])[-1] if isinstance(record.get("actions"), list) else "",
            record.get("auto_apply_status", "not_applied"),
            record.get("auto_apply_message", ""),
            actor,
        )
        _upsert_action_clip_from_asset_record(data, record, actor, target_armature, {{}}, str(note or "AI 工作流生成动作"))
    _append_asset_record(data, record)
    return record


def _register_ai_workflow_result(data, filepath, result_type="auto", task_id="", note=""):
    filepath = str(filepath or "").strip()
    if not filepath or not os.path.exists(filepath):
        raise RuntimeError("AI 结果文件不存在")
    result_type = _ai_result_type_from_path(filepath, result_type)
    if result_type in ("image", "video"):
        payload = _register_ai_render_result(data, filepath, result_type, task_id, note)
        target_type = "render"
    elif result_type in ("asset", "motion"):
        payload = _register_ai_asset_result(data, filepath, result_type, task_id, note)
        target_type = "asset"
    else:
        payload = {{"path": filepath, "name": os.path.basename(filepath)}}
        target_type = "attachment"
    record = {{
        "id": _safe_id("ai_result_" + os.path.splitext(os.path.basename(filepath))[0] + "_" + datetime.now().strftime("%H%M%S"), "ai_result"),
        "task_id": str(task_id or ""),
        "result_type": result_type,
        "target_type": target_type,
        "path": filepath,
        "payload_id": str(payload.get("id") or payload.get("shot_id") or ""),
        "payload_name": str(payload.get("name") or payload.get("shot_name") or os.path.basename(filepath)),
        "note": str(note or ""),
        "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    _append_ai_workflow_result(data, record)
    return record, payload


ACTION_MATCH_GROUPS = (
    ("走路", ("走路", "行走", "走入", "走进", "进入", "进门", "走到", "步行", "walk", "walking")),
    ("跑步", ("跑步", "奔跑", "冲向", "跑向", "逃跑", "run", "running", "sprint")),
    ("坐下", ("坐下", "落座", "入座", "坐到", "sit", "sitting")),
    ("站起", ("站起", "起身", "站起来", "stand up", "standing up")),
    ("转身", ("转身", "回头", "转向", "扭头", "turn", "turning")),
    ("挥手", ("挥手", "招手", "挥别", "告别", "wave", "waving")),
    ("打斗", ("打斗", "搏斗", "攻击", "出拳", "拳击", "踢打", "fight", "punch", "attack", "kick")),
    ("跌倒", ("跌倒", "摔倒", "倒地", "倒下", "fall", "falling")),
    ("说话", ("说话", "对话", "交谈", "争吵", "演讲", "talk", "talking", "speak", "dialogue")),
    ("停顿", ("停顿", "停下", "站定", "待机", "静止", "idle", "pause", "stop")),
    ("开门", ("开门", "推门", "拉门", "open door", "door open")),
    ("关门", ("关门", "合门", "close door", "door close")),
    ("拿取", ("拿起", "拿着", "拾取", "抓住", "取出", "pick up", "grab", "hold")),
    ("放下", ("放下", "放回", "搁下", "put down", "drop")),
    ("鞠躬", ("鞠躬", "弯腰致意", "bow", "bowing")),
    ("跳跃", ("跳跃", "跳起", "跃起", "jump", "jumping")),
    ("拥抱", ("拥抱", "抱住", "相拥", "hug", "hugging")),
)


def _action_match_text(value):
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item or "") for item in value)
    elif isinstance(value, dict):
        value = " ".join(str(item or "") for item in value.values())
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _action_match_keywords(text):
    normalized = _action_match_text(text)
    keywords = []
    matched_terms = {{}}
    for label, terms in ACTION_MATCH_GROUPS:
        hits = [term for term in terms if term.lower() in normalized]
        if hits:
            keywords.append(label)
            matched_terms[label] = hits
    return keywords, matched_terms


def _action_match_actor_ref(actor):
    if not isinstance(actor, dict):
        return {{}}
    return {{
        "id": str(actor.get("id") or "").strip(),
        "name": str(actor.get("name") or "").strip(),
        "role": str(actor.get("role") or "").strip(),
    }}


def _action_match_candidate(item, origin, index):
    if not isinstance(item, dict):
        return {{}}
    candidate_id = str(item.get("id") or item.get("asset_id") or item.get("library_item_id") or "").strip()
    name = str(item.get("name") or item.get("file_name") or item.get("action") or candidate_id or "动作" + str(index)).strip()
    action = str(item.get("action") or name).strip()
    search_text = _action_match_text([
        name,
        action,
        item.get("note"),
        item.get("tags"),
        item.get("usage_note"),
        item.get("relative_path"),
        item.get("library_relative_path"),
        item.get("path"),
        item.get("source_profile_name"),
        item.get("retarget_profile_name"),
        item.get("retarget_source_action"),
        item.get("retarget_source_clip_name"),
    ])
    keywords, matched_terms = _action_match_keywords(search_text)
    try:
        usage_count = max(0, int(item.get("usage_count") or 0))
    except Exception:
        usage_count = 0
    return {{
        "id": candidate_id or origin + "_" + str(index),
        "name": name,
        "action": action,
        "origin": origin,
        "origin_label": {{
            "action_clip": "工程动作片段",
            "asset_library": "动作库资产",
            "asset": "工程动作资产",
        }}.get(origin, origin),
        "actor": _action_match_actor_ref(item.get("actor")),
        "target_armature": str(item.get("target_armature") or "").strip(),
        "frame_start": item.get("frame_start"),
        "frame_end": item.get("frame_end"),
        "frame_count": item.get("frame_count"),
        "source_profile_id": str(item.get("source_profile_id") or "").strip(),
        "source_profile_name": str(item.get("source_profile_name") or "").strip(),
        "library_item_id": str(item.get("library_item_id") or "").strip(),
        "library_path": str(item.get("library_path") or "").strip(),
        "library_relative_path": str(item.get("library_relative_path") or item.get("relative_path") or "").strip(),
        "path": str(item.get("path") or item.get("source_path") or "").strip(),
        "format": str(item.get("format") or "").strip(),
        "favorite": bool(item.get("favorite")),
        "usage_count": usage_count,
        "generated_by": str(item.get("generated_by") or "").strip(),
        "retarget_profile_id": str(item.get("retarget_profile_id") or "").strip(),
        "retarget_profile_name": str(item.get("retarget_profile_name") or "").strip(),
        "retarget_source_action": str(item.get("retarget_source_action") or "").strip(),
        "retarget_source_clip_name": str(item.get("retarget_source_clip_name") or "").strip(),
        "retarget_quality": item.get("retarget_quality") if isinstance(item.get("retarget_quality"), dict) else {{}},
        "keywords": keywords,
        "matched_terms": matched_terms,
        "_search_text": search_text,
    }}


def _action_match_candidates(data):
    candidates = []
    seen = set()
    index = 0
    for clip in data.get("action_clips") if isinstance(data.get("action_clips"), list) else []:
        index += 1
        candidate = _action_match_candidate(clip, "action_clip", index)
        key = (candidate.get("origin"), candidate.get("id"), candidate.get("action"), candidate.get("path"))
        if key not in seen:
            candidates.append(candidate)
            seen.add(key)
    for item in data.get("asset_library_items") if isinstance(data.get("asset_library_items"), list) else []:
        if not isinstance(item, dict) or str(item.get("kind_hint") or "").strip().lower() != "action":
            continue
        index += 1
        candidate = _action_match_candidate(item, "asset_library", index)
        key = (candidate.get("origin"), candidate.get("id"), candidate.get("action"), candidate.get("path"))
        if key not in seen:
            candidates.append(candidate)
            seen.add(key)
    for asset in data.get("assets") if isinstance(data.get("assets"), list) else []:
        if not isinstance(asset, dict) or str(asset.get("type") or "").strip().lower() != "action":
            continue
        index += 1
        candidate = _action_match_candidate(asset, "asset", index)
        key = (candidate.get("origin"), candidate.get("id"), candidate.get("action"), candidate.get("path"))
        if key not in seen:
            candidates.append(candidate)
            seen.add(key)
    return candidates


def _score_action_match(requirement, candidate):
    requirement_keywords = set(requirement.get("keywords") if isinstance(requirement.get("keywords"), list) else [])
    candidate_keywords = set(candidate.get("keywords") if isinstance(candidate.get("keywords"), list) else [])
    shared_keywords = sorted(requirement_keywords & candidate_keywords)
    score = min(0.64, 0.32 * len(shared_keywords))
    reasons = []
    if shared_keywords:
        reasons.append("动作词：" + "、".join(shared_keywords))
    query_text = _action_match_text(requirement.get("query"))
    phrase_hit = False
    for phrase in (
        _action_match_text(candidate.get("name")),
        _action_match_text(candidate.get("action")),
        _action_match_text(candidate.get("retarget_source_clip_name")),
    ):
        if len(phrase) >= 2 and (phrase in query_text or query_text in phrase):
            phrase_hit = True
            break
    if phrase_hit:
        score += 0.2
        reasons.append("镜头描述与动作名称直接对应")
    requirement_actor = requirement.get("actor") if isinstance(requirement.get("actor"), dict) else {{}}
    candidate_actor = candidate.get("actor") if isinstance(candidate.get("actor"), dict) else {{}}
    requirement_actor_keys = set([
        str(requirement_actor.get("id") or "").strip(),
        str(requirement_actor.get("name") or "").strip(),
        str(requirement_actor.get("role") or "").strip(),
    ])
    candidate_actor_keys = set([
        str(candidate_actor.get("id") or "").strip(),
        str(candidate_actor.get("name") or "").strip(),
        str(candidate_actor.get("role") or "").strip(),
    ])
    requirement_actor_keys.discard("")
    candidate_actor_keys.discard("")
    if requirement_actor_keys and candidate_actor_keys and requirement_actor_keys & candidate_actor_keys:
        score += 0.18
        reasons.append("演员绑定：" + str(requirement_actor.get("name") or requirement_actor.get("role") or requirement_actor.get("id") or "已匹配"))
    origin = str(candidate.get("origin") or "")
    if origin == "action_clip":
        score += 0.08
        reasons.append("优先复用工程动作片段")
    elif origin == "asset_library":
        score += 0.04
        reasons.append("来自动作资产库")
    source_name = str(candidate.get("source_profile_name") or "")
    if "mixamo" in source_name.lower():
        score += 0.03
        reasons.append("来源：Mixamo 动作生态")
    if str(candidate.get("generated_by") or "") == "retarget":
        score += 0.05
        reasons.append("已完成目标骨骼重定向")
    if candidate.get("favorite"):
        score += 0.03
        reasons.append("已收藏")
    usage_count = int(candidate.get("usage_count") or 0)
    if usage_count > 0:
        score += min(0.05, usage_count * 0.01)
        reasons.append("已有 " + str(usage_count) + " 次使用记录")
    if not shared_keywords and not phrase_hit:
        return 0.0, [], []
    return round(min(1.0, max(0.0, score)), 3), reasons, shared_keywords


def _public_action_match_candidate(candidate, score=0.0, reasons=None, shared_keywords=None):
    return {{
        "id": candidate.get("id") or "",
        "name": candidate.get("name") or "",
        "action": candidate.get("action") or "",
        "origin": candidate.get("origin") or "",
        "origin_label": candidate.get("origin_label") or "",
        "actor": candidate.get("actor") if isinstance(candidate.get("actor"), dict) else {{}},
        "target_armature": candidate.get("target_armature") or "",
        "frame_start": candidate.get("frame_start"),
        "frame_end": candidate.get("frame_end"),
        "frame_count": candidate.get("frame_count"),
        "source_profile_id": candidate.get("source_profile_id") or "",
        "source_profile_name": candidate.get("source_profile_name") or "",
        "library_item_id": candidate.get("library_item_id") or "",
        "library_path": candidate.get("library_path") or "",
        "library_relative_path": candidate.get("library_relative_path") or "",
        "path": candidate.get("path") or "",
        "format": candidate.get("format") or "",
        "favorite": bool(candidate.get("favorite")),
        "usage_count": int(candidate.get("usage_count") or 0),
        "generated_by": candidate.get("generated_by") or "",
        "retarget_profile_id": candidate.get("retarget_profile_id") or "",
        "retarget_profile_name": candidate.get("retarget_profile_name") or "",
        "retarget_source_action": candidate.get("retarget_source_action") or "",
        "retarget_source_clip_name": candidate.get("retarget_source_clip_name") or "",
        "retarget_quality": candidate.get("retarget_quality") if isinstance(candidate.get("retarget_quality"), dict) else {{}},
        "keywords": candidate.get("keywords") if isinstance(candidate.get("keywords"), list) else [],
        "score": score,
        "reasons": reasons or [],
        "shared_keywords": shared_keywords or [],
    }}


def _build_action_matches(data):
    candidates = _action_match_candidates(data)
    requirements = []
    shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    for shot_index, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("id") or "shot_" + str(shot_index)).strip()
        shot_name = str(shot.get("name") or shot_id or "镜头" + str(shot_index)).strip()
        query = "；".join(part for part in (
            shot_name,
            str(shot.get("note") or "").strip(),
            str(shot.get("scene_location") or "").strip(),
            str(shot.get("scene_environment_label") or shot.get("scene_environment") or "").strip(),
        ) if part)
        keywords, matched_terms = _action_match_keywords(query)
        actors = [item for item in (shot.get("actors") if isinstance(shot.get("actors"), list) else []) if isinstance(item, dict)]
        actor_rows = actors or [{{}}]
        for actor_index, actor in enumerate(actor_rows, 1):
            actor_ref = _action_match_actor_ref(actor)
            requirement = {{
                "id": _safe_id("action_requirement_" + shot_id + "_" + str(actor_ref.get("id") or actor_ref.get("name") or actor_index), "action_requirement"),
                "shot_id": shot_id,
                "shot_name": shot_name,
                "shot_index": shot_index,
                "note": str(shot.get("note") or ""),
                "scene_location": str(shot.get("scene_location") or ""),
                "actor": actor_ref,
                "query": query,
                "keywords": keywords,
                "matched_terms": matched_terms,
            }}
            scored = []
            for candidate in candidates:
                score, reasons, shared = _score_action_match(requirement, candidate)
                scored.append((score, candidate, reasons, shared))
            scored.sort(key=lambda row: (-row[0], 0 if str(row[1].get("origin") or "") == "action_clip" else 1, str(row[1].get("name") or "")))
            best = scored[0] if scored and scored[0][0] >= 0.28 else None
            alternatives = [
                _public_action_match_candidate(candidate, score, reasons, shared)
                for score, candidate, reasons, shared in scored
                if score >= 0.18 and (best is None or candidate is not best[1])
            ][:3]
            if best:
                requirement["status"] = "matched"
                requirement["status_label"] = "已匹配"
                requirement["best_match"] = _public_action_match_candidate(best[1], best[0], best[2], best[3])
                requirement["match_note"] = (
                    "动作片段已完成目标骨骼重定向，可直接进入镜头验证。"
                    if str(best[1].get("generated_by") or "") == "retarget"
                    else "动作片段可直接复用；跨骨架资产仍需后续人工确认或骨骼重定向。"
                )
            else:
                requirement["status"] = "unmatched"
                requirement["status_label"] = "待补动作"
                requirement["best_match"] = {{}}
                requirement["match_note"] = "现有动作片段和动作资产库没有达到匹配阈值，请补充动作或人工指定。"
            requirement["alternatives"] = alternatives
            requirement["candidate_count"] = len(candidates)
            requirements.append(requirement)
    matched_count = sum(1 for item in requirements if item.get("status") == "matched")
    return {{
        "project_id": str(data.get("project_id") or ""),
        "project_name": str(data.get("project_name") or "Blender 导演台工程"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candidate_count": len(candidates),
        "requirement_count": len(requirements),
        "matched_count": matched_count,
        "unmatched_count": len(requirements) - matched_count,
        "requirements": requirements,
    }}


def _refresh_action_matches(data):
    match_data = _build_action_matches(data if isinstance(data, dict) else {{}})
    data["action_matches"] = match_data.get("requirements", [])
    data["action_match_count"] = int(match_data.get("matched_count") or 0)
    data["action_match_requirement_count"] = int(match_data.get("requirement_count") or 0)
    data["action_unmatched_count"] = int(match_data.get("unmatched_count") or 0)
    data["action_matches_updated_at"] = str(match_data.get("updated_at") or "")
    return match_data


def _active_shot_action_requirement(data, scene):
    key = _active_shot_key(scene)
    match_data = _refresh_action_matches(data)
    requirements = match_data.get("requirements") if isinstance(match_data.get("requirements"), list) else []
    if key:
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            if key in (str(requirement.get("shot_id") or ""), str(requirement.get("shot_name") or "")):
                return requirement
    for requirement in requirements:
        if isinstance(requirement, dict) and requirement.get("best_match"):
            return requirement
    return {{}}


def _save_shot_file(shot):
    if not isinstance(shot, dict):
        return
    shot_id = _safe_id(shot.get("id") or shot.get("name") or "shot", "shot")
    _ensure_dir(SHOTS_DIR)
    path = os.path.join(SHOTS_DIR, shot_id + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(shot, f, ensure_ascii=False, indent=2)


def _delete_shot_file(shot):
    if not isinstance(shot, dict):
        return
    shot_id = _safe_id(shot.get("id") or shot.get("name") or "shot", "shot")
    path = os.path.join(SHOTS_DIR, shot_id + ".json")
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _timeline_marker_name(shot):
    if not isinstance(shot, dict):
        return "SHOT"
    shot_id = _safe_id(shot.get("id") or shot.get("name") or "shot", "shot")
    name = str(shot.get("name") or shot_id).strip()
    if name and name != shot_id:
        return "SHOT " + shot_id + " - " + name
    return "SHOT " + shot_id


def _upsert_timeline_marker(scene, shot):
    if not isinstance(shot, dict):
        return None
    frame = int(shot.get("frame") or scene.frame_current)
    marker_name = _timeline_marker_name(shot)
    marker = None
    for item in scene.timeline_markers:
        if item.name == marker_name:
            marker = item
            break
    if marker is None:
        marker = scene.timeline_markers.new(marker_name, frame=frame)
    else:
        marker.frame = frame
    if scene.camera:
        try:
            marker.camera = scene.camera
        except Exception:
            pass
    return marker


def _delete_timeline_marker(scene, shot):
    marker_name = _timeline_marker_name(shot)
    for item in list(scene.timeline_markers):
        if item.name == marker_name:
            try:
                scene.timeline_markers.remove(item)
            except Exception:
                pass


def _delete_shot(data, shot):
    if not isinstance(shot, dict):
        return False
    shot_id = str(shot.get("id") or "").strip()
    shot_name = str(shot.get("name") or "").strip()
    shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    kept = []
    removed = False
    for item in shots:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (shot_id and str(item.get("id") or "") == shot_id) or (shot_name and str(item.get("name") or "") == shot_name):
            removed = True
            continue
        kept.append(item)
    data["shots"] = kept
    return removed


def _active_shot_package_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_shot_package_name", "") or "").strip()
    return name or "未命名镜头包"


def _active_shot_package_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_shot_package_note", "") or "").strip()


def _copy_shot_for_package(shot):
    try:
        return json.loads(json.dumps(shot, ensure_ascii=False))
    except Exception:
        return dict(shot)


def _shot_package_from_saved_shots(data, package_id, package_name, package_note):
    shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    package_shots = []
    for shot in shots:
        if not isinstance(shot, dict) or not (shot.get("id") or shot.get("name")):
            continue
        package_shots.append(_copy_shot_for_package(shot))
    if not package_shots:
        raise RuntimeError("当前还没有可保存到镜头包的镜头，请先保存至少一个镜头")
    return {{
        "id": package_id,
        "name": package_name,
        "note": package_note,
        "shots": package_shots,
        "shot_count": len(package_shots),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_shot_package(data, package):
    packages = data.get("shot_packages")
    if not isinstance(packages, list):
        packages = []
    package_id = package.get("id")
    replaced = False
    for idx, existing in enumerate(packages):
        if isinstance(existing, dict) and existing.get("id") == package_id:
            merged = dict(existing)
            merged.update(package)
            packages[idx] = merged
            replaced = True
            break
    if not replaced:
        packages.append(package)
    data["shot_packages"] = packages[-500:]
    return data


def _active_shot_package_key(scene):
    choice = str(getattr(scene, "gpt_director_shot_package_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_shot_package", "") or "").strip()


def _shot_package_enum_items(self, context):
    items = [("__manual__", "手动输入/当前镜头列表", "使用下方镜头包ID/名称输入框")]
    data = _load_meta()
    packages = data.get("shot_packages") if isinstance(data.get("shot_packages"), list) else []
    seen = set(["__manual__"])
    for package in packages:
        if not isinstance(package, dict):
            continue
        package_id = str(package.get("id") or "").strip()
        if not package_id or package_id in seen:
            continue
        name = str(package.get("name") or package_id).strip()
        shots = package.get("shots") if isinstance(package.get("shots"), list) else []
        shot_names = [
            str(item.get("name") or item.get("id") or "").strip()
            for item in shots
            if isinstance(item, dict) and str(item.get("name") or item.get("id") or "").strip()
        ]
        detail_parts = []
        if shots:
            detail_parts.append("镜头 " + str(len(shots)) + " 个")
        if shot_names:
            label = "、".join(shot_names[:4])
            if len(shot_names) > 4:
                label += " 等 " + str(len(shot_names)) + " 个"
            detail_parts.append(label)
        note = str(package.get("note") or "").strip()
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "镜头包"
        items.append((package_id, name, description))
        seen.add(package_id)
    return items


def _find_shot_package(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_shot_package_name()
    packages = data.get("shot_packages") if isinstance(data.get("shot_packages"), list) else []
    for package in reversed(packages):
        if not isinstance(package, dict):
            continue
        if key in (str(package.get("id") or ""), str(package.get("name") or "")):
            return dict(package)
    return {{}}


def _delete_shot_package(data, package):
    if not isinstance(package, dict):
        return False
    package_id = str(package.get("id") or "").strip()
    package_name = str(package.get("name") or "").strip()
    packages = data.get("shot_packages") if isinstance(data.get("shot_packages"), list) else []
    kept = []
    removed = False
    for item in packages:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (package_id and str(item.get("id") or "") == package_id) or (package_name and str(item.get("name") or "") == package_name):
            removed = True
            continue
        kept.append(item)
    data["shot_packages"] = kept
    return removed


def _load_shot_package_into_project(context, data, package):
    if not isinstance(package, dict):
        return 0
    source_shots = package.get("shots") if isinstance(package.get("shots"), list) else []
    if not source_shots:
        raise RuntimeError("镜头包里没有可加载的镜头")
    existing_shots = data.get("shots") if isinstance(data.get("shots"), list) else []
    existing_ids = set(
        str(item.get("id") or "")
        for item in existing_shots
        if isinstance(item, dict) and str(item.get("id") or "")
    )
    package_id = str(package.get("id") or "").strip()
    package_name = str(package.get("name") or "").strip()
    stamp = datetime.now().strftime("%H%M%S")
    loaded = 0
    for idx, shot in enumerate(source_shots, 1):
        if not isinstance(shot, dict):
            continue
        copied = _copy_shot_for_package(shot)
        base = str(copied.get("id") or copied.get("name") or "shot")
        new_id = _safe_id(base + "_" + stamp + "_" + str(idx), "shot")
        attempt = 1
        while new_id in existing_ids:
            attempt += 1
            new_id = _safe_id(base + "_" + stamp + "_" + str(idx) + "_" + str(attempt), "shot")
        copied["id"] = new_id
        copied["source_package_id"] = package_id
        copied["source_package_name"] = package_name
        copied["loaded_from_package_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _upsert_shot(data, copied)
        _save_shot_file(copied)
        _upsert_timeline_marker(context.scene, copied)
        existing_ids.add(new_id)
        loaded += 1
    return loaded


def _active_set_package_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_set_package_name", "") or "").strip()
    return name or "未命名布景包"


def _active_set_package_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_set_package_note", "") or "").strip()


def _set_package_path(package_id):
    _ensure_dir(SET_PACKAGES_DIR)
    return os.path.join(SET_PACKAGES_DIR, _safe_id(package_id, "set_package") + ".blend")


def _selected_set_package_objects(context):
    objects = [obj for obj in (context.selected_objects or []) if obj is not None]
    if not objects:
        raise RuntimeError("请先选中要保存为布景包的场景、人物、道具或灯光")
    return objects


def _write_set_package_blend(filepath, objects):
    _ensure_dir(os.path.dirname(filepath))
    datablocks = set(obj for obj in objects if obj is not None)
    if not datablocks:
        raise RuntimeError("没有可保存到布景包的对象")
    try:
        bpy.data.libraries.write(filepath, datablocks, fake_user=True, compress=True)
    except TypeError:
        try:
            bpy.data.libraries.write(filepath, datablocks, fake_user=True)
        except TypeError:
            bpy.data.libraries.write(filepath, datablocks)
    except Exception as exc:
        raise RuntimeError("保存布景包失败：" + str(exc))
    return filepath


def _set_package_from_selected_objects(context, package_id, package_name, package_note):
    objects = _selected_set_package_objects(context)
    path = _set_package_path(package_id)
    _write_set_package_blend(path, objects)
    collection_names = []
    for obj in objects:
        try:
            collection_names.extend(coll.name for coll in obj.users_collection)
        except Exception:
            pass
    snapshots = [_object_snapshot(obj) for obj in objects if obj is not None]
    return {{
        "id": package_id,
        "name": package_name,
        "note": package_note,
        "path": path,
        "objects": snapshots,
        "object_names": sorted(obj.name for obj in objects if obj is not None),
        "collections": sorted(set(name for name in collection_names if name)),
        "object_count": len(objects),
        "collection_count": len(set(name for name in collection_names if name)),
        "frame": int(context.scene.frame_current),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_set_package(data, package):
    packages = data.get("set_packages")
    if not isinstance(packages, list):
        packages = []
    package_id = package.get("id")
    replaced = False
    for idx, existing in enumerate(packages):
        if isinstance(existing, dict) and existing.get("id") == package_id:
            merged = dict(existing)
            merged.update(package)
            packages[idx] = merged
            replaced = True
            break
    if not replaced:
        packages.append(package)
    data["set_packages"] = packages[-500:]
    return data


def _active_set_package_key(scene):
    choice = str(getattr(scene, "gpt_director_set_package_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_set_package", "") or "").strip()


def _set_package_enum_items(self, context):
    items = [("__manual__", "手动输入/当前选中对象", "使用下方布景包ID/名称输入框")]
    data = _load_meta()
    packages = data.get("set_packages") if isinstance(data.get("set_packages"), list) else []
    seen = set(["__manual__"])
    for package in packages:
        if not isinstance(package, dict):
            continue
        package_id = str(package.get("id") or "").strip()
        if not package_id or package_id in seen:
            continue
        name = str(package.get("name") or package_id).strip()
        object_count = package.get("object_count")
        collection_count = package.get("collection_count")
        note = str(package.get("note") or "").strip()
        detail_parts = []
        if object_count not in (None, ""):
            detail_parts.append("对象 " + str(object_count))
        if collection_count not in (None, ""):
            detail_parts.append("集合 " + str(collection_count))
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "布景包"
        items.append((package_id, name, description))
        seen.add(package_id)
    return items


def _find_set_package(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_set_package_name()
    packages = data.get("set_packages") if isinstance(data.get("set_packages"), list) else []
    for package in reversed(packages):
        if not isinstance(package, dict):
            continue
        if key in (str(package.get("id") or ""), str(package.get("name") or "")):
            return dict(package)
    return {{}}


def _delete_set_package(data, package):
    if not isinstance(package, dict):
        return False
    package_id = str(package.get("id") or "").strip()
    package_name = str(package.get("name") or "").strip()
    packages = data.get("set_packages") if isinstance(data.get("set_packages"), list) else []
    kept = []
    removed = False
    for item in packages:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (package_id and str(item.get("id") or "") == package_id) or (package_name and str(item.get("name") or "") == package_name):
            removed = True
            continue
        kept.append(item)
    data["set_packages"] = kept
    path = str(package.get("path") or "").strip()
    if path and os.path.exists(path):
        try:
            if os.path.abspath(path).startswith(os.path.abspath(SET_PACKAGES_DIR)):
                os.remove(path)
        except Exception:
            pass
    return removed


def _load_set_package_into_project(context, package):
    if not isinstance(package, dict):
        return 0, 0
    path = str(package.get("path") or "").strip()
    if not path and package.get("id"):
        path = _set_package_path(package.get("id"))
    if not path or not os.path.exists(path):
        raise RuntimeError("布景包文件不存在，请重新保存布景包")
    collection_name = "Director Set Package " + _safe_id(package.get("name") or package.get("id") or "set", "set")
    imported_objects, imported_collections, _imported_actions = _append_blend_asset(path, collection_name)
    root_collection = _ensure_collection(collection_name)
    _link_collection_to_parent(root_collection, "Director Set Packages")
    for obj in imported_objects:
        _link_object_to_collection_without_moving(obj, collection_name)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in imported_objects:
            obj.select_set(True)
        if imported_objects:
            context.view_layer.objects.active = imported_objects[0]
    except Exception:
        pass
    return len(imported_objects), len(imported_collections)


def _ensure_render_settings(scene):
    try:
        if int(getattr(scene.render, "resolution_x", 0) or 0) <= 0:
            scene.render.resolution_x = 1280
        if int(getattr(scene.render, "resolution_y", 0) or 0) <= 0:
            scene.render.resolution_y = 720
    except Exception:
        pass
    try:
        if str(getattr(scene.render, "engine", "") or "") == "":
            scene.render.engine = "CYCLES"
            scene.cycles.device = "CPU"
            scene.cycles.samples = 32
    except Exception:
        try:
            if str(getattr(scene.render, "engine", "") or "") == "":
                scene.render.engine = "BLENDER_EEVEE"
        except Exception:
            pass


def _render_paths(shot_id, output_type):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = _safe_id(shot_id, "shot") + "_" + timestamp
    if output_type == "layered":
        output_dir = _ensure_dir(os.path.join(RENDERS_DIR, base + "_layers"))
        return {{
            "output_path": output_dir,
            "render_filepath": os.path.join(output_dir, _safe_id(shot_id, "shot") + "_beauty.png"),
            "preview_path": os.path.join(output_dir, _safe_id(shot_id, "shot") + "_beauty.png"),
            "transparent_path": os.path.join(output_dir, _safe_id(shot_id, "shot") + "_transparent.png"),
            "manifest_path": os.path.join(output_dir, "manifest.json"),
        }}
    if output_type == "sequence":
        output_dir = _ensure_dir(os.path.join(RENDERS_DIR, base + "_frames"))
        return {{
            "output_path": output_dir,
            "render_filepath": os.path.join(output_dir, _safe_id(shot_id, "shot") + "_"),
            "preview_path": "",
        }}
    if output_type == "video":
        return {{
            "output_path": os.path.join(RENDERS_DIR, base + ".mp4"),
            "render_filepath": os.path.join(RENDERS_DIR, base + ".mp4"),
            "preview_path": os.path.join(RENDERS_DIR, base + "_preview.png"),
        }}
    path = os.path.join(RENDERS_DIR, base + ".png")
    return {{
        "output_path": path,
        "render_filepath": path,
        "preview_path": path,
    }}


def _configure_image_output(scene, output_type, filepath):
    scene.render.filepath = filepath
    try:
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA" if output_type == "transparent" else "RGB"
        scene.render.film_transparent = output_type == "transparent"
    except Exception:
        pass


def _configure_video_output(scene, filepath):
    scene.render.filepath = filepath
    try:
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        scene.render.film_transparent = False
    except Exception:
        pass


def _first_image_in_dir(path):
    if not path or not os.path.isdir(path):
        return ""
    names = sorted(name for name in os.listdir(path) if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")))
    return os.path.join(path, names[0]) if names else ""


def _record_render(data, render_record):
    renders = data.get("renders")
    if not isinstance(renders, list):
        renders = []
    renders.append(render_record)
    data["renders"] = renders[-500:]
    return data


def _next_render_version(data, shot_id):
    shot_id = str(shot_id or "").strip()
    renders = data.get("renders") if isinstance(data.get("renders"), list) else []
    versions = []
    for item in renders:
        if not isinstance(item, dict):
            continue
        if shot_id and str(item.get("shot_id") or "") != shot_id:
            continue
        try:
            versions.append(int(item.get("render_version") or 0))
        except Exception:
            pass
    return (max(versions) if versions else 0) + 1


def _write_layered_manifest(path, record):
    if not path:
        return
    payload = record if isinstance(record, dict) else {{}}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _render_saved_shot(context, data, shot, render_mode="current", output_type=None):
    if not isinstance(shot, dict):
        return ""
    _ensure_dir(RENDERS_DIR)
    scene = context.scene
    output_type = output_type or str(shot.get("output_type") or "") or _active_render_output()
    if output_type not in RENDER_OUTPUT_LABELS:
        output_type = "still"
    shot_id = _safe_id(shot.get("id") or shot.get("name") or "shot", "shot")
    shot_name = str(shot.get("name") or shot_id)
    shot_note = str(shot.get("note") or "")
    render_version = _next_render_version(data, shot_id)
    _apply_camera_snapshot(shot.get("camera") or {{}})
    _apply_object_snapshots(shot.get("objects") or [])
    try:
        scene.frame_current = int(shot.get("frame") or scene.frame_current)
    except Exception:
        pass
    _ensure_render_settings(scene)
    paths = _render_paths(shot_id, output_type)
    output_path = paths["output_path"]
    preview_path = paths["preview_path"]
    if output_type in ("sequence", "video"):
        start = int(shot.get("frame_start") or _active_frame_range(scene)[0])
        end = int(shot.get("frame_end") or _active_frame_range(scene)[1])
        if end < start:
            end = start
        scene.frame_start = start
        scene.frame_end = end
    if output_type == "video":
        _configure_video_output(scene, paths["render_filepath"])
        bpy.ops.render.render(animation=True)
        _configure_image_output(scene, "still", preview_path)
        bpy.ops.render.render(write_still=True)
    elif output_type == "sequence":
        _configure_image_output(scene, "still", paths["render_filepath"])
        bpy.ops.render.render(animation=True)
        preview_path = _first_image_in_dir(output_path)
    elif output_type == "layered":
        _configure_image_output(scene, "still", paths["render_filepath"])
        bpy.ops.render.render(write_still=True)
        _configure_image_output(scene, "transparent", paths["transparent_path"])
        bpy.ops.render.render(write_still=True)
        preview_path = paths["preview_path"]
    else:
        _configure_image_output(scene, output_type, paths["render_filepath"])
        bpy.ops.render.render(write_still=True)
    saved = dict(shot)
    saved["camera"] = _camera_snapshot(scene.camera)
    saved["objects"] = _scene_object_snapshots(scene)
    saved["frame"] = int(scene.frame_current)
    saved["frame_start"] = int(scene.frame_start)
    saved["frame_end"] = int(scene.frame_end)
    saved["output_type"] = output_type
    saved["output_label"] = RENDER_OUTPUT_LABELS.get(output_type, output_type)
    saved["render_version"] = render_version
    saved["last_rendered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _upsert_shot(data, saved)
    _save_shot_file(saved)
    render_record = {{
        "path": preview_path or output_path,
        "output_path": output_path,
        "preview_path": preview_path,
        "output_type": output_type,
        "output_label": RENDER_OUTPUT_LABELS.get(output_type, output_type),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": render_mode,
        "shot_id": shot_id,
        "shot_name": shot_name,
        "shot_note": shot_note,
        "render_version": render_version,
        "frame_start": int(scene.frame_start),
        "frame_end": int(scene.frame_end),
        "camera": _camera_snapshot(scene.camera),
    }}
    if output_type == "layered":
        render_record["layer_paths"] = {{
            "beauty": paths.get("render_filepath", ""),
            "transparent": paths.get("transparent_path", ""),
        }}
        render_record["manifest_path"] = paths.get("manifest_path", "")
        _write_layered_manifest(paths.get("manifest_path", ""), render_record)
    _record_render(data, render_record)
    return preview_path or output_path


def _active_armature():
    obj = bpy.context.object
    if obj and obj.type == "ARMATURE":
        return obj
    if obj and obj.parent and obj.parent.type == "ARMATURE":
        return obj.parent
    for selected in bpy.context.selected_objects:
        if selected.type == "ARMATURE":
            return selected
    return None


def _action_from_armature(armature):
    if not armature or not armature.animation_data:
        return None
    return armature.animation_data.action


def _latest_action(action_name=""):
    action_name = str(action_name or "").strip()
    if action_name and bpy.data.actions.get(action_name):
        return bpy.data.actions.get(action_name)
    actions = list(bpy.data.actions)
    return actions[-1] if actions else None


def _apply_action_to_armature(target_armature, action, copy_action=True):
    if not target_armature or target_armature.type != "ARMATURE":
        return False, "请先选中要套动作的人物骨骼"
    if not action:
        return False, "没有找到可用动作"
    target_armature.animation_data_create()
    applied = action.copy() if copy_action else action
    if copy_action:
        applied.name = _safe_id(target_armature.name + "_" + action.name, "director_action")
    target_armature.animation_data.action = applied
    try:
        start, end = action.frame_range
        bpy.context.scene.frame_start = int(start)
        bpy.context.scene.frame_end = int(end)
    except Exception:
        pass
    return True, applied.name


HUMANOID_BONE_ALIASES = (
    ("hips", ("hips", "hip", "pelvis", "root", "mixamorig:hips", "骨盆")),
    ("spine", ("spine", "spine1", "spine_01", "腰", "脊柱")),
    ("chest", ("chest", "spine2", "spine_02", "upperchest", "胸")),
    ("neck", ("neck", "颈")),
    ("head", ("head", "头")),
    ("left_shoulder", ("leftshoulder", "shoulderl", "lshoulder", "clavicle_l", "leftarm_clavicle", "左肩")),
    ("right_shoulder", ("rightshoulder", "shoulderr", "rshoulder", "clavicle_r", "rightarm_clavicle", "右肩")),
    ("left_upper_arm", ("leftarm", "upperarm_l", "l_upperarm", "arm_l", "左上臂")),
    ("right_upper_arm", ("rightarm", "upperarm_r", "r_upperarm", "arm_r", "右上臂")),
    ("left_lower_arm", ("leftforearm", "lowerarm_l", "l_forearm", "forearm_l", "左前臂")),
    ("right_lower_arm", ("rightforearm", "lowerarm_r", "r_forearm", "forearm_r", "右前臂")),
    ("left_hand", ("lefthand", "hand_l", "l_hand", "左手")),
    ("right_hand", ("righthand", "hand_r", "r_hand", "右手")),
    ("left_upper_leg", ("leftupleg", "thigh_l", "upperleg_l", "leg_l", "左大腿")),
    ("right_upper_leg", ("rightupleg", "thigh_r", "upperleg_r", "leg_r", "右大腿")),
    ("left_lower_leg", ("leftleg", "calf_l", "shin_l", "lowerleg_l", "左小腿")),
    ("right_lower_leg", ("rightleg", "calf_r", "shin_r", "lowerleg_r", "右小腿")),
    ("left_foot", ("leftfoot", "foot_l", "l_foot", "左脚")),
    ("right_foot", ("rightfoot", "foot_r", "r_foot", "右脚")),
    ("left_toe", ("lefttoe", "toe_l", "ball_l", "左脚趾")),
    ("right_toe", ("righttoe", "toe_r", "ball_r", "右脚趾")),
)


def _normalize_bone_name(name):
    text = str(name or "").lower()
    text = text.replace("mixamorig:", "")
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text)


def _bone_role(name):
    normalized = _normalize_bone_name(name)
    if not normalized:
        return ""
    for role, aliases in HUMANOID_BONE_ALIASES:
        for alias in aliases:
            if _normalize_bone_name(alias) == normalized:
                return role
    for role, aliases in HUMANOID_BONE_ALIASES:
        for alias in aliases:
            alias_norm = _normalize_bone_name(alias)
            if alias_norm and (normalized.endswith(alias_norm) or alias_norm in normalized):
                return role
    return ""


def _armature_by_name(name):
    name = str(name or "").strip()
    if not name:
        return None
    obj = bpy.data.objects.get(name)
    return obj if obj and obj.type == "ARMATURE" else None


def _retarget_source_armature(scene, target_armature=None):
    source = _armature_by_name(getattr(scene, "gpt_director_retarget_source_armature", ""))
    if source:
        return source
    selected = [obj for obj in getattr(bpy.context, "selected_objects", []) if obj and obj.type == "ARMATURE"]
    for obj in selected:
        if target_armature is None or obj.name != target_armature.name:
            return obj
    return None


def _retarget_target_armature(data, scene):
    target = _armature_by_name(getattr(scene, "gpt_director_retarget_target_armature", ""))
    if target:
        return target
    _actor, active_target = _active_action_target(data)
    return active_target


def _retarget_profile_name():
    name = str(getattr(bpy.context.scene, "gpt_director_retarget_profile_name", "") or "").strip()
    return name or "动作重定向档案"


def _retarget_profile_note():
    return str(getattr(bpy.context.scene, "gpt_director_retarget_profile_note", "") or "").strip()


def _armature_height(armature):
    if not armature or armature.type != "ARMATURE":
        return 0.0
    z_values = []
    for bone in armature.data.bones:
        try:
            z_values.extend((float(bone.head_local.z), float(bone.tail_local.z)))
        except Exception:
            continue
    if not z_values:
        return 0.0
    return max(z_values) - min(z_values)


def _retarget_root_bone_name(armature, preferred=""):
    if not armature or armature.type != "ARMATURE":
        return ""
    preferred = str(preferred or "").strip()
    if preferred and armature.data.bones.get(preferred):
        return preferred
    for bone in armature.data.bones:
        if _bone_role(bone.name) == "hips":
            return bone.name
    for bone in armature.data.bones:
        if bone.parent is None:
            return bone.name
    return ""


def _retarget_automatic_scale(source_armature, target_armature):
    source_height = _armature_height(source_armature)
    target_height = _armature_height(target_armature)
    if source_height <= 0.000001 or target_height <= 0.000001:
        return 1.0
    return target_height / source_height


def _retarget_motion_scale(source_armature, target_armature, profile):
    root_motion = profile.get("root_motion") if isinstance(profile.get("root_motion"), dict) else {{}}
    try:
        manual_scale = max(0.01, float(root_motion.get("manual_scale") or 1.0))
    except Exception:
        manual_scale = 1.0
    return _retarget_automatic_scale(source_armature, target_armature) * manual_scale


def _bone_rest_local_quaternion(armature, bone_name):
    if not armature or armature.type != "ARMATURE":
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    bone = armature.data.bones.get(str(bone_name or ""))
    if not bone:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    try:
        rest_matrix = bone.matrix_local.copy()
        if bone.parent:
            rest_matrix = bone.parent.matrix_local.inverted() @ rest_matrix
        result = rest_matrix.to_quaternion()
        result.normalize()
        return result
    except Exception:
        return Quaternion((1.0, 0.0, 0.0, 0.0))


def _retarget_rest_correction(source_armature, target_armature, source_bone, target_bone):
    source_rest = _bone_rest_local_quaternion(source_armature, source_bone)
    target_rest = _bone_rest_local_quaternion(target_armature, target_bone)
    try:
        correction = target_rest.inverted() @ source_rest
        correction.normalize()
        return correction
    except Exception:
        return Quaternion((1.0, 0.0, 0.0, 0.0))


def _retarget_rest_angle_degrees(source_armature, target_armature, source_bone, target_bone):
    try:
        return round(float(_retarget_rest_correction(source_armature, target_armature, source_bone, target_bone).angle) * 57.295779513, 3)
    except Exception:
        return 0.0


def _retarget_rotation_property(data_path):
    data_path = str(data_path or "")
    for property_name in ("rotation_quaternion", "rotation_euler", "rotation_axis_angle"):
        if data_path.endswith("." + property_name):
            return property_name
    return ""


def _retarget_bake_frames(action, step):
    try:
        start, end = action.frame_range
        start = int(round(float(start)))
        end = int(round(float(end)))
    except Exception:
        start, end = 1, 1
    if end < start:
        start, end = end, start
    step = max(1, min(12, int(step or 1)))
    frames = list(range(start, end + 1, step))
    if not frames or frames[-1] != end:
        frames.append(end)
    return frames


def _retarget_source_rotation_quaternion(source_armature, source_bone, property_name, curve_map, frame):
    if property_name == "rotation_quaternion":
        values = [1.0, 0.0, 0.0, 0.0]
        for index in range(4):
            curve = curve_map.get(index)
            if curve:
                values[index] = float(curve.evaluate(frame))
        result = Quaternion(tuple(values))
    elif property_name == "rotation_axis_angle":
        values = [0.0, 0.0, 1.0, 0.0]
        for index in range(4):
            curve = curve_map.get(index)
            if curve:
                values[index] = float(curve.evaluate(frame))
        axis = Vector((values[1], values[2], values[3]))
        if axis.length <= 0.000001:
            axis = Vector((0.0, 1.0, 0.0))
        else:
            axis.normalize()
        result = Quaternion(axis, values[0])
    else:
        values = [0.0, 0.0, 0.0]
        for index in range(3):
            curve = curve_map.get(index)
            if curve:
                values[index] = float(curve.evaluate(frame))
        order = "XYZ"
        try:
            pose_bone = source_armature.pose.bones.get(source_bone)
            if pose_bone and pose_bone.rotation_mode in ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"):
                order = pose_bone.rotation_mode
        except Exception:
            pass
        result = Euler(tuple(values), order).to_quaternion()
    try:
        result.normalize()
    except Exception:
        pass
    return result


def _write_retarget_rotation_curves(target_action, source_action, source_armature, target_armature, source_bone, target_bone, property_name, curve_map, bake_step):
    correction = _retarget_rest_correction(source_armature, target_armature, source_bone, target_bone)
    inverse_correction = correction.inverted()
    frames = _retarget_bake_frames(source_action, bake_step)
    samples = []
    previous = None
    for frame in frames:
        source_rotation = _retarget_source_rotation_quaternion(source_armature, source_bone, property_name, curve_map, frame)
        target_rotation = correction @ source_rotation @ inverse_correction
        target_rotation.normalize()
        if previous is not None:
            target_rotation.make_compatible(previous)
        samples.append((frame, (target_rotation.w, target_rotation.x, target_rotation.y, target_rotation.z)))
        previous = target_rotation.copy()
    target_pose_bone = target_armature.pose.bones.get(target_bone) if target_armature.pose else None
    if target_pose_bone:
        target_pose_bone.rotation_mode = "QUATERNION"
    data_path = 'pose.bones["' + target_bone + '"].rotation_quaternion'
    written = 0
    for index in range(4):
        curve = target_action.fcurves.new(data_path=data_path, index=index, action_group=target_bone)
        for frame, values in samples:
            point = curve.keyframe_points.insert(frame, values[index], options={{"FAST"}})
            point.interpolation = "BEZIER"
        curve.update()
        written += 1
    return written


def _write_retarget_root_location_curves(target_action, source_action, source_armature, target_armature, source_root, target_root, curve_map, bake_step, root_scale):
    correction = _retarget_rest_correction(source_armature, target_armature, source_root, target_root)
    frames = _retarget_bake_frames(source_action, bake_step)
    samples = []
    for frame in frames:
        source_location = Vector((
            float(curve_map.get(0).evaluate(frame)) if curve_map.get(0) else 0.0,
            float(curve_map.get(1).evaluate(frame)) if curve_map.get(1) else 0.0,
            float(curve_map.get(2).evaluate(frame)) if curve_map.get(2) else 0.0,
        ))
        target_location = (correction @ source_location) * root_scale
        samples.append((frame, tuple(target_location)))
    data_path = 'pose.bones["' + target_root + '"].location'
    written = 0
    for index in range(3):
        curve = target_action.fcurves.new(data_path=data_path, index=index, action_group=target_root)
        for frame, values in samples:
            point = curve.keyframe_points.insert(frame, values[index], options={{"FAST"}})
            point.interpolation = "BEZIER"
        curve.update()
        written += 1
    return written


def _refresh_retarget_profile_stats(profile, source_armature=None, target_armature=None):
    profile = dict(profile or {{}})
    source_armature = source_armature or _armature_by_name(profile.get("source_armature"))
    target_armature = target_armature or _armature_by_name(profile.get("target_armature"))
    bone_map = profile.get("bone_map") if isinstance(profile.get("bone_map"), list) else []
    normalized_rows = []
    seen_sources = set()
    seen_targets = set()
    for row in bone_map:
        if not isinstance(row, dict):
            continue
        source_name = str(row.get("source") or "").strip()
        target_name = str(row.get("target") or "").strip()
        if not source_name or not target_name or source_name in seen_sources or target_name in seen_targets:
            continue
        normalized = dict(row)
        normalized["source"] = source_name
        normalized["target"] = target_name
        normalized["role"] = str(normalized.get("role") or _bone_role(source_name))
        normalized["rest_pose_angle_degrees"] = _retarget_rest_angle_degrees(
            source_armature,
            target_armature,
            source_name,
            target_name,
        )
        normalized_rows.append(normalized)
        seen_sources.add(source_name)
        seen_targets.add(target_name)
    source_names = [bone.name for bone in source_armature.data.bones] if source_armature else []
    target_names = [bone.name for bone in target_armature.data.bones] if target_armature else []
    source_root = _retarget_root_bone_name(source_armature)
    target_root = ""
    for row in normalized_rows:
        if row.get("source") == source_root or row.get("role") == "hips":
            source_root = str(row.get("source") or source_root)
            target_root = str(row.get("target") or "")
            break
    target_root = _retarget_root_bone_name(target_armature, target_root)
    root_motion = profile.get("root_motion") if isinstance(profile.get("root_motion"), dict) else {{}}
    root_motion = dict(root_motion)
    root_motion["enabled"] = bool(root_motion.get("enabled", True))
    try:
        root_motion["manual_scale"] = max(0.01, float(root_motion.get("manual_scale") or 1.0))
    except Exception:
        root_motion["manual_scale"] = 1.0
    root_motion["automatic_scale"] = _retarget_automatic_scale(source_armature, target_armature)
    root_motion["effective_scale"] = root_motion["automatic_scale"] * root_motion["manual_scale"]
    root_motion["source_bone"] = source_root
    root_motion["target_bone"] = target_root
    root_motion["source_height"] = _armature_height(source_armature)
    root_motion["target_height"] = _armature_height(target_armature)
    rest_pose = profile.get("rest_pose_alignment") if isinstance(profile.get("rest_pose_alignment"), dict) else {{}}
    rest_pose = dict(rest_pose)
    rest_pose["enabled"] = bool(rest_pose.get("enabled", True))
    try:
        rest_pose["bake_step"] = max(1, min(12, int(rest_pose.get("bake_step") or 1)))
    except Exception:
        rest_pose["bake_step"] = 1
    rest_angles = [float(row.get("rest_pose_angle_degrees") or 0.0) for row in normalized_rows]
    rest_pose["mismatch_bone_count"] = len([angle for angle in rest_angles if angle >= 5.0])
    rest_pose["max_angle_degrees"] = max(rest_angles) if rest_angles else 0.0
    profile["bone_map"] = normalized_rows
    profile["mapped_bone_count"] = len(normalized_rows)
    profile["unmapped_source_bones"] = [name for name in source_names if name not in seen_sources]
    profile["unmapped_target_bones"] = [name for name in target_names if name not in seen_targets]
    profile["unmapped_source_count"] = len(profile["unmapped_source_bones"])
    profile["unmapped_target_count"] = len(profile["unmapped_target_bones"])
    profile["root_motion"] = root_motion
    profile["rest_pose_alignment"] = rest_pose
    return profile


def _auto_bone_map(source_armature, target_armature):
    if not source_armature or not target_armature:
        return []
    target_by_normalized = {{}}
    target_by_role = {{}}
    for bone in target_armature.data.bones:
        normalized = _normalize_bone_name(bone.name)
        if normalized and normalized not in target_by_normalized:
            target_by_normalized[normalized] = bone.name
        role = _bone_role(bone.name)
        if role and role not in target_by_role:
            target_by_role[role] = bone.name
    rows = []
    used_targets = set()
    for source_bone in source_armature.data.bones:
        normalized = _normalize_bone_name(source_bone.name)
        role = _bone_role(source_bone.name)
        target_name = target_by_normalized.get(normalized, "")
        confidence = 1.0 if target_name else 0.0
        method = "同名骨骼"
        if not target_name and role:
            target_name = target_by_role.get(role, "")
            confidence = 0.72 if target_name else 0.0
            method = "人体骨骼角色"
        if target_name and target_name not in used_targets:
            rows.append({{
                "source": source_bone.name,
                "target": target_name,
                "role": role,
                "confidence": confidence,
                "method": method,
            }})
            used_targets.add(target_name)
    return rows


def _retarget_profile_from_armatures(source_armature, target_armature, profile_id, name, note):
    if not source_armature or not target_armature:
        raise RuntimeError("请指定源骨骼和目标骨骼")
    bone_map = _auto_bone_map(source_armature, target_armature)
    profile = {{
        "id": profile_id,
        "name": name,
        "note": note,
        "source_armature": source_armature.name,
        "target_armature": target_armature.name,
        "source_bone_count": len(source_armature.data.bones),
        "target_bone_count": len(target_armature.data.bones),
        "mapped_bone_count": len(bone_map),
        "bone_map": bone_map,
        "root_motion": {{
            "enabled": bool(getattr(bpy.context.scene, "gpt_director_retarget_root_motion_enabled", True)),
            "manual_scale": float(getattr(bpy.context.scene, "gpt_director_retarget_root_motion_scale", 1.0) or 1.0),
        }},
        "rest_pose_alignment": {{
            "enabled": bool(getattr(bpy.context.scene, "gpt_director_retarget_rest_pose_enabled", True)),
            "bake_step": int(getattr(bpy.context.scene, "gpt_director_retarget_bake_step", 1) or 1),
        }},
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    return _refresh_retarget_profile_stats(profile, source_armature, target_armature)


def _upsert_retarget_profile(data, profile):
    profiles = data.get("retarget_profiles")
    if not isinstance(profiles, list):
        profiles = []
    profile_id = str(profile.get("id") or "")
    replaced = False
    for idx, existing in enumerate(profiles):
        if isinstance(existing, dict) and str(existing.get("id") or "") == profile_id:
            merged = dict(existing)
            merged.update(profile)
            profiles[idx] = merged
            replaced = True
            break
    if not replaced:
        profiles.append(profile)
    data["retarget_profiles"] = profiles[-300:]
    return data


def _active_retarget_profile_key(scene):
    choice = str(getattr(scene, "gpt_director_retarget_profile_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_retarget_profile", "") or "").strip()


def _find_retarget_profile(data, key):
    key = str(key or "").strip()
    profiles = data.get("retarget_profiles") if isinstance(data.get("retarget_profiles"), list) else []
    for profile in reversed(profiles):
        if not isinstance(profile, dict):
            continue
        if key in (str(profile.get("id") or ""), str(profile.get("name") or "")):
            return dict(profile)
    return {{}}


def _delete_retarget_profile(data, profile):
    if not isinstance(profile, dict):
        return False
    profile_id = str(profile.get("id") or "").strip()
    profile_name = str(profile.get("name") or "").strip()
    profiles = data.get("retarget_profiles") if isinstance(data.get("retarget_profiles"), list) else []
    kept = []
    removed = False
    for item in profiles:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (profile_id and str(item.get("id") or "") == profile_id) or (profile_name and str(item.get("name") or "") == profile_name):
            removed = True
            continue
        kept.append(item)
    data["retarget_profiles"] = kept
    return removed


def _retarget_profile_enum_items(self, context):
    items = [("__manual__", "手动/自动映射", "使用下方源骨骼和目标骨骼自动建立映射")]
    data = _load_meta()
    profiles = data.get("retarget_profiles") if isinstance(data.get("retarget_profiles"), list) else []
    seen = set(["__manual__"])
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id") or "").strip()
        if not profile_id or profile_id in seen:
            continue
        name = str(profile.get("name") or profile_id).strip()
        detail = " → ".join(part for part in (str(profile.get("source_armature") or ""), str(profile.get("target_armature") or "")) if part)
        mapped = profile.get("mapped_bone_count")
        if mapped not in (None, ""):
            detail = (detail + "｜" if detail else "") + "映射 " + str(mapped) + " 根"
        items.append((profile_id, name, detail or "重定向档案"))
        seen.add(profile_id)
    return items


def _retarget_bone_mapping_enum_items(self, context):
    items = [("__none__", "选择骨骼映射", "选择后可读取、修改或删除这一条映射")]
    data = _load_meta()
    profile = _find_retarget_profile(data, _active_retarget_profile_key(context.scene))
    bone_map = profile.get("bone_map") if isinstance(profile.get("bone_map"), list) else []
    for index, row in enumerate(bone_map):
        if not isinstance(row, dict):
            continue
        source_name = str(row.get("source") or "").strip()
        target_name = str(row.get("target") or "").strip()
        if not source_name or not target_name:
            continue
        method = str(row.get("method") or "骨骼映射")
        confidence = row.get("confidence")
        description = method
        if confidence not in (None, ""):
            try:
                description += "｜置信度 " + str(int(float(confidence) * 100)) + "%"
            except Exception:
                pass
        items.append(("map_" + str(index), source_name + " → " + target_name, description))
    return items


def _retarget_mapping_row(profile, choice):
    choice = str(choice or "").strip()
    if not choice.startswith("map_"):
        return {{}}
    try:
        index = int(choice.split("_", 1)[1])
    except Exception:
        return {{}}
    bone_map = profile.get("bone_map") if isinstance(profile.get("bone_map"), list) else []
    if index < 0 or index >= len(bone_map) or not isinstance(bone_map[index], dict):
        return {{}}
    return dict(bone_map[index])


def _retarget_action_to_armature(source_action, source_armature, target_armature, profile):
    if not source_action:
        raise RuntimeError("没有找到源动作")
    if not source_armature or source_armature.type != "ARMATURE":
        raise RuntimeError("请指定源骨骼")
    if not target_armature or target_armature.type != "ARMATURE":
        raise RuntimeError("请指定目标骨骼")
    bone_map = profile.get("bone_map") if isinstance(profile.get("bone_map"), list) else []
    mapping = {{
        str(row.get("source") or ""): str(row.get("target") or "")
        for row in bone_map
        if isinstance(row, dict) and str(row.get("source") or "") and str(row.get("target") or "")
    }}
    if not mapping:
        raise RuntimeError("骨骼映射为空，请先建立重定向档案")
    target_bones = set(bone.name for bone in target_armature.data.bones)
    root_motion = profile.get("root_motion") if isinstance(profile.get("root_motion"), dict) else {{}}
    root_motion_enabled = bool(root_motion.get("enabled", True))
    source_root = _retarget_root_bone_name(source_armature, root_motion.get("source_bone"))
    target_root = _retarget_root_bone_name(target_armature, root_motion.get("target_bone") or mapping.get(source_root))
    root_scale = _retarget_motion_scale(source_armature, target_armature, profile)
    rest_pose = profile.get("rest_pose_alignment") if isinstance(profile.get("rest_pose_alignment"), dict) else {{}}
    rest_pose_enabled = bool(rest_pose.get("enabled", True))
    bake_step = max(1, min(12, int(rest_pose.get("bake_step") or 1)))
    target_action = bpy.data.actions.new(_safe_id(target_armature.name + "_" + source_action.name + "_retarget", "retarget_action"))
    try:
        target_action["gpt_director_root_motion_enabled"] = root_motion_enabled
        target_action["gpt_director_root_motion_scale"] = root_scale
        target_action["gpt_director_retarget_profile_id"] = str(profile.get("id") or "")
        target_action["gpt_director_rest_pose_alignment"] = rest_pose_enabled
        target_action["gpt_director_retarget_bake_step"] = bake_step
    except Exception:
        pass
    copied = 0
    skipped = 0
    rotation_groups = {{}}
    root_location_curves = {{}}
    if rest_pose_enabled:
        for fcurve in source_action.fcurves:
            data_path = str(fcurve.data_path or "")
            match = re.search(r'pose\.bones\["([^"]+)"\]', data_path)
            if not match:
                continue
            source_bone = match.group(1)
            rotation_property = _retarget_rotation_property(data_path)
            if rotation_property:
                bone_groups = rotation_groups.setdefault(source_bone, {{}})
                bone_groups.setdefault(rotation_property, {{}})[int(fcurve.array_index)] = fcurve
            elif source_bone == source_root and data_path.endswith(".location"):
                root_location_curves[int(fcurve.array_index)] = fcurve
    for fcurve in source_action.fcurves:
        data_path = str(fcurve.data_path or "")
        match = re.search(r'pose\.bones\["([^"]+)"\]', data_path)
        source_bone = ""
        target_bone = ""
        action_group = "Root Motion"
        root_location_curve = False
        if match:
            source_bone = match.group(1)
            if rest_pose_enabled and (_retarget_rotation_property(data_path) or (source_bone == source_root and data_path.endswith(".location"))):
                continue
            target_bone = mapping.get(source_bone, "")
            if not target_bone or target_bone not in target_bones:
                skipped += 1
                continue
            new_path = data_path.replace('pose.bones["' + source_bone + '"]', 'pose.bones["' + target_bone + '"]', 1)
            action_group = target_bone
            root_location_curve = source_bone == source_root and target_bone == target_root and data_path.endswith(".location")
        elif data_path in ("location", "rotation_euler", "rotation_quaternion", "scale"):
            new_path = data_path
            root_location_curve = data_path == "location"
        else:
            skipped += 1
            continue
        if root_location_curve and not root_motion_enabled:
            skipped += 1
            continue
        try:
            new_curve = target_action.fcurves.new(data_path=new_path, index=fcurve.array_index, action_group=action_group)
            for keyframe in fcurve.keyframe_points:
                value = keyframe.co.y * root_scale if root_location_curve else keyframe.co.y
                point = new_curve.keyframe_points.insert(keyframe.co.x, value, options={{"FAST"}})
                point.interpolation = keyframe.interpolation
                point.easing = keyframe.easing
            new_curve.update()
            copied += 1
        except Exception:
            skipped += 1
    if rest_pose_enabled:
        property_priority = ("rotation_quaternion", "rotation_euler", "rotation_axis_angle")
        for source_bone, property_groups in rotation_groups.items():
            target_bone = mapping.get(source_bone, "")
            if not target_bone or target_bone not in target_bones:
                skipped += sum(len(curves) for curves in property_groups.values())
                continue
            selected_property = next((name for name in property_priority if property_groups.get(name)), "")
            selected_curves = property_groups.get(selected_property) if selected_property else {{}}
            skipped += sum(len(curves) for name, curves in property_groups.items() if name != selected_property)
            try:
                copied += _write_retarget_rotation_curves(
                    target_action,
                    source_action,
                    source_armature,
                    target_armature,
                    source_bone,
                    target_bone,
                    selected_property,
                    selected_curves,
                    bake_step,
                )
            except Exception:
                skipped += len(selected_curves)
        if root_location_curves:
            if root_motion_enabled and target_root and target_root in target_bones:
                try:
                    copied += _write_retarget_root_location_curves(
                        target_action,
                        source_action,
                        source_armature,
                        target_armature,
                        source_root,
                        target_root,
                        root_location_curves,
                        bake_step,
                        root_scale,
                    )
                except Exception:
                    skipped += len(root_location_curves)
            else:
                skipped += len(root_location_curves)
    if copied <= 0:
        try:
            bpy.data.actions.remove(target_action)
        except Exception:
            pass
        raise RuntimeError("没有可重定向的骨骼动作曲线")
    target_armature.animation_data_create()
    target_armature.animation_data.action = target_action
    try:
        start, end = source_action.frame_range
        bpy.context.scene.frame_start = int(start)
        bpy.context.scene.frame_end = int(end)
    except Exception:
        pass
    return target_action, copied, skipped


def _record_retarget_application(data, profile, source_action, target_action, source_armature, target_armature, status, message, copied=0, skipped=0, action_clip=None, match_data=None):
    records = data.get("retarget_applications")
    if not isinstance(records, list):
        records = []
    record = {{
        "profile_id": str(profile.get("id") or ""),
        "profile_name": str(profile.get("name") or ""),
        "source_armature": source_armature.name if source_armature else str(profile.get("source_armature") or ""),
        "target_armature": target_armature.name if target_armature else str(profile.get("target_armature") or ""),
        "source_action": source_action.name if source_action else "",
        "target_action": target_action.name if target_action else "",
        "status": status,
        "message": message,
        "copied_fcurve_count": copied,
        "skipped_fcurve_count": skipped,
        "root_motion_enabled": bool((profile.get("root_motion") or {{}}).get("enabled", True)) if isinstance(profile.get("root_motion"), dict) else True,
        "root_motion_scale": _retarget_motion_scale(source_armature, target_armature, profile) if source_armature and target_armature else 1.0,
        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    if isinstance(action_clip, dict) and action_clip:
        record["action_clip"] = {{
            "id": str(action_clip.get("id") or ""),
            "name": str(action_clip.get("name") or ""),
            "action": str(action_clip.get("action") or ""),
            "target_armature": str(action_clip.get("target_armature") or ""),
        }}
    if isinstance(match_data, dict):
        record["action_matches"] = {{
            "matched_count": int(match_data.get("matched_count") or 0),
            "requirement_count": int(match_data.get("requirement_count") or 0),
            "unmatched_count": int(match_data.get("unmatched_count") or 0),
            "updated_at": str(match_data.get("updated_at") or ""),
        }}
    records.append(record)
    data["retarget_applications"] = records[-500:]
    return data


def _action_frame_range(action):
    if not action:
        return None, None
    try:
        start, end = action.frame_range
        return int(start), int(end)
    except Exception:
        return None, None


def _active_action_clip_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_action_clip_name", "") or "").strip()
    return name or "未命名动作片段"


def _active_action_clip_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_action_clip_note", "") or "").strip()


def _action_clip_from_action(action, target_armature, clip_id, clip_name, clip_note, actor=None, asset_record=None, library_item=None):
    if not action:
        raise RuntimeError("没有找到可保存的动作，请先导入或套用一个动作")
    frame_start, frame_end = _action_frame_range(action)
    asset_record = asset_record if isinstance(asset_record, dict) else {{}}
    library_item = library_item if isinstance(library_item, dict) else {{}}
    actor_ref = _actor_reference(actor)
    source_path = str(asset_record.get("source_path") or asset_record.get("path") or library_item.get("path") or "").strip()
    record = {{
        "id": clip_id,
        "name": clip_name,
        "note": clip_note,
        "action": action.name,
        "target_armature": target_armature.name if target_armature else str(asset_record.get("target_armature") or ""),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "frame_count": (frame_end - frame_start + 1) if frame_start is not None and frame_end is not None else None,
        "source_path": source_path,
        "path": str(asset_record.get("path") or source_path),
        "asset_id": str(asset_record.get("id") or ""),
        "asset_name": str(asset_record.get("name") or ""),
        "library_item_id": str(asset_record.get("library_item_id") or library_item.get("id") or ""),
        "library_path": str(asset_record.get("library_path") or library_item.get("library_path") or ""),
        "library_relative_path": str(asset_record.get("library_relative_path") or library_item.get("relative_path") or ""),
        "source_profile_id": str(asset_record.get("source_profile_id") or library_item.get("source_profile_id") or ""),
        "source_profile_name": str(asset_record.get("source_profile_name") or library_item.get("source_profile_name") or ""),
        "format": str(asset_record.get("format") or library_item.get("format") or ""),
        "status": str(asset_record.get("auto_apply_status") or ""),
        "message": str(asset_record.get("auto_apply_message") or ""),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    if actor_ref:
        record["actor"] = actor_ref
    return record


def _action_clip_from_asset_record(asset_record, actor=None, target_armature=None, library_item=None, note=""):
    if not isinstance(asset_record, dict) or str(asset_record.get("type") or "") != "action":
        return {{}}
    actions = asset_record.get("actions") if isinstance(asset_record.get("actions"), list) else []
    action_name = str(actions[-1] if actions else asset_record.get("action") or "").strip()
    action = _latest_action(action_name)
    if not action:
        return {{}}
    clip_base = str(asset_record.get("id") or asset_record.get("name") or action.name or "action_clip")
    clip_id = _safe_id(clip_base + "_" + action.name, "action_clip")
    clip_name = str(asset_record.get("name") or action.name or "动作片段")
    return _action_clip_from_action(action, target_armature, clip_id, clip_name, note, actor, asset_record, library_item)


def _upsert_action_clip(data, clip):
    clips = data.get("action_clips")
    if not isinstance(clips, list):
        clips = []
    clip_id = clip.get("id")
    replaced = False
    for idx, existing in enumerate(clips):
        if isinstance(existing, dict) and existing.get("id") == clip_id:
            merged = dict(existing)
            merged.update(clip)
            clips[idx] = merged
            replaced = True
            break
    if not replaced:
        clips.append(clip)
    data["action_clips"] = clips[-500:]
    return data


def _find_action_clip_by_action(data, action_name):
    action_name = str(action_name or "").strip()
    if not action_name:
        return {{}}
    clips = data.get("action_clips") if isinstance(data.get("action_clips"), list) else []
    for clip in reversed(clips):
        if isinstance(clip, dict) and str(clip.get("action") or "").strip() == action_name:
            return dict(clip)
    return {{}}


def _upsert_retarget_action_clip(data, profile, source_action, target_action, target_armature, actor=None, copied=0, skipped=0):
    source_clip = _find_action_clip_by_action(data, source_action.name if source_action else "")
    base_name = str(source_clip.get("name") or (source_action.name if source_action else "") or target_action.name or "重定向动作").strip()
    clip_name = base_name if "重定向" in base_name else base_name + "（重定向）"
    profile_name = str(profile.get("name") or profile.get("id") or "重定向档案")
    note_parts = [
        str(source_clip.get("note") or "").strip(),
        "已通过“" + profile_name + "”适配目标骨骼 " + (target_armature.name if target_armature else ""),
    ]
    clip_note = "；".join(part for part in note_parts if part)
    clip_id = _safe_id(
        "retarget_"
        + str(profile.get("id") or profile_name)
        + "_"
        + (source_action.name if source_action else target_action.name)
        + "_"
        + (target_armature.name if target_armature else ""),
        "retarget_action_clip",
    )
    clip = _action_clip_from_action(
        target_action,
        target_armature,
        clip_id,
        clip_name,
        clip_note,
        actor,
    )
    inherited_fields = (
        "tags",
        "usage_note",
        "source_path",
        "path",
        "asset_id",
        "asset_name",
        "library_item_id",
        "library_path",
        "library_relative_path",
        "source_profile_id",
        "source_profile_name",
        "format",
        "favorite",
        "usage_count",
    )
    for field in inherited_fields:
        if field in source_clip and source_clip.get(field) not in (None, "", []):
            clip[field] = source_clip.get(field)
    rest_pose = profile.get("rest_pose_alignment") if isinstance(profile.get("rest_pose_alignment"), dict) else {{}}
    root_motion = profile.get("root_motion") if isinstance(profile.get("root_motion"), dict) else {{}}
    clip["generated_by"] = "retarget"
    clip["retarget_profile_id"] = str(profile.get("id") or "")
    clip["retarget_profile_name"] = profile_name
    clip["retarget_source_action"] = source_action.name if source_action else ""
    clip["retarget_source_clip_name"] = base_name
    clip["source_action_clip_id"] = str(source_clip.get("id") or "")
    clip["retarget_quality"] = {{
        "copied_fcurve_count": int(copied or 0),
        "skipped_fcurve_count": int(skipped or 0),
        "mapped_bone_count": int(profile.get("mapped_bone_count") or 0),
        "unmapped_source_count": int(profile.get("unmapped_source_count") or 0),
        "unmapped_target_count": int(profile.get("unmapped_target_count") or 0),
        "rest_pose_enabled": bool(rest_pose.get("enabled", True)),
        "rest_pose_mismatch_bone_count": int(rest_pose.get("mismatch_bone_count") or 0),
        "rest_pose_max_angle_degrees": float(rest_pose.get("max_angle_degrees") or 0.0),
        "bake_step": int(rest_pose.get("bake_step") or 1),
        "root_motion_enabled": bool(root_motion.get("enabled", True)),
        "root_motion_scale": float(root_motion.get("effective_scale") or 1.0),
    }}
    clip["status"] = "ready"
    clip["message"] = "已完成骨骼重定向，可用于分镜动作匹配"
    _upsert_action_clip(data, clip)
    return clip


def _upsert_action_clip_from_asset_record(data, asset_record, actor=None, target_armature=None, library_item=None, note=""):
    clip = _action_clip_from_asset_record(asset_record, actor, target_armature, library_item, note)
    if clip:
        _upsert_action_clip(data, clip)
    return clip


def _active_action_clip_key(scene):
    choice = str(getattr(scene, "gpt_director_action_clip_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_action_clip", "") or "").strip()


def _action_clip_enum_items(self, context):
    items = [("__manual__", "手动输入/当前动作", "使用下方动作片段ID/名称输入框")]
    data = _load_meta()
    clips = data.get("action_clips") if isinstance(data.get("action_clips"), list) else []
    seen = set(["__manual__"])
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        clip_id = str(clip.get("id") or "").strip()
        if not clip_id or clip_id in seen:
            continue
        name = str(clip.get("name") or clip.get("action") or clip_id).strip()
        actor_label = ""
        actor_ref = clip.get("actor") if isinstance(clip.get("actor"), dict) else {{}}
        if actor_ref:
            actor_label = str(actor_ref.get("name") or actor_ref.get("id") or "").strip()
        frame_start = clip.get("frame_start")
        frame_end = clip.get("frame_end")
        source = str(clip.get("source_profile_name") or "").strip()
        detail_parts = []
        if actor_label:
            detail_parts.append("演员 " + actor_label)
        if frame_start is not None and frame_end is not None:
            detail_parts.append("帧 " + str(frame_start) + "-" + str(frame_end))
        if source:
            detail_parts.append(source)
        items.append((clip_id, name, "｜".join(detail_parts) if detail_parts else "动作片段"))
        seen.add(clip_id)
    return items


def _find_action_clip(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_action_clip_name()
    clips = data.get("action_clips") if isinstance(data.get("action_clips"), list) else []
    for clip in reversed(clips):
        if not isinstance(clip, dict):
            continue
        if key in (str(clip.get("id") or ""), str(clip.get("name") or ""), str(clip.get("action") or "")):
            return dict(clip)
    return {{}}


def _delete_action_clip(data, clip):
    if not isinstance(clip, dict):
        return False
    clip_id = str(clip.get("id") or "").strip()
    clip_name = str(clip.get("name") or "").strip()
    clips = data.get("action_clips") if isinstance(data.get("action_clips"), list) else []
    kept = []
    removed = False
    for item in clips:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (clip_id and str(item.get("id") or "") == clip_id) or (clip_name and str(item.get("name") or "") == clip_name):
            removed = True
            continue
        kept.append(item)
    data["action_clips"] = kept
    return removed


def _actor_from_clip(data, clip):
    actor_ref = clip.get("actor") if isinstance(clip.get("actor"), dict) else {{}}
    actor_key = str(actor_ref.get("id") or actor_ref.get("name") or "").strip()
    if actor_key:
        actor = _find_actor(data, actor_key)
        if actor:
            return actor
    return _active_actor(data)


def _apply_action_clip(context, data, clip):
    if not isinstance(clip, dict):
        raise RuntimeError("动作片段无效")
    actor = _actor_from_clip(data, clip)
    target_armature = _armature_from_actor(actor) if actor else None
    stored_target = str(clip.get("target_armature") or "").strip()
    if target_armature is None and stored_target:
        obj = bpy.data.objects.get(stored_target)
        if obj and obj.type == "ARMATURE":
            target_armature = obj
    if target_armature is None:
        _actor, target_armature = _active_action_target(data)
        if actor is None:
            actor = _actor
    action_name = str(clip.get("action") or "").strip()
    action = _latest_action(action_name)
    if action is None:
        source_path = str(clip.get("path") or clip.get("source_path") or "").strip()
        if source_path and os.path.exists(source_path):
            imported = _import_director_asset(source_path, "action", str(clip.get("name") or os.path.basename(source_path)), target_armature)
            _append_asset_record(data, imported)
            _upsert_action_clip_from_asset_record(data, imported, actor, target_armature, {{}}, str(clip.get("note") or ""))
            actions = imported.get("actions") if isinstance(imported.get("actions"), list) else []
            action = _latest_action(actions[-1] if actions else "")
    ok, message = _apply_action_to_armature(target_armature, action)
    _record_action_application(
        data,
        target_armature.name if target_armature else "",
        action.name if action else action_name,
        "applied" if ok else "failed",
        message,
        actor,
        clip,
    )
    if not ok:
        raise RuntimeError(message)
    return target_armature, action, message


def _record_action_application(data, target_name, action_name, status, message="", actor=None, clip=None):
    records = data.get("action_applications")
    if not isinstance(records, list):
        records = []
    record = {{
        "target": target_name,
        "action": action_name,
        "status": status,
        "message": message,
        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    actor_ref = _actor_reference(actor)
    if actor_ref:
        record["actor"] = actor_ref
    if isinstance(clip, dict) and (clip.get("id") or clip.get("name")):
        record["action_clip"] = {{
            "id": str(clip.get("id") or ""),
            "name": str(clip.get("name") or ""),
            "source_profile_name": str(clip.get("source_profile_name") or ""),
        }}
        if isinstance(clip.get("shot_action_match"), dict):
            record["shot_action_match"] = clip.get("shot_action_match")
    records.append(record)
    data["action_applications"] = records[-500:]
    return data


def _active_pose_template_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_pose_template_name", "") or "").strip()
    return name or "未命名姿势模板"


def _active_pose_template_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_pose_template_note", "") or "").strip()


def _bone_pose_snapshot(pose_bone):
    data = {{
        "name": pose_bone.name,
        "location": [round(v, 5) for v in pose_bone.location],
        "rotation_mode": str(pose_bone.rotation_mode or "XYZ"),
        "scale": [round(v, 5) for v in pose_bone.scale],
    }}
    if pose_bone.rotation_mode == "QUATERNION":
        data["rotation_quaternion"] = [round(v, 5) for v in pose_bone.rotation_quaternion]
    elif pose_bone.rotation_mode == "AXIS_ANGLE":
        data["rotation_axis_angle"] = [round(v, 5) for v in pose_bone.rotation_axis_angle]
    else:
        data["rotation_euler"] = [round(v, 5) for v in pose_bone.rotation_euler]
    return data


def _pose_template_from_armature(armature, template_id, template_name, template_note):
    if not armature or armature.type != "ARMATURE":
        raise RuntimeError("请先选中要保存姿势的人物骨骼")
    bones = [_bone_pose_snapshot(pose_bone) for pose_bone in armature.pose.bones]
    if not bones:
        raise RuntimeError("当前骨骼没有可保存的姿势骨骼")
    action = _action_from_armature(armature)
    return {{
        "id": template_id,
        "name": template_name,
        "note": template_note,
        "armature": armature.name,
        "action": action.name if action else "",
        "bones": bones,
        "bone_count": len(bones),
        "frame": int(bpy.context.scene.frame_current),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_pose_template(data, template):
    templates = data.get("pose_templates")
    if not isinstance(templates, list):
        templates = []
    template_id = template.get("id")
    replaced = False
    for idx, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("id") == template_id:
            merged = dict(existing)
            merged.update(template)
            templates[idx] = merged
            replaced = True
            break
    if not replaced:
        templates.append(template)
    data["pose_templates"] = templates[-500:]
    return data


def _active_pose_template_key(scene):
    choice = str(getattr(scene, "gpt_director_pose_template_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_pose_template", "") or "").strip()


def _pose_template_enum_items(self, context):
    items = [("__manual__", "手动输入/当前骨骼", "使用下方姿势模板ID/名称输入框")]
    data = _load_meta()
    templates = data.get("pose_templates") if isinstance(data.get("pose_templates"), list) else []
    seen = set(["__manual__"])
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        name = str(template.get("name") or template_id).strip()
        armature = str(template.get("armature") or "").strip()
        bone_count = template.get("bone_count")
        note = str(template.get("note") or "").strip()
        detail_parts = []
        if armature:
            detail_parts.append(armature)
        if bone_count not in (None, ""):
            detail_parts.append("骨骼 " + str(bone_count))
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "姿势模板"
        items.append((template_id, name, description))
        seen.add(template_id)
    return items


def _find_pose_template(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_pose_template_name()
    templates = data.get("pose_templates") if isinstance(data.get("pose_templates"), list) else []
    for template in reversed(templates):
        if not isinstance(template, dict):
            continue
        if key in (str(template.get("id") or ""), str(template.get("name") or "")):
            return dict(template)
    return {{}}


def _delete_pose_template(data, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    templates = data.get("pose_templates") if isinstance(data.get("pose_templates"), list) else []
    kept = []
    removed = False
    for item in templates:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (template_id and str(item.get("id") or "") == template_id) or (template_name and str(item.get("name") or "") == template_name):
            removed = True
            continue
        kept.append(item)
    data["pose_templates"] = kept
    return removed


def _apply_pose_template(context, template):
    if not isinstance(template, dict):
        raise RuntimeError("姿势模板无效")
    target = _active_armature()
    stored_armature = str(template.get("armature") or "").strip()
    if target is None and stored_armature:
        target = bpy.data.objects.get(stored_armature)
    if not target or target.type != "ARMATURE":
        raise RuntimeError("请先选中要套用姿势的人物骨骼")
    bones = template.get("bones") if isinstance(template.get("bones"), list) else []
    applied = 0
    for item in bones:
        if not isinstance(item, dict):
            continue
        bone_name = str(item.get("name") or "").strip()
        pose_bone = target.pose.bones.get(bone_name) if bone_name else None
        if not pose_bone:
            continue
        location = item.get("location")
        rotation_mode = str(item.get("rotation_mode") or pose_bone.rotation_mode or "XYZ")
        rotation_quaternion = item.get("rotation_quaternion")
        rotation_axis_angle = item.get("rotation_axis_angle")
        rotation_euler = item.get("rotation_euler")
        scale = item.get("scale")
        if isinstance(location, list) and len(location) >= 3:
            pose_bone.location = (float(location[0]), float(location[1]), float(location[2]))
        try:
            pose_bone.rotation_mode = rotation_mode
        except Exception:
            pass
        if rotation_mode == "QUATERNION" and isinstance(rotation_quaternion, list) and len(rotation_quaternion) >= 4:
            pose_bone.rotation_quaternion = (
                float(rotation_quaternion[0]),
                float(rotation_quaternion[1]),
                float(rotation_quaternion[2]),
                float(rotation_quaternion[3]),
            )
        elif rotation_mode == "AXIS_ANGLE" and isinstance(rotation_axis_angle, list) and len(rotation_axis_angle) >= 4:
            pose_bone.rotation_axis_angle = (
                float(rotation_axis_angle[0]),
                float(rotation_axis_angle[1]),
                float(rotation_axis_angle[2]),
                float(rotation_axis_angle[3]),
            )
        elif isinstance(rotation_euler, list) and len(rotation_euler) >= 3:
            pose_bone.rotation_euler = (
                float(rotation_euler[0]),
                float(rotation_euler[1]),
                float(rotation_euler[2]),
            )
        if isinstance(scale, list) and len(scale) >= 3:
            pose_bone.scale = (float(scale[0]), float(scale[1]), float(scale[2]))
        applied += 1
    try:
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(True)
        context.view_layer.objects.active = target
    except Exception:
        pass
    try:
        context.scene.frame_current = int(template.get("frame") or context.scene.frame_current)
    except Exception:
        pass
    return target, applied


def _active_animation_template_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_animation_template_name", "") or "").strip()
    return name or "未命名动画片段"


def _active_animation_template_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_animation_template_note", "") or "").strip()


def _selected_animation_objects(context):
    objects = [obj for obj in context.selected_objects if obj is not None]
    if not objects and context.scene.camera:
        objects = [context.scene.camera]
    return objects


def _snapshot_fcurves(owner, frame_start, frame_end):
    if owner is None or not getattr(owner, "animation_data", None) or not owner.animation_data.action:
        return []
    fcurves = []
    for fcurve in owner.animation_data.action.fcurves:
        points = []
        for key in fcurve.keyframe_points:
            frame = float(key.co.x)
            if frame < frame_start or frame > frame_end:
                continue
            points.append({{
                "frame": round(frame, 4),
                "value": round(float(key.co.y), 6),
                "interpolation": str(getattr(key, "interpolation", "") or "BEZIER"),
            }})
        if points:
            fcurves.append({{
                "data_path": str(fcurve.data_path or ""),
                "array_index": int(fcurve.array_index),
                "keyframes": points,
            }})
    return fcurves


def _animation_template_from_selected_objects(context, template_id, template_name, template_note):
    frame_start, frame_end = _active_frame_range(context.scene)
    objects = _selected_animation_objects(context)
    if not objects:
        raise RuntimeError("请先选中要保存动画片段的对象")
    template_objects = []
    keyframe_count = 0
    for obj in objects:
        object_fcurves = _snapshot_fcurves(obj, frame_start, frame_end)
        data_fcurves = _snapshot_fcurves(getattr(obj, "data", None), frame_start, frame_end)
        if not object_fcurves and not data_fcurves:
            continue
        object_keyframes = sum(len(item.get("keyframes") or []) for item in object_fcurves if isinstance(item, dict))
        data_keyframes = sum(len(item.get("keyframes") or []) for item in data_fcurves if isinstance(item, dict))
        keyframe_count += object_keyframes + data_keyframes
        template_objects.append({{
            "name": obj.name,
            "type": obj.type,
            "object_fcurves": object_fcurves,
            "data_fcurves": data_fcurves,
        }})
    if not template_objects:
        raise RuntimeError("当前选中对象在帧段内没有可保存的关键帧")
    return {{
        "id": template_id,
        "name": template_name,
        "note": template_note,
        "objects": template_objects,
        "object_count": len(template_objects),
        "keyframe_count": keyframe_count,
        "frame_start": int(frame_start),
        "frame_end": int(frame_end),
        "frame": int(context.scene.frame_current),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_animation_template(data, template):
    templates = data.get("animation_templates")
    if not isinstance(templates, list):
        templates = []
    template_id = template.get("id")
    replaced = False
    for idx, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("id") == template_id:
            merged = dict(existing)
            merged.update(template)
            templates[idx] = merged
            replaced = True
            break
    if not replaced:
        templates.append(template)
    data["animation_templates"] = templates[-500:]
    return data


def _active_animation_template_key(scene):
    choice = str(getattr(scene, "gpt_director_animation_template_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_animation_template", "") or "").strip()


def _animation_template_enum_items(self, context):
    items = [("__manual__", "手动输入/当前动画片段", "使用下方动画片段ID/名称输入框")]
    data = _load_meta()
    templates = data.get("animation_templates") if isinstance(data.get("animation_templates"), list) else []
    seen = set(["__manual__"])
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        name = str(template.get("name") or template_id).strip()
        object_count = template.get("object_count")
        keyframe_count = template.get("keyframe_count")
        frame_start = template.get("frame_start")
        frame_end = template.get("frame_end")
        note = str(template.get("note") or "").strip()
        detail_parts = []
        if object_count not in (None, ""):
            detail_parts.append("对象 " + str(object_count))
        if keyframe_count not in (None, ""):
            detail_parts.append("关键帧 " + str(keyframe_count))
        if frame_start is not None and frame_end is not None:
            detail_parts.append("帧：" + str(frame_start) + "-" + str(frame_end))
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "动画片段"
        items.append((template_id, name, description))
        seen.add(template_id)
    return items


def _find_animation_template(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_animation_template_name()
    templates = data.get("animation_templates") if isinstance(data.get("animation_templates"), list) else []
    for template in reversed(templates):
        if not isinstance(template, dict):
            continue
        if key in (str(template.get("id") or ""), str(template.get("name") or "")):
            return dict(template)
    return {{}}


def _delete_animation_template(data, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    templates = data.get("animation_templates") if isinstance(data.get("animation_templates"), list) else []
    kept = []
    removed = False
    for item in templates:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (template_id and str(item.get("id") or "") == template_id) or (template_name and str(item.get("name") or "") == template_name):
            removed = True
            continue
        kept.append(item)
    data["animation_templates"] = kept
    return removed


def _ensure_action(owner, name):
    if owner is None:
        return None
    owner.animation_data_create()
    if owner.animation_data.action is None:
        owner.animation_data.action = bpy.data.actions.new(_safe_id(name, "director_animation"))
    return owner.animation_data.action


def _apply_fcurve_points(owner, fcurves, action_name):
    if owner is None or not isinstance(fcurves, list):
        return 0
    action = _ensure_action(owner, action_name)
    if action is None:
        return 0
    inserted = 0
    for item in fcurves:
        if not isinstance(item, dict):
            continue
        data_path = str(item.get("data_path") or "").strip()
        if not data_path:
            continue
        try:
            array_index = int(item.get("array_index") or 0)
        except Exception:
            array_index = 0
        fcurve = action.fcurves.find(data_path, index=array_index)
        if fcurve is None:
            try:
                fcurve = action.fcurves.new(data_path=data_path, index=array_index)
            except Exception:
                continue
        for key in item.get("keyframes") or []:
            if not isinstance(key, dict):
                continue
            try:
                point = fcurve.keyframe_points.insert(float(key.get("frame")), float(key.get("value")), options={{"FAST"}})
                point.interpolation = str(key.get("interpolation") or "BEZIER")
                inserted += 1
            except Exception:
                pass
        try:
            fcurve.update()
        except Exception:
            pass
    return inserted


def _apply_animation_template(context, template):
    if not isinstance(template, dict):
        raise RuntimeError("动画片段无效")
    template_objects = template.get("objects") if isinstance(template.get("objects"), list) else []
    if not template_objects:
        raise RuntimeError("动画片段里没有可加载的对象关键帧")
    applied_objects = 0
    inserted_keyframes = 0
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    for item in template_objects:
        if not isinstance(item, dict):
            continue
        obj_name = str(item.get("name") or "").strip()
        obj = bpy.data.objects.get(obj_name) if obj_name else None
        if obj is None:
            continue
        inserted = _apply_fcurve_points(obj, item.get("object_fcurves") or [], obj.name + "_animation")
        inserted += _apply_fcurve_points(getattr(obj, "data", None), item.get("data_fcurves") or [], obj.name + "_data_animation")
        if inserted:
            inserted_keyframes += inserted
            applied_objects += 1
            try:
                obj.select_set(True)
                context.view_layer.objects.active = obj
            except Exception:
                pass
    if applied_objects <= 0:
        raise RuntimeError("没有找到可匹配的对象，动画片段未加载")
    try:
        context.scene.gpt_director_frame_start = int(template.get("frame_start") or context.scene.gpt_director_frame_start)
        context.scene.gpt_director_frame_end = int(template.get("frame_end") or context.scene.gpt_director_frame_end)
        context.scene.frame_start = int(context.scene.gpt_director_frame_start)
        context.scene.frame_end = int(context.scene.gpt_director_frame_end)
        context.scene.frame_current = int(template.get("frame") or context.scene.frame_current)
    except Exception:
        pass
    return applied_objects, inserted_keyframes


def _active_material_template_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_material_template_name", "") or "").strip()
    return name or "未命名材质模板"


def _active_material_template_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_material_template_note", "") or "").strip()


def _material_color(value, length=4):
    try:
        values = list(value)
    except Exception:
        values = []
    if len(values) < length:
        values = values + [1.0] * (length - len(values))
    return [round(float(v), 6) for v in values[:length]]


def _principled_snapshot(material):
    if material is None or not getattr(material, "use_nodes", False):
        return {{}}
    node_tree = getattr(material, "node_tree", None)
    nodes = getattr(node_tree, "nodes", []) if node_tree else []
    principled = None
    for node in nodes:
        if getattr(node, "type", "") == "BSDF_PRINCIPLED":
            principled = node
            break
    if principled is None:
        return {{}}
    values = {{}}
    for socket_name in ("Base Color", "Metallic", "Roughness", "Specular", "Alpha", "Emission", "Emission Strength"):
        socket = principled.inputs.get(socket_name) if hasattr(principled.inputs, "get") else None
        if socket is None or not hasattr(socket, "default_value"):
            continue
        default_value = socket.default_value
        try:
            if hasattr(default_value, "__len__") and not isinstance(default_value, (str, bytes)):
                values[socket_name] = _material_color(default_value, len(default_value))
            else:
                values[socket_name] = round(float(default_value), 6)
        except Exception:
            pass
    return values


def _material_snapshot(material, slot_index=0):
    if material is None:
        return {{}}
    snapshot = {{
        "name": material.name,
        "slot_index": int(slot_index),
        "diffuse_color": _material_color(getattr(material, "diffuse_color", (1, 1, 1, 1)), 4),
        "use_nodes": bool(getattr(material, "use_nodes", False)),
    }}
    for attr in ("blend_method", "shadow_method", "use_screen_refraction", "show_transparent_back", "alpha_threshold"):
        try:
            value = getattr(material, attr)
        except Exception:
            continue
        if isinstance(value, bool):
            snapshot[attr] = bool(value)
        elif value is not None:
            snapshot[attr] = value
    principled = _principled_snapshot(material)
    if principled:
        snapshot["principled"] = principled
    return snapshot


def _selected_material_objects(context):
    selected = [obj for obj in (context.selected_objects or []) if obj and obj.type != "CAMERA" and getattr(obj, "data", None) is not None and hasattr(obj.data, "materials")]
    if not selected and context.object and context.object.type != "CAMERA" and getattr(context.object, "data", None) is not None and hasattr(context.object.data, "materials"):
        selected = [context.object]
    return selected


def _material_template_from_selected_objects(context, template_id, template_name, template_note):
    objects = _selected_material_objects(context)
    if not objects:
        raise RuntimeError("请先选中要保存材质的角色或道具")
    template_objects = []
    total_materials = 0
    first_materials = []
    for obj in objects:
        materials = []
        for index, material in enumerate(list(obj.data.materials)):
            if material is None:
                continue
            snapshot = _material_snapshot(material, index)
            if snapshot:
                materials.append(snapshot)
        if not materials:
            continue
        if not first_materials:
            first_materials = [dict(item) for item in materials]
        total_materials += len(materials)
        template_objects.append({{
            "name": obj.name,
            "type": obj.type,
            "materials": materials,
            "material_count": len(materials),
        }})
    if not template_objects:
        raise RuntimeError("当前选中对象没有可保存的材质")
    return {{
        "id": template_id,
        "name": template_name,
        "note": template_note,
        "objects": template_objects,
        "materials": first_materials,
        "object_count": len(template_objects),
        "material_count": total_materials,
        "frame": int(context.scene.frame_current),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_material_template(data, template):
    templates = data.get("material_templates")
    if not isinstance(templates, list):
        templates = []
    template_id = template.get("id")
    replaced = False
    for idx, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("id") == template_id:
            merged = dict(existing)
            merged.update(template)
            templates[idx] = merged
            replaced = True
            break
    if not replaced:
        templates.append(template)
    data["material_templates"] = templates[-500:]
    return data


def _active_material_template_key(scene):
    choice = str(getattr(scene, "gpt_director_material_template_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_material_template", "") or "").strip()


def _material_template_enum_items(self, context):
    items = [("__manual__", "手动输入/当前材质", "使用下方材质模板ID/名称输入框")]
    data = _load_meta()
    templates = data.get("material_templates") if isinstance(data.get("material_templates"), list) else []
    seen = set(["__manual__"])
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        name = str(template.get("name") or template_id).strip()
        object_count = template.get("object_count")
        material_count = template.get("material_count")
        note = str(template.get("note") or "").strip()
        detail_parts = []
        if object_count not in (None, ""):
            detail_parts.append("对象 " + str(object_count))
        if material_count not in (None, ""):
            detail_parts.append("材质 " + str(material_count))
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "材质模板"
        items.append((template_id, name, description))
        seen.add(template_id)
    return items


def _find_material_template(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_material_template_name()
    templates = data.get("material_templates") if isinstance(data.get("material_templates"), list) else []
    for template in reversed(templates):
        if not isinstance(template, dict):
            continue
        if key in (str(template.get("id") or ""), str(template.get("name") or "")):
            return dict(template)
    return {{}}


def _delete_material_template(data, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    templates = data.get("material_templates") if isinstance(data.get("material_templates"), list) else []
    kept = []
    removed = False
    for item in templates:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (template_id and str(item.get("id") or "") == template_id) or (template_name and str(item.get("name") or "") == template_name):
            removed = True
            continue
        kept.append(item)
    data["material_templates"] = kept
    return removed


def _ensure_material_from_snapshot(item):
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "Director Material").strip()
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    diffuse_color = item.get("diffuse_color")
    if isinstance(diffuse_color, list) and len(diffuse_color) >= 3:
        try:
            material.diffuse_color = (
                float(diffuse_color[0]),
                float(diffuse_color[1]),
                float(diffuse_color[2]),
                float(diffuse_color[3]) if len(diffuse_color) > 3 else 1.0,
            )
        except Exception:
            pass
    for attr in ("blend_method", "shadow_method", "use_screen_refraction", "show_transparent_back", "alpha_threshold"):
        if attr not in item:
            continue
        try:
            setattr(material, attr, item.get(attr))
        except Exception:
            pass
    material.use_nodes = bool(item.get("use_nodes"))
    principled_values = item.get("principled") if isinstance(item.get("principled"), dict) else {{}}
    if material.use_nodes and principled_values:
        node_tree = getattr(material, "node_tree", None)
        nodes = getattr(node_tree, "nodes", []) if node_tree else []
        principled = None
        for node in nodes:
            if getattr(node, "type", "") == "BSDF_PRINCIPLED":
                principled = node
                break
        if principled is not None:
            for socket_name, value in principled_values.items():
                socket = principled.inputs.get(socket_name) if hasattr(principled.inputs, "get") else None
                if socket is None or not hasattr(socket, "default_value"):
                    continue
                try:
                    if isinstance(value, list):
                        socket.default_value = tuple(float(v) for v in value)
                    else:
                        socket.default_value = float(value)
                except Exception:
                    pass
    return material


def _apply_materials_to_object(obj, material_items):
    if obj is None or getattr(obj, "data", None) is None or not hasattr(obj.data, "materials"):
        return 0
    if not isinstance(material_items, list) or not material_items:
        return 0
    try:
        obj.data.materials.clear()
    except Exception:
        pass
    applied = 0
    for item in material_items:
        material = _ensure_material_from_snapshot(item)
        if material is None:
            continue
        try:
            obj.data.materials.append(material)
            applied += 1
        except Exception:
            pass
    return applied


def _apply_material_template(context, template):
    if not isinstance(template, dict):
        raise RuntimeError("材质模板无效")
    selected = _selected_material_objects(context)
    applied_objects = 0
    applied_materials = 0
    if selected:
        materials = template.get("materials") if isinstance(template.get("materials"), list) else []
        if not materials:
            objects = template.get("objects") if isinstance(template.get("objects"), list) else []
            if objects and isinstance(objects[0], dict):
                materials = objects[0].get("materials") if isinstance(objects[0].get("materials"), list) else []
        if not materials:
            raise RuntimeError("材质模板里没有可套用的材质")
        for obj in selected:
            count = _apply_materials_to_object(obj, materials)
            if count:
                applied_objects += 1
                applied_materials += count
        return applied_objects, applied_materials
    template_objects = template.get("objects") if isinstance(template.get("objects"), list) else []
    for item in template_objects:
        if not isinstance(item, dict):
            continue
        obj_name = str(item.get("name") or "").strip()
        obj = bpy.data.objects.get(obj_name) if obj_name else None
        materials = item.get("materials") if isinstance(item.get("materials"), list) else []
        count = _apply_materials_to_object(obj, materials)
        if count:
            applied_objects += 1
            applied_materials += count
    if applied_objects <= 0:
        raise RuntimeError("没有找到可套用材质的对象，请先选中目标对象")
    return applied_objects, applied_materials


def _texture_group_prefix(path):
    stem = os.path.splitext(os.path.basename(str(path or "").lower()))[0]
    normalized = stem.replace("-", "_").replace(" ", "_").replace(".", "_")
    role_tokens = (
        "basecolor",
        "base_color",
        "albedo",
        "diffuse",
        "colour",
        "color",
        "normalgl",
        "normaldx",
        "normal",
        "roughness",
        "rough",
        "metallic",
        "metalness",
        "opacity",
        "alpha",
        "height",
        "displacement",
        "ambientocclusion",
        "ambient_occlusion",
    )
    prefix = normalized
    for token in role_tokens:
        index = normalized.find(token)
        if index > 0:
            prefix = normalized[:index]
            break
    return prefix.strip("_-. ") or normalized


def _texture_set_from_path(path):
    selected = os.path.abspath(str(path or ""))
    if not selected or not os.path.isfile(selected) or not _is_texture_asset_path(selected):
        return []
    if _asset_kind_from_path(selected) == "hdri":
        return [{{
            "path": selected,
            "source_path": selected,
            "role": "environment",
            "file_name": os.path.basename(selected),
            "format": os.path.splitext(selected)[1].lstrip(".").lower(),
        }}]
    base_dir = os.path.dirname(selected)
    group_prefix = _texture_group_prefix(selected)
    candidates = [selected]
    try:
        for name in os.listdir(base_dir):
            candidate = os.path.abspath(os.path.join(base_dir, name))
            if candidate == selected or not os.path.isfile(candidate) or not _is_texture_asset_path(candidate):
                continue
            if _asset_kind_from_path(candidate) == "hdri":
                continue
            if _texture_group_prefix(candidate) == group_prefix:
                candidates.append(candidate)
    except Exception:
        pass
    seen = set()
    textures = []
    for candidate in sorted(candidates):
        if candidate in seen:
            continue
        seen.add(candidate)
        textures.append({{
            "path": candidate,
            "source_path": candidate,
            "role": _texture_role_from_path(candidate),
            "file_name": os.path.basename(candidate),
            "format": os.path.splitext(candidate)[1].lstrip(".").lower(),
        }})
    return textures[:12]


def _copy_texture_set_into_project(textures, asset_kind="material"):
    copied = []
    for texture in textures if isinstance(textures, list) else []:
        if not isinstance(texture, dict):
            continue
        source = str(texture.get("path") or texture.get("source_path") or "").strip()
        if not source or not os.path.exists(source):
            continue
        target = _copy_asset_into_project(source, asset_kind)
        item = dict(texture)
        item["source_path"] = source
        item["path"] = target
        item["file_name"] = os.path.basename(target)
        item["format"] = os.path.splitext(target)[1].lstrip(".").lower()
        copied.append(item)
    return copied


def _principled_node(material):
    if material is None:
        return None
    material.use_nodes = True
    node_tree = getattr(material, "node_tree", None)
    nodes = getattr(node_tree, "nodes", None) if node_tree else None
    if nodes is None:
        return None
    for node in nodes:
        if getattr(node, "type", "") == "BSDF_PRINCIPLED":
            return node
    try:
        return nodes.new("ShaderNodeBsdfPrincipled")
    except Exception:
        return None


def _unique_material_name(base_name):
    base_name = str(base_name or "Director Texture Material").strip() or "Director Texture Material"
    if bpy.data.materials.get(base_name) is None:
        return base_name
    index = 1
    while True:
        candidate = base_name + "." + str(index).zfill(3)
        if bpy.data.materials.get(candidate) is None:
            return candidate
        index += 1


def _set_image_non_color(image):
    try:
        image.colorspace_settings.name = "Non-Color"
    except Exception:
        pass


def _link_socket(node_tree, output_socket, input_socket):
    if node_tree is None or output_socket is None or input_socket is None:
        return False
    try:
        node_tree.links.new(output_socket, input_socket)
        return True
    except Exception:
        return False


def _create_material_from_texture_set(material_name, textures):
    textures = textures if isinstance(textures, list) else []
    if not textures:
        raise RuntimeError("没有可用贴图，无法创建材质")
    material = bpy.data.materials.new(_unique_material_name(material_name))
    material.use_nodes = True
    node_tree = material.node_tree
    nodes = node_tree.nodes
    principled = _principled_node(material)
    if principled is None:
        raise RuntimeError("无法创建 Blender 节点材质")
    first_node = None
    base_color_linked = False
    used_roles = []
    x = -700
    y = 260
    for index, texture in enumerate(textures):
        if not isinstance(texture, dict):
            continue
        path = str(texture.get("path") or "").strip()
        if not path or not os.path.exists(path):
            continue
        try:
            image = bpy.data.images.load(path, check_existing=True)
        except Exception:
            continue
        role = str(texture.get("role") or _texture_role_from_path(path) or "base_color")
        if role not in ("base_color", "alpha"):
            _set_image_non_color(image)
        try:
            image_node = nodes.new("ShaderNodeTexImage")
        except Exception:
            continue
        image_node.image = image
        image_node.label = role + " · " + os.path.basename(path)
        image_node.location = (x, y - index * 220)
        if first_node is None:
            first_node = image_node
        used_roles.append(role)
        color_output = image_node.outputs.get("Color") if hasattr(image_node.outputs, "get") else None
        alpha_output = image_node.outputs.get("Alpha") if hasattr(image_node.outputs, "get") else None
        if role == "base_color" and not base_color_linked:
            base_input = principled.inputs.get("Base Color") if hasattr(principled.inputs, "get") else None
            base_color_linked = _link_socket(node_tree, color_output, base_input)
        elif role == "roughness":
            roughness_input = principled.inputs.get("Roughness") if hasattr(principled.inputs, "get") else None
            _link_socket(node_tree, color_output, roughness_input)
        elif role == "metallic":
            metallic_input = principled.inputs.get("Metallic") if hasattr(principled.inputs, "get") else None
            _link_socket(node_tree, color_output, metallic_input)
        elif role == "alpha":
            alpha_input = principled.inputs.get("Alpha") if hasattr(principled.inputs, "get") else None
            _link_socket(node_tree, alpha_output or color_output, alpha_input)
            try:
                material.blend_method = "BLEND"
                material.show_transparent_back = True
            except Exception:
                pass
        elif role == "normal":
            try:
                normal_node = nodes.new("ShaderNodeNormalMap")
                normal_node.location = (x + 280, y - index * 220)
                normal_color = normal_node.inputs.get("Color") if hasattr(normal_node.inputs, "get") else None
                normal_output = normal_node.outputs.get("Normal") if hasattr(normal_node.outputs, "get") else None
                _link_socket(node_tree, color_output, normal_color)
                normal_input = principled.inputs.get("Normal") if hasattr(principled.inputs, "get") else None
                _link_socket(node_tree, normal_output, normal_input)
            except Exception:
                pass
    if not base_color_linked and first_node is not None:
        base_input = principled.inputs.get("Base Color") if hasattr(principled.inputs, "get") else None
        color_output = first_node.outputs.get("Color") if hasattr(first_node.outputs, "get") else None
        _link_socket(node_tree, color_output, base_input)
    material["gpt_director_texture_roles"] = ",".join(sorted(set(used_roles)))
    return material


def _apply_material_to_selected_objects(context, material):
    if material is None:
        return []
    objects = _selected_material_objects(context)
    if not objects:
        raise RuntimeError("请先选中要套用贴图材质的人物或道具")
    applied = []
    for obj in objects:
        try:
            obj.data.materials.clear()
        except Exception:
            pass
        try:
            obj.data.materials.append(material)
            applied.append(obj.name)
        except Exception:
            pass
    return applied


def _apply_hdri_to_world(context, texture):
    path = str(texture.get("path") or texture.get("source_path") or "").strip() if isinstance(texture, dict) else ""
    if not path or not os.path.exists(path):
        raise RuntimeError("HDRI 文件不存在，请重新扫描资产库")
    world = context.scene.world
    if world is None:
        world = bpy.data.worlds.new("Director World")
        context.scene.world = world
    world.use_nodes = True
    node_tree = world.node_tree
    nodes = node_tree.nodes
    background = None
    for node in nodes:
        if getattr(node, "type", "") == "BACKGROUND":
            background = node
            break
    if background is None:
        background = nodes.new("ShaderNodeBackground")
    try:
        image = bpy.data.images.load(path, check_existing=True)
        environment_node = nodes.new("ShaderNodeTexEnvironment")
        environment_node.image = image
        environment_node.location = (-500, 120)
        _link_socket(node_tree, environment_node.outputs.get("Color"), background.inputs.get("Color"))
    except Exception as exc:
        raise RuntimeError("HDRI 加载失败：" + str(exc))
    return world


def _append_material_application(data, record):
    records = data.get("material_applications")
    if not isinstance(records, list):
        records = []
    records.append(record)
    data["material_applications"] = records[-500:]
    return record


def _library_texture_asset_record(item, asset_kind, texture_items, material=None, objects=None, world=None):
    texture_items = texture_items if isinstance(texture_items, list) else []
    texture_paths = [str(texture.get("path") or "") for texture in texture_items if isinstance(texture, dict) and texture.get("path")]
    source_paths = [str(texture.get("source_path") or "") for texture in texture_items if isinstance(texture, dict) and texture.get("source_path")]
    label = str(item.get("name") or item.get("file_name") or "贴图材质") if isinstance(item, dict) else "贴图材质"
    return {{
        "id": _safe_id(label + "_" + datetime.now().strftime("%H%M%S"), "texture_asset"),
        "path": texture_paths[0] if texture_paths else str(item.get("path") or ""),
        "source_path": str(item.get("path") or ""),
        "name": label,
        "file_name": os.path.basename(texture_paths[0]) if texture_paths else str(item.get("file_name") or ""),
        "type": asset_kind,
        "format": str(item.get("format") or os.path.splitext(str(item.get("path") or ""))[1].lstrip(".").lower()),
        "objects": sorted(objects or []),
        "collections": [],
        "actions": [],
        "texture_paths": texture_paths,
        "source_texture_paths": source_paths,
        "texture_roles": sorted(set(str(texture.get("role") or "") for texture in texture_items if isinstance(texture, dict) and texture.get("role"))),
        "material_name": material.name if material else "",
        "world": world.name if world else "",
        "library_item_id": str(item.get("id") or ""),
        "library_path": str(item.get("library_path") or ""),
        "library_relative_path": str(item.get("relative_path") or ""),
        "source_profile_id": str(item.get("source_profile_id") or ""),
        "source_profile_name": str(item.get("source_profile_name") or ""),
        "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _apply_library_texture_material(context, data, item):
    if not isinstance(item, dict):
        raise RuntimeError("库资产无效")
    filepath = str(item.get("path") or "").strip()
    if not filepath or not os.path.exists(filepath):
        raise RuntimeError("库资产文件不存在，请重新扫描资产库")
    kind = str(item.get("kind_hint") or _asset_kind_from_path(filepath, item) or "texture")
    if kind not in ("material", "texture", "hdri"):
        raise RuntimeError("请选择材质、贴图或 HDRI 类型的库资产")
    if kind == "hdri":
        texture_items = _copy_texture_set_into_project(_texture_set_from_path(filepath), "hdri")
        if not texture_items:
            raise RuntimeError("没有可用 HDRI 文件")
        world = _apply_hdri_to_world(context, texture_items[0])
        asset_record = _library_texture_asset_record(item, "hdri", texture_items, None, [], world)
        _append_asset_record(data, asset_record)
        application = _append_material_application(data, {{
            "id": _safe_id("hdri_" + str(item.get("name") or item.get("file_name") or "") + "_" + datetime.now().strftime("%H%M%S"), "hdri_application"),
            "type": "hdri",
            "name": str(item.get("name") or item.get("file_name") or "HDRI 环境光"),
            "world": world.name,
            "texture_paths": asset_record.get("texture_paths", []),
            "library_item_id": str(item.get("id") or ""),
            "source_profile_name": str(item.get("source_profile_name") or ""),
            "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }})
        return asset_record, application
    texture_items = _copy_texture_set_into_project(_texture_set_from_path(filepath), "material" if kind == "material" else "texture")
    if not texture_items:
        raise RuntimeError("没有可用贴图文件")
    label = str(item.get("name") or item.get("file_name") or "贴图材质")
    material = _create_material_from_texture_set(label, texture_items)
    applied_objects = _apply_material_to_selected_objects(context, material)
    asset_record = _library_texture_asset_record(item, "material", texture_items, material, applied_objects, None)
    _append_asset_record(data, asset_record)
    application = _append_material_application(data, {{
        "id": _safe_id(label + "_" + datetime.now().strftime("%H%M%S"), "material_application"),
        "type": "material",
        "name": label,
        "material_name": material.name,
        "objects": sorted(applied_objects),
        "object_count": len(applied_objects),
        "texture_paths": asset_record.get("texture_paths", []),
        "texture_roles": asset_record.get("texture_roles", []),
        "library_item_id": str(item.get("id") or ""),
        "source_profile_name": str(item.get("source_profile_name") or ""),
        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }})
    return asset_record, application


def _mat(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def _link_to_collection(obj, collection_name):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
    try:
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
    except Exception:
        pass
    collection.objects.link(obj)
    return obj


def _ensure_collection(collection_name):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _link_collection_to_parent(collection, parent_name):
    if collection is None:
        return None
    parent = _ensure_collection(parent_name)
    try:
        child_names = [child.name for child in parent.children]
        if collection.name not in child_names:
            parent.children.link(collection)
    except Exception:
        try:
            parent.children.link(collection)
        except Exception:
            pass
    return collection


def _append_blend_asset(filepath, collection_name):
    before_object_names = set(obj.name for obj in bpy.data.objects)
    before_collection_names = set(collection.name for collection in bpy.data.collections)
    before_action_names = set(action.name for action in bpy.data.actions)
    try:
        with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
            data_to.collections = list(data_from.collections)
            data_to.objects = list(data_from.objects)
            data_to.actions = list(data_from.actions)
    except Exception as exc:
        raise RuntimeError("读取 .blend 资产失败：" + str(exc))
    imported_collections = [collection for collection in bpy.data.collections if collection.name not in before_collection_names]
    imported_objects = [obj for obj in bpy.data.objects if obj.name not in before_object_names]
    for collection in imported_collections:
        _link_collection_to_parent(collection, collection_name)
    for obj in imported_objects:
        if not obj.users_collection:
            _link_to_collection(obj, collection_name)
    imported_actions = [action.name for action in bpy.data.actions if action.name not in before_action_names]
    return imported_objects, imported_collections, imported_actions


def _import_director_asset(filepath, asset_kind="model", asset_label="", target_armature=None):
    asset_kind = asset_kind if asset_kind in ASSET_KIND_COLLECTIONS else "model"
    if asset_kind == "model" and _is_texture_asset_path(filepath):
        asset_kind = _asset_kind_from_path(filepath)
    project_asset_path = _copy_asset_into_project(filepath, asset_kind)
    import_path = project_asset_path if os.path.exists(project_asset_path) else filepath
    lower = import_path.lower()
    if _is_texture_asset_path(import_path):
        asset_kind = asset_kind if asset_kind in ("material", "texture", "hdri") else _asset_kind_from_path(import_path)
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        asset_name = asset_label or os.path.basename(filepath)
        return {{
            "id": _safe_id((asset_name or os.path.basename(filepath)) + "_" + datetime.now().strftime("%H%M%S"), "texture_asset"),
            "path": project_asset_path,
            "source_path": filepath,
            "name": asset_name,
            "file_name": os.path.basename(project_asset_path),
            "type": asset_kind,
            "format": os.path.splitext(filepath)[1].lstrip(".").lower(),
            "objects": [],
            "collections": [],
            "actions": [],
            "texture_paths": [project_asset_path],
            "source_texture_paths": [filepath],
            "texture_roles": [_texture_role_from_path(filepath)],
            "imported_as": "texture_material_asset",
            "imported_at": imported_at,
        }}
    before_object_names = set(obj.name for obj in bpy.data.objects)
    before_action_names = set(action.name for action in bpy.data.actions)
    collection = ASSET_KIND_COLLECTIONS.get(asset_kind, "Director Imported Assets")
    imported_collections = []
    if lower.endswith(".blend"):
        imported, imported_collections, imported_actions = _append_blend_asset(import_path, collection)
    elif lower.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=import_path)
    elif lower.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=import_path)
    elif lower.endswith(".obj"):
        bpy.ops.import_scene.obj(filepath=import_path)
    elif lower.endswith(".bvh"):
        bpy.ops.import_anim.bvh(filepath=import_path)
    elif lower.endswith(".stl"):
        bpy.ops.import_mesh.stl(filepath=import_path)
    elif lower.endswith(".ply"):
        bpy.ops.import_mesh.ply(filepath=import_path)
    elif lower.endswith(".abc"):
        bpy.ops.wm.alembic_import(filepath=import_path)
    elif lower.endswith((".usd", ".usdz")):
        if not hasattr(bpy.ops.wm, "usd_import"):
            raise RuntimeError("当前 Blender 版本没有 USD 导入器，请升级 Blender 或先转换为 GLB/FBX。")
        bpy.ops.wm.usd_import(filepath=import_path)
    else:
        raise RuntimeError("只支持 blend/glb/gltf/fbx/obj/bvh/stl/ply/abc/usd/usdz/png/jpg/tif/exr/hdr")
    if not lower.endswith(".blend"):
        imported = [obj for obj in bpy.data.objects if obj.name not in before_object_names]
        imported_actions = [action.name for action in bpy.data.actions if action.name not in before_action_names]
        for obj in imported:
            _link_to_collection(obj, collection)
    imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    asset_name = asset_label or os.path.basename(filepath)
    asset_record = {{
        "id": _safe_id((asset_name or os.path.basename(filepath)) + "_" + datetime.now().strftime("%H%M%S"), "asset"),
        "path": project_asset_path,
        "source_path": filepath,
        "name": asset_name,
        "file_name": os.path.basename(project_asset_path),
        "type": asset_kind,
        "format": os.path.splitext(filepath)[1].lstrip(".").lower(),
        "objects": sorted(obj.name for obj in imported),
        "collections": sorted(collection.name for collection in imported_collections),
        "actions": imported_actions,
        "imported_at": imported_at,
    }}
    control_record = _attach_imported_asset_controls(asset_record.get("id", ""), asset_name, asset_kind, imported)
    if control_record:
        asset_record.update(control_record)
    if asset_kind == "action":
        action = _latest_action(imported_actions[-1] if imported_actions else "")
        if action:
            bpy.context.scene.gpt_director_action_name = action.name
        if target_armature and action:
            ok, message = _apply_action_to_armature(target_armature, action)
            status = "applied" if ok else "failed"
            asset_record["auto_apply_status"] = status
            asset_record["auto_apply_message"] = message
            asset_record["target_armature"] = target_armature.name
        else:
            asset_record["auto_apply_status"] = "not_applied"
            asset_record["auto_apply_message"] = "未选中目标骨骼，可稍后手动套用"
    return asset_record


def _append_asset_record(data, asset_record):
    assets = data.get("assets")
    if not isinstance(assets, list):
        assets = []
    assets.append(asset_record)
    data["assets"] = assets[-500:]
    return data



def _link_object_to_collection_without_moving(obj, collection_name):
    if obj is None:
        return None
    collection = _ensure_collection(collection_name)
    try:
        names = [item.name for item in collection.objects]
        if obj.name not in names:
            collection.objects.link(obj)
    except Exception:
        try:
            collection.objects.link(obj)
        except Exception:
            pass
    return collection


def _actions_from_objects(objects):
    actions = []
    for obj in objects:
        action = None
        try:
            if obj.animation_data:
                action = obj.animation_data.action
        except Exception:
            action = None
        if action and action.name:
            actions.append(action.name)
    return sorted(set(actions))


def _register_selected_asset(asset_kind="model", asset_label=""):
    asset_kind = asset_kind if asset_kind in ASSET_KIND_COLLECTIONS else "model"
    selected = [obj for obj in bpy.context.selected_objects if obj and obj.type != "CAMERA"]
    if not selected:
        raise RuntimeError("请先在 Blender 里选中要登记为资产的对象")
    asset_name = str(asset_label or "").strip() or ("工程资产 " + datetime.now().strftime("%H%M%S"))
    asset_id = _safe_id(asset_name + "_" + datetime.now().strftime("%H%M%S"), "asset")
    collection_name = "Director Asset " + asset_id
    collection = _ensure_collection(collection_name)
    _link_collection_to_parent(collection, ASSET_KIND_COLLECTIONS.get(asset_kind, "Director Imported Assets"))
    for obj in selected:
        _link_object_to_collection_without_moving(obj, collection_name)
    return {{
        "id": asset_id,
        "path": "",
        "source_path": "",
        "name": asset_name,
        "file_name": "",
        "type": asset_kind,
        "format": "selected",
        "objects": sorted(obj.name for obj in selected),
        "collections": [collection_name],
        "actions": _actions_from_objects(selected),
        "registered_from": "selected_objects",
        "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _asset_key_for_record(asset, index=0):
    if not isinstance(asset, dict):
        return ""
    asset_id = str(asset.get("id") or "").strip()
    if asset_id:
        return asset_id
    source = str(asset.get("path") or asset.get("name") or asset.get("file_name") or "asset").strip()
    return _safe_id(source + "_" + str(index), "asset")


def _asset_enum_items(self, context):
    items = [("__manual__", "手动选择/当前对象", "使用 Blender 当前选中的对象")]
    data = _load_meta()
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    seen = set(["__manual__"])
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            continue
        key = _asset_key_for_record(asset, index)
        if not key or key in seen:
            continue
        kind = ASSET_KIND_COLLECTIONS.get(str(asset.get("type") or ""), "资产")
        name = str(asset.get("name") or asset.get("file_name") or key).strip()
        object_count = len(asset.get("objects")) if isinstance(asset.get("objects"), list) else 0
        collection_count = len(asset.get("collections")) if isinstance(asset.get("collections"), list) else 0
        action_count = len(asset.get("actions")) if isinstance(asset.get("actions"), list) else 0
        detail_parts = []
        if object_count:
            detail_parts.append("对象 " + str(object_count))
        if asset.get("control_root"):
            detail_parts.append("可控")
        if collection_count:
            detail_parts.append("集合 " + str(collection_count))
        if action_count:
            detail_parts.append("动作 " + str(action_count))
        description = " · ".join(detail_parts) if detail_parts else "工程资产"
        items.append((key, name + " · " + kind.replace("Director ", ""), description))
        seen.add(key)
    return items


def _find_asset(data, key):
    key = str(key or "").strip()
    if not key or key == "__manual__":
        return {{}}
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            continue
        values = [
            _asset_key_for_record(asset, index),
            str(asset.get("id") or ""),
            str(asset.get("name") or ""),
            str(asset.get("path") or ""),
            str(asset.get("file_name") or ""),
        ]
        if key in values:
            return dict(asset)
    return {{}}


def _select_objects_by_names(names):
    raw_names = names if isinstance(names, (list, tuple, set)) else [names]
    clean_names = []
    seen = set()
    for name in raw_names:
        name = str(name or "").strip()
        if name and name not in seen:
            clean_names.append(name)
            seen.add(name)
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    selected = []
    for name in clean_names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            obj.select_set(True)
            selected.append(obj)
        except Exception:
            pass
    if selected:
        bpy.context.view_layer.objects.active = selected[0]
    return len(selected)


def _select_asset_objects(asset):
    if not isinstance(asset, dict):
        return 0
    names = []
    control_root = str(asset.get("control_root") or "").strip()
    if control_root:
        names.append(control_root)
    raw_control_objects = asset.get("control_objects")
    if isinstance(raw_control_objects, list):
        names.extend(str(name or "").strip() for name in raw_control_objects)
    raw_objects = asset.get("objects")
    if not names and isinstance(raw_objects, list):
        names.extend(str(name or "").strip() for name in raw_objects)
    raw_collections = asset.get("collections")
    if not names and isinstance(raw_collections, list):
        for collection_name in raw_collections:
            collection = bpy.data.collections.get(str(collection_name or ""))
            if collection:
                names.extend(obj.name for obj in collection.objects)
    selected_count = _select_objects_by_names(names)
    actions = asset.get("actions")
    if isinstance(actions, list) and actions:
        bpy.context.scene.gpt_director_action_name = str(actions[-1] or "")
    return selected_count


def _director_collection_names():
    return [
        "Director Base",
        "Director Scenes",
        "Director Props",
        "Director Characters",
        "Director Cameras",
        "Director Lights",
        "Director Controls",
        "Director Imported Assets",
    ]


def _clear_director_workbench():
    for collection_name in _director_collection_names():
        _clear_collection(collection_name)


def _object_names(objects):
    return sorted(set(obj.name for obj in objects if obj is not None and obj.name))


def _set_director_tags(obj, asset_id="", asset_kind="", role=""):
    if obj is None:
        return obj
    try:
        if asset_id:
            obj["gpt_director_asset_id"] = asset_id
        if asset_kind:
            obj["gpt_director_asset_kind"] = asset_kind
        if role:
            obj["gpt_director_role"] = role
    except Exception:
        pass
    return obj


def _set_director_label_visibility(obj, visible=False):
    if obj is None:
        return obj
    try:
        obj.show_name = bool(visible)
    except Exception:
        pass
    try:
        if obj.type == "ARMATURE" and obj.data is not None:
            obj.data.show_names = bool(visible)
    except Exception:
        pass
    return obj


def _is_director_control_object(obj):
    if obj is None:
        return False
    try:
        return (
            obj.name.startswith("蓝色人偶")
            or obj.name.startswith("红色人偶")
            or obj.name.startswith("Director ")
            or bool(obj.get("gpt_director_asset_id", ""))
            or bool(obj.get("gpt_director_control_hint", ""))
            or bool(obj.get("gpt_director_control_bone", ""))
        )
    except Exception:
        return False


def _is_director_mannequin_armature(obj):
    if obj is None or getattr(obj, "type", "") != "ARMATURE":
        return False
    try:
        if str(obj.get("gpt_director_asset_kind", "")) == "character":
            return True
        if "骨骼控制器" in str(obj.name or ""):
            return True
        bones = getattr(getattr(obj, "pose", None), "bones", None)
        if bones is not None:
            known_controls = ("hand.IK.L", "hand.IK.R", "foot.IK.L", "foot.IK.R")
            return any(bones.get(name) is not None for name in known_controls)
    except Exception:
        pass
    return False


def _remove_mannequin_custom_shapes():
    removed = 0
    for obj in bpy.data.objects:
        if not _is_director_mannequin_armature(obj):
            continue
        try:
            for pose_bone in obj.pose.bones:
                if pose_bone.custom_shape is not None:
                    pose_bone.custom_shape = None
                    removed += 1
        except Exception:
            pass
        try:
            obj.data.show_names = False
            obj.data.show_bone_custom_shapes = False
        except Exception:
            pass
    return removed


def _remove_mannequin_rig_ui_objects():
    removable = []
    for obj in bpy.data.objects:
        try:
            parent = obj.parent
            if (
                obj.type == "MESH"
                and parent is not None
                and _is_director_mannequin_armature(parent)
                and bool(obj.hide_render)
                and not bool(obj.get("gpt_director_recolor_material", ""))
            ):
                removable.append(obj)
        except Exception:
            pass
    for obj in removable:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    return len(removable)


def _set_all_director_label_visibility(visible=False):
    changed = 0
    for obj in bpy.data.objects:
        if not _is_director_control_object(obj):
            continue
        _set_director_label_visibility(obj, visible)
        changed += 1
    return changed


def _director_view3d_screens(context=None):
    screens = []
    try:
        screen = context.screen if context is not None else bpy.context.screen
        if screen is not None:
            screens.append(screen)
    except Exception:
        pass
    try:
        for screen in bpy.data.screens:
            if screen not in screens:
                screens.append(screen)
    except Exception:
        pass
    return screens


def _set_view3d_relationship_lines(context=None, visible=False):
    for screen in _director_view3d_screens(context):
        for area in getattr(screen, "areas", []):
            if getattr(area, "type", "") != "VIEW_3D":
                continue
            for space in getattr(area, "spaces", []):
                if getattr(space, "type", "") != "VIEW_3D":
                    continue
                try:
                    space.overlay.show_relationship_lines = bool(visible)
                except Exception:
                    pass


def _set_view3d_simple_overlays(context=None, simple=True):
    for screen in _director_view3d_screens(context):
        for area in getattr(screen, "areas", []):
            if getattr(area, "type", "") != "VIEW_3D":
                continue
            for space in getattr(area, "spaces", []):
                if getattr(space, "type", "") != "VIEW_3D":
                    continue
                try:
                    space.overlay.show_relationship_lines = not bool(simple)
                except Exception:
                    pass
                try:
                    space.overlay.show_extras = not bool(simple)
                except Exception:
                    pass
                try:
                    space.overlay.show_floor = True
                    space.overlay.show_ortho_grid = True
                except Exception:
                    pass
                for attr in ("show_axis_x", "show_axis_y", "show_axis_z"):
                    try:
                        setattr(space.overlay, attr, not bool(simple))
                    except Exception:
                        pass


def _set_director_clean_view(context=None, enabled=True):
    clean = bool(enabled)
    changed = _set_all_director_label_visibility(False)
    for obj in bpy.data.objects:
        if not _is_director_control_object(obj):
            continue
        role = str(obj.get("gpt_director_role", ""))
        asset_kind = str(obj.get("gpt_director_asset_kind", ""))
        try:
            if role == "viewport_control":
                obj.hide_set(clean)
                changed += 1
        except Exception:
            pass
        try:
            if obj.type == "ARMATURE" and asset_kind == "character":
                obj.hide_viewport = False
                obj.hide_set(clean)
                obj.show_in_front = not clean
                if obj.data is not None:
                    obj.data.show_names = False
                    obj.data.display_type = "STICK" if clean else "BBONE"
                    try:
                        obj.data.show_bone_custom_shapes = not clean
                    except Exception:
                        pass
                changed += 1
        except Exception:
            pass
        try:
            if role == "pose_proxy":
                original_size = float(obj.get("gpt_director_original_display_size", obj.empty_display_size) or obj.empty_display_size or 0.1)
                obj["gpt_director_original_display_size"] = original_size
                obj.empty_display_size = min(original_size, 0.08) if clean else original_size
                obj.show_in_front = True
                obj.hide_set(False)
                changed += 1
        except Exception:
            pass
    _set_view3d_relationship_lines(context, not clean)
    return changed


def _set_director_simple_view(context=None, enabled=True):
    simple = bool(enabled)
    changed = _set_all_director_label_visibility(False)
    if simple:
        changed += _remove_mannequin_rig_ui_objects()
        changed += _remove_mannequin_custom_shapes()
    try:
        widgets_collection = bpy.data.collections.get("Director Mannequin Widgets")
        if widgets_collection is not None:
            widgets_collection.hide_viewport = True
            widgets_collection.hide_render = True
    except Exception:
        pass
    for obj in bpy.data.objects:
        if simple and (str(obj.name or "").startswith("横向网格 ") or str(obj.name or "").startswith("纵向网格 ")):
            try:
                obj.hide_set(True)
                changed += 1
            except Exception:
                pass
            continue
        if simple and getattr(obj, "type", "") in {{"LIGHT", "CAMERA"}}:
            try:
                obj.hide_set(True)
                changed += 1
            except Exception:
                pass
            continue
        mannequin_armature = _is_director_mannequin_armature(obj)
        if not _is_director_control_object(obj) and not mannequin_armature:
            continue
        role = str(obj.get("gpt_director_role", ""))
        asset_kind = str(obj.get("gpt_director_asset_kind", ""))
        try:
            if mannequin_armature:
                obj.hide_viewport = simple
                obj.hide_set(simple)
                obj.show_in_front = not simple
                if obj.data is not None:
                    obj.data.show_names = False
                    obj.data.display_type = "STICK" if simple else "BBONE"
                    try:
                        obj.data.show_bone_custom_shapes = not simple
                    except Exception:
                        pass
                changed += 1
                continue
        except Exception:
            pass
        try:
            if obj.type == "EMPTY" or role in {"pose_proxy", "viewport_control", "import_control"} or asset_kind == "control":
                obj.hide_set(simple)
                changed += 1
        except Exception:
            pass
    _set_view3d_simple_overlays(context, simple)
    return changed


def _director_drag_root_for_object(obj):
    if obj is None:
        return None
    asset_id = str(obj.get("gpt_director_asset_id", "")).strip()
    if not asset_id and not _is_director_control_object(obj):
        return None
    current = obj
    while current is not None:
        try:
            if current.type == "EMPTY" and (not asset_id or str(current.get("gpt_director_asset_id", "")).strip() == asset_id):
                return current
        except Exception:
            pass
        current = getattr(current, "parent", None)
    if asset_id:
        candidates = []
        for candidate in bpy.data.objects:
            try:
                if str(candidate.get("gpt_director_asset_id", "")).strip() != asset_id:
                    continue
                if candidate.type != "EMPTY":
                    continue
                role = str(candidate.get("gpt_director_role", ""))
                score = 0
                if "根控制器" in candidate.name or "root" in candidate.name.lower():
                    score += 100
                if "整体移动" in str(candidate.get("gpt_director_control_hint", "")):
                    score += 80
                if role in {"pose_proxy", "viewport_control"}:
                    score -= 80
                if candidate.parent is None:
                    score += 20
                candidates.append((score, candidate.name, candidate))
            except Exception:
                pass
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][2]
    return obj


def _view3d_window_region_and_space(context):
    area = getattr(context, "area", None)
    if area is None or getattr(area, "type", "") != "VIEW_3D":
        return None, None
    region = None
    for item in getattr(area, "regions", []):
        if getattr(item, "type", "") == "WINDOW":
            region = item
            break
    space = getattr(context, "space_data", None)
    if space is None or getattr(space, "type", "") != "VIEW_3D":
        for item in getattr(area, "spaces", []):
            if getattr(item, "type", "") == "VIEW_3D":
                space = item
                break
    if region is None or space is None or getattr(space, "region_3d", None) is None:
        return None, None
    return region, space


def _event_in_view3d_window(context, event):
    region, _space = _view3d_window_region_and_space(context)
    if region is None:
        return False
    try:
        mouse_x = int(event.mouse_x)
        mouse_y = int(event.mouse_y)
        area = getattr(context, "area", None)
        interface_region_types = {{"UI", "HEADER", "TOOL_HEADER", "TOOLS", "HUD", "ASSET_SHELF", "ASSET_SHELF_HEADER"}}
        for item in getattr(area, "regions", []):
            if getattr(item, "type", "") not in interface_region_types:
                continue
            if int(getattr(item, "width", 0)) <= 0 or int(getattr(item, "height", 0)) <= 0:
                continue
            if item.x <= mouse_x < item.x + item.width and item.y <= mouse_y < item.y + item.height:
                return False
        return (
            region.x <= mouse_x < region.x + region.width
            and region.y <= mouse_y < region.y + region.height
        )
    except Exception:
        return False


def _view3d_mouse_ray(context, event):
    region, space = _view3d_window_region_and_space(context)
    if region is None or space is None:
        return None, None
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    try:
        origin = view3d_utils.region_2d_to_origin_3d(region, space.region_3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, space.region_3d, coord)
        return origin, direction
    except Exception:
        return None, None


def _view3d_plane_intersection(context, event, z_value=0.0):
    origin, direction = _view3d_mouse_ray(context, event)
    if origin is None or direction is None:
        return None
    try:
        denom = float(direction.z)
        if abs(denom) < 1e-6:
            return None
        distance = (float(z_value) - float(origin.z)) / denom
        if distance < 0:
            return None
        return origin + direction * distance
    except Exception:
        return None


def _raycast_visible_director_object(context, event):
    origin, direction = _view3d_mouse_ray(context, event)
    if origin is None or direction is None:
        return None, None
    try:
        depsgraph = context.evaluated_depsgraph_get()
        result = context.scene.ray_cast(depsgraph, origin, direction, distance=1000.0)
    except TypeError:
        try:
            result = context.scene.ray_cast(origin, direction, distance=1000.0)
        except Exception:
            return None, None
    except Exception:
        return None, None
    try:
        hit = bool(result[0])
        location = result[1]
        obj = result[4]
    except Exception:
        return None, None
    if not hit or obj is None:
        return None, None
    return obj, location


def _add_empty_control(name, location=(0, 0, 0), asset_id="", asset_kind="model", role=""):
    bpy.ops.object.empty_add(type="ARROWS", location=location)
    root = bpy.context.object
    root.name = name
    root.empty_display_size = 0.58 if asset_kind == "character" else 0.45
    _set_director_label_visibility(root, False)
    try:
        root.show_in_front = True
        root.color = (1.0, 0.72, 0.12, 1.0)
        root["gpt_director_control_hint"] = "拖动此根控制器可整体移动、旋转或缩放资产"
    except Exception:
        pass
    _set_director_tags(root, asset_id, asset_kind, role)
    _link_to_collection(root, "Director Controls")
    return root


def _parent_to_root(obj, root, local_location=None, local_rotation=None):
    if obj is None or root is None:
        return obj
    obj.parent = root
    if local_location is not None:
        obj.location = local_location
    if local_rotation is not None:
        obj.rotation_euler = local_rotation
    return obj


def _add_control_ring(root, name, radius=0.46, color=(0.92, 0.78, 0.18, 0.55)):
    mat = _mat(name + " 材质", color)
    try:
        mat.use_nodes = False
        mat.diffuse_color = color
    except Exception:
        pass
    try:
        bpy.ops.mesh.primitive_torus_add(major_radius=radius, minor_radius=0.012, major_segments=64, minor_segments=8, location=(0, 0, 0.02))
        ring = bpy.context.object
        ring.name = name
        ring.data.materials.append(mat)
        _link_to_collection(ring, "Director Controls")
        _parent_to_root(ring, root, (0, 0, 0.02), (0, 0, 0))
        ring.hide_render = True
        ring.hide_select = True
        ring.show_in_front = True
        ring.display_type = "WIRE"
        try:
            ring.hide_set(True)
        except Exception:
            pass
        _set_director_tags(ring, str(root.get("gpt_director_asset_id", "")), "control", "viewport_control")
        return ring
    except Exception:
        return None


def _imported_asset_control_location(objects):
    points = []
    for obj in objects or []:
        if obj is None:
            continue
        try:
            points.append(obj.matrix_world.translation.copy())
        except Exception:
            try:
                points.append(obj.location.copy())
            except Exception:
                pass
    if not points:
        return Vector((0, 0, 0)), 0.72
    min_x = min(point.x for point in points)
    max_x = max(point.x for point in points)
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)
    min_z = min(point.z for point in points)
    max_z = max(point.z for point in points)
    center = Vector(((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5))
    span = max(max_x - min_x, max_y - min_y, max_z - min_z)
    radius = max(0.48, min(4.0, span * 0.65 if span > 0 else 0.72))
    return center, radius


def _parent_preserve_world(obj, root):
    if obj is None or root is None:
        return obj
    try:
        matrix = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
        obj.matrix_world = matrix
    except Exception:
        try:
            obj.parent = root
        except Exception:
            pass
    return obj


def _attach_imported_asset_controls(asset_id, asset_name, asset_kind, imported_objects):
    if asset_kind not in ("character", "prop", "scene", "model"):
        return {{}}
    imported_objects = [obj for obj in (imported_objects or []) if obj is not None]
    if not imported_objects:
        return {{}}
    label = str(asset_name or asset_id or "导入资产")
    location, radius = _imported_asset_control_location(imported_objects)
    root = _add_empty_control(label + " 导演控制器", location, asset_id, asset_kind, "import_control")
    ring = _add_control_ring(root, label + " 导演控制圈", radius=radius)
    imported_names = set(obj.name for obj in imported_objects if obj is not None and obj.name)
    top_level = []
    for obj in imported_objects:
        parent = getattr(obj, "parent", None)
        if parent is None or str(getattr(parent, "name", "") or "") not in imported_names:
            top_level.append(obj)
    if not top_level:
        top_level = list(imported_objects)
    for obj in imported_objects:
        _set_director_tags(obj, asset_id, asset_kind, "imported_asset")
    for obj in top_level:
        _parent_preserve_world(obj, root)
    control_objects = [root.name]
    if ring is not None:
        control_objects.append(ring.name)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        root.select_set(True)
        bpy.context.view_layer.objects.active = root
    except Exception:
        pass
    return {{
        "control_root": root.name,
        "control_objects": control_objects,
        "controlled_objects": sorted(set(obj.name for obj in imported_objects if obj is not None and obj.name)),
        "controls": ["root_empty", "viewport_control_ring", "drag_transform", "object_motion", "select_asset"],
        "control_role": "imported_asset_control",
    }}


def _upsert_asset_record(data, asset_record):
    if not isinstance(asset_record, dict):
        return data
    assets = data.get("assets")
    if not isinstance(assets, list):
        assets = []
    asset_id = str(asset_record.get("id") or "").strip()
    replaced = False
    for idx, existing in enumerate(assets):
        if isinstance(existing, dict) and asset_id and str(existing.get("id") or "") == asset_id:
            merged = dict(existing)
            merged.update(asset_record)
            assets[idx] = merged
            replaced = True
            break
    if not replaced:
        assets.append(asset_record)
    data["assets"] = assets[-500:]
    return data


def _record_builtin_asset(data, asset_id, name, asset_kind, objects, collections=None, note=""):
    object_names = _object_names(objects)
    record = dict(
        id=asset_id,
        path="",
        source_path="builtin://" + asset_id,
        name=name,
        file_name="",
        type=asset_kind,
        format="procedural",
        license="procedural_local",
        objects=object_names,
        collections=list(collections or []),
        actions=[],
        controls=["root_empty", "viewport_control_ring", "drag_transform", "object_motion"],
        note=note,
        registered_from="builtin_director_kit",
        imported_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    return _upsert_asset_record(data, record)


def _record_builtin_actor(data, actor_id, name, role, objects, note=""):
    object_names = _object_names(objects)
    actor = dict(
        id=actor_id,
        name=name,
        role=role,
        note=note,
        objects=[_object_snapshot(obj) for obj in objects if obj is not None],
        object_names=object_names,
        object_count=len(object_names),
        actions=_actions_from_objects(objects),
        saved_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        registered_from="builtin_director_kit",
    )
    return _upsert_actor(data, actor)


def _select_roots(objects):
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    selected = []
    for obj in objects:
        if obj is None:
            continue
        try:
            obj.select_set(True)
            selected.append(obj)
        except Exception:
            pass
    if selected:
        bpy.context.view_layer.objects.active = selected[0]
    return selected


def _clear_collection(collection_name):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        return
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _cube(name, location, scale, mat, collection="Director Base"):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    _link_to_collection(obj, collection)
    return obj


def _cylinder(name, location, radius, depth, mat, rotation=(0, 0, 0), collection="Director Assets"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    _link_to_collection(obj, collection)
    return obj


def _sphere(name, location, radius, mat, collection="Director Assets"):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    _link_to_collection(obj, collection)
    return obj


def _look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _add_camera(name="Director Camera", location=(4.0, -6.0, 2.6), target=(0, 0, 1.1), lens=35):
    bpy.ops.object.camera_add(location=location)
    camera = bpy.context.object
    camera.name = name
    camera.data.lens = lens
    _look_at(camera, target)
    bpy.context.scene.camera = camera
    _link_to_collection(camera, "Director Cameras")
    return camera


def _set_camera_preset(preset):
    presets = {{
        "wide": ((4.6, -6.2, 2.7), (0, 0, 1.0), 24),
        "medium": ((3.2, -4.4, 2.0), (0, 0, 1.15), 35),
        "close": ((1.7, -2.5, 1.65), (0, 0, 1.35), 55),
        "top": ((0.0, -0.6, 6.2), (0, 0, 0.7), 32),
    }}
    location, target, lens = presets.get(preset, presets["medium"])
    camera = bpy.context.scene.camera
    if camera is None or camera.type != "CAMERA":
        camera = _add_camera()
    camera.location = location
    camera.data.lens = lens
    _look_at(camera, target)
    bpy.context.scene.camera = camera
    return camera


def _add_area_light(name, location, target, energy, size):
    existing = bpy.data.objects.get(name)
    if existing and existing.type == "LIGHT":
        light = existing
        light.location = location
    else:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = name
    light.data.energy = energy
    light.data.size = size
    _look_at(light, target)
    _link_to_collection(light, "Director Lights")
    return light


def _add_three_point_lighting():
    _add_area_light("Director Key Light", (-2.6, -3.8, 4.2), (0, 0, 1.1), 520, 4.0)
    _add_area_light("Director Fill Light", (3.2, -2.4, 2.8), (0, 0, 1.1), 140, 5.0)
    _add_area_light("Director Rim Light", (0.0, 3.2, 3.2), (0, 0, 1.2), 300, 2.2)


def _active_light_template_name():
    scene = bpy.context.scene
    name = str(getattr(scene, "gpt_director_light_template_name", "") or "").strip()
    return name or "未命名灯光模板"


def _active_light_template_note():
    scene = bpy.context.scene
    return str(getattr(scene, "gpt_director_light_template_note", "") or "").strip()


def _light_snapshot(light):
    if not light or light.type != "LIGHT":
        return {{}}
    data = light.data
    snapshot = {{
        "name": light.name,
        "light_type": str(getattr(data, "type", "POINT") or "POINT"),
        "location": [round(v, 5) for v in light.location],
        "rotation": [round(v, 5) for v in light.rotation_euler],
        "scale": [round(v, 5) for v in light.scale],
        "energy": round(float(getattr(data, "energy", 0) or 0), 5),
        "color": [round(float(v), 5) for v in getattr(data, "color", (1, 1, 1))],
        "hide_viewport": bool(getattr(light, "hide_viewport", False)),
        "hide_render": bool(getattr(light, "hide_render", False)),
    }}
    for attr in ("use_shadow", "shadow_soft_size", "size", "size_y", "spot_size", "spot_blend"):
        try:
            value = getattr(data, attr)
        except Exception:
            continue
        if isinstance(value, bool):
            snapshot[attr] = bool(value)
        elif value is not None:
            try:
                snapshot[attr] = round(float(value), 5)
            except Exception:
                snapshot[attr] = value
    return snapshot


def _active_light_snapshots(context):
    lights = [obj for obj in (context.selected_objects or []) if obj and obj.type == "LIGHT"]
    if not lights:
        lights = [obj for obj in context.scene.objects if obj and obj.type == "LIGHT"]
    if not lights:
        raise RuntimeError("当前场景没有可保存的灯光，请先添加灯光")
    return [_light_snapshot(light) for light in lights]


def _light_template_from_current_scene(context, template_id, template_name, template_note):
    lights = _active_light_snapshots(context)
    return {{
        "id": template_id,
        "name": template_name,
        "note": template_note,
        "lights": lights,
        "light_count": len(lights),
        "frame": int(context.scene.frame_current),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}


def _upsert_light_template(data, template):
    templates = data.get("light_templates")
    if not isinstance(templates, list):
        templates = []
    template_id = template.get("id")
    replaced = False
    for idx, existing in enumerate(templates):
        if isinstance(existing, dict) and existing.get("id") == template_id:
            merged = dict(existing)
            merged.update(template)
            templates[idx] = merged
            replaced = True
            break
    if not replaced:
        templates.append(template)
    data["light_templates"] = templates[-500:]
    return data


def _active_light_template_key(scene):
    choice = str(getattr(scene, "gpt_director_light_template_choice", "") or "").strip()
    if choice and choice != "__manual__":
        return choice
    return str(getattr(scene, "gpt_director_selected_light_template", "") or "").strip()


def _light_template_enum_items(self, context):
    items = [("__manual__", "手动输入/当前灯光", "使用下方灯光模板ID/名称输入框")]
    data = _load_meta()
    templates = data.get("light_templates") if isinstance(data.get("light_templates"), list) else []
    seen = set(["__manual__"])
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "").strip()
        if not template_id or template_id in seen:
            continue
        name = str(template.get("name") or template_id).strip()
        lights = template.get("lights") if isinstance(template.get("lights"), list) else []
        light_names = [str(item.get("name") or "").strip() for item in lights if isinstance(item, dict)]
        light_names = [item for item in light_names if item]
        detail_parts = []
        if light_names:
            label = "、".join(light_names[:4])
            if len(light_names) > 4:
                label += " 等 " + str(len(light_names)) + " 个"
            detail_parts.append(label)
        note = str(template.get("note") or "").strip()
        if note:
            detail_parts.append(note)
        description = "｜".join(detail_parts) if detail_parts else "灯光模板"
        items.append((template_id, name, description))
        seen.add(template_id)
    return items


def _find_light_template(data, key):
    key = str(key or "").strip()
    if not key:
        key = _active_light_template_name()
    templates = data.get("light_templates") if isinstance(data.get("light_templates"), list) else []
    for template in reversed(templates):
        if not isinstance(template, dict):
            continue
        if key in (str(template.get("id") or ""), str(template.get("name") or "")):
            return dict(template)
    return {{}}


def _delete_light_template(data, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    templates = data.get("light_templates") if isinstance(data.get("light_templates"), list) else []
    kept = []
    removed = False
    for item in templates:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if (template_id and str(item.get("id") or "") == template_id) or (template_name and str(item.get("name") or "") == template_name):
            removed = True
            continue
        kept.append(item)
    data["light_templates"] = kept
    return removed


def _ensure_light_from_snapshot(item):
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "Director Light").strip()
    light_type = str(item.get("light_type") or "POINT").strip().upper()
    if light_type not in ("POINT", "SUN", "SPOT", "AREA"):
        light_type = "POINT"
    obj = bpy.data.objects.get(name) if name else None
    if obj is None or obj.type != "LIGHT":
        bpy.ops.object.light_add(type=light_type, location=(0, 0, 0))
        obj = bpy.context.object
        obj.name = name or "Director Light"
    try:
        obj.data.type = light_type
    except Exception:
        pass
    data = obj.data
    location = item.get("location")
    rotation = item.get("rotation")
    scale = item.get("scale")
    if isinstance(location, list) and len(location) >= 3:
        obj.location = (float(location[0]), float(location[1]), float(location[2]))
    if isinstance(rotation, list) and len(rotation) >= 3:
        obj.rotation_euler = (float(rotation[0]), float(rotation[1]), float(rotation[2]))
    if isinstance(scale, list) and len(scale) >= 3:
        obj.scale = (float(scale[0]), float(scale[1]), float(scale[2]))
    for attr in ("energy", "use_shadow", "shadow_soft_size", "size", "size_y", "spot_size", "spot_blend"):
        if attr not in item:
            continue
        try:
            setattr(data, attr, item.get(attr))
        except Exception:
            pass
    color = item.get("color")
    if isinstance(color, list) and len(color) >= 3:
        try:
            data.color = (float(color[0]), float(color[1]), float(color[2]))
        except Exception:
            pass
    if "hide_viewport" in item:
        obj.hide_viewport = bool(item.get("hide_viewport"))
    if "hide_render" in item:
        obj.hide_render = bool(item.get("hide_render"))
    _link_to_collection(obj, "Director Lights")
    return obj


def _apply_light_template(context, template):
    if not isinstance(template, dict):
        return 0
    lights = template.get("lights") if isinstance(template.get("lights"), list) else []
    applied = 0
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    for item in lights:
        light = _ensure_light_from_snapshot(item)
        if light:
            applied += 1
            try:
                light.select_set(True)
                context.view_layer.objects.active = light
            except Exception:
                pass
    try:
        context.scene.frame_current = int(template.get("frame") or context.scene.frame_current)
    except Exception:
        pass
    return applied


def _camera_motion_target():
    selected = [obj for obj in bpy.context.selected_objects if obj.type != "CAMERA"]
    if selected:
        total = Vector((0, 0, 0))
        for obj in selected:
            total += obj.location
        center = total / max(len(selected), 1)
        return (center.x, center.y, center.z + 1.0)
    return (0, 0, 1.15)


def _camera_right_vector(camera):
    try:
        return camera.matrix_world.to_quaternion() @ Vector((1, 0, 0))
    except Exception:
        return Vector((1, 0, 0))


def _insert_camera_key(camera, frame, target):
    scene = bpy.context.scene
    scene.frame_set(int(frame))
    _look_at(camera, target)
    camera.keyframe_insert(data_path="location", frame=int(frame))
    camera.keyframe_insert(data_path="rotation_euler", frame=int(frame))
    try:
        camera.data.keyframe_insert(data_path="lens", frame=int(frame))
    except Exception:
        pass


def _record_camera_motion(data, motion, camera_name, frame_start, frame_end):
    motions = data.get("camera_motions")
    if not isinstance(motions, list):
        motions = []
    motions.append({{
        "motion": motion,
        "label": CAMERA_MOTION_LABELS.get(motion, motion),
        "camera": camera_name,
        "frame_start": int(frame_start),
        "frame_end": int(frame_end),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }})
    data["camera_motions"] = motions[-500:]
    return data


def _apply_camera_motion(motion):
    scene = bpy.context.scene
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        camera = _add_camera()
    target = _camera_motion_target()
    frame_start, frame_end = _active_frame_range(scene)
    if frame_end <= frame_start:
        frame_end = frame_start + 48
        scene.gpt_director_frame_end = frame_end
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    start_location = Vector(camera.location)
    _look_at(camera, target)
    direction = Vector(target) - start_location
    if direction.length <= 0.001:
        direction = Vector((0, -1, 0))
    direction.normalize()
    right = _camera_right_vector(camera)
    if right.length <= 0.001:
        right = Vector((1, 0, 0))
    right.normalize()
    offset = Vector((0, 0, 0))
    if motion == "push_in":
        offset = direction * 1.1
    elif motion == "pull_out":
        offset = -direction * 1.1
    elif motion == "truck_left":
        offset = -right * 1.1
    elif motion == "truck_right":
        offset = right * 1.1
    elif motion == "rise":
        offset = Vector((0, 0, 0.8))
    elif motion == "descend":
        offset = Vector((0, 0, -0.8))
    _insert_camera_key(camera, frame_start, target)
    camera.location = start_location + offset
    _insert_camera_key(camera, frame_end, target)
    scene.frame_set(frame_start)
    camera.location = start_location
    _look_at(camera, target)
    return camera, frame_start, frame_end


def _selected_motion_objects():
    return [obj for obj in bpy.context.selected_objects if obj.type not in {{"CAMERA", "LIGHT"}}]


def _object_motion_offset(motion):
    if motion == "forward":
        return Vector((0, -1.0, 0))
    if motion == "backward":
        return Vector((0, 1.0, 0))
    if motion == "left":
        return Vector((-1.0, 0, 0))
    if motion == "right":
        return Vector((1.0, 0, 0))
    if motion == "rise":
        return Vector((0, 0, 0.8))
    if motion == "descend":
        return Vector((0, 0, -0.8))
    return Vector((0, -1.0, 0))


def _record_object_motion(data, motion, object_names, frame_start, frame_end, actor=None):
    records = data.get("object_motions")
    if not isinstance(records, list):
        records = []
    record = {{
        "motion": motion,
        "label": OBJECT_MOTION_LABELS.get(motion, motion),
        "objects": list(object_names or []),
        "frame_start": int(frame_start),
        "frame_end": int(frame_end),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }}
    actor_ref = _actor_reference(actor)
    if actor_ref:
        record["actor"] = actor_ref
    records.append(record)
    data["object_motions"] = records[-500:]
    return data


def _apply_object_motion(motion, objects=None):
    scene = bpy.context.scene
    objects = list(objects or []) if objects is not None else _selected_motion_objects()
    if not objects:
        raise RuntimeError("请先选中要走位的人物或物体")
    frame_start, frame_end = _active_frame_range(scene)
    if frame_end <= frame_start:
        frame_end = frame_start + 48
        scene.gpt_director_frame_end = frame_end
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    offset = _object_motion_offset(motion)
    start_locations = {{}}
    scene.frame_set(int(frame_start))
    for obj in objects:
        start_locations[obj.name] = Vector(obj.location)
        obj.keyframe_insert(data_path="location", frame=int(frame_start))
    scene.frame_set(int(frame_end))
    for obj in objects:
        obj.location = start_locations.get(obj.name, Vector(obj.location)) + offset
        obj.keyframe_insert(data_path="location", frame=int(frame_end))
    scene.frame_set(int(frame_start))
    for obj in objects:
        obj.location = start_locations.get(obj.name, Vector(obj.location))
    return objects, frame_start, frame_end


def _set_mannequin_material_color(body, label, color):
    if body is None or body.type != "MESH":
        return None
    if not body.data.materials:
        material = bpy.data.materials.new(label + " 身体材质")
        material.use_nodes = True
        body.data.materials.append(material)
    else:
        material = body.data.materials[0].copy()
        material.name = label + " 身体材质"
        body.data.materials[0] = material
    try:
        material.diffuse_color = color
    except Exception:
        pass
    try:
        material.use_nodes = True
        shader = next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
        if shader is not None:
            shader.inputs["Base Color"].default_value = color
    except Exception:
        pass
    return material


def _move_pose_control(armature, bone_name, offset):
    if armature is None or armature.type != "ARMATURE":
        return
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        return
    matrix = pose_bone.matrix.copy()
    matrix.translation = matrix.translation + Vector(offset)
    pose_bone.matrix = matrix


def _rotate_pose_control(armature, bone_name, rotation):
    if armature is None or armature.type != "ARMATURE":
        return
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        return
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = Euler(rotation, "XYZ")


def _configure_mannequin_pose_display(armature):
    if armature is None or armature.type != "ARMATURE":
        return
    try:
        armature.show_in_front = True
        armature.data.display_type = "BBONE"
        _set_director_label_visibility(armature, False)
    except Exception:
        pass
    group_specs = (
        ("GPT 手脚 IK", "THEME03", ("hand.IK.L", "hand.IK.R", "foot.IK.L", "foot.IK.R")),
        ("GPT 肘膝 Pole", "THEME04", ("Polo.Codo.L", "Polo.Codo.R", "Polo.Rodilla.L", "Polo.Rodilla.R")),
        ("GPT 躯干", "THEME06", ("hips", "chest", "head")),
    )
    for group_name, color_set, bone_names in group_specs:
        try:
            group = armature.pose.bone_groups.get(group_name) or armature.pose.bone_groups.new(name=group_name)
            group.color_set = color_set
        except Exception:
            continue
        for bone_name in bone_names:
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is not None:
                try:
                    pose_bone.bone_group = group
                except Exception:
                    pass


def _add_pose_proxy_control(root, armature, bone_name, label, display_type, size, color):
    if root is None or armature is None or armature.type != "ARMATURE":
        return None
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        return None
    try:
        matrix_world = armature.matrix_world @ pose_bone.matrix
        bpy.ops.object.empty_add(type=display_type, location=matrix_world.translation)
        control = bpy.context.object
        control.name = label
        control.matrix_world = matrix_world
        control.empty_display_size = size
        control["gpt_director_original_display_size"] = float(size or 0.1)
        _set_director_label_visibility(control, False)
        control.show_in_front = True
        control.color = color
        control.hide_render = True
        _link_to_collection(control, "Director Controls")
        _parent_preserve_world(control, root)
        _set_director_tags(
            control,
            str(root.get("gpt_director_asset_id", "")),
            "control",
            "pose_proxy",
        )
        control["gpt_director_control_bone"] = bone_name
        control["gpt_director_control_hint"] = "对象模式直接拖动，驱动骨骼 " + bone_name
        constraint = pose_bone.constraints.get("GPT 导演台可视控制器")
        if constraint is None:
            constraint = pose_bone.constraints.new(type="COPY_TRANSFORMS")
            constraint.name = "GPT 导演台可视控制器"
        constraint.target = control
        constraint.owner_space = "WORLD"
        constraint.target_space = "WORLD"
        return control
    except Exception:
        return None


def _add_mannequin_pose_controls(root, armature, label):
    specs = (
        ("hand.IK.L", label + " 左手 IK 控制器", "CUBE", 0.105, (1.0, 0.50, 0.06, 1.0)),
        ("hand.IK.R", label + " 右手 IK 控制器", "CUBE", 0.105, (1.0, 0.50, 0.06, 1.0)),
        ("foot.IK.L", label + " 左脚 IK 控制器", "CIRCLE", 0.15, (0.18, 0.88, 0.34, 1.0)),
        ("foot.IK.R", label + " 右脚 IK 控制器", "CIRCLE", 0.15, (0.18, 0.88, 0.34, 1.0)),
        ("Polo.Codo.L", label + " 左肘 Pole 控制器", "SPHERE", 0.085, (0.92, 0.20, 0.72, 1.0)),
        ("Polo.Codo.R", label + " 右肘 Pole 控制器", "SPHERE", 0.085, (0.92, 0.20, 0.72, 1.0)),
        ("Polo.Rodilla.L", label + " 左膝 Pole 控制器", "SPHERE", 0.09, (0.30, 0.66, 1.0, 1.0)),
        ("Polo.Rodilla.R", label + " 右膝 Pole 控制器", "SPHERE", 0.09, (0.30, 0.66, 1.0, 1.0)),
    )
    controls = []
    for bone_name, control_label, display_type, size, color in specs:
        control = _add_pose_proxy_control(
            root,
            armature,
            bone_name,
            control_label,
            display_type,
            size,
            color,
        )
        if control is not None:
            controls.append(control)
    return controls


def _apply_rigged_mannequin_pose(armature, pose="standing", look_yaw=0.0):
    if armature is None or armature.type != "ARMATURE":
        return
    for pose_bone in armature.pose.bones:
        try:
            pose_bone.matrix_basis.identity()
        except Exception:
            pass
    bpy.context.view_layer.update()
    if pose == "standing":
        if look_yaw:
            _rotate_pose_control(armature, "head", (0.0, 0.0, math.radians(look_yaw)))
            bpy.context.view_layer.update()
        return
    if pose == "walking":
        _move_pose_control(armature, "hips", (0.0, 0.01, -0.02))
        _move_pose_control(armature, "foot.IK.L", (0.02, -0.30, 0.08))
        _move_pose_control(armature, "foot.IK.R", (-0.02, 0.24, 0.01))
        _move_pose_control(armature, "Polo.Rodilla.L", (0.02, -0.12, 0.04))
        _move_pose_control(armature, "Polo.Rodilla.R", (-0.02, 0.10, 0.02))
        _move_pose_control(armature, "hand.IK.L", (-0.03, 0.19, 0.02))
        _move_pose_control(armature, "hand.IK.R", (0.03, -0.19, 0.02))
        _move_pose_control(armature, "Polo.Codo.L", (-0.08, 0.12, 0.02))
        _move_pose_control(armature, "Polo.Codo.R", (0.08, -0.12, 0.02))
        _rotate_pose_control(armature, "hips", (math.radians(3), 0.0, math.radians(-2)))
        _rotate_pose_control(armature, "chest", (math.radians(-3), 0.0, math.radians(3)))
        _rotate_pose_control(armature, "head", (0.0, 0.0, math.radians(look_yaw)))
        bpy.context.view_layer.update()
        return
    if pose == "running":
        _move_pose_control(armature, "hips", (0.0, 0.05, 0.03))
        _move_pose_control(armature, "foot.IK.L", (0.03, -0.52, 0.22))
        _move_pose_control(armature, "foot.IK.R", (-0.03, 0.40, 0.08))
        _move_pose_control(armature, "Polo.Rodilla.L", (0.03, -0.20, 0.13))
        _move_pose_control(armature, "Polo.Rodilla.R", (-0.03, 0.18, 0.08))
        _move_pose_control(armature, "hand.IK.L", (-0.08, 0.34, 0.16))
        _move_pose_control(armature, "hand.IK.R", (0.08, -0.32, 0.18))
        _move_pose_control(armature, "Polo.Codo.L", (-0.18, 0.20, 0.13))
        _move_pose_control(armature, "Polo.Codo.R", (0.18, -0.19, 0.14))
        _rotate_pose_control(armature, "hips", (math.radians(9), 0.0, math.radians(-3)))
        _rotate_pose_control(armature, "chest", (math.radians(-11), 0.0, math.radians(4)))
        _rotate_pose_control(armature, "head", (math.radians(4), 0.0, math.radians(look_yaw)))
        bpy.context.view_layer.update()
        return
    if pose == "waving":
        _move_pose_control(armature, "hand.IK.R", (0.08, 0.02, 0.60))
        _move_pose_control(armature, "Polo.Codo.R", (0.22, -0.02, 0.34))
        _move_pose_control(armature, "hand.IK.L", (-0.02, -0.03, 0.02))
        _rotate_pose_control(armature, "chest", (0.0, 0.0, math.radians(-3)))
        _rotate_pose_control(armature, "head", (0.0, 0.0, math.radians(look_yaw - 5)))
        bpy.context.view_layer.update()
        return
    _move_pose_control(armature, "hips", (0.0, 0.03, -0.21))
    _move_pose_control(armature, "foot.IK.L", (0.04, -0.40, 0.00))
    _move_pose_control(armature, "foot.IK.R", (-0.04, -0.40, 0.00))
    _move_pose_control(armature, "Polo.Rodilla.L", (0.02, -0.02, 0.04))
    _move_pose_control(armature, "Polo.Rodilla.R", (-0.02, -0.02, 0.04))
    _move_pose_control(armature, "hand.IK.L", (-0.10, -0.16, -0.11))
    _move_pose_control(armature, "hand.IK.R", (0.10, -0.16, -0.11))
    _move_pose_control(armature, "Polo.Codo.L", (-0.24, -0.06, -0.17))
    _move_pose_control(armature, "Polo.Codo.R", (0.24, -0.06, -0.17))
    _rotate_pose_control(armature, "hips", (math.radians(4), 0.0, 0.0))
    _rotate_pose_control(armature, "chest", (math.radians(-3), 0.0, 0.0))
    head_pitch = 2
    if pose == "reclining":
        _move_pose_control(armature, "hips", (0.0, 0.22, 0.01))
        _move_pose_control(armature, "foot.IK.L", (0.02, -0.12, 0.00))
        _move_pose_control(armature, "foot.IK.R", (-0.01, -0.03, 0.00))
        _move_pose_control(armature, "hand.IK.L", (0.34, 0.40, 0.22))
        _move_pose_control(armature, "hand.IK.R", (0.00, 0.03, 0.00))
        _move_pose_control(armature, "Polo.Codo.L", (0.20, 0.25, 0.07))
        _move_pose_control(armature, "Polo.Codo.R", (0.02, 0.02, 0.00))
        _rotate_pose_control(armature, "hips", (math.radians(-9), 0.0, 0.0))
        _rotate_pose_control(armature, "chest", (math.radians(-18), 0.0, 0.0))
        head_pitch = 9
    _rotate_pose_control(
        armature,
        "head",
        (math.radians(head_pitch), 0.0, math.radians(look_yaw)),
    )
    bpy.context.view_layer.update()


def _character_armature_for_asset(asset_id):
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        return None
    for obj in bpy.data.objects:
        try:
            if (
                obj.type == "ARMATURE"
                and str(obj.get("gpt_director_asset_id", "")).strip() == asset_id
                and str(obj.get("gpt_director_asset_kind", "")) == "character"
            ):
                return obj
        except Exception:
            pass
    return None


def _object_is_descendant_of(obj, root):
    current = obj
    while current is not None:
        if current is root:
            return True
        current = getattr(current, "parent", None)
    return False


def _character_armature_for_root(root):
    if root is None:
        return None
    for obj in bpy.data.objects:
        try:
            if obj.type == "ARMATURE" and _object_is_descendant_of(obj, root):
                return obj
        except Exception:
            pass
    return None


def _mannequin_color_key(root):
    if root is None:
        return ""
    stored = str(root.get("gpt_director_character_color", "")).strip().lower()
    if stored in {{"blue", "red"}}:
        return stored
    text = " ".join(
        (
            str(getattr(root, "name", "") or ""),
            str(root.get("gpt_director_asset_id", "") or ""),
            str(root.get("gpt_director_role", "") or ""),
        )
    ).lower()
    if "蓝" in text or "blue" in text or "男角色" in text:
        return "blue"
    if "红" in text or "red" in text or "女角色" in text:
        return "red"
    return ""


def _mannequin_character_roots():
    roots = []
    for obj in bpy.data.objects:
        try:
            if obj.type != "ARMATURE" or str(obj.get("gpt_director_asset_kind", "")) != "character":
                continue
            current = getattr(obj, "parent", None)
            while current is not None:
                if current.type == "EMPTY" and str(current.get("gpt_director_asset_kind", "")) == "character":
                    if _mannequin_color_key(current) and current not in roots:
                        roots.append(current)
                    break
                current = getattr(current, "parent", None)
        except Exception:
            pass
    roots.sort(key=lambda item: str(item.name or ""))
    return roots


def _character_label_for_color(color_key, index):
    prefix = "男角色" if color_key == "blue" else "女角色"
    return prefix + str(int(index))


def _character_asset_id_for_color(color_key, index):
    return "builtin_" + color_key + "_mannequin_" + str(int(index))


def _set_character_instance_identity(root, color_key, index):
    if root is None or color_key not in {{"blue", "red"}}:
        return 0
    index = max(1, int(index))
    label = _character_label_for_color(color_key, index)
    asset_id = _character_asset_id_for_color(color_key, index)
    changed = 0
    descendants = [obj for obj in bpy.data.objects if _object_is_descendant_of(obj, root)]
    for obj in descendants:
        try:
            if str(obj.get("gpt_director_asset_id", "")) != asset_id:
                obj["gpt_director_asset_id"] = asset_id
                changed += 1
        except Exception:
            pass
    for obj in (root, _character_armature_for_root(root)):
        if obj is None:
            continue
        try:
            if str(obj.get("gpt_director_character_label", "")) != label:
                obj["gpt_director_character_label"] = label
                changed += 1
            obj["gpt_director_character_color"] = color_key
            obj["gpt_director_character_index"] = index
        except Exception:
            pass
    try:
        root["gpt_director_asset_kind"] = "character"
        root["gpt_director_role"] = "actor_" + color_key
        root.name = label + " 根控制器"
    except Exception:
        pass
    armature = _character_armature_for_root(root)
    if armature is not None:
        try:
            armature.name = label + " 骨骼控制器"
        except Exception:
            pass
    for obj in descendants:
        try:
            if obj.type == "MESH" and bool(obj.get("gpt_director_recolor_material", "")):
                obj.name = label + " 人偶主体"
                obj["gpt_director_character_label"] = label
                obj["gpt_director_character_color"] = color_key
                obj["gpt_director_character_index"] = index
                break
        except Exception:
            pass
    return changed


def _ensure_independent_mannequin_instances():
    groups = {{"blue": [], "red": []}}
    for root in _mannequin_character_roots():
        color_key = _mannequin_color_key(root)
        if color_key in groups:
            groups[color_key].append(root)
    changed = 0
    for color_key, roots in groups.items():
        roots.sort(key=lambda item: str(item.name or ""))
        for index, root in enumerate(roots, 1):
            changed += _set_character_instance_identity(root, color_key, index)
    try:
        active = getattr(bpy.context, "active_object", None)
        active_root = next((root for root in _mannequin_character_roots() if _object_is_descendant_of(active, root)), None)
        if active_root is not None:
            _remember_active_character(bpy.context, active_root)
    except Exception:
        pass
    return changed


def _next_mannequin_index(color_key):
    _ensure_independent_mannequin_instances()
    indexes = []
    for root in _mannequin_character_roots():
        if _mannequin_color_key(root) != color_key:
            continue
        try:
            indexes.append(int(root.get("gpt_director_character_index", 0) or 0))
        except Exception:
            pass
    return max(indexes or [0]) + 1


def _mannequin_spawn_location(color_key, index):
    offset = max(0, int(index) - 2)
    direction = -1.0 if color_key == "blue" else 1.0
    return (direction * (0.8 + 0.7 * (offset % 3)), -0.75 * (offset // 3), 0.0)


def _character_label_world_location(root):
    armature = _character_armature_for_root(root)
    if armature is not None:
        try:
            head = armature.pose.bones.get("head")
            if head is not None:
                return armature.matrix_world @ head.head + Vector((0.0, 0.0, 0.28))
        except Exception:
            pass
    try:
        return root.matrix_world.translation + Vector((0.0, 0.0, 2.1))
    except Exception:
        return None


def _draw_character_name_labels():
    context = bpy.context
    region = getattr(context, "region", None)
    space = getattr(context, "space_data", None)
    if region is None or space is None or getattr(space, "type", "") != "VIEW_3D":
        return
    region_3d = getattr(space, "region_3d", None)
    if region_3d is None:
        return
    font_id = _character_label_font_id()
    try:
        blf.size(font_id, 15, 72)
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.85)
        blf.shadow_offset(font_id, 1, -1)
    except Exception:
        pass
    for root in _mannequin_character_roots():
        label = str(root.get("gpt_director_character_label", "") or "").strip()
        world_location = _character_label_world_location(root)
        if not label or world_location is None:
            continue
        try:
            point = view3d_utils.location_3d_to_region_2d(region, region_3d, world_location)
            if point is None:
                continue
            width, _height = blf.dimensions(font_id, label)
            color_key = _mannequin_color_key(root)
            color = (0.55, 0.80, 1.0, 1.0) if color_key == "blue" else (1.0, 0.68, 0.72, 1.0)
            blf.color(font_id, *color)
            blf.position(font_id, point.x - width * 0.5, point.y + 4.0, 0.0)
            blf.draw(font_id, label)
        except Exception:
            pass
    try:
        blf.disable(font_id, blf.SHADOW)
    except Exception:
        pass


_CHARACTER_LABEL_HANDLER_KEY = "gpt_director_character_label_handler"
_CHARACTER_LABEL_FONT_KEY = "gpt_director_character_label_font"
_SIMPLE_DRAG_RUNTIME_KEY = "gpt_director_simple_drag_runtime_active"
_SIMPLE_DRAG_TIMER_KEY = "gpt_director_simple_drag_start_timer"
_SIMPLE_DRAG_TIMER_ATTEMPTS_KEY = "gpt_director_simple_drag_start_attempts"
_CHARACTER_LABEL_FONT_PATHS = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)


def _character_label_font_id():
    try:
        cached = bpy.app.driver_namespace.get(_CHARACTER_LABEL_FONT_KEY)
        if isinstance(cached, int) and cached >= 0:
            return cached
    except Exception:
        pass
    font_id = 0
    for path in _CHARACTER_LABEL_FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            loaded = int(blf.load(path))
            if loaded >= 0:
                font_id = loaded
                break
        except Exception:
            pass
    try:
        bpy.app.driver_namespace[_CHARACTER_LABEL_FONT_KEY] = font_id
    except Exception:
        pass
    return font_id


def _unregister_character_label_draw_handler():
    try:
        handle = bpy.app.driver_namespace.pop(_CHARACTER_LABEL_HANDLER_KEY, None)
    except Exception:
        handle = None
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except Exception:
            pass


def _register_character_label_draw_handler():
    if getattr(bpy.app, "background", False):
        return
    _unregister_character_label_draw_handler()
    try:
        handle = bpy.types.SpaceView3D.draw_handler_add(_draw_character_name_labels, (), "WINDOW", "POST_PIXEL")
        bpy.app.driver_namespace[_CHARACTER_LABEL_HANDLER_KEY] = handle
    except Exception:
        pass
    for screen in _director_view3d_screens():
        for area in getattr(screen, "areas", []):
            if getattr(area, "type", "") == "VIEW_3D":
                try:
                    area.tag_redraw()
                except Exception:
                    pass


def _set_simple_drag_runtime_active(active):
    try:
        if active:
            bpy.app.driver_namespace[_SIMPLE_DRAG_RUNTIME_KEY] = True
        else:
            bpy.app.driver_namespace.pop(_SIMPLE_DRAG_RUNTIME_KEY, None)
    except Exception:
        pass


def _simple_drag_runtime_active():
    try:
        return bool(bpy.app.driver_namespace.get(_SIMPLE_DRAG_RUNTIME_KEY, False))
    except Exception:
        return False


def _start_simple_drag_mode_after_load():
    try:
        attempts = int(bpy.app.driver_namespace.get(_SIMPLE_DRAG_TIMER_ATTEMPTS_KEY, 0) or 0) + 1
        bpy.app.driver_namespace[_SIMPLE_DRAG_TIMER_ATTEMPTS_KEY] = attempts
    except Exception:
        attempts = 1
    if _simple_drag_runtime_active():
        return None
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", []):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", []):
            if getattr(area, "type", "") != "VIEW_3D":
                continue
            region = next((item for item in getattr(area, "regions", []) if getattr(item, "type", "") == "WINDOW"), None)
            space = next((item for item in getattr(area, "spaces", []) if getattr(item, "type", "") == "VIEW_3D"), None)
            if region is None or space is None:
                continue
            override = bpy.context.copy()
            override.update({{
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
                "space_data": space,
                "scene": getattr(window, "scene", bpy.context.scene),
            }})
            try:
                result = bpy.ops.gpt_director.simple_drag_mode(override, "INVOKE_DEFAULT")
                if "RUNNING_MODAL" in result:
                    return None
            except Exception:
                pass
    if attempts < 20:
        return 0.25
    try:
        bpy.context.scene.gpt_director_simple_drag_enabled = False
    except Exception:
        pass
    return None


def _cancel_simple_drag_mode_start():
    try:
        timer = bpy.app.driver_namespace.pop(_SIMPLE_DRAG_TIMER_KEY, None)
        bpy.app.driver_namespace.pop(_SIMPLE_DRAG_TIMER_ATTEMPTS_KEY, None)
        if timer is not None and bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    except Exception:
        pass


def _schedule_simple_drag_mode_start():
    _cancel_simple_drag_mode_start()
    _set_simple_drag_runtime_active(False)
    try:
        bpy.context.scene.gpt_director_simple_drag_enabled = False
    except Exception:
        pass


@persistent
def _director_load_post(_loaded_file):
    try:
        _remove_legacy_depth_scene_data()
    except Exception:
        pass
    try:
        _ensure_independent_mannequin_instances()
    except Exception:
        pass
    try:
        _register_character_label_draw_handler()
    except Exception:
        pass
    try:
        _set_director_simple_view(bpy.context, True)
    except Exception:
        pass
    _cancel_simple_drag_mode_start()
    _set_simple_drag_runtime_active(False)
    try:
        bpy.context.scene.gpt_director_simple_drag_enabled = False
    except Exception:
        pass


def _unregister_director_load_post_handler():
    for handler in list(getattr(bpy.app.handlers, "load_post", [])):
        if handler is _director_load_post or getattr(handler, "__name__", "") == "_director_load_post":
            try:
                bpy.app.handlers.load_post.remove(handler)
            except Exception:
                pass


def _register_director_load_post_handler():
    _unregister_director_load_post_handler()
    try:
        bpy.app.handlers.load_post.append(_director_load_post)
    except Exception:
        pass


def _remember_active_character(context, root):
    if root is None or str(root.get("gpt_director_asset_kind", "")) != "character":
        return
    asset_id = str(root.get("gpt_director_asset_id", "")).strip()
    armature = _character_armature_for_root(root)
    label = str(root.name or asset_id).replace(" 根控制器", "")
    if armature is not None:
        label = str(armature.name or label).replace(" 骨骼控制器", "")
    try:
        context.scene.gpt_director_active_character_asset_id = asset_id
        context.scene.gpt_director_active_character_name = label
        if armature is not None:
            context.scene.gpt_director_active_pose = str(armature.get("gpt_director_current_pose", "standing") or "standing")
    except Exception:
        pass


def _active_character_armature(context):
    active = getattr(context, "active_object", None)
    root = _director_drag_root_for_object(active)
    if root is not None and str(root.get("gpt_director_asset_kind", "")) == "character":
        _remember_active_character(context, root)
        armature = _character_armature_for_root(root)
        if armature is not None:
            return armature
    asset_id = str(getattr(context.scene, "gpt_director_active_character_asset_id", "") or "").strip()
    if asset_id:
        matching_roots = [
            root
            for root in _mannequin_character_roots()
            if str(root.get("gpt_director_asset_id", "")).strip() == asset_id
        ]
        if len(matching_roots) == 1:
            armature = _character_armature_for_root(matching_roots[0])
            if armature is not None:
                return armature
    armatures = [
        obj
        for obj in bpy.data.objects
        if obj.type == "ARMATURE" and str(obj.get("gpt_director_asset_kind", "")) == "character"
    ]
    if len(armatures) == 1:
        return armatures[0]
    return None


def _apply_mannequin_pose_preset(context, armature, pose):
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError("请先在画面中点一下要调整姿势的人偶")
    root = _director_drag_root_for_object(armature)
    if root is None:
        raise RuntimeError("当前人物缺少独立根控制器，请重新打开导演台自动修复")
    proxies = [
        obj
        for obj in bpy.data.objects
        if _object_is_descendant_of(obj, root)
        and str(obj.get("gpt_director_role", "")) == "pose_proxy"
    ]
    muted_constraints = []
    for control in proxies:
        bone_name = str(control.get("gpt_director_control_bone", "")).strip()
        pose_bone = armature.pose.bones.get(bone_name) if bone_name else None
        constraint = pose_bone.constraints.get("GPT 导演台可视控制器") if pose_bone is not None else None
        if constraint is not None:
            muted_constraints.append(constraint)
            constraint.mute = True
    try:
        _apply_rigged_mannequin_pose(armature, pose)
        context.view_layer.update()
        for control in proxies:
            bone_name = str(control.get("gpt_director_control_bone", "")).strip()
            pose_bone = armature.pose.bones.get(bone_name) if bone_name else None
            if pose_bone is not None:
                control.matrix_world = armature.matrix_world @ pose_bone.matrix
    finally:
        for constraint in muted_constraints:
            constraint.mute = False
    armature["gpt_director_current_pose"] = str(pose or "standing")
    context.scene.gpt_director_active_pose = str(pose or "standing")
    _remember_active_character(context, root)
    _set_director_simple_view(context, True)
    context.view_layer.update()
    return armature


def _add_rigged_mannequin(label, color, location=(0, 0, 0), collection="Director Characters", pose="standing", asset_id="", role="actor", look_yaw=0.0, character_color=""):
    asset_id = asset_id or _safe_id(label, "builtin_actor")
    if not MANNEQUIN_TEMPLATE_PATH or not os.path.exists(MANNEQUIN_TEMPLATE_PATH):
        raise RuntimeError("内置骨骼人偶资源不存在，请重新打开导演台工程以修复资产：" + str(MANNEQUIN_TEMPLATE_PATH))
    try:
        with bpy.data.libraries.load(MANNEQUIN_TEMPLATE_PATH, link=False) as (data_from, data_to):
            data_to.objects = list(data_from.objects)
    except Exception as exc:
        raise RuntimeError("载入内置骨骼人偶失败：" + str(exc))
    imported = [obj for obj in data_to.objects if obj is not None]
    armature = next((obj for obj in imported if obj.type == "ARMATURE"), None)
    body = next(
        (
            obj
            for obj in imported
            if obj.type == "MESH"
            and (
                bool(obj.get("gpt_director_recolor_material", ""))
                or str(obj.name).startswith("Director Mannequin Body")
            )
        ),
        None,
    )
    if armature is None or body is None:
        for obj in imported:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
        raise RuntimeError("内置骨骼人偶模板缺少骨骼或主体网格")

    rig_ui_objects = [
        obj
        for obj in imported
        if obj.type == "MESH" and obj is not body and obj.parent is armature and bool(obj.hide_render)
    ]
    imported = [obj for obj in imported if obj not in rig_ui_objects]
    for obj in rig_ui_objects:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass

    custom_shapes = set(
        pose_bone.custom_shape
        for pose_bone in armature.pose.bones
        if pose_bone.custom_shape is not None
    )
    widgets_collection = _ensure_collection("Director Mannequin Widgets")
    widgets_collection.hide_render = True
    widgets_collection.hide_viewport = True
    for obj in imported:
        _set_director_tags(obj, asset_id, "character", role)
        original_name = str(obj.name)
        obj.name = label + " " + original_name
        if obj in custom_shapes:
            _link_to_collection(obj, "Director Mannequin Widgets")
            obj.hide_render = True
        elif obj is armature or obj is body:
            _link_to_collection(obj, collection)
        else:
            _link_to_collection(obj, "Director Controls")
            obj.hide_render = True

    armature.name = label + " 骨骼控制器"
    body.name = label + " 人偶主体"
    armature.show_in_front = True
    armature["gpt_director_asset_source"] = "BlendSwap"
    armature["gpt_director_asset_source_url"] = "https://blendswap.com/blend/13034"
    armature["gpt_director_asset_author"] = "jgilhutton / Juan Ignacio"
    armature["gpt_director_asset_license"] = "CC-BY"
    armature["gpt_director_attribution_path"] = MANNEQUIN_ATTRIBUTION_PATH
    armature["gpt_director_ik_controls"] = "hand.IK.L,hand.IK.R,foot.IK.L,foot.IK.R"
    armature["gpt_director_pole_controls"] = "Polo.Codo.L,Polo.Codo.R,Polo.Rodilla.L,Polo.Rodilla.R"
    armature["gpt_director_control_mode"] = "对象模式拖动彩色代理控制器；Pose 模式可使用原始自定义骨骼控件"
    _configure_mannequin_pose_display(armature)
    _set_mannequin_material_color(body, label, color)
    _apply_rigged_mannequin_pose(armature, pose, look_yaw)
    armature["gpt_director_current_pose"] = str(pose or "standing")

    root = _add_empty_control(label + " 根控制器", (0, 0, 0), asset_id, "character", role)
    _parent_preserve_world(armature, root)
    root.location = Vector(location)
    pose_controls = _add_mannequin_pose_controls(root, armature, label)
    ring = _add_control_ring(root, label + " 视口控制圈", radius=0.55)
    controls = [root, armature] + pose_controls
    if ring is not None:
        controls.append(ring)
    color_key = str(character_color or "").strip().lower() or _mannequin_color_key(root)
    if color_key in {{"blue", "red"}}:
        match = re.search(r"(\d+)$", str(asset_id or label))
        character_index = int(match.group(1)) if match else 1
        _set_character_instance_identity(root, color_key, character_index)
    _set_director_simple_view(None, True)
    _select_roots([root])
    objects = [root] + imported + pose_controls
    if ring is not None:
        objects.append(ring)
    return dict(root=root, armature=armature, body=body, objects=objects, controls=controls)


def _add_bundled_furniture_asset(kind, label, location, asset_id, collection="Director Props"):
    collection_name = (
        FURNITURE_SOFA_COLLECTION_NAME
        if kind == "sofa"
        else FURNITURE_TABLE_COLLECTION_NAME
    )
    if not FURNITURE_TEMPLATE_PATH or not os.path.exists(FURNITURE_TEMPLATE_PATH):
        raise RuntimeError(
            "内置现代家具资源不存在，请重新打开导演台工程以修复资产："
            + str(FURNITURE_TEMPLATE_PATH)
        )
    try:
        with bpy.data.libraries.load(FURNITURE_TEMPLATE_PATH, link=False) as (data_from, data_to):
            if collection_name not in data_from.collections:
                raise RuntimeError("家具包缺少集合：" + collection_name)
            data_to.collections = [collection_name]
    except Exception as exc:
        raise RuntimeError("载入内置现代家具失败：" + str(exc))

    imported_collection = data_to.collections[0]
    if imported_collection is None:
        raise RuntimeError("载入家具集合失败：" + collection_name)
    imported = [obj for obj in imported_collection.all_objects if obj is not None]
    root = next(
        (
            obj
            for obj in imported
            if bool(obj.get("gpt_director_asset_template_root", False))
            and str(obj.get("gpt_director_furniture_kind", "")) == kind
        ),
        None,
    )
    if root is None:
        for obj in imported:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass
        try:
            bpy.data.collections.remove(imported_collection)
        except Exception:
            pass
        raise RuntimeError("家具模板缺少根控制器：" + kind)

    role = "sofa" if kind == "sofa" else "table"
    for obj in imported:
        original_name = str(obj.name)
        obj.name = label + " " + original_name
        _set_director_tags(obj, asset_id, "prop", role)
        if obj is root:
            _link_to_collection(obj, "Director Controls")
        else:
            _link_to_collection(obj, collection)
    try:
        bpy.data.collections.remove(imported_collection)
    except Exception:
        pass

    root.name = label + " 根控制器"
    root.location = Vector(location)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 0.45
    _set_director_label_visibility(root, False)
    root.hide_render = True
    root.show_in_front = True
    root.color = (1.0, 0.72, 0.12, 1.0)
    root["gpt_director_attribution_path"] = FURNITURE_ATTRIBUTION_PATH
    root["gpt_director_control_hint"] = "拖动此根控制器可整体移动、旋转或缩放专业家具资产"

    ring_radius = 1.08 if kind == "sofa" else 0.68
    ring = _add_control_ring(root, label + " 控制圈", radius=ring_radius)
    objects = list(imported)
    if ring is not None:
        objects.append(ring)
    _select_roots([root])
    return dict(root=root, objects=objects)


def _add_sofa_unit(label, location=(0, 0, 0), asset_id="", collection="Director Props"):
    asset_id = asset_id or _safe_id(label, "builtin_sofa")
    return _add_bundled_furniture_asset(
        "sofa",
        label,
        location,
        asset_id,
        collection=collection,
    )


def _add_round_table_asset(label="圆桌", location=(0, 0, 0), asset_id="builtin_round_table", collection="Director Props"):
    return _add_bundled_furniture_asset(
        "table",
        label,
        location,
        asset_id,
        collection=collection,
    )


def _seed_director_metadata_for_lounge(left_actor, right_actor, left_sofa, right_sofa, table):
    data = _load_meta()
    if not isinstance(data.get("builtin_asset_pack"), list):
        data["builtin_asset_pack"] = BUILTIN_DIRECTOR_ASSET_PACK
    if not isinstance(data.get("open_asset_source_profiles"), list):
        data["open_asset_source_profiles"] = OPEN_ASSET_SOURCE_PROFILES
    if not isinstance(data.get("material_applications"), list):
        data["material_applications"] = []
    if not isinstance(data.get("action_clips"), list):
        data["action_clips"] = []
    if not isinstance(data.get("retarget_profiles"), list):
        data["retarget_profiles"] = []
    if not isinstance(data.get("retarget_applications"), list):
        data["retarget_applications"] = []
    data["director_capabilities"] = dict(
        version=2,
        mode="real_blender_director_stage",
        asset_formats=["blend", "glb", "gltf", "fbx", "obj", "bvh", "stl", "ply", "abc", "usd", "usdz", "png", "jpg", "jpeg", "tif", "tiff", "exr", "hdr"],
        asset_kinds=["character", "prop", "scene", "action", "model", "material", "texture", "hdri"],
        control_model=["root_empty", "viewport_control_ring", "armature", "ik_fk", "hand_foot_controls", "actor_slots", "object_templates", "camera_templates", "texture_materials", "action_clips", "retarget_profiles"],
        built_in_scene_operator="gpt_director.add_dialogue_lounge_scene",
        open_ecosystem=[item.get("id") for item in OPEN_ASSET_SOURCE_PROFILES if isinstance(item, dict)],
    )
    _record_builtin_asset(
        data,
        "builtin_blue_mannequin",
        "蓝色 IK/FK 骨骼人偶",
        "character",
        right_actor.get("objects") if isinstance(right_actor, dict) else [],
        ["Director Characters", "Director Controls", "Director Mannequin Widgets"],
        "CC-BY 骨骼人偶，可拖动根控制器整体走位，也可拖动手脚 IK 控制器摆姿势。",
    )
    _record_builtin_asset(
        data,
        "builtin_red_mannequin",
        "红色 IK/FK 骨骼人偶",
        "character",
        left_actor.get("objects") if isinstance(left_actor, dict) else [],
        ["Director Characters", "Director Controls", "Director Mannequin Widgets"],
        "CC-BY 骨骼人偶，适合对手戏、正反打、坐姿和动作预演。",
    )
    prop_objects = []
    for bundle in (left_sofa, right_sofa, table):
        if isinstance(bundle, dict):
            prop_objects.extend(bundle.get("objects") or [])
    _record_builtin_asset(
        data,
        "builtin_sofa_table_props",
        "沙发茶几与圆桌道具",
        "prop",
        prop_objects,
        ["Director Props", "Director Controls"],
        "双人对话常用可拖动道具组。",
    )
    _record_builtin_actor(
        data,
        "builtin_actor_blue",
        "蓝色人偶",
        "主角位",
        right_actor.get("objects") if isinstance(right_actor, dict) else [],
        "内置可控演员位，可替换为外部开源角色模型。",
    )
    _record_builtin_actor(
        data,
        "builtin_actor_red",
        "红色人偶",
        "对手位",
        left_actor.get("objects") if isinstance(left_actor, dict) else [],
        "内置可控演员位，可替换为外部开源角色模型。",
    )
    scene = bpy.context.scene
    scene.gpt_director_preset_name = "双人沙发圆桌导演台"
    scene.gpt_director_preset_note = "图片参考风格：两名可控人偶、专业软包沙发、几何茶几、深色网格地面、可调机位。"
    preset = _scene_preset_from_current_scene(
        scene,
        "builtin_dialogue_lounge_scene",
        scene.gpt_director_preset_name,
        scene.gpt_director_preset_note,
    )
    _upsert_scene_preset(data, preset)
    roots = []
    for bundle in (left_actor, right_actor, left_sofa, right_sofa, table):
        if isinstance(bundle, dict) and bundle.get("root") is not None:
            roots.append(bundle.get("root"))
    object_template = dict(
        id="builtin_dialogue_lounge_blocking",
        name="双人沙发圆桌站位",
        note="主角坐左侧、对手位靠右侧，圆桌居中；拖动根控制器可自由调整。",
        objects=[_object_snapshot(obj) for obj in roots],
        frame=int(scene.frame_current),
        saved_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    _upsert_object_template(data, object_template)
    scene.gpt_director_shot_name = "双人对话建立镜头"
    scene.gpt_director_shot_note = "一键生成的 3D 导演台建立镜头，可继续保存正反打。"
    shot = _shot_from_current_scene(scene, "builtin_dialogue_lounge_establishing", scene.gpt_director_shot_name, scene.gpt_director_shot_note, data)
    _upsert_shot(data, shot)
    _save_meta(data)
    return data


def _build_dialogue_lounge_scene():
    _clear_director_workbench()
    try:
        bpy.ops.gpt_director.init_scene()
    except Exception:
        pass
    left_sofa = _add_sofa_unit("左侧沙发", (-1.15, 0.05, 0), "builtin_left_sofa")
    right_sofa = _add_sofa_unit("右侧沙发", (1.15, 0.05, 0), "builtin_right_sofa")
    table = _add_round_table_asset("中心茶几", (0, -0.92, 0), "builtin_round_table")
    left_actor = _add_rigged_mannequin(
        "女角色1",
        (0.78, 0.18, 0.12, 1),
        location=(-1.15, -0.28, 0),
        pose="seated",
        asset_id="builtin_red_mannequin_1",
        role="actor_red",
        look_yaw=12,
        character_color="red",
    )
    right_actor = _add_rigged_mannequin(
        "男角色1",
        (0.08, 0.38, 0.84, 1),
        location=(1.15, -0.26, 0),
        pose="seated",
        asset_id="builtin_blue_mannequin_1",
        role="actor_blue",
        look_yaw=-12,
        character_color="blue",
    )
    _add_three_point_lighting()
    camera = bpy.context.scene.camera
    if camera is None or camera.type != "CAMERA":
        camera = _add_camera()
    camera.location = (3.4, -4.2, 2.55)
    camera.data.lens = 32
    _look_at(camera, (0, -0.05, 0.95))
    bpy.context.scene.camera = camera
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 96
    try:
        bpy.context.scene.gpt_director_frame_start = 1
        bpy.context.scene.gpt_director_frame_end = 96
        bpy.context.scene.gpt_director_scene_location = "导演台客厅"
        bpy.context.scene.gpt_director_scene_environment = "interior"
        bpy.context.scene.gpt_director_scene_time = "day"
        bpy.context.scene.gpt_director_render_output = "still"
    except Exception:
        pass
    _seed_director_metadata_for_lounge(left_actor, right_actor, left_sofa, right_sofa, table)
    _set_director_simple_view(bpy.context, True)
    _select_roots([left_actor.get("root"), right_actor.get("root"), table.get("root")])
    return dict(left_actor=left_actor, right_actor=right_actor, left_sofa=left_sofa, right_sofa=right_sofa, table=table)


class GPT_OT_director_init_scene(bpy.types.Operator):
    bl_idname = "gpt_director.init_scene"
    bl_label = "初始化导演台场景"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        _clear_collection("Director Base")
        floor = _mat("导演台地面", (0.24, 0.26, 0.30, 1))
        wall = _mat("导演台背景", (0.14, 0.16, 0.20, 1))
        line = _mat("导演台网格线", (0.36, 0.40, 0.47, 1))
        _cube("地面", (0, 0, -0.03), (5.0, 5.0, 0.03), floor)
        _cube("后墙", (0, 2.5, 1.6), (5.0, 0.05, 1.6), wall)
        for idx in range(-5, 6):
            _cube("横向网格 " + str(idx), (0, idx * 0.5, 0.01), (5.0, 0.008, 0.008), line)
            _cube("纵向网格 " + str(idx), (idx * 0.5, 0, 0.012), (0.008, 5.0, 0.008), line)
        if not bpy.context.scene.camera:
            _add_camera()
        if not bpy.data.objects.get("Director Key Light"):
            bpy.ops.object.light_add(type="AREA", location=(0, -3.5, 4.5))
            light = bpy.context.object
            light.name = "Director Key Light"
            light.data.energy = 450
            light.data.size = 4
            _link_to_collection(light, "Director Lights")
        context.scene.render.resolution_x = 1280
        context.scene.render.resolution_y = 720
        try:
            context.scene.render.engine = "CYCLES"
            context.scene.cycles.device = "CPU"
            context.scene.cycles.samples = 32
        except Exception:
            context.scene.render.engine = "BLENDER_EEVEE"
        self.report({{"INFO"}}, "导演台基础场景已创建")
        return {{"FINISHED"}}


class GPT_OT_director_add_dialogue_lounge_scene(bpy.types.Operator):
    bl_idname = "gpt_director.add_dialogue_lounge_scene"
    bl_label = "一键影视双人对话场"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        _build_dialogue_lounge_scene()
        self.report({{"INFO"}}, "影视双人对话场已生成：可拖动人偶、专业沙发、几何茶几和机位继续调整")
        return {{"FINISHED"}}


class GPT_OT_director_add_room_set(bpy.types.Operator):
    bl_idname = "gpt_director.add_room_set"
    bl_label = "搭建房间"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        floor = _mat("房间木地板", (0.42, 0.35, 0.28, 1))
        wall = _mat("房间浅灰墙", (0.62, 0.64, 0.66, 1))
        trim = _mat("房间深色边线", (0.16, 0.16, 0.18, 1))
        _cube("房间地板", (0, 0, -0.025), (4.2, 3.2, 0.025), floor, "Director Scenes")
        _cube("房间后墙", (0, 1.6, 1.45), (4.2, 0.04, 1.45), wall, "Director Scenes")
        _cube("房间左墙", (-2.1, 0, 1.45), (0.04, 3.2, 1.45), wall, "Director Scenes")
        _cube("房间踢脚线", (0, 1.55, 0.12), (4.2, 0.045, 0.05), trim, "Director Scenes")
        _add_three_point_lighting()
        _set_camera_preset("medium")
        return {{"FINISHED"}}


class GPT_OT_director_add_street_set(bpy.types.Operator):
    bl_idname = "gpt_director.add_street_set"
    bl_label = "搭建街道"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        road = _mat("街道路面", (0.12, 0.13, 0.14, 1))
        curb = _mat("街道边石", (0.42, 0.42, 0.40, 1))
        line = _mat("街道标线", (0.95, 0.82, 0.18, 1))
        building = _mat("街道建筑灰", (0.26, 0.28, 0.32, 1))
        glass = _mat("街道窗户暗蓝", (0.08, 0.14, 0.22, 1))
        _cube("街道路面", (0, 0, -0.02), (5.5, 4.0, 0.02), road, "Director Scenes")
        _cube("左人行道", (-2.2, 0, 0.06), (0.65, 4.0, 0.06), curb, "Director Scenes")
        _cube("右人行道", (2.2, 0, 0.06), (0.65, 4.0, 0.06), curb, "Director Scenes")
        _cube("街道中线", (0, 0, 0.02), (0.035, 3.5, 0.01), line, "Director Scenes")
        for idx, x in enumerate((-2.7, 2.7)):
            _cube("街道建筑 " + str(idx + 1), (x, 0.8, 1.35), (0.42, 1.4, 1.35), building, "Director Scenes")
            _cube("街道窗户 " + str(idx + 1), (x, 0.0, 1.45), (0.43, 0.035, 0.32), glass, "Director Scenes")
        _add_three_point_lighting()
        _set_camera_preset("wide")
        return {{"FINISHED"}}


class GPT_OT_director_add_stage_set(bpy.types.Operator):
    bl_idname = "gpt_director.add_stage_set"
    bl_label = "搭建舞台"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        stage = _mat("舞台地面", (0.10, 0.10, 0.12, 1))
        back = _mat("舞台背景", (0.02, 0.03, 0.05, 1))
        mark = _mat("舞台站位标记", (0.88, 0.14, 0.12, 1))
        _cube("舞台台面", (0, 0, 0.08), (4.6, 2.8, 0.10), stage, "Director Scenes")
        _cube("舞台背景墙", (0, 1.45, 1.6), (4.6, 0.05, 1.6), back, "Director Scenes")
        _cylinder("舞台中心标记", (0, -0.2, 0.2), 0.16, 0.02, mark, rotation=(math.radians(90), 0, 0), collection="Director Scenes")
        _add_three_point_lighting()
        _set_camera_preset("medium")
        return {{"FINISHED"}}


class GPT_OT_director_add_blue_mannequin(bpy.types.Operator):
    bl_idname = "gpt_director.add_blue_mannequin"
    bl_label = "添加蓝色人偶"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        index = _next_mannequin_index("blue")
        label = _character_label_for_color("blue", index)
        asset_id = _character_asset_id_for_color("blue", index)
        bundle = _add_rigged_mannequin(
            label,
            (0.08, 0.38, 0.84, 1),
            location=_mannequin_spawn_location("blue", index),
            asset_id=asset_id,
            role="actor_blue",
            character_color="blue",
        )
        data = _load_meta()
        _record_builtin_asset(data, asset_id, label + " / 蓝色 IK/FK 骨骼人偶", "character", bundle.get("objects") or [], ["Director Characters", "Director Controls", "Director Mannequin Widgets"])
        _record_builtin_actor(data, "builtin_actor_blue_" + str(index), label, "男角色", bundle.get("objects") or [])
        _save_meta(data)
        _remember_active_character(context, bundle.get("root"))
        self.report({{"INFO"}}, "已添加并选中 " + label)
        return {{"FINISHED"}}


class GPT_OT_director_add_red_mannequin(bpy.types.Operator):
    bl_idname = "gpt_director.add_red_mannequin"
    bl_label = "添加红色人偶"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        index = _next_mannequin_index("red")
        label = _character_label_for_color("red", index)
        asset_id = _character_asset_id_for_color("red", index)
        bundle = _add_rigged_mannequin(
            label,
            (0.78, 0.18, 0.12, 1),
            location=_mannequin_spawn_location("red", index),
            asset_id=asset_id,
            role="actor_red",
            character_color="red",
        )
        data = _load_meta()
        _record_builtin_asset(data, asset_id, label + " / 红色 IK/FK 骨骼人偶", "character", bundle.get("objects") or [], ["Director Characters", "Director Controls", "Director Mannequin Widgets"])
        _record_builtin_actor(data, "builtin_actor_red_" + str(index), label, "女角色", bundle.get("objects") or [])
        _save_meta(data)
        _remember_active_character(context, bundle.get("root"))
        self.report({{"INFO"}}, "已添加并选中 " + label)
        return {{"FINISHED"}}


class GPT_OT_director_select_mannequin_controls(bpy.types.Operator):
    bl_idname = "gpt_director.select_mannequin_controls"
    bl_label = "选择人偶可视控制器"
    bl_options = {{"REGISTER"}}

    asset_id: StringProperty(default="")

    def execute(self, context):
        controls = [
            obj
            for obj in bpy.data.objects
            if str(obj.get("gpt_director_asset_id", "")) == str(self.asset_id or "")
            and str(obj.get("gpt_director_role", "")) == "pose_proxy"
        ]
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except Exception:
            pass
        for control in controls:
            try:
                control.hide_set(False)
                control.hide_select = False
                control.select_set(True)
            except Exception:
                pass
        if not controls:
            self.report({{"WARNING"}}, "未找到该人偶的可视控制器，请先添加人偶或生成双人场")
            return {{"CANCELLED"}}
        context.view_layer.objects.active = controls[0]
        self.report({{"INFO"}}, "已选择 " + str(len(controls)) + " 个彩色控制器，可在对象模式直接拖动")
        return {{"FINISHED"}}


class GPT_OT_director_toggle_control_labels(bpy.types.Operator):
    bl_idname = "gpt_director.toggle_control_labels"
    bl_label = "切换导演台文字标签"
    bl_options = {{"REGISTER", "UNDO"}}

    visible: BoolProperty(default=False)

    def execute(self, context):
        changed = _set_all_director_label_visibility(bool(self.visible))
        if self.visible:
            self.report({{"INFO"}}, "已显示 " + str(changed) + " 个导演台对象/骨骼名称")
        else:
            self.report({{"INFO"}}, "已隐藏 " + str(changed) + " 个导演台对象/骨骼名称，控制器仍可选择拖动")
        return {{"FINISHED"}}


class GPT_OT_director_toggle_clean_view(bpy.types.Operator):
    bl_idname = "gpt_director.toggle_clean_view"
    bl_label = "切换导演台清爽视图"
    bl_options = {{"REGISTER", "UNDO"}}

    enabled: BoolProperty(default=True)

    def execute(self, context):
        changed = _set_director_clean_view(context, bool(self.enabled))
        if self.enabled:
            self.report({{"INFO"}}, "已进入清爽视图：隐藏骨架线、大控制圈和关系虚线，保留可拖动控制器")
        else:
            self.report({{"INFO"}}, "已显示精调线框：" + str(changed) + " 个导演台辅助对象可见")
        return {{"FINISHED"}}


class GPT_OT_director_set_simple_view(bpy.types.Operator):
    bl_idname = "gpt_director.set_simple_view"
    bl_label = "隐藏所有控制线"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        changed = _set_director_simple_view(context, True)
        self.report({{"INFO"}}, "已隐藏骨骼、IK、名称和关系线：" + str(changed) + " 个辅助对象")
        return {{"FINISHED"}}


class GPT_OT_director_apply_quick_pose(bpy.types.Operator):
    bl_idname = "gpt_director.apply_quick_pose"
    bl_label = "应用人物姿势"
    bl_options = {{"REGISTER", "UNDO"}}

    pose: StringProperty(default="standing")

    def execute(self, context):
        armature = _active_character_armature(context)
        if armature is None:
            self.report({{"WARNING"}}, "请先在画面中点一下要调整姿势的人偶")
            return {{"CANCELLED"}}
        labels = {{
            "standing": "站立",
            "seated": "坐下",
            "walking": "行走",
            "running": "跑步",
            "waving": "招手",
            "reclining": "斜躺",
        }}
        try:
            _apply_mannequin_pose_preset(context, armature, self.pose)
        except Exception as exc:
            self.report({{"ERROR"}}, "姿势应用失败：" + str(exc))
            return {{"CANCELLED"}}
        self.report({{"INFO"}}, "已为 " + armature.name.replace(" 骨骼控制器", "") + " 应用姿势：" + labels.get(self.pose, self.pose))
        return {{"FINISHED"}}


class GPT_OT_director_simple_drag_mode(bpy.types.Operator):
    bl_idname = "gpt_director.simple_drag_mode"
    bl_label = "极简拖动模式"
    bl_options = {{"REGISTER", "UNDO"}}

    _drag_root = None
    _drag_plane_z = 0.0
    _drag_offset = None
    _dragging = False
    _drag_operation = "MOVE"
    _rotate_start_mouse_x = 0
    _rotate_start_z = 0.0
    _view_rotate_start_mouse_x = 0
    _view_rotate_start_mouse_y = 0
    _view_rotate_start = None
    _view_pan_start_mouse_x = 0
    _view_pan_start_mouse_y = 0
    _view_pan_start_location = None
    _view_pan_start_rotation = None
    _view_pan_scale = 0.01

    def invoke(self, context, event):
        if _simple_drag_runtime_active():
            self.report({{"INFO"}}, "鼠标拖动已经开启")
            return {{"CANCELLED"}}
        region, space = _view3d_window_region_and_space(context)
        if region is None or space is None:
            self.report({{"WARNING"}}, "请在 Blender 3D 视图里启动极简拖动模式")
            return {{"CANCELLED"}}
        _set_director_simple_view(context, True)
        self._drag_root = None
        self._drag_offset = None
        self._dragging = False
        self._drag_operation = "MOVE"
        self._rotate_start_mouse_x = 0
        self._rotate_start_z = 0.0
        self._view_rotate_start_mouse_x = 0
        self._view_rotate_start_mouse_y = 0
        self._view_rotate_start = None
        self._view_pan_start_mouse_x = 0
        self._view_pan_start_mouse_y = 0
        self._view_pan_start_location = None
        self._view_pan_start_rotation = None
        self._view_pan_scale = 0.01
        _set_simple_drag_runtime_active(True)
        context.scene.gpt_director_simple_drag_enabled = True
        context.window_manager.modal_handler_add(self)
        self.report({{"INFO"}}, "模型左拖移动；Shift+左拖旋转；空白左拖旋转视角；右键拖动平移视角")
        return {{"RUNNING_MODAL"}}

    def modal(self, context, event):
        if event.type == "ESC":
            self._drag_root = None
            self._dragging = False
            self._drag_operation = "MOVE"
            self._view_pan_start_location = None
            _set_simple_drag_runtime_active(False)
            context.scene.gpt_director_simple_drag_enabled = False
            self.report({{"INFO"}}, "已退出位置拖放")
            return {{"CANCELLED"}}
        event_in_view = _event_in_view3d_window(context, event)
        if event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value == "PRESS" and not event_in_view:
            return {{"PASS_THROUGH"}}
        if event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value == "RELEASE" and not self._dragging:
            return {{"PASS_THROUGH"}}
        if event.type == "MOUSEMOVE" and not self._dragging and not event_in_view:
            return {{"PASS_THROUGH"}}
        if event.type == "RIGHTMOUSE" and event.value == "PRESS":
            _region, space = _view3d_window_region_and_space(context)
            if _region is None or space is None:
                return {{"RUNNING_MODAL"}}
            try:
                self._drag_root = None
                self._drag_operation = "VIEW_PAN"
                self._view_pan_start_mouse_x = int(event.mouse_x)
                self._view_pan_start_mouse_y = int(event.mouse_y)
                self._view_pan_start_location = space.region_3d.view_location.copy()
                self._view_pan_start_rotation = space.region_3d.view_rotation.copy()
                viewport_size = max(1, min(int(_region.width), int(_region.height)))
                self._view_pan_scale = max(0.0001, float(space.region_3d.view_distance) * 2.0 / viewport_size)
                self._dragging = True
            except Exception:
                self._dragging = False
            return {{"RUNNING_MODAL"}}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            obj, hit_location = _raycast_visible_director_object(context, event)
            root = _director_drag_root_for_object(obj)
            if root is None:
                _region, space = _view3d_window_region_and_space(context)
                if space is None:
                    return {{"RUNNING_MODAL"}}
                try:
                    self._drag_operation = "VIEW_ROTATE"
                    self._view_rotate_start_mouse_x = int(event.mouse_x)
                    self._view_rotate_start_mouse_y = int(event.mouse_y)
                    self._view_rotate_start = space.region_3d.view_rotation.copy()
                    self._dragging = True
                except Exception:
                    self._dragging = False
                return {{"RUNNING_MODAL"}}
            self._drag_root = root
            self._dragging = True
            if event.shift:
                self._drag_operation = "ROTATE"
                self._rotate_start_mouse_x = int(event.mouse_x)
                try:
                    self._rotate_start_z = float(root.rotation_euler.z)
                except Exception:
                    self._rotate_start_z = 0.0
            else:
                self._drag_operation = "MOVE"
                try:
                    self._drag_plane_z = float(root.location.z)
                except Exception:
                    self._drag_plane_z = 0.0
                plane_point = _view3d_plane_intersection(context, event, self._drag_plane_z) or hit_location
                if plane_point is None:
                    self._drag_root = None
                    self._dragging = False
                    return {{"RUNNING_MODAL"}}
                self._drag_offset = root.location.copy() - plane_point
            try:
                bpy.ops.object.select_all(action="DESELECT")
                root.hide_set(False)
                root.select_set(True)
                context.view_layer.objects.active = root
                root.hide_set(True)
            except Exception:
                pass
            _remember_active_character(context, root)
            return {{"RUNNING_MODAL"}}
        if event.type == "MOUSEMOVE" and self._dragging and self._drag_operation == "VIEW_PAN":
            _region, space = _view3d_window_region_and_space(context)
            if space is None or self._view_pan_start_location is None or self._view_pan_start_rotation is None:
                return {{"RUNNING_MODAL"}}
            try:
                delta_x = int(event.mouse_x) - self._view_pan_start_mouse_x
                delta_y = int(event.mouse_y) - self._view_pan_start_mouse_y
                inverse_rotation = self._view_pan_start_rotation.inverted()
                view_right = inverse_rotation @ Vector((1.0, 0.0, 0.0))
                view_up = inverse_rotation @ Vector((0.0, 1.0, 0.0))
                space.region_3d.view_location = (
                    self._view_pan_start_location
                    - view_right * delta_x * self._view_pan_scale
                    - view_up * delta_y * self._view_pan_scale
                )
                context.area.tag_redraw()
            except Exception:
                pass
            return {{"RUNNING_MODAL"}}
        if event.type == "MOUSEMOVE" and self._dragging and self._drag_root is not None:
            if self._drag_operation == "ROTATE":
                try:
                    delta = int(event.mouse_x) - self._rotate_start_mouse_x
                    self._drag_root.rotation_euler.z = self._rotate_start_z + delta * 0.01
                    context.view_layer.update()
                except Exception:
                    pass
                return {{"RUNNING_MODAL"}}
            plane_point = _view3d_plane_intersection(context, event, self._drag_plane_z)
            if plane_point is None:
                return {{"RUNNING_MODAL"}}
            try:
                new_location = plane_point + self._drag_offset
                self._drag_root.location.x = new_location.x
                self._drag_root.location.y = new_location.y
                self._drag_root.location.z = self._drag_plane_z
                context.view_layer.update()
            except Exception:
                pass
            return {{"RUNNING_MODAL"}}
        if event.type == "MOUSEMOVE" and self._dragging and self._drag_operation == "VIEW_ROTATE":
            _region, space = _view3d_window_region_and_space(context)
            if space is None or self._view_rotate_start is None:
                return {{"RUNNING_MODAL"}}
            try:
                delta_x = int(event.mouse_x) - self._view_rotate_start_mouse_x
                delta_y = int(event.mouse_y) - self._view_rotate_start_mouse_y
                yaw = Quaternion((0.0, 0.0, 1.0), -delta_x * 0.005)
                pitch = Quaternion((1.0, 0.0, 0.0), delta_y * 0.005)
                space.region_3d.view_rotation = yaw @ self._view_rotate_start @ pitch
                context.area.tag_redraw()
            except Exception:
                pass
            return {{"RUNNING_MODAL"}}
        if event.type == "RIGHTMOUSE" and event.value == "RELEASE":
            if self._drag_operation != "VIEW_PAN":
                return {{"PASS_THROUGH"}}
            self._drag_root = None
            self._dragging = False
            self._drag_operation = "MOVE"
            self._view_pan_start_location = None
            self._view_pan_start_rotation = None
            return {{"RUNNING_MODAL"}}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._drag_root = None
            self._drag_offset = None
            self._dragging = False
            self._drag_operation = "MOVE"
            self._view_rotate_start = None
            return {{"RUNNING_MODAL"}}
        return {{"PASS_THROUGH"}}


class GPT_OT_director_add_sofa_set(bpy.types.Operator):
    bl_idname = "gpt_director.add_sofa_set"
    bl_label = "添加沙发茶几"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        left = _add_sofa_unit("左侧沙发", (-1.0, 0.25, 0), "builtin_left_sofa")
        right = _add_sofa_unit("右侧沙发", (1.0, 0.25, 0), "builtin_right_sofa")
        table = _add_round_table_asset("中心茶几", (0, -0.85, 0), "builtin_round_table")
        objects = []
        for bundle in (left, right, table):
            objects.extend(bundle.get("objects") or [])
        data = _load_meta()
        _record_builtin_asset(data, "builtin_sofa_table_props", "沙发茶几与圆桌道具", "prop", objects, ["Director Props", "Director Controls"])
        _save_meta(data)
        return {{"FINISHED"}}


class GPT_OT_director_add_round_table(bpy.types.Operator):
    bl_idname = "gpt_director.add_round_table"
    bl_label = "添加几何茶几"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        table = _add_round_table_asset("几何茶几", (0, 0, 0), "builtin_round_table")
        data = _load_meta()
        _record_builtin_asset(data, "builtin_round_table", "几何茶几道具", "prop", table.get("objects") or [], ["Director Props", "Director Controls"])
        _save_meta(data)
        return {{"FINISHED"}}


class GPT_OT_director_add_camera(bpy.types.Operator):
    bl_idname = "gpt_director.add_camera"
    bl_label = "添加镜头机位"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        _add_camera(name="Director Camera " + datetime.now().strftime("%H%M%S"))
        return {{"FINISHED"}}


class GPT_OT_director_camera_preset(bpy.types.Operator):
    bl_idname = "gpt_director.camera_preset"
    bl_label = "应用镜头预设"
    bl_options = {{"REGISTER", "UNDO"}}

    preset: StringProperty(default="medium")

    def execute(self, context):
        _set_camera_preset(self.preset)
        return {{"FINISHED"}}


class GPT_OT_director_save_camera_template(bpy.types.Operator):
    bl_idname = "gpt_director.save_camera_template"
    bl_label = "保存机位模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_camera_template_name()
        template_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "camera_template")
        template = _camera_template_from_current_scene(
            context.scene,
            template_id,
            name,
            _active_camera_template_note(),
        )
        _upsert_camera_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_camera_template = template_id
        try:
            context.scene.gpt_director_camera_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "机位模板已保存：" + name)
        return {{"FINISHED"}}


class GPT_OT_director_update_camera_template(bpy.types.Operator):
    bl_idname = "gpt_director.update_camera_template"
    bl_label = "更新机位模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_camera_template_key(context.scene)
        existing = _find_camera_template(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的机位模板，请先从机位模板列表选择一个模板")
            return {{"CANCELLED"}}
        template_id = str(existing.get("id") or key or _safe_id(_active_camera_template_name(), "camera_template"))
        template = _camera_template_from_current_scene(
            context.scene,
            template_id,
            _active_camera_template_name(),
            _active_camera_template_note(),
        )
        _upsert_camera_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_camera_template = template_id
        try:
            context.scene.gpt_director_camera_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "机位模板已更新：" + template.get("name", template_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_camera_template(bpy.types.Operator):
    bl_idname = "gpt_director.delete_camera_template"
    bl_label = "删除机位模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_camera_template_key(context.scene)
        template = _find_camera_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到要删除的机位模板")
            return {{"CANCELLED"}}
        removed = _delete_camera_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_camera_template = ""
        try:
            context.scene.gpt_director_camera_template_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "机位模板已删除：" + str(template.get("name") or template.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "机位模板删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_camera_template(bpy.types.Operator):
    bl_idname = "gpt_director.load_camera_template"
    bl_label = "加载机位模板"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_camera_template_key(context.scene)
        template = _find_camera_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到机位模板，请输入模板名或模板ID")
            return {{"CANCELLED"}}
        camera = _apply_camera_template(context, template)
        context.scene.gpt_director_camera_template_name = str(template.get("name") or template.get("id") or "")
        context.scene.gpt_director_camera_template_note = str(template.get("note") or "")
        context.scene.gpt_director_selected_camera_template = str(template.get("id") or template.get("name") or "")
        try:
            context.scene.gpt_director_camera_template_choice = str(template.get("id") or "__manual__")
        except Exception:
            pass
        camera_name = camera.name if camera else ""
        self.report({{"INFO"}}, "已加载机位模板：" + context.scene.gpt_director_camera_template_name + (("，相机 " + camera_name) if camera_name else ""))
        return {{"FINISHED"}}


class GPT_OT_director_save_object_template(bpy.types.Operator):
    bl_idname = "gpt_director.save_object_template"
    bl_label = "保存站位模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_object_template_name()
        template_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "object_template")
        try:
            template = _object_template_from_selected_objects(
                context,
                template_id,
                name,
                _active_object_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_object_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_object_template = template_id
        try:
            context.scene.gpt_director_object_template_choice = template_id
        except Exception:
            pass
        object_count = len(template.get("objects") or [])
        self.report({{"INFO"}}, "站位模板已保存：" + name + "，对象 " + str(object_count) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_update_object_template(bpy.types.Operator):
    bl_idname = "gpt_director.update_object_template"
    bl_label = "更新站位模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_object_template_key(context.scene)
        existing = _find_object_template(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的站位模板，请先从站位模板列表选择一个模板")
            return {{"CANCELLED"}}
        template_id = str(existing.get("id") or key or _safe_id(_active_object_template_name(), "object_template"))
        try:
            template = _object_template_from_selected_objects(
                context,
                template_id,
                _active_object_template_name(),
                _active_object_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_object_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_object_template = template_id
        try:
            context.scene.gpt_director_object_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "站位模板已更新：" + template.get("name", template_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_object_template(bpy.types.Operator):
    bl_idname = "gpt_director.delete_object_template"
    bl_label = "删除站位模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_object_template_key(context.scene)
        template = _find_object_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到要删除的站位模板")
            return {{"CANCELLED"}}
        removed = _delete_object_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_object_template = ""
        try:
            context.scene.gpt_director_object_template_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "站位模板已删除：" + str(template.get("name") or template.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "站位模板删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_object_template(bpy.types.Operator):
    bl_idname = "gpt_director.load_object_template"
    bl_label = "加载站位模板"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_object_template_key(context.scene)
        template = _find_object_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到站位模板，请输入模板名或模板ID")
            return {{"CANCELLED"}}
        applied = _apply_object_template(context, template)
        context.scene.gpt_director_object_template_name = str(template.get("name") or template.get("id") or "")
        context.scene.gpt_director_object_template_note = str(template.get("note") or "")
        context.scene.gpt_director_selected_object_template = str(template.get("id") or template.get("name") or "")
        try:
            context.scene.gpt_director_object_template_choice = str(template.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载站位模板：" + context.scene.gpt_director_object_template_name + "，应用对象 " + str(applied) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_camera_motion(bpy.types.Operator):
    bl_idname = "gpt_director.camera_motion"
    bl_label = "添加镜头运动"
    bl_options = {{"REGISTER", "UNDO"}}

    motion: StringProperty(default="push_in")

    def execute(self, context):
        motion = str(self.motion or "push_in")
        try:
            camera, frame_start, frame_end = _apply_camera_motion(motion)
        except Exception as exc:
            self.report({{"ERROR"}}, "添加镜头运动失败：" + str(exc))
            return {{"CANCELLED"}}
        data = _load_meta()
        _record_camera_motion(data, motion, camera.name if camera else "", frame_start, frame_end)
        _save_meta(data)
        label = CAMERA_MOTION_LABELS.get(motion, motion)
        self.report({{"INFO"}}, "镜头运动已添加：" + label)
        return {{"FINISHED"}}


class GPT_OT_director_object_motion(bpy.types.Operator):
    bl_idname = "gpt_director.object_motion"
    bl_label = "添加角色走位"
    bl_options = {{"REGISTER", "UNDO"}}

    motion: StringProperty(default="forward")

    def execute(self, context):
        motion = str(self.motion or "forward")
        data = _load_meta()
        actor = _active_actor(data)
        actor_objects = _objects_from_actor(actor) if actor else []
        try:
            objects, frame_start, frame_end = _apply_object_motion(motion, actor_objects or None)
        except Exception as exc:
            self.report({{"ERROR"}}, "添加走位失败：" + str(exc))
            return {{"CANCELLED"}}
        object_names = [obj.name for obj in objects]
        _record_object_motion(data, motion, object_names, frame_start, frame_end, actor)
        _save_meta(data)
        label = OBJECT_MOTION_LABELS.get(motion, motion)
        self.report({{"INFO"}}, "角色走位已添加：" + label)
        return {{"FINISHED"}}


class GPT_OT_director_three_point_lighting(bpy.types.Operator):
    bl_idname = "gpt_director.three_point_lighting"
    bl_label = "三点布光"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        _add_three_point_lighting()
        return {{"FINISHED"}}


class GPT_OT_director_save_light_template(bpy.types.Operator):
    bl_idname = "gpt_director.save_light_template"
    bl_label = "保存灯光模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_light_template_name()
        template_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "light_template")
        try:
            template = _light_template_from_current_scene(
                context,
                template_id,
                name,
                _active_light_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_light_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_light_template = template_id
        try:
            context.scene.gpt_director_light_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "灯光模板已保存：" + name + "，灯光 " + str(template.get("light_count") or 0) + " 盏")
        return {{"FINISHED"}}


class GPT_OT_director_update_light_template(bpy.types.Operator):
    bl_idname = "gpt_director.update_light_template"
    bl_label = "更新灯光模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_light_template_key(context.scene)
        existing = _find_light_template(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的灯光模板，请先从灯光模板列表选择一个模板")
            return {{"CANCELLED"}}
        template_id = str(existing.get("id") or key or _safe_id(_active_light_template_name(), "light_template"))
        try:
            template = _light_template_from_current_scene(
                context,
                template_id,
                _active_light_template_name(),
                _active_light_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_light_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_light_template = template_id
        try:
            context.scene.gpt_director_light_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "灯光模板已更新：" + template.get("name", template_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_light_template(bpy.types.Operator):
    bl_idname = "gpt_director.delete_light_template"
    bl_label = "删除灯光模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_light_template_key(context.scene)
        template = _find_light_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到要删除的灯光模板")
            return {{"CANCELLED"}}
        removed = _delete_light_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_light_template = ""
        try:
            context.scene.gpt_director_light_template_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "灯光模板已删除：" + str(template.get("name") or template.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "灯光模板删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_light_template(bpy.types.Operator):
    bl_idname = "gpt_director.load_light_template"
    bl_label = "加载灯光模板"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_light_template_key(context.scene)
        template = _find_light_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到灯光模板，请输入模板名或模板ID")
            return {{"CANCELLED"}}
        applied = _apply_light_template(context, template)
        context.scene.gpt_director_light_template_name = str(template.get("name") or template.get("id") or "")
        context.scene.gpt_director_light_template_note = str(template.get("note") or "")
        context.scene.gpt_director_selected_light_template = str(template.get("id") or template.get("name") or "")
        try:
            context.scene.gpt_director_light_template_choice = str(template.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载灯光模板：" + context.scene.gpt_director_light_template_name + "，应用灯光 " + str(applied) + " 盏")
        return {{"FINISHED"}}


class GPT_OT_director_insert_keyframe(bpy.types.Operator):
    bl_idname = "gpt_director.insert_keyframe"
    bl_label = "记录选中对象关键帧"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        objects = list(context.selected_objects or [])
        if not objects and context.scene.camera:
            objects = [context.scene.camera]
        if not objects:
            self.report({{"ERROR"}}, "请先选中要记录动作的对象")
            return {{"CANCELLED"}}
        frame = int(context.scene.frame_current)
        for obj in objects:
            try:
                obj.keyframe_insert(data_path="location", frame=frame)
                obj.keyframe_insert(data_path="rotation_euler", frame=frame)
                obj.keyframe_insert(data_path="scale", frame=frame)
            except Exception:
                pass
        self.report({{"INFO"}}, "已记录关键帧：" + str(frame))
        return {{"FINISHED"}}


class GPT_OT_director_save_shot(bpy.types.Operator):
    bl_idname = "gpt_director.save_shot"
    bl_label = "保存当前镜头"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_shot_name()
        shot_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "shot")
        shot = _shot_from_current_scene(context.scene, shot_id, name, _active_shot_note(), data)
        _upsert_timeline_marker(context.scene, shot)
        _upsert_shot(data, shot)
        _save_shot_file(shot)
        _save_meta(data)
        context.scene.gpt_director_selected_shot = shot_id
        try:
            context.scene.gpt_director_shot_choice = shot_id
        except Exception:
            pass
        self.report({{"INFO"}}, "当前镜头已保存：" + name)
        return {{"FINISHED"}}


class GPT_OT_director_update_shot(bpy.types.Operator):
    bl_idname = "gpt_director.update_shot"
    bl_label = "更新选中镜头"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_shot_key(context.scene)
        existing = _find_shot(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的保存镜头，请先从保存镜头列表选择一个镜头")
            return {{"CANCELLED"}}
        shot_id = str(existing.get("id") or key or _safe_id(_active_shot_name(), "shot"))
        shot = _shot_from_current_scene(context.scene, shot_id, _active_shot_name(), _active_shot_note(), data)
        _delete_timeline_marker(context.scene, existing)
        _upsert_timeline_marker(context.scene, shot)
        _upsert_shot(data, shot)
        _save_shot_file(shot)
        _save_meta(data)
        context.scene.gpt_director_selected_shot = shot_id
        try:
            context.scene.gpt_director_shot_choice = shot_id
        except Exception:
            pass
        self.report({{"INFO"}}, "选中镜头已更新：" + shot.get("name", shot_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_shot(bpy.types.Operator):
    bl_idname = "gpt_director.delete_shot"
    bl_label = "删除选中镜头"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_shot_key(context.scene)
        shot = _find_shot(data, key)
        if not shot:
            self.report({{"ERROR"}}, "没有找到要删除的保存镜头")
            return {{"CANCELLED"}}
        removed = _delete_shot(data, shot)
        _delete_shot_file(shot)
        _delete_timeline_marker(context.scene, shot)
        _save_meta(data)
        context.scene.gpt_director_selected_shot = ""
        try:
            context.scene.gpt_director_shot_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "选中镜头已删除：" + str(shot.get("name") or shot.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "镜头记录删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_shot(bpy.types.Operator):
    bl_idname = "gpt_director.load_shot"
    bl_label = "加载保存镜头"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_shot_key(context.scene)
        shot = _find_shot(data, key)
        if not shot:
            self.report({{"ERROR"}}, "没有找到保存镜头，请输入镜头名或镜头ID")
            return {{"CANCELLED"}}
        _apply_camera_snapshot(shot.get("camera") or {{}})
        _apply_object_snapshots(shot.get("objects") or [])
        try:
            context.scene.frame_current = int(shot.get("frame") or context.scene.frame_current)
        except Exception:
            pass
        _upsert_timeline_marker(context.scene, shot)
        context.scene.gpt_director_shot_name = str(shot.get("name") or shot.get("id") or "")
        context.scene.gpt_director_shot_note = str(shot.get("note") or "")
        context.scene.gpt_director_scene_number = str(shot.get("scene_number") or "")
        context.scene.gpt_director_scene_location = str(shot.get("scene_location") or "")
        scene_environment = str(shot.get("scene_environment") or "unspecified")
        if scene_environment in SCENE_ENVIRONMENT_LABELS:
            context.scene.gpt_director_scene_environment = scene_environment
        scene_time = str(shot.get("scene_time") or "unspecified")
        if scene_time in SCENE_TIME_LABELS:
            context.scene.gpt_director_scene_time = scene_time
        status = str(shot.get("shot_status") or "draft")
        if status in SHOT_STATUS_LABELS:
            context.scene.gpt_director_shot_status = status
        context.scene.gpt_director_selected_shot = str(shot.get("id") or shot.get("name") or "")
        try:
            context.scene.gpt_director_shot_choice = str(shot.get("id") or "__manual__")
        except Exception:
            pass
        output_type = str(shot.get("output_type") or "")
        if output_type in RENDER_OUTPUT_LABELS:
            context.scene.gpt_director_render_output = output_type
        try:
            context.scene.gpt_director_frame_start = int(shot.get("frame_start") or context.scene.gpt_director_frame_start)
            context.scene.gpt_director_frame_end = int(shot.get("frame_end") or context.scene.gpt_director_frame_end)
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载镜头：" + context.scene.gpt_director_shot_name)
        return {{"FINISHED"}}


class GPT_OT_director_save_shot_package(bpy.types.Operator):
    bl_idname = "gpt_director.save_shot_package"
    bl_label = "保存镜头包"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_shot_package_name()
        package_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "shot_package")
        try:
            package = _shot_package_from_saved_shots(
                data,
                package_id,
                name,
                _active_shot_package_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_shot_package(data, package)
        _save_meta(data)
        context.scene.gpt_director_selected_shot_package = package_id
        try:
            context.scene.gpt_director_shot_package_choice = package_id
        except Exception:
            pass
        self.report({{"INFO"}}, "镜头包已保存：" + name + "，镜头 " + str(package.get("shot_count") or len(package.get("shots") or [])) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_update_shot_package(bpy.types.Operator):
    bl_idname = "gpt_director.update_shot_package"
    bl_label = "更新镜头包"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_shot_package_key(context.scene)
        existing = _find_shot_package(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的镜头包，请先从镜头包列表选择一个镜头包")
            return {{"CANCELLED"}}
        package_id = str(existing.get("id") or key or _safe_id(_active_shot_package_name(), "shot_package"))
        try:
            package = _shot_package_from_saved_shots(
                data,
                package_id,
                _active_shot_package_name(),
                _active_shot_package_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_shot_package(data, package)
        _save_meta(data)
        context.scene.gpt_director_selected_shot_package = package_id
        try:
            context.scene.gpt_director_shot_package_choice = package_id
        except Exception:
            pass
        self.report({{"INFO"}}, "镜头包已更新：" + package.get("name", package_id) + "，镜头 " + str(package.get("shot_count") or len(package.get("shots") or [])) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_delete_shot_package(bpy.types.Operator):
    bl_idname = "gpt_director.delete_shot_package"
    bl_label = "删除镜头包"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_shot_package_key(context.scene)
        package = _find_shot_package(data, key)
        if not package:
            self.report({{"ERROR"}}, "没有找到要删除的镜头包")
            return {{"CANCELLED"}}
        removed = _delete_shot_package(data, package)
        _save_meta(data)
        context.scene.gpt_director_selected_shot_package = ""
        try:
            context.scene.gpt_director_shot_package_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "镜头包已删除：" + str(package.get("name") or package.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "镜头包删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_shot_package(bpy.types.Operator):
    bl_idname = "gpt_director.load_shot_package"
    bl_label = "加载镜头包"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_shot_package_key(context.scene)
        package = _find_shot_package(data, key)
        if not package:
            self.report({{"ERROR"}}, "没有找到镜头包，请输入镜头包名或镜头包ID")
            return {{"CANCELLED"}}
        try:
            loaded = _load_shot_package_into_project(context, data, package)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _save_meta(data)
        context.scene.gpt_director_shot_package_name = str(package.get("name") or package.get("id") or "")
        context.scene.gpt_director_shot_package_note = str(package.get("note") or "")
        context.scene.gpt_director_selected_shot_package = str(package.get("id") or package.get("name") or "")
        try:
            context.scene.gpt_director_shot_package_choice = str(package.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载镜头包：" + context.scene.gpt_director_shot_package_name + "，新增镜头 " + str(loaded) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_save_set_package(bpy.types.Operator):
    bl_idname = "gpt_director.save_set_package"
    bl_label = "保存布景包"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        name = _active_set_package_name()
        package_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "set_package")
        try:
            package = _set_package_from_selected_objects(
                context,
                package_id,
                name,
                _active_set_package_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        data = _load_meta()
        _upsert_set_package(data, package)
        _save_meta(data)
        context.scene.gpt_director_selected_set_package = package_id
        try:
            context.scene.gpt_director_set_package_choice = package_id
        except Exception:
            pass
        self.report({{"INFO"}}, "布景包已保存：" + name + "，对象 " + str(package.get("object_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_update_set_package(bpy.types.Operator):
    bl_idname = "gpt_director.update_set_package"
    bl_label = "更新布景包"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_set_package_key(context.scene)
        existing = _find_set_package(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的布景包，请先从布景包列表选择一个布景包")
            return {{"CANCELLED"}}
        package_id = str(existing.get("id") or key or _safe_id(_active_set_package_name(), "set_package"))
        try:
            package = _set_package_from_selected_objects(
                context,
                package_id,
                _active_set_package_name(),
                _active_set_package_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_set_package(data, package)
        _save_meta(data)
        context.scene.gpt_director_selected_set_package = package_id
        try:
            context.scene.gpt_director_set_package_choice = package_id
        except Exception:
            pass
        self.report({{"INFO"}}, "布景包已更新：" + package.get("name", package_id) + "，对象 " + str(package.get("object_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_delete_set_package(bpy.types.Operator):
    bl_idname = "gpt_director.delete_set_package"
    bl_label = "删除布景包"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_set_package_key(context.scene)
        package = _find_set_package(data, key)
        if not package:
            self.report({{"ERROR"}}, "没有找到要删除的布景包")
            return {{"CANCELLED"}}
        removed = _delete_set_package(data, package)
        _save_meta(data)
        context.scene.gpt_director_selected_set_package = ""
        try:
            context.scene.gpt_director_set_package_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "布景包已删除：" + str(package.get("name") or package.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "布景包删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_set_package(bpy.types.Operator):
    bl_idname = "gpt_director.load_set_package"
    bl_label = "加载布景包"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_set_package_key(context.scene)
        package = _find_set_package(data, key)
        if not package:
            self.report({{"ERROR"}}, "没有找到布景包，请输入布景包名或布景包ID")
            return {{"CANCELLED"}}
        try:
            object_count, collection_count = _load_set_package_into_project(context, package)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        context.scene.gpt_director_set_package_name = str(package.get("name") or package.get("id") or "")
        context.scene.gpt_director_set_package_note = str(package.get("note") or "")
        context.scene.gpt_director_selected_set_package = str(package.get("id") or package.get("name") or "")
        try:
            context.scene.gpt_director_set_package_choice = str(package.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载布景包：" + context.scene.gpt_director_set_package_name + "，对象 " + str(object_count) + " 个，集合 " + str(collection_count) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_save_actor(bpy.types.Operator):
    bl_idname = "gpt_director.save_actor"
    bl_label = "保存演员位"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_actor_name()
        actor_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "actor")
        try:
            actor = _actor_from_selected_objects(
                context,
                actor_id,
                name,
                _active_actor_role(),
                _active_actor_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_actor(data, actor)
        _save_meta(data)
        context.scene.gpt_director_selected_actor = actor_id
        try:
            context.scene.gpt_director_actor_choice = actor_id
        except Exception:
            pass
        self.report({{"INFO"}}, "演员位已保存：" + name + "，对象 " + str(actor.get("object_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_update_actor(bpy.types.Operator):
    bl_idname = "gpt_director.update_actor"
    bl_label = "更新演员位"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_actor_key(context.scene)
        existing = _find_actor(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的演员位，请先从演员位列表选择一个角色")
            return {{"CANCELLED"}}
        actor_id = str(existing.get("id") or key or _safe_id(_active_actor_name(), "actor"))
        try:
            actor = _actor_from_selected_objects(
                context,
                actor_id,
                _active_actor_name(),
                _active_actor_role(),
                _active_actor_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_actor(data, actor)
        _save_meta(data)
        context.scene.gpt_director_selected_actor = actor_id
        try:
            context.scene.gpt_director_actor_choice = actor_id
        except Exception:
            pass
        self.report({{"INFO"}}, "演员位已更新：" + actor.get("name", actor_id) + "，对象 " + str(actor.get("object_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_delete_actor(bpy.types.Operator):
    bl_idname = "gpt_director.delete_actor"
    bl_label = "删除演员位"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_actor_key(context.scene)
        actor = _find_actor(data, key)
        if not actor:
            self.report({{"ERROR"}}, "没有找到要删除的演员位")
            return {{"CANCELLED"}}
        removed = _delete_actor(data, actor)
        _save_meta(data)
        context.scene.gpt_director_selected_actor = ""
        try:
            context.scene.gpt_director_actor_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "演员位已删除：" + str(actor.get("name") or actor.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "演员位删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_actor(bpy.types.Operator):
    bl_idname = "gpt_director.load_actor"
    bl_label = "加载演员位"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_actor_key(context.scene)
        actor = _find_actor(data, key)
        if not actor:
            self.report({{"ERROR"}}, "没有找到演员位，请输入演员名或演员ID")
            return {{"CANCELLED"}}
        count = _select_actor_objects(actor)
        context.scene.gpt_director_actor_name = str(actor.get("name") or actor.get("id") or "")
        context.scene.gpt_director_actor_role = str(actor.get("role") or "")
        context.scene.gpt_director_actor_note = str(actor.get("note") or "")
        context.scene.gpt_director_selected_actor = str(actor.get("id") or actor.get("name") or "")
        try:
            context.scene.gpt_director_actor_choice = str(actor.get("id") or "__manual__")
        except Exception:
            pass
        if count:
            self.report({{"INFO"}}, "已加载演员位：" + context.scene.gpt_director_actor_name + "，选中对象 " + str(count) + " 个")
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "演员位记录里没有找到可选中的对象")
        return {{"CANCELLED"}}


class GPT_OT_director_save_scene_preset(bpy.types.Operator):
    bl_idname = "gpt_director.save_scene_preset"
    bl_label = "保存场景预设"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_preset_name()
        preset_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "preset")
        preset = _scene_preset_from_current_scene(context.scene, preset_id, name, _active_preset_note())
        _upsert_scene_preset(data, preset)
        _save_scene_preset_file(preset)
        _save_meta(data)
        context.scene.gpt_director_selected_preset = preset_id
        try:
            context.scene.gpt_director_preset_choice = preset_id
        except Exception:
            pass
        self.report({{"INFO"}}, "场景预设已保存：" + name)
        return {{"FINISHED"}}


class GPT_OT_director_update_scene_preset(bpy.types.Operator):
    bl_idname = "gpt_director.update_scene_preset"
    bl_label = "更新场景预设"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_scene_preset_key(context.scene)
        existing = _find_scene_preset(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的场景预设，请先从场景预设列表选择一个预设")
            return {{"CANCELLED"}}
        preset_id = str(existing.get("id") or key or _safe_id(_active_preset_name(), "preset"))
        preset = _scene_preset_from_current_scene(context.scene, preset_id, _active_preset_name(), _active_preset_note())
        _upsert_scene_preset(data, preset)
        _save_scene_preset_file(preset)
        _save_meta(data)
        context.scene.gpt_director_selected_preset = preset_id
        try:
            context.scene.gpt_director_preset_choice = preset_id
        except Exception:
            pass
        self.report({{"INFO"}}, "场景预设已更新：" + preset.get("name", preset_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_scene_preset(bpy.types.Operator):
    bl_idname = "gpt_director.delete_scene_preset"
    bl_label = "删除场景预设"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_scene_preset_key(context.scene)
        preset = _find_scene_preset(data, key)
        if not preset:
            self.report({{"ERROR"}}, "没有找到要删除的场景预设")
            return {{"CANCELLED"}}
        removed = _delete_scene_preset(data, preset)
        _delete_scene_preset_file(preset)
        _save_meta(data)
        context.scene.gpt_director_selected_preset = ""
        try:
            context.scene.gpt_director_preset_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "场景预设已删除：" + str(preset.get("name") or preset.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "场景预设记录删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_scene_preset(bpy.types.Operator):
    bl_idname = "gpt_director.load_scene_preset"
    bl_label = "加载场景预设"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_scene_preset_key(context.scene)
        preset = _find_scene_preset(data, key)
        if not preset:
            self.report({{"ERROR"}}, "没有找到场景预设，请输入预设名或预设ID")
            return {{"CANCELLED"}}
        applied = _apply_scene_preset(context, preset)
        context.scene.gpt_director_preset_name = str(preset.get("name") or preset.get("id") or "")
        context.scene.gpt_director_preset_note = str(preset.get("note") or "")
        context.scene.gpt_director_selected_preset = str(preset.get("id") or preset.get("name") or "")
        try:
            context.scene.gpt_director_preset_choice = str(preset.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载场景预设：" + context.scene.gpt_director_preset_name + "，恢复对象 " + str(applied) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_import_model(bpy.types.Operator, ImportHelper):
    bl_idname = "gpt_director.import_model"
    bl_label = "导入资产"
    bl_options = {{"REGISTER", "UNDO"}}
    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.blend;*.glb;*.gltf;*.fbx;*.obj;*.bvh;*.stl;*.ply;*.abc;*.usd;*.usdz;*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.exr;*.hdr", options={{"HIDDEN"}})

    def execute(self, context):
        filepath = self.filepath
        asset_kind = str(getattr(context.scene, "gpt_director_asset_kind", "model") or "model")
        if asset_kind == "model":
            hinted_kind = _asset_kind_from_path(filepath)
            if hinted_kind in ASSET_KIND_COLLECTIONS:
                asset_kind = hinted_kind
        asset_label = str(getattr(context.scene, "gpt_director_asset_name", "") or "").strip()
        data = _load_meta()
        actor, target_armature = _active_action_target(data) if asset_kind == "action" else ({{}}, None)
        try:
            asset_record = _import_director_asset(filepath, asset_kind, asset_label, target_armature)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        if asset_kind == "action":
            _record_action_application(
                data,
                asset_record.get("target_armature", target_armature.name if target_armature else ""),
                (asset_record.get("actions") or [""])[-1] if isinstance(asset_record.get("actions"), list) else "",
                asset_record.get("auto_apply_status", "not_applied"),
                asset_record.get("auto_apply_message", ""),
                actor,
            )
            _upsert_action_clip_from_asset_record(data, asset_record, actor, target_armature)
        _append_asset_record(data, asset_record)
        _save_meta(data)
        self.report({{"INFO"}}, "资产已导入：" + asset_record.get("name", os.path.basename(filepath)))
        return {{"FINISHED"}}


class GPT_OT_director_import_asset_directory(bpy.types.Operator):
    bl_idname = "gpt_director.import_asset_directory"
    bl_label = "导入资产目录"
    bl_options = {{"REGISTER", "UNDO"}}

    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {{"RUNNING_MODAL"}}

    def execute(self, context):
        directory = str(self.directory or "").strip()
        paths = _asset_paths_from_directory(directory, recursive=True)
        if not paths:
            self.report({{"ERROR"}}, "目录里没有支持的资产文件")
            return {{"CANCELLED"}}
        asset_kind = str(getattr(context.scene, "gpt_director_asset_kind", "model") or "model")
        target_armature = _active_armature() if asset_kind == "action" else None
        imported, failed = _import_asset_paths(paths, asset_kind, "", target_armature)
        if imported:
            self.report({{"INFO"}}, "资产目录已导入：" + str(imported) + " 个" + (("，失败 " + str(failed) + " 个") if failed else ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "资产目录导入失败")
        return {{"CANCELLED"}}


class GPT_OT_director_scan_asset_library(bpy.types.Operator):
    bl_idname = "gpt_director.scan_asset_library"
    bl_label = "扫描资产库目录"
    bl_options = {{"REGISTER"}}

    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        current = str(getattr(context.scene, "gpt_director_asset_library_path", "") or "").strip()
        if current:
            self.directory = current
        context.window_manager.fileselect_add(self)
        return {{"RUNNING_MODAL"}}

    def execute(self, context):
        directory = str(self.directory or getattr(context.scene, "gpt_director_asset_library_path", "") or "").strip()
        if not directory or not os.path.isdir(directory):
            self.report({{"ERROR"}}, "请选择可用的资产库目录")
            return {{"CANCELLED"}}
        data = _load_meta()
        profile_id = _active_asset_source_profile()
        library, items = _scan_asset_library(data, directory, profile_id)
        _save_meta(data)
        context.scene.gpt_director_asset_library_path = str(library.get("path") or directory)
        profile_label = str(library.get("source_profile_name") or "")
        self.report({{"INFO"}}, (profile_label + " " if profile_label else "") + "资产库已扫描：" + str(len(items)) + " 个文件")
        return {{"FINISHED"}}


class GPT_OT_director_import_library_asset(bpy.types.Operator):
    bl_idname = "gpt_director.import_library_asset"
    bl_label = "导入选中库资产"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = str(getattr(context.scene, "gpt_director_library_asset_choice", "") or "").strip()
        item = _find_library_asset(data, key)
        if not item:
            self.report({{"ERROR"}}, "没有找到选中的库资产，请先扫描资产库")
            return {{"CANCELLED"}}
        preflight = _asset_preflight_for_library_item(data, item)
        _set_library_asset_preflight(data, key, preflight)
        if preflight.get("blocked"):
            _save_meta(data)
            self.report({{"ERROR"}}, _asset_preflight_error_message(preflight))
            return {{"CANCELLED"}}
        filepath = str(item.get("path") or "").strip()
        if not filepath or not os.path.exists(filepath):
            self.report({{"ERROR"}}, "库资产文件不存在，请重新扫描资产库")
            return {{"CANCELLED"}}
        asset_kind = str(getattr(context.scene, "gpt_director_asset_kind", "model") or "model")
        item_kind = str(item.get("kind_hint") or "").strip()
        if asset_kind == "model" and item_kind in ASSET_KIND_COLLECTIONS:
            asset_kind = item_kind
        if filepath.lower().endswith(".bvh"):
            asset_kind = "action"
        asset_label = str(getattr(context.scene, "gpt_director_asset_name", "") or "").strip() or str(item.get("name") or os.path.basename(filepath))
        actor, target_armature = _active_action_target(data) if asset_kind == "action" else ({{}}, None)
        try:
            asset_record = _import_director_asset(filepath, asset_kind, asset_label, target_armature)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        asset_record["library_item_id"] = str(item.get("id") or "")
        asset_record["library_path"] = str(item.get("library_path") or "")
        asset_record["library_relative_path"] = str(item.get("relative_path") or "")
        asset_record["source_profile_id"] = str(item.get("source_profile_id") or "")
        asset_record["source_profile_name"] = str(item.get("source_profile_name") or "")
        if asset_kind == "action":
            _record_action_application(
                data,
                asset_record.get("target_armature", target_armature.name if target_armature else ""),
                (asset_record.get("actions") or [""])[-1] if isinstance(asset_record.get("actions"), list) else "",
                asset_record.get("auto_apply_status", "not_applied"),
                asset_record.get("auto_apply_message", ""),
                actor,
            )
            _upsert_action_clip_from_asset_record(data, asset_record, actor, target_armature, item)
        _append_asset_record(data, asset_record)
        _mark_library_asset_used(data, key)
        _save_meta(data)
        try:
            context.scene.gpt_director_asset_choice = asset_record.get("id", "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "库资产已导入：" + asset_record.get("name", os.path.basename(filepath)))
        return {{"FINISHED"}}


class GPT_OT_director_apply_library_texture_material(bpy.types.Operator):
    bl_idname = "gpt_director.apply_library_texture_material"
    bl_label = "应用贴图材质"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = str(getattr(context.scene, "gpt_director_library_asset_choice", "") or "").strip()
        item = _find_library_asset(data, key)
        if not item:
            self.report({{"ERROR"}}, "没有找到选中的贴图/材质库资产，请先扫描资产库")
            return {{"CANCELLED"}}
        preflight = _asset_preflight_for_library_item(data, item)
        _set_library_asset_preflight(data, key, preflight)
        if preflight.get("blocked"):
            _save_meta(data)
            self.report({{"ERROR"}}, _asset_preflight_error_message(preflight))
            return {{"CANCELLED"}}
        try:
            asset_record, application = _apply_library_texture_material(context, data, item)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _mark_library_asset_used(data, key)
        _save_meta(data)
        try:
            context.scene.gpt_director_asset_choice = asset_record.get("id", "__manual__")
        except Exception:
            pass
        if application.get("type") == "hdri":
            self.report({{"INFO"}}, "HDRI 环境光已应用：" + str(application.get("name") or asset_record.get("name") or ""))
        else:
            self.report({{"INFO"}}, "贴图材质已应用：" + str(application.get("name") or asset_record.get("name") or "") + "，对象 " + str(application.get("object_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_favorite_library_asset(bpy.types.Operator):
    bl_idname = "gpt_director.favorite_library_asset"
    bl_label = "收藏/取消收藏库资产"
    bl_options = {{"REGISTER"}}

    favorite: BoolProperty(default=True)

    def execute(self, context):
        data = _load_meta()
        key = str(getattr(context.scene, "gpt_director_library_asset_choice", "") or "").strip()
        item = _set_library_asset_favorite(data, key, self.favorite)
        if not item:
            self.report({{"ERROR"}}, "没有找到选中的库资产，请先扫描资产库")
            return {{"CANCELLED"}}
        _save_meta(data)
        try:
            context.scene.gpt_director_library_asset_choice = str(item.get("id") or "__manual__")
        except Exception:
            pass
        name = str(item.get("name") or item.get("file_name") or "库资产")
        self.report({{"INFO"}}, ("已收藏库资产：" if self.favorite else "已取消收藏：") + name)
        return {{"FINISHED"}}


class GPT_OT_director_load_library_asset_metadata(bpy.types.Operator):
    bl_idname = "gpt_director.load_library_asset_metadata"
    bl_label = "读取库资产标签"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = str(getattr(context.scene, "gpt_director_library_asset_choice", "") or "").strip()
        item = _find_library_asset(data, key)
        if not item:
            self.report({{"ERROR"}}, "没有找到选中的库资产，请先扫描资产库")
            return {{"CANCELLED"}}
        context.scene.gpt_director_library_asset_tags = str(item.get("tags") or "")
        context.scene.gpt_director_library_asset_note = str(item.get("usage_note") or "")
        self.report({{"INFO"}}, "已读取库资产标签")
        return {{"FINISHED"}}


class GPT_OT_director_update_library_asset_metadata(bpy.types.Operator):
    bl_idname = "gpt_director.update_library_asset_metadata"
    bl_label = "保存库资产标签"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = str(getattr(context.scene, "gpt_director_library_asset_choice", "") or "").strip()
        tags = str(getattr(context.scene, "gpt_director_library_asset_tags", "") or "").strip()
        usage_note = str(getattr(context.scene, "gpt_director_library_asset_note", "") or "").strip()
        item = _set_library_asset_metadata(data, key, tags, usage_note)
        if not item:
            self.report({{"ERROR"}}, "没有找到选中的库资产，请先扫描资产库")
            return {{"CANCELLED"}}
        _save_meta(data)
        name = str(item.get("name") or item.get("file_name") or "库资产")
        self.report({{"INFO"}}, "已保存库资产标签：" + name)
        return {{"FINISHED"}}


class GPT_OT_director_register_selected_asset(bpy.types.Operator):
    bl_idname = "gpt_director.register_selected_asset"
    bl_label = "登记选中为资产"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        asset_kind = str(getattr(context.scene, "gpt_director_asset_kind", "model") or "model")
        asset_label = str(getattr(context.scene, "gpt_director_asset_name", "") or "").strip()
        try:
            asset_record = _register_selected_asset(asset_kind, asset_label)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        data = _load_meta()
        _append_asset_record(data, asset_record)
        _save_meta(data)
        try:
            context.scene.gpt_director_asset_choice = asset_record.get("id", "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已登记工程资产：" + asset_record.get("name", "工程资产"))
        return {{"FINISHED"}}


class GPT_OT_director_import_plan_assets(bpy.types.Operator):
    bl_idname = "gpt_director.import_plan_assets"
    bl_label = "导入工程资产清单"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        plan = data.get("plan") if isinstance(data.get("plan"), dict) else {{}}
        asset_paths = plan.get("asset_paths") if isinstance(plan.get("asset_paths"), list) else []
        clean_paths = []
        seen = set()
        for path in asset_paths:
            path = str(path or "").strip()
            if not path or path in seen or not os.path.exists(path):
                continue
            seen.add(path)
            clean_paths.append(path)
        if not clean_paths:
            self.report({{"ERROR"}}, "工程计划里没有可导入的资产路径")
            return {{"CANCELLED"}}
        imported = 0
        failed = 0
        actor, target_armature = _active_action_target(data)
        for path in clean_paths:
            asset_kind = _asset_kind_from_path(path)
            try:
                record = _import_director_asset(path, asset_kind, os.path.basename(path), target_armature if asset_kind == "action" else None)
                if asset_kind == "action":
                    _record_action_application(
                        data,
                        record.get("target_armature", target_armature.name if target_armature else ""),
                        (record.get("actions") or [""])[-1] if isinstance(record.get("actions"), list) else "",
                        record.get("auto_apply_status", "not_applied"),
                        record.get("auto_apply_message", ""),
                        actor,
                    )
                    _upsert_action_clip_from_asset_record(data, record, actor, target_armature)
                _append_asset_record(data, record)
                imported += 1
            except Exception as exc:
                failed += 1
                print("GPT_DIRECTOR_PLAN_ASSET_IMPORT_FAILED", path, exc)
        _save_meta(data)
        if imported:
            self.report({{"INFO"}}, "工程资产已导入：" + str(imported) + " 个" + (("，失败 " + str(failed) + " 个") if failed else ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "工程资产导入失败")
        return {{"CANCELLED"}}


class GPT_OT_director_prepare_shot_assets(bpy.types.Operator):
    bl_idname = "gpt_director.prepare_shot_assets"
    bl_label = "准备当前镜头资产"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data, shot, plan = _active_shot_asset_plan(context)
        if not shot:
            self.report({{"ERROR"}}, "请先选择或保存一个镜头")
            return {{"CANCELLED"}}
        requirements = plan.get("requirements") if isinstance(plan.get("requirements"), list) else []
        if not requirements:
            self.report({{"ERROR"}}, "当前镜头没有记录演员或资产依赖")
            return {{"CANCELLED"}}
        actor, target_armature = _active_action_target(data)
        imported = 0
        skipped = 0
        failed = 0
        imported_assets = []
        skipped_requirements = []
        used_candidates = set()
        last_asset_id = ""
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            if requirement.get("available"):
                skipped += 1
                skipped_requirements.append({{"name": str(requirement.get("name") or ""), "reason": "已具备"}})
                continue
            candidate = requirement.get("best_library_candidate") if isinstance(requirement.get("best_library_candidate"), dict) else {{}}
            candidate_id = str(candidate.get("id") or "").strip()
            if not candidate_id:
                skipped += 1
                skipped_requirements.append({{"name": str(requirement.get("name") or ""), "reason": "没有本地库候选"}})
                continue
            if candidate_id in used_candidates:
                skipped += 1
                skipped_requirements.append({{"name": str(requirement.get("name") or ""), "reason": "候选已用于本镜头"}})
                continue
            used_candidates.add(candidate_id)
            item = _find_library_asset(data, candidate_id)
            if not item:
                skipped += 1
                skipped_requirements.append({{"name": str(requirement.get("name") or ""), "reason": "候选记录不存在"}})
                continue
            preflight = _asset_preflight_for_library_item(data, item)
            _set_library_asset_preflight(data, candidate_id, preflight)
            if preflight.get("blocked"):
                skipped += 1
                skipped_requirements.append({{"name": str(requirement.get("name") or ""), "reason": _asset_preflight_error_message(preflight)}})
                continue
            filepath = str(item.get("path") or "").strip()
            if not filepath or not os.path.exists(filepath):
                skipped += 1
                skipped_requirements.append({{"name": str(requirement.get("name") or ""), "reason": "候选文件不存在"}})
                continue
            item_kind = str(item.get("kind_hint") or _asset_kind_from_path(filepath, item) or "").strip()
            target_type = _shot_asset_target_type(requirement)
            asset_kind = item_kind if item_kind in ASSET_KIND_COLLECTIONS else (target_type if target_type in ASSET_KIND_COLLECTIONS else "model")
            if filepath.lower().endswith(".bvh"):
                asset_kind = "action"
            label = str(requirement.get("name") or item.get("name") or item.get("file_name") or os.path.basename(filepath))
            try:
                asset_record = _import_director_asset(filepath, asset_kind, label, target_armature if asset_kind == "action" else None)
            except Exception as exc:
                failed += 1
                skipped_requirements.append({{"name": label, "reason": "导入失败：" + str(exc)}})
                continue
            asset_record["library_item_id"] = str(item.get("id") or "")
            asset_record["library_path"] = str(item.get("library_path") or "")
            asset_record["library_relative_path"] = str(item.get("relative_path") or "")
            asset_record["source_profile_id"] = str(item.get("source_profile_id") or "")
            asset_record["source_profile_name"] = str(item.get("source_profile_name") or "")
            asset_record["prepared_for_shot_id"] = str(shot.get("id") or "")
            asset_record["prepared_for_shot_name"] = str(shot.get("name") or "")
            asset_record["shot_asset_requirement"] = {{
                "kind": str(requirement.get("kind") or ""),
                "name": str(requirement.get("name") or ""),
                "type": str(requirement.get("type") or ""),
                "candidate_score": candidate.get("score"),
            }}
            if asset_kind == "action":
                _record_action_application(
                    data,
                    asset_record.get("target_armature", target_armature.name if target_armature else ""),
                    (asset_record.get("actions") or [""])[-1] if isinstance(asset_record.get("actions"), list) else "",
                    asset_record.get("auto_apply_status", "not_applied"),
                    asset_record.get("auto_apply_message", ""),
                    actor,
                )
                _upsert_action_clip_from_asset_record(data, asset_record, actor, target_armature, item)
            _append_asset_record(data, asset_record)
            _mark_library_asset_used(data, candidate_id)
            imported += 1
            last_asset_id = str(asset_record.get("id") or "")
            imported_assets.append({{
                "id": last_asset_id,
                "name": str(asset_record.get("name") or ""),
                "type": str(asset_record.get("type") or ""),
                "library_item_id": str(item.get("id") or ""),
                "requirement_name": str(requirement.get("name") or ""),
            }})
        _append_shot_asset_preparation(data, {{
            "shot_id": str(shot.get("id") or ""),
            "shot_name": str(shot.get("name") or ""),
            "imported_count": imported,
            "skipped_count": skipped,
            "failed_count": failed,
            "imported_assets": imported_assets,
            "skipped_requirements": skipped_requirements,
            "prepared_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }})
        _save_meta(data)
        if last_asset_id:
            try:
                context.scene.gpt_director_asset_choice = last_asset_id
            except Exception:
                pass
        if imported:
            self.report({{"INFO"}}, "镜头资产已准备：" + str(imported) + " 个" + (("，跳过 " + str(skipped)) if skipped else "") + (("，失败 " + str(failed)) if failed else ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "没有可导入的镜头资产候选")
        return {{"CANCELLED"}}


class GPT_OT_director_export_ai_workflow_tasks(bpy.types.Operator):
    bl_idname = "gpt_director.export_ai_workflow_tasks"
    bl_label = "导出AI工作流任务包"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        task_data, manifest_path, report_path, csv_path = _write_ai_workflow_tasks(data)
        _save_meta(data)
        self.report({{"INFO"}}, "AI工作流任务包已导出：" + str(task_data.get("task_count") or 0) + " 个任务")
        return {{"FINISHED"}}


class GPT_OT_director_export_ai_workflow_handoff(bpy.types.Operator):
    bl_idname = "gpt_director.export_ai_workflow_handoff"
    bl_label = "导出AI工作包与结果收件箱"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        manifest, manifest_path, report_path, csv_path, readme_path = _write_ai_workflow_handoff(data)
        _save_meta(data)
        self.report({{"INFO"}}, "AI工作包已导出：" + str(manifest.get("task_count") or 0) + " 个任务")
        return {{"FINISHED"}}


class GPT_OT_director_register_ai_workflow_result(bpy.types.Operator, ImportHelper):
    bl_idname = "gpt_director.register_ai_workflow_result"
    bl_label = "登记AI生成结果"
    bl_options = {{"REGISTER", "UNDO"}}
    filename_ext = ".png"
    filter_glob: StringProperty(default="*.blend;*.glb;*.gltf;*.fbx;*.obj;*.bvh;*.stl;*.ply;*.abc;*.usd;*.usdz;*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.mp4;*.mov;*.avi;*.mkv;*.exr;*.hdr", options={{"HIDDEN"}})

    def execute(self, context):
        data = _load_meta()
        result_type = str(getattr(context.scene, "gpt_director_ai_result_type", "auto") or "auto")
        task_id = _active_ai_task_id(context.scene)
        note = _active_ai_result_note(context.scene)
        try:
            result, payload = _register_ai_workflow_result(data, self.filepath, result_type, task_id, note)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _save_meta(data)
        try:
            if result.get("target_type") == "asset" and payload.get("id"):
                context.scene.gpt_director_asset_choice = payload.get("id")
            if result.get("task_id"):
                context.scene.gpt_director_ai_task_id = result.get("task_id")
        except Exception:
            pass
        self.report({{"INFO"}}, "AI生成结果已登记：" + str(result.get("payload_name") or os.path.basename(self.filepath)))
        return {{"FINISHED"}}


class GPT_OT_director_register_ai_workflow_result_directory(bpy.types.Operator):
    bl_idname = "gpt_director.register_ai_workflow_result_directory"
    bl_label = "批量登记AI结果目录"
    bl_options = {{"REGISTER", "UNDO"}}

    directory: StringProperty(name="AI结果目录", default="", subtype="DIR_PATH")
    recursive: BoolProperty(name="递归扫描", default=False)

    def invoke(self, context, event):
        self.directory = str(getattr(context.scene, "gpt_director_ai_result_directory", "") or "")
        self.recursive = bool(getattr(context.scene, "gpt_director_ai_result_recursive", False))
        context.window_manager.fileselect_add(self)
        return {{"RUNNING_MODAL"}}

    def execute(self, context):
        directory = str(self.directory or getattr(context.scene, "gpt_director_ai_result_directory", "") or "").strip()
        if not directory or not os.path.isdir(directory):
            self.report({{"ERROR"}}, "AI结果目录不存在")
            return {{"CANCELLED"}}
        data = _load_meta()
        result_type = str(getattr(context.scene, "gpt_director_ai_result_type", "auto") or "auto")
        fallback_task_id = _active_ai_task_id(context.scene)
        note = _active_ai_result_note(context.scene)
        recursive = bool(getattr(context.scene, "gpt_director_ai_result_recursive", False) or self.recursive)
        paths = []
        if recursive:
            for root, dirs, files in os.walk(directory):
                dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git"))
                for name in sorted(files):
                    path = os.path.join(root, name)
                    if path.lower().endswith(AI_RESULT_EXTENSIONS):
                        paths.append(path)
        else:
            for name in sorted(os.listdir(directory)):
                path = os.path.join(directory, name)
                if os.path.isfile(path) and path.lower().endswith(AI_RESULT_EXTENSIONS):
                    paths.append(path)
        if not paths:
            self.report({{"ERROR"}}, "目录里没有可登记的AI结果文件")
            return {{"CANCELLED"}}
        registered = 0
        failed = 0
        last_asset_id = ""
        for path in paths:
            task_id = _ai_result_task_id_from_path(data, path, fallback_task_id)
            try:
                result, payload = _register_ai_workflow_result(data, path, result_type, task_id, note)
            except Exception:
                failed += 1
                continue
            registered += 1
            if result.get("target_type") == "asset" and payload.get("id"):
                last_asset_id = str(payload.get("id") or "")
        _save_meta(data)
        try:
            context.scene.gpt_director_ai_result_directory = directory
            if last_asset_id:
                context.scene.gpt_director_asset_choice = last_asset_id
        except Exception:
            pass
        if registered:
            self.report({{"INFO"}}, "批量登记AI结果：" + str(registered) + " 个" + (("，失败 " + str(failed)) if failed else ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "AI结果登记失败：" + str(failed) + " 个")
        return {{"CANCELLED"}}


class GPT_OT_director_select_asset(bpy.types.Operator):
    bl_idname = "gpt_director.select_asset"
    bl_label = "选中工程资产"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = str(getattr(context.scene, "gpt_director_asset_choice", "") or "").strip()
        asset = _find_asset(data, key)
        if not asset:
            self.report({{"ERROR"}}, "没有找到工程资产，请先导入资产或选择列表里的资产")
            return {{"CANCELLED"}}
        count = _select_asset_objects(asset)
        if count:
            self.report({{"INFO"}}, "已选中资产对象：" + str(count) + " 个")
            return {{"FINISHED"}}
        if asset.get("type") == "action":
            self.report({{"INFO"}}, "已选中动作资产，可套用到当前骨骼")
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "资产记录里没有可选中的对象")
        return {{"CANCELLED"}}


class GPT_OT_director_apply_action(bpy.types.Operator):
    bl_idname = "gpt_director.apply_action"
    bl_label = "套用动作到选中骨骼"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        actor, target_armature = _active_action_target(data)
        action_name = str(getattr(context.scene, "gpt_director_action_name", "") or "").strip()
        action = _latest_action(action_name)
        ok, message = _apply_action_to_armature(target_armature, action)
        _record_action_application(
            data,
            target_armature.name if target_armature else "",
            action.name if action else action_name,
            "applied" if ok else "failed",
            message,
            actor,
        )
        _save_meta(data)
        if ok:
            context.scene.gpt_director_action_name = message
            self.report({{"INFO"}}, "动作已套用：" + message)
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, message)
        return {{"CANCELLED"}}


class GPT_OT_director_build_retarget_profile(bpy.types.Operator):
    bl_idname = "gpt_director.build_retarget_profile"
    bl_label = "建立重定向映射"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        target_armature = _retarget_target_armature(data, context.scene)
        source_armature = _retarget_source_armature(context.scene, target_armature)
        if not source_armature or not target_armature:
            self.report({{"ERROR"}}, "请指定源骨骼和目标骨骼，或同时选中两个骨骼")
            return {{"CANCELLED"}}
        name = _retarget_profile_name()
        profile_id = _safe_id(name + "_" + source_armature.name + "_" + target_armature.name, "retarget_profile")
        try:
            profile = _retarget_profile_from_armatures(
                source_armature,
                target_armature,
                profile_id,
                name,
                _retarget_profile_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_retarget_profile(data, profile)
        _save_meta(data)
        context.scene.gpt_director_selected_retarget_profile = profile_id
        context.scene.gpt_director_retarget_source_armature = source_armature.name
        context.scene.gpt_director_retarget_target_armature = target_armature.name
        try:
            context.scene.gpt_director_retarget_profile_choice = profile_id
        except Exception:
            pass
        self.report(
            {{"INFO"}},
            "重定向映射已建立："
            + str(profile.get("mapped_bone_count") or 0)
            + " 根，源未映射 "
            + str(profile.get("unmapped_source_count") or 0)
            + " 根",
        )
        return {{"FINISHED"}}


class GPT_OT_director_load_retarget_bone_mapping(bpy.types.Operator):
    bl_idname = "gpt_director.load_retarget_bone_mapping"
    bl_label = "读取骨骼映射"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        profile = _find_retarget_profile(data, _active_retarget_profile_key(context.scene))
        row = _retarget_mapping_row(profile, getattr(context.scene, "gpt_director_retarget_bone_mapping_choice", ""))
        if not row:
            self.report({{"ERROR"}}, "请先选择一条骨骼映射")
            return {{"CANCELLED"}}
        context.scene.gpt_director_retarget_source_bone = str(row.get("source") or "")
        context.scene.gpt_director_retarget_target_bone = str(row.get("target") or "")
        self.report({{"INFO"}}, "已读取映射：" + context.scene.gpt_director_retarget_source_bone + " → " + context.scene.gpt_director_retarget_target_bone)
        return {{"FINISHED"}}


class GPT_OT_director_set_retarget_bone_mapping(bpy.types.Operator):
    bl_idname = "gpt_director.set_retarget_bone_mapping"
    bl_label = "保存骨骼映射"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        profile = _find_retarget_profile(data, _active_retarget_profile_key(context.scene))
        if not profile:
            self.report({{"ERROR"}}, "请先建立或选择一个重定向档案")
            return {{"CANCELLED"}}
        source_armature = _armature_by_name(profile.get("source_armature"))
        target_armature = _armature_by_name(profile.get("target_armature"))
        source_name = str(getattr(context.scene, "gpt_director_retarget_source_bone", "") or "").strip()
        target_name = str(getattr(context.scene, "gpt_director_retarget_target_bone", "") or "").strip()
        if not source_armature or not source_armature.data.bones.get(source_name):
            self.report({{"ERROR"}}, "源骨骼不存在：" + (source_name or "未填写"))
            return {{"CANCELLED"}}
        if not target_armature or not target_armature.data.bones.get(target_name):
            self.report({{"ERROR"}}, "目标骨骼不存在：" + (target_name or "未填写"))
            return {{"CANCELLED"}}
        bone_map = profile.get("bone_map") if isinstance(profile.get("bone_map"), list) else []
        kept = []
        for row in bone_map:
            if not isinstance(row, dict):
                continue
            if str(row.get("source") or "") == source_name or str(row.get("target") or "") == target_name:
                continue
            kept.append(row)
        kept.append({{
            "source": source_name,
            "target": target_name,
            "role": _bone_role(source_name),
            "confidence": 1.0,
            "method": "手动覆盖",
        }})
        profile["bone_map"] = kept
        profile["root_motion"] = {{
            "enabled": bool(getattr(context.scene, "gpt_director_retarget_root_motion_enabled", True)),
            "manual_scale": float(getattr(context.scene, "gpt_director_retarget_root_motion_scale", 1.0) or 1.0),
        }}
        profile["rest_pose_alignment"] = {{
            "enabled": bool(getattr(context.scene, "gpt_director_retarget_rest_pose_enabled", True)),
            "bake_step": int(getattr(context.scene, "gpt_director_retarget_bake_step", 1) or 1),
        }}
        profile = _refresh_retarget_profile_stats(profile, source_armature, target_armature)
        profile["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _upsert_retarget_profile(data, profile)
        _save_meta(data)
        context.scene.gpt_director_retarget_bone_mapping_choice = "__none__"
        self.report({{"INFO"}}, "骨骼映射已保存：" + source_name + " → " + target_name)
        return {{"FINISHED"}}


class GPT_OT_director_remove_retarget_bone_mapping(bpy.types.Operator):
    bl_idname = "gpt_director.remove_retarget_bone_mapping"
    bl_label = "删除骨骼映射"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        profile = _find_retarget_profile(data, _active_retarget_profile_key(context.scene))
        row = _retarget_mapping_row(profile, getattr(context.scene, "gpt_director_retarget_bone_mapping_choice", ""))
        source_name = str(getattr(context.scene, "gpt_director_retarget_source_bone", "") or "").strip()
        if row:
            source_name = str(row.get("source") or source_name)
        if not profile or not source_name:
            self.report({{"ERROR"}}, "请选择映射或填写要删除的源骨骼")
            return {{"CANCELLED"}}
        bone_map = profile.get("bone_map") if isinstance(profile.get("bone_map"), list) else []
        kept = [item for item in bone_map if not isinstance(item, dict) or str(item.get("source") or "") != source_name]
        if len(kept) == len(bone_map):
            self.report({{"ERROR"}}, "没有找到对应骨骼映射")
            return {{"CANCELLED"}}
        source_armature = _armature_by_name(profile.get("source_armature"))
        target_armature = _armature_by_name(profile.get("target_armature"))
        profile["bone_map"] = kept
        profile = _refresh_retarget_profile_stats(profile, source_armature, target_armature)
        profile["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _upsert_retarget_profile(data, profile)
        _save_meta(data)
        context.scene.gpt_director_retarget_bone_mapping_choice = "__none__"
        context.scene.gpt_director_retarget_source_bone = ""
        context.scene.gpt_director_retarget_target_bone = ""
        self.report({{"INFO"}}, "骨骼映射已删除：" + source_name)
        return {{"FINISHED"}}


class GPT_OT_director_apply_retarget_profile(bpy.types.Operator):
    bl_idname = "gpt_director.apply_retarget_profile"
    bl_label = "应用重定向动作"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        target_armature = _retarget_target_armature(data, context.scene)
        source_armature = _retarget_source_armature(context.scene, target_armature)
        key = _active_retarget_profile_key(context.scene)
        profile = _find_retarget_profile(data, key)
        if not profile:
            if not source_armature or not target_armature:
                self.report({{"ERROR"}}, "没有找到重定向档案，请先指定源骨骼和目标骨骼")
                return {{"CANCELLED"}}
            profile_id = _safe_id(_retarget_profile_name() + "_" + source_armature.name + "_" + target_armature.name, "retarget_profile")
            profile = _retarget_profile_from_armatures(source_armature, target_armature, profile_id, _retarget_profile_name(), _retarget_profile_note())
            _upsert_retarget_profile(data, profile)
        if source_armature is None:
            source_armature = _armature_by_name(profile.get("source_armature"))
        if target_armature is None:
            target_armature = _armature_by_name(profile.get("target_armature"))
        root_motion = profile.get("root_motion") if isinstance(profile.get("root_motion"), dict) else {{}}
        root_motion = dict(root_motion)
        root_motion["enabled"] = bool(getattr(context.scene, "gpt_director_retarget_root_motion_enabled", root_motion.get("enabled", True)))
        root_motion["manual_scale"] = float(getattr(context.scene, "gpt_director_retarget_root_motion_scale", root_motion.get("manual_scale", 1.0)) or 1.0)
        profile["root_motion"] = root_motion
        rest_pose = profile.get("rest_pose_alignment") if isinstance(profile.get("rest_pose_alignment"), dict) else {{}}
        rest_pose = dict(rest_pose)
        rest_pose["enabled"] = bool(getattr(context.scene, "gpt_director_retarget_rest_pose_enabled", rest_pose.get("enabled", True)))
        rest_pose["bake_step"] = int(getattr(context.scene, "gpt_director_retarget_bake_step", rest_pose.get("bake_step", 1)) or 1)
        profile["rest_pose_alignment"] = rest_pose
        profile = _refresh_retarget_profile_stats(profile, source_armature, target_armature)
        _upsert_retarget_profile(data, profile)
        action_name = str(getattr(context.scene, "gpt_director_action_name", "") or "").strip()
        source_action = _latest_action(action_name) or _action_from_armature(source_armature)
        try:
            target_action, copied, skipped = _retarget_action_to_armature(source_action, source_armature, target_armature, profile)
        except Exception as exc:
            _record_retarget_application(data, profile, source_action, None, source_armature, target_armature, "failed", str(exc))
            _save_meta(data)
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        actor, actor_target = _active_action_target(data)
        if actor_target is None or target_armature is None or actor_target.name != target_armature.name:
            actor = {{}}
        action_clip = _upsert_retarget_action_clip(
            data,
            profile,
            source_action,
            target_action,
            target_armature,
            actor,
            copied,
            skipped,
        )
        match_data = _refresh_action_matches(data)
        _record_retarget_application(
            data,
            profile,
            source_action,
            target_action,
            source_armature,
            target_armature,
            "applied",
            "已复制 "
            + str(copied)
            + " 条动作曲线，跳过 "
            + str(skipped)
            + " 条，根运动比例 "
            + ("%.3f" % _retarget_motion_scale(source_armature, target_armature, profile)),
            copied,
            skipped,
            action_clip,
            match_data,
        )
        _save_meta(data)
        context.scene.gpt_director_action_name = target_action.name
        context.scene.gpt_director_action_clip_name = str(action_clip.get("name") or "")
        context.scene.gpt_director_action_clip_note = str(action_clip.get("note") or "")
        context.scene.gpt_director_selected_action_clip = str(action_clip.get("id") or "")
        context.scene.gpt_director_selected_retarget_profile = str(profile.get("id") or "")
        try:
            context.scene.gpt_director_retarget_profile_choice = str(profile.get("id") or "__manual__")
        except Exception:
            pass
        try:
            context.scene.gpt_director_action_clip_choice = str(action_clip.get("id") or "__manual__")
        except Exception:
            pass
        self.report(
            {{"INFO"}},
            "重定向动作已应用："
            + target_action.name
            + "，复制 "
            + str(copied)
            + " 条曲线，根运动比例 "
            + ("%.3f" % _retarget_motion_scale(source_armature, target_armature, profile))
            + "，动作匹配 "
            + str(match_data.get("matched_count") or 0)
            + "/"
            + str(match_data.get("requirement_count") or 0),
        )
        return {{"FINISHED"}}


class GPT_OT_director_delete_retarget_profile(bpy.types.Operator):
    bl_idname = "gpt_director.delete_retarget_profile"
    bl_label = "删除重定向映射"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        profile = _find_retarget_profile(data, _active_retarget_profile_key(context.scene))
        if not profile:
            self.report({{"ERROR"}}, "没有找到要删除的重定向档案")
            return {{"CANCELLED"}}
        removed = _delete_retarget_profile(data, profile)
        _save_meta(data)
        context.scene.gpt_director_selected_retarget_profile = ""
        try:
            context.scene.gpt_director_retarget_profile_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "重定向档案已删除：" + str(profile.get("name") or profile.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "重定向档案删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_save_action_clip(bpy.types.Operator):
    bl_idname = "gpt_director.save_action_clip"
    bl_label = "保存动作片段"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        actor, target_armature = _active_action_target(data)
        action_name = str(getattr(context.scene, "gpt_director_action_name", "") or "").strip()
        action = _latest_action(action_name) or _action_from_armature(target_armature)
        name = _active_action_clip_name()
        clip_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "action_clip")
        try:
            clip = _action_clip_from_action(
                action,
                target_armature,
                clip_id,
                name,
                _active_action_clip_note(),
                actor,
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_action_clip(data, clip)
        _save_meta(data)
        context.scene.gpt_director_selected_action_clip = clip_id
        try:
            context.scene.gpt_director_action_clip_choice = clip_id
        except Exception:
            pass
        self.report({{"INFO"}}, "动作片段已保存：" + name + "，帧 " + str(clip.get("frame_start") or "") + "-" + str(clip.get("frame_end") or ""))
        return {{"FINISHED"}}


class GPT_OT_director_update_action_clip(bpy.types.Operator):
    bl_idname = "gpt_director.update_action_clip"
    bl_label = "更新动作片段"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_action_clip_key(context.scene)
        existing = _find_action_clip(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的动作片段，请先从动作片段列表选择一个片段")
            return {{"CANCELLED"}}
        actor, target_armature = _active_action_target(data)
        action_name = str(getattr(context.scene, "gpt_director_action_name", "") or "").strip()
        action = _latest_action(action_name) or _action_from_armature(target_armature)
        clip_id = str(existing.get("id") or key or _safe_id(_active_action_clip_name(), "action_clip"))
        try:
            clip = _action_clip_from_action(
                action,
                target_armature,
                clip_id,
                _active_action_clip_name(),
                _active_action_clip_note(),
                actor,
                existing,
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_action_clip(data, clip)
        _save_meta(data)
        context.scene.gpt_director_selected_action_clip = clip_id
        try:
            context.scene.gpt_director_action_clip_choice = clip_id
        except Exception:
            pass
        self.report({{"INFO"}}, "动作片段已更新：" + clip.get("name", clip_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_action_clip(bpy.types.Operator):
    bl_idname = "gpt_director.delete_action_clip"
    bl_label = "删除动作片段"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_action_clip_key(context.scene)
        clip = _find_action_clip(data, key)
        if not clip:
            self.report({{"ERROR"}}, "没有找到要删除的动作片段")
            return {{"CANCELLED"}}
        removed = _delete_action_clip(data, clip)
        _save_meta(data)
        context.scene.gpt_director_selected_action_clip = ""
        try:
            context.scene.gpt_director_action_clip_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "动作片段已删除：" + str(clip.get("name") or clip.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "动作片段删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_action_clip(bpy.types.Operator):
    bl_idname = "gpt_director.load_action_clip"
    bl_label = "加载动作片段"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_action_clip_key(context.scene)
        clip = _find_action_clip(data, key)
        if not clip:
            self.report({{"ERROR"}}, "没有找到动作片段，请输入片段名或片段ID")
            return {{"CANCELLED"}}
        try:
            target_armature, action, message = _apply_action_clip(context, data, clip)
        except Exception as exc:
            _save_meta(data)
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _save_meta(data)
        context.scene.gpt_director_action_name = action.name if action else str(clip.get("action") or "")
        context.scene.gpt_director_action_clip_name = str(clip.get("name") or clip.get("id") or "")
        context.scene.gpt_director_action_clip_note = str(clip.get("note") or "")
        context.scene.gpt_director_selected_action_clip = str(clip.get("id") or clip.get("name") or "")
        try:
            context.scene.gpt_director_action_clip_choice = str(clip.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载动作片段：" + context.scene.gpt_director_action_clip_name + "，骨骼 " + (target_armature.name if target_armature else "") + "，" + message)
        return {{"FINISHED"}}


class GPT_OT_director_refresh_action_matches(bpy.types.Operator):
    bl_idname = "gpt_director.refresh_action_matches"
    bl_label = "刷新动作匹配"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        match_data = _refresh_action_matches(data)
        _save_meta(data)
        self.report(
            {{"INFO"}},
            "动作匹配已刷新："
            + str(match_data.get("matched_count") or 0)
            + "/"
            + str(match_data.get("requirement_count") or 0)
            + " 已匹配，待补 "
            + str(match_data.get("unmatched_count") or 0),
        )
        return {{"FINISHED"}}


class GPT_OT_director_apply_shot_action_match(bpy.types.Operator):
    bl_idname = "gpt_director.apply_shot_action_match"
    bl_label = "应用镜头匹配动作"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        requirement = _active_shot_action_requirement(data, context.scene)
        if not requirement:
            _save_meta(data)
            self.report({{"ERROR"}}, "没有找到当前镜头的动作匹配，请先保存镜头并刷新动作匹配")
            return {{"CANCELLED"}}
        best = requirement.get("best_match") if isinstance(requirement.get("best_match"), dict) else {{}}
        if not best:
            _save_meta(data)
            self.report({{"ERROR"}}, "当前镜头还没有可用动作，请先导入或保存动作片段")
            return {{"CANCELLED"}}
        origin = str(best.get("origin") or "")
        actor_ref = requirement.get("actor") if isinstance(requirement.get("actor"), dict) else {{}}
        actor_key = str(actor_ref.get("id") or actor_ref.get("name") or "").strip()
        actor = _find_actor(data, actor_key) if actor_key else {{}}
        target_armature = _armature_from_actor(actor) if actor else None
        if target_armature is None:
            actor, target_armature = _active_action_target(data)
        if origin == "action_clip":
            clip = _find_action_clip(data, str(best.get("id") or best.get("name") or best.get("action") or ""))
            if not clip:
                _save_meta(data)
                self.report({{"ERROR"}}, "没有找到匹配的工程动作片段：" + str(best.get("name") or best.get("id") or ""))
                return {{"CANCELLED"}}
        else:
            source_path = str(best.get("path") or "").strip()
            if not source_path or not os.path.exists(source_path):
                _save_meta(data)
                self.report({{"ERROR"}}, "最佳候选来自" + str(best.get("origin_label") or "动作库") + "，但本地动作文件不存在，请先导入并保存为工程动作片段")
                return {{"CANCELLED"}}
            try:
                imported = _import_director_asset(
                    source_path,
                    "action",
                    str(best.get("name") or os.path.basename(source_path) or "匹配动作"),
                    target_armature,
                )
                _append_asset_record(data, imported)
                clip = _upsert_action_clip_from_asset_record(
                    data,
                    imported,
                    actor,
                    target_armature,
                    best,
                    "来自镜头动作匹配：" + str(requirement.get("query") or ""),
                )
            except Exception as exc:
                _save_meta(data)
                self.report({{"ERROR"}}, "导入匹配动作失败：" + str(exc))
                return {{"CANCELLED"}}
            if not clip:
                _save_meta(data)
                self.report({{"ERROR"}}, "匹配动作已导入，但没有生成可应用的动作片段")
                return {{"CANCELLED"}}
        clip = dict(clip)
        if actor_ref and not isinstance(clip.get("actor"), dict):
            clip["actor"] = actor_ref
        clip["shot_action_match"] = {{
            "shot_id": str(requirement.get("shot_id") or ""),
            "shot_name": str(requirement.get("shot_name") or ""),
            "score": best.get("score"),
            "reasons": best.get("reasons") if isinstance(best.get("reasons"), list) else [],
        }}
        try:
            target_armature, action, message = _apply_action_clip(context, data, clip)
        except Exception as exc:
            _save_meta(data)
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        shot = _find_shot(data, str(requirement.get("shot_id") or requirement.get("shot_name") or ""))
        if shot:
            shot["action_match_status"] = "applied"
            shot["matched_action_clip"] = {{
                "id": str(clip.get("id") or ""),
                "name": str(clip.get("name") or ""),
                "action": action.name if action else str(clip.get("action") or ""),
                "score": best.get("score"),
                "source_profile_name": str(clip.get("source_profile_name") or best.get("source_profile_name") or ""),
                "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }}
            _upsert_shot(data, shot)
            _save_shot_file(shot)
        _refresh_action_matches(data)
        _save_meta(data)
        context.scene.gpt_director_action_name = action.name if action else str(clip.get("action") or "")
        context.scene.gpt_director_action_clip_name = str(clip.get("name") or clip.get("id") or "")
        context.scene.gpt_director_action_clip_note = str(clip.get("note") or "")
        context.scene.gpt_director_selected_action_clip = str(clip.get("id") or clip.get("name") or "")
        try:
            context.scene.gpt_director_action_clip_choice = str(clip.get("id") or "__manual__")
        except Exception:
            pass
        self.report(
            {{"INFO"}},
            "已应用镜头动作："
            + str(requirement.get("shot_name") or "")
            + " → "
            + str(clip.get("name") or clip.get("action") or "")
            + "，骨骼 "
            + (target_armature.name if target_armature else "")
            + "，"
            + message,
        )
        return {{"FINISHED"}}


class GPT_OT_director_save_pose_template(bpy.types.Operator):
    bl_idname = "gpt_director.save_pose_template"
    bl_label = "保存姿势模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        armature = _active_armature()
        name = _active_pose_template_name()
        template_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "pose_template")
        try:
            template = _pose_template_from_armature(
                armature,
                template_id,
                name,
                _active_pose_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        data = _load_meta()
        _upsert_pose_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_pose_template = template_id
        try:
            context.scene.gpt_director_pose_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "姿势模板已保存：" + name + "，骨骼 " + str(template.get("bone_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_update_pose_template(bpy.types.Operator):
    bl_idname = "gpt_director.update_pose_template"
    bl_label = "更新姿势模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_pose_template_key(context.scene)
        existing = _find_pose_template(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的姿势模板，请先从姿势模板列表选择一个模板")
            return {{"CANCELLED"}}
        armature = _active_armature()
        template_id = str(existing.get("id") or key or _safe_id(_active_pose_template_name(), "pose_template"))
        try:
            template = _pose_template_from_armature(
                armature,
                template_id,
                _active_pose_template_name(),
                _active_pose_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_pose_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_pose_template = template_id
        try:
            context.scene.gpt_director_pose_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "姿势模板已更新：" + template.get("name", template_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_pose_template(bpy.types.Operator):
    bl_idname = "gpt_director.delete_pose_template"
    bl_label = "删除姿势模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_pose_template_key(context.scene)
        template = _find_pose_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到要删除的姿势模板")
            return {{"CANCELLED"}}
        removed = _delete_pose_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_pose_template = ""
        try:
            context.scene.gpt_director_pose_template_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "姿势模板已删除：" + str(template.get("name") or template.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "姿势模板删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_pose_template(bpy.types.Operator):
    bl_idname = "gpt_director.load_pose_template"
    bl_label = "加载姿势模板"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_pose_template_key(context.scene)
        template = _find_pose_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到姿势模板，请输入模板名或模板ID")
            return {{"CANCELLED"}}
        try:
            armature, applied = _apply_pose_template(context, template)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        context.scene.gpt_director_pose_template_name = str(template.get("name") or template.get("id") or "")
        context.scene.gpt_director_pose_template_note = str(template.get("note") or "")
        context.scene.gpt_director_selected_pose_template = str(template.get("id") or template.get("name") or "")
        try:
            context.scene.gpt_director_pose_template_choice = str(template.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载姿势模板：" + context.scene.gpt_director_pose_template_name + "，" + armature.name + " 应用骨骼 " + str(applied) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_save_animation_template(bpy.types.Operator):
    bl_idname = "gpt_director.save_animation_template"
    bl_label = "保存动画片段"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        name = _active_animation_template_name()
        template_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "animation_template")
        try:
            template = _animation_template_from_selected_objects(
                context,
                template_id,
                name,
                _active_animation_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        data = _load_meta()
        _upsert_animation_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_animation_template = template_id
        try:
            context.scene.gpt_director_animation_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "动画片段已保存：" + name + "，关键帧 " + str(template.get("keyframe_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_update_animation_template(bpy.types.Operator):
    bl_idname = "gpt_director.update_animation_template"
    bl_label = "更新动画片段"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_animation_template_key(context.scene)
        existing = _find_animation_template(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的动画片段，请先从动画片段列表选择一个模板")
            return {{"CANCELLED"}}
        template_id = str(existing.get("id") or key or _safe_id(_active_animation_template_name(), "animation_template"))
        try:
            template = _animation_template_from_selected_objects(
                context,
                template_id,
                _active_animation_template_name(),
                _active_animation_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_animation_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_animation_template = template_id
        try:
            context.scene.gpt_director_animation_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "动画片段已更新：" + template.get("name", template_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_animation_template(bpy.types.Operator):
    bl_idname = "gpt_director.delete_animation_template"
    bl_label = "删除动画片段"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_animation_template_key(context.scene)
        template = _find_animation_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到要删除的动画片段")
            return {{"CANCELLED"}}
        removed = _delete_animation_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_animation_template = ""
        try:
            context.scene.gpt_director_animation_template_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "动画片段已删除：" + str(template.get("name") or template.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "动画片段删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_animation_template(bpy.types.Operator):
    bl_idname = "gpt_director.load_animation_template"
    bl_label = "加载动画片段"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_animation_template_key(context.scene)
        template = _find_animation_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到动画片段，请输入模板名或模板ID")
            return {{"CANCELLED"}}
        try:
            applied_objects, inserted_keyframes = _apply_animation_template(context, template)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        context.scene.gpt_director_animation_template_name = str(template.get("name") or template.get("id") or "")
        context.scene.gpt_director_animation_template_note = str(template.get("note") or "")
        context.scene.gpt_director_selected_animation_template = str(template.get("id") or template.get("name") or "")
        try:
            context.scene.gpt_director_animation_template_choice = str(template.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载动画片段：" + context.scene.gpt_director_animation_template_name + "，对象 " + str(applied_objects) + " 个，关键帧 " + str(inserted_keyframes) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_save_material_template(bpy.types.Operator):
    bl_idname = "gpt_director.save_material_template"
    bl_label = "保存材质模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        name = _active_material_template_name()
        template_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "material_template")
        try:
            template = _material_template_from_selected_objects(
                context,
                template_id,
                name,
                _active_material_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        data = _load_meta()
        _upsert_material_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_material_template = template_id
        try:
            context.scene.gpt_director_material_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "材质模板已保存：" + name + "，材质 " + str(template.get("material_count") or 0) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_update_material_template(bpy.types.Operator):
    bl_idname = "gpt_director.update_material_template"
    bl_label = "更新材质模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_material_template_key(context.scene)
        existing = _find_material_template(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的材质模板，请先从材质模板列表选择一个模板")
            return {{"CANCELLED"}}
        template_id = str(existing.get("id") or key or _safe_id(_active_material_template_name(), "material_template"))
        try:
            template = _material_template_from_selected_objects(
                context,
                template_id,
                _active_material_template_name(),
                _active_material_template_note(),
            )
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        _upsert_material_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_material_template = template_id
        try:
            context.scene.gpt_director_material_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "材质模板已更新：" + template.get("name", template_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_material_template(bpy.types.Operator):
    bl_idname = "gpt_director.delete_material_template"
    bl_label = "删除材质模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_material_template_key(context.scene)
        template = _find_material_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到要删除的材质模板")
            return {{"CANCELLED"}}
        removed = _delete_material_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_material_template = ""
        try:
            context.scene.gpt_director_material_template_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "材质模板已删除：" + str(template.get("name") or template.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "材质模板删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_material_template(bpy.types.Operator):
    bl_idname = "gpt_director.load_material_template"
    bl_label = "加载材质模板"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_material_template_key(context.scene)
        template = _find_material_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到材质模板，请输入模板名或模板ID")
            return {{"CANCELLED"}}
        try:
            applied_objects, applied_materials = _apply_material_template(context, template)
        except Exception as exc:
            self.report({{"ERROR"}}, str(exc))
            return {{"CANCELLED"}}
        context.scene.gpt_director_material_template_name = str(template.get("name") or template.get("id") or "")
        context.scene.gpt_director_material_template_note = str(template.get("note") or "")
        context.scene.gpt_director_selected_material_template = str(template.get("id") or template.get("name") or "")
        try:
            context.scene.gpt_director_material_template_choice = str(template.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载材质模板：" + context.scene.gpt_director_material_template_name + "，对象 " + str(applied_objects) + " 个，材质 " + str(applied_materials) + " 个")
        return {{"FINISHED"}}


class GPT_OT_director_save_render_template(bpy.types.Operator):
    bl_idname = "gpt_director.save_render_template"
    bl_label = "保存渲染模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        name = _active_render_template_name()
        template_id = _safe_id(name + "_" + datetime.now().strftime("%H%M%S"), "render_template")
        template = _render_template_from_scene(
            context.scene,
            template_id,
            name,
            _active_render_template_note(),
        )
        _upsert_render_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_render_template = template_id
        try:
            context.scene.gpt_director_render_template_choice = template_id
        except Exception:
            pass
        label = str(template.get("output_label") or template.get("output_type") or "")
        self.report({{"INFO"}}, "渲染模板已保存：" + name + (("，" + label) if label else ""))
        return {{"FINISHED"}}


class GPT_OT_director_update_render_template(bpy.types.Operator):
    bl_idname = "gpt_director.update_render_template"
    bl_label = "更新渲染模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_render_template_key(context.scene)
        existing = _find_render_template(data, key)
        if not existing:
            self.report({{"ERROR"}}, "没有找到要更新的渲染模板，请先从渲染模板列表选择一个模板")
            return {{"CANCELLED"}}
        template_id = str(existing.get("id") or key or _safe_id(_active_render_template_name(), "render_template"))
        template = _render_template_from_scene(
            context.scene,
            template_id,
            _active_render_template_name(),
            _active_render_template_note(),
        )
        _upsert_render_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_render_template = template_id
        try:
            context.scene.gpt_director_render_template_choice = template_id
        except Exception:
            pass
        self.report({{"INFO"}}, "渲染模板已更新：" + template.get("name", template_id))
        return {{"FINISHED"}}


class GPT_OT_director_delete_render_template(bpy.types.Operator):
    bl_idname = "gpt_director.delete_render_template"
    bl_label = "删除渲染模板"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_render_template_key(context.scene)
        template = _find_render_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到要删除的渲染模板")
            return {{"CANCELLED"}}
        removed = _delete_render_template(data, template)
        _save_meta(data)
        context.scene.gpt_director_selected_render_template = ""
        try:
            context.scene.gpt_director_render_template_choice = "__manual__"
        except Exception:
            pass
        if removed:
            self.report({{"INFO"}}, "渲染模板已删除：" + str(template.get("name") or template.get("id") or ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "渲染模板删除失败")
        return {{"CANCELLED"}}


class GPT_OT_director_load_render_template(bpy.types.Operator):
    bl_idname = "gpt_director.load_render_template"
    bl_label = "加载渲染模板"
    bl_options = {{"REGISTER", "UNDO"}}

    def execute(self, context):
        data = _load_meta()
        key = _active_render_template_key(context.scene)
        template = _find_render_template(data, key)
        if not template:
            self.report({{"ERROR"}}, "没有找到渲染模板，请输入模板名或模板ID")
            return {{"CANCELLED"}}
        _apply_render_template(context.scene, template)
        context.scene.gpt_director_render_template_name = str(template.get("name") or template.get("id") or "")
        context.scene.gpt_director_render_template_note = str(template.get("note") or "")
        context.scene.gpt_director_selected_render_template = str(template.get("id") or template.get("name") or "")
        try:
            context.scene.gpt_director_render_template_choice = str(template.get("id") or "__manual__")
        except Exception:
            pass
        self.report({{"INFO"}}, "已加载渲染模板：" + context.scene.gpt_director_render_template_name)
        return {{"FINISHED"}}


class GPT_OT_director_save_metadata(bpy.types.Operator):
    bl_idname = "gpt_director.save_metadata"
    bl_label = "保存分镜数据"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        _ensure_independent_mannequin_instances()
        data = _load_meta()
        objects = []
        for obj in bpy.context.scene.objects:
            objects.append({{
                "name": obj.name,
                "type": obj.type,
                "location": [round(v, 4) for v in obj.location],
                "rotation": [round(v, 4) for v in obj.rotation_euler],
                "scale": [round(v, 4) for v in obj.scale],
            }})
        data["last_saved_from_blender"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["scene_objects"] = objects
        data["active_camera"] = bpy.context.scene.camera.name if bpy.context.scene.camera else ""
        data["frame_current"] = int(bpy.context.scene.frame_current)
        data["active_shot_name"] = _active_shot_name()
        data["active_shot_note"] = _active_shot_note()
        _save_meta(data)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
        except Exception:
            bpy.ops.wm.save_mainfile()
        self.report({{"INFO"}}, "导演台工程与分镜数据已保存")
        return {{"FINISHED"}}


class GPT_OT_director_render_current(bpy.types.Operator):
    bl_idname = "gpt_director.render_current"
    bl_label = "渲染当前镜头"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        scene = bpy.context.scene
        data = _load_meta()
        shot_name = _active_shot_name()
        selected_key = str(getattr(scene, "gpt_director_selected_shot", "") or "").strip()
        existing_shot = _find_shot(data, selected_key) if selected_key else {{}}
        shot_id = str(existing_shot.get("id") or "").strip() or _safe_id(shot_name, "shot")
        shot = _shot_from_current_scene(scene, shot_id, shot_name, _active_shot_note())
        path = _render_saved_shot(context, data, shot, "current")
        _save_meta(data)
        self.report({{"INFO"}}, "当前镜头已渲染：" + path)
        return {{"FINISHED"}}


class GPT_OT_director_render_all_shots(bpy.types.Operator):
    bl_idname = "gpt_director.render_all_shots"
    bl_label = "批量渲染所有镜头"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        shots = data.get("shots") if isinstance(data.get("shots"), list) else []
        valid_shots = [shot for shot in shots if isinstance(shot, dict) and (shot.get("id") or shot.get("name"))]
        if not valid_shots:
            self.report({{"ERROR"}}, "还没有保存镜头，请先保存至少一个镜头")
            return {{"CANCELLED"}}
        rendered = 0
        failed = 0
        for shot in valid_shots:
            try:
                path = _render_saved_shot(context, data, shot, "batch")
                if path:
                    rendered += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                print("GPT_DIRECTOR_BATCH_RENDER_FAILED", shot.get("id") or shot.get("name"), exc)
        _save_meta(data)
        if rendered:
            self.report({{"INFO"}}, "批量渲染完成：" + str(rendered) + " 个镜头" + (("，失败 " + str(failed) + " 个") if failed else ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "批量渲染失败，请检查镜头和相机设置")
        return {{"CANCELLED"}}


class GPT_OT_director_render_pending_shots(bpy.types.Operator):
    bl_idname = "gpt_director.render_pending_shots"
    bl_label = "批量渲染待渲染镜头"
    bl_options = {{"REGISTER"}}

    def execute(self, context):
        data = _load_meta()
        shots = data.get("shots") if isinstance(data.get("shots"), list) else []
        renders = data.get("renders") if isinstance(data.get("renders"), list) else []
        rendered_shot_ids = set()
        for render in renders:
            if not isinstance(render, dict):
                continue
            shot_id = str(render.get("shot_id") or "").strip()
            has_output = bool(render.get("path") or render.get("preview_path") or render.get("output_path") or render.get("created_at"))
            if shot_id and has_output:
                rendered_shot_ids.add(shot_id)
        valid_shots = []
        for shot in shots:
            if not isinstance(shot, dict) or not (shot.get("id") or shot.get("name")):
                continue
            shot_id = str(shot.get("id") or "").strip()
            if shot_id and shot_id in rendered_shot_ids:
                continue
            valid_shots.append(shot)
        if not valid_shots:
            self.report({{"INFO"}}, "没有待渲染镜头")
            return {{"CANCELLED"}}
        rendered = 0
        failed = 0
        for shot in valid_shots:
            try:
                path = _render_saved_shot(context, data, shot, "pending")
                if path:
                    rendered += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                print("GPT_DIRECTOR_PENDING_RENDER_FAILED", shot.get("id") or shot.get("name"), exc)
        _save_meta(data)
        if rendered:
            self.report({{"INFO"}}, "待渲染镜头已完成：" + str(rendered) + " 个" + (("，失败 " + str(failed) + " 个") if failed else ""))
            return {{"FINISHED"}}
        self.report({{"ERROR"}}, "待渲染镜头渲染失败")
        return {{"CANCELLED"}}


def _draw_director_quick_controls(layout, context):
    layout.operator("gpt_director.add_dialogue_lounge_scene", text="一键生成双人对话场", icon="SCENE_DATA")
    row = layout.row(align=True)
    row.operator("gpt_director.add_room_set", text="房间")
    row.operator("gpt_director.add_street_set", text="街道")
    row.operator("gpt_director.add_stage_set", text="舞台")

    layout.label(text="人物与家具")
    row = layout.row(align=True)
    row.operator("gpt_director.add_blue_mannequin", text="蓝色人偶")
    row.operator("gpt_director.add_red_mannequin", text="红色人偶")
    row = layout.row(align=True)
    row.operator("gpt_director.add_sofa_set", text="沙发茶几")
    row.operator("gpt_director.add_round_table", text="圆桌")

    control_box = layout.box()
    control_box.operator("gpt_director.set_simple_view", text="隐藏所有控制线")
    control_box.label(text="当前人物：" + str(context.scene.gpt_director_active_character_name or "请在画面中点选"))
    control_box.label(text="人物姿势")
    row = control_box.row(align=True)
    for pose_id, pose_label in (("standing", "站立"), ("seated", "坐下"), ("walking", "行走")):
        op = row.operator("gpt_director.apply_quick_pose", text=pose_label, depress=context.scene.gpt_director_active_pose == pose_id)
        op.pose = pose_id
    row = control_box.row(align=True)
    for pose_id, pose_label in (("running", "跑步"), ("waving", "招手"), ("reclining", "斜躺")):
        op = row.operator("gpt_director.apply_quick_pose", text=pose_label, depress=context.scene.gpt_director_active_pose == pose_id)
        op.pose = pose_id
    control_box.separator()
    control_box.operator(
        "gpt_director.simple_drag_mode",
        text="鼠标拖动已开启" if context.scene.gpt_director_simple_drag_enabled else "开启鼠标拖放位置",
        depress=context.scene.gpt_director_simple_drag_enabled,
    )
    control_box.label(text="模型左拖移动｜Shift+左拖旋转")
    control_box.label(text="空白左拖旋转视角｜右键拖动平移")
    control_box.prop(context.scene, "gpt_director_show_advanced_pose_controls", text="高级姿势精调")
    if context.scene.gpt_director_show_advanced_pose_controls:
        row = control_box.row(align=True)
        op = row.operator("gpt_director.select_mannequin_controls", text="当前人物精调控制器")
        op.asset_id = str(context.scene.gpt_director_active_character_asset_id or "")
        row = control_box.row(align=True)
        op = row.operator("gpt_director.toggle_clean_view", text="清爽视图")
        op.enabled = True
        op = row.operator("gpt_director.toggle_clean_view", text="显示精调线框")
        op.enabled = False

    layout.label(text="镜头")
    row = layout.row(align=True)
    for preset_id, preset_label in (("wide", "远景"), ("medium", "中景"), ("close", "近景"), ("top", "俯拍")):
        op = row.operator("gpt_director.camera_preset", text=preset_label)
        op.preset = preset_id
    row = layout.row(align=True)
    row.operator("gpt_director.save_metadata", text="保存工程")
    row.operator("gpt_director.render_current", text="渲染当前镜头")


class GPT_PT_director_panel(bpy.types.Panel):
    bl_label = "Director 导演台"
    bl_idname = "GPT_PT_director_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Director"

    def draw(self, context):
        layout = self.layout
        layout.label(text="AI 短剧 3D 导演台")
        _draw_director_quick_controls(layout, context)
        layout.separator()
        layout.prop(context.scene, "gpt_director_show_professional_tools", text="专业工程工具")
        if not context.scene.gpt_director_show_professional_tools:
            return
        layout.separator()
        layout.label(text="专业工程设置")
        layout.prop(context.scene, "gpt_director_shot_name", text="镜头名")
        layout.prop(context.scene, "gpt_director_shot_note", text="备注")
        layout.prop(context.scene, "gpt_director_scene_number", text="场次")
        layout.prop(context.scene, "gpt_director_scene_location", text="地点")
        row = layout.row(align=True)
        row.prop(context.scene, "gpt_director_scene_environment", text="内外景")
        row.prop(context.scene, "gpt_director_scene_time", text="日夜")
        layout.prop(context.scene, "gpt_director_shot_status", text="镜头状态")
        layout.operator("gpt_director.init_scene", icon="SCENE_DATA")
        layout.separator()
        layout.operator("gpt_director.add_dialogue_lounge_scene", text="一键影视双人对话场", icon="SCENE_DATA")
        row = layout.row(align=True)
        row.operator("gpt_director.add_room_set", text="房间")
        row.operator("gpt_director.add_street_set", text="街道")
        row.operator("gpt_director.add_stage_set", text="舞台")
        layout.operator("gpt_director.three_point_lighting", icon="LIGHT_AREA")
        layout.prop(context.scene, "gpt_director_light_template_name", text="灯光模板名")
        layout.prop(context.scene, "gpt_director_light_template_note", text="灯光备注")
        layout.prop(context.scene, "gpt_director_light_template_choice", text="灯光模板")
        layout.prop(context.scene, "gpt_director_selected_light_template", text="灯光ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_light_template", text="保存灯光")
        row.operator("gpt_director.load_light_template", text="加载灯光")
        row = layout.row(align=True)
        row.operator("gpt_director.update_light_template", text="更新灯光")
        row.operator("gpt_director.delete_light_template", text="删除灯光")
        layout.separator()
        layout.prop(context.scene, "gpt_director_preset_name", text="场景预设名")
        layout.prop(context.scene, "gpt_director_preset_note", text="预设备注")
        layout.prop(context.scene, "gpt_director_preset_choice", text="场景预设")
        layout.prop(context.scene, "gpt_director_selected_preset", text="预设ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_scene_preset", text="保存预设")
        row.operator("gpt_director.load_scene_preset", text="加载预设")
        row = layout.row(align=True)
        row.operator("gpt_director.update_scene_preset", text="更新预设")
        row.operator("gpt_director.delete_scene_preset", text="删除预设")
        layout.prop(context.scene, "gpt_director_set_package_name", text="布景包名")
        layout.prop(context.scene, "gpt_director_set_package_note", text="布景包备注")
        layout.prop(context.scene, "gpt_director_set_package_choice", text="布景包")
        layout.prop(context.scene, "gpt_director_selected_set_package", text="布景包ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_set_package", text="保存布景")
        row.operator("gpt_director.load_set_package", text="加载布景")
        row = layout.row(align=True)
        row.operator("gpt_director.update_set_package", text="更新布景")
        row.operator("gpt_director.delete_set_package", text="删除布景")
        layout.separator()
        layout.prop(context.scene, "gpt_director_asset_kind", text="资产类型")
        layout.prop(context.scene, "gpt_director_asset_name", text="资产名")
        layout.operator("gpt_director.import_model", icon="IMPORT")
        layout.operator("gpt_director.import_asset_directory", icon="FILE_FOLDER")
        layout.operator("gpt_director.import_plan_assets", icon="APPEND_BLEND")
        layout.prop(context.scene, "gpt_director_asset_source_profile", text="开源来源")
        layout.prop(context.scene, "gpt_director_asset_library_path", text="资产库目录")
        layout.operator("gpt_director.scan_asset_library", text="扫描资产库")
        layout.prop(context.scene, "gpt_director_asset_library_catalog", text="资产分类")
        layout.prop(context.scene, "gpt_director_asset_library_search", text="库资产搜索")
        layout.prop(context.scene, "gpt_director_library_favorites_only", text="只看收藏")
        layout.prop(context.scene, "gpt_director_library_asset_choice", text="库资产")
        _draw_library_asset_preflight(layout, context)
        layout.prop(context.scene, "gpt_director_library_asset_tags", text="资产标签")
        layout.prop(context.scene, "gpt_director_library_asset_note", text="用途备注")
        row = layout.row(align=True)
        row.operator("gpt_director.import_library_asset", text="导入库资产")
        row.operator("gpt_director.apply_library_texture_material", text="应用贴图材质")
        row = layout.row(align=True)
        op = row.operator("gpt_director.favorite_library_asset", text="收藏")
        op.favorite = True
        op = row.operator("gpt_director.favorite_library_asset", text="取消收藏")
        op.favorite = False
        row = layout.row(align=True)
        row.operator("gpt_director.load_library_asset_metadata", text="读取标签")
        row.operator("gpt_director.update_library_asset_metadata", text="保存标签")
        layout.operator("gpt_director.register_selected_asset", text="登记选中为资产")
        layout.prop(context.scene, "gpt_director_asset_choice", text="工程资产")
        layout.operator("gpt_director.select_asset", icon="RESTRICT_SELECT_OFF")
        layout.separator()
        layout.prop(context.scene, "gpt_director_actor_name", text="演员名")
        layout.prop(context.scene, "gpt_director_actor_role", text="角色定位")
        layout.prop(context.scene, "gpt_director_actor_note", text="演员备注")
        layout.prop(context.scene, "gpt_director_actor_choice", text="演员位")
        layout.prop(context.scene, "gpt_director_selected_actor", text="演员ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_actor", text="保存演员")
        row.operator("gpt_director.load_actor", text="加载演员")
        row = layout.row(align=True)
        row.operator("gpt_director.update_actor", text="更新演员")
        row.operator("gpt_director.delete_actor", text="删除演员")
        layout.separator()
        layout.prop(context.scene, "gpt_director_action_name", text="动作名")
        layout.operator("gpt_director.apply_action", icon="ARMATURE_DATA")
        layout.prop(context.scene, "gpt_director_action_clip_name", text="动作片段名")
        layout.prop(context.scene, "gpt_director_action_clip_note", text="动作备注")
        layout.prop(context.scene, "gpt_director_action_clip_choice", text="动作片段")
        layout.prop(context.scene, "gpt_director_selected_action_clip", text="动作ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_action_clip", text="保存动作")
        row.operator("gpt_director.load_action_clip", text="加载动作")
        row = layout.row(align=True)
        row.operator("gpt_director.refresh_action_matches", text="刷新匹配")
        row.operator("gpt_director.apply_shot_action_match", text="应用镜头动作")
        row = layout.row(align=True)
        row.operator("gpt_director.update_action_clip", text="更新动作")
        row.operator("gpt_director.delete_action_clip", text="删除动作")
        layout.prop(context.scene, "gpt_director_retarget_profile_name", text="重定向档案")
        layout.prop(context.scene, "gpt_director_retarget_profile_note", text="重定向备注")
        layout.prop(context.scene, "gpt_director_retarget_source_armature", text="源骨骼")
        layout.prop(context.scene, "gpt_director_retarget_target_armature", text="目标骨骼")
        layout.prop(context.scene, "gpt_director_retarget_profile_choice", text="映射档案")
        layout.prop(context.scene, "gpt_director_selected_retarget_profile", text="映射ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.build_retarget_profile", text="建立映射")
        row.operator("gpt_director.apply_retarget_profile", text="重定向动作")
        row = layout.row(align=True)
        row.operator("gpt_director.delete_retarget_profile", text="删除映射")
        profile = _find_retarget_profile(_load_meta(), _active_retarget_profile_key(context.scene))
        if profile:
            profile = _refresh_retarget_profile_stats(profile)
            mapping_box = layout.box()
            mapping_box.label(
                text="映射 "
                + str(profile.get("mapped_bone_count") or 0)
                + "｜源未映射 "
                + str(profile.get("unmapped_source_count") or 0)
                + "｜目标未映射 "
                + str(profile.get("unmapped_target_count") or 0)
            )
            source_unmapped = profile.get("unmapped_source_bones") if isinstance(profile.get("unmapped_source_bones"), list) else []
            target_unmapped = profile.get("unmapped_target_bones") if isinstance(profile.get("unmapped_target_bones"), list) else []
            if source_unmapped:
                mapping_box.label(text="源待处理：" + "、".join(source_unmapped[:6]), icon="ERROR")
            if target_unmapped:
                mapping_box.label(text="目标未使用：" + "、".join(target_unmapped[:6]), icon="INFO")
            mapping_box.prop(context.scene, "gpt_director_retarget_bone_mapping_choice", text="映射条目")
            row = mapping_box.row(align=True)
            row.operator("gpt_director.load_retarget_bone_mapping", text="读取")
            row.operator("gpt_director.remove_retarget_bone_mapping", text="删除")
            mapping_box.prop(context.scene, "gpt_director_retarget_source_bone", text="源骨骼")
            mapping_box.prop(context.scene, "gpt_director_retarget_target_bone", text="目标骨骼")
            mapping_box.operator("gpt_director.set_retarget_bone_mapping", text="保存手动映射")
            root_motion = profile.get("root_motion") if isinstance(profile.get("root_motion"), dict) else {{}}
            rest_pose = profile.get("rest_pose_alignment") if isinstance(profile.get("rest_pose_alignment"), dict) else {{}}
            mapping_box.prop(context.scene, "gpt_director_retarget_root_motion_enabled", text="保留根运动")
            mapping_box.prop(context.scene, "gpt_director_retarget_root_motion_scale", text="根运动手动倍率")
            mapping_box.label(
                text="自动比例 "
                + ("%.3f" % float(root_motion.get("automatic_scale") or 1.0))
                + "｜当前有效 "
                + ("%.3f" % (float(root_motion.get("automatic_scale") or 1.0) * float(getattr(context.scene, "gpt_director_retarget_root_motion_scale", 1.0) or 1.0)))
            )
            mapping_box.prop(context.scene, "gpt_director_retarget_rest_pose_enabled", text="校正 Rest Pose 轴向")
            mapping_box.prop(context.scene, "gpt_director_retarget_bake_step", text="烘焙帧步长")
            mapping_box.label(
                text="姿态差异骨骼 "
                + str(rest_pose.get("mismatch_bone_count") or 0)
                + "｜最大轴向差 "
                + ("%.1f°" % float(rest_pose.get("max_angle_degrees") or 0.0))
            )
        layout.prop(context.scene, "gpt_director_pose_template_name", text="姿势模板名")
        layout.prop(context.scene, "gpt_director_pose_template_note", text="姿势备注")
        layout.prop(context.scene, "gpt_director_pose_template_choice", text="姿势模板")
        layout.prop(context.scene, "gpt_director_selected_pose_template", text="姿势ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_pose_template", text="保存姿势")
        row.operator("gpt_director.load_pose_template", text="加载姿势")
        row = layout.row(align=True)
        row.operator("gpt_director.update_pose_template", text="更新姿势")
        row.operator("gpt_director.delete_pose_template", text="删除姿势")
        layout.prop(context.scene, "gpt_director_animation_template_name", text="动画片段名")
        layout.prop(context.scene, "gpt_director_animation_template_note", text="动画备注")
        layout.prop(context.scene, "gpt_director_animation_template_choice", text="动画片段")
        layout.prop(context.scene, "gpt_director_selected_animation_template", text="动画ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_animation_template", text="保存动画")
        row.operator("gpt_director.load_animation_template", text="加载动画")
        row = layout.row(align=True)
        row.operator("gpt_director.update_animation_template", text="更新动画")
        row.operator("gpt_director.delete_animation_template", text="删除动画")
        layout.prop(context.scene, "gpt_director_material_template_name", text="材质模板名")
        layout.prop(context.scene, "gpt_director_material_template_note", text="材质备注")
        layout.prop(context.scene, "gpt_director_material_template_choice", text="材质模板")
        layout.prop(context.scene, "gpt_director_selected_material_template", text="材质ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_material_template", text="保存材质")
        row.operator("gpt_director.load_material_template", text="加载材质")
        row = layout.row(align=True)
        row.operator("gpt_director.update_material_template", text="更新材质")
        row.operator("gpt_director.delete_material_template", text="删除材质")
        row = layout.row(align=True)
        row.operator("gpt_director.add_sofa_set", text="沙发茶几")
        row.operator("gpt_director.add_round_table", text="圆桌")
        layout.operator("gpt_director.add_camera", icon="CAMERA_DATA")
        row = layout.row(align=True)
        op = row.operator("gpt_director.camera_preset", text="远景")
        op.preset = "wide"
        op = row.operator("gpt_director.camera_preset", text="中景")
        op.preset = "medium"
        op = row.operator("gpt_director.camera_preset", text="近景")
        op.preset = "close"
        op = row.operator("gpt_director.camera_preset", text="俯拍")
        op.preset = "top"
        layout.prop(context.scene, "gpt_director_camera_template_name", text="机位模板名")
        layout.prop(context.scene, "gpt_director_camera_template_note", text="机位备注")
        layout.prop(context.scene, "gpt_director_camera_template_choice", text="机位模板")
        layout.prop(context.scene, "gpt_director_selected_camera_template", text="机位ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_camera_template", text="保存机位")
        row.operator("gpt_director.load_camera_template", text="加载机位")
        row = layout.row(align=True)
        row.operator("gpt_director.update_camera_template", text="更新机位")
        row.operator("gpt_director.delete_camera_template", text="删除机位")
        layout.prop(context.scene, "gpt_director_object_template_name", text="站位模板名")
        layout.prop(context.scene, "gpt_director_object_template_note", text="站位备注")
        layout.prop(context.scene, "gpt_director_object_template_choice", text="站位模板")
        layout.prop(context.scene, "gpt_director_selected_object_template", text="站位ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_object_template", text="保存站位")
        row.operator("gpt_director.load_object_template", text="加载站位")
        row = layout.row(align=True)
        row.operator("gpt_director.update_object_template", text="更新站位")
        row.operator("gpt_director.delete_object_template", text="删除站位")
        row = layout.row(align=True)
        op = row.operator("gpt_director.camera_motion", text="推近")
        op.motion = "push_in"
        op = row.operator("gpt_director.camera_motion", text="拉远")
        op.motion = "pull_out"
        op = row.operator("gpt_director.camera_motion", text="左移")
        op.motion = "truck_left"
        op = row.operator("gpt_director.camera_motion", text="右移")
        op.motion = "truck_right"
        row = layout.row(align=True)
        op = row.operator("gpt_director.camera_motion", text="升起")
        op.motion = "rise"
        op = row.operator("gpt_director.camera_motion", text="下降")
        op.motion = "descend"
        row = layout.row(align=True)
        op = row.operator("gpt_director.object_motion", text="前进")
        op.motion = "forward"
        op = row.operator("gpt_director.object_motion", text="后退")
        op.motion = "backward"
        op = row.operator("gpt_director.object_motion", text="左移")
        op.motion = "left"
        op = row.operator("gpt_director.object_motion", text="右移")
        op.motion = "right"
        layout.operator("gpt_director.insert_keyframe", icon="KEY_HLT")
        layout.separator()
        layout.prop(context.scene, "gpt_director_shot_choice", text="保存镜头")
        layout.prop(context.scene, "gpt_director_selected_shot", text="镜头ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_shot", text="保存镜头", icon="MARKER")
        row.operator("gpt_director.load_shot", text="加载镜头", icon="CAMERA_DATA")
        row = layout.row(align=True)
        row.operator("gpt_director.refresh_action_matches", text="刷新动作匹配")
        row.operator("gpt_director.apply_shot_action_match", text="应用匹配动作")
        _draw_shot_asset_plan(layout, context)
        layout.operator("gpt_director.prepare_shot_assets", text="准备镜头资产", icon="ASSET_MANAGER")
        row = layout.row(align=True)
        row.operator("gpt_director.export_ai_workflow_tasks", text="导出AI任务包", icon="FILE_TICK")
        row.operator("gpt_director.export_ai_workflow_handoff", text="导出AI工作包", icon="FILE_FOLDER")
        layout.prop(context.scene, "gpt_director_ai_task_id", text="AI任务ID")
        layout.prop(context.scene, "gpt_director_ai_result_type", text="AI结果类型")
        layout.prop(context.scene, "gpt_director_ai_result_note", text="AI结果备注")
        layout.prop(context.scene, "gpt_director_ai_result_directory", text="AI结果目录")
        layout.prop(context.scene, "gpt_director_ai_result_recursive", text="递归扫描")
        row = layout.row(align=True)
        row.operator("gpt_director.register_ai_workflow_result", text="登记AI结果", icon="IMPORT")
        row.operator("gpt_director.register_ai_workflow_result_directory", text="批量登记AI结果目录", icon="FILE_FOLDER")
        row = layout.row(align=True)
        row.operator("gpt_director.update_shot", text="更新镜头")
        row.operator("gpt_director.delete_shot", text="删除镜头")
        layout.prop(context.scene, "gpt_director_shot_package_name", text="镜头包名")
        layout.prop(context.scene, "gpt_director_shot_package_note", text="镜头包备注")
        layout.prop(context.scene, "gpt_director_shot_package_choice", text="镜头包")
        layout.prop(context.scene, "gpt_director_selected_shot_package", text="镜头包ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_shot_package", text="保存镜头包")
        row.operator("gpt_director.load_shot_package", text="加载镜头包")
        row = layout.row(align=True)
        row.operator("gpt_director.update_shot_package", text="更新镜头包")
        row.operator("gpt_director.delete_shot_package", text="删除镜头包")
        layout.prop(context.scene, "gpt_director_render_output", text="输出类型")
        row = layout.row(align=True)
        row.prop(context.scene, "gpt_director_frame_start", text="起始帧")
        row.prop(context.scene, "gpt_director_frame_end", text="结束帧")
        layout.prop(context.scene, "gpt_director_render_template_name", text="渲染模板名")
        layout.prop(context.scene, "gpt_director_render_template_note", text="渲染备注")
        layout.prop(context.scene, "gpt_director_render_template_choice", text="渲染模板")
        layout.prop(context.scene, "gpt_director_selected_render_template", text="渲染ID/名称")
        row = layout.row(align=True)
        row.operator("gpt_director.save_render_template", text="保存渲染")
        row.operator("gpt_director.load_render_template", text="加载渲染")
        row = layout.row(align=True)
        row.operator("gpt_director.update_render_template", text="更新渲染")
        row.operator("gpt_director.delete_render_template", text="删除渲染")
        layout.operator("gpt_director.save_metadata", icon="FILE_TICK")
        layout.operator("gpt_director.render_current", icon="RENDER_STILL")
        layout.operator("gpt_director.render_pending_shots", icon="RENDER_ANIMATION")
        layout.operator("gpt_director.render_all_shots", icon="RENDER_ANIMATION")


CLASSES = (
    GPT_OT_director_init_scene,
    GPT_OT_director_add_dialogue_lounge_scene,
    GPT_OT_director_add_room_set,
    GPT_OT_director_add_street_set,
    GPT_OT_director_add_stage_set,
    GPT_OT_director_add_blue_mannequin,
    GPT_OT_director_add_red_mannequin,
    GPT_OT_director_select_mannequin_controls,
    GPT_OT_director_add_sofa_set,
    GPT_OT_director_add_round_table,
    GPT_OT_director_add_camera,
    GPT_OT_director_camera_preset,
    GPT_OT_director_save_camera_template,
    GPT_OT_director_update_camera_template,
    GPT_OT_director_delete_camera_template,
    GPT_OT_director_load_camera_template,
    GPT_OT_director_save_object_template,
    GPT_OT_director_update_object_template,
    GPT_OT_director_delete_object_template,
    GPT_OT_director_load_object_template,
    GPT_OT_director_camera_motion,
    GPT_OT_director_object_motion,
    GPT_OT_director_three_point_lighting,
    GPT_OT_director_save_light_template,
    GPT_OT_director_update_light_template,
    GPT_OT_director_delete_light_template,
    GPT_OT_director_load_light_template,
    GPT_OT_director_insert_keyframe,
    GPT_OT_director_save_shot,
    GPT_OT_director_update_shot,
    GPT_OT_director_delete_shot,
    GPT_OT_director_load_shot,
    GPT_OT_director_save_shot_package,
    GPT_OT_director_update_shot_package,
    GPT_OT_director_delete_shot_package,
    GPT_OT_director_load_shot_package,
    GPT_OT_director_save_set_package,
    GPT_OT_director_update_set_package,
    GPT_OT_director_delete_set_package,
    GPT_OT_director_load_set_package,
    GPT_OT_director_save_actor,
    GPT_OT_director_update_actor,
    GPT_OT_director_delete_actor,
    GPT_OT_director_load_actor,
    GPT_OT_director_save_scene_preset,
    GPT_OT_director_update_scene_preset,
    GPT_OT_director_delete_scene_preset,
    GPT_OT_director_load_scene_preset,
    GPT_OT_director_import_model,
    GPT_OT_director_import_asset_directory,
    GPT_OT_director_scan_asset_library,
    GPT_OT_director_import_library_asset,
    GPT_OT_director_apply_library_texture_material,
    GPT_OT_director_favorite_library_asset,
    GPT_OT_director_load_library_asset_metadata,
    GPT_OT_director_update_library_asset_metadata,
    GPT_OT_director_register_selected_asset,
    GPT_OT_director_import_plan_assets,
    GPT_OT_director_prepare_shot_assets,
    GPT_OT_director_export_ai_workflow_tasks,
    GPT_OT_director_export_ai_workflow_handoff,
    GPT_OT_director_register_ai_workflow_result,
    GPT_OT_director_register_ai_workflow_result_directory,
    GPT_OT_director_select_asset,
    GPT_OT_director_apply_action,
    GPT_OT_director_build_retarget_profile,
    GPT_OT_director_load_retarget_bone_mapping,
    GPT_OT_director_set_retarget_bone_mapping,
    GPT_OT_director_remove_retarget_bone_mapping,
    GPT_OT_director_apply_retarget_profile,
    GPT_OT_director_delete_retarget_profile,
    GPT_OT_director_save_action_clip,
    GPT_OT_director_update_action_clip,
    GPT_OT_director_delete_action_clip,
    GPT_OT_director_load_action_clip,
    GPT_OT_director_refresh_action_matches,
    GPT_OT_director_apply_shot_action_match,
    GPT_OT_director_save_pose_template,
    GPT_OT_director_update_pose_template,
    GPT_OT_director_delete_pose_template,
    GPT_OT_director_load_pose_template,
    GPT_OT_director_save_animation_template,
    GPT_OT_director_update_animation_template,
    GPT_OT_director_delete_animation_template,
    GPT_OT_director_load_animation_template,
    GPT_OT_director_save_material_template,
    GPT_OT_director_update_material_template,
    GPT_OT_director_delete_material_template,
    GPT_OT_director_load_material_template,
    GPT_OT_director_toggle_control_labels,
    GPT_OT_director_toggle_clean_view,
    GPT_OT_director_set_simple_view,
    GPT_OT_director_apply_quick_pose,
    GPT_OT_director_simple_drag_mode,
    GPT_OT_director_save_render_template,
    GPT_OT_director_update_render_template,
    GPT_OT_director_delete_render_template,
    GPT_OT_director_load_render_template,
    GPT_OT_director_save_metadata,
    GPT_OT_director_render_current,
    GPT_OT_director_render_pending_shots,
    GPT_OT_director_render_all_shots,
    GPT_PT_director_panel,
)


def register():
    bpy.types.Scene.gpt_director_shot_name = StringProperty(name="镜头名", default="镜头01")
    bpy.types.Scene.gpt_director_shot_note = StringProperty(name="备注", default="")
    bpy.types.Scene.gpt_director_scene_number = StringProperty(name="场次", default="场次01")
    bpy.types.Scene.gpt_director_scene_location = StringProperty(name="地点", default="")
    bpy.types.Scene.gpt_director_scene_environment = EnumProperty(
        name="内外景",
        default="unspecified",
        items=[
            ("unspecified", "未指定", "暂不指定内外景"),
            ("interior", "内景", "室内场景"),
            ("exterior", "外景", "室外场景"),
            ("mixed", "内外景", "同时包含室内和室外"),
        ],
    )
    bpy.types.Scene.gpt_director_scene_time = EnumProperty(
        name="日夜",
        default="unspecified",
        items=[
            ("unspecified", "未指定", "暂不指定日夜"),
            ("day", "日", "白天"),
            ("night", "夜", "夜晚"),
            ("dawn", "晨", "清晨"),
            ("dusk", "昏", "黄昏"),
        ],
    )
    bpy.types.Scene.gpt_director_shot_status = EnumProperty(
        name="镜头状态",
        default="draft",
        items=[
            ("draft", "草稿", "还在搭建或试镜头"),
            ("review", "待调整", "已成型但还需要修改"),
            ("approved", "已定稿", "镜头已确认可进入后续制作"),
        ],
    )
    bpy.types.Scene.gpt_director_shot_choice = EnumProperty(name="保存镜头", items=_shot_enum_items)
    bpy.types.Scene.gpt_director_selected_shot = StringProperty(name="镜头ID/名称", default="")
    bpy.types.Scene.gpt_director_shot_package_name = StringProperty(name="镜头包名", default="镜头包01")
    bpy.types.Scene.gpt_director_shot_package_note = StringProperty(name="镜头包备注", default="")
    bpy.types.Scene.gpt_director_shot_package_choice = EnumProperty(name="镜头包", items=_shot_package_enum_items)
    bpy.types.Scene.gpt_director_selected_shot_package = StringProperty(name="镜头包ID/名称", default="")
    bpy.types.Scene.gpt_director_set_package_name = StringProperty(name="布景包名", default="布景包01")
    bpy.types.Scene.gpt_director_set_package_note = StringProperty(name="布景包备注", default="")
    bpy.types.Scene.gpt_director_set_package_choice = EnumProperty(name="布景包", items=_set_package_enum_items)
    bpy.types.Scene.gpt_director_selected_set_package = StringProperty(name="布景包ID/名称", default="")
    bpy.types.Scene.gpt_director_actor_name = StringProperty(name="演员名", default="主角")
    bpy.types.Scene.gpt_director_actor_role = StringProperty(name="角色定位", default="")
    bpy.types.Scene.gpt_director_actor_note = StringProperty(name="演员备注", default="")
    bpy.types.Scene.gpt_director_actor_choice = EnumProperty(name="演员位", items=_actor_enum_items)
    bpy.types.Scene.gpt_director_selected_actor = StringProperty(name="演员ID/名称", default="")
    bpy.types.Scene.gpt_director_preset_name = StringProperty(name="场景预设名", default="场景预设01")
    bpy.types.Scene.gpt_director_preset_note = StringProperty(name="预设备注", default="")
    bpy.types.Scene.gpt_director_preset_choice = EnumProperty(name="场景预设", items=_scene_preset_enum_items)
    bpy.types.Scene.gpt_director_selected_preset = StringProperty(name="预设ID/名称", default="")
    bpy.types.Scene.gpt_director_camera_template_name = StringProperty(name="机位模板名", default="机位模板01")
    bpy.types.Scene.gpt_director_camera_template_note = StringProperty(name="机位备注", default="")
    bpy.types.Scene.gpt_director_camera_template_choice = EnumProperty(name="机位模板", items=_camera_template_enum_items)
    bpy.types.Scene.gpt_director_selected_camera_template = StringProperty(name="机位ID/名称", default="")
    bpy.types.Scene.gpt_director_light_template_name = StringProperty(name="灯光模板名", default="灯光模板01")
    bpy.types.Scene.gpt_director_light_template_note = StringProperty(name="灯光备注", default="")
    bpy.types.Scene.gpt_director_light_template_choice = EnumProperty(name="灯光模板", items=_light_template_enum_items)
    bpy.types.Scene.gpt_director_selected_light_template = StringProperty(name="灯光ID/名称", default="")
    bpy.types.Scene.gpt_director_object_template_name = StringProperty(name="站位模板名", default="站位模板01")
    bpy.types.Scene.gpt_director_object_template_note = StringProperty(name="站位备注", default="")
    bpy.types.Scene.gpt_director_object_template_choice = EnumProperty(name="站位模板", items=_object_template_enum_items)
    bpy.types.Scene.gpt_director_selected_object_template = StringProperty(name="站位ID/名称", default="")
    bpy.types.Scene.gpt_director_render_output = EnumProperty(
        name="输出类型",
        default="still",
        items=[
            ("still", "普通图", "输出一张普通参考图"),
            ("transparent", "透明图", "输出透明背景 PNG，适合后期合成"),
            ("sequence", "图片序列", "按帧输出 PNG 序列"),
            ("video", "视频", "输出 MP4 视频，同时生成一张预览图"),
            ("layered", "分层素材包", "输出普通参考图、透明图和素材清单，适合后期合成"),
        ],
    )
    bpy.types.Scene.gpt_director_frame_start = IntProperty(name="起始帧", default=1, min=1)
    bpy.types.Scene.gpt_director_frame_end = IntProperty(name="结束帧", default=120, min=1)
    bpy.types.Scene.gpt_director_render_template_name = StringProperty(name="渲染模板名", default="渲染模板01")
    bpy.types.Scene.gpt_director_render_template_note = StringProperty(name="渲染备注", default="")
    bpy.types.Scene.gpt_director_render_template_choice = EnumProperty(name="渲染模板", items=_render_template_enum_items)
    bpy.types.Scene.gpt_director_selected_render_template = StringProperty(name="渲染ID/名称", default="")
    bpy.types.Scene.gpt_director_ai_task_id = StringProperty(name="AI任务ID", default="")
    bpy.types.Scene.gpt_director_ai_result_type = EnumProperty(
        name="AI结果类型",
        default="auto",
        items=[
            ("auto", "自动判断", "按文件后缀自动判断 AI 结果用途"),
            ("image", "图片/首帧", "登记为镜头参考图或首帧图"),
            ("video", "视频", "登记为镜头视频输出"),
            ("asset", "模型资产", "导入为人物、道具、场景或通用模型资产"),
            ("motion", "动作", "导入为动作并尝试进入动作片段/重定向流程"),
            ("attachment", "附件", "只登记文件，不导入到场景"),
        ],
    )
    bpy.types.Scene.gpt_director_ai_result_note = StringProperty(name="AI结果备注", default="")
    bpy.types.Scene.gpt_director_ai_result_directory = StringProperty(name="AI结果目录", default="", subtype="DIR_PATH")
    bpy.types.Scene.gpt_director_ai_result_recursive = BoolProperty(name="递归扫描AI结果目录", default=False)
    bpy.types.Scene.gpt_director_asset_kind = EnumProperty(
        name="资产类型",
        default="model",
        items=[
            ("character", "人物", "人物模型、虚拟演员、带骨骼角色"),
            ("prop", "道具", "桌椅、武器、手机、车辆等可摆放物件"),
            ("scene", "场景", "房间、街道、舞台、建筑等场景资产"),
            ("action", "动作", "BVH/FBX 动作、姿势、走位资产"),
            ("model", "通用模型", "暂未分类的 3D 模型"),
            ("material", "材质", "PBR 材质贴图组，可套到选中人物或道具"),
            ("texture", "贴图", "单张图片贴图、透明图或表面纹理"),
            ("hdri", "HDRI", "环境光和天空贴图"),
        ],
    )
    bpy.types.Scene.gpt_director_asset_name = StringProperty(name="资产名", default="")
    bpy.types.Scene.gpt_director_asset_source_profile = EnumProperty(
        name="开源来源",
        items=_asset_source_profile_enum_items,
    )
    bpy.types.Scene.gpt_director_asset_library_path = StringProperty(
        name="资产库目录",
        default=DEFAULT_ASSET_LIBRARY_PATH,
        subtype="DIR_PATH",
    )
    bpy.types.Scene.gpt_director_asset_library_catalog = EnumProperty(
        name="资产分类",
        items=_asset_library_catalog_enum_items,
    )
    bpy.types.Scene.gpt_director_asset_library_search = StringProperty(name="库资产搜索", default="")
    bpy.types.Scene.gpt_director_library_favorites_only = BoolProperty(name="只看收藏", default=False)
    bpy.types.Scene.gpt_director_library_asset_choice = EnumProperty(name="库资产", items=_library_asset_enum_items)
    bpy.types.Scene.gpt_director_library_asset_tags = StringProperty(name="资产标签", default="")
    bpy.types.Scene.gpt_director_library_asset_note = StringProperty(name="用途备注", default="")
    bpy.types.Scene.gpt_director_asset_choice = EnumProperty(name="工程资产", items=_asset_enum_items)
    bpy.types.Scene.gpt_director_action_name = StringProperty(name="动作名", default="")
    bpy.types.Scene.gpt_director_action_clip_name = StringProperty(name="动作片段名", default="动作片段01")
    bpy.types.Scene.gpt_director_action_clip_note = StringProperty(name="动作备注", default="")
    bpy.types.Scene.gpt_director_action_clip_choice = EnumProperty(name="动作片段", items=_action_clip_enum_items)
    bpy.types.Scene.gpt_director_selected_action_clip = StringProperty(name="动作ID/名称", default="")
    bpy.types.Scene.gpt_director_retarget_profile_name = StringProperty(name="重定向档案", default="动作重定向档案")
    bpy.types.Scene.gpt_director_retarget_profile_note = StringProperty(name="重定向备注", default="")
    bpy.types.Scene.gpt_director_retarget_source_armature = StringProperty(name="源骨骼", default="")
    bpy.types.Scene.gpt_director_retarget_target_armature = StringProperty(name="目标骨骼", default="")
    bpy.types.Scene.gpt_director_retarget_profile_choice = EnumProperty(name="重定向档案", items=_retarget_profile_enum_items)
    bpy.types.Scene.gpt_director_selected_retarget_profile = StringProperty(name="重定向ID/名称", default="")
    bpy.types.Scene.gpt_director_retarget_bone_mapping_choice = EnumProperty(name="骨骼映射", items=_retarget_bone_mapping_enum_items)
    bpy.types.Scene.gpt_director_retarget_source_bone = StringProperty(name="源骨骼名称", default="")
    bpy.types.Scene.gpt_director_retarget_target_bone = StringProperty(name="目标骨骼名称", default="")
    bpy.types.Scene.gpt_director_retarget_root_motion_enabled = BoolProperty(name="保留根运动", default=True)
    bpy.types.Scene.gpt_director_retarget_root_motion_scale = FloatProperty(name="根运动倍率", default=1.0, min=0.01, max=100.0, precision=3)
    bpy.types.Scene.gpt_director_retarget_rest_pose_enabled = BoolProperty(name="校正 Rest Pose 轴向", default=True)
    bpy.types.Scene.gpt_director_retarget_bake_step = IntProperty(name="重定向烘焙帧步长", default=1, min=1, max=12)
    bpy.types.Scene.gpt_director_pose_template_name = StringProperty(name="姿势模板名", default="姿势模板01")
    bpy.types.Scene.gpt_director_pose_template_note = StringProperty(name="姿势备注", default="")
    bpy.types.Scene.gpt_director_pose_template_choice = EnumProperty(name="姿势模板", items=_pose_template_enum_items)
    bpy.types.Scene.gpt_director_selected_pose_template = StringProperty(name="姿势ID/名称", default="")
    bpy.types.Scene.gpt_director_active_character_asset_id = StringProperty(name="当前人物资产ID", default="")
    bpy.types.Scene.gpt_director_active_character_name = StringProperty(name="当前人物", default="")
    bpy.types.Scene.gpt_director_active_pose = StringProperty(name="当前姿势", default="standing")
    bpy.types.Scene.gpt_director_simple_drag_enabled = BoolProperty(name="位置拖放", default=False)
    bpy.types.Scene.gpt_director_show_advanced_pose_controls = BoolProperty(name="高级姿势精调", default=False)
    bpy.types.Scene.gpt_director_show_professional_tools = BoolProperty(name="专业工程工具", default=False)
    bpy.types.Scene.gpt_director_animation_template_name = StringProperty(name="动画片段名", default="动画片段01")
    bpy.types.Scene.gpt_director_animation_template_note = StringProperty(name="动画备注", default="")
    bpy.types.Scene.gpt_director_animation_template_choice = EnumProperty(name="动画片段", items=_animation_template_enum_items)
    bpy.types.Scene.gpt_director_selected_animation_template = StringProperty(name="动画ID/名称", default="")
    bpy.types.Scene.gpt_director_material_template_name = StringProperty(name="材质模板名", default="材质模板01")
    bpy.types.Scene.gpt_director_material_template_note = StringProperty(name="材质备注", default="")
    bpy.types.Scene.gpt_director_material_template_choice = EnumProperty(name="材质模板", items=_material_template_enum_items)
    bpy.types.Scene.gpt_director_selected_material_template = StringProperty(name="材质ID/名称", default="")
    for cls in CLASSES:
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
        bpy.utils.register_class(cls)
    try:
        _remove_legacy_depth_scene_data()
    except Exception:
        pass
    try:
        _ensure_default_asset_library()
    except Exception:
        pass
    _register_director_load_post_handler()
    _register_character_label_draw_handler()
    _cancel_simple_drag_mode_start()
    _set_simple_drag_runtime_active(False)


def unregister():
    _cancel_simple_drag_mode_start()
    _set_simple_drag_runtime_active(False)
    _unregister_director_load_post_handler()
    _unregister_character_label_draw_handler()
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    try:
        del bpy.types.Scene.gpt_director_shot_name
        del bpy.types.Scene.gpt_director_shot_note
        del bpy.types.Scene.gpt_director_scene_number
        del bpy.types.Scene.gpt_director_scene_location
        del bpy.types.Scene.gpt_director_scene_environment
        del bpy.types.Scene.gpt_director_scene_time
        del bpy.types.Scene.gpt_director_shot_status
        del bpy.types.Scene.gpt_director_shot_choice
        del bpy.types.Scene.gpt_director_selected_shot
        del bpy.types.Scene.gpt_director_shot_package_name
        del bpy.types.Scene.gpt_director_shot_package_note
        del bpy.types.Scene.gpt_director_shot_package_choice
        del bpy.types.Scene.gpt_director_selected_shot_package
        del bpy.types.Scene.gpt_director_set_package_name
        del bpy.types.Scene.gpt_director_set_package_note
        del bpy.types.Scene.gpt_director_set_package_choice
        del bpy.types.Scene.gpt_director_selected_set_package
        del bpy.types.Scene.gpt_director_actor_name
        del bpy.types.Scene.gpt_director_actor_role
        del bpy.types.Scene.gpt_director_actor_note
        del bpy.types.Scene.gpt_director_actor_choice
        del bpy.types.Scene.gpt_director_selected_actor
        del bpy.types.Scene.gpt_director_preset_name
        del bpy.types.Scene.gpt_director_preset_note
        del bpy.types.Scene.gpt_director_preset_choice
        del bpy.types.Scene.gpt_director_selected_preset
        del bpy.types.Scene.gpt_director_camera_template_name
        del bpy.types.Scene.gpt_director_camera_template_note
        del bpy.types.Scene.gpt_director_camera_template_choice
        del bpy.types.Scene.gpt_director_selected_camera_template
        del bpy.types.Scene.gpt_director_light_template_name
        del bpy.types.Scene.gpt_director_light_template_note
        del bpy.types.Scene.gpt_director_light_template_choice
        del bpy.types.Scene.gpt_director_selected_light_template
        del bpy.types.Scene.gpt_director_object_template_name
        del bpy.types.Scene.gpt_director_object_template_note
        del bpy.types.Scene.gpt_director_object_template_choice
        del bpy.types.Scene.gpt_director_selected_object_template
        del bpy.types.Scene.gpt_director_render_output
        del bpy.types.Scene.gpt_director_frame_start
        del bpy.types.Scene.gpt_director_frame_end
        del bpy.types.Scene.gpt_director_render_template_name
        del bpy.types.Scene.gpt_director_render_template_note
        del bpy.types.Scene.gpt_director_render_template_choice
        del bpy.types.Scene.gpt_director_selected_render_template
        del bpy.types.Scene.gpt_director_ai_task_id
        del bpy.types.Scene.gpt_director_ai_result_type
        del bpy.types.Scene.gpt_director_ai_result_note
        del bpy.types.Scene.gpt_director_ai_result_directory
        del bpy.types.Scene.gpt_director_ai_result_recursive
        del bpy.types.Scene.gpt_director_asset_kind
        del bpy.types.Scene.gpt_director_asset_name
        del bpy.types.Scene.gpt_director_asset_source_profile
        del bpy.types.Scene.gpt_director_asset_library_path
        del bpy.types.Scene.gpt_director_asset_library_catalog
        del bpy.types.Scene.gpt_director_asset_library_search
        del bpy.types.Scene.gpt_director_library_favorites_only
        del bpy.types.Scene.gpt_director_library_asset_choice
        del bpy.types.Scene.gpt_director_library_asset_tags
        del bpy.types.Scene.gpt_director_library_asset_note
        del bpy.types.Scene.gpt_director_asset_choice
        del bpy.types.Scene.gpt_director_action_name
        del bpy.types.Scene.gpt_director_action_clip_name
        del bpy.types.Scene.gpt_director_action_clip_note
        del bpy.types.Scene.gpt_director_action_clip_choice
        del bpy.types.Scene.gpt_director_selected_action_clip
        del bpy.types.Scene.gpt_director_retarget_profile_name
        del bpy.types.Scene.gpt_director_retarget_profile_note
        del bpy.types.Scene.gpt_director_retarget_source_armature
        del bpy.types.Scene.gpt_director_retarget_target_armature
        del bpy.types.Scene.gpt_director_retarget_profile_choice
        del bpy.types.Scene.gpt_director_selected_retarget_profile
        del bpy.types.Scene.gpt_director_retarget_bone_mapping_choice
        del bpy.types.Scene.gpt_director_retarget_source_bone
        del bpy.types.Scene.gpt_director_retarget_target_bone
        del bpy.types.Scene.gpt_director_retarget_root_motion_enabled
        del bpy.types.Scene.gpt_director_retarget_root_motion_scale
        del bpy.types.Scene.gpt_director_retarget_rest_pose_enabled
        del bpy.types.Scene.gpt_director_retarget_bake_step
        del bpy.types.Scene.gpt_director_pose_template_name
        del bpy.types.Scene.gpt_director_pose_template_note
        del bpy.types.Scene.gpt_director_pose_template_choice
        del bpy.types.Scene.gpt_director_selected_pose_template
        del bpy.types.Scene.gpt_director_active_character_asset_id
        del bpy.types.Scene.gpt_director_active_character_name
        del bpy.types.Scene.gpt_director_active_pose
        del bpy.types.Scene.gpt_director_simple_drag_enabled
        del bpy.types.Scene.gpt_director_show_advanced_pose_controls
        del bpy.types.Scene.gpt_director_show_professional_tools
        del bpy.types.Scene.gpt_director_animation_template_name
        del bpy.types.Scene.gpt_director_animation_template_note
        del bpy.types.Scene.gpt_director_animation_template_choice
        del bpy.types.Scene.gpt_director_selected_animation_template
        del bpy.types.Scene.gpt_director_material_template_name
        del bpy.types.Scene.gpt_director_material_template_note
        del bpy.types.Scene.gpt_director_material_template_choice
        del bpy.types.Scene.gpt_director_selected_material_template
    except Exception:
        pass
'''
