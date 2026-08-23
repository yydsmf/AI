import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QPushButton

from gpt_desktop import blender_director_project
from gpt_desktop.native_workflow import BlenderDirectorProjectDialog, NODE_CATALOG, WorkflowEdgeItem, WorkflowScene


_QT_APP = QApplication.instance() or QApplication([])


class BlenderDirectorWorkflowTests(unittest.TestCase):
    def _connect(self, scene, source, source_port, target, target_port):
        edge = WorkflowEdgeItem(source.output_ports[source_port], target.input_ports[target_port])
        scene.edges.append(edge)
        scene.addItem(edge)
        return edge

    def test_blender_director_nodes_are_available(self):
        for node_type in (
            "blender_model",
            "blender_scene",
            "blender_character",
            "blender_camera",
            "blender_render",
            "blender_director_project",
        ):
            self.assertIn(node_type, NODE_CATALOG)

        self.assertEqual(NODE_CATALOG["blender_render"]["outputs"][0]["data_type"], "image")
        self.assertEqual(NODE_CATALOG["blender_scene"]["outputs"][0]["data_type"], "blender")
        self.assertEqual(NODE_CATALOG["blender_director_project"]["outputs"][0]["data_type"], "blender")

    def test_render_node_collects_upstream_blender_plan(self):
        scene = WorkflowScene(config={"providers": []}, load_defaults=False)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            model_path = str(Path(tmp) / "hero.glb")
            Path(model_path).write_bytes(b"fake")

            model = scene.add_node("blender_model", QPointF(0, 0))
            scene_node = scene.add_node("blender_scene", QPointF(250, 0))
            character = scene.add_node("blender_character", QPointF(500, 0))
            camera = scene.add_node("blender_camera", QPointF(750, 0))
            render = scene.add_node("blender_render", QPointF(1000, 0))

            model.data["model_paths"] = [model_path]
            model.value_edit.setPlainText(model_path)
            scene_node.value_edit.setPlainText("会议室，长桌，冷色灯光。")
            character.value_edit.setPlainText("主角站在门口，反派坐在桌边。")
            camera.value_edit.setPlainText("低角度中景。")
            render.value_edit.setPlainText("输出参考图。")

            self._connect(scene, model, "blender", scene_node, "blender")
            self._connect(scene, scene_node, "blender", character, "blender")
            self._connect(scene, character, "blender", camera, "blender")
            self._connect(scene, camera, "blender", render, "blender")

            plan = scene.blender_plan_for_node(render)

        self.assertEqual(plan["asset_paths"], [model_path])
        self.assertIn("会议室", plan["scene_prompt"])
        self.assertIn("主角站在门口", plan["character_prompt"])
        self.assertIn("低角度中景", plan["camera_prompt"])
        self.assertIn("输出参考图", plan["render_prompt"])

    def test_director_project_node_collects_plan_and_opens_project(self):
        scene = WorkflowScene(config={"providers": []}, load_defaults=False)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            model_path = str(Path(tmp) / "hero.glb")
            Path(model_path).write_bytes(b"fake")

            model = scene.add_node("blender_model", QPointF(0, 0))
            scene_node = scene.add_node("blender_scene", QPointF(250, 0))
            character = scene.add_node("blender_character", QPointF(500, 0))
            camera = scene.add_node("blender_camera", QPointF(750, 0))
            project = scene.add_node("blender_director_project", QPointF(1000, 0))

            model.data["model_paths"] = [model_path]
            model.value_edit.setPlainText(model_path)
            scene_node.value_edit.setPlainText("客厅，有沙发、茶几和夜景窗。")
            character.value_edit.setPlainText("蓝色人偶坐在左侧，红色人偶靠在右侧。")
            camera.value_edit.setPlainText("中景，35mm，低机位。")
            project.value_edit.setPlainText("短剧第一场客厅对话")

            self._connect(scene, model, "blender", scene_node, "blender")
            self._connect(scene, scene_node, "blender", character, "blender")
            self._connect(scene, character, "blender", camera, "blender")
            self._connect(scene, camera, "blender", project, "blender")

            prepared = {
                "project_id": "workflow_test",
                "project_name": "短剧第一场客厅对话",
                "project_dir": tmp,
                "blend_path": str(Path(tmp) / "director.blend"),
                "meta_path": str(Path(tmp) / "director_project.json"),
                "addon_path": str(Path(tmp) / "gpt_director_panel.py"),
                "bootstrap_path": str(Path(tmp) / "open_director_project.py"),
                "renders_dir": str(Path(tmp) / "renders"),
                "assets_dir": str(Path(tmp) / "assets"),
            }
            with mock.patch.object(scene, "_select_blender_executable", return_value="/fake/blender"), mock.patch(
                "gpt_desktop.native_workflow.prepare_blender_director_project", return_value=prepared
            ) as prepare, mock.patch("gpt_desktop.native_workflow.launch_blender_director_project") as launch:
                scene.run_blender_director_project_node(project)

            _, project_name, plan = prepare.call_args.args
            self.assertEqual(project_name, "短剧第一场客厅对话")
            self.assertIn(model_path, plan["asset_paths"])
            self.assertIn("客厅", plan["scene_prompt"])
            self.assertIn("蓝色人偶", plan["character_prompt"])
            self.assertIn("35mm", plan["camera_prompt"])
            self.assertIn("短剧第一场客厅对话", plan["project_prompt"])
            launch.assert_called_once_with("/fake/blender", prepared)
            self.assertEqual(project.data["director_project"], prepared)
            self.assertTrue(project.data["director_project_id"].startswith("workflow_"))
            self.assertIn("资产 0 个", project.data["director_project_summary"])

    def test_prepare_blender_director_project_writes_bridge_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            plan = {
                "asset_paths": [str(Path(tmp) / "hero.glb")],
                "scene_prompt": "街道夜景。",
                "character_prompt": "蓝色人偶站在路口。",
                "camera_prompt": "低角度中景。",
                "project_prompt": "第一场街道路口",
            }
            with mock.patch.object(blender_director_project, "DIRECTOR_PROJECT_ROOT", tmp):
                project = blender_director_project.prepare_blender_director_project(
                    "project:bad/name",
                    "第一场/街道路口",
                    plan,
                )

            for key in (
                "project_dir",
                "meta_path",
                "addon_path",
                "bootstrap_path",
                "batch_render_script_path",
                "batch_render_command_path",
                "batch_render_command_report_path",
                "renders_dir",
                "assets_dir",
            ):
                self.assertTrue(os.path.exists(project[key]), key)
            for key in ("characters", "props", "scenes", "actions", "models", "materials", "textures", "hdris"):
                self.assertTrue(os.path.isdir(project["asset_dirs"][key]), key)
            self.assertTrue(Path(project["mannequin_asset_path"]).exists())
            self.assertTrue(Path(project["mannequin_attribution_path"]).exists())
            self.assertTrue(Path(project["furniture_asset_path"]).exists())
            self.assertTrue(Path(project["furniture_attribution_path"]).exists())
            self.assertTrue(os.path.isdir(project["shots_dir"]))
            self.assertTrue(os.path.isdir(project["presets_dir"]))
            self.assertTrue(os.path.isdir(project["set_packages_dir"]))
            self.assertTrue(project["project_id"].startswith("projectbadname"))
            meta_data = json.loads(Path(project["meta_path"]).read_text(encoding="utf-8"))
            addon = Path(project["addon_path"]).read_text(encoding="utf-8")
            bootstrap = Path(project["bootstrap_path"]).read_text(encoding="utf-8")
            batch_script = Path(project["batch_render_script_path"]).read_text(encoding="utf-8")
            batch_command = json.loads(Path(project["batch_render_command_path"]).read_text(encoding="utf-8"))
            compile(addon, project["addon_path"], "exec")
            compile(bootstrap, project["bootstrap_path"], "exec")
            compile(batch_script, project["batch_render_script_path"], "exec")
            self.assertIn('panel["_ensure_independent_mannequin_instances"]()', bootstrap)
            self.assertIn("if created or migrated:", bootstrap)
            self.assertIn("街道夜景", json.dumps(meta_data, ensure_ascii=False))
            self.assertEqual(meta_data["assets"], [])
            self.assertEqual(meta_data["actors"], [])
            self.assertEqual(meta_data["shots"], [])
            self.assertEqual(meta_data["shot_packages"], [])
            self.assertEqual(meta_data["set_packages"], [])
            self.assertEqual(meta_data["renders"], [])
            self.assertEqual(meta_data["render_templates"], [])
            self.assertEqual(meta_data["camera_motions"], [])
            self.assertEqual(meta_data["camera_templates"], [])
            self.assertEqual(meta_data["light_templates"], [])
            self.assertEqual(meta_data["action_clips"], [])
            self.assertEqual(meta_data["retarget_profiles"], [])
            self.assertEqual(meta_data["retarget_applications"], [])
            self.assertEqual(meta_data["pose_templates"], [])
            self.assertEqual(meta_data["animation_templates"], [])
            self.assertEqual(meta_data["material_templates"], [])
            self.assertEqual(meta_data["material_applications"], [])
            self.assertEqual(meta_data["object_templates"], [])
            self.assertEqual(meta_data["object_motions"], [])
            self.assertEqual(meta_data["scene_presets"], [])
            self.assertNotIn("scene_references", meta_data)
            self.assertNotIn("depth_estimator_script_path", project)
            self.assertFalse((Path(project["project_dir"]) / "scripts" / "generate_scene_depth_map.py").exists())
            self.assertEqual(meta_data["asset_libraries"], [])
            self.assertEqual(meta_data["asset_library_items"], [])
            self.assertEqual(meta_data["asset_sources"], [])
            self.assertEqual(meta_data["shot_asset_preparations"], [])
            self.assertEqual(meta_data["ai_workflow_results"], [])
            self.assertEqual(len(meta_data["builtin_asset_pack"]), 4)
            self.assertEqual(len(meta_data["open_asset_source_profiles"]), 6)
            self.assertEqual(
                meta_data["director_capabilities"]["built_in_scene_operator"],
                "gpt_director.add_dialogue_lounge_scene",
            )
            self.assertIn("root_empty", meta_data["director_capabilities"]["control_model"])
            self.assertIn("object_mode_pose_proxies", meta_data["director_capabilities"]["control_model"])
            self.assertIn("color_coded_controls", meta_data["director_capabilities"]["control_model"])
            self.assertNotIn("scene_reference_2_5d", meta_data["director_capabilities"]["control_model"])
            self.assertNotIn("scene_reference_operator", meta_data["director_capabilities"])
            self.assertNotIn("scene_reference_depth_workflow", meta_data["director_capabilities"])
            self.assertIn("GPT_PT_director_panel", addon)
            self.assertIn("BUILTIN_DIRECTOR_ASSET_PACK", addon)
            self.assertIn("OPEN_ASSET_SOURCE_PROFILES", addon)
            self.assertIn("blender_asset_browser", addon)
            self.assertIn("gpt_director.add_dialogue_lounge_scene", addon)
            self.assertIn("_build_dialogue_lounge_scene", addon)
            self.assertIn("_seed_director_metadata_for_lounge", addon)
            self.assertIn("_add_empty_control", addon)
            self.assertIn("_add_control_ring", addon)
            self.assertIn("_add_mannequin_pose_controls", addon)
            self.assertIn("_add_pose_proxy_control", addon)
            self.assertIn("gpt_director_control_bone", addon)
            self.assertIn("GPT 导演台可视控制器", addon)
            self.assertIn("对象模式直接拖动", addon)
            self.assertIn("gpt_director.toggle_control_labels", addon)
            self.assertIn("_set_all_director_label_visibility", addon)
            self.assertIn("gpt_director.toggle_clean_view", addon)
            self.assertIn("清爽视图", addon)
            self.assertIn("_set_director_clean_view", addon)
            self.assertIn("_is_director_mannequin_armature", addon)
            self.assertIn("_remove_mannequin_custom_shapes", addon)
            self.assertIn("pose_bone.custom_shape = None", addon)
            self.assertIn("_remove_mannequin_rig_ui_objects", addon)
            self.assertIn("rig_ui_objects", addon)
            self.assertIn("_director_view3d_screens", addon)
            self.assertIn('bpy.data.collections.get("Director Mannequin Widgets")', addon)
            self.assertIn("obj.hide_viewport = simple", addon)
            self.assertNotIn("bone.hide = simple", addon)
            self.assertIn("gpt_director.set_simple_view", addon)
            self.assertIn("隐藏所有控制线", addon)
            self.assertIn('getattr(obj, "type", "") in {"LIGHT", "CAMERA"}', addon)
            self.assertIn("space.overlay.show_floor = True", addon)
            self.assertIn("space.overlay.show_ortho_grid = True", addon)
            self.assertIn('("show_axis_x", "show_axis_y", "show_axis_z")', addon)
            self.assertIn('startswith("横向网格 ")', addon)
            self.assertIn("gpt_director.simple_drag_mode", addon)
            self.assertIn("开启鼠标拖放位置", addon)
            self.assertIn("_raycast_visible_director_object", addon)
            self.assertIn('interface_region_types = {"UI", "HEADER", "TOOL_HEADER", "TOOLS", "HUD", "ASSET_SHELF", "ASSET_SHELF_HEADER"}', addon)
            self.assertIn('event.value == "RELEASE" and not self._dragging', addon)
            self.assertIn("event.shift", addon)
            self.assertIn("_rotate_start_mouse_x", addon)
            self.assertIn("_rotate_start_z", addon)
            self.assertIn("rotation_euler.z = self._rotate_start_z + delta * 0.01", addon)
            self.assertIn("Shift+左拖旋转", addon)
            self.assertIn('_drag_operation = "VIEW_ROTATE"', addon)
            self.assertIn("Quaternion((0.0, 0.0, 1.0), -delta_x * 0.005)", addon)
            self.assertIn("Quaternion((1.0, 0.0, 0.0), delta_y * 0.005)", addon)
            self.assertIn("space.region_3d.view_rotation = yaw @ self._view_rotate_start @ pitch", addon)
            self.assertIn('_drag_operation = "VIEW_PAN"', addon)
            self.assertIn("space.region_3d.view_location", addon)
            self.assertIn('event.type == "RIGHTMOUSE" and event.value == "PRESS"', addon)
            self.assertIn("空白左拖旋转视角｜右键拖动平移", addon)
            self.assertIn("_cancel_simple_drag_mode_start", addon)
            self.assertNotIn("bpy.app.timers.register(_start_simple_drag_mode_after_load", addon)
            self.assertNotIn("鼠标拖动已自动开启", addon)
            self.assertIn("gpt_director.apply_quick_pose", addon)
            self.assertIn("_apply_mannequin_pose_preset", addon)
            self.assertIn("_ensure_independent_mannequin_instances", addon)
            self.assertIn("_character_asset_id_for_color", addon)
            self.assertIn('"builtin_" + color_key + "_mannequin_"', addon)
            self.assertIn('"男角色" if color_key == "blue" else "女角色"', addon)
            self.assertIn("_draw_character_name_labels", addon)
            self.assertIn("location_3d_to_region_2d", addon)
            self.assertIn("_character_label_font_id", addon)
            self.assertIn("/System/Library/Fonts/PingFang.ttc", addon)
            self.assertIn("if _object_is_descendant_of(obj, root)", addon)
            self.assertIn("armature = _character_armature_for_root(root)", addon)
            self.assertIn("@persistent", addon)
            self.assertIn("def _director_load_post", addon)
            self.assertIn("bpy.app.handlers.load_post.append(_director_load_post)", addon)
            self.assertIn("_register_director_load_post_handler()", addon)
            self.assertIn("当前人物精调控制器", addon)
            self.assertIn("人物姿势", addon)
            self.assertIn("站立", addon)
            self.assertIn("坐下", addon)
            self.assertIn("行走", addon)
            self.assertIn("跑步", addon)
            self.assertIn("招手", addon)
            self.assertIn("斜躺", addon)
            self.assertIn("高级姿势精调", addon)
            self.assertIn('gpt_director_show_advanced_pose_controls = BoolProperty(name="高级姿势精调", default=False)', addon)
            self.assertIn('gpt_director_show_professional_tools = BoolProperty(name="专业工程工具", default=False)', addon)
            self.assertIn("_draw_director_quick_controls", addon)
            self.assertIn("gpt_director.select_mannequin_controls", addon)
            self.assertIn("builtin_blue_mannequin", addon)
            self.assertIn("builtin_sofa_table_props", addon)
            self.assertIn("FURNITURE_TEMPLATE_PATH", addon)
            self.assertIn("Director Modern Sofa", addon)
            self.assertIn("Director Modern Coffee Table", addon)
            self.assertIn("_add_bundled_furniture_asset", addon)
            self.assertIn("专业家具资产", addon)
            self.assertIn("PRESETS_DIR", addon)
            self.assertIn("SET_PACKAGES_DIR", addon)
            self.assertIn("import hashlib", addon)
            self.assertIn("import re", addon)
            self.assertIn("gpt_director.import_model", addon)
            self.assertNotIn("gpt_director.generate_scene_depth_map", addon)
            self.assertNotIn("gpt_director.import_scene_reference_from_fields", addon)
            self.assertNotIn("真实深度图搭景参考", addon)
            self.assertNotIn("2.5d_depth_map_proxy", addon)
            self.assertIn("gpt_director.import_asset_directory", addon)
            self.assertIn("*.blend;*.glb;*.gltf;*.fbx;*.obj;*.bvh", addon)
            self.assertIn("*.stl;*.ply;*.abc;*.usd;*.usdz", addon)
            self.assertIn("SUPPORTED_ASSET_EXTENSIONS", addon)
            self.assertIn("SUPPORTED_TEXTURE_EXTENSIONS", addon)
            self.assertIn("SUPPORTED_LIBRARY_EXTENSIONS", addon)
            self.assertIn("bpy.ops.import_mesh.stl", addon)
            self.assertIn("bpy.ops.import_mesh.ply", addon)
            self.assertIn("bpy.ops.wm.alembic_import", addon)
            self.assertIn("bpy.ops.wm.usd_import", addon)
            self.assertIn("_asset_paths_from_directory", addon)
            self.assertIn("_texture_role_from_path", addon)
            self.assertIn("_apply_library_texture_material", addon)
            self.assertIn("_create_material_from_texture_set", addon)
            self.assertIn("_path_based_id", addon)
            self.assertIn("_scan_asset_library", addon)
            self.assertIn("_asset_source_profile_enum_items", addon)
            self.assertIn("_upsert_asset_source", addon)
            self.assertIn("_library_asset_enum_items", addon)
            self.assertIn("_read_blender_asset_catalogs", addon)
            self.assertIn("_catalog_for_library_item", addon)
            self.assertIn("asset_browser_catalog_path", addon)
            self.assertIn("_set_library_asset_favorite", addon)
            self.assertIn("_set_library_asset_metadata", addon)
            self.assertIn("_mark_library_asset_used", addon)
            self.assertIn("_asset_preflight_for_library_item", addon)
            self.assertIn("_draw_library_asset_preflight", addon)
            self.assertIn("_set_library_asset_preflight", addon)
            self.assertIn("preflight_status_label", addon)
            self.assertIn("资产预检：", addon)
            self.assertIn("资产预检阻断", addon)
            self.assertIn("unsupported_format", addon)
            self.assertIn("gpt_director.scan_asset_library", addon)
            self.assertIn("gpt_director.import_library_asset", addon)
            self.assertIn("gpt_director.apply_library_texture_material", addon)
            self.assertIn("gpt_director.favorite_library_asset", addon)
            self.assertIn("gpt_director.load_library_asset_metadata", addon)
            self.assertIn("gpt_director.update_library_asset_metadata", addon)
            self.assertIn("gpt_director_asset_library_path", addon)
            self.assertIn("gpt_director_asset_source_profile", addon)
            self.assertIn('"material"', addon)
            self.assertIn('"texture"', addon)
            self.assertIn('"hdri"', addon)
            self.assertIn("gpt_director_asset_library_search", addon)
            self.assertIn("gpt_director_asset_library_catalog", addon)
            self.assertIn("_asset_library_catalog_enum_items", addon)
            self.assertIn("_asset_library_catalog_filter", addon)
            self.assertIn("全部分类", addon)

            self.assertIn("gpt_director_library_favorites_only", addon)
            self.assertIn("gpt_director_library_asset_choice", addon)
            self.assertIn("gpt_director_library_asset_tags", addon)
            self.assertIn("gpt_director_library_asset_note", addon)
            self.assertIn("gpt_director.import_plan_assets", addon)
            self.assertIn("_shot_asset_plan", addon)
            self.assertIn("_draw_shot_asset_plan", addon)
            self.assertIn("_append_shot_asset_preparation", addon)
            self.assertIn("gpt_director.prepare_shot_assets", addon)
            self.assertIn("镜头资产准备：", addon)
            self.assertIn("准备镜头资产", addon)
            self.assertIn('"prepared_for_shot_id"', addon)
            self.assertIn("_build_ai_workflow_tasks", addon)
            self.assertIn("_write_ai_workflow_tasks", addon)
            self.assertIn("_write_ai_workflow_handoff", addon)
            self.assertIn("gpt_director.export_ai_workflow_tasks", addon)
            self.assertIn("gpt_director.export_ai_workflow_handoff", addon)
            self.assertIn("导出AI任务包", addon)
            self.assertIn("导出AI工作包", addon)
            self.assertIn("ai_workflow_tasks_report_path", addon)
            self.assertIn("ai_workflow_handoff_report_path", addon)
            self.assertIn("_register_ai_workflow_result", addon)
            self.assertIn("_append_ai_workflow_result", addon)
            self.assertIn("_ai_result_task_id_from_path", addon)
            self.assertIn("gpt_director.register_ai_workflow_result", addon)
            self.assertIn("gpt_director.register_ai_workflow_result_directory", addon)
            self.assertIn("gpt_director_ai_task_id", addon)
            self.assertIn("gpt_director_ai_result_type", addon)
            self.assertIn("gpt_director_ai_result_note", addon)
            self.assertIn("gpt_director_ai_result_directory", addon)
            self.assertIn("gpt_director_ai_result_recursive", addon)
            self.assertIn("登记AI结果", addon)
            self.assertIn("批量登记AI结果目录", addon)
            self.assertIn('"ai_workflow_results"', addon)
            self.assertIn("gpt_director_asset_kind", addon)
            self.assertIn("gpt_director_asset_name", addon)
            self.assertIn("gpt_director_asset_choice", addon)
            self.assertIn("gpt_director.select_asset", addon)
            self.assertIn("gpt_director.register_selected_asset", addon)
            self.assertIn("_register_selected_asset", addon)
            self.assertIn('"registered_from"', addon)
            self.assertIn('"selected_objects"', addon)
            self.assertIn("_attach_imported_asset_controls", addon)
            self.assertIn("_parent_preserve_world", addon)
            self.assertIn('"control_root"', addon)
            self.assertIn('"control_objects"', addon)
            self.assertIn('"imported_asset_control"', addon)
            self.assertIn('"可控"', addon)
            self.assertIn("_actor_enum_items", addon)
            self.assertIn("_actor_from_selected_objects", addon)
            self.assertIn("_select_actor_objects", addon)
            self.assertIn("_assets_for_object_snapshots", addon)
            self.assertIn("_objects_from_actor", addon)
            self.assertIn("_armature_from_actor", addon)
            self.assertIn("_actor_reference", addon)
            self.assertIn("_active_action_target", addon)
            self.assertIn("_action_clip_enum_items", addon)
            self.assertIn("_apply_action_clip", addon)
            self.assertIn("_refresh_action_matches", addon)
            self.assertIn("_active_shot_action_requirement", addon)
            self.assertIn("gpt_director.refresh_action_matches", addon)
            self.assertIn("gpt_director.apply_shot_action_match", addon)
            self.assertIn("GPT_OT_director_apply_shot_action_match", addon)
            self.assertIn('"shot_action_match"', addon)
            self.assertIn('"matched_action_clip"', addon)
            self.assertIn("_retarget_action_to_armature", addon)
            self.assertIn("_retarget_profile_enum_items", addon)
            self.assertIn("_retarget_bone_mapping_enum_items", addon)
            self.assertIn("_refresh_retarget_profile_stats", addon)
            self.assertIn("_retarget_motion_scale", addon)
            self.assertIn("_retarget_rest_correction", addon)
            self.assertIn("_write_retarget_rotation_curves", addon)
            self.assertIn("_write_retarget_root_location_curves", addon)
            self.assertIn("_upsert_retarget_action_clip", addon)
            self.assertIn("_find_action_clip_by_action", addon)
            self.assertIn("gpt_director.build_retarget_profile", addon)
            self.assertIn("gpt_director.apply_retarget_profile", addon)
            self.assertIn("GPT_OT_director_apply_retarget_profile", addon)
            self.assertIn("gpt_director.load_retarget_bone_mapping", addon)
            self.assertIn("gpt_director.set_retarget_bone_mapping", addon)
            self.assertIn("gpt_director.remove_retarget_bone_mapping", addon)
            self.assertIn("gpt_director_retarget_source_armature", addon)
            self.assertIn("gpt_director_retarget_target_armature", addon)
            self.assertIn("gpt_director_retarget_bone_mapping_choice", addon)
            self.assertIn("gpt_director_retarget_root_motion_enabled", addon)
            self.assertIn("gpt_director_retarget_root_motion_scale", addon)
            self.assertIn("gpt_director_retarget_rest_pose_enabled", addon)
            self.assertIn("gpt_director_retarget_bake_step", addon)
            self.assertIn('"unmapped_source_bones"', addon)
            self.assertIn('"root_motion"', addon)
            self.assertIn('"rest_pose_alignment"', addon)
            self.assertIn('"generated_by"] = "retarget"', addon)
            self.assertIn('"retarget_quality"', addon)
            self.assertIn('"retarget_source_clip_name"', addon)
            self.assertIn('"action_matches"', addon)
            self.assertIn("_upsert_action_clip_from_asset_record", addon)
            self.assertIn("_select_objects_by_names", addon)
            self.assertIn("gpt_director.save_actor", addon)
            self.assertIn("gpt_director.load_actor", addon)
            self.assertIn("gpt_director.update_actor", addon)
            self.assertIn("gpt_director.delete_actor", addon)
            self.assertIn("gpt_director_actor_name", addon)
            self.assertIn("gpt_director_actor_role", addon)
            self.assertIn("gpt_director_actor_note", addon)
            self.assertIn("gpt_director_actor_choice", addon)
            self.assertIn("gpt_director_selected_actor", addon)
            self.assertIn("gpt_director.load_shot", addon)
            self.assertIn("gpt_director.update_shot", addon)
            self.assertIn("gpt_director.delete_shot", addon)
            self.assertIn("_active_shot_key", addon)
            self.assertIn("_delete_shot", addon)
            self.assertIn("_shot_package_enum_items", addon)
            self.assertIn("_load_shot_package_into_project", addon)
            self.assertIn("gpt_director.save_shot_package", addon)
            self.assertIn("gpt_director.load_shot_package", addon)
            self.assertIn("gpt_director.update_shot_package", addon)
            self.assertIn("gpt_director.delete_shot_package", addon)
            self.assertIn("gpt_director_shot_package_choice", addon)
            self.assertIn("_set_package_enum_items", addon)
            self.assertIn("_load_set_package_into_project", addon)
            self.assertIn("gpt_director.save_set_package", addon)
            self.assertIn("gpt_director.load_set_package", addon)
            self.assertIn("gpt_director.update_set_package", addon)
            self.assertIn("gpt_director.delete_set_package", addon)
            self.assertIn("gpt_director_set_package_choice", addon)
            self.assertIn("gpt_director.render_pending_shots", addon)
            self.assertIn("GPT_OT_director_render_pending_shots", addon)
            self.assertIn("gpt_director.render_all_shots", addon)
            self.assertIn("gpt_director.render_pending_shots", batch_script)
            self.assertIn("GPT_DIRECTOR_PENDING_BATCH_RENDER_DONE", batch_script)
            self.assertEqual(batch_command["mode"], "pending")
            self.assertIn("--background", batch_command["command_template"])
            self.assertIn("gpt_director_shot_choice", addon)
            self.assertIn("_shot_enum_items", addon)
            self.assertIn("_asset_enum_items", addon)
            self.assertIn("gpt_director_selected_shot", addon)
            self.assertIn("_import_director_asset", addon)
            self.assertIn("_append_blend_asset", addon)
            self.assertIn("gpt_director.add_room_set", addon)
            self.assertIn("gpt_director.add_street_set", addon)
            self.assertIn("gpt_director.add_stage_set", addon)
            self.assertIn("gpt_director.camera_preset", addon)
            self.assertIn("gpt_director.camera_motion", addon)
            self.assertIn("_camera_template_from_current_scene", addon)
            self.assertIn("_camera_template_enum_items", addon)
            self.assertIn("_apply_camera_template", addon)
            self.assertIn("gpt_director.save_camera_template", addon)
            self.assertIn("gpt_director.load_camera_template", addon)
            self.assertIn("gpt_director.update_camera_template", addon)
            self.assertIn("gpt_director.delete_camera_template", addon)
            self.assertIn("gpt_director_camera_template_choice", addon)
            self.assertIn("_light_template_enum_items", addon)
            self.assertIn("_apply_light_template", addon)
            self.assertIn("gpt_director.save_light_template", addon)
            self.assertIn("gpt_director.load_light_template", addon)
            self.assertIn("gpt_director.update_light_template", addon)
            self.assertIn("gpt_director.delete_light_template", addon)
            self.assertIn("gpt_director_light_template_choice", addon)
            self.assertIn("gpt_director.save_action_clip", addon)
            self.assertIn("gpt_director.load_action_clip", addon)
            self.assertIn("gpt_director.update_action_clip", addon)
            self.assertIn("gpt_director.delete_action_clip", addon)
            self.assertIn("gpt_director_action_clip_choice", addon)
            self.assertIn("_pose_template_enum_items", addon)
            self.assertIn("_apply_pose_template", addon)
            self.assertIn("gpt_director.save_pose_template", addon)
            self.assertIn("gpt_director.load_pose_template", addon)
            self.assertIn("gpt_director.update_pose_template", addon)
            self.assertIn("gpt_director.delete_pose_template", addon)
            self.assertIn("gpt_director_pose_template_choice", addon)
            self.assertIn("_animation_template_enum_items", addon)
            self.assertIn("_apply_animation_template", addon)
            self.assertIn("gpt_director.save_animation_template", addon)
            self.assertIn("gpt_director.load_animation_template", addon)
            self.assertIn("gpt_director.update_animation_template", addon)
            self.assertIn("gpt_director.delete_animation_template", addon)
            self.assertIn("gpt_director_animation_template_choice", addon)
            self.assertIn("_material_template_enum_items", addon)
            self.assertIn("_apply_material_template", addon)
            self.assertIn("gpt_director.save_material_template", addon)
            self.assertIn("gpt_director.load_material_template", addon)
            self.assertIn("gpt_director.update_material_template", addon)
            self.assertIn("gpt_director.delete_material_template", addon)
            self.assertIn("gpt_director_material_template_choice", addon)
            self.assertIn("_object_template_enum_items", addon)
            self.assertIn("_apply_object_template", addon)
            self.assertIn("gpt_director.save_object_template", addon)
            self.assertIn("gpt_director.load_object_template", addon)
            self.assertIn("gpt_director.update_object_template", addon)
            self.assertIn("gpt_director.delete_object_template", addon)
            self.assertIn("gpt_director_object_template_choice", addon)
            self.assertIn("gpt_director.object_motion", addon)
            self.assertIn("CAMERA_MOTION_LABELS", addon)
            self.assertIn("OBJECT_MOTION_LABELS", addon)
            self.assertIn("_apply_camera_motion", addon)
            self.assertIn("_record_camera_motion", addon)
            self.assertIn("_apply_object_motion", addon)
            self.assertIn("_record_object_motion", addon)
            self.assertIn("gpt_director.three_point_lighting", addon)
            self.assertIn("gpt_director.insert_keyframe", addon)
            self.assertIn("_upsert_timeline_marker", addon)
            self.assertIn("timeline_markers", addon)
            self.assertIn("_shot_from_current_scene", addon)
            self.assertIn("_apply_object_snapshots", addon)
            self.assertIn("_scene_preset_from_current_scene", addon)
            self.assertIn("_scene_preset_enum_items", addon)
            self.assertIn("_apply_scene_preset", addon)
            self.assertIn("gpt_director.save_scene_preset", addon)
            self.assertIn("gpt_director.load_scene_preset", addon)
            self.assertIn("gpt_director.update_scene_preset", addon)
            self.assertIn("gpt_director.delete_scene_preset", addon)
            self.assertIn("gpt_director_preset_choice", addon)
            self.assertIn("_render_template_enum_items", addon)
            self.assertIn("_apply_render_template", addon)
            self.assertIn("gpt_director.save_render_template", addon)
            self.assertIn("gpt_director.load_render_template", addon)
            self.assertIn("gpt_director.update_render_template", addon)
            self.assertIn("gpt_director.delete_render_template", addon)
            self.assertIn("gpt_director_render_template_choice", addon)
            self.assertIn("gpt_director_render_output", addon)
            self.assertIn("gpt_director_frame_start", addon)
            self.assertIn("gpt_director_frame_end", addon)
            self.assertIn('"frame_start"', addon)
            self.assertIn('"frame_end"', addon)
            self.assertIn("gpt_director_scene_number", addon)
            self.assertIn("gpt_director_scene_location", addon)
            self.assertIn("gpt_director_scene_environment", addon)
            self.assertIn("gpt_director_scene_time", addon)
            self.assertIn('"scene_number"', addon)
            self.assertIn('"scene_location"', addon)
            self.assertIn('"output_type"', addon)
            self.assertIn('"output_label"', addon)
            self.assertIn("RENDER_OUTPUT_LABELS", addon)
            self.assertIn('"layered": "分层素材包"', addon)
            self.assertIn("_write_layered_manifest", addon)
            self.assertIn('("layered", "分层素材包"', addon)
            self.assertIn("SHOT_STATUS_LABELS", addon)
            self.assertIn("gpt_director_shot_status", addon)
            self.assertIn("_next_render_version", addon)
            self.assertTrue(hasattr(blender_director_project, "build_blender_director_production_manifest"))
            self.assertTrue(hasattr(blender_director_project, "write_blender_director_production_report"))
            self.assertIn("_save_shot_file", addon)
            self.assertIn("GPT_DIRECTOR_PROJECT_READY", bootstrap)
            self.assertIn("gpt_director.add_dialogue_lounge_scene", bootstrap)
            self.assertIn("bpy.ops.wm.read_homefile(use_empty=True)", bootstrap)
            self.assertNotIn("bpy.ops.wm.read_factory_settings", bootstrap)
            self.assertIn('panel["_set_director_simple_view"](bpy.context, True)', bootstrap)

            summary = blender_director_project.summarize_blender_director_metadata(meta_data)
            self.assertIn("资产 0 个", summary)
            self.assertIn("镜头 0 个", summary)
            meta_data["scene_presets"].append({"id": "preset_001", "name": "客厅站位"})
            meta_data["shot_packages"].append(
                {
                    "id": "package_001",
                    "name": "二人对话正反打组",
                    "shots": [{"name": "第一镜"}, {"name": "第二镜"}],
                }
            )
            meta_data["set_packages"].append({"id": "set_package_001", "name": "客厅常用布景"})
            meta_data["render_templates"].append({"id": "render_001", "name": "分镜预览规格"})
            meta_data["light_templates"].append({"id": "light_001", "name": "夜景冷光"})
            meta_data["camera_templates"].append({"id": "camera_001", "name": "正反打机位"})
            meta_data["action_clips"].append({"id": "action_clip_001", "name": "走入停顿", "generated_by": "retarget"})
            meta_data["retarget_profiles"].append({"id": "retarget_001", "name": "Mixamo到主角骨骼"})
            meta_data["retarget_applications"].append({"id": "retarget_apply_001", "name": "走入动作重定向"})
            meta_data["pose_templates"].append({"id": "pose_001", "name": "举手质问"})
            meta_data["animation_templates"].append({"id": "animation_001", "name": "开门走入"})
            meta_data["material_templates"].append({"id": "material_001", "name": "蓝色人偶外观"})
            meta_data["material_applications"].append({"id": "material_application_001", "name": "办公室墙面"})
            meta_data["object_templates"].append({"id": "object_001", "name": "二人对峙站位"})
            meta_data["actors"].append({"id": "actor_001", "name": "陈景川"})
            meta_data["asset_sources"].append({"id": "source_001", "name": "Mixamo动作库"})
            meta_data["asset_libraries"].append({"id": "library_001", "name": "影视资产库"})
            meta_data["asset_library_items"].append({"id": "asset_001", "name": "蓝色人偶"})
            meta_data["ai_workflow_results"].append({"id": "ai_result_001", "payload_name": "AI首帧"})
            meta_data["renders"].append({"output_type": "layered", "output_label": "分层素材包"})
            summary = blender_director_project.summarize_blender_director_metadata(meta_data)
            self.assertIn("输出 1 个", summary)
            self.assertIn("分层素材包 1 个", summary)
            self.assertIn("AI结果回填 1 个", summary)
            self.assertIn("演员位 1 个", summary)
            self.assertIn("场景预设 1 个", summary)
            self.assertIn("镜头包 1 个", summary)
            self.assertIn("布景包 1 个", summary)
            self.assertIn("渲染模板 1 个", summary)
            self.assertIn("灯光模板 1 个", summary)
            self.assertIn("机位模板 1 个", summary)
            self.assertIn("动作片段 1 个", summary)
            self.assertIn("重定向动作片段 1 个", summary)
            self.assertIn("重定向档案 1 个", summary)
            self.assertIn("重定向记录 1 条", summary)
            self.assertIn("姿势模板 1 个", summary)
            self.assertIn("动画片段 1 个", summary)
            self.assertIn("材质模板 1 个", summary)
            self.assertIn("材质应用 1 条", summary)
            self.assertIn("站位模板 1 个", summary)
            self.assertIn("资产源 1 个", summary)
            self.assertIn("资产库 1 个", summary)
            self.assertIn("库资产 1 个", summary)

    def test_prepare_director_project_discovers_shared_asset_library(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            project_root = Path(tmp) / "projects"
            asset_library = Path(tmp) / "shared-assets"
            asset_library.mkdir()
            (asset_library / "sample.glb").write_bytes(b"glb")
            with mock.patch.object(blender_director_project, "DIRECTOR_PROJECT_ROOT", str(project_root)), mock.patch.dict(
                os.environ,
                {"GPT_TOOLBOX_SHARED_ASSET_LIBRARY": str(asset_library)},
            ):
                project = blender_director_project.prepare_blender_director_project(
                    "shared_assets",
                    "\u5171\u4eab\u7d20\u6750\u5e93",
                )

            metadata = json.loads(Path(project["meta_path"]).read_text(encoding="utf-8"))
            addon = Path(project["addon_path"]).read_text(encoding="utf-8")
            self.assertEqual(metadata["default_asset_library_path"], str(asset_library))
            self.assertIn(str(asset_library), addon)
            self.assertIn("def _ensure_default_asset_library", addon)
            self.assertIn("default=DEFAULT_ASSET_LIBRARY_PATH", addon)

    def test_sync_director_project_renders_only_adds_new_images(self):
        scene = WorkflowScene(config={"providers": []}, load_defaults=False)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_a = Path(tmp) / "shot_a.png"
            render_b = Path(tmp) / "shot_b.png"
            render_a.write_bytes(b"fake image a")
            render_b.write_bytes(b"fake image b")
            meta_path = Path(tmp) / "director_project.json"
            meta_path.write_text(
                """
                {
                  "project_id": "director_sync",
                  "project_name": "客厅对话",
                  "project_dir": "%s",
                  "plan": {
                    "scene_prompt": "客厅，有沙发茶几。",
                    "camera_prompt": "35mm中景。"
                  },
                  "actors": [
                    {"id": "actor_001", "name": "陈景川", "role": "主角", "object_names": ["蓝色主角"]}
                  ],
                  "assets": [
                    {"id": "asset_001", "name": "蓝色主角模型", "type": "character", "objects": ["蓝色主角"]}
                  ],
                  "shots": [
                    {
                      "id": "shot_b",
                      "name": "镜头B",
                      "note": "右侧反应，男主从门外走到桌边后停下",
                      "frame_start": 12,
                      "frame_end": 96,
                      "output_type": "still",
                      "actors": [
                        {"id": "actor_001", "name": "陈景川", "role": "主角", "object_names": ["蓝色主角"]}
                      ],
                      "assets": [
                        {"id": "asset_001", "name": "蓝色主角模型", "type": "character", "object_names": ["蓝色主角"]}
                      ]
                    }
                  ],
                  "shot_packages": [
                    {"id": "package_001", "name": "二人对话正反打组", "shots": [{"name": "第一镜"}, {"name": "第二镜"}]}
                  ],
                  "set_packages": [
                    {"id": "set_package_001", "name": "客厅常用布景", "object_count": 3, "collection_count": 1, "object_names": ["沙发", "茶几", "落地灯"]}
                  ],
                  "object_motions": [
                    {"label": "前进", "objects": ["蓝色主角"], "frame_start": 12, "frame_end": 96}
                  ],
                  "render_templates": [
                    {"id": "render_template_001", "name": "分镜预览规格", "output_label": "普通图", "resolution_x": 1280, "resolution_y": 720, "fps": 24}
                  ],
                  "camera_templates": [
                    {"id": "camera_template_001", "name": "正反打机位", "camera": {"name": "Director Camera", "lens": 50}}
                  ],
                  "light_templates": [
                    {"id": "light_template_001", "name": "夜景冷光", "light_count": 3, "lights": [{"name": "Director Key Light"}]}
                  ],
                  "action_clips": [
                    {
                      "id": "action_clip_001",
                      "name": "走入停顿",
                      "action": "WalkStop",
                      "target_armature": "HeroRig",
                      "frame_start": 12,
                      "frame_end": 48,
                      "actor": {"id": "actor_001", "name": "陈景川", "role": "主角"},
                      "source_profile_name": "Mixamo / 角色动作"
                    }
                  ],
                  "pose_templates": [
                    {"id": "pose_template_001", "name": "举手质问", "armature": "HeroRig", "bone_count": 28}
                  ],
                  "animation_templates": [
                    {"id": "animation_template_001", "name": "开门走入", "object_count": 1, "keyframe_count": 4, "frame_start": 12, "frame_end": 96}
                  ],
                  "material_templates": [
                    {"id": "material_template_001", "name": "蓝色人偶外观", "object_count": 1, "material_count": 1, "materials": [{"name": "蓝色材质"}]}
                  ],
                  "material_applications": [
                    {"id": "material_application_001", "name": "办公室墙面材质", "material_name": "OfficeWall", "objects": ["墙面"], "texture_paths": ["%s"]}
                  ],
                  "object_templates": [
                    {"id": "object_template_001", "name": "二人对峙站位", "objects": [{"name": "蓝色主角"}, {"name": "红色反派"}]}
                  ],
                  "renders": [
                    {"path": "%s"},
                    {"path": "%s", "shot_id": "shot_b", "shot_name": "镜头B", "shot_note": "右侧反应", "output_path": "%s"}
                  ]
                }
                """
                % (tmp, str(render_a), str(render_a), str(render_b), str(render_b)),
                encoding="utf-8",
            )

            node = scene.add_node("blender_director_project", QPointF(0, 0))
            node.data["director_project"] = {"meta_path": str(meta_path)}
            node.data["director_synced_renders"] = [str(render_a)]

            captured = {}

            def fake_sync(result):
                captured["result"] = result

            with mock.patch.object(scene, "sync_image_result_to_history", side_effect=fake_sync):
                scene.sync_blender_director_project_renders(node)

            self.assertEqual(captured["result"]["images"], [str(render_b)])
            self.assertEqual(captured["result"]["model"], "Blender 导演台")
            self.assertIn("客厅对话", captured["result"]["prompt"])
            self.assertIn("镜头B", captured["result"]["prompt"])
            self.assertEqual(captured["result"]["blender_render"]["shot_name"], "镜头B")
            self.assertEqual(captured["result"]["blender_project"]["shots"][0]["note"], "右侧反应，男主从门外走到桌边后停下")
            self.assertEqual(captured["result"]["blender_project"]["actor_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["actors"][0]["name"], "陈景川")
            self.assertEqual(captured["result"]["blender_project"]["assets"][0]["name"], "蓝色主角模型")
            self.assertEqual(captured["result"]["blender_project"]["storyboard_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["shot_package_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["shot_packages"][0]["name"], "二人对话正反打组")
            self.assertEqual(captured["result"]["blender_project"]["set_package_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["set_packages"][0]["name"], "客厅常用布景")
            self.assertEqual(captured["result"]["blender_project"]["object_motion_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["object_motions"][0]["objects"], ["蓝色主角"])
            self.assertEqual(captured["result"]["blender_project"]["render_template_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["render_templates"][0]["name"], "分镜预览规格")
            self.assertEqual(captured["result"]["blender_project"]["camera_template_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["camera_templates"][0]["name"], "正反打机位")
            self.assertEqual(captured["result"]["blender_project"]["light_template_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["light_templates"][0]["name"], "夜景冷光")
            self.assertEqual(captured["result"]["blender_project"]["action_clip_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["action_clips"][0]["name"], "走入停顿")
            self.assertEqual(captured["result"]["blender_project"]["action_match_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["action_match_requirement_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["action_unmatched_count"], 0)
            self.assertEqual(captured["result"]["blender_project"]["action_matches"][0]["best_match"]["name"], "走入停顿")
            self.assertEqual(captured["result"]["blender_project"]["object_template_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["object_templates"][0]["name"], "二人对峙站位")
            self.assertEqual(captured["result"]["blender_project"]["pose_template_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["pose_templates"][0]["name"], "举手质问")
            self.assertEqual(captured["result"]["blender_project"]["animation_template_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["animation_templates"][0]["name"], "开门走入")
            self.assertEqual(captured["result"]["blender_project"]["material_template_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["material_templates"][0]["name"], "蓝色人偶外观")
            self.assertEqual(captured["result"]["blender_project"]["material_application_count"], 1)
            self.assertEqual(captured["result"]["blender_project"]["material_applications"][0]["name"], "办公室墙面材质")
            self.assertEqual(captured["result"]["blender_storyboard_entry"]["shot_name"], "镜头B")
            self.assertEqual(captured["result"]["blender_storyboard_entry"]["frame_start"], 12)
            self.assertEqual(captured["result"]["blender_storyboard_entry"]["actors"][0]["name"], "陈景川")
            self.assertEqual(captured["result"]["blender_storyboard_entry"]["assets"][0]["name"], "蓝色主角模型")
            manifest_path = Path(captured["result"]["blender_project"]["storyboard_manifest_path"])
            self.assertTrue(manifest_path.exists())
            production_manifest_path = Path(captured["result"]["blender_project"]["production_manifest_path"])
            self.assertTrue(production_manifest_path.exists())
            production_manifest = json.loads(production_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(production_manifest["shot_count"], 1)
            self.assertEqual(production_manifest["used_asset_count"], 1)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["entries"][0]["shot_name"], "镜头B")
            self.assertEqual(manifest["entries"][0]["actors"][0]["role"], "主角")
            self.assertEqual(manifest["entries"][0]["assets"][0]["type"], "character")
            self.assertEqual(manifest["entries"][0]["frame_start"], 12)
            self.assertEqual(manifest["entries"][0]["frame_end"], 96)
            self.assertEqual(manifest["entries"][0]["preview_path"], str(render_b))
            self.assertEqual(manifest["entries"][0]["output_path"], str(render_b))
            report_path = Path(captured["result"]["blender_project"]["storyboard_report_path"])
            self.assertTrue(report_path.exists())
            csv_path = Path(captured["result"]["blender_project"]["storyboard_csv_path"])
            self.assertTrue(csv_path.exists())
            render_queue_path = Path(captured["result"]["blender_project"]["render_queue_report_path"])
            self.assertTrue(render_queue_path.exists())
            render_queue_csv_path = Path(captured["result"]["blender_project"]["render_queue_csv_path"])
            self.assertTrue(render_queue_csv_path.exists())
            batch_render_jobs_path = Path(captured["result"]["blender_project"]["batch_render_jobs_report_path"])
            self.assertTrue(batch_render_jobs_path.exists())
            batch_render_jobs_csv_path = Path(captured["result"]["blender_project"]["batch_render_jobs_csv_path"])
            self.assertTrue(batch_render_jobs_csv_path.exists())
            batch_render_command_path = Path(captured["result"]["blender_project"]["batch_render_command_path"])
            self.assertTrue(batch_render_command_path.exists())
            batch_render_command_report_path = Path(captured["result"]["blender_project"]["batch_render_command_report_path"])
            self.assertTrue(batch_render_command_report_path.exists())
            batch_render_script_path = Path(captured["result"]["blender_project"]["batch_render_script_path"])
            self.assertTrue(batch_render_script_path.exists())
            render_versions_path = Path(captured["result"]["blender_project"]["render_versions_report_path"])
            self.assertTrue(render_versions_path.exists())
            render_versions_csv_path = Path(captured["result"]["blender_project"]["render_versions_csv_path"])
            self.assertTrue(render_versions_csv_path.exists())
            scene_breakdown_path = Path(captured["result"]["blender_project"]["scene_breakdown_report_path"])
            self.assertTrue(scene_breakdown_path.exists())
            scene_breakdown_csv_path = Path(captured["result"]["blender_project"]["scene_breakdown_csv_path"])
            self.assertTrue(scene_breakdown_csv_path.exists())
            episode_delivery_path = Path(captured["result"]["blender_project"]["episode_delivery_report_path"])
            self.assertTrue(episode_delivery_path.exists())
            episode_delivery_csv_path = Path(captured["result"]["blender_project"]["episode_delivery_csv_path"])
            self.assertTrue(episode_delivery_csv_path.exists())
            episode_delivery_packages_path = Path(captured["result"]["blender_project"]["episode_delivery_packages_report_path"])
            self.assertTrue(episode_delivery_packages_path.exists())
            episode_delivery_packages_csv_path = Path(captured["result"]["blender_project"]["episode_delivery_packages_csv_path"])
            self.assertTrue(episode_delivery_packages_csv_path.exists())
            self.assertTrue(captured["result"]["blender_project"]["episode_delivery_packages"])
            call_sheet_path = Path(captured["result"]["blender_project"]["call_sheet_report_path"])
            self.assertTrue(call_sheet_path.exists())
            call_sheet_csv_path = Path(captured["result"]["blender_project"]["call_sheet_csv_path"])
            self.assertTrue(call_sheet_csv_path.exists())
            actor_schedule_path = Path(captured["result"]["blender_project"]["actor_schedule_report_path"])
            self.assertTrue(actor_schedule_path.exists())
            actor_schedule_csv_path = Path(captured["result"]["blender_project"]["actor_schedule_csv_path"])
            self.assertTrue(actor_schedule_csv_path.exists())
            edit_timeline_path = Path(captured["result"]["blender_project"]["edit_timeline_report_path"])
            self.assertTrue(edit_timeline_path.exists())
            edit_timeline_csv_path = Path(captured["result"]["blender_project"]["edit_timeline_csv_path"])
            self.assertTrue(edit_timeline_csv_path.exists())
            edit_timeline_edl_path = Path(captured["result"]["blender_project"]["edit_timeline_edl_path"])
            self.assertTrue(edit_timeline_edl_path.exists())
            edit_timeline_fcpxml_path = Path(captured["result"]["blender_project"]["edit_timeline_fcpxml_path"])
            self.assertTrue(edit_timeline_fcpxml_path.exists())
            post_handoff_path = Path(captured["result"]["blender_project"]["post_handoff_report_path"])
            self.assertTrue(post_handoff_path.exists())
            post_handoff_csv_path = Path(captured["result"]["blender_project"]["post_handoff_csv_path"])
            self.assertTrue(post_handoff_csv_path.exists())
            continuity_check_path = Path(captured["result"]["blender_project"]["continuity_check_report_path"])
            self.assertTrue(continuity_check_path.exists())
            continuity_check_csv_path = Path(captured["result"]["blender_project"]["continuity_check_csv_path"])
            self.assertTrue(continuity_check_csv_path.exists())
            production_check_path = Path(captured["result"]["blender_project"]["production_check_report_path"])
            self.assertTrue(production_check_path.exists())
            production_check_csv_path = Path(captured["result"]["blender_project"]["production_check_csv_path"])
            self.assertTrue(production_check_csv_path.exists())
            duration_summary_path = Path(captured["result"]["blender_project"]["duration_summary_path"])
            self.assertTrue(duration_summary_path.exists())
            production_report_path = Path(captured["result"]["blender_project"]["production_report_path"])
            self.assertTrue(production_report_path.exists())
            asset_usage_csv_path = Path(captured["result"]["blender_project"]["asset_usage_csv_path"])
            self.assertTrue(asset_usage_csv_path.exists())
            asset_requirements_path = Path(captured["result"]["blender_project"]["asset_requirements_report_path"])
            self.assertTrue(asset_requirements_path.exists())
            asset_requirements_csv_path = Path(captured["result"]["blender_project"]["asset_requirements_csv_path"])
            self.assertTrue(asset_requirements_csv_path.exists())
            asset_ecosystem_path = Path(captured["result"]["blender_project"]["asset_ecosystem_report_path"])
            self.assertTrue(asset_ecosystem_path.exists())
            asset_ecosystem_csv_path = Path(captured["result"]["blender_project"]["asset_ecosystem_csv_path"])
            self.assertTrue(asset_ecosystem_csv_path.exists())
            asset_preflight_path = Path(captured["result"]["blender_project"]["asset_preflight_report_path"])
            self.assertTrue(asset_preflight_path.exists())
            asset_preflight_csv_path = Path(captured["result"]["blender_project"]["asset_preflight_csv_path"])
            self.assertTrue(asset_preflight_csv_path.exists())
            action_matches_path = Path(captured["result"]["blender_project"]["action_matches_report_path"])
            self.assertTrue(action_matches_path.exists())
            action_matches_csv_path = Path(captured["result"]["blender_project"]["action_matches_csv_path"])
            self.assertTrue(action_matches_csv_path.exists())
            ai_workflow_tasks_path = Path(captured["result"]["blender_project"]["ai_workflow_tasks_report_path"])
            self.assertTrue(ai_workflow_tasks_path.exists())
            ai_workflow_tasks_csv_path = Path(captured["result"]["blender_project"]["ai_workflow_tasks_csv_path"])
            self.assertTrue(ai_workflow_tasks_csv_path.exists())
            ai_workflow_handoff_path = Path(captured["result"]["blender_project"]["ai_workflow_handoff_report_path"])
            self.assertTrue(ai_workflow_handoff_path.exists())
            ai_workflow_handoff_csv_path = Path(captured["result"]["blender_project"]["ai_workflow_handoff_csv_path"])
            self.assertTrue(ai_workflow_handoff_csv_path.exists())
            ai_workflow_results_path = Path(captured["result"]["blender_project"]["ai_workflow_results_report_path"])
            self.assertTrue(ai_workflow_results_path.exists())
            ai_workflow_results_csv_path = Path(captured["result"]["blender_project"]["ai_workflow_results_csv_path"])
            self.assertTrue(ai_workflow_results_csv_path.exists())
            dashboard_path = Path(captured["result"]["blender_project"]["project_dashboard_path"])
            self.assertTrue(dashboard_path.exists())
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("镜头B", report_html)
            self.assertIn("演员", report_html)
            self.assertIn("资产", report_html)
            self.assertIn("蓝色主角模型", report_html)
            self.assertIn("陈景川", report_html)
            self.assertIn("主角", report_html)
            self.assertIn("帧段", report_html)
            self.assertEqual(node.data["director_project"]["storyboard_manifest_path"], str(manifest_path))
            self.assertEqual(node.data["director_project"]["storyboard_report_path"], str(report_path))
            self.assertEqual(node.data["director_project"]["storyboard_csv_path"], str(csv_path))
            self.assertEqual(node.data["director_project"]["render_queue_report_path"], str(render_queue_path))
            self.assertEqual(node.data["director_project"]["render_queue_csv_path"], str(render_queue_csv_path))
            self.assertEqual(node.data["director_project"]["batch_render_jobs_report_path"], str(batch_render_jobs_path))
            self.assertEqual(node.data["director_project"]["batch_render_jobs_csv_path"], str(batch_render_jobs_csv_path))
            self.assertEqual(node.data["director_project"]["batch_render_command_path"], str(batch_render_command_path))
            self.assertEqual(node.data["director_project"]["batch_render_command_report_path"], str(batch_render_command_report_path))
            self.assertEqual(node.data["director_project"]["batch_render_script_path"], str(batch_render_script_path))
            self.assertEqual(node.data["director_project"]["render_versions_report_path"], str(render_versions_path))
            self.assertEqual(node.data["director_project"]["render_versions_csv_path"], str(render_versions_csv_path))
            self.assertEqual(node.data["director_project"]["scene_breakdown_report_path"], str(scene_breakdown_path))
            self.assertEqual(node.data["director_project"]["scene_breakdown_csv_path"], str(scene_breakdown_csv_path))
            self.assertEqual(node.data["director_project"]["episode_delivery_report_path"], str(episode_delivery_path))
            self.assertEqual(node.data["director_project"]["episode_delivery_csv_path"], str(episode_delivery_csv_path))
            self.assertEqual(node.data["director_project"]["episode_delivery_packages_report_path"], str(episode_delivery_packages_path))
            self.assertEqual(node.data["director_project"]["episode_delivery_packages_csv_path"], str(episode_delivery_packages_csv_path))
            self.assertTrue(node.data["director_project"]["episode_delivery_packages"])
            self.assertEqual(node.data["director_project"]["call_sheet_report_path"], str(call_sheet_path))
            self.assertEqual(node.data["director_project"]["call_sheet_csv_path"], str(call_sheet_csv_path))
            self.assertEqual(node.data["director_project"]["actor_schedule_report_path"], str(actor_schedule_path))
            self.assertEqual(node.data["director_project"]["actor_schedule_csv_path"], str(actor_schedule_csv_path))
            self.assertEqual(node.data["director_project"]["edit_timeline_report_path"], str(edit_timeline_path))
            self.assertEqual(node.data["director_project"]["edit_timeline_csv_path"], str(edit_timeline_csv_path))
            self.assertEqual(node.data["director_project"]["edit_timeline_edl_path"], str(edit_timeline_edl_path))
            self.assertEqual(node.data["director_project"]["edit_timeline_fcpxml_path"], str(edit_timeline_fcpxml_path))
            self.assertEqual(node.data["director_project"]["post_handoff_report_path"], str(post_handoff_path))
            self.assertEqual(node.data["director_project"]["post_handoff_csv_path"], str(post_handoff_csv_path))
            self.assertEqual(node.data["director_project"]["continuity_check_report_path"], str(continuity_check_path))
            self.assertEqual(node.data["director_project"]["continuity_check_csv_path"], str(continuity_check_csv_path))
            self.assertEqual(node.data["director_project"]["production_check_report_path"], str(production_check_path))
            self.assertEqual(node.data["director_project"]["production_check_csv_path"], str(production_check_csv_path))
            self.assertEqual(node.data["director_project"]["duration_summary_path"], str(duration_summary_path))
            self.assertEqual(node.data["director_project"]["production_manifest_path"], str(production_manifest_path))
            self.assertEqual(node.data["director_project"]["production_report_path"], str(production_report_path))
            self.assertEqual(node.data["director_project"]["asset_usage_csv_path"], str(asset_usage_csv_path))
            self.assertEqual(node.data["director_project"]["asset_requirements_report_path"], str(asset_requirements_path))
            self.assertEqual(node.data["director_project"]["asset_requirements_csv_path"], str(asset_requirements_csv_path))
            self.assertEqual(node.data["director_project"]["asset_ecosystem_report_path"], str(asset_ecosystem_path))
            self.assertEqual(node.data["director_project"]["asset_ecosystem_csv_path"], str(asset_ecosystem_csv_path))
            self.assertEqual(node.data["director_project"]["asset_preflight_report_path"], str(asset_preflight_path))
            self.assertEqual(node.data["director_project"]["asset_preflight_csv_path"], str(asset_preflight_csv_path))
            self.assertEqual(node.data["director_project"]["action_matches_report_path"], str(action_matches_path))
            self.assertEqual(node.data["director_project"]["action_matches_csv_path"], str(action_matches_csv_path))
            self.assertEqual(node.data["director_project"]["ai_workflow_tasks_report_path"], str(ai_workflow_tasks_path))
            self.assertEqual(node.data["director_project"]["ai_workflow_tasks_csv_path"], str(ai_workflow_tasks_csv_path))
            self.assertEqual(node.data["director_project"]["ai_workflow_handoff_report_path"], str(ai_workflow_handoff_path))
            self.assertEqual(node.data["director_project"]["ai_workflow_handoff_csv_path"], str(ai_workflow_handoff_csv_path))
            self.assertEqual(node.data["director_project"]["ai_workflow_results_report_path"], str(ai_workflow_results_path))
            self.assertEqual(node.data["director_project"]["ai_workflow_results_csv_path"], str(ai_workflow_results_csv_path))
            self.assertEqual(node.data["director_project"]["project_dashboard_path"], str(dashboard_path))
            self.assertIn(str(render_a), node.data["director_synced_renders"])
            self.assertIn(str(render_b), node.data["director_synced_renders"])
            self.assertIn("镜头 1 个", node.data["director_project_summary"])
            self.assertIn("输出 2 个", node.data["director_project_summary"])

    def test_sync_director_project_renders_uses_preview_images_only(self):
        messages = []
        scene = WorkflowScene(config={"providers": []}, status_callback=messages.append, load_defaults=False)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            preview = Path(tmp) / "shot_preview.png"
            video = Path(tmp) / "shot.mp4"
            sequence_dir = Path(tmp) / "shot_frames"
            preview.write_bytes(b"fake preview")
            video.write_bytes(b"fake video")
            sequence_dir.mkdir()
            (sequence_dir / "frame_0001.png").write_bytes(b"fake frame")
            meta_path = Path(tmp) / "director_project.json"
            meta_path.write_text(
                json.dumps(
                    {
                        "project_id": "director_sync_preview",
                        "project_name": "视频输出测试",
                        "project_dir": tmp,
                        "renders": [
                            {
                                "path": str(preview),
                                "preview_path": str(preview),
                                "output_path": str(video),
                                "output_type": "video",
                                "shot_id": "shot_video",
                                "shot_name": "视频镜头",
                            },
                            {
                                "path": str(sequence_dir),
                                "output_path": str(sequence_dir),
                                "output_type": "sequence",
                                "shot_id": "shot_seq",
                                "shot_name": "序列镜头",
                            },
                            {
                                "path": str(video),
                                "output_path": str(video),
                                "output_type": "video",
                                "shot_id": "shot_video_no_preview",
                                "shot_name": "无预览视频",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            node = scene.add_node("blender_director_project", QPointF(0, 0))
            node.data["director_project"] = {"meta_path": str(meta_path)}
            captured = []

            with mock.patch.object(scene, "sync_image_result_to_history", side_effect=captured.append):
                scene.sync_blender_director_project_renders(node)

            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["images"], [str(preview)])
            self.assertEqual(captured[0]["blender_render"]["output_path"], str(video))
            self.assertIn(str(preview), node.data["director_synced_renders"])
            self.assertEqual(node.data["image_path"], str(preview))

    def test_storyboard_manifest_and_report_include_layered_assets(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            layer_dir = Path(tmp) / "shot_layers"
            layer_dir.mkdir()
            beauty = layer_dir / "shot_beauty.png"
            transparent = layer_dir / "shot_transparent.png"
            manifest = layer_dir / "manifest.json"
            beauty.write_bytes(b"fake beauty")
            transparent.write_bytes(b"fake transparent")
            manifest.write_text("{}", encoding="utf-8")
            metadata = {
                "project_id": "storyboard_layered",
                "project_name": "分层分镜测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_layered",
                        "name": "分层镜头",
                        "output_type": "layered",
                        "output_label": "分层素材包",
                        "shot_status": "approved",
                        "shot_status_label": "已定稿",
                        "assets": [
                            {"id": "asset_layered", "name": "主角透明素材", "type": "character"}
                        ],
                    }
                ],
                "renders": [
                    {
                        "shot_id": "shot_layered",
                        "path": str(beauty),
                        "preview_path": str(beauty),
                        "output_path": str(layer_dir),
                        "output_type": "layered",
                        "output_label": "分层素材包",
                        "render_version": 2,
                        "manifest_path": str(manifest),
                        "layer_paths": {"beauty": str(beauty), "transparent": str(transparent)},
                    }
                ],
            }

            storyboard = blender_director_project.build_blender_director_storyboard(metadata)
            self.assertEqual(storyboard[0]["layer_paths"]["transparent"], str(transparent))
            self.assertEqual(storyboard[0]["manifest_path"], str(manifest))
            self.assertEqual(storyboard[0]["shot_status_label"], "已定稿")
            self.assertEqual(storyboard[0]["render_version"], 2)
            self.assertEqual(storyboard[0]["assets"][0]["name"], "主角透明素材")
            manifest_path = Path(blender_director_project.write_blender_director_storyboard_manifest(metadata))
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest_data["entries"][0]["layer_paths"]["beauty"], str(beauty))
            self.assertEqual(manifest_data["entries"][0]["shot_status"], "approved")
            self.assertEqual(manifest_data["entries"][0]["render_version"], 2)
            self.assertEqual(manifest_data["entries"][0]["assets"][0]["type"], "character")
            report_path = Path(blender_director_project.write_blender_director_storyboard_report(metadata))
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("素材层", report_html)
            self.assertIn("状态/版本", report_html)
            self.assertIn("已定稿", report_html)
            self.assertIn("v2", report_html)
            self.assertIn("主角透明素材", report_html)
            self.assertIn("beauty", report_html)
            self.assertIn("transparent", report_html)
            self.assertIn("manifest", report_html)
            csv_path = Path(blender_director_project.write_blender_director_storyboard_csv(metadata))
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("镜头ID", csv_text)
            self.assertIn("shot_layered", csv_text)
            self.assertIn("主角透明素材", csv_text)

    def test_render_queue_manifest_report_and_csv_track_pending_shots(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "render_queue_test",
                "project_name": "渲染队列测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "已完成镜头",
                        "frame_start": 1,
                        "frame_end": 48,
                        "shot_status": "approved",
                        "shot_status_label": "已定稿",
                        "output_type": "still",
                        "output_label": "普通图",
                        "actors": [{"id": "actor_a", "name": "男主"}],
                        "assets": [{"id": "asset_a", "name": "会议桌"}],
                    },
                    {
                        "id": "shot_b",
                        "name": "待渲染镜头",
                        "frame_start": 49,
                        "frame_end": 96,
                        "output_type": "sequence",
                        "output_label": "图片序列",
                    },
                ],
                "renders": [
                    {
                        "shot_id": "shot_a",
                        "path": str(render_path),
                        "preview_path": str(render_path),
                        "output_path": str(render_path),
                        "render_version": 2,
                    }
                ],
            }

            queue = blender_director_project.build_blender_director_render_queue(metadata)
            self.assertEqual(queue["shot_count"], 2)
            self.assertEqual(queue["rendered_count"], 1)
            self.assertEqual(queue["pending_count"], 1)
            self.assertEqual(queue["entries"][0]["queue_status_label"], "已渲染")
            self.assertEqual(queue["entries"][0]["duration_frames"], 48)
            self.assertEqual(queue["entries"][1]["queue_status_label"], "待渲染")

            manifest_path = Path(blender_director_project.write_blender_director_render_queue_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_render_queue_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_render_queue_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["pending_count"], 1)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("渲染队列测试 - 渲染队列", report_html)
            self.assertIn("待渲染镜头", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("队列状态", csv_text)
            self.assertIn("图片序列", csv_text)

    def test_batch_render_jobs_list_pending_shots_and_blocked_reasons(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_done.png"
            render_path.write_bytes(b"png")
            metadata = {
                "project_id": "batch_render_test",
                "project_name": "批量渲染测试",
                "project_dir": tmp,
                "fps": 24,
                "shots": [
                    {
                        "id": "shot_done",
                        "name": "已渲染镜头",
                        "frame_start": 1,
                        "frame_end": 48,
                        "output_type": "still",
                        "output_label": "普通图",
                    },
                    {
                        "id": "shot_ready",
                        "name": "可渲染镜头",
                        "episode_number": "第1集",
                        "scene_number": "场次01",
                        "scene_location": "办公室",
                        "frame_start": 49,
                        "frame_end": 72,
                        "output_type": "sequence",
                        "output_label": "图片序列",
                    },
                    {
                        "id": "shot_blocked",
                        "name": "缺信息镜头",
                    },
                ],
                "renders": [{"shot_id": "shot_done", "path": str(render_path), "preview_path": str(render_path)}],
            }

            jobs = blender_director_project.build_blender_director_batch_render_jobs(metadata)

            self.assertEqual(jobs["job_count"], 2)
            self.assertEqual(jobs["ready_count"], 1)
            self.assertEqual(jobs["blocked_count"], 1)
            self.assertEqual(jobs["skipped_rendered_count"], 1)
            self.assertEqual(jobs["jobs"][0]["shot_id"], "shot_ready")
            self.assertEqual(jobs["jobs"][0]["status"], "ready")
            self.assertEqual(jobs["jobs"][0]["duration_seconds"], 1.0)
            self.assertEqual(jobs["jobs"][1]["status"], "blocked")
            self.assertIn("缺少帧段", jobs["jobs"][1]["blocked_reasons"])
            self.assertIn("缺少输出类型", jobs["jobs"][1]["blocked_reasons"])

            manifest_path = Path(blender_director_project.write_blender_director_batch_render_jobs_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_batch_render_jobs_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_batch_render_jobs_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["ready_count"], 1)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("批量渲染测试 - 批量渲染任务", report_html)
            self.assertIn("可渲染镜头", report_html)
            self.assertIn("缺少输出类型", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("优先级", csv_text)
            self.assertIn("图片序列", csv_text)

    def test_batch_render_command_writes_background_launcher_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            project_dir = Path(tmp)
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir()
            addon_path = scripts_dir / "gpt_director_panel.py"
            blend_path = project_dir / "director.blend"
            meta_path = project_dir / "director_project.json"
            addon_path.write_text("# addon placeholder\n", encoding="utf-8")
            blend_path.write_bytes(b"blend")
            metadata = {
                "project_id": "batch_command_test",
                "project_name": "后台渲染命令测试",
                "project_dir": str(project_dir),
                "meta_path": str(meta_path),
                "addon_path": str(addon_path),
                "blend_path": str(blend_path),
                "shots": [
                    {
                        "id": "shot_ready",
                        "name": "待渲染镜头",
                        "frame_start": 1,
                        "frame_end": 24,
                        "output_type": "still",
                        "output_label": "普通图",
                    }
                ],
                "renders": [],
            }

            data = blender_director_project.write_blender_director_batch_render_command(metadata)

            script_path = Path(data["script_path"])
            command_path = Path(data["command_path"])
            report_path = Path(data["report_path"])
            self.assertTrue(script_path.exists())
            self.assertTrue(command_path.exists())
            self.assertTrue(report_path.exists())
            script_text = script_path.read_text(encoding="utf-8")
            command = json.loads(command_path.read_text(encoding="utf-8"))
            report_html = report_path.read_text(encoding="utf-8")
            compile(script_text, str(script_path), "exec")
            self.assertEqual(command["ready_count"], 1)
            self.assertIn("--background", command["command_template"])
            self.assertIn("gpt_director.render_pending_shots", script_text)
            self.assertIn("后台渲染命令测试 - 后台批量渲染命令", report_html)
            self.assertIn("待渲染任务", report_html)

    def test_render_versions_groups_outputs_and_marks_latest(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            first = Path(tmp) / "shot_a_v1.png"
            second = Path(tmp) / "shot_a_v2.png"
            missing = Path(tmp) / "missing.png"
            first.write_bytes(b"v1")
            second.write_bytes(b"v2")
            metadata = {
                "project_id": "render_versions_test",
                "project_name": "镜头版本测试",
                "project_dir": tmp,
                "shots": [{"id": "shot_a", "name": "镜头A"}],
                "renders": [
                    {
                        "shot_id": "shot_a",
                        "shot_name": "镜头A",
                        "path": str(first),
                        "preview_path": str(first),
                        "output_path": str(first),
                        "render_version": 1,
                        "created_at": "2026-07-10 08:00:00",
                    },
                    {
                        "shot_id": "shot_a",
                        "shot_name": "镜头A",
                        "path": str(second),
                        "preview_path": str(second),
                        "output_path": str(missing),
                        "render_version": 2,
                        "created_at": "2026-07-10 08:10:00",
                    },
                ],
            }

            versions = blender_director_project.build_blender_director_render_versions(metadata)

            self.assertEqual(versions["render_count"], 2)
            self.assertEqual(versions["shot_count"], 1)
            self.assertFalse(versions["entries"][0]["is_latest_for_shot"])
            self.assertTrue(versions["entries"][1]["is_latest_for_shot"])
            self.assertEqual(versions["entries"][1]["missing_file_count"], 1)

            manifest_path = Path(blender_director_project.write_blender_director_render_versions_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_render_versions_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_render_versions_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["render_count"], 2)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("镜头版本测试 - 镜头版本索引", report_html)
            self.assertIn("v2", report_html)
            self.assertIn("最新", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("是否最新", csv_text)
            self.assertIn("镜头A", csv_text)

    def test_scene_breakdown_manifest_report_and_csv_group_shots(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "scene_breakdown_test",
                "project_name": "分场表测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "开场推进",
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "scene_environment": "interior",
                        "scene_environment_label": "内景",
                        "scene_time": "day",
                        "scene_time_label": "日",
                        "frame_start": 1,
                        "frame_end": 48,
                    },
                    {
                        "id": "shot_b",
                        "name": "反打质问",
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "scene_environment": "interior",
                        "scene_environment_label": "内景",
                        "scene_time": "day",
                        "scene_time_label": "日",
                        "frame_start": 49,
                        "frame_end": 96,
                    },
                    {
                        "id": "shot_c",
                        "name": "未分场镜头",
                        "frame_start": 97,
                        "frame_end": 120,
                    },
                ],
                "renders": [
                    {"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}
                ],
            }

            breakdown = blender_director_project.build_blender_director_scene_breakdown(metadata)

            self.assertEqual(breakdown["scene_count"], 1)
            self.assertEqual(breakdown["unassigned_shot_count"], 1)
            scene = breakdown["scenes"][0]
            self.assertEqual(scene["scene_number"], "场次01")
            self.assertEqual(scene["scene_location"], "会议室")
            self.assertEqual(scene["shot_count"], 2)
            self.assertEqual(scene["rendered_shot_count"], 1)
            self.assertEqual(scene["pending_shot_count"], 1)
            self.assertEqual(scene["total_frames"], 96)

            manifest_path = Path(blender_director_project.write_blender_director_scene_breakdown_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_scene_breakdown_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_scene_breakdown_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["scenes"][0]["shots"][1]["shot_name"], "反打质问")
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("分场表测试 - 分场表", report_html)
            self.assertIn("会议室", report_html)
            self.assertIn("未分场镜头", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("场次", csv_text)
            self.assertIn("反打质问", csv_text)

    def test_episode_delivery_groups_shots_by_episode_and_scene(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "episode_delivery_test",
                "project_name": "分集交付测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "第一集开场",
                        "episode_number": "第1集",
                        "episode_name": "总部风暴",
                        "scene_number": "场次01",
                        "scene_location": "总部大厅",
                        "frame_start": 1,
                        "frame_end": 48,
                        "actors": [{"id": "actor_a", "name": "男主", "role": "主角"}],
                        "assets": [{"id": "asset_table", "name": "会议桌", "type": "prop"}],
                    },
                    {
                        "id": "shot_b",
                        "name": "第一集反打",
                        "episode_number": "第1集",
                        "episode_name": "总部风暴",
                        "scene_number": "场次01",
                        "scene_location": "总部大厅",
                        "frame_start": 49,
                        "frame_end": 72,
                        "actors": [{"id": "actor_a", "name": "男主", "role": "主角"}],
                    },
                    {
                        "id": "shot_c",
                        "name": "第二集开场",
                        "episode_number": "第2集",
                        "episode_name": "老宅会议",
                        "scene_number": "场次02",
                        "scene_location": "陈家老宅",
                        "frame_start": 1,
                        "frame_end": 24,
                    },
                ],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}],
            }

            delivery = blender_director_project.build_blender_director_episode_delivery(metadata)

            self.assertEqual(delivery["episode_count"], 2)
            self.assertEqual(delivery["shot_count"], 3)
            self.assertEqual(delivery["rendered_shot_count"], 1)
            self.assertEqual(delivery["pending_shot_count"], 2)
            self.assertEqual(delivery["total_frames"], 96)
            first_episode = delivery["episodes"][0]
            self.assertEqual(first_episode["episode_number"], "第1集")
            self.assertEqual(first_episode["episode_name"], "总部风暴")
            self.assertEqual(first_episode["shot_count"], 2)
            self.assertEqual(first_episode["scene_count"], 1)
            self.assertEqual(first_episode["actor_count"], 1)
            self.assertEqual(first_episode["asset_count"], 1)
            self.assertEqual(first_episode["scenes"][0]["rendered_shot_count"], 1)
            self.assertEqual(first_episode["scenes"][0]["pending_shot_count"], 1)

            manifest_path = Path(blender_director_project.write_blender_director_episode_delivery_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_episode_delivery_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_episode_delivery_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["episodes"][1]["episode_name"], "老宅会议")
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("分集交付测试 - 分集交付清单", report_html)
            self.assertIn("总部风暴", report_html)
            self.assertIn("陈家老宅", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("分集", csv_text)
            self.assertIn("第一集开场", csv_text)

    def test_episode_delivery_packages_bundle_episode_renders_and_assets(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            project_dir = Path(tmp)
            assets_dir = project_dir / "assets"
            renders_dir = project_dir / "renders"
            assets_dir.mkdir()
            renders_dir.mkdir()
            asset_path = assets_dir / "hero.glb"
            render_path = renders_dir / "shot_a.png"
            asset_path.write_bytes(b"asset")
            render_path.write_bytes(b"render")
            metadata = {
                "project_id": "episode_package_test",
                "project_name": "分集包测试",
                "project_dir": str(project_dir),
                "assets": [{"id": "asset_hero", "name": "主角模型", "type": "character", "path": str(asset_path)}],
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "第一集开场",
                        "episode_number": "第1集",
                        "episode_name": "总部风暴",
                        "scene_number": "场次01",
                        "scene_location": "总部大厅",
                        "frame_start": 1,
                        "frame_end": 24,
                        "assets": [{"id": "asset_hero", "name": "主角模型", "type": "character"}],
                    }
                ],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path), "output_path": str(render_path)}],
            }

            packages = blender_director_project.write_blender_director_episode_delivery_packages(metadata)

            self.assertEqual(packages["episode_count"], 1)
            self.assertTrue(Path(packages["manifest_path"]).exists())
            self.assertTrue(Path(packages["report_path"]).exists())
            self.assertTrue(Path(packages["csv_path"]).exists())
            package_path = Path(packages["packages"][0]["package_path"])
            self.assertTrue(package_path.exists())
            with zipfile.ZipFile(package_path) as zf:
                names = set(zf.namelist())
                self.assertIn("episode_manifest.json", names)
                self.assertIn("episode_delivery.csv", names)
                self.assertIn("renders/shot_a.png", names)
                self.assertIn("assets/hero.glb", names)
                episode_manifest = json.loads(zf.read("episode_manifest.json").decode("utf-8"))
            self.assertEqual(episode_manifest["episode"]["episode_name"], "总部风暴")
            report_html = Path(packages["report_path"]).read_text(encoding="utf-8")
            self.assertIn("分集包测试 - 分集交付包", report_html)
            self.assertIn(str(package_path), report_html)

    def test_call_sheet_summarizes_scene_actors_assets_and_pending_shots(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "call_sheet_test",
                "project_name": "拍摄单测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "开场推进",
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "scene_environment": "interior",
                        "scene_environment_label": "内景",
                        "scene_time": "day",
                        "scene_time_label": "日",
                        "frame_start": 1,
                        "frame_end": 48,
                        "actors": [{"id": "actor_a", "name": "男主", "role": "主角"}],
                        "assets": [{"id": "asset_table", "name": "会议桌", "type": "prop"}],
                    },
                    {
                        "id": "shot_b",
                        "name": "女主入场",
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "scene_environment": "interior",
                        "scene_environment_label": "内景",
                        "scene_time": "day",
                        "scene_time_label": "日",
                        "frame_start": 49,
                        "frame_end": 96,
                        "actors": [{"id": "actor_b", "name": "女主", "role": "女主"}],
                        "assets": [{"id": "asset_table", "name": "会议桌", "type": "prop"}],
                    },
                ],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}],
            }

            call_sheet = blender_director_project.build_blender_director_call_sheet(metadata)

            self.assertEqual(call_sheet["scene_count"], 1)
            self.assertEqual(call_sheet["shot_count"], 2)
            self.assertEqual(call_sheet["pending_shot_count"], 1)
            scene = call_sheet["scenes"][0]
            self.assertEqual(scene["scene_location"], "会议室")
            self.assertEqual(len(scene["actors"]), 2)
            self.assertEqual(len(scene["assets"]), 1)
            self.assertEqual(scene["total_frames"], 96)

            manifest_path = Path(blender_director_project.write_blender_director_call_sheet_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_call_sheet_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_call_sheet_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["scenes"][0]["actors"][1]["name"], "女主")
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("拍摄单测试 - 拍摄单", report_html)
            self.assertIn("会议桌", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("拍摄", report_html)
            self.assertIn("女主入场", csv_text)

    def test_actor_schedule_manifest_report_and_csv_group_actor_shots(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "actor_schedule_test",
                "project_name": "演员调度测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "男女主对峙",
                        "frame_start": 1,
                        "frame_end": 48,
                        "actors": [
                            {"id": "actor_hero", "name": "陈景川", "role": "男主"},
                            {"id": "actor_heroine", "name": "林知夏", "role": "女主"},
                        ],
                    },
                    {
                        "id": "shot_b",
                        "name": "男主独白",
                        "frame_start": 49,
                        "frame_end": 96,
                        "actors": [{"id": "actor_hero", "name": "陈景川", "role": "男主"}],
                    },
                    {
                        "id": "shot_c",
                        "name": "空镜",
                        "frame_start": 97,
                        "frame_end": 120,
                    },
                ],
                "renders": [
                    {
                        "shot_id": "shot_a",
                        "path": str(render_path),
                        "preview_path": str(render_path),
                        "output_path": str(render_path),
                    }
                ],
            }

            schedule = blender_director_project.build_blender_director_actor_schedule(metadata)

            self.assertEqual(schedule["actor_count"], 2)
            self.assertEqual(schedule["unassigned_shot_count"], 1)
            hero = schedule["actors"][0]
            self.assertEqual(hero["name"], "陈景川")
            self.assertEqual(hero["shot_count"], 2)
            self.assertEqual(hero["rendered_shot_count"], 1)
            self.assertEqual(hero["pending_shot_count"], 1)
            self.assertEqual(hero["total_frames"], 96)

            manifest_path = Path(blender_director_project.write_blender_director_actor_schedule_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_actor_schedule_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_actor_schedule_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["actors"][0]["shots"][0]["shot_name"], "男女主对峙")
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("演员调度测试 - 演员调度", report_html)
            self.assertIn("陈景川", report_html)
            self.assertIn("未绑定演员镜头", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("演员ID", csv_text)
            self.assertIn("男主独白", csv_text)

    def test_duration_summary_counts_total_frames_and_seconds(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_id": "duration_test",
                "project_name": "时长统计测试",
                "project_dir": tmp,
                "fps": 24,
                "shots": [
                    {"id": "shot_a", "name": "镜头A", "frame_start": 1, "frame_end": 48},
                    {"id": "shot_b", "name": "镜头B", "frame_start": 49, "frame_end": 96},
                    {"id": "shot_c", "name": "无帧段镜头"},
                ],
                "renders": [],
            }

            summary = blender_director_project.build_blender_director_duration_summary(metadata)

            self.assertEqual(summary["shot_count"], 3)
            self.assertEqual(summary["shots_with_duration"], 2)
            self.assertEqual(summary["shots_without_duration"], 1)
            self.assertEqual(summary["total_frames"], 96)
            self.assertEqual(summary["total_seconds"], 4.0)
            self.assertEqual(summary["average_shot_seconds"], 2.0)
            path = Path(blender_director_project.write_blender_director_duration_summary(metadata))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["entries"][0]["duration_seconds"], 2.0)

    def test_edit_timeline_accumulates_shot_times_and_exports_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "edit_timeline_test",
                "project_name": "剪辑时间线测试",
                "project_dir": tmp,
                "fps": 24,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "开场镜头",
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "frame_start": 1,
                        "frame_end": 48,
                        "actors": [{"id": "actor_a", "name": "男主", "role": "主角"}],
                        "output_type": "still",
                        "output_label": "普通图",
                    },
                    {
                        "id": "shot_b",
                        "name": "反打镜头",
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "frame_start": 49,
                        "frame_end": 72,
                    },
                ],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}],
            }

            timeline = blender_director_project.build_blender_director_edit_timeline(metadata)

            self.assertEqual(timeline["shot_count"], 2)
            self.assertEqual(timeline["total_frames"], 72)
            self.assertEqual(timeline["total_seconds"], 3.0)
            self.assertEqual(timeline["entries"][0]["timeline_start"], "00:00.000")
            self.assertEqual(timeline["entries"][0]["timeline_end"], "00:02.000")
            self.assertEqual(timeline["entries"][1]["timeline_start"], "00:02.000")
            self.assertEqual(timeline["entries"][1]["timeline_end"], "00:03.000")

            manifest_path = Path(blender_director_project.write_blender_director_edit_timeline_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_edit_timeline_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_edit_timeline_csv(metadata))
            edl = blender_director_project.build_blender_director_edit_decision_list(metadata)
            edl_path = Path(blender_director_project.write_blender_director_edit_decision_list(metadata))
            fcpxml_path = Path(blender_director_project.write_blender_director_final_cut_xml(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["entries"][1]["duration_seconds"], 1.0)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("剪辑时间线测试 - 剪辑时间线", report_html)
            self.assertIn("反打镜头", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("时间线开始", csv_text)
            self.assertIn("会议室", csv_text)
            self.assertEqual(edl["fps"], 24)
            self.assertEqual(edl["entries"][0]["source_out"], "00:00:02:00")
            self.assertEqual(edl["entries"][0]["record_in"], "00:00:00:00")
            self.assertEqual(edl["entries"][0]["record_out"], "00:00:02:00")
            self.assertEqual(edl["entries"][1]["record_in"], "00:00:02:00")
            self.assertEqual(edl["entries"][1]["record_out"], "00:00:03:00")
            edl_text = edl_path.read_text(encoding="utf-8")
            self.assertIn("TITLE: 剪辑时间线测试", edl_text)
            self.assertIn("FCM: NON-DROP FRAME", edl_text)
            self.assertIn("* SHOT ID: shot_a", edl_text)
            fcpxml_text = fcpxml_path.read_text(encoding="utf-8")
            self.assertIn("<fcpxml", fcpxml_text)
            self.assertIn("剪辑时间线测试", fcpxml_text)
            self.assertIn("开场镜头", fcpxml_text)
            self.assertIn("48/24s", fcpxml_text)

    def test_post_handoff_collects_layered_outputs_and_missing_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            layer_dir = Path(tmp) / "layers"
            layer_dir.mkdir()
            beauty = layer_dir / "beauty.png"
            transparent = layer_dir / "transparent.png"
            manifest_file = layer_dir / "manifest.json"
            missing_output = layer_dir / "missing.png"
            beauty.write_bytes(b"beauty")
            transparent.write_bytes(b"transparent")
            manifest_file.write_text("{}", encoding="utf-8")
            metadata = {
                "project_id": "post_handoff_test",
                "project_name": "后期交接测试",
                "project_dir": tmp,
                "fps": 24,
                "shots": [
                    {
                        "id": "shot_layered",
                        "name": "分层镜头",
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "frame_start": 1,
                        "frame_end": 48,
                        "output_type": "layered",
                        "output_label": "分层素材包",
                    },
                    {
                        "id": "shot_missing",
                        "name": "缺文件镜头",
                        "frame_start": 49,
                        "frame_end": 72,
                    },
                ],
                "renders": [
                    {
                        "shot_id": "shot_layered",
                        "path": str(beauty),
                        "preview_path": str(beauty),
                        "output_path": str(layer_dir),
                        "output_type": "layered",
                        "output_label": "分层素材包",
                        "render_version": 3,
                        "manifest_path": str(manifest_file),
                        "layer_paths": {"beauty": str(beauty), "transparent": str(transparent)},
                    },
                    {
                        "shot_id": "shot_missing",
                        "path": str(missing_output),
                        "preview_path": str(missing_output),
                        "output_path": str(missing_output),
                    },
                ],
            }

            handoff = blender_director_project.build_blender_director_post_handoff(metadata)

            self.assertEqual(handoff["shot_count"], 2)
            self.assertEqual(handoff["layered_count"], 1)
            self.assertEqual(handoff["transparent_count"], 1)
            self.assertEqual(handoff["missing_file_shot_count"], 1)
            self.assertEqual(handoff["entries"][0]["timeline_start"], "00:00.000")
            self.assertEqual(handoff["entries"][0]["timeline_end"], "00:02.000")
            self.assertTrue(handoff["entries"][0]["layers"][1]["exists"])

            manifest_path = Path(blender_director_project.write_blender_director_post_handoff_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_post_handoff_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_post_handoff_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["entries"][0]["render_version"], 3)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("后期交接测试 - 后期交接清单", report_html)
            self.assertIn("transparent", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("分层素材", csv_text)
            self.assertIn(str(missing_output), csv_text)

    def test_production_check_reports_deterministic_project_issues(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            missing_output = Path(tmp) / "missing.png"
            metadata = {
                "project_id": "production_check_test",
                "project_name": "制作问题检查测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "重复镜头",
                        "frame_start": 1,
                        "frame_end": 48,
                        "camera": {"name": "Camera"},
                        "actors": [{"id": "actor_a", "name": "男主"}],
                        "assets": [{"id": "asset_a", "name": "会议桌"}],
                        "scene_number": "场次01",
                        "scene_location": "会议室",
                        "shot_status": "approved",
                        "shot_status_label": "已定稿",
                    },
                    {
                        "id": "shot_a",
                        "name": "重复镜头",
                        "frame_start": 40,
                        "frame_end": 72,
                    },
                ],
                "renders": [
                    {
                        "shot_id": "shot_a",
                        "path": str(missing_output),
                        "preview_path": str(missing_output),
                        "output_path": str(missing_output),
                    }
                ],
            }

            check = blender_director_project.build_blender_director_production_check(metadata)
            codes = {item["code"] for item in check["issues"]}

            self.assertGreaterEqual(check["error_count"], 1)
            self.assertIn("duplicate_shot_id", codes)
            self.assertIn("frame_overlap", codes)
            self.assertIn("missing_scene", codes)
            self.assertIn("missing_actors", codes)
            self.assertIn("missing_assets", codes)
            self.assertIn("missing_camera", codes)
            self.assertIn("missing_output_file", codes)

            manifest_path = Path(blender_director_project.write_blender_director_production_check_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_production_check_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_production_check_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["project_name"], "制作问题检查测试")
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("制作问题检查测试 - 制作问题检查", report_html)
            self.assertIn("镜头ID重复", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("级别", csv_text)
            self.assertIn("缺少演员记录", csv_text)

    def test_continuity_check_groups_shots_by_scene_and_flags_missing_data(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"png")
            metadata = {
                "project_id": "continuity_test",
                "project_name": "连续性检查测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "完整镜头",
                        "scene_number": "场次01",
                        "scene_location": "办公室",
                        "frame_start": 1,
                        "frame_end": 48,
                        "actors": [{"id": "actor_a", "name": "主角"}],
                        "assets": [{"id": "asset_a", "name": "办公桌"}],
                    },
                    {
                        "id": "shot_b",
                        "name": "缺数据镜头",
                        "scene_number": "场次01",
                        "scene_location": "办公室",
                    },
                ],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}],
            }

            check = blender_director_project.build_blender_director_continuity_check(metadata)

            self.assertEqual(check["scene_count"], 1)
            self.assertEqual(check["shot_count"], 2)
            self.assertEqual(check["issue_count"], 4)
            self.assertEqual(check["scenes"][0]["shots"][0]["issues"], [])
            self.assertEqual(
                set(check["scenes"][0]["shots"][1]["issues"]),
                {"缺少演员", "缺少资产", "缺少帧段", "尚未渲染"},
            )

            manifest_path = Path(blender_director_project.write_blender_director_continuity_check_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_continuity_check_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_continuity_check_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["issue_count"], 4)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("连续性检查测试 - 连续性检查", report_html)
            self.assertIn("缺数据镜头", report_html)
            self.assertIn("缺少帧段", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("问题", csv_text)
            self.assertIn("尚未渲染", csv_text)

    def test_production_manifest_and_report_summarize_progress_and_assets(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "production_test",
                "project_name": "制作清单测试",
                "project_dir": tmp,
                "assets": [
                    {"id": "asset_hero", "name": "蓝色主角模型", "type": "character", "format": "glb"},
                    {"id": "asset_table", "name": "会议桌", "type": "prop", "format": "obj"},
                ],
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "镜头A",
                        "shot_status": "approved",
                        "shot_status_label": "已定稿",
                        "output_type": "still",
                        "output_label": "普通图",
                        "assets": [
                            {"id": "asset_hero", "name": "蓝色主角模型", "type": "character"}
                        ],
                    },
                    {
                        "id": "shot_b",
                        "name": "镜头B",
                        "shot_status": "draft",
                        "shot_status_label": "草稿",
                        "output_type": "layered",
                        "output_label": "分层素材包",
                    },
                ],
                "renders": [
                    {
                        "shot_id": "shot_a",
                        "path": str(render_path),
                        "preview_path": str(render_path),
                        "output_path": str(render_path),
                        "render_version": 3,
                    }
                ],
                "retarget_profiles": [
                    {
                        "id": "retarget_mixamo_hero",
                        "name": "Mixamo到主角骨骼",
                        "source_armature": "MixamoRig",
                        "target_armature": "HeroRig",
                        "mapped_bone_count": 55,
                        "unmapped_source_count": 2,
                        "unmapped_target_count": 1,
                        "rest_pose_alignment": {
                            "enabled": True,
                            "mismatch_bone_count": 4,
                            "max_angle_degrees": 18.5,
                            "bake_step": 1,
                        },
                        "root_motion": {"enabled": True, "effective_scale": 1.2},
                    }
                ],
                "action_clips": [
                    {
                        "id": "retarget_walk",
                        "name": "走入停顿（重定向）",
                        "action": "HeroRig_Walk_retarget",
                        "target_armature": "HeroRig",
                        "generated_by": "retarget",
                        "retarget_profile_name": "Mixamo到主角骨骼",
                        "retarget_quality": {
                            "copied_fcurve_count": 96,
                            "skipped_fcurve_count": 3,
                            "mapped_bone_count": 55,
                            "unmapped_source_count": 2,
                            "unmapped_target_count": 1,
                            "rest_pose_mismatch_bone_count": 4,
                            "rest_pose_max_angle_degrees": 18.5,
                            "root_motion_scale": 1.2,
                        },
                    }
                ],
                "retarget_applications": [
                    {
                        "profile_name": "Mixamo到主角骨骼",
                        "source_action": "Walk",
                        "target_action": "HeroRig_Walk_retarget",
                        "target_armature": "HeroRig",
                        "status": "applied",
                        "copied_fcurve_count": 96,
                        "skipped_fcurve_count": 3,
                        "root_motion_scale": 1.2,
                        "action_clip": {"id": "retarget_walk", "name": "走入停顿（重定向）"},
                        "action_matches": {"matched_count": 1, "requirement_count": 1, "unmatched_count": 0},
                        "applied_at": "2026-07-10 17:00:00",
                    }
                ],
            }

            manifest = blender_director_project.build_blender_director_production_manifest(metadata)
            self.assertEqual(manifest["shot_count"], 2)
            self.assertEqual(manifest["rendered_shot_count"], 1)
            self.assertEqual(manifest["pending_shot_count"], 1)
            self.assertEqual(manifest["approved_shot_count"], 1)
            self.assertEqual(manifest["asset_count"], 2)
            self.assertEqual(manifest["used_asset_count"], 1)
            self.assertEqual(manifest["unused_asset_count"], 1)
            self.assertEqual(manifest["unused_assets"][0]["name"], "会议桌")
            self.assertEqual(manifest["assets"][0]["used_by_shots"][0]["shot_name"], "镜头A")
            self.assertEqual(manifest["asset_usage"][0]["name"], "蓝色主角模型")
            self.assertEqual(manifest["asset_usage"][0]["shots"][0]["shot_id"], "shot_a")
            self.assertEqual(manifest["retarget_summary"]["ready_clip_count"], 1)
            self.assertEqual(manifest["retarget_summary"]["mapped_bone_count"], 55)
            self.assertEqual(manifest["retarget_summary"]["rest_pose_max_angle_degrees"], 18.5)

            manifest_path = Path(blender_director_project.write_blender_director_production_manifest(metadata))
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest_data["shots"][0]["render_version"], 3)
            self.assertEqual(manifest_data["assets"][0]["used_by_shots"][0]["shot_id"], "shot_a")
            self.assertEqual(manifest_data["retarget_summary"]["success_count"], 1)
            report_path = Path(blender_director_project.write_blender_director_production_report(metadata))
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("制作清单测试 - 制作清单", report_html)
            self.assertIn("已渲染", report_html)
            self.assertIn("未渲染", report_html)
            self.assertIn("蓝色主角模型", report_html)
            self.assertIn("会议桌", report_html)
            self.assertIn("引用镜头", report_html)
            self.assertIn("重定向动作质量", report_html)
            self.assertIn("Mixamo到主角骨骼", report_html)
            self.assertIn("根运动比例", report_html)
            retarget_manifest_path = Path(blender_director_project.write_blender_director_retarget_summary_manifest(metadata))
            retarget_manifest = json.loads(retarget_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(retarget_manifest["ready_clip_count"], 1)
            retarget_report_path = Path(blender_director_project.write_blender_director_retarget_summary_report(metadata))
            retarget_report_html = retarget_report_path.read_text(encoding="utf-8")
            self.assertIn("重定向质量报告", retarget_report_html)
            self.assertIn("走入停顿（重定向）", retarget_report_html)
            self.assertIn("最大轴向差", retarget_report_html)
            retarget_csv_path = Path(blender_director_project.write_blender_director_retarget_summary_csv(metadata))
            retarget_csv = retarget_csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("Rest Pose差异骨骼", retarget_csv)
            self.assertIn("走入停顿（重定向）", retarget_csv)
            usage_csv_path = Path(blender_director_project.write_blender_director_asset_usage_csv(metadata))
            usage_csv = usage_csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("资产ID", usage_csv)
            self.assertIn("蓝色主角模型", usage_csv)
            self.assertIn("镜头A", usage_csv)

    def test_asset_requirements_report_marks_missing_actor_models_and_assets(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            library_dir = Path(tmp) / "library"
            character_dir = library_dir / "characters"
            prop_dir = library_dir / "props"
            character_dir.mkdir(parents=True)
            prop_dir.mkdir(parents=True)
            missing_actor_candidate = character_dir / "black_agent.glb"
            missing_actor_candidate.write_bytes(b"glb")
            missing_car_candidate = prop_dir / "black_car.glb"
            missing_car_candidate.write_bytes(b"glb")
            metadata = {
                "project_id": "asset_requirements_test",
                "project_name": "资产需求测试",
                "project_dir": tmp,
                "actors": [
                    {"id": "actor_ready", "name": "蓝色主角", "role": "主角", "objects": [{"name": "Hero"}]}
                ],
                "assets": [
                    {"id": "asset_table", "name": "会议桌", "type": "prop", "format": "obj"}
                ],
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "镜头A",
                        "actors": [
                            {"id": "actor_ready", "name": "蓝色主角", "role": "主角"},
                            {"id": "actor_missing", "name": "黑衣人", "role": "临时反派"},
                        ],
                        "assets": [
                            {"id": "asset_table", "name": "会议桌", "type": "prop"},
                            {"id": "asset_missing", "name": "黑色轿车", "type": "vehicle"},
                        ],
                    }
                ],
                "asset_library_items": [
                    {
                        "id": "candidate_black_agent",
                        "name": "黑衣人",
                        "path": str(missing_actor_candidate),
                        "relative_path": "characters/black_agent.glb",
                        "kind_hint": "character",
                        "format": "glb",
                        "favorite": True,
                    },
                    {
                        "id": "candidate_black_car",
                        "name": "黑色轿车",
                        "path": str(missing_car_candidate),
                        "relative_path": "props/black_car.glb",
                        "kind_hint": "prop",
                        "format": "glb",
                    },
                ],
            }

            requirements = blender_director_project.build_blender_director_asset_requirements(metadata)

            self.assertEqual(requirements["requirement_count"], 4)
            self.assertEqual(requirements["available_count"], 2)
            self.assertEqual(requirements["missing_count"], 2)
            self.assertEqual(requirements["missing_with_candidate_count"], 2)
            missing_names = {item["name"] for item in requirements["requirements"] if not item["available"]}
            self.assertEqual(missing_names, {"黑衣人", "黑色轿车"})
            missing_actor = next(item for item in requirements["requirements"] if item["name"] == "黑衣人")
            self.assertEqual(missing_actor["best_library_candidate"]["id"], "candidate_black_agent")

            manifest_path = Path(blender_director_project.write_blender_director_asset_requirements_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_asset_requirements_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_asset_requirements_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["missing_count"], 2)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("资产需求测试 - 资产需求清单", report_html)
            self.assertIn("缺素材", report_html)
            self.assertIn("黑衣人", report_html)
            self.assertIn("缺项有本地候选", report_html)
            self.assertIn("candidate_black_agent", json.dumps(manifest, ensure_ascii=False))
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("资产类型", csv_text)
            self.assertIn("黑色轿车", csv_text)
            self.assertIn("本地库候选", csv_text)

    def test_asset_ecosystem_report_tracks_sources_files_licenses_and_imports(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            project_dir = Path(tmp)
            library_dir = project_dir / "open_assets"
            project_assets = project_dir / "assets"
            library_dir.mkdir()
            project_assets.mkdir()
            hero_source = library_dir / "characters" / "hero.glb"
            hero_source.parent.mkdir()
            hero_source.write_bytes(b"glb")
            walk_source = library_dir / "actions" / "walk.bvh"
            walk_source.parent.mkdir()
            walk_source.write_bytes(b"bvh")
            imported_hero = project_assets / "hero.glb"
            imported_hero.write_bytes(b"glb")
            missing_prop = library_dir / "props" / "missing_chair.glb"
            metadata = {
                "project_id": "asset_ecosystem_test",
                "project_name": "资产生态测试",
                "project_dir": tmp,
                "asset_sources": [
                    {
                        "id": "source_open",
                        "name": "本地开源库",
                        "path": str(library_dir),
                        "profile_id": "sketchfab_opengameart",
                        "profile_name": "Sketchfab / OpenGameArt 本地下载库",
                        "item_count": 3,
                        "asset_browser_catalog_count": 1,
                    }
                ],
                "asset_libraries": [
                    {
                        "id": "library_open",
                        "name": "open_assets",
                        "path": str(library_dir),
                        "source_profile_id": "sketchfab_opengameart",
                        "source_profile_name": "Sketchfab / OpenGameArt 本地下载库",
                        "item_count": 3,
                        "asset_browser_catalog_count": 1,
                        "asset_browser_catalog_path": str(library_dir / "blender_assets.cats.txt"),
                    }
                ],
                "asset_library_items": [
                    {
                        "id": "hero_item",
                        "name": "蓝色主角",
                        "path": str(hero_source),
                        "relative_path": "characters/hero.glb",
                        "library_id": "library_open",
                        "library_path": str(library_dir),
                        "kind_hint": "character",
                        "format": "glb",
                        "source_profile_id": "sketchfab_opengameart",
                        "source_profile_name": "Sketchfab / OpenGameArt 本地下载库",
                        "license": "CC-BY",
                        "favorite": True,
                        "tags": "主角 hero",
                        "usage_count": 1,
                        "asset_browser_catalog_id": "catalog-hero",
                        "asset_browser_catalog_path": "Characters/Heroes",
                        "asset_browser_catalog_name": "Heroes",
                    },
                    {
                        "id": "walk_item",
                        "name": "走路动作",
                        "path": str(walk_source),
                        "relative_path": "actions/walk.bvh",
                        "library_id": "library_open",
                        "library_path": str(library_dir),
                        "kind_hint": "action",
                        "format": "bvh",
                        "source_profile_id": "mixamo",
                        "source_profile_name": "Mixamo / 角色动作",
                        "usage_note": "走入镜头可用",
                        "usage_count": 1,
                    },
                    {
                        "id": "missing_prop",
                        "name": "缺失椅子",
                        "path": str(missing_prop),
                        "relative_path": "props/missing_chair.glb",
                        "library_id": "library_open",
                        "library_path": str(library_dir),
                        "kind_hint": "prop",
                        "format": "glb",
                    },
                ],
                "assets": [
                    {
                        "id": "asset_hero",
                        "name": "蓝色主角",
                        "type": "character",
                        "format": "glb",
                        "path": str(imported_hero),
                        "source_path": str(hero_source),
                        "library_item_id": "hero_item",
                        "library_relative_path": "characters/hero.glb",
                        "source_profile_id": "sketchfab_opengameart",
                        "source_profile_name": "Sketchfab / OpenGameArt 本地下载库",
                        "license": "CC-BY",
                        "objects": ["Hero"],
                        "control_root": "蓝色主角 导演控制器",
                        "control_objects": ["蓝色主角 导演控制器", "蓝色主角 导演控制圈"],
                        "controls": ["root_empty", "viewport_control_ring", "drag_transform", "object_motion", "select_asset"],
                    }
                ],
            }

            ecosystem = blender_director_project.build_blender_director_asset_ecosystem(metadata)

            self.assertEqual(ecosystem["source_count"], 1)
            self.assertEqual(ecosystem["library_count"], 1)
            self.assertEqual(ecosystem["library_item_count"], 3)
            self.assertEqual(ecosystem["available_item_count"], 2)
            self.assertEqual(ecosystem["missing_file_count"], 1)
            self.assertEqual(ecosystem["missing_license_count"], 1)
            self.assertEqual(ecosystem["favorite_count"], 1)
            self.assertEqual(ecosystem["tagged_count"], 2)
            self.assertEqual(ecosystem["imported_item_count"], 1)
            self.assertEqual(ecosystem["controllable_asset_count"], 1)
            self.assertEqual(ecosystem["asset_browser_catalog_count"], 1)
            self.assertEqual(ecosystem["action_item_count"], 1)
            self.assertEqual(ecosystem["ready_action_count"], 1)
            self.assertIn("库资产缺文件 1 个", ecosystem["health_warnings"])
            missing_row = next(item for item in ecosystem["items"] if item["id"] == "missing_prop")
            self.assertIn("缺文件", missing_row["status_label"])
            self.assertIn("缺授权来源", missing_row["status_label"])

            manifest_path = Path(blender_director_project.write_blender_director_asset_ecosystem_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_asset_ecosystem_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_asset_ecosystem_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["imported_item_count"], 1)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("资产生态测试 - 资产生态报告", report_html)
            self.assertIn("开源生态来源", report_html)
            self.assertIn("缺授权来源", report_html)
            self.assertIn("蓝色主角", report_html)
            self.assertIn("Blender Catalog", report_html)
            self.assertIn("Characters/Heroes", report_html)
            self.assertIn("可控工程资产", report_html)
            self.assertIn("蓝色主角 导演控制器", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("授权", csv_text)
            self.assertIn("Blender Catalog", csv_text)
            self.assertIn("Characters/Heroes", csv_text)
            self.assertIn("缺失椅子", csv_text)
            self.assertIn("可控", csv_text)

            preflight = blender_director_project.build_blender_director_asset_preflight(metadata)
            self.assertEqual(preflight["library_item_count"], 3)
            self.assertEqual(preflight["blocked_count"], 1)
            self.assertGreaterEqual(preflight["review_count"], 1)
            self.assertGreaterEqual(preflight["warning_count"], 2)
            missing_preflight = next(item for item in preflight["items"] if item["id"] == "missing_prop")
            self.assertEqual(missing_preflight["preflight_status_label"], "阻断")
            self.assertIn("库资产文件不存在", [issue["title"] for issue in missing_preflight["issues"]])
            walk_preflight = next(item for item in preflight["items"] if item["id"] == "walk_item")
            self.assertIn(walk_preflight["preflight_status_label"], {"需复核", "可导入（有建议）"})
            preflight_manifest_path = Path(blender_director_project.write_blender_director_asset_preflight_manifest(metadata))
            preflight_report_path = Path(blender_director_project.write_blender_director_asset_preflight_report(metadata))
            preflight_csv_path = Path(blender_director_project.write_blender_director_asset_preflight_csv(metadata))
            preflight_manifest = json.loads(preflight_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(preflight_manifest["blocked_count"], 1)
            preflight_report_html = preflight_report_path.read_text(encoding="utf-8")
            self.assertIn("资产导入预检", preflight_report_html)
            self.assertIn("修复建议", preflight_report_html)
            preflight_csv = preflight_csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("预检状态", preflight_csv)
            self.assertIn("缺失椅子", preflight_csv)

    def test_action_matches_rank_reusable_clips_and_flag_missing_actions(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_id": "action_match_test",
                "project_name": "动作匹配测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_walk",
                        "name": "男主进门",
                        "note": "男主从门外走到桌边后停下",
                        "actors": [{"id": "actor_hero", "name": "陈景川", "role": "男主"}],
                    },
                    {
                        "id": "shot_wave",
                        "name": "挥手告别",
                        "note": "男主向门外挥手告别",
                        "actors": [{"id": "actor_hero", "name": "陈景川", "role": "男主"}],
                    },
                ],
                "action_clips": [
                    {
                        "id": "action_clip_walk_stop",
                        "name": "走入停顿",
                        "note": "从门外走到桌边后停顿",
                        "action": "WalkStop",
                        "actor": {"id": "actor_hero", "name": "陈景川", "role": "男主"},
                        "frame_start": 1,
                        "frame_end": 48,
                        "source_profile_name": "Mixamo / 角色动作",
                        "library_relative_path": "walk/mixamo_walk.fbx",
                    }
                ],
                "asset_library_items": [
                    {
                        "id": "action_run",
                        "name": "快速奔跑",
                        "kind_hint": "action",
                        "source_profile_name": "Mixamo / 角色动作",
                        "relative_path": "run/fast_run.fbx",
                        "tags": "奔跑 run",
                    }
                ],
            }

            matches = blender_director_project.build_blender_director_action_matches(metadata)

            self.assertEqual(matches["requirement_count"], 2)
            self.assertEqual(matches["matched_count"], 1)
            self.assertEqual(matches["unmatched_count"], 1)
            walk = next(item for item in matches["requirements"] if item["shot_id"] == "shot_walk")
            wave = next(item for item in matches["requirements"] if item["shot_id"] == "shot_wave")
            self.assertEqual(walk["status"], "matched")
            self.assertEqual(walk["best_match"]["name"], "走入停顿")
            self.assertGreaterEqual(walk["best_match"]["score"], 0.8)
            self.assertIn("动作词：", "；".join(walk["best_match"]["reasons"]))
            self.assertEqual(wave["status"], "unmatched")
            self.assertEqual(wave["best_match"], {})

            manifest_path = Path(blender_director_project.write_blender_director_action_matches_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_action_matches_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_action_matches_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["matched_count"], 1)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("动作匹配测试 - 动作匹配清单", report_html)
            self.assertIn("走入停顿", report_html)
            self.assertIn("Mixamo / 角色动作", report_html)
            self.assertIn("无合适候选", report_html)
            self.assertIn("骨骼重定向", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("Blender Action", csv_text)
            self.assertIn("WalkStop", csv_text)
            self.assertIn("待补动作", csv_text)

    def test_ai_workflow_tasks_package_shots_assets_and_motion_needs(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            preview_path = Path(tmp) / "shot_ai.png"
            preview_path.write_bytes(b"png")
            library_dir = Path(tmp) / "open_library"
            library_dir.mkdir()
            umbrella_path = library_dir / "umbrella.glb"
            umbrella_path.write_bytes(b"glb")
            metadata = {
                "project_id": "ai_workflow_test",
                "project_name": "AI工作流测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_ai",
                        "name": "雨夜挥手",
                        "note": "女主撑伞在雨夜街口向远处挥手告别",
                        "scene_number": "场次03",
                        "scene_location": "街口",
                        "output_type": "video",
                        "output_label": "视频",
                        "frame_start": 1,
                        "frame_end": 72,
                        "actors": [{"id": "actor_heroine", "name": "女主", "role": "主角"}],
                        "assets": [{"id": "asset_umbrella", "name": "雨伞", "type": "prop"}],
                    }
                ],
                "renders": [
                    {
                        "shot_id": "shot_ai",
                        "path": str(preview_path),
                        "preview_path": str(preview_path),
                        "output_path": str(preview_path),
                    }
                ],
                "asset_library_items": [
                    {
                        "id": "candidate_umbrella",
                        "name": "雨伞",
                        "path": str(umbrella_path),
                        "relative_path": "props/umbrella.glb",
                        "kind_hint": "prop",
                        "format": "glb",
                    }
                ],
            }

            tasks = blender_director_project.build_blender_director_ai_workflow_tasks(metadata)

            self.assertEqual(tasks["shot_count"], 1)
            self.assertEqual(tasks["task_count"], 3)
            task_types = {item["type"] for item in tasks["tasks"]}
            self.assertEqual(task_types, {"image_to_video", "asset_generation", "motion_generation"})
            visual = next(item for item in tasks["tasks"] if item["type"] == "image_to_video")
            self.assertEqual(visual["status"], "ready_with_reference")
            self.assertEqual(visual["inputs"]["reference_image"]["path"], str(preview_path))
            asset_task = next(item for item in tasks["tasks"] if item["type"] == "asset_generation")
            self.assertEqual(asset_task["status"], "ready_with_candidates")
            umbrella_requirement = next(
                item
                for item in asset_task["inputs"]["missing_requirements"]
                if item["name"] == "雨伞"
            )
            self.assertEqual(
                umbrella_requirement["best_library_candidate"]["id"],
                "candidate_umbrella",
            )
            motion_task = next(item for item in tasks["tasks"] if item["type"] == "motion_generation")
            self.assertEqual(motion_task["status"], "needs_motion")

            manifest_path = Path(blender_director_project.write_blender_director_ai_workflow_tasks_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_ai_workflow_tasks_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_ai_workflow_tasks_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["task_count"], 3)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("AI工作流测试 - AI 工作流任务包", report_html)
            self.assertIn("图生视频", report_html)
            self.assertIn("资产生成/替换", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("任务类型", csv_text)
            self.assertIn("雨夜挥手", csv_text)

            handoff = blender_director_project.write_blender_director_ai_workflow_handoff_package(metadata)
            self.assertEqual(handoff["task_count"], 3)
            self.assertEqual(handoff["result_inbox_count"], 3)
            handoff_dir = Path(handoff["handoff_dir"])
            self.assertTrue(handoff_dir.exists())
            self.assertTrue(Path(handoff["manifest_path"]).exists())
            self.assertTrue(Path(handoff["report_path"]).exists())
            self.assertTrue(Path(handoff["csv_path"]).exists())
            self.assertTrue(Path(handoff["readme_path"]).exists())
            visual_job = next(item for item in handoff["jobs"] if item["task_type"] == "image_to_video")
            self.assertTrue(Path(visual_job["prompt_path"]).exists())
            self.assertTrue(Path(visual_job["task_manifest_path"]).exists())
            self.assertTrue(Path(visual_job["result_dir"]).is_dir())
            self.assertTrue(Path(visual_job["result_readme_path"]).exists())
            self.assertEqual(visual_job["expected_output"]["label"], "视频镜头")
            self.assertIn("AI 工作包与结果收件箱", Path(handoff["report_path"]).read_text(encoding="utf-8"))

    def test_ai_workflow_results_report_tracks_registered_outputs(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            image_path = Path(tmp) / "ai_frame.png"
            asset_path = Path(tmp) / "ai_prop.glb"
            missing_path = Path(tmp) / "missing_ai_video.mp4"
            image_path.write_bytes(b"png")
            asset_path.write_bytes(b"glb")
            metadata = {
                "project_id": "ai_result_test",
                "project_name": "AI结果测试",
                "project_dir": tmp,
                "ai_workflow_tasks": {
                    "tasks": [
                        {
                            "id": "ai_visual_shot_ai",
                            "type": "image_to_video",
                            "type_label": "图生视频/镜头延展",
                            "shot_id": "shot_ai",
                            "shot_name": "雨夜挥手",
                        }
                    ]
                },
                "ai_workflow_results": [
                    {
                        "id": "ai_result_frame",
                        "task_id": "ai_visual_shot_ai",
                        "result_type": "image",
                        "target_type": "render",
                        "path": str(image_path),
                        "payload_name": "AI首帧",
                        "note": "外部工具生成首帧",
                        "registered_at": "2026-07-10 18:00:00",
                    },
                    {
                        "id": "ai_result_missing_video",
                        "task_id": "ai_visual_shot_ai",
                        "result_type": "video",
                        "target_type": "attachment",
                        "path": str(missing_path),
                        "payload_name": "缺失视频",
                    },
                ],
                "assets": [
                    {
                        "id": "asset_ai_prop",
                        "name": "AI道具",
                        "path": str(asset_path),
                        "generated_by": "ai_workflow",
                        "ai_task_id": "ai_assets_shot_ai",
                        "ai_result_type": "asset",
                    }
                ],
            }

            results = blender_director_project.build_blender_director_ai_workflow_results(metadata)

            self.assertEqual(results["result_count"], 3)
            self.assertEqual(results["file_exists_count"], 2)
            self.assertEqual(results["missing_file_count"], 1)
            self.assertEqual(results["render_count"], 1)
            self.assertEqual(results["asset_count"], 1)
            frame = next(item for item in results["results"] if item["id"] == "ai_result_frame")
            self.assertEqual(frame["task_type_label"], "图生视频/镜头延展")
            self.assertEqual(frame["shot_name"], "雨夜挥手")

            manifest_path = Path(blender_director_project.write_blender_director_ai_workflow_results_manifest(metadata))
            report_path = Path(blender_director_project.write_blender_director_ai_workflow_results_report(metadata))
            csv_path = Path(blender_director_project.write_blender_director_ai_workflow_results_csv(metadata))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["result_count"], 3)
            report_html = report_path.read_text(encoding="utf-8")
            self.assertIn("AI结果测试 - AI 结果回填台账", report_html)
            self.assertIn("AI首帧", report_html)
            self.assertIn("文件缺失", report_html)
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("结果ID", csv_text)
            self.assertIn("AI道具", csv_text)

    def test_project_dashboard_links_core_reports(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "shot_a.png"
            render_path.write_bytes(b"fake image")
            metadata = {
                "project_id": "dashboard_test",
                "project_name": "工程总览测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "开场镜头",
                        "shot_status": "approved",
                        "shot_status_label": "已定稿",
                    },
                    {"id": "shot_b", "name": "待渲染镜头"},
                ],
                "assets": [{"id": "asset_a", "name": "主角模型", "type": "character"}],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}],
                "ai_workflow_results": [
                    {
                        "id": "ai_result_dashboard",
                        "task_id": "ai_visual_shot_a",
                        "result_type": "image",
                        "target_type": "render",
                        "path": str(render_path),
                        "payload_name": "AI首帧",
                    }
                ],
                "retarget_profiles": [
                    {
                        "id": "retarget_hero",
                        "name": "动作库到主角",
                        "mapped_bone_count": 40,
                        "rest_pose_alignment": {"mismatch_bone_count": 3, "max_angle_degrees": 12},
                    }
                ],
                "action_clips": [
                    {
                        "id": "retarget_idle",
                        "name": "站定（重定向）",
                        "generated_by": "retarget",
                        "retarget_quality": {"mapped_bone_count": 40, "rest_pose_mismatch_bone_count": 3},
                    }
                ],
                "retarget_applications": [
                    {"status": "failed", "profile_name": "动作库到主角", "message": "测试失败记录"}
                ],
            }
            metadata["storyboard_report_path"] = blender_director_project.write_blender_director_storyboard_report(metadata)
            metadata["storyboard_csv_path"] = blender_director_project.write_blender_director_storyboard_csv(metadata)
            metadata["render_queue_report_path"] = blender_director_project.write_blender_director_render_queue_report(metadata)
            metadata["render_queue_csv_path"] = blender_director_project.write_blender_director_render_queue_csv(metadata)
            metadata["batch_render_jobs_report_path"] = blender_director_project.write_blender_director_batch_render_jobs_report(metadata)
            metadata["batch_render_jobs_csv_path"] = blender_director_project.write_blender_director_batch_render_jobs_csv(metadata)
            batch_render_command = blender_director_project.write_blender_director_batch_render_command(metadata)
            metadata["batch_render_script_path"] = batch_render_command["script_path"]
            metadata["batch_render_command_path"] = batch_render_command["command_path"]
            metadata["batch_render_command_report_path"] = batch_render_command["report_path"]
            metadata["render_versions_report_path"] = blender_director_project.write_blender_director_render_versions_report(metadata)
            metadata["render_versions_csv_path"] = blender_director_project.write_blender_director_render_versions_csv(metadata)
            metadata["scene_breakdown_report_path"] = blender_director_project.write_blender_director_scene_breakdown_report(metadata)
            metadata["scene_breakdown_csv_path"] = blender_director_project.write_blender_director_scene_breakdown_csv(metadata)
            metadata["episode_delivery_report_path"] = blender_director_project.write_blender_director_episode_delivery_report(metadata)
            metadata["episode_delivery_csv_path"] = blender_director_project.write_blender_director_episode_delivery_csv(metadata)
            episode_packages = blender_director_project.write_blender_director_episode_delivery_packages(metadata)
            metadata["episode_delivery_packages_manifest_path"] = episode_packages["manifest_path"]
            metadata["episode_delivery_packages_report_path"] = episode_packages["report_path"]
            metadata["episode_delivery_packages_csv_path"] = episode_packages["csv_path"]
            metadata["episode_delivery_packages"] = episode_packages["packages"]
            metadata["call_sheet_report_path"] = blender_director_project.write_blender_director_call_sheet_report(metadata)
            metadata["call_sheet_csv_path"] = blender_director_project.write_blender_director_call_sheet_csv(metadata)
            metadata["actor_schedule_report_path"] = blender_director_project.write_blender_director_actor_schedule_report(metadata)
            metadata["actor_schedule_csv_path"] = blender_director_project.write_blender_director_actor_schedule_csv(metadata)
            metadata["edit_timeline_report_path"] = blender_director_project.write_blender_director_edit_timeline_report(metadata)
            metadata["edit_timeline_csv_path"] = blender_director_project.write_blender_director_edit_timeline_csv(metadata)
            metadata["edit_timeline_edl_path"] = blender_director_project.write_blender_director_edit_decision_list(metadata)
            metadata["edit_timeline_fcpxml_path"] = blender_director_project.write_blender_director_final_cut_xml(metadata)
            metadata["post_handoff_report_path"] = blender_director_project.write_blender_director_post_handoff_report(metadata)
            metadata["post_handoff_csv_path"] = blender_director_project.write_blender_director_post_handoff_csv(metadata)
            metadata["continuity_check_report_path"] = blender_director_project.write_blender_director_continuity_check_report(metadata)
            metadata["continuity_check_csv_path"] = blender_director_project.write_blender_director_continuity_check_csv(metadata)
            metadata["production_check_report_path"] = blender_director_project.write_blender_director_production_check_report(metadata)
            metadata["production_check_csv_path"] = blender_director_project.write_blender_director_production_check_csv(metadata)
            metadata["duration_summary_path"] = blender_director_project.write_blender_director_duration_summary(metadata)
            metadata["production_report_path"] = blender_director_project.write_blender_director_production_report(metadata)
            metadata["asset_usage_csv_path"] = blender_director_project.write_blender_director_asset_usage_csv(metadata)
            metadata["asset_requirements_report_path"] = blender_director_project.write_blender_director_asset_requirements_report(metadata)
            metadata["asset_requirements_csv_path"] = blender_director_project.write_blender_director_asset_requirements_csv(metadata)
            metadata["asset_ecosystem_report_path"] = blender_director_project.write_blender_director_asset_ecosystem_report(metadata)
            metadata["asset_ecosystem_csv_path"] = blender_director_project.write_blender_director_asset_ecosystem_csv(metadata)
            metadata["asset_preflight_report_path"] = blender_director_project.write_blender_director_asset_preflight_report(metadata)
            metadata["asset_preflight_csv_path"] = blender_director_project.write_blender_director_asset_preflight_csv(metadata)
            metadata["action_matches_report_path"] = blender_director_project.write_blender_director_action_matches_report(metadata)
            metadata["action_matches_csv_path"] = blender_director_project.write_blender_director_action_matches_csv(metadata)
            metadata["ai_workflow_tasks_report_path"] = blender_director_project.write_blender_director_ai_workflow_tasks_report(metadata)
            metadata["ai_workflow_tasks_csv_path"] = blender_director_project.write_blender_director_ai_workflow_tasks_csv(metadata)
            ai_handoff = blender_director_project.write_blender_director_ai_workflow_handoff_package(metadata)
            metadata["ai_workflow_handoff_report_path"] = ai_handoff["report_path"]
            metadata["ai_workflow_handoff_csv_path"] = ai_handoff["csv_path"]
            metadata["ai_workflow_results_report_path"] = blender_director_project.write_blender_director_ai_workflow_results_report(metadata)
            metadata["ai_workflow_results_csv_path"] = blender_director_project.write_blender_director_ai_workflow_results_csv(metadata)
            metadata["retarget_summary_report_path"] = blender_director_project.write_blender_director_retarget_summary_report(metadata)
            metadata["retarget_summary_csv_path"] = blender_director_project.write_blender_director_retarget_summary_csv(metadata)
            metadata["delivery_audit_report_path"] = blender_director_project.write_blender_director_delivery_audit_report(metadata)

            dashboard_path = Path(blender_director_project.write_blender_director_project_dashboard(metadata))
            dashboard_html = dashboard_path.read_text(encoding="utf-8")

            self.assertTrue(dashboard_path.exists())
            self.assertIn("工程总览测试 - 工程总览", dashboard_html)
            self.assertIn("制作文件", dashboard_html)
            self.assertIn("分镜表", dashboard_html)
            self.assertIn("渲染队列", dashboard_html)
            self.assertIn("批量渲染任务", dashboard_html)
            self.assertIn("后台渲染命令", dashboard_html)
            self.assertIn("镜头版本索引", dashboard_html)
            self.assertIn("分场表", dashboard_html)
            self.assertIn("分集交付清单", dashboard_html)
            self.assertIn("分集交付包", dashboard_html)
            self.assertIn("拍摄单", dashboard_html)
            self.assertIn("演员调度", dashboard_html)
            self.assertIn("剪辑时间线", dashboard_html)
            self.assertIn("剪辑 EDL", dashboard_html)
            self.assertIn("剪辑 FCPXML", dashboard_html)
            self.assertIn("后期交接清单", dashboard_html)
            self.assertIn("连续性检查", dashboard_html)
            self.assertIn("制作问题检查", dashboard_html)
            self.assertIn("时长统计", dashboard_html)
            self.assertIn("估算秒数", dashboard_html)
            self.assertIn("制作清单", dashboard_html)
            self.assertIn("资产需求清单", dashboard_html)
            self.assertIn("缺项有候选", dashboard_html)
            self.assertIn("资产生态报告", dashboard_html)
            self.assertIn("资产生态 CSV", dashboard_html)
            self.assertIn("资产库缺文件", dashboard_html)
            self.assertIn("缺授权来源", dashboard_html)
            self.assertIn("可控工程资产", dashboard_html)
            self.assertIn("资产导入预检", dashboard_html)
            self.assertIn("资产导入预检 CSV", dashboard_html)
            self.assertIn("导入阻断", dashboard_html)
            self.assertIn("导入需复核", dashboard_html)
            self.assertIn("动作匹配清单", dashboard_html)
            self.assertIn("待补动作", dashboard_html)
            self.assertIn("AI 工作流任务包", dashboard_html)
            self.assertIn("AI任务可执行", dashboard_html)
            self.assertIn("AI 工作包与结果收件箱", dashboard_html)
            self.assertIn("AI结果收件箱", dashboard_html)
            self.assertIn("AI 结果回填台账", dashboard_html)
            self.assertIn("AI结果回填", dashboard_html)
            self.assertIn("AI结果缺文件", dashboard_html)
            self.assertIn("重定向动作片段", dashboard_html)
            self.assertIn("Rest Pose 差异骨骼", dashboard_html)
            self.assertIn("重定向失败", dashboard_html)
            self.assertIn("重定向质量报告", dashboard_html)
            self.assertIn("重定向质量 CSV", dashboard_html)
            self.assertIn("交付检查", dashboard_html)

    def test_delivery_audit_detects_missing_files_and_pending_shots(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            existing_render = Path(tmp) / "shot_done.png"
            existing_render.write_bytes(b"png")
            metadata = {
                "project_id": "audit_test",
                "project_name": "交付检查测试",
                "project_dir": tmp,
                "blend_path": str(Path(tmp) / "missing.blend"),
                "assets": [
                    {"id": "asset_missing", "name": "缺失模型", "path": str(Path(tmp) / "missing.glb")}
                ],
                "shots": [
                    {
                        "id": "shot_done",
                        "name": "已渲染镜头",
                        "shot_status": "approved",
                        "shot_status_label": "已定稿",
                        "assets": [{"id": "asset_missing", "name": "缺失模型"}],
                    },
                    {"id": "shot_pending", "name": "未渲染镜头"},
                ],
                "renders": [
                    {"shot_id": "shot_done", "path": str(existing_render), "preview_path": str(existing_render)}
                ],
            }

            audit = blender_director_project.build_blender_director_delivery_audit(metadata)

            self.assertFalse(audit["ready_for_delivery"])
            self.assertEqual(len(audit["pending_shots"]), 1)
            self.assertEqual(audit["pending_shots"][0]["shot_name"], "未渲染镜头")
            missing_paths = {item["path"] for item in audit["missing_files"]}
            self.assertIn(str(Path(tmp) / "missing.blend"), missing_paths)
            self.assertIn(str(Path(tmp) / "missing.glb"), missing_paths)

            audit_path = Path(blender_director_project.write_blender_director_delivery_audit(metadata))
            report_path = Path(blender_director_project.write_blender_director_delivery_audit_report(metadata))
            self.assertTrue(audit_path.exists())
            self.assertTrue(report_path.exists())
            self.assertIn("交付检查测试 - 交付检查", report_path.read_text(encoding="utf-8"))
            self.assertIn("未渲染镜头", report_path.read_text(encoding="utf-8"))

    def test_delivery_package_bundles_project_reports_assets_and_renders(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            project_dir = Path(tmp)
            assets_dir = project_dir / "assets"
            characters_dir = assets_dir / "characters"
            library_dir = project_dir / "open_library"
            shots_dir = project_dir / "shots"
            renders_dir = project_dir / "renders"
            layer_dir = renders_dir / "shot_01_layers"
            for path in (characters_dir, library_dir, shots_dir, layer_dir):
                path.mkdir(parents=True, exist_ok=True)
            meta_path = project_dir / "director_project.json"
            blend_path = project_dir / "director.blend"
            asset_path = characters_dir / "hero.glb"
            library_asset_path = library_dir / "hero_source.glb"
            shot_path = shots_dir / "shot_01.json"
            preview_path = renders_dir / "shot_01.png"
            transparent_path = layer_dir / "transparent.png"
            layer_manifest_path = layer_dir / "manifest.json"
            blend_path.write_bytes(b"blend")
            asset_path.write_bytes(b"glb")
            library_asset_path.write_bytes(b"source glb")
            shot_path.write_text('{"id":"shot_01"}', encoding="utf-8")
            preview_path.write_bytes(b"png")
            transparent_path.write_bytes(b"transparent")
            layer_manifest_path.write_text("{}", encoding="utf-8")

            metadata = {
                "project_id": "delivery_test",
                "project_name": "交付包测试",
                "project_dir": str(project_dir),
                "meta_path": str(meta_path),
                "blend_path": str(blend_path),
                "assets_dir": str(assets_dir),
                "asset_dirs": {"characters": str(characters_dir)},
                "shots_dir": str(shots_dir),
                "renders_dir": str(renders_dir),
                "assets": [
                    {
                        "id": "hero",
                        "name": "主角",
                        "path": str(asset_path),
                        "source_path": str(library_asset_path),
                        "type": "character",
                        "library_item_id": "library_hero",
                        "library_relative_path": "hero_source.glb",
                        "source_profile_id": "poly_haven",
                        "source_profile_name": "Poly Haven / HDRI 与 CC0 资产",
                    }
                ],
                "asset_sources": [
                    {
                        "id": "source_poly_haven",
                        "name": "open_library",
                        "path": str(library_dir),
                        "profile_id": "poly_haven",
                        "profile_name": "Poly Haven / HDRI 与 CC0 资产",
                        "item_count": 1,
                    }
                ],
                "asset_libraries": [
                    {
                        "id": "library_open",
                        "name": "open_library",
                        "path": str(library_dir),
                        "source_profile_id": "poly_haven",
                        "source_profile_name": "Poly Haven / HDRI 与 CC0 资产",
                        "item_count": 1,
                    }
                ],
                "asset_library_items": [
                    {
                        "id": "library_hero",
                        "name": "主角源文件",
                        "path": str(library_asset_path),
                        "relative_path": "hero_source.glb",
                        "library_id": "library_open",
                        "library_path": str(library_dir),
                        "kind_hint": "character",
                        "format": "glb",
                        "source_profile_id": "poly_haven",
                        "source_profile_name": "Poly Haven / HDRI 与 CC0 资产",
                        "tags": "主角 可商用",
                    }
                ],
                "shots": [
                    {"id": "shot_01", "name": "开场", "assets": [{"id": "hero", "name": "主角"}]}
                ],
                "renders": [
                    {
                        "shot_id": "shot_01",
                        "path": str(preview_path),
                        "preview_path": str(preview_path),
                        "output_path": str(layer_dir),
                        "manifest_path": str(layer_manifest_path),
                        "layer_paths": {"transparent": str(transparent_path)},
                    }
                ],
                "ai_workflow_results": [
                    {
                        "id": "ai_result_delivery",
                        "task_id": "ai_visual_shot_01",
                        "result_type": "image",
                        "target_type": "render",
                        "path": str(preview_path),
                        "payload_name": "AI交付首帧",
                        "registered_at": "2026-07-10 18:30:00",
                    }
                ],
                "retarget_profiles": [
                    {
                        "id": "retarget_delivery",
                        "name": "交付骨骼重定向",
                        "source_armature": "SourceRig",
                        "target_armature": "HeroRig",
                        "mapped_bone_count": 30,
                        "unmapped_source_count": 0,
                        "unmapped_target_count": 1,
                        "rest_pose_alignment": {"mismatch_bone_count": 2, "max_angle_degrees": 8.5},
                        "root_motion": {"effective_scale": 1.1},
                    }
                ],
                "action_clips": [
                    {
                        "id": "retarget_delivery_clip",
                        "name": "走入（重定向）",
                        "generated_by": "retarget",
                        "retarget_profile_name": "交付骨骼重定向",
                        "retarget_quality": {
                            "copied_fcurve_count": 48,
                            "mapped_bone_count": 30,
                            "unmapped_target_count": 1,
                            "rest_pose_mismatch_bone_count": 2,
                            "rest_pose_max_angle_degrees": 8.5,
                            "root_motion_scale": 1.1,
                        },
                    }
                ],
                "retarget_applications": [
                    {
                        "status": "applied",
                        "profile_name": "交付骨骼重定向",
                        "target_action": "HeroRig_Walk_retarget",
                        "copied_fcurve_count": 48,
                        "action_clip": {"id": "retarget_delivery_clip", "name": "走入（重定向）"},
                    }
                ],
            }
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

            package_path = Path(blender_director_project.write_blender_director_delivery_package(metadata))

            self.assertTrue(package_path.exists())
            self.assertEqual(package_path.parent.name, "delivery_packages")
            with zipfile.ZipFile(package_path) as zf:
                names = set(zf.namelist())
                self.assertIn("director_project.json", names)
                self.assertIn("director.blend", names)
                self.assertIn("storyboard_report.html", names)
                self.assertIn("storyboard.csv", names)
                self.assertIn("render_queue.json", names)
                self.assertIn("render_queue.html", names)
                self.assertIn("render_queue.csv", names)
                self.assertIn("batch_render_jobs.json", names)
                self.assertIn("batch_render_jobs.html", names)
                self.assertIn("batch_render_jobs.csv", names)
                self.assertIn("batch_render_command.json", names)
                self.assertIn("batch_render_command.html", names)
                self.assertIn("scripts/run_pending_renders.py", names)
                self.assertIn("render_versions.json", names)
                self.assertIn("render_versions.html", names)
                self.assertIn("render_versions.csv", names)
                self.assertIn("scene_breakdown.json", names)
                self.assertIn("scene_breakdown.html", names)
                self.assertIn("scene_breakdown.csv", names)
                self.assertIn("episode_delivery.json", names)
                self.assertIn("episode_delivery.html", names)
                self.assertIn("episode_delivery.csv", names)
                self.assertIn("episode_delivery_packages.json", names)
                self.assertIn("episode_delivery_packages.html", names)
                self.assertIn("episode_delivery_packages.csv", names)
                self.assertTrue(any(name.startswith("delivery_packages/episodes/") and name.endswith(".zip") for name in names))
                self.assertIn("call_sheet.json", names)
                self.assertIn("call_sheet.html", names)
                self.assertIn("call_sheet.csv", names)
                self.assertIn("actor_schedule.json", names)
                self.assertIn("actor_schedule.html", names)
                self.assertIn("actor_schedule.csv", names)
                self.assertIn("edit_timeline.json", names)
                self.assertIn("edit_timeline.html", names)
                self.assertIn("edit_timeline.csv", names)
                self.assertIn("edit_timeline.edl", names)
                self.assertIn("edit_timeline.fcpxml", names)
                self.assertIn("post_handoff.json", names)
                self.assertIn("post_handoff.html", names)
                self.assertIn("post_handoff.csv", names)
                self.assertIn("continuity_check.json", names)
                self.assertIn("continuity_check.html", names)
                self.assertIn("continuity_check.csv", names)
                self.assertIn("production_check.json", names)
                self.assertIn("production_check.html", names)
                self.assertIn("production_check.csv", names)
                self.assertIn("duration_summary.json", names)
                self.assertIn("production_report.html", names)
                self.assertIn("asset_usage.csv", names)
                self.assertIn("asset_requirements.json", names)
                self.assertIn("asset_requirements.html", names)
                self.assertIn("asset_requirements.csv", names)
                self.assertIn("asset_ecosystem.json", names)
                self.assertIn("asset_ecosystem.html", names)
                self.assertIn("asset_ecosystem.csv", names)
                self.assertIn("asset_preflight.json", names)
                self.assertIn("asset_preflight.html", names)
                self.assertIn("asset_preflight.csv", names)
                self.assertIn("action_matches.json", names)
                self.assertIn("action_matches.html", names)
                self.assertIn("action_matches.csv", names)
                self.assertIn("ai_workflow_tasks.json", names)
                self.assertIn("ai_workflow_tasks.html", names)
                self.assertIn("ai_workflow_tasks.csv", names)
                self.assertIn("ai_workflow_handoff/handoff_manifest.json", names)
                self.assertIn("ai_workflow_handoff/handoff.html", names)
                self.assertIn("ai_workflow_handoff/handoff.csv", names)
                self.assertIn("ai_workflow_handoff/README.txt", names)
                self.assertIn("ai_workflow_handoff/ai_visual_shot_01/task.json", names)
                self.assertIn("ai_workflow_handoff/ai_visual_shot_01/prompt.txt", names)
                self.assertIn("ai_workflow_handoff/ai_visual_shot_01/results/README.txt", names)
                self.assertIn("ai_workflow_results.json", names)
                self.assertIn("ai_workflow_results.html", names)
                self.assertIn("ai_workflow_results.csv", names)
                self.assertIn("retarget_summary.json", names)
                self.assertIn("retarget_summary.html", names)
                self.assertIn("retarget_summary.csv", names)
                self.assertIn("delivery_audit.json", names)
                self.assertIn("delivery_audit.html", names)
                self.assertIn("project_dashboard.html", names)
                self.assertIn("assets/characters/hero.glb", names)
                self.assertIn("open_library/hero_source.glb", names)
                self.assertIn("shots/shot_01.json", names)
                self.assertIn("renders/shot_01.png", names)
                self.assertIn("renders/shot_01_layers/transparent.png", names)
                self.assertIn("delivery_manifest.json", names)
                self.assertFalse(
                    any(
                        name.startswith("delivery_packages/")
                        and not name.startswith("delivery_packages/episodes/")
                        for name in names
                    )
                )
                manifest = json.loads(zf.read("delivery_manifest.json").decode("utf-8"))
            self.assertEqual(manifest["project_name"], "交付包测试")
            self.assertEqual(manifest["delivery_audit_report"], "delivery_audit.html")
            self.assertEqual(manifest["storyboard_csv"], "storyboard.csv")
            self.assertEqual(manifest["render_queue_report"], "render_queue.html")
            self.assertEqual(manifest["render_queue_csv"], "render_queue.csv")
            self.assertEqual(manifest["batch_render_jobs_report"], "batch_render_jobs.html")
            self.assertEqual(manifest["batch_render_jobs_csv"], "batch_render_jobs.csv")
            self.assertEqual(manifest["batch_render_command"], "batch_render_command.json")
            self.assertEqual(manifest["batch_render_command_report"], "batch_render_command.html")
            self.assertEqual(manifest["batch_render_script"], "scripts/run_pending_renders.py")
            self.assertEqual(manifest["render_versions_report"], "render_versions.html")
            self.assertEqual(manifest["render_versions_csv"], "render_versions.csv")
            self.assertEqual(manifest["scene_breakdown_report"], "scene_breakdown.html")
            self.assertEqual(manifest["scene_breakdown_csv"], "scene_breakdown.csv")
            self.assertEqual(manifest["episode_delivery_report"], "episode_delivery.html")
            self.assertEqual(manifest["episode_delivery_csv"], "episode_delivery.csv")
            self.assertEqual(manifest["episode_delivery_packages_report"], "episode_delivery_packages.html")
            self.assertEqual(manifest["episode_delivery_packages_csv"], "episode_delivery_packages.csv")
            self.assertTrue(manifest["episode_delivery_packages"])
            self.assertEqual(manifest["call_sheet_report"], "call_sheet.html")
            self.assertEqual(manifest["call_sheet_csv"], "call_sheet.csv")
            self.assertEqual(manifest["actor_schedule_report"], "actor_schedule.html")
            self.assertEqual(manifest["actor_schedule_csv"], "actor_schedule.csv")
            self.assertEqual(manifest["edit_timeline_report"], "edit_timeline.html")
            self.assertEqual(manifest["edit_timeline_csv"], "edit_timeline.csv")
            self.assertEqual(manifest["edit_timeline_edl"], "edit_timeline.edl")
            self.assertEqual(manifest["edit_timeline_fcpxml"], "edit_timeline.fcpxml")
            self.assertEqual(manifest["post_handoff_report"], "post_handoff.html")
            self.assertEqual(manifest["post_handoff_csv"], "post_handoff.csv")
            self.assertEqual(manifest["continuity_check_report"], "continuity_check.html")
            self.assertEqual(manifest["continuity_check_csv"], "continuity_check.csv")
            self.assertEqual(manifest["production_check_report"], "production_check.html")
            self.assertEqual(manifest["production_check_csv"], "production_check.csv")
            self.assertEqual(manifest["duration_summary"], "duration_summary.json")
            self.assertEqual(manifest["asset_usage_csv"], "asset_usage.csv")
            self.assertEqual(manifest["asset_requirements_report"], "asset_requirements.html")
            self.assertEqual(manifest["asset_requirements_csv"], "asset_requirements.csv")
            self.assertEqual(manifest["asset_ecosystem_manifest"], "asset_ecosystem.json")
            self.assertEqual(manifest["asset_ecosystem_report"], "asset_ecosystem.html")
            self.assertEqual(manifest["asset_ecosystem_csv"], "asset_ecosystem.csv")
            self.assertEqual(manifest["asset_ecosystem"]["library_item_count"], 1)
            self.assertEqual(manifest["asset_ecosystem"]["imported_item_count"], 1)
            self.assertEqual(manifest["asset_ecosystem"]["controllable_asset_count"], 0)
            self.assertEqual(manifest["asset_ecosystem"]["missing_file_count"], 0)
            self.assertEqual(manifest["asset_preflight_manifest"], "asset_preflight.json")
            self.assertEqual(manifest["asset_preflight_report"], "asset_preflight.html")
            self.assertEqual(manifest["asset_preflight_csv"], "asset_preflight.csv")
            self.assertEqual(manifest["asset_preflight"]["library_item_count"], 1)
            self.assertEqual(manifest["asset_preflight"]["blocked_count"], 0)
            self.assertEqual(manifest["action_matches_report"], "action_matches.html")
            self.assertEqual(manifest["action_matches_csv"], "action_matches.csv")
            self.assertEqual(manifest["ai_workflow_tasks_manifest"], "ai_workflow_tasks.json")
            self.assertEqual(manifest["ai_workflow_tasks_report"], "ai_workflow_tasks.html")
            self.assertEqual(manifest["ai_workflow_tasks_csv"], "ai_workflow_tasks.csv")
            self.assertGreaterEqual(manifest["ai_workflow_tasks"]["task_count"], 1)
            self.assertEqual(manifest["ai_workflow_handoff_manifest"], "ai_workflow_handoff/handoff_manifest.json")
            self.assertEqual(manifest["ai_workflow_handoff_report"], "ai_workflow_handoff/handoff.html")
            self.assertEqual(manifest["ai_workflow_handoff_csv"], "ai_workflow_handoff/handoff.csv")
            self.assertEqual(manifest["ai_workflow_handoff_readme"], "ai_workflow_handoff/README.txt")
            self.assertGreaterEqual(manifest["ai_workflow_handoff"]["result_inbox_count"], 1)
            self.assertEqual(manifest["ai_workflow_results_manifest"], "ai_workflow_results.json")
            self.assertEqual(manifest["ai_workflow_results_report"], "ai_workflow_results.html")
            self.assertEqual(manifest["ai_workflow_results_csv"], "ai_workflow_results.csv")
            self.assertEqual(manifest["ai_workflow_results"]["result_count"], 1)
            self.assertEqual(manifest["ai_workflow_results"]["missing_file_count"], 0)
            self.assertEqual(manifest["retarget_summary_manifest"], "retarget_summary.json")
            self.assertEqual(manifest["retarget_summary_report"], "retarget_summary.html")
            self.assertEqual(manifest["retarget_summary_csv"], "retarget_summary.csv")
            self.assertEqual(manifest["retarget_summary"]["ready_clip_count"], 1)
            self.assertEqual(manifest["retarget_summary"]["mapped_bone_count"], 30)
            self.assertEqual(manifest["retarget_summary"]["rest_pose_max_angle_degrees"], 8.5)
            self.assertEqual(manifest["project_dashboard"], "project_dashboard.html")
            self.assertGreater(manifest["file_count"], 0)
            saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_meta["delivery_package_path"], str(package_path))

    def test_sync_director_project_renders_keeps_layered_output_metadata(self):
        messages = []
        scene = WorkflowScene(config={"providers": []}, status_callback=messages.append, load_defaults=False)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            layer_dir = Path(tmp) / "shot_layers"
            layer_dir.mkdir()
            beauty = layer_dir / "shot_beauty.png"
            transparent = layer_dir / "shot_transparent.png"
            manifest = layer_dir / "manifest.json"
            beauty.write_bytes(b"fake beauty")
            transparent.write_bytes(b"fake transparent")
            manifest.write_text("{}", encoding="utf-8")
            meta_path = Path(tmp) / "director_project.json"
            meta_path.write_text(
                json.dumps(
                    {
                        "project_id": "director_sync_layered",
                        "project_name": "分层素材测试",
                        "project_dir": tmp,
                        "renders": [
                            {
                                "path": str(beauty),
                                "preview_path": str(beauty),
                                "output_path": str(layer_dir),
                                "output_type": "layered",
                                "output_label": "分层素材包",
                                "manifest_path": str(manifest),
                                "layer_paths": {
                                    "beauty": str(beauty),
                                    "transparent": str(transparent),
                                },
                                "shot_id": "shot_layered",
                                "shot_name": "分层镜头",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            node = scene.add_node("blender_director_project", QPointF(0, 0))
            node.data["director_project"] = {"meta_path": str(meta_path)}
            captured = []

            with mock.patch.object(scene, "sync_image_result_to_history", side_effect=captured.append):
                scene.sync_blender_director_project_renders(node)

            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["images"], [str(beauty)])
            self.assertEqual(captured[0]["blender_render"]["output_path"], str(layer_dir))
            self.assertEqual(captured[0]["blender_render"]["manifest_path"], str(manifest))
            self.assertEqual(captured[0]["blender_render"]["layer_paths"]["transparent"], str(transparent))
            self.assertIn(str(beauty), node.data["director_synced_renders"])
            self.assertEqual(node.data["image_path"], str(beauty))

    def test_director_project_dialog_shows_shot_output_fields(self):
        metadata = {
            "project_name": "镜头字段显示测试",
            "assets": [
                {
                    "type": "character",
                    "name": "蓝色主角",
                    "format": "glb",
                    "objects": ["Body", "Armature"],
                    "collections": ["Hero"],
                    "actions": ["Idle"],
                }
            ],
            "actors": [
                {
                    "id": "actor_001",
                    "name": "陈景川",
                    "role": "主角",
                    "note": "蓝色人偶常驻男主",
                    "object_names": ["蓝色主角"],
                    "object_count": 1,
                    "actions": ["Idle"],
                    "saved_at": "2026-07-09 12:01:44",
                }
            ],
            "camera_motions": [
                {
                    "label": "推近",
                    "camera": "Director Camera",
                    "frame_start": 12,
                    "frame_end": 96,
                    "created_at": "2026-07-09 12:01:00",
                }
            ],
            "light_templates": [
                {
                    "id": "light_template_001",
                    "name": "夜景冷光",
                    "note": "主光偏冷，轮廓光压暗",
                    "lights": [
                        {"name": "Director Key Light"},
                        {"name": "Director Fill Light"},
                        {"name": "Director Rim Light"},
                    ],
                    "light_count": 3,
                    "saved_at": "2026-07-09 12:01:20",
                }
            ],
            "render_templates": [
                {
                    "id": "render_template_001",
                    "name": "分镜预览规格",
                    "note": "快速出分镜参考",
                    "output_type": "still",
                    "output_label": "普通图",
                    "resolution_x": 1280,
                    "resolution_y": 720,
                    "fps": 24,
                    "frame_start": 12,
                    "frame_end": 96,
                    "engine": "CYCLES",
                    "saved_at": "2026-07-09 12:01:10",
                }
            ],
            "camera_templates": [
                {
                    "id": "camera_template_001",
                    "name": "正反打机位",
                    "note": "男主过肩看向反派",
                    "camera": {"name": "Director Camera", "lens": 50},
                    "saved_at": "2026-07-09 12:01:30",
                }
            ],
            "action_clips": [
                {
                    "id": "action_clip_001",
                    "name": "走入停顿",
                    "note": "从门外走到桌边后停顿",
                    "action": "WalkStop",
                    "target_armature": "HeroRig",
                    "actor": {"id": "actor_001", "name": "陈景川", "role": "主角"},
                    "frame_start": 12,
                    "frame_end": 48,
                    "frame_count": 37,
                    "source_profile_name": "Mixamo / 角色动作",
                    "library_relative_path": "actions/walk_stop.fbx",
                    "saved_at": "2026-07-09 12:01:35",
                }
            ],
            "pose_templates": [
                {
                    "id": "pose_template_001",
                    "name": "举手质问",
                    "note": "右手抬起，身体微前倾",
                    "armature": "HeroRig",
                    "action": "QuestionPose",
                    "bone_count": 28,
                    "saved_at": "2026-07-09 12:01:40",
                }
            ],
            "animation_templates": [
                {
                    "id": "animation_template_001",
                    "name": "开门走入",
                    "note": "人物从门口走到桌边",
                    "object_count": 1,
                    "keyframe_count": 4,
                    "frame_start": 12,
                    "frame_end": 96,
                    "objects": [{"name": "蓝色主角"}],
                    "saved_at": "2026-07-09 12:01:42",
                }
            ],
            "material_templates": [
                {
                    "id": "material_template_001",
                    "name": "蓝色人偶外观",
                    "note": "统一角色蓝色塑料质感",
                    "object_count": 1,
                    "material_count": 1,
                    "objects": [{"name": "蓝色主角"}],
                    "materials": [{"name": "蓝色材质"}],
                    "saved_at": "2026-07-09 12:01:43",
                }
            ],
            "object_templates": [
                {
                    "id": "object_template_001",
                    "name": "二人对峙站位",
                    "note": "主角站门口，反派靠沙发",
                    "objects": [{"name": "蓝色主角"}, {"name": "红色反派"}],
                    "saved_at": "2026-07-09 12:01:45",
                }
            ],
            "object_motions": [
                {
                    "label": "前进",
                    "objects": ["蓝色主角"],
                    "actor": {"id": "actor_001", "name": "陈景川", "role": "主角"},
                    "frame_start": 12,
                    "frame_end": 96,
                    "created_at": "2026-07-09 12:02:00",
                }
            ],
            "action_applications": [
                {
                    "target": "HeroRig",
                    "action": "WalkCycle",
                    "status": "applied",
                    "message": "HeroRig_WalkCycle",
                    "actor": {"id": "actor_001", "name": "陈景川", "role": "主角"},
                    "action_clip": {"id": "action_clip_001", "name": "走入停顿"},
                    "applied_at": "2026-07-09 12:02:05",
                }
            ],
            "scene_presets": [
                {
                    "id": "preset_001",
                    "name": "客厅对峙站位",
                    "note": "主角靠门，反派坐在沙发右侧",
                    "output_type": "still",
                    "output_label": "普通图",
                    "objects": [{"name": "蓝色主角"}, {"name": "红色反派"}],
                    "camera": {"name": "Director Camera"},
                    "frame_start": 12,
                    "frame_end": 96,
                    "saved_at": "2026-07-09 12:03:00",
                }
            ],
            "shot_packages": [
                {
                    "id": "package_001",
                    "name": "二人对话正反打组",
                    "note": "对话常用镜头结构",
                    "shots": [{"name": "第一镜"}, {"name": "第二镜"}],
                    "saved_at": "2026-07-09 12:03:20",
                }
            ],
            "set_packages": [
                {
                    "id": "set_package_001",
                    "name": "客厅常用布景",
                    "note": "沙发茶几夜景窗",
                    "object_count": 3,
                    "collection_count": 1,
                    "object_names": ["沙发", "茶几", "落地灯"],
                    "collections": ["客厅"],
                    "saved_at": "2026-07-09 12:03:30",
                }
            ],
            "shots": [
                {
                    "id": "shot_001",
                    "name": "第一镜",
                    "note": "主角进门",
                    "output_type": "video",
                    "output_label": "视频",
                    "shot_status": "review",
                    "shot_status_label": "待调整",
                    "render_version": 4,
                    "assets": [
                        {"id": "asset_hero", "name": "蓝色主角模型", "type": "character"}
                    ],
                    "frame_start": 12,
                    "frame_end": 96,
                    "saved_at": "2026-07-09 12:00:00",
                }
            ],
            "renders": [
                {
                    "shot_id": "shot_layered",
                    "shot_name": "分层镜头",
                    "output_type": "layered",
                    "output_label": "分层素材包",
                    "render_version": 2,
                    "output_path": "/tmp/shot_layers",
                    "path": "/tmp/shot_layers/shot_beauty.png",
                    "manifest_path": "/tmp/shot_layers/manifest.json",
                    "layer_paths": {
                        "beauty": "/tmp/shot_layers/shot_beauty.png",
                        "transparent": "/tmp/shot_layers/shot_transparent.png",
                    },
                    "mode": "current",
                    "created_at": "2026-07-09 12:04:00",
                }
            ],
        }
        dialog = BlenderDirectorProjectDialog(metadata)
        try:
            item = dialog.shot_list.item(0)
            self.assertIsNotNone(item)
            label = item.text()
            self.assertIn("第一镜", label)
            self.assertIn("视频", label)
            self.assertIn("待调整", label)
            self.assertIn("v4", label)
            self.assertIn("资产：蓝色主角模型", label)
            self.assertIn("帧：12-96", label)
            self.assertIn("主角进门", label)
            asset_label = dialog.asset_list.item(0).text()
            self.assertIn("蓝色主角", asset_label)
            self.assertIn("GLB", asset_label)
            self.assertIn("对象 2 个", asset_label)
            self.assertIn("集合 1 个", asset_label)
            self.assertIn("动作 1 个", asset_label)

            def action_item_text(prefix):
                for index in range(dialog.action_list.count()):
                    item = dialog.action_list.item(index)
                    text = item.text() if item is not None else ""
                    if prefix in text:
                        return text
                self.fail(f"未找到记录：{prefix}")

            actor_label = action_item_text("演员位｜陈景川")
            self.assertIn("主角", actor_label)
            self.assertIn("对象 1 个", actor_label)
            self.assertIn("蓝色主角", actor_label)
            self.assertIn("动作：Idle", actor_label)
            self.assertIn("蓝色人偶常驻男主", actor_label)
            motion_label = action_item_text("场景预设｜客厅对峙站位")
            self.assertIn("场景预设｜客厅对峙站位", motion_label)
            self.assertIn("对象 2 个", motion_label)
            self.assertIn("相机：Director Camera", motion_label)
            self.assertIn("帧：12-96", motion_label)
            self.assertIn("主角靠门", motion_label)
            motion_label = action_item_text("镜头包｜二人对话正反打组")
            self.assertIn("镜头包｜二人对话正反打组", motion_label)
            self.assertIn("镜头 2 个", motion_label)
            self.assertIn("第一镜、第二镜", motion_label)
            self.assertIn("对话常用镜头结构", motion_label)
            motion_label = action_item_text("布景包｜客厅常用布景")
            self.assertIn("布景包｜客厅常用布景", motion_label)
            self.assertIn("对象 3 个", motion_label)
            self.assertIn("集合 1 个", motion_label)
            self.assertIn("沙发、茶几、落地灯", motion_label)
            self.assertIn("沙发茶几夜景窗", motion_label)
            motion_label = action_item_text("渲染模板｜分镜预览规格")
            self.assertIn("渲染模板｜分镜预览规格", motion_label)
            self.assertIn("普通图", motion_label)
            self.assertIn("1280x720", motion_label)
            self.assertIn("24fps", motion_label)
            self.assertIn("快速出分镜参考", motion_label)
            motion_label = action_item_text("灯光模板｜夜景冷光")
            self.assertIn("灯光模板｜夜景冷光", motion_label)
            self.assertIn("灯光 3 盏", motion_label)
            self.assertIn("Director Key Light", motion_label)
            self.assertIn("主光偏冷", motion_label)
            motion_label = action_item_text("机位模板｜正反打机位")
            self.assertIn("机位模板｜正反打机位", motion_label)
            self.assertIn("相机：Director Camera", motion_label)
            self.assertIn("焦距：50", motion_label)
            self.assertIn("男主过肩", motion_label)
            motion_label = action_item_text("站位模板｜二人对峙站位")
            self.assertIn("站位模板｜二人对峙站位", motion_label)
            self.assertIn("对象 2 个", motion_label)
            self.assertIn("蓝色主角、红色反派", motion_label)
            self.assertIn("主角站门口", motion_label)
            motion_label = action_item_text("动作片段｜走入停顿")
            self.assertIn("演员：陈景川（主角）", motion_label)
            self.assertIn("骨骼：HeroRig", motion_label)
            self.assertIn("动作：WalkStop", motion_label)
            self.assertIn("帧：12-48（37帧）", motion_label)
            self.assertIn("来源：Mixamo / 角色动作", motion_label)
            self.assertIn("actions/walk_stop.fbx", motion_label)
            self.assertIn("从门外走到桌边", motion_label)
            motion_label = action_item_text("姿势模板｜举手质问")
            self.assertIn("姿势模板｜举手质问", motion_label)
            self.assertIn("骨骼：HeroRig", motion_label)
            self.assertIn("骨骼数：28", motion_label)
            self.assertIn("动作：QuestionPose", motion_label)
            self.assertIn("右手抬起", motion_label)
            motion_label = action_item_text("动画片段｜开门走入")
            self.assertIn("动画片段｜开门走入", motion_label)
            self.assertIn("对象 1 个", motion_label)
            self.assertIn("关键帧 4 个", motion_label)
            self.assertIn("帧：12-96", motion_label)
            self.assertIn("蓝色主角", motion_label)
            self.assertIn("人物从门口", motion_label)
            motion_label = action_item_text("材质模板｜蓝色人偶外观")
            self.assertIn("材质模板｜蓝色人偶外观", motion_label)
            self.assertIn("对象 1 个", motion_label)
            self.assertIn("材质 1 个", motion_label)
            self.assertIn("蓝色主角", motion_label)
            self.assertIn("蓝色材质", motion_label)
            self.assertIn("统一角色蓝色", motion_label)
            motion_label = action_item_text("镜头运动｜推近")
            self.assertIn("镜头运动｜推近", motion_label)
            self.assertIn("Director Camera", motion_label)
            self.assertIn("帧：12-96", motion_label)
            action_label = action_item_text("已套用｜HeroRig")
            self.assertIn("WalkCycle", action_label)
            self.assertIn("演员：陈景川（主角）", action_label)
            self.assertIn("片段：走入停顿", action_label)
            self.assertIn("HeroRig_WalkCycle", action_label)
            object_motion_label = action_item_text("角色走位｜前进")
            self.assertIn("角色走位｜前进", object_motion_label)
            self.assertIn("演员：陈景川（主角）", object_motion_label)
            self.assertIn("蓝色主角", object_motion_label)
            self.assertIn("帧：12-96", object_motion_label)
            render_label = dialog.render_list.item(0).text()
            self.assertIn("分层镜头", render_label)
            self.assertIn("分层素材包", render_label)
            self.assertIn("v2", render_label)
            self.assertIn("素材层：beauty、transparent", render_label)
            self.assertIn("含素材清单", render_label)
        finally:
            dialog.close()

    def test_director_project_dialog_filters_assets_by_type(self):
        metadata = {
            "project_name": "资产筛选测试",
            "assets": [
                {"type": "character", "name": "蓝色主角"},
                {"type": "prop", "name": "会议桌"},
                {"type": "scene", "name": "京城总部大厅"},
                {"type": "action", "name": "转身"},
                {"type": "model", "name": "备用模型"},
            ],
        }
        dialog = BlenderDirectorProjectDialog(metadata)
        try:
            self.assertEqual(dialog.asset_list.count(), 5)
            self.assertIn("蓝色主角", dialog.asset_list.item(0).text())

            prop_index = dialog.asset_filter_combo.findData("prop")
            self.assertGreaterEqual(prop_index, 0)
            dialog.asset_filter_combo.setCurrentIndex(prop_index)
            self.assertEqual(dialog.asset_list.count(), 1)
            self.assertIn("会议桌", dialog.asset_list.item(0).text())

            action_index = dialog.asset_filter_combo.findData("action")
            self.assertGreaterEqual(action_index, 0)
            dialog.asset_filter_combo.setCurrentIndex(action_index)
            self.assertEqual(dialog.asset_list.count(), 1)
            self.assertIn("转身", dialog.asset_list.item(0).text())
        finally:
            dialog.close()

    def test_director_project_dialog_shows_asset_libraries_and_library_items(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            hero = Path(tmp) / "characters" / "hero.glb"
            hero.parent.mkdir(parents=True, exist_ok=True)
            hero.write_bytes(b"fake glb")
            walk = Path(tmp) / "actions" / "walk.bvh"
            walk.parent.mkdir(parents=True, exist_ok=True)
            walk.write_bytes(b"fake bvh")
            metadata = {
                "project_name": "资产库显示测试",
                "asset_libraries": [
                    {
                        "id": "library_001",
                        "name": "开源人物库",
                        "path": tmp,
                        "item_count": 2,
                        "scanned_at": "2026-07-09 18:00:00",
                    }
                ],
                "asset_library_items": [
                    {
                        "id": "hero_001",
                        "name": "蓝色人偶",
                        "path": str(hero),
                        "file_name": "hero.glb",
                        "format": "glb",
                        "relative_path": "characters/hero.glb",
                        "kind_hint": "character",
                        "modified_at": "2026-07-09 18:01:00",
                        "favorite": True,
                        "favorited_at": "2026-07-09 18:03:00",
                        "usage_count": 3,
                        "last_used_at": "2026-07-09 18:04:00",
                        "tags": "男主, 蓝色, 办公室",
                        "usage_note": "适合男主远景和办公室对话。",
                    },
                    {
                        "id": "walk_001",
                        "name": "行走动作",
                        "path": str(walk),
                        "file_name": "walk.bvh",
                        "format": "bvh",
                        "relative_path": "actions/walk.bvh",
                        "kind_hint": "action",
                        "modified_at": "2026-07-09 18:02:00",
                    }
                ],
                "assets": [
                    {
                        "type": "character",
                        "name": "已导入主角",
                        "format": "glb",
                    }
                ],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                self.assertGreaterEqual(dialog.asset_list.count(), 3)
                library_label = dialog.asset_list.item(0).text()
                self.assertIn("资产库目录｜开源人物库", library_label)
                self.assertIn("文件 2 个", library_label)
                library_item_label = dialog.asset_list.item(1).text()
                self.assertIn("库资产｜★ 蓝色人偶", library_item_label)
                self.assertIn("已收藏：2026-07-09 18:03:00", library_item_label)
                self.assertIn("人物", library_item_label)
                self.assertIn("GLB", library_item_label)
                self.assertIn("使用 3 次：2026-07-09 18:04:00", library_item_label)
                self.assertIn("标签：男主, 蓝色, 办公室", library_item_label)
                self.assertIn("备注：适合男主远景和办公室对话。", library_item_label)
                self.assertIn("characters/hero.glb", library_item_label)
                action_library_label = dialog.asset_list.item(2).text()
                self.assertIn("库资产｜行走动作", action_library_label)
                self.assertIn("动作", action_library_label)
                self.assertIn("BVH", action_library_label)
                imported_label = dialog.asset_list.item(3).text()
                self.assertIn("人物｜已导入主角", imported_label)

                dialog.asset_list.setCurrentRow(1)
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_selected_asset()
                opened.assert_called_once_with(str(hero))

                character_index = dialog.asset_filter_combo.findData("character")
                self.assertGreaterEqual(character_index, 0)
                dialog.asset_filter_combo.setCurrentIndex(character_index)
                self.assertEqual(dialog.asset_list.count(), 2)
                self.assertIn("库资产｜★ 蓝色人偶", dialog.asset_list.item(0).text())
                self.assertIn("人物｜已导入主角", dialog.asset_list.item(1).text())

                action_index = dialog.asset_filter_combo.findData("action")
                self.assertGreaterEqual(action_index, 0)
                dialog.asset_filter_combo.setCurrentIndex(action_index)
                self.assertEqual(dialog.asset_list.count(), 1)
                self.assertIn("库资产｜行走动作", dialog.asset_list.item(0).text())

                dialog.asset_search_edit.setText("hero.glb")
                self.assertEqual(dialog.asset_list.count(), 1)
                self.assertIn("暂无资产", dialog.asset_list.item(0).text())

                all_index = dialog.asset_filter_combo.findData("all")
                self.assertGreaterEqual(all_index, 0)
                dialog.asset_filter_combo.setCurrentIndex(all_index)
                self.assertGreaterEqual(dialog.asset_list.count(), 1)
                self.assertIn("库资产｜★ 蓝色人偶", dialog.asset_list.item(0).text())
                self.assertNotIn("行走动作", "\n".join(dialog.asset_list.item(i).text() for i in range(dialog.asset_list.count())))

                dialog.asset_search_edit.clear()
                dialog.asset_favorites_only.setChecked(True)
                self.assertEqual(dialog.asset_list.count(), 1)
                self.assertIn("库资产｜★ 蓝色人偶", dialog.asset_list.item(0).text())
                self.assertNotIn("资产库目录", dialog.asset_list.item(0).text())

                dialog.asset_favorites_only.setChecked(False)
                dialog.asset_search_edit.setText("办公室对话")
                self.assertGreaterEqual(dialog.asset_list.count(), 1)
                self.assertIn("库资产｜★ 蓝色人偶", dialog.asset_list.item(0).text())
                self.assertIn("标签：男主, 蓝色, 办公室", dialog.asset_list.item(0).text())
            finally:
                dialog.close()

    def test_director_project_dialog_shows_texture_material_assets_and_applications(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            wall_color = Path(tmp) / "materials" / "office_wall_BaseColor.jpg"
            wall_roughness = Path(tmp) / "materials" / "office_wall_Roughness.jpg"
            studio_hdri = Path(tmp) / "hdris" / "studio_hdri.hdr"
            wall_color.parent.mkdir(parents=True, exist_ok=True)
            studio_hdri.parent.mkdir(parents=True, exist_ok=True)
            wall_color.write_bytes(b"jpg")
            wall_roughness.write_bytes(b"roughness")
            studio_hdri.write_bytes(b"hdr")
            metadata = {
                "project_name": "贴图材质显示测试",
                "asset_library_items": [
                    {
                        "id": "office_wall_color",
                        "name": "办公室墙_BaseColor",
                        "path": str(wall_color),
                        "file_name": "office_wall_BaseColor.jpg",
                        "format": "jpg",
                        "relative_path": "materials/office_wall_BaseColor.jpg",
                        "kind_hint": "material",
                        "texture_role": "base_color",
                        "source_profile_name": "ambientCG / CC0 材质",
                    },
                    {
                        "id": "studio_hdri",
                        "name": "摄影棚环境光",
                        "path": str(studio_hdri),
                        "file_name": "studio_hdri.hdr",
                        "format": "hdr",
                        "relative_path": "hdris/studio_hdri.hdr",
                        "kind_hint": "hdri",
                        "texture_role": "environment",
                        "source_profile_name": "Poly Haven / HDRI 与 CC0 资产",
                    },
                ],
                "assets": [
                    {
                        "id": "asset_office_wall",
                        "type": "material",
                        "name": "已应用办公室墙面",
                        "format": "jpg",
                        "path": str(wall_color),
                        "texture_paths": [str(wall_color), str(wall_roughness)],
                        "material_name": "OfficeWall",
                        "source_profile_name": "ambientCG / CC0 材质",
                    }
                ],
                "material_applications": [
                    {
                        "id": "application_office_wall",
                        "name": "办公室墙面材质",
                        "type": "material",
                        "material_name": "OfficeWall",
                        "objects": ["墙面"],
                        "texture_paths": [str(wall_color), str(wall_roughness)],
                        "texture_roles": ["base_color", "roughness"],
                        "source_profile_name": "ambientCG / CC0 材质",
                        "applied_at": "2026-07-10 14:20:00",
                    }
                ],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                labels = "\n".join(dialog.asset_list.item(i).text() for i in range(dialog.asset_list.count()))
                self.assertIn("库资产｜办公室墙_BaseColor", labels)
                self.assertIn("材质", labels)
                self.assertIn("贴图：base_color", labels)
                self.assertIn("来源：ambientCG / CC0 材质", labels)
                self.assertIn("库资产｜摄影棚环境光", labels)
                self.assertIn("HDRI", labels)
                self.assertIn("贴图：environment", labels)
                self.assertIn("材质｜已应用办公室墙面", labels)
                self.assertIn("贴图 2 张", labels)
                self.assertIn("材质：OfficeWall", labels)

                material_index = dialog.asset_filter_combo.findData("material")
                self.assertGreaterEqual(material_index, 0)
                dialog.asset_filter_combo.setCurrentIndex(material_index)
                material_labels = "\n".join(dialog.asset_list.item(i).text() for i in range(dialog.asset_list.count()))
                self.assertIn("办公室墙_BaseColor", material_labels)
                self.assertIn("已应用办公室墙面", material_labels)
                self.assertNotIn("摄影棚环境光", material_labels)

                hdri_index = dialog.asset_filter_combo.findData("hdri")
                self.assertGreaterEqual(hdri_index, 0)
                dialog.asset_filter_combo.setCurrentIndex(hdri_index)
                self.assertEqual(dialog.asset_list.count(), 1)
                self.assertIn("摄影棚环境光", dialog.asset_list.item(0).text())

                action_labels = "\n".join(dialog.action_list.item(i).text() for i in range(dialog.action_list.count()))
                self.assertIn("材质应用｜办公室墙面材质", action_labels)
                self.assertIn("对象 1 个", action_labels)
                self.assertIn("贴图 2 张", action_labels)
                self.assertIn("通道：base_color / roughness", action_labels)
            finally:
                dialog.close()

    def test_director_project_dialog_shows_asset_sources_and_builtin_pack(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_name": "生态资产源显示测试",
                "open_asset_source_profiles": [
                    {
                        "id": "mixamo",
                        "name": "Mixamo / 角色动作",
                        "formats": ["fbx", "bvh"],
                        "route": "动作库扫描后可套到演员骨骼。",
                    }
                ],
                "asset_sources": [
                    {
                        "id": "source_mixamo",
                        "name": "动作下载目录",
                        "path": tmp,
                        "profile_id": "mixamo",
                        "profile_name": "Mixamo / 角色动作",
                        "item_count": 7,
                        "route": "动作库扫描后可套到演员骨骼。",
                        "scanned_at": "2026-07-10 13:40:00",
                    }
                ],
                "builtin_asset_pack": [
                    {
                        "id": "builtin_blue_mannequin",
                        "name": "蓝色可控人偶",
                        "type": "character",
                        "format": "procedural",
                        "license": "procedural_local",
                        "controls": ["root_empty", "viewport_control_ring"],
                        "description": "内置影视人偶。",
                    }
                ],
                "asset_libraries": [
                    {
                        "id": "library_mixamo",
                        "name": "Mixamo动作库",
                        "path": tmp,
                        "source_profile_name": "Mixamo / 角色动作",
                        "item_count": 7,
                    }
                ],
                "asset_library_items": [],
                "assets": [
                    {
                        "type": "action",
                        "name": "已导入走路动作",
                        "format": "fbx",
                        "source_profile_name": "Mixamo / 角色动作",
                    }
                ],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                labels = "\n".join(dialog.asset_list.item(i).text() for i in range(dialog.asset_list.count()))
                self.assertIn("资产源｜动作下载目录", labels)
                self.assertIn("Mixamo / 角色动作", labels)
                self.assertIn("文件 7 个", labels)
                self.assertIn("资产库目录｜Mixamo动作库", labels)
                self.assertIn("来源：Mixamo / 角色动作", labels)
                self.assertIn("内置人物｜蓝色可控人偶", labels)
                self.assertIn("控制：root_empty / viewport_control_ring", labels)
                self.assertIn("动作｜已导入走路动作", labels)
            finally:
                dialog.close()

    def test_director_project_dialog_opens_selected_shot_file(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            shot_path = Path(tmp) / "shot_001.json"
            shot_path.write_text('{"id":"shot_001"}', encoding="utf-8")
            metadata = {
                "project_name": "镜头文件测试",
                "shots_dir": tmp,
                "shots": [
                    {
                        "id": "shot_001",
                        "name": "第一镜",
                        "output_type": "still",
                    }
                ],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                dialog.shot_list.setCurrentRow(0)
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_selected_shot()
                opened.assert_called_once_with(str(shot_path))
            finally:
                dialog.close()

    def test_director_project_dialog_opens_selected_scene_preset_file(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            preset_path = Path(tmp) / "preset_001.json"
            preset_path.write_text('{"id":"preset_001"}', encoding="utf-8")
            metadata = {
                "project_name": "场景预设文件测试",
                "presets_dir": tmp,
                "scene_presets": [
                    {
                        "id": "preset_001",
                        "name": "客厅站位",
                        "frame_start": 1,
                        "frame_end": 120,
                    }
                ],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                dialog.action_list.setCurrentRow(0)
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_selected_action_record()
                opened.assert_called_once_with(str(preset_path))
            finally:
                dialog.close()

    def test_director_project_dialog_opens_storyboard_report_first(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            manifest_path = Path(tmp) / "storyboard_manifest.json"
            manifest_path.write_text('{"entries":[]}', encoding="utf-8")
            report_path = Path(tmp) / "storyboard_report.html"
            report_path.write_text("<html></html>", encoding="utf-8")
            metadata = {
                "project_name": "分镜表测试",
                "project_dir": tmp,
                "storyboard_manifest_path": str(manifest_path),
                "storyboard_report_path": str(report_path),
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_storyboard_manifest()
                opened.assert_called_once_with(str(report_path))
            finally:
                dialog.close()

    def test_director_project_dialog_opens_production_report_first(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            manifest_path = Path(tmp) / "production_manifest.json"
            manifest_path.write_text('{"shots":[]}', encoding="utf-8")
            report_path = Path(tmp) / "production_report.html"
            report_path.write_text("<html></html>", encoding="utf-8")
            metadata = {
                "project_name": "制作清单测试",
                "project_dir": tmp,
                "production_manifest_path": str(manifest_path),
                "production_report_path": str(report_path),
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_production_report()
                opened.assert_called_once_with(str(report_path))
            finally:
                dialog.close()

    def test_director_project_dialog_generates_render_queue_report(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            render_path = Path(tmp) / "render.png"
            render_path.write_bytes(b"png")
            metadata = {
                "project_name": "界面渲染队列测试",
                "project_dir": tmp,
                "shots": [
                    {"id": "shot_a", "name": "镜头A"},
                    {"id": "shot_b", "name": "镜头B"},
                ],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_render_queue_report()
                report_path = Path(opened.call_args.args[0])
                self.assertTrue(report_path.exists())
                self.assertEqual(report_path.name, "render_queue.html")
                self.assertEqual(metadata["render_queue_report_path"], str(report_path))
                self.assertTrue(Path(metadata["render_queue_csv_path"]).exists())
            finally:
                dialog.close()

    def test_director_project_dialog_generates_scene_breakdown_report(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_name": "界面分场表测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "镜头A",
                        "scene_number": "场次01",
                        "scene_location": "办公室",
                        "scene_environment": "interior",
                        "scene_environment_label": "内景",
                        "scene_time": "day",
                        "scene_time_label": "日",
                    }
                ],
                "renders": [],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_scene_breakdown_report()
                report_path = Path(opened.call_args.args[0])
                self.assertTrue(report_path.exists())
                self.assertEqual(report_path.name, "scene_breakdown.html")
                self.assertEqual(metadata["scene_breakdown_report_path"], str(report_path))
                self.assertTrue(Path(metadata["scene_breakdown_csv_path"]).exists())
            finally:
                dialog.close()

    def test_director_project_dialog_generates_actor_schedule_report(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_name": "界面演员调度测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "镜头A",
                        "actors": [{"id": "actor_a", "name": "男主", "role": "主角"}],
                    }
                ],
                "renders": [],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_actor_schedule_report()
                report_path = Path(opened.call_args.args[0])
                self.assertTrue(report_path.exists())
                self.assertEqual(report_path.name, "actor_schedule.html")
                self.assertEqual(metadata["actor_schedule_report_path"], str(report_path))
                self.assertTrue(Path(metadata["actor_schedule_csv_path"]).exists())
            finally:
                dialog.close()

    def test_director_project_dialog_generates_project_dashboard(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_name": "界面工程总览测试",
                "project_dir": tmp,
                "shots": [{"id": "shot_a", "name": "镜头A"}],
                "renders": [],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_project_dashboard()
                dashboard_path = Path(opened.call_args.args[0])
                self.assertTrue(dashboard_path.exists())
                self.assertEqual(dashboard_path.name, "project_dashboard.html")
                self.assertEqual(metadata["project_dashboard_path"], str(dashboard_path))
            finally:
                dialog.close()

    def test_director_project_dialog_files_menu_opens_report(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_name": "制作文件菜单测试",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_a",
                        "name": "镜头A",
                        "frame_start": 1,
                        "frame_end": 48,
                    }
                ],
                "renders": [],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                files_buttons = [button for button in dialog.findChildren(QPushButton) if button.text() == "制作文件"]
                self.assertEqual(len(files_buttons), 1)
                menu = files_buttons[0].menu()
                self.assertIsNotNone(menu)
                labels = [action.text() for action in menu.actions()]
                for label in (
                    "工程总览",
                    "分镜表",
                    "渲染队列",
                    "批量渲染任务",
                    "后台渲染命令",
                    "镜头版本索引",
                    "分场表",
                    "分集交付清单",
                    "生成分集交付包",
                    "拍摄单",
                    "演员调度",
                    "剪辑时间线",
                    "剪辑 EDL",
                    "剪辑 FCPXML",
                    "后期交接清单",
                    "连续性检查",
                    "制作问题检查",
                    "制作清单",
                    "资产需求清单",
                    "动作匹配清单",
                    "交付检查",
                    "生成交付包",
                ):
                    self.assertIn(label, labels)

                handoff_action = next(action for action in menu.actions() if action.text() == "后期交接清单")
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    handoff_action.trigger()
                report_path = Path(opened.call_args.args[0])
                self.assertTrue(report_path.exists())
                self.assertEqual(report_path.name, "post_handoff.html")
                self.assertEqual(metadata["post_handoff_report_path"], str(report_path))
            finally:
                dialog.close()

    def test_director_project_dialog_generates_delivery_package(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            meta_path = Path(tmp) / "director_project.json"
            render_path = Path(tmp) / "render.png"
            render_path.write_bytes(b"png")
            metadata = {
                "project_name": "界面交付包测试",
                "project_dir": tmp,
                "meta_path": str(meta_path),
                "shots": [{"id": "shot_a", "name": "镜头A"}],
                "renders": [{"shot_id": "shot_a", "path": str(render_path), "preview_path": str(render_path)}],
            }
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_delivery_package()
                package_path = Path(opened.call_args.args[0])
                self.assertTrue(package_path.exists())
                self.assertEqual(package_path.parent.name, "delivery_packages")
                self.assertEqual(metadata["delivery_package_path"], str(package_path))
            finally:
                dialog.close()

    def test_director_project_dialog_generates_delivery_audit_report(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            metadata = {
                "project_name": "界面交付检查测试",
                "project_dir": tmp,
                "shots": [{"id": "shot_pending", "name": "未渲染镜头"}],
                "renders": [],
            }
            dialog = BlenderDirectorProjectDialog(metadata)
            try:
                with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                    dialog.open_delivery_audit()
                report_path = Path(opened.call_args.args[0])
                self.assertTrue(report_path.exists())
                self.assertEqual(report_path.name, "delivery_audit.html")
                self.assertEqual(metadata["delivery_audit_report_path"], str(report_path))
            finally:
                dialog.close()

    def test_director_project_folder_buttons_open_project_paths(self):
        scene = WorkflowScene(config={"providers": []}, load_defaults=False)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            assets_dir = str(Path(tmp) / "assets")
            renders_dir = str(Path(tmp) / "renders")
            storyboard_path = str(Path(tmp) / "storyboard_report.html")
            os.makedirs(assets_dir, exist_ok=True)
            os.makedirs(renders_dir, exist_ok=True)
            Path(storyboard_path).write_text("<html></html>", encoding="utf-8")
            node = scene.add_node("blender_director_project", QPointF(0, 0))
            node.data["director_project"] = {
                "project_dir": tmp,
                "assets_dir": assets_dir,
                "renders_dir": renders_dir,
                "storyboard_report_path": storyboard_path,
            }

            with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                scene.open_blender_director_project_folder(node)
                scene.open_blender_director_asset_folder(node)
                scene.open_blender_director_render_folder(node)
                scene.open_blender_director_storyboard_report(node)

            self.assertEqual(opened.call_args_list[0].args[0], tmp)
            self.assertEqual(opened.call_args_list[1].args[0], assets_dir)
            self.assertEqual(opened.call_args_list[2].args[0], renders_dir)
            self.assertEqual(opened.call_args_list[3].args[0], storyboard_path)

    def test_director_project_storyboard_button_generates_latest_report(self):
        scene = WorkflowScene(config={"providers": []}, load_defaults=False)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            meta_path = Path(tmp) / "director_project.json"
            metadata = {
                "project_id": "storyboard_button",
                "project_name": "节点分镜表",
                "project_dir": tmp,
                "shots": [
                    {
                        "id": "shot_01",
                        "name": "开场",
                        "note": "主角进入房间",
                        "frame_start": 1,
                        "frame_end": 48,
                        "output_type": "still",
                    }
                ],
                "renders": [],
            }
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            node = scene.add_node("blender_director_project", QPointF(0, 0))
            node.data["director_project"] = {"project_dir": tmp, "meta_path": str(meta_path)}

            with mock.patch("gpt_desktop.native_workflow.open_local_file", return_value=True) as opened:
                scene.open_blender_director_storyboard_report(node)

            report_path = Path(tmp) / "storyboard_report.html"
            manifest_path = Path(tmp) / "storyboard_manifest.json"
            opened.assert_called_once_with(str(report_path))
            self.assertTrue(report_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertIn("开场", report_path.read_text(encoding="utf-8"))
            self.assertEqual(node.data["director_project"]["storyboard_report_path"], str(report_path))


if __name__ == "__main__":
    unittest.main()
