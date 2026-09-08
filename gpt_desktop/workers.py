import asyncio
import gc
import hashlib
import json
import math
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy

import requests
from PySide6.QtCore import QThread, Signal

from .core import (
    IMAGE_DIR,
    VIDEO_DIR,
    _dated_image_dir,
    api_url,
    ensure_thumbnail_cache,
    extract_api_error,
    image_file_to_base64,
    image_suffix_from_bytes,
    image_suffix_from_content_type,
    now_str,
    prepare_image_upload_file,
    reasoning_effort_for_model,
    reasoning_effort_not_supported,
    requests_proxies,
    safe_response_text,
    safe_remove_file,
    save_base64_to_image,
    save_bytes_to_image,
)
from .novel_utils import (
    NOVEL_AI_CONTEXT_LIMIT,
    VOLUME_CONTINUATION_REQUEST_CHAR_BUDGET,
    VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET,
    _compact_volume_continuity_anchors,
    _compact_volume_handoff_for_framework,
    _compact_volume_handoff_source_for_request,
    _build_chapter_ai_context,
    _clean_chapter_plan_story_boundary,
    _clip_context_text,
    _dedupe_volume_handoff_terminal_records,
    _extract_prose_delivery_result,
    _infer_foreshadow_status,
    _merge_text_lines_without_duplicates,
    _merge_foreshadow_description_without_bloat,
    _merge_foreshadow_status,
    _normalize_creative_intent_contract,
    _normalize_volume_continuity_anchors,
    NOVEL_PROSE_END_MARKER,
    NOVEL_PROSE_START_MARKER,
)
from .novel_import import (
    _foreshadow_candidate_is_terminal_review,
    _foreshadow_terminal_review_description,
    _foreshadow_terminal_review_should_replace,
    _is_framework_placeholder_chapter_title,
    _is_framework_scope_title,
    _normalize_ai_candidates,
)

_BLENDER_PROBE_CACHE = {}


_CHAPTER_PLAN_STATE_PROGRESSION_GUIDANCE = (
    "长期状态推进要求：对项目资料中已经明确的受伤、疾病、修养、长期身体限制、身份风险、持续追踪、关系僵局和未决任务，"
    "阶段与章节规划必须安排自然的变化路径：从当前影响走向继续、缓解、恶化、转化、解决或稳定。"
    "可以暂不解决，但必须给出本阶段真实的新后果或下一推进窗口，不能让同一句状态原样跨多个章节。"
    "恢复或解决必须有资料中已有或剧情自然建立的时间、资源、事件依据；不要凭空痊愈，"
    "也不要把状态推进拆成固定办理流程或要求每章处理所有状态。"
)


class NovelContextBuildWorker(QThread):
    """Build a chapter prompt from an immutable project snapshot off the UI thread."""

    result_ready = Signal(str, str, str, str)
    failed = Signal(str, str, str, str)

    def __init__(self, token, action, project_snapshot, chapter_index, project_path="", chapter_id=""):
        super().__init__()
        self.token = str(token or "")
        self.action = str(action or "")
        self.project_snapshot = deepcopy(project_snapshot if isinstance(project_snapshot, dict) else {})
        self.chapter_index = int(chapter_index or 0)
        self.project_path = str(project_path or "")
        self.chapter_id = str(chapter_id or "")

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            context = _build_chapter_ai_context(
                self.project_snapshot,
                self.chapter_index,
                self.action,
            )
            if not self.isInterruptionRequested():
                self.result_ready.emit(self.token, self.action, self.chapter_id, context)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.token, self.action, self.chapter_id, str(exc))


def post_json(session, url, headers, payload, timeout, proxies=None):
    r = session.post(url, headers=headers, json=payload, timeout=timeout, proxies=proxies)
    try:
        if r.status_code >= 400:
            raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")
        return r.json()
    finally:
        try:
            r.close()
        except Exception:
            pass


def _blender_candidate_paths(path=""):
    candidates = []

    def add_raw(raw_path):
        raw_path = str(raw_path or "").strip().strip('"')
        if not raw_path:
            return
        candidates.append(raw_path)
        if raw_path.lower().endswith(".app") or os.path.isdir(raw_path):
            candidates.append(os.path.join(raw_path, "Contents", "MacOS", "Blender"))
            candidates.append(os.path.join(raw_path, "Contents", "MacOS", "blender"))
            candidates.append(os.path.join(raw_path, "blender"))
            candidates.append(os.path.join(raw_path, "blender.exe"))

    add_raw(path)
    add_raw(os.environ.get("BLENDER_PATH", ""))

    app_roots = [
        "/Applications",
        os.path.expanduser("~/Applications"),
    ]
    for root in app_roots:
        if not os.path.isdir(root):
            continue
        try:
            app_names = sorted(os.listdir(root), reverse=True)
        except Exception:
            continue
        for name in app_names:
            if "blender" not in name.lower() or not name.lower().endswith(".app"):
                continue
            app_path = os.path.join(root, name)
            candidates.append(os.path.join(app_path, "Contents", "MacOS", "Blender"))
            candidates.append(os.path.join(app_path, "Contents", "MacOS", "blender"))

    which_path = shutil.which("blender")
    if which_path:
        candidates.append(which_path)

    if os.name == "nt":
        program_files = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        for root in program_files:
            if not root:
                continue
            blender_root = os.path.join(root, "Blender Foundation")
            if not os.path.isdir(blender_root):
                continue
            try:
                for name in sorted(os.listdir(blender_root), reverse=True):
                    candidates.append(os.path.join(blender_root, name, "blender.exe"))
            except Exception:
                pass

    seen = set()
    result = []
    for candidate in candidates:
        candidate = os.path.abspath(os.path.expanduser(str(candidate or "").strip()))
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def _probe_blender_executable(path):
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        return False, "文件不存在或没有执行权限。"
    cache_key = os.path.abspath(os.path.expanduser(path))
    if cache_key in _BLENDER_PROBE_CACHE:
        return _BLENDER_PROBE_CACHE[cache_key]
    try:
        result = subprocess.run(
            [path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        if result.returncode == 0:
            unstable_reason = _known_unstable_blender_reason(result.stdout or result.stderr or "")
            if unstable_reason:
                outcome = (False, unstable_reason)
                _BLENDER_PROBE_CACHE[cache_key] = outcome
                return outcome
            ok, reason = _probe_blender_background_startup(path)
            outcome = (ok, reason)
            _BLENDER_PROBE_CACHE[cache_key] = outcome
            return outcome
        detail = "\n".join((result.stderr or result.stdout or "").splitlines()[-4:]).strip()
        outcome = (False, detail or f"Blender 启动失败，退出码 {result.returncode}。")
        _BLENDER_PROBE_CACHE[cache_key] = outcome
        return outcome
    except subprocess.TimeoutExpired:
        outcome = (True, "")
        _BLENDER_PROBE_CACHE[cache_key] = outcome
        return outcome
    except OSError as e:
        outcome = (False, str(e))
        _BLENDER_PROBE_CACHE[cache_key] = outcome
        return outcome
    except Exception as e:
        outcome = (False, str(e))
        _BLENDER_PROBE_CACHE[cache_key] = outcome
        return outcome


def _probe_blender_background_startup(path):
    if platform.system() != "Darwin":
        return True, ""
    try:
        result = subprocess.run(
            [
                path,
                "--background",
                "--factory-startup",
                "--disable-crash-handler",
                "--python-expr",
                'print("BLENDER_PROBE_OK")',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
        )
    except subprocess.TimeoutExpired:
        return False, "Blender 后台启动自检超时。"
    except OSError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)
    if result.returncode == 0 and "BLENDER_PROBE_OK" in (result.stdout or ""):
        return True, ""
    detail = "\n".join((result.stderr or result.stdout or "").splitlines()[-8:]).strip()
    reason = detail or f"Blender 后台启动自检失败，退出码 {result.returncode}。"
    if result.returncode in (-11, 139):
        reason = f"Blender 后台启动时崩溃。\n{reason}"
    return False, reason


def _parse_blender_version(version_text):
    match = re.search(r"Blender\s+(\d+)\.(\d+)(?:\.(\d+))?", str(version_text or ""))
    if not match:
        return ()
    return tuple(int(part or 0) for part in match.groups())


def _mac_display_summary():
    if platform.system() != "Darwin":
        return ""
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    lines = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(("Chipset Model:", "Metal:")):
            lines.append(stripped)
    return "\n".join(lines)


def _known_unstable_blender_reason(version_text):
    version = _parse_blender_version(version_text)
    if not version:
        return ""
    if platform.system() != "Darwin" or platform.machine().lower() not in ("x86_64", "amd64"):
        return ""
    display = _mac_display_summary()
    display_lower = display.lower()
    older_intel_gpu = any(name in display_lower for name in ("intel hd graphics", "intel iris"))
    if version >= (4, 2, 0) and older_intel_gpu:
        version_label = ".".join(str(part) for part in version)
        return (
            f"当前 Blender {version_label} 在这台 Intel Mac 的图形环境下容易在 Metal 初始化阶段崩溃。\n"
            f"{display}\n"
            "建议安装 Blender 2.93.18 LTS 的 macOS x64/Intel 版本后再渲染分镜。"
        )
    return ""


def _blender_cpu_hint(reason):
    text = str(reason or "").lower()
    if "bad cpu type" not in text:
        return ""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "当前电脑是 Intel/x64 架构，但这个 Blender 看起来是 Apple Silicon/arm64 版。请下载 macOS x64/Intel 版本。"
    if machine in ("arm64", "aarch64"):
        return "当前电脑是 Apple Silicon/arm64 架构，但这个 Blender 不能在当前环境运行。请下载 macOS arm64 版本，或安装 Rosetta 后使用 x64 版本。"
    return "这个 Blender 的架构和当前电脑不匹配，请下载对应电脑芯片的版本。"


def _is_usable_blender_executable(path):
    ok, _ = _probe_blender_executable(path)
    return ok


def blender_detection_issue(path=""):
    for candidate in _blender_candidate_paths(path):
        if not os.path.exists(candidate):
            continue
        ok, reason = _probe_blender_executable(candidate)
        if ok:
            continue
        hint = _blender_cpu_hint(reason)
        if hint:
            reason = f"{reason}\n{hint}"
        return f"已找到 Blender，但无法启动：\n{candidate}\n\n原因：{reason}"
    return ""


def resolve_blender_executable(path=""):
    for candidate in _blender_candidate_paths(path):
        if _is_usable_blender_executable(candidate):
            return candidate
    return ""


def _blender_storyboard_script(prompt, output_path, width, height):
    config = {
        "prompt": str(prompt or ""),
        "output_path": str(output_path or ""),
        "width": int(width or 1280),
        "height": int(height or 720),
    }
    config_json = json.dumps(config, ensure_ascii=False)
    return f"""# -*- coding: utf-8 -*-
import json
import math
import os

import bpy
from mathutils import Vector

CONFIG = json.loads({config_json!r})
PROMPT = str(CONFIG.get("prompt") or "")
OUTPUT_PATH = str(CONFIG.get("output_path") or "")
WIDTH = int(CONFIG.get("width") or 1280)
HEIGHT = int(CONFIG.get("height") or 720)


def has_any(words):
    return any(word in PROMPT for word in words)


def make_mat(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def set_mat(obj, mat):
    obj.data.materials.append(mat)
    return obj


def add_cube(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    set_mat(obj, mat)
    return obj


def add_cylinder(name, loc, radius, depth, mat, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth, location=loc, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    set_mat(obj, mat)
    return obj


def add_sphere(name, loc, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=radius, location=loc)
    obj = bpy.context.object
    obj.name = name
    set_mat(obj, mat)
    return obj


def add_label(text, loc):
    bpy.ops.object.text_add(location=loc, rotation=(math.radians(75), 0, 0))
    obj = bpy.context.object
    obj.name = "角色标记 " + text
    obj.data.body = text
    obj.data.align_x = "CENTER"
    obj.data.align_y = "CENTER"
    obj.data.size = 0.28
    set_mat(obj, MAT_DARK)
    return obj


def make_person(label, x, y, mat):
    add_cylinder(label + " 身体", (x, y, 1.18), 0.22, 1.2, mat)
    add_sphere(label + " 头部", (x, y, 1.92), 0.23, MAT_SKIN)
    add_cylinder(label + " 左臂", (x - 0.34, y, 1.34), 0.055, 0.75, mat, rotation=(0, math.radians(72), 0))
    add_cylinder(label + " 右臂", (x + 0.34, y, 1.34), 0.055, 0.75, mat, rotation=(0, math.radians(-72), 0))
    add_cylinder(label + " 左腿", (x - 0.11, y, 0.42), 0.07, 0.84, MAT_DARK)
    add_cylinder(label + " 右腿", (x + 0.11, y, 0.42), 0.07, 0.84, MAT_DARK)
    add_label(label, (x, y - 0.42, 2.36))


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

scene = bpy.context.scene
try:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.preview_samples = 8
except Exception:
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except Exception:
        scene.render.engine = "BLENDER_WORKBENCH"

scene.render.resolution_x = WIDTH
scene.render.resolution_y = HEIGHT
scene.render.film_transparent = False
scene.render.filepath = OUTPUT_PATH
try:
    scene.eevee.taa_render_samples = 32
except Exception:
    pass
try:
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
except Exception:
    pass

MAT_FLOOR = make_mat("冷灰地面", (0.32, 0.35, 0.38, 1))
MAT_WALL = make_mat("背景墙", (0.18, 0.22, 0.27, 1))
MAT_TABLE = make_mat("桌面", (0.30, 0.20, 0.13, 1))
MAT_BLUE = make_mat("角色A 蓝", (0.10, 0.38, 0.86, 1))
MAT_RED = make_mat("角色B 红", (0.78, 0.18, 0.15, 1))
MAT_GREEN = make_mat("角色C 绿", (0.12, 0.55, 0.28, 1))
MAT_PURPLE = make_mat("角色D 紫", (0.46, 0.26, 0.72, 1))
MAT_GOLD = make_mat("角色E 金", (0.90, 0.62, 0.12, 1))
MAT_SKIN = make_mat("头部", (0.88, 0.70, 0.55, 1))
MAT_DARK = make_mat("深色标记", (0.04, 0.05, 0.07, 1))

add_cube("地面", (0, 0, -0.03), (4.8, 4.2, 0.03), MAT_FLOOR)
add_cube("后墙", (0, 2.1, 1.55), (4.8, 0.05, 1.6), MAT_WALL)
add_cube("左侧景片", (-2.4, 0, 1.05), (0.05, 2.1, 1.1), MAT_WALL)

is_meeting = has_any(["会议", "桌", "办公室", "审讯", "谈判", "董事会"])
is_door = has_any(["门口", "推门", "进门", "门"])
if is_meeting:
    add_cube("会议桌", (0, 0.45, 0.62), (1.5, 0.58, 0.12), MAT_TABLE)
    add_cube("桌脚一", (-1.1, 0.1, 0.28), (0.08, 0.08, 0.28), MAT_DARK)
    add_cube("桌脚二", (1.1, 0.1, 0.28), (0.08, 0.08, 0.28), MAT_DARK)
if is_door:
    add_cube("门框", (-1.95, 1.92, 1.15), (0.34, 0.08, 1.15), MAT_TABLE)

count = 2
if has_any(["独自", "一个人", "单人"]):
    count = 1
elif has_any(["三人", "三名", "三个人", "三位"]):
    count = 3
elif has_any(["四人", "四名", "四个人", "四位"]):
    count = 4
elif has_any(["众人", "多人", "人群", "两侧", "会议室"]):
    count = 5

positions = [(-0.85, -0.4), (0.85, -0.25), (0.0, 0.8), (-1.45, 0.65), (1.45, 0.65)]
materials = [MAT_BLUE, MAT_RED, MAT_GREEN, MAT_PURPLE, MAT_GOLD]
for idx in range(count):
    x, y = positions[idx]
    make_person(chr(ord("A") + idx), x, y, materials[idx])

if has_any(["对峙", "冲突", "压迫", "审讯", "质问"]):
    add_cube("冲突焦点线", (0, -0.05, 0.04), (1.7, 0.025, 0.025), MAT_GOLD)

bpy.ops.object.light_add(type="AREA", location=(0, -2.3, 4.2))
light = bpy.context.object
light.name = "主光"
light.data.energy = 550
light.data.size = 4

bpy.ops.object.camera_add(location=(0, -6.4, 2.45))
camera = bpy.context.object
if has_any(["低角度", "仰拍", "压迫感"]):
    camera.location = (0, -6.2, 1.25)
    camera.data.lens = 30
elif has_any(["俯拍", "顶拍"]):
    camera.location = (0, -4.8, 6.2)
    camera.data.lens = 28
elif has_any(["侧面", "侧拍"]):
    camera.location = (4.8, -3.2, 2.2)
    camera.data.lens = 36
else:
    camera.data.lens = 34
look_at(camera, (0, 0.1, 1.15))
scene.camera = camera

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
bpy.ops.render.render(write_still=True)
"""


class BlenderStoryboardWorker(QThread):
    progress = Signal(str)
    result_ready = Signal(dict)
    failed = Signal(str)
    REQUEST_TIMEOUT = 300

    def __init__(self, blender_path, prompt, width=1280, height=720):
        super().__init__()
        self.blender_path = str(blender_path or "").strip()
        self.prompt = str(prompt or "").strip()
        self.width = int(width or 1280)
        self.height = int(height or 720)
        self._stop_requested = False
        self._process = None
        self._output_path = ""

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        proc = self._process
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _raise_if_stopped(self):
        if self._stop_requested or self.isInterruptionRequested():
            raise Exception("任务已中止")

    def _render_storyboard(self):
        executable = resolve_blender_executable(self.blender_path)
        if not executable:
            raise Exception("没有找到 Blender。请先安装 Blender，或在节点运行时选择 blender.exe / Blender 可执行文件。")
        if not self.prompt:
            raise Exception("请先输入镜头描述。")

        output_dir = _dated_image_dir()
        os.makedirs(output_dir or IMAGE_DIR, exist_ok=True)
        output_path = os.path.join(output_dir or IMAGE_DIR, f"blender_storyboard_{uuid.uuid4().hex}.png")
        self._output_path = output_path

        script_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as f:
                script_path = f.name
                f.write(_blender_storyboard_script(self.prompt, output_path, self.width, self.height))

            self.progress.emit("正在启动 Blender 后台渲染分镜...")
            cmd = [executable, "--background", "--factory-startup", "--python", script_path]
            started_at = time.monotonic()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._process = proc
            stdout = ""
            stderr = ""
            while True:
                self._raise_if_stopped()
                try:
                    stdout, stderr = proc.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() - started_at > self.REQUEST_TIMEOUT:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    raise Exception("Blender 渲染超时，请降低分辨率或检查场景资源。")
            self._process = None
            if proc.returncode != 0:
                combined = "\n".join(part for part in (stdout, stderr) if part)
                tail = "\n".join(combined.splitlines()[-18:]).strip()
                raise Exception(f"Blender 渲染失败：{tail or '未知错误'}")
            self._raise_if_stopped()
            if not os.path.exists(output_path) or os.path.getsize(output_path) <= 0:
                tail = "\n".join((stderr or stdout or "").splitlines()[-8:]).strip()
                raise Exception(f"Blender 没有输出分镜图片。{tail}")
            return output_path
        finally:
            self._process = None
            if script_path:
                safe_remove_file(script_path)

    def run(self):
        try:
            path = self._render_storyboard()
            self.progress.emit("Blender 分镜参考图已生成。")
            self.result_ready.emit({
                "time": now_str(),
                "prompt": self.prompt,
                "refs": [],
                "images": [path],
                "model": "Blender 本地分镜",
                "size": f"{self.width}x{self.height}",
                "quality": "本地预览",
                "n": "1",
                "blender_path": resolve_blender_executable(self.blender_path),
            })
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.failed.emit("任务已中止")
            else:
                self.failed.emit(str(e))


def _blender_director_script(plan, output_path, width, height):
    config = {
        "plan": plan if isinstance(plan, dict) else {},
        "output_path": str(output_path or ""),
        "width": int(width or 1280),
        "height": int(height or 720),
    }
    config_json = json.dumps(config, ensure_ascii=False)
    return f"""# -*- coding: utf-8 -*-
import json
import math
import os

import bpy
from mathutils import Vector

CONFIG = json.loads({config_json!r})
PLAN = CONFIG.get("plan") or {{}}
OUTPUT_PATH = str(CONFIG.get("output_path") or "")
WIDTH = int(CONFIG.get("width") or 1280)
HEIGHT = int(CONFIG.get("height") or 720)


def text_for(*keys):
    parts = []
    for key in keys:
        value = PLAN.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if str(item).strip())
        elif str(value or "").strip():
            parts.append(str(value).strip())
    return "\\n".join(parts)


SCENE_TEXT = text_for("scene_prompt", "render_prompt")
CHARACTER_TEXT = text_for("character_prompt")
CAMERA_TEXT = text_for("camera_prompt", "render_prompt")
ALL_TEXT = "\\n".join([SCENE_TEXT, CHARACTER_TEXT, CAMERA_TEXT])


def has_any(words, text=None):
    text = ALL_TEXT if text is None else text
    return any(word in text for word in words)


def make_mat(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def set_mat(obj, mat):
    try:
        obj.data.materials.append(mat)
    except Exception:
        pass
    return obj


def add_cube(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    set_mat(obj, mat)
    return obj


def add_cylinder(name, loc, radius, depth, mat, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=radius, depth=depth, location=loc, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    set_mat(obj, mat)
    return obj


def add_sphere(name, loc, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=radius, location=loc)
    obj = bpy.context.object
    obj.name = name
    set_mat(obj, mat)
    return obj


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def make_person(label, x, y, mat):
    add_cylinder(label + " 身体", (x, y, 1.08), 0.20, 1.1, mat)
    add_sphere(label + " 头部", (x, y, 1.76), 0.22, MAT_SKIN)
    add_cylinder(label + " 左臂", (x - 0.31, y, 1.24), 0.045, 0.68, mat, rotation=(0, math.radians(68), 0))
    add_cylinder(label + " 右臂", (x + 0.31, y, 1.24), 0.045, 0.68, mat, rotation=(0, math.radians(-68), 0))
    add_cylinder(label + " 左腿", (x - 0.10, y, 0.38), 0.06, 0.76, MAT_DARK)
    add_cylinder(label + " 右腿", (x + 0.10, y, 0.38), 0.06, 0.76, MAT_DARK)


def scene_objects_from_import():
    return [obj for obj in bpy.context.scene.objects if obj.type not in {"CAMERA", "LIGHT"}]


def normalize_imported_objects(objects, target_location, target_height=1.7):
    mesh_like = [obj for obj in objects if obj.type in {"MESH", "CURVE", "SURFACE", "ARMATURE", "EMPTY"}]
    if not mesh_like:
        return
    corners = []
    for obj in mesh_like:
        try:
            for corner in obj.bound_box:
                corners.append(obj.matrix_world @ Vector(corner))
        except Exception:
            pass
    if not corners:
        for obj in mesh_like:
            obj.location = target_location
        return
    min_v = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    max_v = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    center = (min_v + max_v) * 0.5
    height = max(0.01, max_v.z - min_v.z)
    scale = min(1.8, max(0.05, target_height / height))
    target = Vector(target_location)
    selected = set(mesh_like)
    roots = [obj for obj in mesh_like if obj.parent not in selected]
    for obj in roots:
        obj.location = (obj.location - center) * scale + target
        obj.scale = obj.scale * scale


def import_asset(path, index):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    try:
        if ext in {".glb", ".gltf"}:
            bpy.ops.import_scene.gltf(filepath=path)
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        elif ext == ".obj":
            if hasattr(bpy.ops, "wm") and hasattr(bpy.ops.wm, "obj_import"):
                bpy.ops.wm.obj_import(filepath=path)
            else:
                bpy.ops.import_scene.obj(filepath=path)
        else:
            return False
    except Exception as exc:
        print("导入模型失败:", path, exc)
        return False
    imported = [obj for obj in bpy.data.objects if obj not in before]
    positions = [(-0.9, -0.25, 0.0), (0.9, -0.25, 0.0), (0.0, 0.75, 0.0), (-1.6, 0.55, 0.0), (1.6, 0.55, 0.0)]
    normalize_imported_objects(imported, positions[index % len(positions)], 1.65)
    return True


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

scene = bpy.context.scene
try:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.preview_samples = 8
except Exception:
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except Exception:
        pass
scene.render.resolution_x = WIDTH
scene.render.resolution_y = HEIGHT
scene.render.film_transparent = bool(PLAN.get("transparent"))
scene.render.filepath = OUTPUT_PATH
try:
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
except Exception:
    pass

MAT_FLOOR = make_mat("地面冷灰", (0.30, 0.33, 0.36, 1))
MAT_WALL = make_mat("背景墙", (0.18, 0.21, 0.26, 1))
MAT_ROAD = make_mat("街道路面", (0.08, 0.09, 0.10, 1))
MAT_LINE = make_mat("道路标线", (0.88, 0.78, 0.38, 1))
MAT_STAGE = make_mat("舞台", (0.22, 0.15, 0.18, 1))
MAT_TABLE = make_mat("道具木色", (0.30, 0.20, 0.12, 1))
MAT_BLUE = make_mat("角色蓝", (0.10, 0.38, 0.86, 1))
MAT_RED = make_mat("角色红", (0.78, 0.18, 0.15, 1))
MAT_GREEN = make_mat("角色绿", (0.12, 0.55, 0.28, 1))
MAT_SKIN = make_mat("头部肤色", (0.86, 0.68, 0.52, 1))
MAT_DARK = make_mat("深色", (0.04, 0.05, 0.07, 1))

if has_any(["街道", "路口", "马路", "巷子", "城市"], SCENE_TEXT):
    add_cube("街道路面", (0, 0, -0.03), (4.8, 4.2, 0.03), MAT_ROAD)
    add_cube("道路中线", (0, 0, 0.005), (0.05, 4.0, 0.01), MAT_LINE)
    add_cube("左侧建筑", (-2.25, 0.6, 1.1), (0.32, 1.8, 1.1), MAT_WALL)
    add_cube("右侧建筑", (2.25, 0.6, 1.1), (0.32, 1.8, 1.1), MAT_WALL)
elif has_any(["舞台", "演出", "发布会", "聚光灯"], SCENE_TEXT):
    add_cube("舞台地台", (0, 0.15, 0.12), (2.4, 1.35, 0.12), MAT_STAGE)
    add_cube("舞台背景", (0, 1.55, 1.45), (3.8, 0.06, 1.45), MAT_WALL)
    add_cube("左幕布", (-1.9, 1.45, 1.35), (0.18, 0.08, 1.35), MAT_RED)
    add_cube("右幕布", (1.9, 1.45, 1.35), (0.18, 0.08, 1.35), MAT_RED)
else:
    add_cube("房间地面", (0, 0, -0.03), (4.8, 4.2, 0.03), MAT_FLOOR)
    add_cube("后墙", (0, 2.05, 1.45), (4.8, 0.05, 1.45), MAT_WALL)
    add_cube("左墙", (-2.4, 0.2, 1.1), (0.05, 1.9, 1.1), MAT_WALL)
    if has_any(["会议", "办公室", "审讯", "谈判", "桌"], SCENE_TEXT):
        add_cube("会议桌", (0, 0.45, 0.58), (1.45, 0.55, 0.10), MAT_TABLE)
        add_cube("文件道具", (-0.35, 0.2, 0.66), (0.22, 0.15, 0.015), MAT_LINE)

asset_paths = [str(path) for path in PLAN.get("asset_paths", []) if str(path).strip()]
imported_count = 0
for idx, path in enumerate(asset_paths):
    if os.path.exists(path) and import_asset(path, idx):
        imported_count += 1

if imported_count <= 0:
    count = 2
    if has_any(["独自", "单人", "一个人"], CHARACTER_TEXT):
        count = 1
    elif has_any(["三人", "三名", "三位"], CHARACTER_TEXT):
        count = 3
    elif has_any(["多人", "众人", "人群", "会议"], CHARACTER_TEXT + SCENE_TEXT):
        count = 3
    positions = [(-0.8, -0.35), (0.8, -0.25), (0.0, 0.75)]
    mats = [MAT_BLUE, MAT_RED, MAT_GREEN]
    for idx in range(count):
        x, y = positions[idx]
        make_person("角色" + str(idx + 1), x, y, mats[idx])

if has_any(["门", "门口", "进门"], SCENE_TEXT + CHARACTER_TEXT):
    add_cube("门框", (-1.95, 1.9, 1.05), (0.30, 0.08, 1.05), MAT_TABLE)
if has_any(["沙发"], SCENE_TEXT):
    add_cube("沙发", (0.65, 0.9, 0.35), (0.75, 0.32, 0.22), MAT_TABLE)

bpy.ops.object.light_add(type="AREA", location=(0, -2.4, 4.2))
key_light = bpy.context.object
key_light.name = "主光"
key_light.data.energy = 450
key_light.data.size = 5
bpy.ops.object.camera_add(location=(0, -5.0, 2.0), rotation=(math.radians(68), 0, 0))
camera = bpy.context.object

target = (0, 0.25, 1.2)
camera.data.lens = 35
if has_any(["近景", "特写", "半身"], CAMERA_TEXT):
    camera.location = (0, -3.0, 1.55)
    camera.data.lens = 55
    target = (0, -0.15, 1.45)
elif has_any(["远景", "全景", "大全景"], CAMERA_TEXT):
    camera.location = (0, -6.4, 2.4)
    camera.data.lens = 26
elif has_any(["俯拍", "高角度"], CAMERA_TEXT):
    camera.location = (0, -4.2, 4.2)
    camera.data.lens = 32
    target = (0, 0.25, 0.75)
elif has_any(["仰拍", "低角度"], CAMERA_TEXT):
    camera.location = (0, -4.2, 0.85)
    camera.data.lens = 34
    target = (0, 0.15, 1.55)
if has_any(["侧面", "侧拍"], CAMERA_TEXT):
    camera.location = (4.0, -2.6, 1.85)
if has_any(["推镜", "推近", "推进"], CAMERA_TEXT):
    camera.data.lens = max(camera.data.lens, 45)
look_at(camera, target)
scene.camera = camera

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
bpy.ops.render.render(write_still=True)
"""


class BlenderDirectorWorker(QThread):
    progress = Signal(str)
    result_ready = Signal(dict)
    failed = Signal(str)
    REQUEST_TIMEOUT = 300

    def __init__(self, blender_path, plan, width=1280, height=720):
        super().__init__()
        self.blender_path = str(blender_path or "").strip()
        self.plan = plan if isinstance(plan, dict) else {}
        self.width = int(width or 1280)
        self.height = int(height or 720)
        self._stop_requested = False
        self._process = None
        self._output_path = ""

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        proc = self._process
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _raise_if_stopped(self):
        if self._stop_requested or self.isInterruptionRequested():
            raise Exception("任务已中止")

    def _render_director_frame(self):
        executable = resolve_blender_executable(self.blender_path)
        if not executable:
            issue = blender_detection_issue(self.blender_path)
            raise Exception(issue or "没有找到可用的 Blender。")

        output_dir = _dated_image_dir()
        os.makedirs(output_dir or IMAGE_DIR, exist_ok=True)
        output_path = os.path.join(output_dir or IMAGE_DIR, f"blender_director_{uuid.uuid4().hex}.png")
        self._output_path = output_path

        script_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as f:
                script_path = f.name
                f.write(_blender_director_script(self.plan, output_path, self.width, self.height))

            self.progress.emit("正在启动 Blender 后台渲染导演台参考图...")
            cmd = [executable, "--background", "--factory-startup", "--python", script_path]
            started_at = time.monotonic()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._process = proc
            stdout = ""
            stderr = ""
            while True:
                self._raise_if_stopped()
                try:
                    stdout, stderr = proc.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() - started_at > self.REQUEST_TIMEOUT:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    raise Exception("Blender 渲染超时，请降低分辨率或简化场景。")
            self._process = None
            if proc.returncode != 0:
                combined = "\n".join(part for part in (stdout, stderr) if part)
                tail = "\n".join(combined.splitlines()[-18:]).strip()
                raise Exception(f"Blender 导演台渲染失败：{tail or '未知错误'}")
            self._raise_if_stopped()
            if not os.path.exists(output_path) or os.path.getsize(output_path) <= 0:
                tail = "\n".join((stderr or stdout or "").splitlines()[-8:]).strip()
                raise Exception(f"Blender 没有输出导演台图片。{tail}")
            return output_path
        finally:
            self._process = None
            if script_path:
                safe_remove_file(script_path)

    def run(self):
        try:
            path = self._render_director_frame()
            self.progress.emit("Blender 导演台参考图已生成。")
            self.result_ready.emit({
                "time": now_str(),
                "prompt": self.plan.get("render_prompt") or self.plan.get("scene_prompt") or "",
                "refs": [path for path in self.plan.get("asset_paths", []) if isinstance(path, str) and os.path.exists(path)],
                "images": [path],
                "model": "Blender 本地导演台",
                "size": f"{self.width}x{self.height}",
                "quality": "本地预览",
                "n": "1",
                "blender_path": resolve_blender_executable(self.blender_path),
                "blender_plan": self.plan,
            })
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.failed.emit("任务已中止")
            else:
                self.failed.emit(str(e))


class ModelListWorker(QThread):
    result_ready = Signal(str, str, list)
    failed = Signal(str, str, str)

    def __init__(self, base_url, api_key, proxy_url="", proxy_mode="不使用代理", provider_id="", request_id=""):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "不使用代理").strip()
        self.provider_id = str(provider_id or "").strip()
        self.request_id = str(request_id or "").strip()
        self._stop_requested = False
        self._response = None
        self._session = None

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        try:
            if self._response is not None:
                self._response.close()
        except Exception:
            pass
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass

    def _proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商或设置中转地址。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")

            url = api_url(self.base_url, "/v1/models")
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            session = requests.Session()
            self._session = session
            session.trust_env = False
            try:
                r = session.get(url, headers=headers, timeout=10, proxies=self._proxies())
                self._response = r
                try:
                    if r.status_code >= 400:
                        raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")
                    data = r.json()
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass
            finally:
                try:
                    session.close()
                except Exception:
                    pass
            models = sorted({item.get("id") for item in data.get("data", []) if item.get("id")})
            if not models:
                raise Exception("接口没有返回可用模型。")
            if self._stop_requested or self.isInterruptionRequested():
                return
            self.result_ready.emit(self.provider_id, self.request_id, models)
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self.failed.emit(self.provider_id, self.request_id, str(e))
        finally:
            self._response = None
            self._session = None


class NovelAnalysisWorker(QThread):
    partial_ready = Signal(dict, int, int)
    result_ready = Signal(dict)
    failed = Signal(str)
    progress = Signal(str)
    output_chars = Signal(int)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        text,
        proxy_url="",
        proxy_mode="不使用代理",
        max_concurrency=3,
        chunks=None,
        dossier="",
    ):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.text = str(text or "")
        self.dossier = str(dossier or "").strip()
        self.input_chunk_records = self._normalize_input_chunk_records(chunks)
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "不使用代理").strip()
        self._stop_requested = False
        self._response = None
        self._active_responses = set()
        self._active_sessions = set()
        self._network_lock = threading.Lock()
        self._capability_lock = threading.Lock()
        self._output_chars_lock = threading.Lock()
        self._output_chars_total = 0
        self._analysis_response_format_supported = True
        self._analysis_stream_supported = True
        # Long-form chapter planning must keep using SSE across retries. Other
        # analysis workers retain the existing stream/non-stream compatibility fallback.
        self._analysis_stream_only = False
        self._diagnostic_lock = threading.Lock()
        self.diagnostic_request_id = ""
        self.diagnostic_started_at = 0.0
        self.diagnostic_stage = ""
        self.diagnostic_project_path = ""
        self.diagnostic_project_title = ""
        self.diagnostic_provider = {}
        self.last_system_prompt = ""
        self.last_user_text = ""
        self.last_partial_output = ""
        self.last_invalid_json_output = ""
        input_bytes = self.text.encode("utf-8", errors="replace")
        self.diagnostics = {
            "requested_model": str(self.model or ""),
            "response_models": [],
            "input_chars": len(self.text),
            "input_utf8_bytes": len(input_bytes),
            "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "api_call_count": 0,
            "retry_count": 0,
            "structure_repair_count": 0,
            "structure_regeneration_count": 0,
            "attempts": [],
            "outcome": "pending",
            "elapsed_ms": 0,
            "started_at": "",
            "finished_at": "",
            "reasoning_chars": 0,
            "content_chars": 0,
            "partial_output_chars": 0,
            "last_http_status": 0,
            "last_response_headers": {},
            "http_status": 0,
            "response_headers": {},
            "response_chars": 0,
            "time_to_headers_ms": 0,
            "time_to_first_piece_ms": 0,
            "max_idle_gap_ms": 0,
            "finish_reason": "",
            "done_received": False,
            "json_syntax_repair_count": 0,
            "json_syntax_repair_types": [],
            "last_json_parse_error": "",
            "last_json_parse_excerpt": "",
            "invalid_json_output_chars": 0,
        }
        try:
            max_concurrency = int(max_concurrency or 3)
        except Exception:
            max_concurrency = 3
        self.max_concurrency = max(1, min(6, max_concurrency))
        self.retry_attempts = 3

    def _emit_output_chars(self, amount):
        try:
            amount = max(0, int(amount or 0))
        except (TypeError, ValueError):
            return
        if amount <= 0:
            return
        with self._output_chars_lock:
            self._output_chars_total += amount
            total = self._output_chars_total
        self.output_chars.emit(total)

    def _start_analysis_diagnostics(self):
        started = time.perf_counter()
        self.diagnostic_started_at = started
        with self._diagnostic_lock:
            self.diagnostics["started_at"] = now_str()
            self.diagnostics["finished_at"] = ""
            self.diagnostics["outcome"] = "pending"
        return started

    @staticmethod
    def _diagnostic_response_headers(response):
        allowed_exact = {
            "content-type",
            "server",
            "retry-after",
            "cf-ray",
            "x-request-id",
            "request-id",
            "trace-id",
            "x-correlation-id",
            "x-upstream-model",
            "x-route",
            "x-upstream",
        }
        headers = {}
        try:
            for key, value in getattr(response, "headers", {}).items():
                key_text = str(key or "")
                lowered = key_text.lower()
                if lowered in allowed_exact or any(
                    marker in lowered
                    for marker in ("request-id", "trace-id", "correlation-id")
                ):
                    headers[key_text] = str(value)
        except Exception:
            return {}
        return headers

    def _begin_analysis_api_diagnostic(self, prompt, user_text, stream, use_response_format):
        prompt = str(prompt or "")
        user_text = str(user_text or "")
        self.last_system_prompt = prompt
        self.last_user_text = user_text
        self.last_partial_output = ""
        user_bytes = user_text.encode("utf-8", errors="replace")
        prompt_bytes = prompt.encode("utf-8", errors="replace")
        attempt = {
            "index": 0,
            "requested_model": str(self.model or ""),
            "response_model": "",
            "stream": bool(stream),
            "response_format_requested": bool(use_response_format),
            "system_prompt_chars": len(prompt),
            "system_prompt_utf8_bytes": len(prompt_bytes),
            "system_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "user_text_chars": len(user_text),
            "user_text_utf8_bytes": len(user_bytes),
            "user_text_sha256": hashlib.sha256(user_bytes).hexdigest(),
            "http_status": 0,
            "time_to_headers_ms": 0,
            "time_to_first_piece_ms": 0,
            "time_to_first_reasoning_ms": 0,
            "time_to_first_content_ms": 0,
            "last_piece_at_ms": 0,
            "max_idle_gap_ms": 0,
            "finish_reason": "",
            "response_headers": {},
            "response_chars": 0,
            "reasoning_chars": 0,
            "content_chars": 0,
            "sse_lines": 0,
            "invalid_sse_lines": 0,
            "received_done": False,
            "started_at": now_str(),
            "outcome": "pending",
            "elapsed_ms": 0,
        }
        with self._diagnostic_lock:
            attempts = self.diagnostics.setdefault("attempts", [])
            attempt["index"] = len(attempts) + 1
            attempts.append(attempt)
            self.diagnostics["api_call_count"] = len(attempts)
            return attempt["index"] - 1

    def _finish_analysis_api_diagnostic(self, index, **updates):
        with self._diagnostic_lock:
            attempts = self.diagnostics.setdefault("attempts", [])
            if not (0 <= int(index) < len(attempts)):
                return
            attempt = attempts[int(index)]
            attempt.update({key: value for key, value in updates.items() if value is not None})
            response_model = str(attempt.get("response_model", "") or "").strip()
            models = self.diagnostics.setdefault("response_models", [])
            if response_model and response_model not in models:
                models.append(response_model)
            self.diagnostics["reasoning_chars"] = sum(
                int(item.get("reasoning_chars", 0) or 0)
                for item in attempts
                if isinstance(item, dict)
            )
            self.diagnostics["content_chars"] = sum(
                int(item.get("content_chars", 0) or 0)
                for item in attempts
                if isinstance(item, dict)
            )
            self.diagnostics["last_http_status"] = int(
                attempt.get("http_status", 0) or 0
            )
            self.diagnostics["last_response_headers"] = deepcopy(
                attempt.get("response_headers", {})
            )
            self.diagnostics["http_status"] = self.diagnostics["last_http_status"]
            self.diagnostics["response_headers"] = deepcopy(
                self.diagnostics["last_response_headers"]
            )
            self.diagnostics["response_chars"] = int(
                attempt.get("response_chars", 0) or 0
            )
            self.diagnostics["time_to_headers_ms"] = float(
                attempt.get("time_to_headers_ms", 0) or 0
            )
            self.diagnostics["time_to_first_piece_ms"] = float(
                attempt.get("time_to_first_piece_ms", 0) or 0
            )
            self.diagnostics["max_idle_gap_ms"] = float(
                attempt.get("max_idle_gap_ms", 0) or 0
            )
            self.diagnostics["finish_reason"] = str(
                attempt.get("finish_reason", "") or ""
            )
            self.diagnostics["done_received"] = bool(
                attempt.get("received_done", False)
            )

    def _increment_analysis_diagnostic(self, key, amount=1):
        with self._diagnostic_lock:
            self.diagnostics[key] = int(self.diagnostics.get(key, 0) or 0) + int(amount or 0)

    def _finalize_analysis_diagnostics(self, outcome, started_at, error=""):
        with self._diagnostic_lock:
            total_started_at = float(
                getattr(self, "diagnostic_started_at", 0.0) or started_at or 0.0
            )
            self.diagnostics["outcome"] = str(outcome or "unknown")
            self.diagnostics["elapsed_ms"] = round(
                max(0.0, time.perf_counter() - total_started_at) * 1000,
                1,
            )
            self.diagnostics["finished_at"] = now_str()
            self.diagnostics["partial_output_chars"] = max(
                len(str(self.last_partial_output or "")),
                len(str(self.last_invalid_json_output or "")),
            )
            if error:
                self.diagnostics["error"] = str(error)[:2000]
                self.diagnostics["error_type"] = type(error).__name__
                formatted = traceback.format_exc(limit=40)
                if formatted.strip() != "NoneType: None":
                    self.diagnostics["traceback"] = formatted[:12000]

    def _normalize_input_chunk_records(self, chunks):
        records = []
        for fallback_index, item in enumerate(chunks or [], 1):
            if isinstance(item, dict):
                text = str(item.get("text", "") or "").strip()
                label = item.get("index", fallback_index)
                total = item.get("total", 0)
                chapter_title = str(item.get("chapter_title", "") or "").strip()
                chapter_id = str(item.get("chapter_id", "") or "").strip()
                review_flow = str(item.get("review_flow", "") or "").strip()
                source_label = str(item.get("source_label", "") or "").strip()
                chunk_key = str(item.get("chunk_key", "") or "").strip()
            else:
                text = str(item or "").strip()
                label = fallback_index
                total = 0
                chapter_title = ""
                chapter_id = ""
                review_flow = ""
                source_label = ""
                chunk_key = ""
            if not text:
                continue
            record = {
                "text": text,
                "index": label if str(label or "").strip() else len(records) + 1,
                "total": total,
                "chapter_title": chapter_title,
                "chapter_id": chapter_id,
            }
            if review_flow:
                record["review_flow"] = review_flow
            if source_label:
                record["source_label"] = source_label
            if chunk_key:
                record["chunk_key"] = chunk_key
            records.append(record)
        batch_total = len(records)
        for record in records:
            try:
                record_total = int(record.get("total", 0) or 0)
            except Exception:
                record_total = 0
            record["total"] = record_total if record_total > 0 else batch_total
        return records

    def _normalize_chapter_ref_value(self, value, chapter_title):
        text = str(value or "").strip()
        chapter_title = str(chapter_title or "").strip()
        if not text or not chapter_title:
            return text
        patterns = (
            r"本片段前文",
            r"本片段后文",
            r"本片段",
            r"当前片段",
            r"本块",
            r"本章",
            r"当前章节",
            r"当前章",
            r"第\s*\d+\s*/\s*\d+\s*个文本片段前文",
            r"第\s*\d+\s*/\s*\d+\s*个文本片段后文",
            r"第\s*\d+\s*/\s*\d+\s*个文本片段",
            r"片段\s*\d+",
            r"第\s*\d+\s*/\s*\d+\s*块前文",
            r"第\s*\d+\s*/\s*\d+\s*块后文",
            r"第\s*\d+\s*/\s*\d+\s*块",
            r"第\s*\d+\s*块前文",
            r"第\s*\d+\s*块后文",
            r"第\s*\d+\s*块",
        )
        pattern = "|".join(f"(?:{part})" for part in patterns)
        return re.sub(pattern, chapter_title, text).strip()

    def _normalize_result_chapter_refs(self, data, record):
        if not isinstance(data, dict) or not isinstance(record, dict):
            return data
        chapter_title = str(record.get("chapter_title", "") or "").strip()
        if not chapter_title:
            return data
        for key in ("foreshadows", "伏笔", "伏笔线索", "线索", "悬念", "clues"):
            items = data.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                for field in ("setup_chapter", "埋设章节", "铺垫章节", "出现章节", "setup"):
                    if field in item:
                        item[field] = self._normalize_chapter_ref_value(item.get(field, ""), chapter_title)
                for field in ("payoff_chapter", "回收章节", "兑现章节", "揭晓章节", "payoff"):
                    if field in item:
                        item[field] = self._normalize_chapter_ref_value(item.get(field, ""), chapter_title)
        return data

    def _analysis_request_capabilities(self):
        with self._capability_lock:
            return self._analysis_response_format_supported, self._analysis_stream_supported

    def _set_analysis_response_format_supported(self, supported):
        with self._capability_lock:
            self._analysis_response_format_supported = bool(supported)

    def _set_analysis_stream_supported(self, supported):
        with self._capability_lock:
            self._analysis_stream_supported = bool(supported)

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_active_network_handles()

    def _proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _new_session(self):
        session = requests.Session()
        session.trust_env = False
        with self._network_lock:
            self._active_sessions.add(session)
        return session

    def _close_active_network_handles(self):
        with self._network_lock:
            responses = list(self._active_responses)
            sessions = list(self._active_sessions)
            self._active_responses.clear()
            self._active_sessions.clear()
        for response in responses:
            try:
                response.close()
            except Exception:
                pass
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass

    def _release_session(self, session):
        if session is None:
            return
        with self._network_lock:
            self._active_sessions.discard(session)

    def _register_response(self, response):
        if response is None:
            return
        with self._network_lock:
            self._active_responses.add(response)

    def _release_response(self, response):
        if response is None:
            return
        with self._network_lock:
            self._active_responses.discard(response)

    def _split_text_chunks(self, text, target_chars=4500, max_chars=6000):
        text = str(text or "").strip()
        if not text:
            return []
        blocks = [x.strip() for x in re.split(r"\n{2,}", text) if x.strip()]
        if not blocks:
            blocks = [text]
        chunks = []
        current = ""

        def flush():
            nonlocal current
            if current.strip():
                chunks.append(current.strip())
            current = ""

        for block in blocks:
            pieces = self._split_long_analysis_block(block, max_chars)
            for piece in pieces:
                candidate = f"{current}\n\n{piece}" if current else piece
                if current and len(candidate) > target_chars:
                    flush()
                    current = piece
                else:
                    current = candidate
                if len(current) >= max_chars:
                    flush()
        flush()
        return chunks

    def _split_retry_chunk_once(self, text, max_parts=3):
        text = str(text or "").strip()
        if not text:
            return []
        try:
            max_parts = int(max_parts or 3)
        except Exception:
            max_parts = 3
        max_parts = max(2, min(3, max_parts))
        if len(text) <= 1800:
            return [text]
        target = max(900, (len(text) + max_parts - 1) // max_parts)
        raw_parts = self._split_text_chunks(
            text,
            target_chars=target,
            max_chars=max(1200, target + 300),
        )
        if len(raw_parts) <= max_parts:
            return raw_parts
        packed = raw_parts[:max_parts - 1]
        tail = "\n\n".join(part for part in raw_parts[max_parts - 1:] if str(part or "").strip()).strip()
        if tail:
            packed.append(tail)
        return packed

    def _split_long_analysis_block(self, text, max_chars):
        text = str(text or "").strip()
        if len(text) <= max_chars:
            return [text] if text else []
        parts = []
        current = ""
        for piece in re.split(r"([。！？；!?;]\s*)", text):
            if not piece:
                continue
            candidate = current + piece
            if current and len(candidate) > max_chars:
                parts.append(current.strip())
                current = piece
            else:
                current = candidate
        if current.strip():
            parts.append(current.strip())
        out = []
        for part in parts:
            while len(part) > max_chars:
                out.append(part[:max_chars].strip())
                part = part[max_chars:].strip()
            if part:
                out.append(part)
        return out

    @staticmethod
    def _extract_json_object_candidate(content):
        """Extract the first top-level object without making content decisions."""
        text = str(content or "").strip().lstrip("\ufeff")
        start = text.find("{")
        if start < 0:
            return text

        depth = 0
        in_string = False
        index = start
        while index < len(text):
            char = text[index]
            if in_string:
                if char == "\\":
                    index += 2
                    continue
                if char == '"':
                    next_index = index + 1
                    while next_index < len(text) and text[next_index].isspace():
                        next_index += 1
                    if next_index >= len(text) or text[next_index] in ",}]:":
                        in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
            index += 1
        return text[start:]

    @staticmethod
    def _repair_json_syntax(content):
        """Repair only deterministic JSON punctuation/escaping errors.

        This deliberately does not add fields, infer values, or repair an
        incomplete string/value.  A None result means the text is ambiguous.
        """
        text = str(content or "").strip()
        if not text:
            return None, []

        output = []
        stack = []
        repair_types = []
        in_string = False
        index = 0
        while index < len(text):
            char = text[index]

            if in_string:
                if char == "\\":
                    if index + 1 >= len(text):
                        return None, []
                    next_char = text[index + 1]
                    if next_char in '"\\/bfnrt':
                        output.extend((char, next_char))
                        index += 2
                        continue
                    if next_char == "u" and index + 5 < len(text):
                        unicode_part = text[index + 2:index + 6]
                        if re.fullmatch(r"[0-9a-fA-F]{4}", unicode_part):
                            output.append(text[index:index + 6])
                            index += 6
                            continue
                    output.append("\\\\")
                    repair_types.append("invalid_escape")
                    index += 1
                    continue
                if char == '"':
                    next_index = index + 1
                    while next_index < len(text) and text[next_index].isspace():
                        next_index += 1
                    if next_index >= len(text) or text[next_index] in ",}]:":
                        output.append(char)
                        in_string = False
                    else:
                        output.append('\\"')
                        repair_types.append("unescaped_quote")
                    index += 1
                    continue
                if char == "\n":
                    output.append("\\n")
                    repair_types.append("control_character")
                elif char == "\r":
                    output.append("\\r")
                    repair_types.append("control_character")
                elif char == "\t":
                    output.append("\\t")
                    repair_types.append("control_character")
                else:
                    output.append(char)
                index += 1
                continue

            if char == '"':
                in_string = True
                output.append(char)
                index += 1
                continue
            if char in "{[":
                stack.append(char)
                output.append(char)
                index += 1
                continue
            if char in "}]":
                expected = "{" if char == "}" else "["
                if not stack or stack[-1] != expected:
                    return None, []
                stack.pop()
                output.append(char)
                index += 1
                continue
            if char == ",":
                next_index = index + 1
                while next_index < len(text) and text[next_index].isspace():
                    next_index += 1
                if next_index < len(text) and text[next_index] in "}]":
                    repair_types.append("trailing_comma")
                    index += 1
                    continue
            output.append(char)
            index += 1

        if in_string:
            return None, []

        repaired = "".join(output).strip()
        if stack:
            last_significant = repaired.rstrip()[-1:] if repaired.rstrip() else ""
            if last_significant in ",:[{" or last_significant == ":":
                return None, []
            for opening in reversed(stack):
                repaired += "}" if opening == "{" else "]"
            repair_types.append("missing_closer")

        if not repair_types or repaired == text:
            return None, []
        return repaired, list(dict.fromkeys(repair_types))

    def _record_json_syntax_repair(self, repair_types):
        repair_types = [str(item or "").strip() for item in (repair_types or []) if str(item or "").strip()]
        if not repair_types:
            return
        self._increment_analysis_diagnostic("json_syntax_repair_count")
        with self._diagnostic_lock:
            existing = self.diagnostics.setdefault("json_syntax_repair_types", [])
            for repair_type in repair_types:
                if repair_type not in existing:
                    existing.append(repair_type)

    def _parse_json_result(self, content):
        raw_content = str(content or "").strip()
        content = raw_content
        if content.startswith("```"):
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:].strip()
            elif content.startswith("```"):
                content = content[3:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()
        content = self._extract_json_object_candidate(content)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as first_error:
            repaired, repair_types = self._repair_json_syntax(content)
            if repaired:
                try:
                    repaired_data = json.loads(repaired)
                except json.JSONDecodeError:
                    repaired_data = None
                if isinstance(repaired_data, dict):
                    self._record_json_syntax_repair(repair_types)
                    return repaired_data
            self.last_invalid_json_output = content
            with self._diagnostic_lock:
                self.diagnostics["last_json_parse_error"] = (
                    f"第 {first_error.lineno} 行，第 {first_error.colno} 列：{first_error.msg}"
                )
                self.diagnostics["last_json_parse_excerpt"] = content[
                    max(0, first_error.pos - 160):first_error.pos + 160
                ].replace("\n", " ")
                self.diagnostics["invalid_json_output_chars"] = len(content)
            preview = content[:240].replace("\n", " ")
            raise ValueError(
                "AI 返回内容不是合法 JSON。请换一个更擅长结构化输出的模型，或减少导入文本后重试。"
                f"\n解析位置：第 {first_error.lineno} 行，第 {first_error.colno} 列。"
                f"\n返回预览：{preview}"
            )
        if not isinstance(data, dict):
            raise ValueError("AI 返回不是 JSON 对象。")
        return data

    def _analysis_prompt(self):
        return (
            "你是长篇小说资料整理助手。请从用户提供的小说/剧本文本片段中提取候选资料。\n"
            "你必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释，不要尾随逗号。\n"
            "所有字符串里的换行、引号都必须正确 JSON 转义。\n"
            "要求：不要把一次性路人或普通名词过度提取；不确定就少提取。\n"
            "人物提取不要只保留主角：本章实际出场并直接推动剧情的人物、冲突/追杀/审问/交易/救援/试探对象、"
            "造成主角资源、去向、身份判断或后续事实变化的人物，即使当前只出现一章，也应进入 characters 候选；"
            "characters.name 必须是具体姓名、可复用称谓或可稳定追踪的单个人物身份；"
            "可以保留“黑衣人”“蒙面女子”“白发老者”“苏家管事”等能在后文继续追踪的单个人物称谓；"
            "复数无名群体排除规则高于主要行动人物保留规则，不要把“王六的两名同伙”“几名手下”“众人”“围观者”等无名群体/复数路人当成人物候选，"
            "即使他们推动了本章剧情，也只把他们造成的剧情影响放入 timeline、summary 或 foreshadows.description；"
            "没有名字、没有独立行动、只围观/传话/完成一次普通动作且不影响后续的人物可以不提取。\n"
            "不要为了压缩结果而丢失会影响后续剧情、人物关系、地点道具、伏笔线索的信息。\n"
            "请按 20 万字左右长篇小说的连续性需求提取：优先保留后续章节必须继承的事实、"
            "人物目标/秘密/关系变化、地点/势力/物品规则、时间顺序和未回收伏笔；"
            "弱化一次性描写、普通动作和不会影响后文的临时信息。\n"
            "如果用户内容含有【已有项目档案】，它只作为合并和去重参考：同名、别称或同一线索不要重复新增，"
            "长期有效的人物变化才写入已有人物 notes，例如身份、目标、秘密、阵营、称呼、关系质变、长期伤势/物品或语言风格变化；"
            "主角或高频人物的 notes 更要克制：如果只是本章行动、临时判断、短暂情绪、重复性性格表现或已经存在于人物卡的特征，不要输出 notes 更新；"
            "只有确实改变长期人物档案的新状态才输出。"
            "普通章节行动、临时情绪、一次性互动和只在本章成立的关系推进，不要写入人物 notes，"
            "也不要转写到本章需继承事实；其中只有会影响全局连续性的长期变化，才放入 project_materials.summary 或 timeline。"
            "章节事实只由正文后的摘要/事实流程负责，AI 分析候选不要追加或改写本章需继承事实。"
            "稳定设定变化才写入 lore.description，例如长期有效的规则、制度、结构关系、地点/势力/物品属性、能力限制、固定渠道或所有权；"
            "本章出现、追问、调查、发送、发现线索、谁去问谁等临时推进，不要写入 lore.description，改放 timeline/summary/foreshadows；"
            "伏笔变化写入状态/章节；对【已有项目档案】中的未埋/已埋伏笔，如果本片段明确推进、回收、揭晓、解释或作废，"
            "必须用已有伏笔名称输出到 foreshadows，并尽量填写旧伏笔编号 target_code/命中编号，同时写明新的 status、setup_chapter/payoff_chapter、evidence 和 review_reason；"
            "如果本片段能证明某条旧伏笔只是短期悬念、低价值道具、一次性催化线，或已经不需要继续牵引后文，status 写“无需回收”，review_action 写“无需回收”；"
            "如果只是普通提及、氛围呼应或没有实质推进，不要输出该伏笔。\n"
            "不要把已有档案里没有在本片段推进的信息当作新发现重复输出。\n"
            "如果这是长文分块的一部分，只提取本片段明确出现或能稳定判断的信息；"
            "没有明确全局增量时，project_materials 对应字段请留空字符串，不要为了填满结构写普通流水账。\n"
            "JSON 结构：{\n"
            '  "characters": [{"name":"","role":"","goal":"","secret":"","voice":"","notes":""}],\n'
            '  "lore": [{"name":"","type":"地点/势力/物品/规则/术语/事件/其他","description":""}],\n'
            '  "foreshadows": [{"name":"","status":"","setup_chapter":"","payoff_chapter":"","description":"","target_code":"","review_action":"","review_reason":"","evidence":""}],\n'
            '  "project_materials": {"bible":"","world_rules":"","timeline":"","summary":""}\n'
            "}\n"
            "foreshadows.status 判定：只提出未来可能用到但尚未在片段中埋下的线索填“未埋”；"
            "片段中已经出现线索、异常、铺垫或悬念填“已埋”；片段中已经兑现、揭示、解释或回收填“已回收”；"
            "明确不是必须回收、不会影响主线/人物/反转/情绪闭环、且不需要继续占用后文注意力的旧伏笔填“无需回收”；"
            "明确作废、冲突、弃用或不再使用的线索填“废弃”。能判断章节/分集标题时填写 setup_chapter/payoff_chapter。\n"
            "已有伏笔复核：同一伏笔从“已埋”推进到“已回收/无需回收/废弃”时，必须保留已有规范名称，不要另起相似名称；"
            "能识别旧伏笔编号时必须填写 target_code；description/review_reason 写清证据章节和判断依据；"
            "payoff_chapter 优先填写本片段实际章节标题；只能判断推进但未回收时，status 仍填“已埋”，说明里写清推进内容。\n"
            "设定和伏笔不要原文重复：同一内容如果只是规则、制度、物品用途或客观设定，只放入 lore；"
            "如果它同时是规则和后续承诺，lore 写规则本身，foreshadows 改写成待验证/待回收的问题或结果，"
            "名称不要与 lore 完全相同，例如“试用条件”进设定，“能否完成试用条件”进伏笔。\n"
            "foreshadows 要求：只提取会跨章节影响后文的明确线索、承诺、谜题或待回收信息；"
            "普通悬念、单章情绪钩子、一次性疑问、普通阶段剧情、爽点节点、临时情绪钩子、单章疑问、普通信息差、氛围描写、已经在本章完成的小悬念不要列为伏笔，"
            "改写入 timeline/summary。"
            "每个片段优先提取最重要的跨章节伏笔；数量不固定，没有明确跨章节价值就返回空数组，"
            "不要为了凑数写普通悬念，也不要因为条数限制丢掉明确会影响后文的伏笔。\n"
            "characters 要求：在满足具体人物或可复用单人称谓的前提下，本章主要行动人物、冲突人物、造成长期结果的人物要保留为候选；"
            "复数无名群体排除规则高于主要行动人物保留规则，不要输出无名群体/复数路人，例如“王六的两名同伙”“几名手下”“围观者”；"
            "删除人物候选时不能丢失剧情作用，需把该群体造成的围堵、袭击、传话、误判、资源变化等后果移入 timeline、summary 或 foreshadows.description；"
            "人物身份字段必须逐项独立判断，不能因为目标或秘密证据不足就把其它字段一并留空：正文中有足够可辨识的直接对白时，voice 必须提炼其稳定的句式、语气、措辞、命令/反问/停顿或表达习惯；"
            "正文明确写出人物正在争夺的资源/机缘/位置、要控制或进入的地点、要保护/排除/追杀/阻止的对象，或明确职责与利益诉求时，goal 必须写成当前正文可证实的行动目标；"
            "secret 只有正文直接揭示、承认或由叙述明确确认时才填写，传闻、旁观者猜测、未证实的能力来源和未知境界不得写成 secret；"
            "voice、goal、secret 分别输出，任何一个字段有证据都必须单独保留，不得用‘证据不足’替代有证据字段。"
            "notes 只写会帮助后续识别和继承的身份、关系、冲突作用、造成的后果或可复用特征，"
            "不要把完整章节流水账塞进 notes。如果是已有主角/高频人物，notes 只写新增且长期有效的档案变化；"
            "如果只是本章发生了什么、短暂情绪、普通互动、重复性性格表现或已有备注的同义复述，就留空字符串。\n"
            "lore.description 要求：只写后续章节需要继承的稳定设定增量；如果只是本章动作、线索推进、调查过程或临时危机，就留空字符串。\n"
            "project_materials 要求：bible 写故事核心、主线矛盾、主要人物关系和风格基调；"
            "world_rules 写世界观、势力、制度、能力/道具规则；"
            "timeline 只记录关键转折、时间顺序变化、伏笔推进/回收、重要关系或长期状态变化；"
            "summary 只写对全局剧情有继承价值的简短状态变化；没有明确内容就留空字符串。"
            "两者都要精炼，但不要因为固定条数限制丢掉会影响后续章节继承的信息。"
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        user_text = (
            f"这是第 {chunk_index}/{total_chunks} 个文本片段。"
            "请只根据本片段提取候选，不要臆测其它片段。"
            "如果片段里提供了“当前章节标题”，setup_chapter/payoff_chapter 必须优先填写该真实章节标题，"
            "不要填写“本片段”“本章”或“第几块”。"
        )
        if self.dossier:
            user_text += "\n\n" + self.dossier
        return user_text + "\n\n【本片段】\n" + str(chunk_text or "")

    def _analysis_progress_label(self):
        return "候选分析"

    def _reasoning_effort_for_request(self):
        return reasoning_effort_for_model(self.model, self.base_url, self._analysis_progress_label())

    def _reasoning_effort_error(self, error):
        match = re.search(r"接口错误\s+(\d+)", str(error or ""))
        status_code = int(match.group(1)) if match else 0
        return reasoning_effort_not_supported(status_code, error)

    def _allow_retry_chunk_split(self):
        return True

    def _post_analysis_chunk(self, prompt, chunk_text, chunk_index, total_chunks, use_response_format=True):
        url = api_url(self.base_url, "/v1/chat/completions")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        user_text = self._chunk_user_text(chunk_text, chunk_index, total_chunks)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
        }
        reasoning_effort = self._reasoning_effort_for_request()
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        diagnostic_started = time.perf_counter()
        diagnostic_index = self._begin_analysis_api_diagnostic(
            prompt, user_text, False, use_response_format
        )
        session = self._new_session()
        response = None
        content = ""
        reasoning = ""
        response_model = ""
        response_headers = {}
        time_to_headers_ms = 0.0
        try:
            try:
                response = session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=(10, 180),
                    proxies=self._proxies(),
                )
                time_to_headers_ms = round((time.perf_counter() - diagnostic_started) * 1000, 1)
                response_headers = self._diagnostic_response_headers(response)
                if response.status_code >= 400:
                    raise Exception(f"接口错误 {response.status_code}：{extract_api_error(response)}")
                data = response.json()
            except Exception as first_error:
                if "reasoning_effort" in payload and self._reasoning_effort_error(first_error):
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass
                    payload.pop("reasoning_effort", None)
                    response = session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=(10, 180),
                        proxies=self._proxies(),
                    )
                    time_to_headers_ms = round((time.perf_counter() - diagnostic_started) * 1000, 1)
                    response_headers = self._diagnostic_response_headers(response)
                    if response.status_code >= 400:
                        raise Exception(f"接口错误 {response.status_code}：{extract_api_error(response)}")
                    data = response.json()
                else:
                    raise
            response_model = str(data.get("model", "") or "")
            message = data.get("choices", [{}])[0].get("message", {}) or {}
            content = str(message.get("content", "") or "")
            reasoning = str(
                message.get("reasoning_content", "")
                or message.get("reasoning", "")
                or ""
            )
            self.last_partial_output = content or reasoning
            self._emit_output_chars(len(content or reasoning))
            parsed = self._parse_json_result(content)
            piece_at_ms = round((time.perf_counter() - diagnostic_started) * 1000, 1)
            self._finish_analysis_api_diagnostic(
                diagnostic_index,
                http_status=int(getattr(response, "status_code", 0) or 0),
                response_model=response_model,
                time_to_headers_ms=time_to_headers_ms,
                time_to_first_piece_ms=piece_at_ms if (content or reasoning) else 0,
                time_to_first_reasoning_ms=piece_at_ms if reasoning else 0,
                time_to_first_content_ms=piece_at_ms if content else 0,
                last_piece_at_ms=piece_at_ms if (content or reasoning) else 0,
                response_headers=response_headers,
                response_chars=len(content or reasoning),
                reasoning_chars=len(reasoning),
                content_chars=len(content),
                outcome="success",
                finished_at=now_str(),
                elapsed_ms=round((time.perf_counter() - diagnostic_started) * 1000, 1),
            )
            return parsed
        except Exception as exc:
            self.last_partial_output = content or reasoning
            self._finish_analysis_api_diagnostic(
                diagnostic_index,
                http_status=int(getattr(response, "status_code", 0) or 0) if response is not None else 0,
                response_model=response_model,
                time_to_headers_ms=time_to_headers_ms,
                response_headers=response_headers,
                response_chars=len(content or reasoning),
                reasoning_chars=len(reasoning),
                content_chars=len(content),
                outcome="error",
                error_type=type(exc).__name__,
                error=str(exc)[:1000],
                finished_at=now_str(),
                elapsed_ms=round((time.perf_counter() - diagnostic_started) * 1000, 1),
            )
            raise
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            self._release_session(session)
            try:
                session.close()
            except Exception:
                pass

    def _post_analysis_chunk_stream(self, prompt, chunk_text, chunk_index, total_chunks, use_response_format=True):
        url = api_url(self.base_url, "/v1/chat/completions")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        user_text = self._chunk_user_text(chunk_text, chunk_index, total_chunks)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
            "stream": True,
        }
        reasoning_effort = self._reasoning_effort_for_request()
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        diagnostic_started = time.perf_counter()
        diagnostic_index = self._begin_analysis_api_diagnostic(
            prompt, user_text, True, use_response_format
        )
        session = self._new_session()
        r = None
        full = ""
        response_model = ""
        finish_reason = ""
        response_headers = {}
        time_to_headers_ms = 0.0
        time_to_first_piece_ms = 0.0
        time_to_first_reasoning_ms = 0.0
        time_to_first_content_ms = 0.0
        last_piece_at_ms = 0.0
        max_idle_gap_ms = 0.0
        reasoning_chars = 0
        content_chars = 0
        sse_lines = 0
        invalid_sse_lines = 0
        received_done = False
        try:
            r = session.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=(10, 180),
                proxies=self._proxies(),
            )
            time_to_headers_ms = round((time.perf_counter() - diagnostic_started) * 1000, 1)
            self._response = r
            self._register_response(r)
            if r.status_code >= 400 and "reasoning_effort" in payload:
                first_error = extract_api_error(r)
                if reasoning_effort_not_supported(r.status_code, first_error):
                    self._release_response(r)
                    try:
                        r.close()
                    except Exception:
                        pass
                    payload.pop("reasoning_effort", None)
                    r = session.post(
                        url,
                        headers=headers,
                        json=payload,
                        stream=True,
                        timeout=(10, 180),
                        proxies=self._proxies(),
                    )
                    self._response = r
                    self._register_response(r)
            response_headers = self._diagnostic_response_headers(r)
            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")

            first_piece = False
            r.encoding = "utf-8"
            for raw_line in r.iter_lines(decode_unicode=False):
                sse_lines += 1
                if self._stop_requested or self.isInterruptionRequested():
                    self._finish_analysis_api_diagnostic(
                        diagnostic_index,
                        http_status=int(getattr(r, "status_code", 0) or 0),
                        response_model=response_model,
                        time_to_headers_ms=time_to_headers_ms,
                        time_to_first_piece_ms=time_to_first_piece_ms,
                        time_to_first_reasoning_ms=time_to_first_reasoning_ms,
                        time_to_first_content_ms=time_to_first_content_ms,
                        last_piece_at_ms=last_piece_at_ms,
                        max_idle_gap_ms=max_idle_gap_ms,
                        finish_reason=finish_reason,
                        response_chars=len(full),
                        reasoning_chars=reasoning_chars,
                        content_chars=content_chars,
                        sse_lines=sse_lines,
                        invalid_sse_lines=invalid_sse_lines,
                        received_done=received_done,
                        outcome="stopped",
                        response_headers=response_headers,
                        finished_at=now_str(),
                        elapsed_ms=round((time.perf_counter() - diagnostic_started) * 1000, 1),
                    )
                    return {}
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("utf-8", errors="replace")
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    received_done = True
                    break
                try:
                    data = json.loads(data_str)
                except Exception:
                    invalid_sse_lines += 1
                    continue
                if data.get("model"):
                    response_model = str(data.get("model") or "")
                if isinstance(data.get("error"), dict):
                    raise Exception(data["error"].get("message") or json.dumps(data["error"], ensure_ascii=False))
                if isinstance(data.get("error"), str) and data.get("error"):
                    raise Exception(data.get("error"))
                choices = data.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] or {}
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason") or "")
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                content_piece = (
                    delta.get("content")
                    or delta.get("text")
                    or message.get("content")
                    or choice.get("text")
                    or ""
                )
                reasoning_piece = (
                    delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or message.get("reasoning_content")
                    or message.get("reasoning")
                    or ""
                )
                content_piece = str(content_piece or "")
                reasoning_piece = str(reasoning_piece or "")
                content_chars += len(content_piece)
                reasoning_chars += len(reasoning_piece)
                piece = content_piece or reasoning_piece
                if piece:
                    piece_at_ms = round((time.perf_counter() - diagnostic_started) * 1000, 1)
                    if last_piece_at_ms:
                        max_idle_gap_ms = max(max_idle_gap_ms, piece_at_ms - last_piece_at_ms)
                    elif time_to_headers_ms:
                        max_idle_gap_ms = max(max_idle_gap_ms, piece_at_ms - time_to_headers_ms)
                    last_piece_at_ms = piece_at_ms
                    if reasoning_piece and not time_to_first_reasoning_ms:
                        time_to_first_reasoning_ms = piece_at_ms
                    if content_piece and not time_to_first_content_ms:
                        time_to_first_content_ms = piece_at_ms
                    if not first_piece:
                        first_piece = True
                        time_to_first_piece_ms = piece_at_ms
                        self.progress.emit(f"正在接收{self._analysis_progress_label()} {chunk_index}/{total_chunks} 的流式结果...")
                    full += piece
                    self.last_partial_output = full
                    self._emit_output_chars(len(piece))
            if not full.strip():
                raise Exception("AI 没有返回有效候选内容。")
            parsed = self._parse_json_result(full)
            self._finish_analysis_api_diagnostic(
                diagnostic_index,
                http_status=int(getattr(r, "status_code", 0) or 0),
                response_model=response_model,
                time_to_headers_ms=time_to_headers_ms,
                time_to_first_piece_ms=time_to_first_piece_ms,
                time_to_first_reasoning_ms=time_to_first_reasoning_ms,
                time_to_first_content_ms=time_to_first_content_ms,
                last_piece_at_ms=last_piece_at_ms,
                max_idle_gap_ms=max_idle_gap_ms,
                finish_reason=finish_reason,
                response_headers=response_headers,
                response_chars=len(full),
                reasoning_chars=reasoning_chars,
                content_chars=content_chars,
                sse_lines=sse_lines,
                invalid_sse_lines=invalid_sse_lines,
                received_done=received_done,
                outcome="success",
                finished_at=now_str(),
                elapsed_ms=round((time.perf_counter() - diagnostic_started) * 1000, 1),
            )
            return parsed
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - diagnostic_started) * 1000, 1)
            if last_piece_at_ms:
                max_idle_gap_ms = max(max_idle_gap_ms, elapsed_ms - last_piece_at_ms)
            self._finish_analysis_api_diagnostic(
                diagnostic_index,
                http_status=int(getattr(r, "status_code", 0) or 0) if r is not None else 0,
                response_model=response_model,
                time_to_headers_ms=time_to_headers_ms,
                time_to_first_piece_ms=time_to_first_piece_ms,
                time_to_first_reasoning_ms=time_to_first_reasoning_ms,
                time_to_first_content_ms=time_to_first_content_ms,
                last_piece_at_ms=last_piece_at_ms,
                max_idle_gap_ms=max_idle_gap_ms,
                finish_reason=finish_reason,
                response_headers=response_headers,
                response_chars=len(full),
                reasoning_chars=reasoning_chars,
                content_chars=content_chars,
                sse_lines=sse_lines,
                invalid_sse_lines=invalid_sse_lines,
                received_done=received_done,
                outcome="error",
                error_type=type(exc).__name__,
                error=str(exc)[:1000],
                finished_at=now_str(),
                elapsed_ms=elapsed_ms,
            )
            raise
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass
                self._release_response(r)
                if self._response is r:
                    self._response = None
            self._release_session(session)
            try:
                session.close()
            except Exception:
                pass

    def _is_retryable_analysis_error(self, error):
        if self._is_analysis_rate_limit_error(error):
            return True
        if getattr(self, "_analysis_stream_only", False) and self._is_stream_json_error(error):
            return True
        msg = str(error or "").lower()
        retry_markers = (
            "upstream request failed",
            "upstream service temporarily unavailable",
            "upstream unavailable",
            "upstream timeout",
            "524",
            "timeout",
            "timed out",
            "read timed out",
            "连接超时",
            "a timeout occurred",
            "temporarily unavailable",
            "bad gateway",
            "502",
            "503",
            "504",
            "response ended prematurely",
            "incomplete read",
            "chunkedencodingerror",
            "connection broken",
            "remote end closed connection",
            "protocolerror",
        )
        return any(marker in msg for marker in retry_markers)

    def _is_analysis_rate_limit_error(self, error):
        msg = str(error or "").lower()
        retry_markers = (
            "concurrency limit",
            "rate limit",
            "too many requests",
            "please retry later",
            "429",
            "并发",
            "限流",
            "请求过多",
            "稍后重试",
        )
        return any(marker in msg for marker in retry_markers)

    def _analysis_retry_wait_seconds(self, error, attempt):
        if self._is_analysis_rate_limit_error(error):
            return 10
        return min(8, 2 * attempt)

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        if self._is_analysis_rate_limit_error(error):
            return f"第 {label}/{total} 块遇到接口并发限制，{wait_seconds} 秒后自动重试 {next_attempt}/{attempts}..."
        return f"第 {label}/{total} 块暂时失败，{wait_seconds} 秒后自动重试 {next_attempt}/{attempts}..."

    def _is_stream_unsupported_error(self, error):
        msg = str(error or "").lower()
        return "stream" in msg and (
            "support" in msg
            or "unsupported" in msg
            or "not support" in msg
            or "不支持" in msg
        )

    def _is_stream_transport_error(self, error):
        msg = str(error or "").lower()
        transport_markers = (
            "response ended prematurely",
            "incomplete read",
            "chunkedencodingerror",
            "connection broken",
            "remote end closed connection",
            "protocolerror",
        )
        return any(marker in msg for marker in transport_markers)

    def _is_stream_json_error(self, error):
        msg = str(error or "").lower()
        return (
            "ai 返回内容不是合法 json" in msg
            or "ai 返回不是 json 对象" in msg
            or "jsondecodeerror" in msg
            or "expecting ',' delimiter" in msg
            or "unterminated string" in msg
        )

    def _analyze_chunk_resilient(self, prompt, chunk, label, total, use_response_format, split_depth=0):
        response_format_supported, stream_supported = self._analysis_request_capabilities()
        use_response_format = bool(use_response_format and response_format_supported)
        if getattr(self, "_analysis_stream_only", False) and not stream_supported:
            raise RuntimeError("当前章节规划接口不支持流式输出，已停止普通模式重试，请更换支持流式的模型或厂商。")
        try:
            if stream_supported:
                return self._post_analysis_chunk_stream(prompt, chunk, label, total, use_response_format), use_response_format
            return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
        except Exception as e:
            msg = str(e).lower()
            if use_response_format and ("response_format" in msg or "json_object" in msg):
                self._set_analysis_response_format_supported(False)
                self.progress.emit("当前接口不支持强制 JSON，已降级继续分块分析...")
                try:
                    if stream_supported:
                        return self._post_analysis_chunk_stream(prompt, chunk, label, total, False), False
                    return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                except Exception as e2:
                    if self._is_stream_unsupported_error(e2):
                        if getattr(self, "_analysis_stream_only", False):
                            raise RuntimeError(
                                "当前章节规划接口不支持流式输出，已停止普通模式重试，请更换支持流式的模型或厂商。"
                            ) from e2
                        self._set_analysis_stream_supported(False)
                        self.progress.emit("当前接口不支持流式候选分析，已自动退回普通分块请求...")
                        return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                    if stream_supported and self._is_stream_transport_error(e2):
                        if getattr(self, "_retry_stream_transport_before_nonstream", False):
                            raise
                        self._set_analysis_stream_supported(False)
                        self.progress.emit("流式候选分析连接提前结束，已切换为普通请求重试...")
                        return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                    raise
            if self._is_stream_unsupported_error(e):
                if getattr(self, "_analysis_stream_only", False):
                    raise RuntimeError(
                        "当前章节规划接口不支持流式输出，已停止普通模式重试，请更换支持流式的模型或厂商。"
                    ) from e
                self._set_analysis_stream_supported(False)
                self.progress.emit("当前接口不支持流式候选分析，已自动退回普通分块请求...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            if stream_supported and self._is_stream_transport_error(e):
                if getattr(self, "_retry_stream_transport_before_nonstream", False):
                    raise
                self._set_analysis_stream_supported(False)
                self.progress.emit("流式候选分析连接提前结束，已切换为普通请求重试...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            if stream_supported and self._is_stream_json_error(e):
                if getattr(self, "_analysis_stream_only", False):
                    raise
                self._set_analysis_stream_supported(False)
                self.progress.emit("流式候选分析返回不完整 JSON，已切换为普通请求重试...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            if (
                self._allow_retry_chunk_split()
                and split_depth <= 0
                and self._is_retryable_analysis_error(e)
                and not self._is_analysis_rate_limit_error(e)
                and len(chunk) > 1800
            ):
                parts = self._split_retry_chunk_once(chunk, max_parts=3)
                if len(parts) > 1:
                    merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
                    self.progress.emit(f"第 {label}/{total} 块响应过慢，已自动拆成 {len(parts)} 小块重试；子块失败后将保留为待重试。")
                    current_response_format = use_response_format
                    for sub_index, part in enumerate(parts, 1):
                        if self._stop_requested or self.isInterruptionRequested():
                            return merged, current_response_format
                        self.progress.emit(f"正在分析候选 {label}/{total} 的小块 {sub_index}/{len(parts)}...")
                        try:
                            parsed, current_response_format = self._analyze_chunk_resilient(
                                prompt,
                                part,
                                f"{label}.{sub_index}",
                                total,
                                current_response_format,
                                split_depth + 1,
                            )
                        except Exception as sub_error:
                            setattr(sub_error, "_analysis_split_failed", True)
                            raise
                        self._merge_analysis_result(merged, parsed)
                    return merged, current_response_format
            raise

    def _analyze_chunk_with_retries(self, prompt, chunk, label, total, use_response_format):
        attempts = max(1, int(self.retry_attempts or 1))
        current_response_format = use_response_format
        last_error = None
        for attempt in range(1, attempts + 1):
            if self._stop_requested or self.isInterruptionRequested():
                return {}, current_response_format
            try:
                return self._analyze_chunk_resilient(
                    prompt,
                    chunk,
                    label,
                    total,
                    current_response_format,
                    0,
                )
            except Exception as e:
                last_error = e
                if getattr(e, "_analysis_split_failed", False) or attempt >= attempts or not self._is_retryable_analysis_error(e):
                    raise
                self._increment_analysis_diagnostic("retry_count")
                wait_seconds = self._analysis_retry_wait_seconds(e, attempt)
                self.progress.emit(
                    self._analysis_retry_progress_text(e, label, total, wait_seconds, attempt + 1, attempts)
                )
                deadline = time.time() + wait_seconds
                while time.time() < deadline:
                    if self._stop_requested or self.isInterruptionRequested():
                        return {}, current_response_format
                    time.sleep(0.2)
        raise last_error or Exception("候选分析失败。")

    def _merge_candidate_group(self, output, key, item, fields, append_fields=()):
        if not isinstance(item, dict):
            return
        name = str(item.get("name", "") or "").strip()
        if not name:
            return
        target = output.setdefault(key, [])

        def merge_source_label(target_item, source_label):
            source_label = str(source_label or "").strip()
            if not source_label:
                return
            old = str(target_item.get("_source_label", "") or "").strip()
            labels = [line.strip() for line in old.splitlines() if line.strip()]
            if source_label not in labels:
                labels.append(source_label)
            target_item["_source_label"] = "\n".join(labels)

        existing = None
        for old in target:
            if isinstance(old, dict) and str(old.get("name", "") or "").strip() == name:
                existing = old
                break
        if existing is None:
            data = {field: str(item.get(field, "") or "") for field in ("name",) + tuple(fields)}
            merge_source_label(data, item.get("_source_label", ""))
            if key == "foreshadows" and _foreshadow_candidate_is_terminal_review(item):
                data["description"] = _foreshadow_terminal_review_description(data.get("description", ""))
            if key == "foreshadows" and item.get("_status_explicit"):
                data["status"] = _infer_foreshadow_status({"status": data.get("status", "")}, preserve_manual=False)
                data["_status_explicit"] = True
            target.append(data)
            return

        merge_source_label(existing, item.get("_source_label", ""))
        if key == "foreshadows" and _foreshadow_candidate_is_terminal_review(existing):
            if _foreshadow_terminal_review_should_replace(existing, item):
                data = {field: str(item.get(field, "") or "") for field in ("name",) + tuple(fields)}
                merge_source_label(data, item.get("_source_label", ""))
                data["description"] = _foreshadow_terminal_review_description(data.get("description", ""))
                if item.get("_status_explicit"):
                    data["status"] = _infer_foreshadow_status({"status": data.get("status", "")}, preserve_manual=False)
                    data["_status_explicit"] = True
                existing.clear()
                existing.update(data)
            return
        incoming_terminal = key == "foreshadows" and _foreshadow_candidate_is_terminal_review(item)

        for field in fields:
            if key == "foreshadows" and field == "status":
                if item.get("_status_explicit"):
                    existing["status"] = _merge_foreshadow_status(existing.get("status", ""), item.get("status", ""))
                    existing["_status_explicit"] = True
                continue
            if key == "foreshadows" and field == "_status_explicit":
                if item.get("_status_explicit"):
                    existing["_status_explicit"] = True
                continue
            old = str(existing.get(field, "") or "").strip()
            new = str(item.get(field, "") or "").strip()
            if not new:
                continue
            if incoming_terminal and field == "description":
                cleaned = _foreshadow_terminal_review_description(new)
                if cleaned and cleaned != old:
                    existing[field] = cleaned
                continue
            if not old:
                existing[field] = new
            elif new == old or new in old:
                continue
            elif old in new:
                existing[field] = new
            elif key == "foreshadows" and field == "description" and field in append_fields:
                merged, _did_change = _merge_foreshadow_description_without_bloat(old, new, item)
                existing[field] = merged
            elif field in append_fields:
                existing[field] = f"{old}\n补充：{new}"

    def _merge_analysis_result(self, output, data, source_label=""):
        data = _normalize_ai_candidates(data)
        source_label = str(source_label or "").strip()
        if source_label:
            for group_key in ("characters", "lore", "foreshadows"):
                for item in data.get(group_key, []) if isinstance(data.get(group_key, []), list) else []:
                    if isinstance(item, dict) and not str(item.get("_source_label", "") or "").strip():
                        item["_source_label"] = source_label
        output.setdefault("project_materials", {})
        for item in data.get("characters", []) if isinstance(data.get("characters", []), list) else []:
            self._merge_candidate_group(
                output,
                "characters",
                item,
                ("role", "goal", "secret", "voice", "notes"),
                append_fields=("notes",),
            )
        for item in data.get("lore", []) if isinstance(data.get("lore", []), list) else []:
            self._merge_candidate_group(
                output,
                "lore",
                item,
                ("type", "description"),
                append_fields=("description",),
            )
        materials = data.get("project_materials", {})
        if isinstance(materials, dict):
            target = output.setdefault("project_materials", {})
            for key in ("bible", "world_rules", "timeline", "summary"):
                old = str(target.get(key, "") or "").strip()
                new = str(materials.get(key, "") or "").strip()
                if not new:
                    continue
                if not old:
                    target[key] = new
                elif new == old or new in old:
                    continue
                elif old in new:
                    target[key] = new
                else:
                    target[key] = f"{old}\n\n补充：{new}"
        for item in data.get("foreshadows", []) if isinstance(data.get("foreshadows", []), list) else []:
            self._merge_candidate_group(
                output,
                "foreshadows",
                item,
                ("status", "setup_chapter", "payoff_chapter", "description", "_target_code", "_merge_target"),
                append_fields=("description",),
            )

    def _source_label_for_record(self, record, index, total):
        record = record if isinstance(record, dict) else {}
        label = record.get("index", index)
        label_total = record.get("total", total) or total
        return f"第 {label}/{label_total} 块"

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            chunk_records = deepcopy(self.input_chunk_records)
            text = self.text.strip()
            if not chunk_records:
                if not text:
                    raise Exception("没有可分析的正文。")
                chunks = self._split_text_chunks(text)
                chunk_records = [
                    {"text": chunk, "index": index, "total": len(chunks)}
                    for index, chunk in enumerate(chunks, 1)
                ]
            chunks = [record.get("text", "") for record in chunk_records]
            if not chunks:
                raise Exception("没有可分析的正文。")
            total = len(chunks)
            prompt = self._analysis_prompt()
            merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
            succeeded = 0
            processed = 0
            failed_chunks = []
            self.progress.emit(f"正在分块分析候选：共 {total} 块，并发 {self.max_concurrency}...")

            def submit_chunk(executor, index):
                record = chunk_records[index - 1]
                chunk = record.get("text", "")
                label = record.get("index", index)
                label_total = record.get("total", total) or total
                response_format_supported, _stream_supported = self._analysis_request_capabilities()
                return executor.submit(
                    self._analyze_chunk_with_retries,
                    prompt,
                    chunk,
                    label,
                    label_total,
                    response_format_supported,
                )

            with ThreadPoolExecutor(max_workers=max(1, int(self.max_concurrency or 1))) as executor:
                futures = {}
                next_index = 1
                while next_index <= total and len(futures) < self.max_concurrency:
                    futures[submit_chunk(executor, next_index)] = next_index
                    next_index += 1

                while futures:
                    if self._stop_requested or self.isInterruptionRequested():
                        for future in futures:
                            future.cancel()
                        return
                    done, _ = wait(list(futures.keys()), timeout=0.2, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        index = futures.pop(future, None)
                        if index is None:
                            continue
                        try:
                            parsed, _response_format = future.result()
                            record = chunk_records[index - 1]
                            parsed = self._normalize_result_chapter_refs(parsed, record)
                        except Exception as e:
                            record = chunk_records[index - 1]
                            failed_chunks.append({
                                "index": record.get("index", index),
                                "total": record.get("total", total) or total,
                                "text": record.get("text", chunks[index - 1]),
                                "chapter_id": record.get("chapter_id", ""),
                                "chapter_title": record.get("chapter_title", ""),
                                "review_flow": record.get("review_flow", ""),
                                "source_label": record.get("source_label", ""),
                                "chunk_key": record.get("chunk_key", ""),
                                "error": str(e),
                            })
                            processed += 1
                            partial = deepcopy(merged)
                            partial["_failed_chunks"] = deepcopy(failed_chunks)
                            partial["_chunk_total"] = total
                            partial["_chunk_succeeded"] = succeeded
                            self.partial_ready.emit(partial, processed, total)
                            error_preview = str(e).replace("\n", " ").strip()
                            if len(error_preview) > 160:
                                error_preview = error_preview[:160] + "..."
                            self.progress.emit(f"第 {index}/{total} 块分析失败：{error_preview}；已保留为待重试。")
                        else:
                            source_label = self._source_label_for_record(record, index, total)
                            self._merge_analysis_result(merged, parsed, source_label=source_label)
                            succeeded += 1
                            processed += 1
                            partial = deepcopy(merged)
                            partial["_failed_chunks"] = deepcopy(failed_chunks)
                            partial["_chunk_total"] = total
                            partial["_chunk_succeeded"] = succeeded
                            self.partial_ready.emit(partial, processed, total)
                            material_hits = sum(
                                1
                                for value in merged.get("project_materials", {}).values()
                                if str(value or "").strip()
                            )
                            self.progress.emit(
                                f"已处理 {processed}/{total}，成功 {succeeded} 块：人物 {len(merged['characters'])}，设定 {len(merged['lore'])}，伏笔 {len(merged['foreshadows'])}，资料草案 {material_hits}"
                            )
                        if next_index <= total:
                            futures[submit_chunk(executor, next_index)] = next_index
                            next_index += 1
            merged["_failed_chunks"] = failed_chunks
            merged["_chunk_total"] = total
            merged["_chunk_succeeded"] = succeeded
            self.result_ready.emit(merged)
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self.failed.emit(str(e))
        finally:
            self._close_active_network_handles()


class NovelCandidatePostprocessWorker(NovelAnalysisWorker):
    def __init__(
        self,
        base_url,
        api_key,
        model,
        candidates,
        dossier,
        proxy_url="",
        proxy_mode="不使用代理",
    ):
        self.candidates = _normalize_ai_candidates(candidates)
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
            dossier=dossier,
        )

    def _postprocess_prompt(self):
        return (
            "你是长篇小说资料整理助手。请对已经分块提取出的候选资料做最终合并、去重和对已有项目档案查重。\n"
            "你必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释，不要尾随逗号。\n"
            "所有字符串里的换行、引号都必须正确 JSON 转义。\n"
            "任务：\n"
            "1. 合并块与块之间的重复候选。同一人物、设定、伏笔只保留一条，说明要整合成完整但精炼的表达。\n"
            "2. 对照【已有项目档案】查重。已有档案里已经稳定存在的信息，不要作为新增候选重复输出；"
            "但已有伏笔的状态/章节发生变化时必须保留为候选，用于更新旧档案。\n"
            "3. 只保留确实需要入库或补充到已有档案的长期信息；但不要把本章主要行动人物、冲突人物、造成长期结果的人物当作普通流水账删掉。"
            "普通章节行动、临时情绪、一次性互动、调查过程和流水账不要进入人物备注或设定说明。\n"
            "对于已有主角/高频人物，characters.notes 只允许保留新增且长期有效的人物档案变化；"
            "如果候选只是本章行动、临时判断、短暂情绪、重复性性格表现，或已有备注/身份/目标/秘密/语言风格的同义复述，必须清空 notes 或删除该人物候选。\n"
            "3a. characters 中应保留本章直接推动剧情的人、和主角发生冲突/追杀/审问/交易/救援/试探的人、"
            "影响主角资源/去向/身份判断/后续事实的人；但 name 必须是具体人物或可复用单人称谓。"
            "可以保留“黑衣人”“蒙面女子”“白发老者”“苏家管事”等能在后文继续追踪的单个人物称谓；"
            "复数无名群体排除规则高于主要行动人物保留规则。"
            "删除“王六的两名同伙”“几名手下”“众人”“围观者”等无名群体/复数路人，"
            "也删除只围观、传话、无姓名、无独立行动、无后续影响的路人。\n"
            "3b. 最终输出前逐条检查 characters.name：如果是复数无名群体，必须从 characters 删除；"
            "删除人物候选时不能丢失剧情作用，需把该群体造成的围堵、袭击、传话、误判、资源变化等后果保留到 timeline、summary 或 foreshadows.description。\n"
            "3c. 人物字段必须逐项复核后再合并：有稳定直接对白的候选必须保留 voice；有明确争夺对象、行动方向、职责或利益诉求的候选必须保留 goal；只有正文明确揭示的隐情才保留 secret。"
            "不能因为 secret 不明确而清空同一人物已有的 goal 或 voice，也不能把传闻、推测、未知能力来源合并成 secret；字段有正文证据就不得删除。\n"
            "4. 如果候选与已有项目档案是同一对象，请使用已有档案中的规范名称；不确定是否同一对象时分开保留，不要强行合并。\n"
            "5. 伏笔要保守：同一线索才合并；只是相似主题但回收目标不同的伏笔要分开。\n"
            "6. 对照已有伏笔逐条复核：如果分块候选或本次片段已经明确兑现、揭示、解释、回收某个已有未埋/已埋伏笔，"
            "必须保留该伏笔并把 status 写成“已回收”，payoff_chapter 写真实章节标题；"
            "如果确认它只是短期悬念、低价值道具、一次性催化线，或已不需要继续牵引后文，status 写“无需回收”；明确作废写“废弃”。"
            "命中旧伏笔时尽量填写 target_code/命中编号，并在 description、evidence、review_reason 写清证据章节和判断依据。"
            "如果只是推进但未回收，status 保持“已埋”，说明写清推进；没有实质变化则不要输出。\n"
            "6a. 重要：仅当候选明确填写了已有伏笔编号 target_code/命中编号，且 status 为“已回收”“无需回收”“废弃”时，"
            "它是旧伏笔状态更新，不是新增重复资料；不同 target_code/命中编号 的终态更新必须分别保留，"
            "只能合并同一个编号的多条候选，不能因为同属同一案件、同一章节、同一证据链或同一大事件而合并删除。"
            "没有 target_code/命中编号 的新增伏笔仍按普通候选规则去重、合并或删除。\n"
            "7. 状态不能倒退：已回收/无需回收/废弃不要改回已埋或未埋；已埋不要改回未埋。\n"
            "8. 小说圣经和世界观/规则只作为查重和冲突参考，不要因为已有档案存在就自动重写；确有新增草案时才放入 project_materials。\n"
            "9. 时间线和摘要只承接全局剧情进展，避免和人物备注、设定说明重复表达同一件事。\n"
            "10. 不要把人物备注里的临时内容转写进“本章需继承事实”；章节事实只由正文后的摘要/事实流程负责。\n"
            "JSON 结构：{\n"
            '  "characters": [{"name":"","role":"","goal":"","secret":"","voice":"","notes":""}],\n'
            '  "lore": [{"name":"","type":"地点/势力/物品/规则/术语/事件/其他","description":""}],\n'
            '  "foreshadows": [{"name":"","status":"","setup_chapter":"","payoff_chapter":"","description":"","target_code":"","review_action":"","review_reason":"","evidence":""}],\n'
            '  "project_materials": {"bible":"","world_rules":"","timeline":"","summary":""}\n'
            "}\n"
            "输出要求：空字段用空字符串，空列表用 []；不要输出已重复、已被已有档案覆盖、或只适合本章临时记录的内容。"
        )

    def _postprocess_user_text(self):
        payload = {
            "已有项目档案": self.dossier,
            "分块候选": self.candidates,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return str(chunk_text or "")

    def _analyze_chunk_resilient(self, prompt, chunk, label, total, use_response_format, split_depth=0):
        response_format_supported, stream_supported = self._analysis_request_capabilities()
        use_response_format = bool(use_response_format and response_format_supported)
        try:
            if stream_supported:
                return self._post_analysis_chunk_stream(prompt, chunk, label, total, use_response_format), use_response_format
            return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
        except Exception as e:
            msg = str(e).lower()
            if use_response_format and ("response_format" in msg or "json_object" in msg):
                self._set_analysis_response_format_supported(False)
                self.progress.emit("当前接口不支持强制 JSON，已降级继续候选合并...")
                try:
                    if stream_supported:
                        return self._post_analysis_chunk_stream(prompt, chunk, label, total, False), False
                    return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                except Exception as e2:
                    if self._is_stream_unsupported_error(e2):
                        self._set_analysis_stream_supported(False)
                        self.progress.emit("当前接口不支持流式候选合并，已自动退回普通请求...")
                        return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                    if stream_supported and self._is_stream_transport_error(e2):
                        self._set_analysis_stream_supported(False)
                        self.progress.emit("流式候选合并连接提前结束，已切换为普通请求重试...")
                        return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                    raise
            if self._is_stream_unsupported_error(e):
                self._set_analysis_stream_supported(False)
                self.progress.emit("当前接口不支持流式候选合并，已自动退回普通请求...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            if stream_supported and self._is_stream_transport_error(e):
                self._set_analysis_stream_supported(False)
                self.progress.emit("流式候选合并连接提前结束，已切换为普通请求重试...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            if stream_supported and self._is_stream_json_error(e):
                self._set_analysis_stream_supported(False)
                self.progress.emit("流式候选合并返回不完整 JSON，已切换为普通请求重试...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            raise

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not any(self.candidates.get(key) for key in ("characters", "lore", "foreshadows")):
                materials = self.candidates.get("project_materials", {})
                if not isinstance(materials, dict) or not any(str(value or "").strip() for value in materials.values()):
                    raise Exception("没有可合并的候选内容。")
            self.progress.emit("正在进行 AI 候选合并和已有档案查重...")
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._postprocess_prompt(),
                self._postprocess_user_text(),
                1,
                1,
                True,
            )
            if self._stop_requested or self.isInterruptionRequested():
                return
            normalized = _normalize_ai_candidates(parsed)
            if not any(normalized.get(key) for key in ("characters", "lore", "foreshadows")):
                materials = normalized.get("project_materials", {})
                if not isinstance(materials, dict) or not any(str(value or "").strip() for value in materials.values()):
                    normalized["_postprocess_empty"] = True
            self.result_ready.emit(normalized)
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self.failed.emit(str(e))
        finally:
            self._close_active_network_handles()


class NovelFrameworkImportWorker(NovelAnalysisWorker):
    result_ready = Signal(dict)

    _BIBLE_SECTION_FIELDS = (
        ("core_setting", "核心设定", ("核心设定",)),
        ("reader_promise", "核心爽点 / 读者承诺", ("核心爽点", "读者承诺", "核心读者承诺")),
        ("theme", "长期主题", ("长期主题", "主题")),
        ("main_conflict", "主线矛盾", ("主线矛盾", "核心矛盾")),
        ("relationship_foundation", "长期关系底盘", ("长期关系底盘", "感情线方向", "关系底盘")),
        ("ending_direction", "结局方向", ("结局方向", "最终结局方向")),
        ("hard_boundaries", "禁用设定 / 硬边界", ("禁用设定", "硬边界", "禁用规则")),
    )

    def __init__(
        self,
        base_url,
        api_key,
        model,
        framework_text,
        project_context="",
        proxy_url="",
        proxy_mode="不使用代理",
    ):
        self.framework_text = str(framework_text or "")
        self.project_context = str(project_context or "")
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self._retry_stream_transport_before_nonstream = True

    def _analysis_prompt(self):
        return (
            "你是长篇小说框架整理编辑。请把用户导入的小说框架/大纲按正式项目分类整理。\n"
            "必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释，不要尾随逗号。\n"
            "只根据【导入框架原文】明确写出的内容分类，不要扩写正文，不要生成新的剧情，不要补全原文没有的设定。\n"
            "不要把整段框架原文原样塞进 bible/world_rules/summary/timeline；这些字段只写精炼、长期有效、方便人工查阅和后续写作的内容。\n"
            "小说圣经只整理原文已经明确写出的长期内容，按核心设定、读者承诺、长期主题、主线矛盾、"
            "长期关系底盘和结局方向等已有信息自然归类；原文没有明确依据的内容留空。"
            "结局方向只写最终应兑现的情感基调、价值取向、关系落点或关键代价，不写终局的逐步事件经过。"
            "全书走向、阶段规划、分卷安排、逐段未来剧情和详细结局事件不得写入小说圣经，也不得写入 timeline 或 summary；"
            "这些内容只写入 chapter_plan.summary 或 chapter_plan.stages，供后续 AI 章节规划使用。"
            "timeline 只保留正文已经发生的时间顺序事实；summary 只保留正文已经写出的全局阶段总结。"
            "导入框架通常还没有正文，timeline 和 summary 默认留空。\n"
            "人物只保留主角、重要配角、反派、长期角色和有明确后续作用的人；路人、无名群体、一次性称谓不要进入人物。\n"
            "设定只保留地点、组织、物品、规则、术语、制度、能力限制等稳定信息；普通剧情动作不要写入设定。\n"
            "伏笔只保留长期悬念、关键秘密、明确待回收承诺；普通冲突、短期疑问、章节钩子不要当长期伏笔。\n"
            "章节规划只提取原文已经明确写出的单章标题和阶段资料；不要凭空生成完整章节规划。"
            "stages 只保留原文明确给出的阶段名称、章节范围和阶段内剧情节点；原文未给明确章节范围时，"
            "把全书走向、故事节奏以及前中后期的题材/情绪/节奏变化写入 chapter_plan.summary，不要猜测范围。\n"
            "重要格式规则：chapters 只能放明确的单章（例如“第一章：……”）；“第4—10章：……”或“第N卷：……”"
            "是范围、分卷或阶段标题，绝对不能作为某一章的 title 或 chapter item。范围标题及其剧情节点应放入阶段资料，"
            "如果原文没有明确的单章标题，不要把范围标题改写成单章。\n"
            "JSON 结构：{\n"
            '  "meta": {"title":"","genre":"","style":"","pov":"","target_words":"","status":"","premise":""},\n'
            '  "project_materials": {"bible_sections":{"core_setting":"","reader_promise":"","theme":"","main_conflict":"","relationship_foundation":"","ending_direction":""},"bible":"","world_rules":"","timeline":"","summary":""},\n'
            '  "characters": [{"name":"","role":"","goal":"","secret":"","voice":"","notes":""}],\n'
            '  "lore": [{"name":"","type":"地点/势力/物品/规则/术语/事件/其他","description":""}],\n'
            '  "foreshadows": [{"name":"","status":"未埋/已埋/已回收/无需回收/废弃","setup_chapter":"","payoff_chapter":"","description":""}],\n'
            '  "chapter_plan": {"summary":"","stages":[{"id":"","name":"","start_chapter":0,"end_chapter":0,"events":[{"order":1,"text":""}]}],"chapters":[{"index":1,"title":"","target_words":"","narrative_stage":"","outline":"","ending_hook":""}]}\n'
            "}\n"
            "空字段用空字符串，空列表用 []。"
        )

    def _framework_user_text(self):
        payload = {
            "已有项目档案": self.project_context,
            "导入框架原文": self.framework_text,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return str(chunk_text or "")

    def _analysis_progress_label(self):
        return "框架分类"

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        if self._is_analysis_rate_limit_error(error):
            return f"框架 AI 分类遇到接口并发限制，{wait_seconds} 秒后自动重试 {next_attempt}/{attempts}..."
        return f"框架 AI 分类暂时失败，{wait_seconds} 秒后自动重试 {next_attempt}/{attempts}..."

    def _allow_retry_chunk_split(self):
        return False

    def _string_list(self, value):
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item or "").strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [item.strip() for item in re.split(r"[、,，;\n；]+", text) if item.strip()]

    def _clean_title(self, value, fallback):
        title = str(value or "").strip()
        title = title.strip(" \t\r\n\"'“”‘’《》「」『』【】[]()（）")
        title = re.sub(r"^\s*第\s*[\d一二三四五六七八九十百千万零〇两]+\s*[章节回集卷部]\s*[:：、.\-—]*\s*", "", title)
        title = re.sub(r"^\s*[\d一二三四五六七八九十百千万零〇两]+\s*[、.．]\s*", "", title)
        title = re.sub(r"\s+", "", title)
        title = title.strip(" \t\r\n\"'“”‘’《》「」『』【】[]()（）：:，,。；;、")
        return title or fallback

    def _target_words_text(self, value):
        match = re.search(r"\d{2,7}", str(value or ""))
        return match.group(0) if match else str(value or "").strip()

    def _project_target_words_text(self, value):
        text = str(value or "").replace(",", "").strip()
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return text
        try:
            number = float(match.group(0))
        except Exception:
            return match.group(0).strip()
        if "万" not in text and number >= 1000:
            number = number / 10000
        number_text = f"{number:.2f}".rstrip("0").rstrip(".")
        return number_text or match.group(0).strip()

    def _framework_bible_section_text(self, value):
        if isinstance(value, (list, tuple)):
            return "\n".join(
                str(item or "").strip() for item in value if str(item or "").strip()
            ).strip()
        return str(value or "").strip()

    def _framework_bible_sections(self, data):
        data = data if isinstance(data, dict) else {}
        materials = data.get("project_materials", {})
        materials = materials if isinstance(materials, dict) else {}
        raw_sections = materials.get("bible_sections")
        if not isinstance(raw_sections, dict) or not raw_sections:
            raw_sections = data.get("bible_sections")
        if not isinstance(raw_sections, dict) or not raw_sections:
            raw_sections = materials.get("bible", {})
        if not isinstance(raw_sections, dict) or not raw_sections:
            raw_sections = data.get("bible", {})
        raw_sections = raw_sections if isinstance(raw_sections, dict) else {}
        parts = []
        for key, label, aliases in self._BIBLE_SECTION_FIELDS:
            value = self._framework_bible_section_text(raw_sections.get(key, ""))
            if not value:
                for alias in aliases:
                    value = self._framework_bible_section_text(raw_sections.get(alias, ""))
                    if value:
                        break
            if value:
                parts.append(f"{label}\n{value}")
        return "\n\n".join(parts).strip()

    def _framework_project_materials(self, data):
        data = data if isinstance(data, dict) else {}
        materials = data.get("project_materials", {})
        materials = deepcopy(materials) if isinstance(materials, dict) else {}
        sectioned_bible = self._framework_bible_sections(data)
        raw_bible = materials.get("bible", "")
        if not raw_bible:
            raw_bible = data.get("bible", "")
        raw_bible = "" if isinstance(raw_bible, dict) else str(raw_bible or "").strip()
        materials["bible"] = sectioned_bible or raw_bible
        materials.pop("bible_sections", None)
        return materials

    def _outline_from_item(self, item):
        item = item if isinstance(item, dict) else {}
        outline = str(item.get("outline", "") or item.get("提纲", "") or item.get("剧情", "") or "").strip()
        parts = []
        if not outline:
            for key in ("mainline_task", "character_task", "relationship_task", "goal"):
                value = str(item.get(key, "") or "").strip()
                if value and value not in parts:
                    parts.append(value)
        if outline:
            parts.append(outline)
        ending_hook = str(item.get("ending_hook", "") or "").strip()
        if ending_hook:
            parts.append(f"结尾钩子：{ending_hook}")
        return "\n\n".join(part for part in parts if part).strip()

    def _normalize_chapter_plan(self, data):
        data = data if isinstance(data, dict) else {}
        plan = data.get("chapter_plan", {})
        if isinstance(plan, list):
            plan = {"chapters": plan}
        plan = plan if isinstance(plan, dict) else {}
        chapters = plan.get("chapters", [])
        normalized = []
        for fallback_index, item in enumerate(chapters if isinstance(chapters, list) else [], 1):
            if not isinstance(item, dict):
                continue
            raw_title = str(item.get("title", "") or item.get("章节名", "")).strip()
            if not raw_title:
                continue
            if _is_framework_scope_title(raw_title) or _is_framework_placeholder_chapter_title(raw_title):
                continue
            title = self._clean_title(raw_title, "")
            if not title:
                continue
            outline = self._outline_from_item(item)
            if not outline:
                continue
            try:
                index = int(item.get("index", fallback_index) or fallback_index)
            except Exception:
                index = fallback_index
            normalized_item = {
                "index": index,
                "title": title,
                "target_words": self._target_words_text(item.get("target_words", "") or item.get("字数", "")),
                "narrative_stage": str(item.get("narrative_stage", "") or "").strip(),
                "outline": outline,
                "characters": self._string_list(item.get("characters", [])),
                "ending_hook": str(item.get("ending_hook", "") or "").strip(),
            }
            for key in (
                "relationship_task", "investigation_scope", "chapter_function",
                "conflict_intensity", "setup_ratio", "character_task", "mainline_task",
                "planning_method", "start_state", "must_happen", "forbidden_reveal",
                "satisfaction_payoff", "emotional_resonance", "relationship_change",
                "exposition_compression", "variation_pattern", "foreshadow_task",
                "forbidden", "goal", "main_event", "conflict", "turning_point",
                "emotional_shift",
            ):
                value = str(item.get(key, "") or "").strip()
                if value:
                    normalized_item[key] = value
            for key in ("dynamic_modules", "settings", "foreshadows", "required_events"):
                values = self._string_list(item.get(key, []))
                if values:
                    normalized_item[key] = values
            normalized.append(normalized_item)
        normalized.sort(key=lambda item: item.get("index", 0))
        for index, item in enumerate(normalized, 1):
            item["index"] = index
        stages = []
        raw_stages = plan.get("stages", [])
        for fallback_index, item in enumerate(raw_stages if isinstance(raw_stages, list) else [], 1):
            if not isinstance(item, dict):
                continue
            try:
                start_chapter = int(item.get("start_chapter", 0) or 0)
                end_chapter = int(item.get("end_chapter", 0) or 0)
            except Exception:
                continue
            name = str(item.get("name", "") or "").strip()
            if not name or start_chapter <= 0 or end_chapter < start_chapter:
                continue
            stage_id = str(item.get("id", "") or f"S{fallback_index:02d}").strip().upper()
            events = []
            raw_events = item.get("events", [])
            for event_index, event in enumerate(raw_events if isinstance(raw_events, list) else [], 1):
                event_data = event if isinstance(event, dict) else {"text": event}
                text = str(event_data.get("text", "") or "").strip()
                if not text:
                    continue
                try:
                    order = int(event_data.get("order", event_index) or event_index)
                except Exception:
                    order = event_index
                events.append({
                    "id": str(event_data.get("id", "") or f"{stage_id}-E{event_index:02d}").strip().upper(),
                    "order": order,
                    "text": text,
                })
            if events:
                stages.append({
                    "id": stage_id,
                    "name": name,
                    "start_chapter": start_chapter,
                    "end_chapter": end_chapter,
                    "events": events,
                })
        return {
            "summary": str(plan.get("summary", "") or data.get("summary", "") or "").strip(),
            "stages": stages,
            "chapters": normalized,
        }

    def _normalize_framework_result(self, data):
        data = data if isinstance(data, dict) else {}
        candidate_data = deepcopy(data)
        candidate_data["project_materials"] = self._framework_project_materials(data)
        candidate_data.pop("bible", None)
        candidate_data.pop("bible_sections", None)
        candidates = _normalize_ai_candidates(candidate_data)
        meta_source = data.get("meta") or data.get("project_info") or data.get("项目信息") or {}
        meta_source = meta_source if isinstance(meta_source, dict) else {}
        meta = {}
        for key in ("title", "genre", "style", "pov", "target_words", "status", "premise"):
            value = str(meta_source.get(key, "") or "").strip()
            if key == "target_words":
                value = self._project_target_words_text(value)
            meta[key] = value
        return {
            "meta": meta,
            "project_materials": candidates.get("project_materials", {}),
            "characters": candidates.get("characters", []),
            "lore": candidates.get("lore", []),
            "foreshadows": candidates.get("foreshadows", []),
            "chapter_plan": self._normalize_chapter_plan(data),
        }

    def run(self):
        started = self._start_analysis_diagnostics()
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not self.framework_text.strip():
                raise Exception("没有可分类的框架内容。")
            self.progress.emit("正在用 AI 分类导入框架...")
            response_format_supported, _stream_supported = self._analysis_request_capabilities()
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._analysis_prompt(),
                self._framework_user_text(),
                1,
                1,
                response_format_supported,
            )
            if self._stop_requested or self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("stopped", started)
                return
            self._finalize_analysis_diagnostics("success", started)
            self.result_ready.emit(self._normalize_framework_result(parsed))
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("error", started, e)
                self.failed.emit(str(e))
            else:
                self._finalize_analysis_diagnostics("stopped", started)
        finally:
            self._close_active_network_handles()


class NovelVolumeHandoffWorker(NovelAnalysisWorker):
    """Create a compact, factual bridge from a completed volume."""

    result_ready = Signal(dict)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        source_context,
        source_catalog=None,
        proxy_url="",
        proxy_mode="不使用代理",
    ):
        self.source_context = deepcopy(source_context if isinstance(source_context, dict) else {})
        self.source_catalog = deepcopy(source_catalog if isinstance(source_catalog, dict) else {})
        if not self.source_catalog:
            records = self.source_context.get("records", {})
            records = records if isinstance(records, dict) else {}
            self.source_catalog = {
                "characters": deepcopy(records.get("characters", [])),
                "lore": deepcopy(records.get("lore", [])),
                "foreshadows": (
                    deepcopy(records.get("foreshadows", []))
                    + deepcopy(records.get("resolved_foreshadows", []))
                    + deepcopy(records.get("discarded_foreshadows", []))
                ),
            }
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self._retry_stream_transport_before_nonstream = True

    def _analysis_prompt(self):
        return (
            "你是长篇小说续作的交接编辑。请根据上一卷资料，整理一份只记录已发生事实的交接摘要，"
            "供本卷框架生成使用。不要写正文，不要擅自解决未完成伏笔，不要替用户决定本卷剧情。\n"
            "必须只输出一个合法 JSON 对象，不要 Markdown、解释或注释。不要把上一卷全文复述进摘要。\n"
            "输出以去重为先：同一事实只放在最合适的字段，不要在不同字段中反复改写。"
            "每个文字字段只写对本卷有继承价值的短句，不写分析过程，不写证据链，不写正文式解释。\n"
            "重点保留：上一卷结尾已经落地的处境、人物关系和目标、仍有效的世界规则、尚未完成的冲突/伏笔、"
            "以及明确适合在本卷继续使用的人物和设定。人物、设定和伏笔的名称要沿用原项目名称。\n"
            "最后一章正文是即时接续证据：只能用来确认卷末场景、最后动作、对话和情绪，不得把其中未发生的推测写成事实。\n"
            "reusable_characters、reusable_lore、reusable_foreshadows只负责从本地档案中选择需要沿用的名称/编号，"
            "默认每项只填name或code，其余详细字段留空；程序会按名称/编号从上一卷本地档案补回完整资料，不要重复抄写档案。"
            "人物筛选时，除主角和本卷主线人物外，必须保留主角的直系家人、前任配偶或固定伴侣、"
            "重要朋友/闺蜜、长期盟友、心腹、固定对手及其他具有长期关系记忆价值的人物；"
            "即使这些人物在本卷当前阶段没有具体剧情，也要保留规范姓名，避免后续重新创造同类人物。"
            "一次性工作人员、普通路人、匿名群体和只承担一次流程动作的人物仍然排除。"
            "人物状态只写本卷结尾后仍有效的变化，关系状态只写核心未解决关系；普通人物介绍和重复状态不要输出。\n"
            "records.foreshadows中的活动伏笔不是本卷必须回收清单。请逐条分流："
            "reusable_foreshadows只放不继承就会造成前后矛盾、直接连接卷末主线、"
            "核心人物未完成目标或用户明确要求继续的长期伏笔；"
            "deferred_foreshadows放上一卷仍可追溯、但本卷不要求主动回收的旧线、一次性线和可选线。"
            "reusable_foreshadows按对本卷连续性的重要性排序，最多选择12条；宁可延期旧线，也不要把旧案清单变成本卷任务表。"
            "每条活动伏笔必须按编号或名称只出现在其中一个列表；模型只需输出名称/编号和简短分流理由，"
            "程序会按编号/名称从上一卷本地档案补回完整资料。已回收、无需回收、废弃伏笔不进入本卷活动档案。\n"
            "resolved_threads只列重要已收束主线，open_threads只列尚未解决且未被伏笔列表覆盖的主线/关系线，"
            "卷末已发生事实按人物状态、关系状态、世界状态和未完成主线自然记录。"
            "continuity_anchors只记录有多个章节证据支持、跨卷后仍不能反写的稳定事实，例如长期生活分工、"
            "固定关系习惯或核心人物的长期相处底盘；每条附来源章节。它们是事实参考，不是剧情任务、章节要求或禁止事项，"
            "不要为了填满字段虚构内容。\n"
            "JSON 结构：{\n"
            '  "volume_summary":"上一卷整体收束状态",\n'
            '  "ending_state":{"story_time":"","location":"","current_situation":"","last_action":"","immediate_tension":""},\n'
            '  "character_states":[{"name":"","state":"","goal":"","relationship":""}],\n'
            '  "relationship_states":[{"characters":[],"state":"","unresolved":""}],\n'
            '  "continuity_anchors":[{"category":"","fact":"","source_chapters":[]}],\n'
            '  "world_state":"上一卷结束时仍有效的世界/势力状态",\n'
            '  "resolved_threads":["已完成且不要误写成未完成的线"],\n'
            '  "open_threads":["仍未解决、可供续作接入的线"],\n'
            '  "reusable_characters":[{"name":""}],\n'
            '  "reusable_lore":[{"name":""}],\n'
            '  "foreshadow_selection_version":2,\n'
            '  "reusable_foreshadows":[{"code":"","name":"","reason":""}],\n'
            '  "deferred_foreshadows":[{"code":"","name":"","reason":""}],\n'
            '  "resolved_foreshadows":[],\n'
            '  "discarded_foreshadows":[]\n'
            "}\n"
            "没有明确内容时使用空字符串或空数组；不要为了填满字段虚构内容。输出是交接索引，不是完整复述稿。"
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        prefix = (
            "以下是上一卷交接资料。请逐项核对来源，只输出有依据的交接信息。\n\n"
        )
        source_budget = min(
            105000,
            max(
                12000,
                VOLUME_CONTINUATION_REQUEST_CHAR_BUDGET
                - len(self._analysis_prompt())
                - len(prefix)
                - 256,
            ),
        )
        source = _compact_volume_handoff_source_for_request(
            self.source_context,
            source_budget,
        )
        user_text = prefix + json.dumps(source, ensure_ascii=False, indent=2)
        self.diagnostics["input_chars"] = len(user_text)
        self.diagnostics["input_utf8_bytes"] = len(user_text.encode("utf-8", errors="replace"))
        return user_text

    def _analysis_progress_label(self):
        return "上一卷交接摘要"

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        return f"上一卷交接摘要暂时失败，{wait_seconds} 秒后自动重试 {next_attempt}/{attempts}..."

    def _allow_retry_chunk_split(self):
        return False

    @staticmethod
    def _list_value(value):
        if isinstance(value, list):
            return [deepcopy(item) for item in value if isinstance(item, (dict, str)) and str(item or "").strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [item.strip() for item in re.split(r"[\n、，,；;]+", text) if item.strip()]

    def _normalize_handoff(self, data):
        data = data if isinstance(data, dict) else {}
        model_reusable = _normalize_ai_candidates({
            "characters": data.get("reusable_characters", []),
            "lore": data.get("reusable_lore", []),
            "foreshadows": data.get("reusable_foreshadows", []),
        })
        source_records = self.source_context.get("records", {})
        source_records = source_records if isinstance(source_records, dict) else {}

        def record_key(item, kind):
            item = item if isinstance(item, dict) else {}
            if kind == "foreshadows":
                code = re.sub(r"\s+", "", str(item.get("code", "") or "")).upper()
                if code:
                    return "code:" + code
            name = re.sub(r"[\s《》<>【】\[\]（）()]+", "", str(item.get("name", "") or "")).lower()
            return "name:" + name if name else ""

        def enrich_selected(kind, selected, fallback=None):
            catalog_items = self.source_catalog.get(kind, [])
            catalog_items = catalog_items if isinstance(catalog_items, list) else []
            catalog = {
                record_key(item, kind): item
                for item in catalog_items
                if isinstance(item, dict) and record_key(item, kind)
            }
            selected = selected if isinstance(selected, list) else []
            if not selected and isinstance(fallback, list):
                selected = fallback
            enriched = []
            seen = set()
            for raw in selected:
                if not isinstance(raw, dict):
                    continue
                key = record_key(raw, kind)
                if not key or key in seen:
                    continue
                source_item = catalog.get(key)
                if source_item is None and kind == "foreshadows":
                    name_key = record_key({"name": raw.get("name", "")}, "characters")
                    source_item = next(
                        (
                            item for item in catalog_items
                            if record_key({"name": item.get("name", "")}, "characters") == name_key
                        ),
                        None,
                    )
                if source_item is None:
                    continue
                item = deepcopy(source_item)
                for field, value in raw.items():
                    if field == "id" or value in (None, "", [], {}):
                        continue
                    item[field] = deepcopy(value)
                enriched.append(item)
                seen.add(key)
            return enriched

        # Characters and settings are selected semantically by the handoff AI,
        # then enriched from the untouched local project catalog. Foreshadow
        # inheritance is an explicit AI selection; unresolved does not mean
        # mandatory for the sequel.
        selected_characters = model_reusable.get("characters", [])
        if not selected_characters:
            selected_characters = list(source_records.get("characters", []))[:12]

        # Preserve explicit relationship anchors even when the handoff model
        # omits them from its reusable-character index. This is intentionally
        # limited to relationship wording already present in the source role
        # or notes, so one-off staff and unnamed process roles stay excluded.
        source_characters = self.source_catalog.get("characters", [])
        source_characters = source_characters if isinstance(source_characters, list) else []
        core_names = set()
        for item in source_characters:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            role = str(item.get("role", "") or "").strip()
            if name and any(
                marker in role
                for marker in ("男主", "女主", "主角", "核心人物", "情感线核心")
            ):
                core_names.add(name)
        relationship_markers = (
            "母亲", "父亲", "妈妈", "爸爸", "哥哥", "姐姐", "弟弟", "妹妹",
            "儿子", "女儿", "家人", "亲属", "岳母", "岳父", "前妻", "前夫",
            "丈夫", "妻子", "伴侣", "朋友", "闺蜜", "好友", "盟友", "心腹",
            "长期伙伴", "长期朋友", "核心协作者", "核心盟友", "固定对手",
            "重要旧关系", "旧关系", "旧识", "旧友", "故人", "前同事", "前下属",
            "旧部", "恩人",
        )
        generic_core_markers = ("主角", "男主", "女主", "男女主")
        relationship_anchor_markers = (
            "核心盟友", "核心协作者", "长期伙伴", "长期朋友", "固定对手", "重要旧关系",
        )
        required_relationship_characters = []
        if core_names:
            for item in source_characters:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "") or "").strip()
                if not name:
                    continue
                role_and_notes = " ".join(
                    str(item.get(field, "") or "").strip()
                    for field in ("role", "notes")
                )
                mentions_core = any(core_name in role_and_notes for core_name in core_names)
                mentions_core_generically = any(
                    marker in role_and_notes for marker in generic_core_markers
                )
                has_relationship = any(marker in role_and_notes for marker in relationship_markers)
                is_relationship_anchor = any(
                    marker in role_and_notes for marker in relationship_anchor_markers
                )
                is_core = name in core_names
                if is_core or (
                    has_relationship
                    and (mentions_core or mentions_core_generically or is_relationship_anchor)
                ):
                    required_relationship_characters.append(deepcopy(item))
        selected_character_keys = {
            record_key(item, "characters")
            for item in selected_characters
            if record_key(item, "characters")
        }
        required_missing_characters = [
            item
            for item in required_relationship_characters
            if record_key(item, "characters") not in selected_character_keys
        ]
        # Put only omitted continuity anchors first. Existing AI selections
        # retain their latest handoff fields and are never overwritten by an
        # older source-card copy.
        selected_characters = required_missing_characters + list(selected_characters)
        # Basic geography is continuity data, not a sequel plot preference.
        # Keep every explicitly classified location locally so the handoff
        # cannot lose the story's existing cities and recurring places just
        # because the model omitted them from its reuse index.
        source_lore = self.source_catalog.get("lore", [])
        source_lore = source_lore if isinstance(source_lore, list) else []
        inherited_geography = [
            deepcopy(item)
            for item in source_lore
            if isinstance(item, dict)
            and str(item.get("type", "") or "").strip() in {"地点", "城市", "国家", "区域"}
        ]
        catalog_foreshadows = self.source_catalog.get("foreshadows", [])
        catalog_foreshadows = catalog_foreshadows if isinstance(catalog_foreshadows, list) else []
        active_foreshadows = [
            item for item in catalog_foreshadows
            if isinstance(item, dict)
            and _infer_foreshadow_status(item, preserve_manual=False) not in {"已回收", "无需回收", "废弃"}
        ]
        selected_foreshadows = enrich_selected(
            "foreshadows",
            list(model_reusable.get("foreshadows", [])),
        )
        selected_foreshadows = [
            item for item in selected_foreshadows
            if _infer_foreshadow_status(item, preserve_manual=False)
            not in {"已回收", "无需回收", "废弃"}
        ][:12]
        selected_foreshadow_keys = {
            record_key(item, "foreshadows")
            for item in selected_foreshadows
            if record_key(item, "foreshadows")
        }
        explicit_deferred = _normalize_ai_candidates({
            "foreshadows": data.get("deferred_foreshadows", []),
        }).get("foreshadows", [])
        deferred_foreshadows = []
        deferred_keys = set()
        for raw in list(explicit_deferred) + active_foreshadows:
            if (
                isinstance(raw, dict)
                and _infer_foreshadow_status(raw, preserve_manual=False)
                in {"已回收", "无需回收", "废弃"}
            ):
                continue
            key = record_key(raw, "foreshadows")
            if not key or key in selected_foreshadow_keys or key in deferred_keys:
                continue
            source_item = next(
                (
                    item for item in catalog_foreshadows
                    if record_key(item, "foreshadows") == key
                ),
                None,
            )
            if source_item is None:
                continue
            deferred_foreshadows.append({
                "code": str(source_item.get("code", "") or "").strip(),
                "name": str(source_item.get("name", "") or "").strip(),
                "status": str(source_item.get("status", "") or "").strip(),
            })
            deferred_keys.add(key)
        reusable = _normalize_ai_candidates({
            "characters": enrich_selected("characters", selected_characters),
            "lore": enrich_selected(
                "lore",
                list(model_reusable.get("lore", [])) + inherited_geography,
            ),
            "foreshadows": selected_foreshadows,
        })
        resolved_foreshadows = _dedupe_volume_handoff_terminal_records(
            source_records.get("resolved_foreshadows", []),
            [
                deepcopy(item)
                for item in data.get("resolved_foreshadows", [])
                if isinstance(item, dict) and str(item.get("name", "") or "").strip()
            ],
        )
        resolved_foreshadows = _compact_volume_handoff_for_framework({
            "resolved_foreshadows": resolved_foreshadows,
        }).get("resolved_foreshadows", [])
        discarded_foreshadows = _dedupe_volume_handoff_terminal_records(
            source_records.get("discarded_foreshadows", []),
            [
                deepcopy(item)
                for item in data.get("discarded_foreshadows", [])
                if isinstance(item, dict) and str(item.get("name", "") or "").strip()
            ],
        )
        discarded_foreshadows = _compact_volume_handoff_for_framework({
            "discarded_foreshadows": discarded_foreshadows,
        }).get("discarded_foreshadows", [])
        terminal_foreshadow_keys = {
            record_key(item, "foreshadows")
            for item in resolved_foreshadows + discarded_foreshadows
            if isinstance(item, dict) and record_key(item, "foreshadows")
        }
        deferred_foreshadows = [
            item for item in deferred_foreshadows
            if record_key(item, "foreshadows") not in terminal_foreshadow_keys
        ]

        ending_state = data.get("ending_state", {})
        ending_state = deepcopy(ending_state) if isinstance(ending_state, dict) else {}
        if not ending_state:
            last_chapter = self.source_context.get("last_chapter", {})
            last_chapter = last_chapter if isinstance(last_chapter, dict) else {}
            ending_state = {
                "location": "",
                "current_situation": str(last_chapter.get("summary", "") or "").strip(),
                "last_action": str(last_chapter.get("key_facts", "") or "").strip(),
            }
        volume_summary = str(data.get("volume_summary", "") or "").strip()
        if not volume_summary:
            volume_summary = str(
                self.source_context.get("summary", "")
                or self.source_context.get("source_project", {}).get("premise", "")
                or ""
            ).strip()
        result = {
            "volume_summary": volume_summary,
            "ending_state": ending_state,
            "character_states": self._list_value(data.get("character_states", [])),
            "relationship_states": self._list_value(data.get("relationship_states", [])),
            "world_state": str(data.get("world_state", "") or "").strip(),
            "resolved_threads": self._list_value(data.get("resolved_threads", [])),
            "open_threads": self._list_value(data.get("open_threads", [])),
            "continuity_anchors": _normalize_volume_continuity_anchors(
                data.get("continuity_anchors", [])
            ),
            "reusable_characters": reusable.get("characters", []),
            "reusable_lore": reusable.get("lore", []),
            "reusable_foreshadows": reusable.get("foreshadows", []),
            "foreshadow_selection_version": 2,
            "deferred_foreshadows": deferred_foreshadows,
            "resolved_foreshadows": resolved_foreshadows,
            "discarded_foreshadows": discarded_foreshadows,
            "inherited_materials": {
                "bible": str(self.source_context.get("bible", "") or "").strip(),
                "world_rules": str(self.source_context.get("world_rules", "") or "").strip(),
            },
            # Keep this verbatim as a first-volume anchor for the framework call.
            "last_chapter": deepcopy(self.source_context.get("last_chapter", {})),
        }
        if "continuity_boundaries" in data:
            result["continuity_boundaries"] = self._list_value(data.get("continuity_boundaries", []))
        elif "continuity_boundaries" in source_records:
            result["continuity_boundaries"] = self._list_value(
                source_records.get("continuity_boundaries", [])
            )
        return result

    def run(self):
        started = self._start_analysis_diagnostics()
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not self.source_context:
                raise Exception("没有可生成交接摘要的上一卷资料。")
            self.progress.emit("正在生成上一卷交接摘要...")
            response_format_supported, _stream_supported = self._analysis_request_capabilities()
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._analysis_prompt(),
                "",
                1,
                1,
                response_format_supported,
            )
            if self._stop_requested or self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("stopped", started)
                return
            self._finalize_analysis_diagnostics("success", started)
            self.result_ready.emit(self._normalize_handoff(parsed))
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("error", started, e)
                self.failed.emit(str(e))
            else:
                self._finalize_analysis_diagnostics("stopped", started)
        finally:
            self._close_active_network_handles()


class NovelVolumeIntentWorker(NovelAnalysisWorker):
    """Interpret free-form sequel requirements into a small planning contract."""

    result_ready = Signal(dict)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        setup_meta=None,
        user_requirements="",
        handoff=None,
        proxy_url="",
        proxy_mode="不使用代理",
    ):
        self.setup_meta = deepcopy(setup_meta if isinstance(setup_meta, dict) else {})
        self.user_requirements = str(user_requirements or "").strip()
        handoff = handoff if isinstance(handoff, dict) else {}
        self.handoff = {
            "volume_summary": str(handoff.get("volume_summary", "") or "").strip(),
            "ending_state": deepcopy(handoff.get("ending_state", {}))
            if isinstance(handoff.get("ending_state", {}), dict) else {},
            "character_states": deepcopy(handoff.get("character_states", []))
            if isinstance(handoff.get("character_states", []), list) else [],
            "relationship_states": deepcopy(handoff.get("relationship_states", []))
            if isinstance(handoff.get("relationship_states", []), list) else [],
            "open_threads": deepcopy(handoff.get("open_threads", []))
            if isinstance(handoff.get("open_threads", []), list) else [],
        }
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self._retry_stream_transport_before_nonstream = True

    def _analysis_prompt(self):
        return (
            "你是长篇小说续作的创作意图整理编辑。把用户对本卷的口语化要求整理成一个简短、可编辑的创作意图契约，"
            "供本卷框架和章节规划使用。必须只输出一个合法 JSON 对象，不要 Markdown、解释、注释或正文。\n"
            "用户明确写出的主线优先级最高。用户说‘以感情线为主’时，primary_line必须是感情/关系推进，"
            "不能因为上一卷有商业、案件、旧案或专业线，就把它改成主线。交接资料只提供已发生事实、人物关系和未完成状态，"
            "不负责决定本卷叙事发动机。辅助线只能制造压力、选择或后果，不能独立夺走本卷主位。\n"
            "不要编写详细剧情、逐章事件、固定比例、每章动作清单或模板化章法；只保留用户真正想要的方向。"
            "没有明确内容的字段留空，不要根据交接资料自行扩写。\n"
            'JSON结构：{"primary_line":"","supporting_lines":[],"core_relationships":"",'
            '"stage_progression":"","reading_experience":"","supporting_line_usage":""}'
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        payload = {
            "本卷基本信息": self.setup_meta,
            "用户原始要求": _clip_context_text(
                self.user_requirements, 8000, keep_tail=True, preserve_lines=True
            ),
            "上一卷交接事实（只作连续性依据）": self.handoff,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _normalize_intent(self, data):
        data = data if isinstance(data, dict) else {}
        for key in ("creative_intent_contract", "creative_intent", "intent", "创作意图"):
            nested = data.get(key)
            if isinstance(nested, dict):
                data = nested
                break
        result = _normalize_creative_intent_contract(data)
        if not result.get("primary_line"):
            raise ValueError("AI没有识别到本卷主线。")
        result["version"] = str(result.get("version", "1") or "1")
        result["source"] = "volume_user_requirements"
        return result

    def run(self):
        started = self._start_analysis_diagnostics()
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            self.progress.emit("正在理解本卷创作要求...")
            response_format_supported, _stream_supported = self._analysis_request_capabilities()
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._analysis_prompt(), self._chunk_user_text("", 1, 1),
                1, 1, response_format_supported,
            )
            if self._stop_requested or self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("stopped", started)
                return
            result = self._normalize_intent(parsed)
            self._finalize_analysis_diagnostics("success", started)
            self.result_ready.emit(result)
        except Exception as exc:
            if not self._stop_requested and not self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("error", started, exc)
                self.failed.emit(str(exc))
            else:
                self._finalize_analysis_diagnostics("stopped", started)
        finally:
            self._close_active_network_handles()


class NovelVolumeFrameworkWorker(NovelFrameworkImportWorker):
    """Generate the editable second-volume framework from three source groups."""

    result_ready = Signal(dict)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        handoff,
        user_requirements,
        template_text,
        proxy_url="",
        proxy_mode="不使用代理",
        setup_meta=None,
        creative_intent_contract=None,
    ):
        self.volume_handoff = deepcopy(handoff if isinstance(handoff, dict) else {})
        self.user_requirements = str(user_requirements or "").strip()
        self.template_text = str(template_text or "").strip()
        self.setup_meta = deepcopy(setup_meta if isinstance(setup_meta, dict) else {})
        self.creative_intent_contract = _normalize_creative_intent_contract(
            creative_intent_contract
        )
        super().__init__(
            base_url,
            api_key,
            model,
            self.template_text,
            project_context="",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
        )
        self._retry_stream_transport_before_nonstream = True

    def _analysis_prompt(self):
        stage_guidance = self._stage_planning_guidance()
        return (
            "你是长篇小说续作框架设计编辑。请依据上一卷交接、本卷基本信息/用户要求和小说模板生成本卷项目框架，"
            "只生成框架资料，不生成正文，不生成详细逐章章节规划。\n"
            "必须只输出一个合法 JSON 对象，不要 Markdown、解释或注释。\n"
            "上一卷交接资料是连续性底座，不要把同一事实同时复述到圣经、人物、设定、伏笔和阶段事件中；"
            "人物、设定、伏笔字段只写本卷需要继续使用或新增的内容，交接资料中已经有的卷末状态不要逐字改写。\n"
            "上一卷交接摘要和最后一章正文是连续性事实依据：已发生事实、人际关系、世界规则和未完成伏笔必须沿用；"
            "最后一章正文只用于确认卷末即时场景，不能把推测写成已发生事实。\n"
            "continuity_anchors是上一卷已经反复得到证据支持的稳定事实，只用于校准本卷框架中的人物、关系和基础设定；"
            "不要把它们单独扩写成新的规则层，也不要把每条锚点变成本卷阶段任务或逐章要求。必要内容请自然吸收进现有圣经、人物或设定字段。\n"
            "下面的creative_intent_contract是用户确认过的本卷创作意图，优先级高于交接资料和AI对题材的推断；"
            "primary_line必须贯穿本卷，supporting_lines只能服务于主线并改变人物选择、关系或情绪状态，不能反客为主。"
            "允许设计新的本卷剧情、人物和阶段变化。上一卷未完成状态不能被改写成已经完成，但不代表所有旧线都必须在本卷主动推进；"
            "是否进入本卷主线由用户要求和creative_intent_contract决定，其余旧线可以保持未完成并延期。\n"
            "严格按小说模板返回：meta 写项目信息；project_materials.bible 只写本卷新增或变更的圣经内容；"
            "project_materials.world_rules 只写本卷新增或变更的世界规则；上一卷圣经和世界规则由程序本地继承，"
            "不要在这两个字段重复改写上一卷原文。确认窗口和最终项目会显示‘上一卷基础资料 + 本卷新增内容’；"
            "characters 写主要人物；lore 写稳定设定；"
            "foreshadows 写需要继续追踪的伏笔。上一卷已经发生的时间线和全局摘要不要填入本卷的 timeline/summary，"
            "它们应由本卷正文完成后再产生。\n"
            "交接资料中的reusable_foreshadows才是本卷默认可用的旧伏笔；被标记为deferred的上一卷旧线不在本次请求中，"
            "但reusable_foreshadows仍只是候选池，不是必须全部继承的清单。只有本卷阶段主线明确需要时，才把对应旧伏笔写入foreshadows；"
            "没有写入的旧伏笔由程序留在上一卷归档，不要自行恢复、改写或为了填满框架新增同类旧伏笔。\n"
            f"{stage_guidance}\n"
            "chapter_plan.summary只写卷级主线方向，stages只写阶段边界、阶段目标和少量高层转折；"
            "不要把每一章拆成固定动作清单，不要生成章节标题、章节正文、章节摘要或100章逐章结果，chapters必须返回空数组。"
            "本卷结尾保留可继续发展的空间，不要把所有线索一次性封死。\n"
            "JSON 结构：{\n"
            '  "meta":{"title":"","genre":"","style":"","pov":"","target_words":"","status":"草稿","premise":""},\n'
            '  "project_materials":{"bible":"","world_rules":"","timeline":"","summary":""},\n'
            '  "characters":[{"name":"","role":"","goal":"","secret":"","voice":"","notes":""}],\n'
            '  "lore":[{"name":"","type":"地点/势力/物品/规则/术语/事件/其他","description":""}],\n'
            '  "foreshadows":[{"name":"","status":"未埋/已埋/已回收/无需回收/废弃","setup_chapter":"","payoff_chapter":"","description":"","remaining_secret":""}],\n'
            '  "chapter_plan":{"summary":"","stages":[{"id":"","name":"","start_chapter":0,"end_chapter":0,"events":[{"order":1,"text":""}]}],"chapters":[]}\n'
            "}\n"
            "字段没有依据时留空，不要为了完整而虚构上一卷事实。"
        )

    def _stage_planning_guidance(self):
        meta = self.setup_meta if isinstance(self.setup_meta, dict) else {}
        raw_target = str(meta.get("target_words", "") or "").strip()
        match = re.search(r"\d+(?:\.\d+)?", raw_target)
        if match:
            try:
                target_wan = float(match.group(0))
            except Exception:
                target_wan = 0.0
        else:
            target_wan = 0.0
        if target_wan > 0:
            stage_count = max(1, int(math.ceil(target_wan / 5.0)))
            target_text = f"约{target_wan:g}万字"
            count_text = f"约{stage_count}个阶段"
        else:
            target_text = "目标字数未明确"
            count_text = "阶段总数不要臆造"
        return (
            f"阶段规划口径：{target_text}；按每阶段约5万字划分，{count_text}。"
            "阶段只是供后续章节规划使用的宏观路线，不是逐章计划。"
            "每个阶段只写阶段名、覆盖范围、阶段目标和约3至5个高层转折；"
            "每个转折用一两句话说明即可，不写场景过程、对白、调查步骤、爽点流水账或章节级动作。"
        )

    def _framework_user_text(self):
        requirements = _clip_context_text(
            self.user_requirements,
            8000,
            keep_tail=True,
            preserve_lines=True,
        )
        fixed_payload = {
            "上一卷交接资料（含卷末最后一章正文）": {},
            "本卷基本信息": deepcopy(self.setup_meta),
            "本卷用户要求": requirements,
            "creative_intent_contract（用户已确认，最高优先级）": deepcopy(self.creative_intent_contract),
            "小说模板": self.template_text,
        }
        fixed_chars = len(json.dumps(fixed_payload, ensure_ascii=False, indent=2))
        handoff_budget = min(
            VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET,
            max(
                12000,
                VOLUME_CONTINUATION_REQUEST_CHAR_BUDGET
                - len(self._analysis_prompt())
                - fixed_chars
                - 256,
            ),
        )
        prompt_handoff = _compact_volume_handoff_for_framework(
            self.volume_handoff,
            handoff_budget,
        )
        payload = {
            "上一卷交接资料（含卷末最后一章正文）": prompt_handoff,
            "本卷基本信息": deepcopy(self.setup_meta),
            "本卷用户要求": requirements,
            "creative_intent_contract（用户已确认，最高优先级）": deepcopy(self.creative_intent_contract),
            "小说模板": self.template_text,
        }
        user_text = json.dumps(payload, ensure_ascii=False, indent=2)
        self.diagnostics["input_chars"] = len(user_text)
        self.diagnostics["input_utf8_bytes"] = len(user_text.encode("utf-8", errors="replace"))
        return user_text

    def _analysis_progress_label(self):
        return "本卷框架"

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        return f"本卷框架生成暂时失败，{wait_seconds} 秒后自动重试 {next_attempt}/{attempts}..."

    def _normalize_framework_result(self, data):
        result = super()._normalize_framework_result(data)
        continuity = _normalize_ai_candidates({
            "characters": self.volume_handoff.get("reusable_characters", []),
            "lore": self.volume_handoff.get("reusable_lore", []),
            "foreshadows": self.volume_handoff.get("reusable_foreshadows", []),
        })
        deferred_keys = set()
        for item in self.volume_handoff.get("deferred_foreshadows", []):
            if not isinstance(item, dict):
                continue
            code = re.sub(r"\s+", "", str(item.get("code", "") or "")).upper()
            name = re.sub(r"[\s《》<>【】\[\]（）()]+", "", str(item.get("name", "") or "")).lower()
            if code:
                deferred_keys.add("code:" + code)
            if name:
                deferred_keys.add("name:" + name)

        filtered_result_foreshadows = []
        for item in result.get("foreshadows", []) if isinstance(result.get("foreshadows", []), list) else []:
            if not isinstance(item, dict):
                continue
            code = re.sub(r"\s+", "", str(item.get("code", "") or "")).upper()
            name = re.sub(r"[\s《》<>【】\[\]（）()]+", "", str(item.get("name", "") or "")).lower()
            if (code and "code:" + code in deferred_keys) or (name and "name:" + name in deferred_keys):
                continue
            filtered_result_foreshadows.append(item)

        continuity_foreshadows = continuity.get("foreshadows", [])
        continuity_foreshadows = continuity_foreshadows if isinstance(continuity_foreshadows, list) else []

        def foreshadow_keys(item):
            item = item if isinstance(item, dict) else {}
            keys = []
            code = re.sub(r"\s+", "", str(item.get("code", "") or "")).upper()
            name = re.sub(
                r"[\s《》<>【】\[\]（）()]+",
                "",
                str(item.get("name", "") or ""),
            ).lower()
            if code:
                keys.append("code:" + code)
            if name:
                keys.append("name:" + name)
            return keys

        continuity_by_key = {}
        for item in continuity_foreshadows:
            if not isinstance(item, dict):
                continue
            for key in foreshadow_keys(item):
                continuity_by_key.setdefault(key, item)

        selected_foreshadows = []
        for item in filtered_result_foreshadows:
            source_item = next(
                (
                    continuity_by_key[key]
                    for key in foreshadow_keys(item)
                    if key in continuity_by_key
                ),
                None,
            )
            if source_item is None:
                selected_foreshadows.append(item)
                continue
            enriched = deepcopy(source_item)
            for key, value in item.items():
                if value not in (None, "", [], {}):
                    enriched[key] = deepcopy(value)
            selected_foreshadows.append(enriched)
        merged = _normalize_ai_candidates({
            "characters": (result.get("characters", []) or []) + continuity.get("characters", []),
            "lore": (result.get("lore", []) or []) + continuity.get("lore", []),
            "foreshadows": selected_foreshadows,
            "project_materials": result.get("project_materials", {}),
        })
        inherited_materials = self.volume_handoff.get("inherited_materials", {})
        inherited_materials = inherited_materials if isinstance(inherited_materials, dict) else {}
        for key in ("bible", "world_rules"):
            inherited = str(inherited_materials.get(key, "") or "").strip()
            current = str(merged.get("project_materials", {}).get(key, "") or "").strip()
            complete, _changed = _merge_text_lines_without_duplicates(
                inherited,
                current,
                prefix="",
            )
            merged.setdefault("project_materials", {})[key] = complete
        result["characters"] = merged.get("characters", [])
        result["lore"] = merged.get("lore", [])
        result["foreshadows"] = merged.get("foreshadows", [])
        result["project_materials"] = merged.get("project_materials", {})
        plan = result.get("chapter_plan", {})
        if not isinstance(plan, dict):
            plan = {}
        plan["chapters"] = []
        result["chapter_plan"] = plan
        return result


class NovelVolumeFrameworkAlignmentWorker(NovelAnalysisWorker):
    """Audit sequel premise/stages without rewriting its characters or lore."""

    result_ready = Signal(dict)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        framework,
        creative_intent_contract=None,
        user_requirements="",
        proxy_url="",
        proxy_mode="不使用代理",
    ):
        self.framework = deepcopy(framework if isinstance(framework, dict) else {})
        self.creative_intent_contract = _normalize_creative_intent_contract(
            creative_intent_contract
        )
        self.user_requirements = str(user_requirements or "").strip()
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self._retry_stream_transport_before_nonstream = True

    def _analysis_prompt(self):
        return (
            "你是本卷框架的主线对齐编辑。只检查并必要时改写meta.premise和chapter_plan.summary/stages，"
            "确保它们执行用户已确认的creative_intent_contract。必须只输出一个合法JSON对象，不要Markdown、解释或注释。\n"
            "primary_line必须是真正的本卷主导线；辅助线只能推动主线中的人物选择、关系变化和情绪后果，"
            "不能把商业、项目、调查、旧案或专业流程另立为主线。每个阶段都要让主导线抵达新的关系/人物状态，"
            "不要重复同一阶段结论，不要在中途写下一卷或卷末收束。轻办案只能服务主线，不能放大为办案流程。\n"
            "只返回修正后的meta.premise和chapter_plan；characters、lore、foreshadows、project_materials不在本次修改范围，"
            "不要返回这些字段。不要补写逐章提纲。\n"
            '{"meta":{"premise":""},"chapter_plan":{"summary":"",'
            '"stages":[{"id":"","name":"","start_chapter":0,"end_chapter":0,"events":[{"order":1,"text":""}]}],"chapters":[]}}'
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        payload = {
            "creative_intent_contract": self.creative_intent_contract,
            "用户原始要求": _clip_context_text(
                self.user_requirements, 6000, keep_tail=True, preserve_lines=True
            ),
            "待对齐框架": {
                "meta": deepcopy(self.framework.get("meta", {}))
                if isinstance(self.framework.get("meta", {}), dict) else {},
                "chapter_plan": deepcopy(self.framework.get("chapter_plan", {}))
                if isinstance(self.framework.get("chapter_plan", {}), dict) else {},
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _normalize_alignment(self, data):
        data = data if isinstance(data, dict) else {}
        nested = data.get("framework_alignment", data.get("alignment", data))
        nested = nested if isinstance(nested, dict) else {}
        meta = nested.get("meta", {}) if isinstance(nested.get("meta", {}), dict) else {}
        plan = nested.get("chapter_plan", {})
        if not isinstance(plan, dict):
            plan = {}
        result = {
            "meta": {"premise": str(meta.get("premise", "") or "").strip()},
            "chapter_plan": deepcopy(plan),
        }
        if not result["meta"]["premise"] and not result["chapter_plan"]:
            raise ValueError("AI没有返回可用的框架对齐结果。")
        result["chapter_plan"].setdefault("chapters", [])
        return result

    def run(self):
        started = self._start_analysis_diagnostics()
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            self.progress.emit("正在检查本卷框架是否执行创作主线...")
            response_format_supported, _stream_supported = self._analysis_request_capabilities()
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._analysis_prompt(), self._chunk_user_text("", 1, 1),
                1, 1, response_format_supported,
            )
            if self._stop_requested or self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("stopped", started)
                return
            result = self._normalize_alignment(parsed)
            self._finalize_analysis_diagnostics("success", started)
            self.result_ready.emit(result)
        except Exception as exc:
            if not self._stop_requested and not self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("error", started, exc)
                self.failed.emit(str(exc))
            else:
                self._finalize_analysis_diagnostics("stopped", started)
        finally:
            self._close_active_network_handles()


class NovelForeshadowReviewWorker(NovelAnalysisWorker):
    def __init__(
        self,
        base_url,
        api_key,
        model,
        dossier,
        proxy_url="",
        proxy_mode="不使用代理",
        max_concurrency=3,
        chunks=None,
    ):
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=max_concurrency,
            chunks=chunks,
            dossier=dossier,
        )

    def _analysis_prompt(self):
        return (
            "你是长篇小说伏笔观察编辑。请只阅读当前章节完整正文，提取本章出现的伏笔线索、推进、解释、兑现或作废证据，供后续按章比对使用。\n"
            "你必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释，不要尾随逗号。\n"
            "本阶段不要查看、引用或匹配现有伏笔列表；不要判断某条观察对应旧伏笔的最终状态。\n"
            "只根据当前章节正文判断，不要引用摘要、关键事实或未提供的其它章节内容。\n"
            "质量优先：不要凭关键词猜测；短期悬念、单章内已经完成的小钩子可以记录为“短期/已完成”，但要写清不确定性，交给后续按章比对决定是否忽略。\n"
            "提取原则：\n"
            "1. 记录可能影响后续章节的线索、异常、承诺、谜题、未解释信息、人物隐瞒、规则限制、物品去向。\n"
            "2. 记录本章对旧线索的明确解释、兑现、揭晓、作废证据；只要正文里有证据就记录，不要因为不知道旧伏笔名而丢弃。\n"
            "3. name 使用本章正文里的短线索名或概括名，不要求等同旧伏笔名；description 写完整证据和上下文。\n"
            "4. status 只能在正文证据非常明确时写“已埋”“已回收”“无需回收”“废弃”，不确定时留空。\n"
            "5. setup_chapter/payoff_chapter 必须用真实章节标题，不要写“本章/本片段/第几块”。\n"
            "输出结构：{\n"
            '  "foreshadows": [{"name":"","status":"","setup_chapter":"","payoff_chapter":"","description":"","review_action":"","merge_target":"","review_reason":"","evidence":""}]\n'
            "}\n"
            "字段说明：review_action 固定写“观察待比对”；review_reason 写一句为什么值得后续比对；evidence 写相关章节标题，可多个。"
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        user_text = (
            f"这是第 {chunk_index}/{total_chunks} 个章节正文块。"
            "请只根据本章完整正文提取伏笔观察记录，不要匹配现有伏笔列表，不要臆测其它章节。"
        )
        return user_text + "\n\n【本章完整正文】\n" + str(chunk_text or "")

    def _merge_analysis_result(self, output, data, source_label=""):
        foreshadow_only = _normalize_ai_candidates(data)
        foreshadow_only["characters"] = []
        foreshadow_only["lore"] = []
        foreshadow_only["project_materials"] = {"bible": "", "world_rules": "", "timeline": "", "summary": ""}
        super()._merge_analysis_result(output, foreshadow_only, source_label=source_label)

    def _source_label_for_record(self, record, index, total):
        title = str(record.get("chapter_title", "") or "").strip() if isinstance(record, dict) else ""
        if title:
            return f"章节：{title}"
        return super()._source_label_for_record(record, index, total)


class NovelForeshadowReviewPostprocessWorker(NovelAnalysisWorker):
    def __init__(
        self,
        base_url,
        api_key,
        model,
        candidates,
        dossier,
        proxy_url="",
        proxy_mode="不使用代理",
        max_concurrency=3,
        chunks=None,
    ):
        self.candidates = _normalize_ai_candidates(candidates)
        chunk_records = deepcopy(chunks) if chunks is not None else self._build_observation_chunks(self.candidates, dossier)
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=max_concurrency,
            chunks=chunk_records,
            dossier=dossier,
        )

    @staticmethod
    def _observation_record(item):
        item = item if isinstance(item, dict) else {}
        record = {
            "name": str(item.get("name", "") or "").strip(),
            "status": str(item.get("status", "") or "").strip(),
            "setup_chapter": str(item.get("setup_chapter", "") or "").strip(),
            "payoff_chapter": str(item.get("payoff_chapter", "") or "").strip(),
            "description": str(item.get("description", "") or "").strip(),
        }
        source_label = str(item.get("_source_label", "") or item.get("source_label", "") or "").strip()
        if source_label:
            record["source_label"] = source_label
        return record

    @classmethod
    def _build_observation_chunks(cls, candidates, dossier="", target_total_chars=30000):
        observations = []
        for item in candidates.get("foreshadows", []) if isinstance(candidates, dict) else []:
            record = cls._observation_record(item)
            if record.get("name") and record.get("description"):
                observations.append(record)
        if not observations:
            return []
        dossier_len = len(str(dossier or ""))
        target_chars = max(5000, min(12000, int(target_total_chars or 30000) - dossier_len))
        max_chars = max(target_chars + 2000, 6500)
        groups = []
        current = []
        current_chars = 0
        for record in observations:
            record_text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            record_chars = len(record_text)
            if current and current_chars + record_chars > target_chars:
                groups.append(current)
                current = []
                current_chars = 0
            current.append(record)
            current_chars += record_chars
            if current_chars >= max_chars:
                groups.append(current)
                current = []
                current_chars = 0
        if current:
            groups.append(current)
        total = len(groups)
        return [
            {
                "text": json.dumps(group, ensure_ascii=False, indent=2),
                "index": index,
                "total": total,
                "review_flow": "foreshadow_review_chapter_compare",
            }
            for index, group in enumerate(groups, 1)
        ]

    def _analysis_prompt(self):
        return (
            "你是长篇小说伏笔连续性总编辑。请把当前章节或当前小批次的伏笔观察记录与现有伏笔列表做按章比对，生成需要用户确认的伏笔更新/清理候选。\n"
            "你必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释，不要尾随逗号。\n"
            "任务：\n"
            "1. 对照【现有伏笔列表】判断观察记录命中了哪个旧伏笔；命中时 name 必须使用旧伏笔规范名称。\n"
            "2. 同一旧伏笔在本批只输出一条候选，description 整合本批观察里最关键的章节依据；不在本批观察中的内容不要臆测。\n"
            "3. 状态不能倒退：已回收/无需回收/废弃不要改回已埋或未埋；已埋不要改回未埋。\n"
            "4. 如果观察记录明确解释、揭晓、兑现旧伏笔，status 写“已回收”，payoff_chapter 写最明确的真实章节标题，review_action 写“更新状态”。\n"
            "5. 如果观察记录只是推进但未回收，status 保持“已埋”，review_action 写“补充推进”，description 写清推进章节和推进内容。\n"
            "6. 如果观察记录证明某个旧伏笔只是短期悬念、低价值道具、一次性催化线，或不需要继续牵引后文，status 写“无需回收”，review_action 写“无需回收”；"
            "如果旧伏笔已与正文冲突、明确作废或应清理，status 写“废弃”，review_action 写“移出伏笔”。\n"
            "7. 多条旧伏笔明显重复时，输出需要合并的旧伏笔名，merge_target 写规范名称，并在 description 中写“别称：规范名称”。\n"
            "8. 观察记录里确有长期价值但现有列表缺漏的线索，可以作为新增伏笔候选输出；不确定时不要新增。\n"
            "9. 如果能识别旧伏笔，请优先填写 target_code/命中编号（例如 F0007）；无法确定编号时再用 merge_target。\n"
            "JSON 结构：{\n"
            '  "foreshadows": [{"name":"","status":"","setup_chapter":"","payoff_chapter":"","description":"","review_action":"","merge_target":"","target_code":"","review_reason":"","evidence":""}]\n'
            "}\n"
            "只输出需要用户确认处理的伏笔；没有变化的伏笔不要输出。"
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        try:
            observations = json.loads(str(chunk_text or "[]"))
        except Exception:
            observations = str(chunk_text or "")
        payload = {
            "已有项目档案": self.dossier,
            "本批逐章伏笔观察": observations,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _merge_analysis_result(self, output, data, source_label=""):
        foreshadow_only = _normalize_ai_candidates(data)
        foreshadow_only["characters"] = []
        foreshadow_only["lore"] = []
        foreshadow_only["project_materials"] = {"bible": "", "world_rules": "", "timeline": "", "summary": ""}
        super()._merge_analysis_result(output, foreshadow_only, source_label=source_label)

    def _source_label_for_record(self, record, index, total):
        record = record if isinstance(record, dict) else {}
        title = str(record.get("chapter_title", "") or record.get("source_label", "") or "").strip()
        if title:
            return f"伏笔按章比对：{title}"
        return f"伏笔按章比对：第 {record.get('index', index)}/{record.get('total', total) or total} 块"

    def run(self):
        if not self.input_chunk_records:
            self.failed.emit("没有可比对的伏笔观察。")
            return
        super().run()


class NovelChapterTitleWorker(NovelAnalysisWorker):
    result_ready = Signal(list)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        project_title,
        genre,
        style,
        chapters,
        proxy_url="",
        proxy_mode="不使用代理",
    ):
        super().__init__(
            base_url,
            api_key,
            model,
            "",
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self.project_title = str(project_title or "").strip()
        self.genre = str(genre or "").strip()
        self.style = str(style or "").strip()
        self.chapters = [deepcopy(chap) for chap in chapters if isinstance(chap, dict)]
        self.retry_attempts = 2
        self._title_context_previous_titles = []

    def _title_prompt(self):
        return (
            "你是长篇小说章节标题编辑。请为拆分后的章节批量生成适合读者阅读的中文章节名。\n"
            "必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释。\n"
            "任务边界：只起标题，不改正文，不补剧情，不总结成大纲。\n"
            "标题要求：优先根据本章正文里最有辨识度的事件、冲突、选择、转折或线索自然起名；简洁、可读，避免剧透后文；"
            "每个标题 5-20 个中文字左右，允许在标题中间使用一个中文逗号，让标题像一句自然短句；"
            "不要使用“本章”“章节”“无题”“续”“上”“下”等占位词；同一批内标题不能重复。\n"
            "不要刻意押韵、对仗、凑四字词、凑文学感，也不要把标题都写成同一种句式或同一种尾词。\n"
            "相邻章节不要使用同一语法模板、同一尾词或同一意象；如果正文适合直白标题，就优先直白准确。\n"
            "如果用户内容提供了 previous_titles，请避免与这些标题同词、同结构、同节奏，尤其不要让跨批次相邻标题像同一模板改词。\n"
            "title 字段只写标题正文，不要带“第几章”和序号。\n"
            '输出结构：{"titles":[{"index":1,"title":"会议室里的选择"}]}\n'
            "titles 数量必须与输入章节数量完全一致，index 必须与输入一致。"
        )

    def _analysis_prompt(self):
        return self._title_prompt()

    def _chapter_excerpt(self, text, edge_chars=500):
        text = re.sub(r"\s+", "\n", str(text or "").strip())
        if len(text) <= edge_chars * 2:
            return text
        return text[:edge_chars].rstrip() + "\n...\n" + text[-edge_chars:].lstrip()

    def _title_batches(self, max_chars=18000, max_count=16):
        items = []
        for index, chap in enumerate(self.chapters, 1):
            text = str(chap.get("text", "") or "").strip()
            if not text:
                continue
            item = {
                "index": index,
                "current_title": str(chap.get("title", "") or f"第 {index} 章").strip(),
                "excerpt": self._chapter_excerpt(text),
            }
            items.append(item)
        batches = []
        current = []
        current_size = 0
        for item in items:
            item_size = len(json.dumps(item, ensure_ascii=False))
            if current and (len(current) >= max_count or current_size + item_size > max_chars):
                batches.append(current)
                current = []
                current_size = 0
            current.append(item)
            current_size += item_size
        if current:
            batches.append(current)
        return batches

    def _user_text_for_batch(self, batch):
        previous_titles = [
            str(title or "").strip()
            for title in getattr(self, "_title_context_previous_titles", [])
            if str(title or "").strip()
        ]
        payload = {
            "作品信息": {
                "书名": self.project_title,
                "类型": self.genre,
                "风格": self.style,
            },
            "previous_titles": previous_titles[-8:],
            "标题差异化要求": [
                "优先让标题来自本章正文独有内容，不要套固定标题模板。",
                "相邻标题不要使用同一结构、同一尾词、同一意象或同一语气。",
                "不要为了统一风格把每章都写成押韵、对仗、同字数或同款文学化标题。",
            ],
            "待命名章节": batch,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return str(chunk_text or "")

    def _parse_json_result(self, content):
        content = str(content or "").strip()
        if content.startswith("```"):
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:].strip()
            elif content.startswith("```"):
                content = content[3:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            preview = content[:240].replace("\n", " ")
            raise ValueError(
                "AI 返回的章节标题不是合法 JSON。"
                f"\n解析位置：第 {e.lineno} 行，第 {e.colno} 列。"
                f"\n返回预览：{preview}"
            )
        if not isinstance(data, dict):
            raise ValueError("AI 返回的章节标题不是 JSON 对象。")
        return data

    def _clean_generated_title(self, value):
        title = str(value or "").strip()
        title = title.strip(" \t\r\n\"'“”‘’《》「」『』【】[]()（）")
        title = re.sub(r"^\s*第\s*[\d一二三四五六七八九十百千万零〇两]+\s*[章节回集卷部]\s*[:：、.\-—]*\s*", "", title)
        title = re.sub(r"^\s*[\d一二三四五六七八九十百千万零〇两]+\s*[、.．]\s*", "", title)
        title = re.sub(r"\s+", "", title)
        title = title.strip(" \t\r\n\"'“”‘’《》「」『』【】[]()（）：:，,。；;、")
        return title.strip()

    def _title_char_count(self, title):
        return len(re.sub(r"\s+", "", str(title or "")))

    def _titles_by_index_from_response(self, data, expected_indices):
        data = data if isinstance(data, dict) else {}
        titles = data.get("titles", [])
        if not isinstance(titles, list):
            raise ValueError("AI 返回缺少 titles 列表。")
        expected = [int(index) for index in expected_indices]
        by_index = {}
        for item in titles:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", 0) or 0)
            except Exception:
                index = 0
            if index not in expected:
                continue
            title = self._clean_generated_title(item.get("title", ""))
            if title:
                by_index[index] = title
        return by_index

    def _normalize_titles_response(self, data, expected_indices):
        expected = [int(index) for index in expected_indices]
        by_index = self._titles_by_index_from_response(data, expected)
        missing = [index for index in expected if not by_index.get(index)]
        if missing:
            raise ValueError("AI 没有为这些章节返回有效标题：" + "、".join(str(index) for index in missing))
        return [by_index[index] for index in expected]

    def _request_title_batch_once(self, batch, label, total):
        response_format_supported, _stream_supported = self._analysis_request_capabilities()
        parsed, _response_format = self._analyze_chunk_with_retries(
            self._title_prompt(),
            self._user_text_for_batch(batch),
            label,
            total,
            response_format_supported,
        )
        return self._titles_by_index_from_response(parsed, [item["index"] for item in batch])

    def _retry_missing_title_items(self, missing_items, label, total):
        if not missing_items:
            return {}
        missing_label = f"{label}.补缺"
        self.progress.emit(f"第 {label}/{total} 批有 {len(missing_items)} 个标题缺失，正在单独重试缺失章节...")
        titles = self._request_title_batch_once(missing_items, missing_label, total)
        missing_indices = [item["index"] for item in missing_items if not titles.get(item["index"])]
        if missing_indices:
            raise ValueError("AI 没有为这些章节返回有效标题：" + "、".join(str(index) for index in missing_indices))
        return titles

    def _request_title_batch_with_retries(self, batch, label, total):
        last_error = None
        for attempt in range(1, 3):
            if self._stop_requested or self.isInterruptionRequested():
                return []
            try:
                titles_by_index = self._request_title_batch_once(batch, label, total)
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                response_format_supported, stream_supported = self._analysis_request_capabilities()
                if stream_supported and ("不是合法 json" in msg or "not valid json" in msg or "jsondecodeerror" in msg):
                    self._set_analysis_stream_supported(False)
                    self.progress.emit(f"第 {label}/{total} 批章节标题返回格式异常，已切换普通请求重试...")
                    try:
                        titles_by_index = self._request_title_batch_once(batch, label, total)
                    except Exception as e2:
                        last_error = e2
                    else:
                        missing_items = [item for item in batch if not titles_by_index.get(item["index"])]
                        titles_by_index.update(self._retry_missing_title_items(missing_items, label, total))
                        return [titles_by_index[item["index"]] for item in batch]
                if attempt < 2:
                    self.progress.emit(f"第 {label}/{total} 批章节标题生成失败，正在自动重试 2/2...")
                    continue
                break
            else:
                missing_items = [item for item in batch if not titles_by_index.get(item["index"])]
                titles_by_index.update(self._retry_missing_title_items(missing_items, label, total))
                return [titles_by_index[item["index"]] for item in batch]
        raise last_error or Exception("章节标题生成失败。")

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not self.chapters:
                raise Exception("没有可命名的拆分章节。")
            batches = self._title_batches()
            if not batches:
                raise Exception("没有可命名的拆分章节。")
            total = len(batches)
            all_titles = []
            for index, batch in enumerate(batches, 1):
                if self._stop_requested or self.isInterruptionRequested():
                    return
                self._title_context_previous_titles = list(all_titles[-8:])
                self.progress.emit(f"正在生成拆分章节标题：{index}/{total}...")
                all_titles.extend(self._request_title_batch_with_retries(batch, index, total))
            if len(all_titles) != len(self.chapters):
                raise Exception(f"章节标题数量不一致：需要 {len(self.chapters)} 个，实际 {len(all_titles)} 个。")
            self.result_ready.emit(all_titles)
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self.failed.emit(str(e))
        finally:
            self._close_active_network_handles()


class NovelWritingWorker(QThread):
    chunk = Signal(str)
    result_ready = Signal(str, str)
    failed = Signal(str)
    progress = Signal(str)
    output_chars = Signal(int)
    _json_transport_fallback_endpoints = set()
    _json_transport_fallback_lock = threading.Lock()

    def __init__(self, base_url, api_key, model, action, context, proxy_url="", proxy_mode="不使用代理"):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.action = str(action or "")
        self.context = str(context or "")
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "不使用代理").strip()
        self._session = requests.Session()
        self._session.trust_env = False
        self._stop_requested = False
        self._response = None
        self.last_response_text = ""
        self.diagnostic_request_id = ""
        self.diagnostic_started_at = 0.0
        context_bytes = self.context.encode("utf-8", errors="replace")
        sent_context_bytes = self.context[:NOVEL_AI_CONTEXT_LIMIT].encode(
            "utf-8", errors="replace"
        )
        self.diagnostics = {
            "action": self.action,
            "model": self.model,
            "context_chars": len(self.context),
            "context_utf8_bytes": len(context_bytes),
            "context_sha256": hashlib.sha256(context_bytes).hexdigest(),
            "sent_context_chars": min(len(self.context), NOVEL_AI_CONTEXT_LIMIT),
            "sent_context_utf8_bytes": len(sent_context_bytes),
            "sent_context_sha256": hashlib.sha256(sent_context_bytes).hexdigest(),
            "context_truncated": len(self.context) > NOVEL_AI_CONTEXT_LIMIT,
            "context_limit": NOVEL_AI_CONTEXT_LIMIT,
            "max_output_tokens": self._max_tokens_for_request(),
            "response_char_limit": self._response_char_limit(),
            "response_char_limit_exceeded": False,
            "ignored_trailing_whitespace_chars": 0,
            "json_response_format_requested": self._uses_json_response_format(),
            "json_response_format_fallback": False,
            "json_response_format_transport_fallback": False,
            "json_response_format_cached_fallback": False,
            "reasoning_effort_requested": "",
            "reasoning_effort_fallback": False,
            "ignored_reasoning_chars": 0,
            "system_prompt_chars": 0,
            "system_prompt_sha256": "",
            "http_status": None,
            "response_headers": {},
            "sse_lines": 0,
            "invalid_sse_json_lines": 0,
            "time_to_headers_ms": 0,
            "time_to_first_piece_ms": 0,
            "finish_reason": "",
            "done_received": False,
            "response_chars": 0,
            "response_sha256": "",
            "outcome": "pending",
            "cancelled_before_headers": False,
        }

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_network_handles()

    def _close_network_handles(self):
        try:
            if self._response is not None:
                self._response.close()
        except Exception:
            pass
        finally:
            self._response = None
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass

    def _proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _post_stream_request_interruptibly(self, url, headers, payload):
        """让中止操作可以脱离厂商迟迟不返回响应头的 requests.post。"""
        result = {}
        finished = threading.Event()
        cancelled = threading.Event()
        session = self._session
        proxies = self._proxies()

        def request():
            response = None
            try:
                response = session.post(
                    url,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=(10, 180),
                    proxies=proxies,
                )
                if cancelled.is_set():
                    try:
                        response.close()
                    except Exception:
                        pass
                else:
                    result["response"] = response
            except Exception as exc:
                if not cancelled.is_set():
                    result["error"] = exc
            finally:
                finished.set()

        request_thread = threading.Thread(
            target=request,
            name="novel-ai-http-request",
            daemon=True,
        )
        self._request_thread = request_thread
        request_thread.start()
        while not finished.wait(0.05):
            if self._stop_requested or self.isInterruptionRequested():
                cancelled.set()
                self.diagnostics["cancelled_before_headers"] = True
                self._close_network_handles()
                self._request_thread = None
                return None
        self._request_thread = None
        if self._stop_requested or self.isInterruptionRequested():
            response = result.pop("response", None)
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
            return None
        error = result.get("error")
        if error is not None:
            raise error
        return result.get("response")

    def _draft_word_target(self):
        if self.action not in {"draft", "style_finalize"}:
            return 0
        match = re.search(r"本次新增正文(?:参考)?目标：\s*约?\s*(\d{1,7})\s*字", self.context)
        if not match:
            match = re.search(r"本章扩写字数：\s*(\d{2,7})\s*字", self.context)
        if not match:
            return 0
        try:
            value = int(match.group(1))
        except Exception:
            return 0
        return value if value > 0 else 0

    def _max_tokens_for_request(self):
        if self.action == "draft" and (
            "【小说正文直写】" in self.context
            or "【剧情执行稿任务】" in self.context
        ):
            target = self._draft_word_target()
            return min(24000, max(10000, target * 2 + 5000)) if target else 16000
        if self.action == "outline":
            return 1200
        if self.action == "summary":
            return 6000
        if self.action == "style_profile":
            return 2800
        if self.action == "style_baseline":
            return 12000
        if self.action in {"style_sheet", "style_sheet_merge"}:
            return 6000
        if self.action == "style_cards":
            return 7000
        if self.action == "style_semantic_vocabulary":
            return 11000
        if self.action in {"style_voice_cards", "style_technique_cards"}:
            return 6500
        if self.action == "style_runtime_voice_pack":
            return 5500
        if self.action == "style_persona":
            return 3200
        if self.action == "style_rules":
            return 4200
        if self.action == "style_finalize":
            target = self._draft_word_target()
            return min(24000, max(7000, target * 2 + 2500)) if target else 16000
        if self.action == "style_audit":
            return 2200
        if self.action == "style_plot_extract":
            return 1800
        if self.action == "memory_finalize":
            return 9000
        if self.action == "memory_reconcile":
            return 4500
        if self.action == "memory_repair":
            if "【状态增量修复补丁】" in self.context:
                return 6000
            return 8000
        if self.action == "logic_repair":
            return 5000
        return 0

    def _response_char_limit(self):
        # Normal ten-chapter boundary updates remain well below this ceiling.
        if self.action == "memory_finalize":
            return 36000
        if self.action == "logic_repair":
            return 12000
        return 0

    def _uses_json_response_format(self):
        return self.action in {"memory_finalize", "memory_reconcile", "memory_repair", "logic_repair"}

    def _reasoning_effort_for_request(self):
        configured_effort = reasoning_effort_for_model(self.model, self.base_url, self.action)
        if configured_effort:
            return configured_effort
        if self.action in {"memory_finalize", "memory_reconcile", "memory_repair", "logic_repair"}:
            return "low"
        return ""

    def _json_transport_fallback_key(self):
        return (
            str(self.base_url or "").strip().rstrip("/").lower(),
            str(self.model or "").strip().lower(),
        )

    def _uses_cached_json_transport_fallback(self):
        key = self._json_transport_fallback_key()
        with self._json_transport_fallback_lock:
            return key in self._json_transport_fallback_endpoints

    def _remember_json_transport_fallback(self):
        key = self._json_transport_fallback_key()
        with self._json_transport_fallback_lock:
            self._json_transport_fallback_endpoints.add(key)

    @staticmethod
    def _json_transport_fallback_error(error):
        text = str(error or "").lower()
        return any(marker in text for marker in (
            "remote end closed connection without response",
            "remotedisconnected",
        ))

    @staticmethod
    def _json_response_format_not_supported(status_code, error_text):
        try:
            status = int(status_code or 0)
        except Exception:
            status = 0
        if status not in {400, 404, 422}:
            return False
        lowered = str(error_text or "").lower()
        return any(marker in lowered for marker in (
            "response_format",
            "json_object",
            "json response",
            "unknown parameter",
            "unsupported parameter",
        ))

    @staticmethod
    def _reasoning_effort_not_supported(status_code, error_text):
        return reasoning_effort_not_supported(status_code, error_text)

    def _stream_finished_normally(self, done_received, finish_reason):
        reason = str(finish_reason or "").strip().lower()
        if reason in {"length", "max_tokens", "token_limit"}:
            return False
        normal_reasons = {"stop", "end_turn", "complete", "completed", "eos", "eos_token"}
        if reason and reason not in normal_reasons:
            return False
        return bool(done_received or reason in normal_reasons)

    def _incomplete_stream_error(self, finish_reason):
        reason = str(finish_reason or "").strip().lower()
        action_label = {
            "draft": "正文",
            "style_profile": "文风画像",
            "style_baseline": "普通写法基准稿",
            "style_sheet": "单元作者写作档案",
            "style_sheet_merge": "合并作者写作档案",
            "style_persona": "作者人格",
            "style_rules": "本章文风执行规则",
            "style_semantic_vocabulary": "原生词语义卡",
            "style_voice_cards": "人物与叙述声纹卡",
            "style_technique_cards": "条件性叙事技法卡",
            "style_runtime_voice_pack": "V4运行时文风总则",
            "style_finalize": "正文终稿补救",
            "style_audit": "文风审校",
            "style_rewrite": "重写正文",
            "style_plot_extract": "剧情事实提取",
            "memory_finalize": "章节状态整理",
            "memory_reconcile": "十章边界语义对账",
            "memory_repair": "章节状态修复",
            "logic_repair": "正文逻辑局部修复",
            "outline": "提纲",
            "summary": "摘要",
            "script_to_novel": "小说正文",
            "novel_to_script": "剧本",
            "novel_to_storyboard": "分镜脚本",
            "script_to_storyboard": "分镜脚本",
        }.get(self.action, "内容")
        if reason in {"length", "max_tokens", "token_limit"}:
            return f"AI 输出达到长度上限，已保留当前预览内容，可点续写{action_label}继续。"
        if reason:
            return f"AI 输出未正常完成（finish_reason={finish_reason}），已保留当前预览内容，可点续写{action_label}继续。"
        reason_text = f" finish_reason={finish_reason}" if finish_reason else ""
        return f"AI 输出未完整结束，已保留当前预览内容，可点续写{action_label}继续。{reason_text}".strip()

    def _draft_ending_looks_complete(self, content):
        text = str(content or "").strip()
        if not text:
            return False
        text = text.rstrip(" \t\r\n\"'”’」』》）)]】")
        if not text:
            return False
        if text[-1] in "。！？!?….":
            return True
        return bool(re.search(r"(?:—{2,}|-{2,}|─{2,})$", text))

    def _initial_progress_text(self):
        return {
            "draft": "正在扩写正文...",
            "style_profile": "正在分析正文样本的文风...",
            "style_baseline": "正在生成普通写法基准稿...",
            "style_sheet": "正在提取带原文证据的作者写法...",
            "style_sheet_merge": "正在合并作者写作档案...",
            "style_persona": "正在生成可长期复用的作者人格...",
            "style_cards": "正在建立功能型原文片段库...",
            "style_semantic_vocabulary": "正在逐词建立原生词语义卡...",
            "style_voice_cards": "正在提炼人物与叙述声纹...",
            "style_technique_cards": "正在分离条件性叙事技法...",
            "style_runtime_voice_pack": "正在整理V4运行时文风总则...",
            "style_rules": "正在生成本章专用文风规则...",
            "style_finalize": "正在执行正文终稿补救...",
            "style_audit": "正在独立审校候选正文的文风...",
            "style_rewrite": "正在按审校结果定向重写正文...",
            "style_plot_extract": "正在提取候选正文的剧情事实...",
            "memory_finalize": "正在独立整理本章摘要和长期状态...",
            "memory_reconcile": "正在执行十章边界语义对账...",
            "memory_repair": "正在修复本章摘要和长篇状态...",
            "logic_repair": "正在按原文证据局部修复正文逻辑...",
            "outline": "正在生成章节提纲...",
            "summary": "正在提炼摘要/关键事实...",
            "script_to_novel": "正在改编为小说正文...",
            "novel_to_script": "正在改编为剧本...",
            "novel_to_storyboard": "正在生成分镜脚本...",
            "script_to_storyboard": "正在生成分镜脚本...",
        }.get(self.action, "正在请求 AI 写作助手...")

    def _editorial_quality_prompt(self):
        fiction_actions = {"draft", "script_to_novel"}
        outline_actions = {"outline"}
        summary_actions = {"summary"}
        adaptation_actions = {"novel_to_script", "novel_to_storyboard", "script_to_storyboard"}
        if self.action not in fiction_actions | outline_actions | summary_actions | adaptation_actions:
            return ""

        common = (
            "\n\n【统一创作与编辑标准】\n"
            "请以成熟的商业小说作者兼责任编辑标准完成本次任务，输出内容要达到可直接交付人工编辑审阅的稳定度。"
            "读起来应自然、连贯、有个人声音；不追求炫技，追求真实推进、人物行为合理、情绪有层次。"
            "信息要通过行动、对话、环境和细节自然出现，少用直接解释。"
            "每个角色都要有不同的说话方式、反应节奏和关注点。"
            "允许局部留白、轻微笨拙和不完全对称的句式，但整体必须成熟。"
            "先依据当前项目的定位写作：题材类型与读者定位（如男频、女频、搞笑、悬疑等）、叙事人称、故事卖点和阅读节奏，"
            "决定本章呈现什么样的冲突、情绪和推进方式。再依据已有样本文风进行仿写：以文风档案中的习惯用词、口语、句式松紧、"
            "对白接法、叙述节奏和情绪落点为仿写目标，尽量复刻它的写法，让当前故事以相近的作者表达方式呈现；"
            "项目资料负责故事定位、人物事实和剧情方向，样本文风负责表达层的落笔方式。"
            "并检查人物、设定、时间线、伏笔、空间关系和因果链是否一致。"
        )
        if self.action in fiction_actions:
            return common + (
                "\n正文写作要求：让人物的欲望、阻力、选择和后果自然形成推进与情绪变化；"
                "需要时用具体动作、环境、感官或生活细节承接场景，不设细节数量配额。"
                "对话要保留人物各自的关注点和潜台词，避免角色互相解释已经知道的事。"
                "不要写摘要式过场、百科式设定说明、空泛金句、重复句式、同义反复或模板化转折词堆叠。"
                "网文阅读感随当前项目定位自然形成；具体落笔优先仿写文风档案中的人物声音、信息差、即时反应、关系变化和节奏起伏。"
                "结尾要来自冲突本身，留下继续读下去的张力。"
                "如果资料提供本章扩写字数，只把它当作节奏和详略参考；优先保证完整小场景、冲突收束和正文质量，"
                "不要为了贴字数截断或省略关键结尾。"
            )
        if self.action in outline_actions:
            return common + (
                "\n提纲要求：输出短提纲，不写正文、不写对白、不写场景描写。"
                "控制在 6-10 条以内，每条 1-2 句；总长度尽量控制在 600-1200 字。"
                "只保留本章核心事件、情绪曲线、角色动机、阻力、小变化、关键细节、冲突收束点和结尾张力。"
                "如果资料里已有正文草稿，只反向整理正文已经发生的内容；不要补写正文没有出现的结尾、下一步计划或伏笔兑现。"
                "不要把资料复述成长篇分析，不要写空泛创作建议。"
            )
        if self.action in summary_actions:
            return common + (
                "\n摘要要求：只提炼已经在正文中发生、后续必须继承的事实。"
                "语言短而明确，不评价、不解释创作意图，不新增正文里没有发生的设定或伏笔。"
                "本章摘要保持简短，只概括核心事件和情绪转折；本章需继承的关键事实写成连续性备忘录，不写剧情复述。"
                "必须保留所有会影响后文续写的变化，包括人物关系、伤势、物品归属、地点、线索、伏笔状态和情绪关系变化。"
                "章节结尾的时间、天气、地点、人物位置、身体状态、持有物品和未完成动作属于必须继承的信息；"
                "如果正文收尾写明雨停、雨后、天亮、转场、离开、抵达、昏迷、受伤、持有/交出物品等状态，必须写入关键事实。"
                "同一件事的背景、判断、结果尽量合并成一条完整事实；删掉过程描写、氛围描述、重复解释和创作建议。"
                "不设固定条数，不因为压缩删除重要事实；目标是事实完整、表达短。"
            )
        return common + (
            "\n改编要求：保留原内容的核心事件、情绪推进、人物动机、空间关系和因果链；"
            "让不同角色保持可区分的说话方式和反应节奏。"
            "不要写摘要式过场、百科式设定说明、空泛金句或创作建议；输出必须符合当前改编格式。"
        )

    def _action_prompt(self):
        if self.action == "style_baseline":
            return (
                "你是中文小说基准稿改写器。严格保留作者原文的全部人物、事件、信息、顺序、叙事人称和大致篇幅，"
                "只把表达改成没有鲜明个人特征的普通中文小说写法。不得总结、续写、删改剧情或模仿原作者。"
                "只输出完整基准正文，不输出标题、说明、分析或Markdown代码块。"
            )
        if self.action == "style_sheet":
            return (
                "你是作者文风差异分析师。通过比较内容相同的作者原文与普通基准稿，提取作者独有且可跨剧情复用的写作行为。"
                "每条结论必须由作者原文中的逐字证据支持，不得把题材、人物、设定或具体情节当成文风，不得自动美化成通用优秀写法。"
                "必须重点提取作者反复原样使用的词组、句首、句法框架、说话标签、对白停顿和不同功能角色的说话机制，"
                "并写明使用场景、出现层级和不适用边界。"
                "严格按用户指定分类直接输出档案，不输出思考过程、评价或Markdown代码块。"
            )
        if self.action == "style_sheet_merge":
            return (
                "你是作者写作档案合并器。只合并真正等价的结论，保留不同侧重点和最有代表性的逐字证据，"
                "删除空泛、矛盾、重复或与题材绑定的内容。必须输出完整合并档案，不输出分析过程或Markdown代码块。"
            )
        if self.action == "style_persona":
            return (
                "你是作者人格与语言声纹建模编辑。把证据化作者写作档案转成模型可以长期扮演的第二人称写作人格，"
                "必须保留分层习惯词、句式框架、对白停顿、语气词、说话标签和功能角色说话方式，"
                "忠实保留作者真实习惯，不添加通用商业写作规则，不提分析过程、样本和证据。只输出人格正文。"
            )
        if self.action == "style_cards":
            return (
                "你是作者原文功能片段建档员。只能从用户提供的作者完整原文中逐字连续截取片段，"
                "不得改写、拼接、纠错、补字或把档案概括伪装成原文。"
                "每张片段卡必须完整展示一种可迁移写法，并写清适用场景、不适用边界和可观察声纹。"
                "严格输出用户指定的合法JSON，不输出Markdown、分析过程或额外说明。"
            )
        if self.action == "style_semantic_vocabulary":
            return (
                "你是作者原生词语义建档员。只能回答用户上下文列出的词条，每个词恰好一张卡，"
                "不得新增、遗漏、合并、替换词条，也不得把所有词机械归为搞笑、冲突或主角口头禅。"
                "meaning必须还原作者原文中的真实语义和用法，source_evidence必须是含目标词的原文逐字连续片段。"
                "逐项填写说话或视角归属、情绪温度、自然搭配、适用句位与不用边界；现代口语、网络词和粗口均是有效语言材料。"
                "只输出用户指定的合法JSON，不输出Markdown、分析过程或额外说明。"
            )
        if self.action == "style_voice_cards":
            return (
                "你是作者人物与叙述声纹建档员。只建立始终可复用的语言层：贴近角色的旁白、人物口吻、"
                "对白长度、停顿、称呼、语气和接话节奏。不得把公开拆台、围观合唱、身份反转、流程推进、"
                "质问-否认-解释-反驳等剧情组织方式误写成每章常驻声纹。"
                "每项均须以用户提供原文的逐字连续证据支撑，只输出指定合法JSON。"
            )
        if self.action == "style_technique_cards":
            return (
                "你是作者条件性叙事技法建档员。只记录在触发条件成立时才可局部使用的剧情组织方法，"
                "并明确普通情绪冲突、私人谈话、关系拉扯、日常推进默认不调用。"
                "技法不能成为章节模板，不能自动制造公开围观、连续拆台、办案核验或来回辩论；"
                "每项必须给出用户原文中的逐字连续证据。只输出指定合法JSON。"
            )
        if self.action == "style_runtime_voice_pack":
            return (
                "你是V4小说文风运行时总则编辑。只把声纹卡整理成常驻语言规则，并把条件性技法明确标记为默认关闭、"
                "触发时才局部借用。不得复述样本剧情、人名、物件或证据，也不得要求每章都有笑点、冲突、公开反转或对白。"
                "普通冲突优先写人物目标、选择、关系变化和直接后果，避免证明链、办案流程和讲道理。只输出总则正文。"
            )
        if self.action == "style_rules":
            return (
                "你是小说文风执行策划。根据作者写作档案、作者人格、原文证据和当前章节资料，"
                "生成只适用于本章的可执行文风规则。规则只能控制同一剧情的表达与组织，不得改变剧情、人物、设定和事件顺序。"
                "不得把参考原文中的角色、物件、设定或原句带入新正文。只输出规则正文，不输出提纲、分析或Markdown代码块。"
            )
        if self.action == "style_profile":
            return (
                "你是小说文风分析师。只分析样本怎样写，不评价剧情，不提出通用写作建议。"
                "必须识别作者真实存在的直白、重复、解释性叙述、短段或长段习惯，不能自动美化成标准商业文风。"
                "分析重复时必须区分关键词强调、对白回环、情绪递进等修辞性重复，与同一事实、规则、因果或结论的重复说明；"
                "不能因为少量强调例句，就推断作者希望所有信息跨段或跨章反复解释。"
                "忽略网页复制、OCR和文档提取造成的异常空格、异形字符、断词、孤立引号及明显标点错误，不得要求仿写这些污染。"
                "严格按用户要求输出可解析JSON，不输出Markdown代码块或额外说明。"
            )
        if self.action == "draft" and "【小说正文直写】" in self.context:
            return (
                "你是长篇小说正文作者。直接写出完整正文，当前章节资料、已发布正文和长期状态是剧情事实边界。"
                "把提纲转化成人物在场景里的行动、反应、对白、关系变化和结果，不要显露提纲、任务清单或审校痕迹。"
                "文风画像、原生词池和原文片段卡是本章唯一的写法标准：优先模仿其中真实可观察的口语、"
                "动作反应、句法松紧、对白停顿、说话标签、接话方式、段落衔接和收束节奏。"
                "不得复制样本的人物、剧情、物件或原句；也不得为了展示文风硬塞口语、笑点、对白、短段或特殊词。"
                "专业流程只保留会直接改变人物选择、关系或结果的部分，避免核验、记录、交接和责任说明堆成办案式流程。"
                "同一事实不要换词重复解释，不要替人物讲道理，不要写报告式推理或机械分镜。"
                "只输出正文，不输出标题、前言、分区标签、审校说明、JSON或Markdown代码块。"
            )
        if self.action == "style_finalize":
            return (
                "你是长篇小说终稿编辑。必须同时校验剧情执行、连续性和样本文风，并直接交付可用终稿。"
                "正文风格样本是唯一写法标准，不得擅自改成模型默认的整齐商业网文、电影分镜、短句强调或动作流。"
                "必须校准样本的习惯词、句首、句式框架、动作与反应词、说话标签和对白声纹；"
                "样本稳定重复的词在适用语境中应原样使用，不得为了词汇丰富强行替换。"
                "结合角色卡语言方式落实不同功能角色的对白长短、停顿、称呼、语气词和接话习惯，不能让所有人物一个腔调。"
                "文风中的关键词强调、对白回环和情绪递进可以保留，但不得把状态资料、既有规则或已经完成的结论反复改写成正文；"
                "同一信息只有出现新证据、新决定或新后果时才能再次展开。"
                "剧情事件、人物、设定、时间线和结尾要求必须完整保留；只修正错误和确有证据的写法偏差。"
                "必须逐段核对时间顺序、因果、代词唯一指向和人物生死、清醒、位置、权限及物件持有状态；"
                "提纲内部互斥时以已发布正文和当前已确认状态为准，不能把两种状态同时写入终稿。"
                "必须严格使用用户上下文指定的输出分区，不输出审校报告、评分、修改说明、Markdown代码块或额外内容。"
            )
        if self.action == "style_audit":
            return (
                "你是独立小说文风审校员。只比较写法，不评价候选剧情是否精彩，不因为题材、人物和事件不同扣分。"
                "必须以正文样本为唯一标准，严格识别候选是否仍使用模型默认的整齐商业网文、电影分镜、短句强调或视觉动作流。"
                "必须专项比较习惯用词、句式框架、说话标签、对白停顿、语气词、称呼和不同功能角色的说话方式，"
                "不能只看段落、句长和对白比例。"
                "忽略样本中的异常空格、异形字符、断词和明显标点错误。绝不能要求候选删除、提前、延后或更换既定剧情事件，"
                "只能要求用更接近样本的方式表达同一剧情；章节结尾也只比较表达和段落组织，不比较具体停在哪个事件。"
                "正常标点、语法规范和剧情题材差异不构成文风问题；最多列5项真正影响整体读感的阻断差异。"
                "严格按用户要求输出可解析JSON；没有明显差异且评分达到80才允许通过，不输出Markdown代码块或额外说明。"
            )
        if self.action == "style_plot_extract":
            return (
                "你是小说剧情事实整理员。把候选正文转换成不带任何原文文风的剧情事实清单。"
                "必须保留事件顺序、人物行为结果、对白传达的关键信息、设定事实、伤势、物品和结尾状态；"
                "删除原文句式、修辞、氛围、节奏、段落和强调方式。用简短编号条目输出，不写分析、评价或改写后的正文。"
            )
        if self.action == "memory_finalize":
            return (
                "你是长篇小说连续性总编辑。最终正文是唯一事实来源；独立逐段检查正文并生成实际提纲、摘要、关键事实和版本2长篇记忆增量，"
                "不得重写正文，不得把原提纲、未来规划、人物秘密或伏笔答案当成已经发生。"
                "生成状态前必须单独审查正文内部的硬逻辑矛盾，尤其是人物位置与清醒状态、物件撤走后再次出现、"
                "开合/损毁/持有人互斥、时间因果和代词歧义；只报告有前后逐字原文直接证明的问题，"
                "不得把文风、剧情选择或现实流程不完整误报为逻辑错误。"
                "必须识别所有会影响后文的命名人物行动、伤势与能力边界、关系变化、物件去向、未决任务、"
                "新线索、证据异常、记录缺失或覆盖、未知来源、责任边界、设施规则、伏笔推进和章节结尾状态。"
                "每项长期事件必须落到真实存储位置；更新旧事实时必须保留仍有效的数量、程度、范围和不确定性。"
                "新增事实的临时引用只能填写在fact_updates各项的key字段，禁止改用temp_id或临时id。"
                "每条operation不是keep的新增、更新、退出或替代事实，都必须至少被一个long_term_events.storage.fact_refs引用；"
                "输出前逐项核对fact_updates，不能让会影响后文的事实脱离对应长期事件。"
                "同时做一次不改写正文的读感诊断：只标出有明确原文位置的重复说明、无结果流程赘述、"
                "机械短碎表达或局部语言冲突。没有明确可替换原文时必须不提出修补；不得把剧情选择、"
                "文风偏好、现实流程不完整或正常留白当成问题。"
                "必须使用用户资料提供的短引用和当前修订号，所有动态更新都附正文逐字证据。"
                "严格输出一个合法JSON对象，不输出Markdown、分析、说明或额外文字。"
                "JSON字符串中出现英文双引号时必须写成\\\"，不能漏掉字符串末尾的英文双引号。"
            )
        if self.action == "memory_reconcile":
            return (
                "你是十章边界的长篇小说状态语义对账编辑。最终正文是唯一事实来源，"
                "调用前的状态快照和原状态增量只是待核对资料。只查找会影响后文的语义错误："
                "把未完成写成完成、把未授权写成已授权、把疑似/未知写成确定、把已发生动作写回尚未发生、"
                "把同一冲突或任务同时写成停止和成功、把新证据批次覆盖旧批次，或把仍有效的精确限制错误退出。"
                "只返回最小纠错补丁，不重写完整状态，不新增人物、设定、伏笔，不补正文没有发生的事件。"
                "事实纠错必须保留原scope和旧事实，状态纠错必须使用目录中的真实ID；没有可靠逐字证据就不要纠正。"
                "如果原状态没有语义错误，返回空corrections。严格只输出一个合法JSON对象，不输出Markdown、分析或额外文字。"
                "JSON字符串中出现英文双引号时必须写成\\\"，不能漏掉字符串末尾的英文双引号。"
            )
        if self.action == "memory_repair":
            return (
                "你是长篇小说章节状态修复器。最终正文是唯一事实来源；只修复实际提纲、摘要、关键事实和版本2长篇记忆增量，"
                "不得重写正文，不得补写正文没有发生的事件，不得改写用户导入的人物身份、长期目标、秘密、语言方式、设定定义或伏笔计划。"
                "必须使用用户资料提供的短引用和当前修订号；所有动态更新必须附带正文逐字证据。"
                "严格输出一个合法JSON对象，不输出Markdown、分析、说明或额外文字。"
                "JSON字符串中出现英文双引号时必须写成\\\"，不能漏掉字符串末尾的英文双引号。"
            )
        if self.action == "logic_repair":
            return (
                "你是小说终稿局部逻辑修复器。只处理用户上下文已经用前后正文逐字证据确认的硬矛盾，"
                "不得重新审稿，不得改写整章，不得调整文风、剧情顺序、人物口吻或其他正确段落。"
                "每个问题只能返回一个覆盖审查证据的最小精确替换；修复内容必须像原正文自然延续，"
                "不得新增解释、流程、总结、伏笔或角色讲道理。严格只输出用户要求的合法JSON对象，"
                "不输出Markdown、分析、完整正文或额外说明。"
            )
        if self.action == "draft" and "【剧情执行稿任务】" in self.context:
            return (
                "你是长篇小说剧情与声纹执行编辑。严格依据当前章节资料完成三项内容：先合并提纲不同字段中的同义任务，"
                "生成按发生顺序排列的唯一剧情拍点；再根据作者人格和功能型原文片段库生成本章声纹执行表；"
                "最后生成一份完整备用正文草稿。"
                "每个拍点必须带来新动作、新信息、新决定、新后果或必要情绪转折，不得把同一场对话、规则、责任边界或人物反应拆成多项。"
                "伤势、能力、证据和连续性事实只作为写作参考，不得为了证明遵守而反复写进对白或旁白。"
                "执行清单必须保留必要的人物行动、因果、物件和证据变化及结尾承接，"
                "使下一次调用无需阅读备用草稿措辞也能从零写作，但不要写成逐句分镜。"
                "不得改变没有冲突的提纲，不得提前未来事件，不得把参考样本中的人物、句子或剧情带入当前小说。"
                "提纲内部出现互斥的人物状态、时间顺序或因果时，必须以已发布正文和当前已确认状态为准，"
                "在后续正文验收与修复阶段处理被舍弃的冲突描述，不能把两种状态同时写入正文。"
                "本章声纹执行表必须逐个区分实际说话人物，并明确普通段落合并与短段边界。"
                "严格使用用户指定的三个分区标题，不输出分析、状态JSON、Markdown代码块或额外内容。"
            )
        if self.action in {"draft", "style_rewrite"} and "【正文风格参考】\n" in self.context:
            return (
                "你是长篇小说正文起草与仿写助手。当前项目资料决定故事事实，完整原样本提供本次仿写的写法来源。"
                "已经确定的人名、时间、地点、关系、物件、编号、人物状态和已发生事件随着当前章节自然延续。"
                "把完整样本中的叙述、对白、情绪和场景组织方式自然转化为当前人物和当前事件，写出可直接进入小说的正文。"
                f"只输出小说正文，并严格使用{NOVEL_PROSE_START_MARKER}和{NOVEL_PROSE_END_MARKER}包住正文；"
                "包络外不得输出‘我会’‘接下来’‘本章将’等规划说明、分析、提纲、执行过程或致读者文字，"
                "包络内也只能是可直接进入小说的正文。"
            )
        prompts = {
            "outline": (
                "你是长篇小说章节策划助手。请基于资料为当前章节生成可直接使用的章节提纲。\n"
                "要求：分成 6-10 个短剧情拍点，每条 1-2 句；"
                "写清本章目标、冲突、转折、情绪变化、结尾钩子；"
                "优先继承资料中的时间线、前文继承摘要、人物目标和关键事实；"
                "如果资料里已有正文草稿，提纲必须只概括正文已经写出来的内容，"
                "不要根据原提纲、后续规划或常规叙事补出正文没有发生的收尾、反转、下一步计划或伏笔兑现；"
                "总长度尽量控制在 600-1200 字，不要写正文、对白或长段场景描写。"
            ),
            "draft": (
                "你是长篇小说正文起草助手。请基于资料扩写当前章节正文草稿。\n"
                "要求：优先参考当前章节提纲，并结合已有正文草稿续写或补强；"
                "如果资料里已有正文草稿，只输出接在草稿末尾的新正文，不要重复、概括或重写已有正文；"
                "如果正文草稿为空，输出完整正文草稿；"
                "看到【续写承接点】时，优先从承接点的最后情绪、动作、场景和悬念自然接上；"
                "必须继承承接点里的时间、天气、地点、人物位置、身体状态、持有物品和未完成动作；"
                "如果上一章写明雨已停、雨后或场景已变化，不要在下一章开头改成仍在下雨或回到旧场景，除非本章提纲明确发生新的天气/场景变化；"
                "严格继承资料中的关键事实、时间线、人物目标、语言风格、伏笔状态和世界规则；"
                "参考【本章相关伏笔】里的已命中伏笔和动态伏笔调度参考，由你判断本章可自然推进、回收或暂不处理的伏笔；"
                "开放伏笔队列不是硬任务，不要为了回收而破坏本章提纲、当前场景和人物动机；后段收束时应优先减少自然可回收的悬置伏笔；"
                "参考【长篇进度 / 节奏】控制本章推进密度，避免开篇过早揭底、中段原地反复、后段新增大坑；"
                "参考【本章写作长度】里的本次新增正文目标安排详略，它是质量优先的参考目标，不是硬性字数要求；"
                "优先保证完整小场景、冲突收束和正文质量，不要为了贴字数截断或省略关键结尾；"
                "多用动作和对话推进，不要写解释性分析。"
                "只输出正文草稿，不输出标题、说明、分析或创作建议。"
            ),
            "summary": (
                "你是长篇小说连续性编辑。请基于当前章节正文提炼本章摘要。\n"
                "要求：章节提纲只作辅助，必须以正文草稿为事实来源；记录已经发生且后续必须继承的事实，"
                "包括人物关系、线索、伏笔、伤势、物品、地点变化和情绪关系变化；不要评价。"
                "本章摘要保持简短，只概括核心事件和情绪转折。"
                "本章需继承的关键事实写成连续性备忘录，不写剧情复述；"
                "同一件事的背景、判断、结果尽量合并成一条完整事实，删掉过程描写、氛围描述、重复解释和创作建议；"
                "章节结尾的时间、天气、地点、人物位置、身体状态、持有物品和未完成动作必须进入关键事实，"
                "尤其是雨停/雨后、天亮/入夜、离开/抵达、受伤/昏迷、物品交接等会影响下一章开头的状态；"
                "不设固定条数，重要连续性事实必须保留，不要为了压缩删掉会影响后文的变化；目标是事实完整、表达短。"
                "请严格输出三段：本章摘要：...；本章需继承的关键事实：...；"
                "本章关联人物：人物A、人物B（只列本章实际出现或被直接推动的人物；优先使用人物卡里的具体姓名，不要只写主角/反派/配角；没有则写无）"
            ),
            "script_to_novel": (
                "你是专业小说改编编辑。请把剧本改编成小说正文。\n"
                "要求：保留剧情、人物关系、关键对白和情绪推进；把场景、动作、对白转为自然叙事；"
                "输出可直接阅读的正文，不要输出说明、分析或创作建议。"
            ),
            "novel_to_script": (
                "你是专业影视剧本改编编辑。请把小说正文改编成可拍摄剧本。\n"
                "要求：按场景组织，写清场景、人物、动作和对白；保留关键剧情和人物动机；"
                "不要输出小说叙述腔、说明、分析或创作建议。"
            ),
            "novel_to_storyboard": (
                "你是专业分镜脚本设计师。请把小说正文改编成分镜脚本。\n"
                "要求：按镜号输出，包含景别、画面、动作、镜头运动、对白/旁白、音效/音乐、时长建议；"
                "保留剧情逻辑和关键情绪，不要输出说明、分析或创作建议。"
            ),
            "script_to_storyboard": (
                "你是专业分镜脚本设计师。请把剧本改编成分镜脚本。\n"
                "要求：按镜号输出，包含景别、画面、动作、镜头运动、对白/旁白、音效/音乐、时长建议；"
                "严格继承原剧本的场景、对白、动作和节奏，不要输出说明、分析或创作建议。"
            ),
        }
        prompt = prompts.get(self.action, prompts["outline"])
        return prompt + self._editorial_quality_prompt()

    def run(self):
        started = time.perf_counter()
        full = ""
        finish_reason = ""
        done_received = False
        first_piece_seen = False
        json_payload_complete = False
        try:
            self.diagnostics.update({
                "started_at": now_str(),
                "outcome": "running",
            })
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not self.context.strip():
                raise Exception("没有可用的章节资料。")

            self.progress.emit(self._initial_progress_text())
            url = api_url(self.base_url, "/v1/chat/completions")
            system_prompt = self._action_prompt()
            sent_context = self.context[:NOVEL_AI_CONTEXT_LIMIT]
            self.diagnostics.update({
                "system_prompt_chars": len(system_prompt),
                "system_prompt_sha256": hashlib.sha256(
                    system_prompt.encode("utf-8", errors="replace")
                ).hexdigest(),
                "sent_context_chars": len(sent_context),
                "sent_context_utf8_bytes": len(sent_context.encode("utf-8", errors="replace")),
                "sent_context_sha256": hashlib.sha256(
                    sent_context.encode("utf-8", errors="replace")
                ).hexdigest(),
            })
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": sent_context},
                ],
                "temperature": (
                    0.30 if self.action == "draft" and "【剧情执行稿任务】" in self.context
                    else 0.20 if self.action in (
                        "style_profile", "style_baseline", "style_sheet", "style_sheet_merge",
                        "style_persona", "style_cards", "style_rules", "style_finalize", "style_audit",
                        "style_semantic_vocabulary", "style_voice_cards", "style_technique_cards",
                        "style_runtime_voice_pack", "style_plot_extract", "style_rewrite", "memory_finalize",
                        "memory_reconcile", "memory_repair", "logic_repair",
                    )
                    else 1.5 if self.action in ("draft", "script_to_novel")
                    else 0.35
                ),
                "stream": True,
            }
            max_tokens = self._max_tokens_for_request()
            self.diagnostics["max_output_tokens"] = max_tokens
            if max_tokens:
                payload["max_tokens"] = max_tokens
            reasoning_effort = self._reasoning_effort_for_request()
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort
                self.diagnostics["reasoning_effort_requested"] = reasoning_effort
            cached_json_fallback = (
                self._uses_json_response_format()
                and self._uses_cached_json_transport_fallback()
            )
            if self._uses_json_response_format() and not cached_json_fallback:
                payload["response_format"] = {"type": "json_object"}
            elif cached_json_fallback:
                self.diagnostics["json_response_format_cached_fallback"] = True
            try:
                r = self._post_stream_request_interruptibly(url, headers, payload)
            except Exception as first_error:
                if (
                    "response_format" in payload
                    and self._json_transport_fallback_error(first_error)
                ):
                    payload.pop("response_format", None)
                    self._remember_json_transport_fallback()
                    self.diagnostics["json_response_format_fallback"] = True
                    self.diagnostics["json_response_format_transport_fallback"] = True
                    self.progress.emit("结构化模式在响应前断开，已切换普通流式 JSON 重试当前步骤...")
                    r = self._post_stream_request_interruptibly(url, headers, payload)
                else:
                    raise
            if r is None:
                self.diagnostics.update({
                    "outcome": "stopped",
                    "finished_at": now_str(),
                })
                self.result_ready.emit(self.action, "")
                return
            if r.status_code >= 400 and "reasoning_effort" in payload:
                first_error = extract_api_error(r)
                if self._reasoning_effort_not_supported(r.status_code, first_error):
                    try:
                        r.close()
                    except Exception:
                        pass
                    payload.pop("reasoning_effort", None)
                    self.diagnostics["reasoning_effort_fallback"] = True
                    self.progress.emit("接口不支持低延迟推理参数，已自动兼容重试当前步骤...")
                    r = self._post_stream_request_interruptibly(url, headers, payload)
                    if r is None:
                        self.diagnostics.update({
                            "outcome": "stopped",
                            "finished_at": now_str(),
                        })
                        self.result_ready.emit(self.action, "")
                        return
                else:
                    raise Exception(f"接口错误 {r.status_code}：{first_error}")
            if r.status_code >= 400 and "response_format" in payload:
                first_error = extract_api_error(r)
                if self._json_response_format_not_supported(r.status_code, first_error):
                    try:
                        r.close()
                    except Exception:
                        pass
                    payload.pop("response_format", None)
                    self.diagnostics["json_response_format_fallback"] = True
                    self.progress.emit("接口不支持结构化 JSON，已自动兼容重试当前步骤...")
                    r = self._post_stream_request_interruptibly(url, headers, payload)
                    if r is None:
                        self.diagnostics.update({
                            "outcome": "stopped",
                            "finished_at": now_str(),
                        })
                        self.result_ready.emit(self.action, "")
                        return
                else:
                    raise Exception(f"接口错误 {r.status_code}：{first_error}")
            self._response = r
            self.diagnostics["http_status"] = int(getattr(r, "status_code", 0) or 0)
            try:
                response_headers = getattr(r, "headers", {}) or {}
                if hasattr(response_headers, "items"):
                    selected_headers = {}
                    for raw_key, raw_value in response_headers.items():
                        key = str(raw_key or "").lower()
                        if key in {
                            "request-id", "x-request-id", "trace-id", "x-correlation-id",
                            "retry-after", "content-type", "server",
                        }:
                            selected_headers[key] = str(raw_value or "")[:500]
                    self.diagnostics["response_headers"] = selected_headers
            except Exception as header_error:
                self.diagnostics["response_headers_error"] = type(header_error).__name__
            self.diagnostics["time_to_headers_ms"] = round((time.perf_counter() - started) * 1000, 1)
            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")

            r.encoding = "utf-8"
            for raw_line in r.iter_lines(decode_unicode=False):
                self.diagnostics["sse_lines"] = int(self.diagnostics.get("sse_lines", 0) or 0) + 1
                if self._stop_requested or self.isInterruptionRequested():
                    break
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("utf-8", errors="replace")
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    done_received = True
                    break
                try:
                    data = json.loads(data_str)
                except Exception:
                    self.diagnostics["invalid_sse_json_lines"] = int(
                        self.diagnostics.get("invalid_sse_json_lines", 0) or 0
                    ) + 1
                    continue
                if isinstance(data.get("error"), dict):
                    raise Exception(data["error"].get("message") or json.dumps(data["error"], ensure_ascii=False))
                if isinstance(data.get("error"), str) and data.get("error"):
                    raise Exception(data.get("error"))
                choices = data.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] or {}
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason") or "")
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning_piece:
                    self.diagnostics["ignored_reasoning_chars"] = int(
                        self.diagnostics.get("ignored_reasoning_chars", 0) or 0
                    ) + len(str(reasoning_piece))
                piece = (
                    delta.get("content")
                    or delta.get("text")
                    or message.get("content")
                    or choice.get("text")
                )
                if piece:
                    piece = str(piece)
                    if json_payload_complete and piece.isspace():
                        self.diagnostics["ignored_trailing_whitespace_chars"] = int(
                            self.diagnostics.get("ignored_trailing_whitespace_chars", 0) or 0
                        ) + len(piece)
                        continue
                    if not first_piece_seen:
                        first_piece_seen = True
                        self.diagnostics["time_to_first_piece_ms"] = round(
                            (time.perf_counter() - started) * 1000, 1
                        )
                    full += piece
                    if self._uses_json_response_format() and not json_payload_complete and "}" in piece:
                        candidate = full.strip()
                        try:
                            json.loads(candidate)
                        except Exception:
                            pass
                        else:
                            json_payload_complete = True
                            ignored = len(full) - len(candidate)
                            if ignored:
                                self.diagnostics["ignored_trailing_whitespace_chars"] = int(
                                    self.diagnostics.get("ignored_trailing_whitespace_chars", 0) or 0
                                ) + ignored
                                full = candidate
                    self.output_chars.emit(len(full))
                    self.last_response_text = full
                    response_char_limit = self._response_char_limit()
                    if response_char_limit and len(full) > response_char_limit:
                        self.diagnostics["response_char_limit_exceeded"] = True
                        raise Exception(
                            "AI 章节状态整理输出异常膨胀"
                            f"（已超过{response_char_limit}字），已中止本次结果。"
                        )
                    if self.action not in {
                        "style_profile", "style_cards", "style_semantic_vocabulary", "style_voice_cards",
                        "style_technique_cards", "style_runtime_voice_pack", "style_finalize", "style_audit",
                        "style_plot_extract", "style_rewrite", "memory_finalize", "memory_reconcile",
                        "memory_repair", "logic_repair",
                    }:
                        self.chunk.emit(piece)

            content = full.strip()
            self.last_response_text = full
            stopped = bool(self._stop_requested or self.isInterruptionRequested())
            if not content:
                if stopped:
                    self.diagnostics.update({
                        "outcome": "stopped",
                        "finish_reason": finish_reason,
                        "done_received": bool(done_received),
                        "response_chars": 0,
                        "response_sha256": "",
                        "finished_at": now_str(),
                    })
                    self.result_ready.emit(self.action, "")
                    return
                reason_text = f" finish_reason={finish_reason}" if finish_reason else ""
                if self.diagnostics.get("http_status") == 200 and (
                    done_received or str(finish_reason or "").strip()
                ):
                    raise Exception(
                        "AI 没有返回有效内容：厂商返回 HTTP 200 并正常结束，但正文为0字。"
                        f"{reason_text}".strip()
                    )
                raise Exception(f"AI 没有返回有效内容。{reason_text}".strip())
            if not stopped and not self._stream_finished_normally(done_received, finish_reason):
                raise Exception(self._incomplete_stream_error(finish_reason))
            validation_text = content
            prose_delivery = None
            if self.action == "draft":
                prose_delivery = _extract_prose_delivery_result(
                    content,
                    require_marker=(
                        "【剧情执行稿任务】" not in self.context
                        and "【小说正文直写】" in self.context
                    ),
                )
                if not prose_delivery.get("ok"):
                    raise Exception(str(prose_delivery.get("error", "AI 正文交付边界不完整。")))
                validation_text = str(prose_delivery.get("text", "") or "").strip()
                self.diagnostics.update({
                    "raw_response_chars": len(content),
                    "delivered_prose_chars": len(validation_text),
                    "prose_delivery_source": str(prose_delivery.get("source", "") or ""),
                    "prose_metadata_stripped": bool(validation_text != content.strip()),
                })
            self.diagnostics.update({
                "outcome": "stopped" if stopped else "success",
                "finish_reason": finish_reason,
                "done_received": bool(done_received),
                "response_chars": len(content),
                "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "finished_at": now_str(),
            })
            if (
                self.action in {"draft", "style_rewrite"}
                and not stopped
                and not self._draft_ending_looks_complete(validation_text)
            ):
                raise Exception("AI 正文似乎还没有写完，已保留当前预览内容，可点续写正文继续。")
            delivered_content = validation_text if self.action == "draft" else content
            self.result_ready.emit(self.action, delivered_content)
        except Exception as e:
            stopped = bool(self._stop_requested or self.isInterruptionRequested())
            self.diagnostics.update({
                "outcome": "stopped" if stopped else "error",
                "finish_reason": finish_reason,
                "done_received": bool(done_received),
                "response_chars": len(str(full or "").strip()),
                "response_sha256": hashlib.sha256(
                    str(full or "").strip().encode("utf-8")
                ).hexdigest() if str(full or "").strip() else "",
                "error_type": type(e).__name__,
                "error": str(e)[:4000],
                "traceback": traceback.format_exc(limit=30),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "finished_at": now_str(),
            })
            if stopped:
                self.result_ready.emit(self.action, "")
            else:
                self.failed.emit(str(e))
        finally:
            self.diagnostics["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            self._close_network_handles()


class EdgeTTSWorker(QThread):
    result_ready = Signal(str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, text, output_path, voice="zh-CN-XiaoxiaoNeural", rate="+0%"):
        super().__init__()
        self.text = str(text or "")
        self.output_path = str(output_path or "")
        self.voice = str(voice or "zh-CN-XiaoxiaoNeural")
        self.rate = str(rate or "+0%")
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass

    def _should_stop(self):
        return bool(self._stop_requested or self.isInterruptionRequested())

    async def _save_audio(self):
        import edge_tts

        communicate = edge_tts.Communicate(self.text, self.voice, rate=self.rate, receive_timeout=10)
        with open(self.output_path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if self._should_stop():
                    return False
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type")
                    data = chunk.get("data")
                else:
                    chunk_type = getattr(chunk, "type", "")
                    data = getattr(chunk, "data", None)
                if chunk_type == "audio" and data:
                    audio_file.write(data)
        return not self._should_stop()

    def _remove_partial_output(self):
        try:
            if self.output_path and os.path.exists(self.output_path):
                os.remove(self.output_path)
        except Exception:
            pass

    def run(self):
        try:
            if not self.text.strip():
                raise Exception("没有可朗读的文本。")
            if not self.output_path:
                raise Exception("没有可用的音频临时路径。")
            self.progress.emit("正在生成 Edge TTS 语音...")
            completed = asyncio.run(self._save_audio())
            if not completed or self._should_stop():
                self._remove_partial_output()
                return
            if not os.path.exists(self.output_path) or os.path.getsize(self.output_path) <= 0:
                raise Exception("Edge TTS 没有生成有效音频。")
            if self._should_stop():
                self._remove_partial_output()
                return
            self.result_ready.emit(self.output_path)
        except ModuleNotFoundError:
            if self._should_stop():
                self._remove_partial_output()
            else:
                self.failed.emit("缺少 edge-tts 依赖，请先安装 edge-tts。")
        except Exception as e:
            if self._should_stop():
                self._remove_partial_output()
            else:
                self.failed.emit(str(e))


class NovelChapterPlanMasterWorker(NovelAnalysisWorker):
    result_ready = Signal(dict)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        project_context,
        target_words,
        average_chapter_words,
        total_chapter_count,
        existing_chapter_count=0,
        proxy_url="",
        proxy_mode="不使用代理",
    ):
        super().__init__(
            base_url,
            api_key,
            model,
            str(project_context or ""),
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self._analysis_stream_only = True
        self._retry_stream_transport_before_nonstream = True
        self.target_words = max(1, int(target_words or 1))
        self.average_chapter_words = max(1, int(average_chapter_words or 3000))
        self.total_chapter_count = max(1, int(total_chapter_count or 1))
        self.existing_chapter_count = max(0, int(existing_chapter_count or 0))
        remaining = max(1, self.total_chapter_count - self.existing_chapter_count)
        self.arc_count = max(1, min(20, (remaining + 24) // 25))

    def _analysis_prompt(self):
        first_chapter = self.existing_chapter_count + 1
        sample_end = min(self.total_chapter_count, first_chapter + 24)
        return (
            "你是长篇小说叙事策略与全书结构规划编辑。先建立项目专属叙事策略画像，再为后续分批规划建立全书阶段地图。\n"
            "必须只输出一个合法JSON对象，不要Markdown、解释、注释或尾随逗号。\n"
            f"目标总字数约{self.target_words}字，单章约{self.average_chapter_words}字，"
            f"全书预计{self.total_chapter_count}章，已有{self.existing_chapter_count}章。\n"
            f"没有用户原始阶段时，把尚未规划的章节划分为约{self.arc_count}个连续剧情阶段。阶段必须"
            f"首尾相接、覆盖到第{self.total_chapter_count}章，不得重叠或留空；第一个阶段必须从第"
            f"{first_chapter}章开始。\n"
            f"arcs必须一次性返回完整阶段数组，最后一个阶段的end_chapter必须等于{self.total_chapter_count}；"
            "严禁只返回第一个阶段或把后续阶段留给下一次回答。如果原框架明确分卷或分阶段，每一卷/阶段都必须"
            "在arcs中独立保留，并按目标总字数和单章字数换算连续章号。\n"
            "规划优先级固定为：已确认creative_intent_contract（若有） > 用户原始框架的具体章段 > 全书分卷/阶段目标 > 通用开局、扩展、收束节奏。"
            "通用节奏只控制冲突强度和收束速度，绝不能改变当前章段写感情、经商、成长、冒险或悬疑的内容方向。\n"
            "如果输入包含creative_intent_contract，它是用户已确认的最高优先级创作意图：primary_line不得被原框架中的辅助线、"
            "上一卷交接权重或AI重新推断的narrative_strategy_profile替换。每个阶段的dominant_line和end_state都必须让"
            "primary_line产生新变化；supporting_lines只能制造推动主线的压力、选择或后果。不要重新生成或改写该契约。\n"
            "先根据项目资料输出narrative_strategy_profile：受众方向和题材世界只是基础，必须判断本项目真正的主线发动机、"
            "读者承诺、情绪方向、节奏原则和低说明性原则。planning_grammar只概括这本小说独有的故事动力：什么会让人物行动、"
            "关系如何发生变化、读者期待怎样积累；它是内部规划依据，不是逐章照抄的句式或通用因果公式。"
            "不得写成公开场合、会议、第三人介入等固定场景顺序；chapter_variation_pool只作可选灵感，"
            "不得列出需要轮换的场景或冲突模块，没有必要时返回空数组。具体项目以用户原框架和已确认意图为准，不按性别套模板。\n"
            "summary写全书走向总览；core_mainline单独写贯穿全书的核心主线；ending_promise写最终结局与"
            "读者承诺如何兑现。全书规划以用户框架和人物关系变化为依据；"
            "每个阶段只需写清原框架阶段、宏观节奏位置、主导剧情线、关系或人物处境的总体走向、"
            "阶段后部才会抵达的关键局面和不能提前改变的故事事实；relationship_goal只描述人物/关系的总体走向，"
            "不能写成申报、核验、会议、材料或其他工作流程目标。不要把阶段拆成逐章待办表，"
            "也不要为了填字段预设每章要完成的动作。不要生成逐章提纲，不要固定安排伏笔编号。主导线必须在整个阶段持续占主位，"
            "不能只在前两三章完成后把剩余章节改写成另一种题材。\n"
            "阅读体验必须服从当前项目确认的题材、风格和受众承诺。轻松、悬疑、感情、成长或其他题材各自用本项目自然的方式"
            "形成节奏、满足感和情绪，不给所有小说套同一种爽点与推进语气；每章只需产生与当前故事相称的有效变化。"
            "项目资料中的制度、商业、专业和案件信息"
            "只是事实参考，只有在它直接改变人物选择或关系结果时才使用，不是章节任务清单。不要把任何辅助线拆成连续办理步骤，"
            "也不要让一章主要由说明、核对、问答或结果确认组成；保留人物行动、冲突和后果，把过程压缩到读者理解所需的最短程度。\n"
            + _CHAPTER_PLAN_STATE_PROGRESSION_GUIDANCE
            + "如果项目资料包含 imported_chapter_plan_reference，阶段边界和阶段顺序必须以其中的"
            "stages及绝对章号为准；stages.events是阶段内有序剧情节点，不是一条节点固定对应一章。"
            "不得合并阶段、调序阶段、提前执行下一阶段，或用新阶段替换用户原始阶段。阶段名称和全部事件共同"
            "决定主导线；稀疏事件之间的扩展章只能深化当前阶段的人物、关系、对抗与结果，不能借空白转入下一阶段。\n"
            'JSON结构：{"summary":"","core_mainline":"","ending_promise":"",'
            '"narrative_strategy_profile":{"version":"1",'
            '"audience_direction":"","genre_world":"","core_reader_promise":"","primary_story_engine":"",'
            '"secondary_story_engine":"","planning_grammar":"","satisfaction_currencies":[],"emotional_resonance_axes":[],'
            '"pacing_strategy":"","low_exposition_strategy":"","chapter_variation_pool":[]},'
            f'"arcs":[{{"name":"","start_chapter":{first_chapter},'
            f'"end_chapter":{sample_end},"macro_phase":"","source_stage":"","dominant_line":"",'
            '"relationship_goal":"","end_state":""}]}。'
            "上面arcs里的单个对象只用于展示字段结构，不代表实际只输出一个阶段；实际JSON必须展开全部阶段。"
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return str(chunk_text or "")

    def _analysis_progress_label(self):
        return "全书阶段规划"

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        return f"全书阶段规划暂时失败，{wait_seconds} 秒后自动进行流式重试 {next_attempt}/{attempts}..."

    def _allow_retry_chunk_split(self):
        return False

    @staticmethod
    def _chapter_number(value):
        if isinstance(value, bool):
            raise ValueError("章号格式无效。")
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value or "").strip()
        match = re.search(r"\d+", text)
        if not match:
            raise ValueError("章号格式无效。")
        return int(match.group(0))

    @staticmethod
    def _first_present(mapping, keys, default=""):
        mapping = mapping if isinstance(mapping, dict) else {}
        for key in keys:
            if key in mapping and mapping.get(key) not in (None, ""):
                return mapping.get(key)
        return default

    def _master_plan_payload(self, data):
        data = data if isinstance(data, dict) else {}
        candidates = [data]
        for key in ("master_plan", "full_book_plan", "chapter_plan", "plan", "全书规划"):
            nested = data.get(key)
            if isinstance(nested, dict):
                merged = deepcopy(data)
                merged.update(nested)
                candidates.append(merged)
        for candidate in candidates:
            for key in ("arcs", "stages", "phases", "阶段规划", "阶段"):
                value = candidate.get(key)
                if isinstance(value, list) and value:
                    normalized = deepcopy(candidate)
                    normalized["arcs"] = value
                    return normalized
        return data

    def _arc_range_summary(self, data):
        data = self._master_plan_payload(data)
        ranges = []
        for item in data.get("arcs", []) if isinstance(data.get("arcs"), list) else []:
            if not isinstance(item, dict):
                continue
            try:
                start = self._chapter_number(self._first_present(
                    item, ("start_chapter", "startChapter", "start", "起始章节", "开始章节"), 0
                ))
                end = self._chapter_number(self._first_present(
                    item, ("end_chapter", "endChapter", "end", "结束章节", "截止章节"), 0
                ))
            except ValueError:
                continue
            ranges.append(f"{start}-{end}")
        return "、".join(ranges) or "未识别到有效阶段范围"

    def _structure_repair_prompt(self):
        return (
            "你是长篇小说规划JSON的结构补正编辑。上一次规划已经完成内容判断，但阶段章号没有完整覆盖全书。\n"
            "必须只输出一个合法JSON对象，不要Markdown、解释、注释或尾随逗号。\n"
            "保留previous_plan中的全书走向、叙事策略、阶段内容和原框架分卷，不要从零改写，不要生成逐章提纲。"
            "只补齐遗漏阶段或修正start_chapter/end_chapter，使arcs首尾相接、不重叠、不留空；第一阶段从"
            f"第{self.existing_chapter_count + 1}章开始，最后阶段必须结束于第{self.total_chapter_count}章。\n"
            "如果project_reference明确分卷或分阶段，必须逐项保留，不能为了修章号而合并或删除。"
            "返回完整对象，必须包含summary、core_mainline、ending_promise、narrative_strategy_profile和完整arcs数组。"
        )

    def _structure_repair_user_text(self, parsed, error):
        compact_reference = {}
        text = str(self.text or "")
        json_start = text.find("{")
        if json_start >= 0:
            try:
                project = json.loads(text[json_start:])
            except Exception:
                project = {}
            if isinstance(project, dict):
                compact_reference = {
                    "target": deepcopy(project.get("target", {})),
                    "meta": deepcopy(project.get("meta", {})),
                    "imported_chapter_plan_reference": deepcopy(
                        project.get("imported_chapter_plan_reference", {})
                    ),
                }
                materials = project.get("project_materials", {})
                if isinstance(materials, dict):
                    compact_reference["project_materials"] = {
                        "bible": str(materials.get("bible", "") or "")[:6000],
                        "world_rules": str(materials.get("world_rules", "") or "")[:4000],
                    }
        payload = {
            "validation_error": str(error or ""),
            "required_range": {
                "start_chapter": self.existing_chapter_count + 1,
                "end_chapter": self.total_chapter_count,
            },
            "project_reference": compact_reference,
            "previous_plan": parsed if isinstance(parsed, dict) else {},
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _normalize_master_plan(self, data):
        data = self._master_plan_payload(data)
        raw_arcs = data.get("arcs", [])
        if not isinstance(raw_arcs, list) or not raw_arcs:
            raise ValueError("AI没有返回全书阶段规划。")
        arcs = []
        for item in raw_arcs:
            if not isinstance(item, dict):
                continue
            try:
                start = self._chapter_number(self._first_present(
                    item, ("start_chapter", "startChapter", "start", "起始章节", "开始章节"), 0
                ))
                end = self._chapter_number(self._first_present(
                    item, ("end_chapter", "endChapter", "end", "结束章节", "截止章节"), 0
                ))
            except Exception:
                continue
            if start <= 0 or end < start:
                continue
            arc = {
                "name": str(self._first_present(
                    item, ("name", "title", "stage_name", "阶段名称", "阶段名"), f"阶段{len(arcs) + 1}"
                )).strip(),
                "start_chapter": start,
                "end_chapter": end,
                "macro_phase": str(item.get("macro_phase", "") or "").strip(),
                "source_stage": str(item.get("source_stage", "") or item.get("name", "") or "").strip(),
                "dominant_line": str(item.get("dominant_line", "") or "").strip(),
                "relationship_goal": str(item.get("relationship_goal", "") or "").strip(),
                "end_state": str(item.get("end_state", "") or "").strip(),
            }
            for key in (
                "supporting_lines", "goal", "main_conflict", "turning_points",
                "reader_payoff", "emotional_arc", "pacing_pattern",
                "exposition_compression", "variation_plan", "investigation_scope",
                "forbidden",
            ):
                value = str(item.get(key, "") or "").strip()
                if value:
                    arc[key] = value
            arcs.append(arc)
        arcs.sort(key=lambda item: item["start_chapter"])
        expected_start = self.existing_chapter_count + 1
        for arc in arcs:
            if arc["start_chapter"] != expected_start:
                raise ValueError(
                    f"全书阶段范围不连续：应从第{expected_start}章开始，"
                    f"实际从第{arc['start_chapter']}章开始。"
                )
            expected_start = arc["end_chapter"] + 1
        if expected_start - 1 != self.total_chapter_count:
            raise ValueError(
                f"全书阶段规划只覆盖到第{expected_start - 1}章，"
                f"没有覆盖到第{self.total_chapter_count}章。"
            )
        strategy = self._first_present(
            data,
            ("narrative_strategy_profile", "strategy_profile", "narrative_profile", "叙事策略画像"),
            {},
        )
        strategy = strategy if isinstance(strategy, dict) else {}
        normalized = {
            "summary": str(data.get("summary", "") or "").strip(),
            "core_mainline": str(data.get("core_mainline", "") or "").strip(),
            "ending_promise": str(data.get("ending_promise", "") or "").strip(),
            "target_words": self.target_words,
            "average_chapter_words": self.average_chapter_words,
            "total_chapter_count": self.total_chapter_count,
            "existing_chapter_count": self.existing_chapter_count,
            "arcs": arcs,
            "narrative_strategy_profile": deepcopy(strategy),
        }
        # Keep an optional model-returned boundary for backward compatibility,
        # but do not create an empty field when the model did not provide one.
        boundary = _clean_chapter_plan_story_boundary(data.get("global_hard_boundaries", ""))
        if boundary:
            normalized["global_hard_boundaries"] = boundary
        return normalized

    def run(self):
        started = time.perf_counter()
        if not float(getattr(self, "diagnostic_started_at", 0.0) or 0.0):
            self.diagnostic_started_at = started
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not self.text.strip():
                raise Exception("没有可用于生成全书阶段规划的项目资料。")
            self.progress.emit("正在生成全书阶段规划...")
            response_format_supported, _stream_supported = self._analysis_request_capabilities()
            parsed, response_format_supported = self._analyze_chunk_with_retries(
                self._analysis_prompt(), self.text, 1, 1, response_format_supported
            )
            if self._stop_requested or self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("stopped", started)
                return
            try:
                normalized = self._normalize_master_plan(parsed)
            except ValueError as first_error:
                self._increment_analysis_diagnostic("structure_repair_count")
                self.diagnostics["first_structure_error"] = str(first_error)[:1000]
                ranges = self._arc_range_summary(parsed)
                self.progress.emit(
                    f"阶段范围需要补正（{ranges}；{first_error}），正在基于首次结果修正一次..."
                )
                parsed, response_format_supported = self._analyze_chunk_with_retries(
                    self._structure_repair_prompt(),
                    self._structure_repair_user_text(parsed, first_error),
                    1,
                    1,
                    response_format_supported,
                )
                if self._stop_requested or self.isInterruptionRequested():
                    self._finalize_analysis_diagnostics("stopped", started)
                    return
                normalized = self._normalize_master_plan(parsed)
            self._finalize_analysis_diagnostics("success", started)
            self.result_ready.emit(normalized)
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("error", started, e)
                self.failed.emit(str(e))
            else:
                self._finalize_analysis_diagnostics("stopped", started)


class NovelChapterPlanWorker(NovelAnalysisWorker):
    result_ready = Signal(dict)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        project_context,
        target_words,
        average_chapter_words,
        chapter_count,
        total_chapter_count=None,
        existing_chapter_count=0,
        proxy_url="",
        proxy_mode="不使用代理",
        batch_number=1,
        total_batches=1,
    ):
        super().__init__(
            base_url,
            api_key,
            model,
            str(project_context or ""),
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self._analysis_stream_only = True
        self._retry_stream_transport_before_nonstream = True
        self.target_words = max(1, int(target_words or 1))
        self.average_chapter_words = max(1, int(average_chapter_words or 3000))
        self.chapter_count = max(1, int(chapter_count or 1))
        self.total_chapter_count = max(1, int(total_chapter_count or self.chapter_count))
        self.existing_chapter_count = max(0, int(existing_chapter_count or 0))
        self.batch_number = max(1, int(batch_number or 1))
        self.total_batches = max(1, int(total_batches or 1))

    def _analysis_prompt(self):
        return (
            "你是长篇小说轻量章节提纲编辑。请根据用户已确认的规划基础，只生成当前批次的逐章提纲。\n"
            "必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释，不要尾随逗号。\n"
            "规划目标：严格执行用户已确认的全书走向、叙事策略画像和阶段规划，但给正文扩写保留场景、节奏、对白与转折的发挥空间。\n"
            f"目标总字数约 {self.target_words} 字，单章目标约 {self.average_chapter_words} 字，"
            f"全书预计约 {self.total_chapter_count} 章，已有 {self.existing_chapter_count} 章，"
            f"本次是第 {self.batch_number}/{self.total_batches} 批，必须输出接下来的 {self.chapter_count} 章。\n"
            "每章应把人物、关系、处境或主线推进到一个读者可感知的新局面，避免重复水章节；"
            "不要提前回收后期伏笔，不要擅自推翻小说圣经和世界规则。\n"
            "不要按伏笔编号、旧伏笔列表或现有早期伏笔为章节固定安排埋设、推进或回收；"
            "伏笔由后续扩写正文和正文分析根据实际内容动态处理。若需要悬念，只写自然剧情信息变化，不写固定伏笔任务。\n"
            "规划优先级固定为：已确认creative_intent_contract（若有） > 用户原始框架的具体章段 > 全书阶段总规划 > 前 10%/中间 70%/后 20%的宏观节奏。"
            "宏观节奏只控制冲突强度、信息释放和收束速度，不能决定本章写什么题材内容，更不能在百分比边界处"
            "擅自从感情、日常、经商或成长切换到调查主线。\n"
            "前 10%为强钩子期，中间 70%为扩展期，后 20%为收束期；narrative_stage只记录宏观位置，不能成为固定章法。"
            "source_stage必须记录当前用户原始章段，dominant_line必须记录本章真正的主导剧情线。"
            "每章的内容方向必须服从source_stage和全书阶段总规划。\n"
            "输入中的narrative_strategy_profile和master_plan均为用户已确认的只读规划基础。不得重新生成、改写、"
            "总结或返回它们；不得另建全书阶段、调整阶段边界或重复输出全书摘要。不同题材必须采用不同的冲突入口、"
            "状态变化与兑现方式。"
            "输入中的creative_intent_contract同样只读且优先级最高；每章主导线必须服务primary_line，辅助线不得连续扩张成独立主线。"
            "让本章自然形成符合当前题材的阅读期待即可；不要把某一种网文节奏或爽点当成所有小说的统一标准。"
            "项目资料是连续性事实参考，不是本章待办清单；只在当下人物选择或关系结果确实需要时取用最少内容。"
            + _CHAPTER_PLAN_STATE_PROGRESSION_GUIDANCE
            + "提纲正文应讲述人物真正会经历的故事，不安排任何固定的工作步骤或说明流程；外部事务只在故事自然需要时出现。\n"
            "title 只写章节名，不要带“第几章”和序号；target_words 写数字字符串。\n"
            "outline是提纲里的故事正文。先理解meta中的题材、风格和叙事人称，再像这本小说的作者在讲述下一章那样，"
            "用不超过300个字符（含标点、不计空白）的一段自然、有题材气质的叙述，写出人物会遇到什么、在意什么以及事情会怎样变化。轻松故事可以有人物视角下的"
            "荒诞、误会、反差和调侃；悬疑、感情、成长等故事则顺着各自的情绪与阅读感来写。"
            "narrative_stage、source_stage、dominant_line和ending_hook负责规划边界，outline只需把这些边界化成故事，"
            "不要复述字段含义，也不要沿用‘目标、关系建立、完成推进、形成新局面’一类策划说明口吻。"
            "提纲仍给正文留下场景、对白和节奏空间，不必按处境、阻力、选择、后果的固定次序组织句子。\n"
            "narrative_stage 只能从“强钩子阶段”“主线扩展阶段”“收束升级阶段”中选择。\n"
            "如果项目资料包含 imported_chapter_plan_reference：chapters是明确章节级约束，必须按绝对章号执行；"
            "stages.events是阶段内有序剧情节点，不得把事件序号当作章号。每章用source_event_ids列出承载的节点ID；"
            "一章可以承载多个连续节点，扩展章可以用空数组，但每个节点只能使用一次、必须在所属阶段内并保持顺序，"
            "阶段结束前必须全部覆盖。凡引用节点，outline必须清楚落实对应事件的语义，可以自然改写，不要机械逐字粘贴。"
            "阶段结局和最终关系状态应放在阶段后部兑现；扩展章只能深化当前阶段，不能提前执行下一阶段事件、结论或场景。\n"
            "characters只记录本章自然涉及的主要人物，没有则用空数组；它是索引，不是强制出场清单。\n"
            'JSON 结构：{"chapters":[{"index":1,"title":"","target_words":"3000",'
            '"narrative_stage":"","source_stage":"","dominant_line":"","source_event_ids":[],"outline":"",'
            '"characters":[],"ending_hook":""}]}\n'
            "chapters 数量必须严格等于请求章节数，index 从 1 连续递增。"
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return str(chunk_text or "")

    def _analysis_progress_label(self):
        return "章节规划"

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        return f"章节规划暂时失败，{wait_seconds} 秒后自动进行流式重试 {next_attempt}/{attempts}..."

    def _allow_retry_chunk_split(self):
        return False

    def _clean_title(self, value, fallback):
        title = str(value or "").strip()
        title = title.strip(" \t\r\n\"'“”‘’《》「」『』【】[]()（）")
        title = re.sub(r"^\s*第\s*[\d一二三四五六七八九十百千万零〇两]+\s*[章节回集卷部]\s*[:：、.\-—]*\s*", "", title)
        title = re.sub(r"^\s*[\d一二三四五六七八九十百千万零〇两]+\s*[、.．]\s*", "", title)
        title = re.sub(r"\s+", "", title)
        title = title.strip(" \t\r\n\"'“”‘’《》「」『』【】[]()（）：:，,。；;、")
        return title or fallback

    def _string_list(self, value):
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item or "").strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [item.strip() for item in re.split(r"[、,，;\n；]+", text) if item.strip()]

    def _target_words_text(self, value):
        match = re.search(r"\d{2,7}", str(value or ""))
        if match:
            return match.group(0)
        return str(self.average_chapter_words)

    def _stage_for_index(self, index):
        try:
            index = int(index or 1)
        except Exception:
            index = 1
        absolute_index = max(1, self.existing_chapter_count + index)
        total = max(1, self.total_chapter_count)
        opening_end = max(1, int(total * 0.10 + 0.9999))
        expansion_end = max(opening_end, int(total * 0.80 + 0.9999))
        if absolute_index <= opening_end:
            return "强钩子阶段"
        if absolute_index <= expansion_end:
            return "主线扩展阶段"
        return "收束升级阶段"

    def _normalize_stage_text(self, value, index):
        text = str(value or "").strip()
        if "强钩子" in text or "开局" in text:
            return "强钩子阶段"
        if "收束" in text or "升级" in text or "高潮" in text:
            return "收束升级阶段"
        if "扩展" in text or "主线" in text or "中段" in text:
            return "主线扩展阶段"
        return self._stage_for_index(index)

    def _outline_from_item(self, item):
        item = item if isinstance(item, dict) else {}
        outline = str(item.get("outline", "") or "").strip()
        if outline:
            return outline
        parts = []
        field_labels = (
            ("本章方向", "goal"),
            ("本章方向", "main_event"),
            ("本章方向", "conflict"),
            ("主导线", "dominant_line"),
            ("原框架阶段", "source_stage"),
            ("结尾悬念", "ending_hook"),
        )
        for label, key in field_labels:
            value = str(item.get(key, "") or "").strip()
            if value:
                parts.append(f"{label}：{value}")
        for label, key in (("出场人物", "characters"),):
            values = self._string_list(item.get(key, []))
            if values:
                parts.append(label + "：\n" + "\n".join(f"- {value}" for value in values))
        return "\n\n".join(parts).strip()

    def _normalize_plan(self, data):
        data = data if isinstance(data, dict) else {}
        chapters = data.get("chapters", [])
        if not isinstance(chapters, list) or not chapters:
            raise ValueError("AI 没有返回章节规划列表。")
        normalized = []
        for fallback_index, item in enumerate(chapters, 1):
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", fallback_index) or fallback_index)
            except Exception:
                index = fallback_index
            raw_title = str(item.get("title", "") or "").strip()
            if _is_framework_scope_title(raw_title):
                raise ValueError(
                    f"AI 返回了范围或分卷标题“{raw_title}”，不能作为第{index}章标题。"
                )
            title = self._clean_title(raw_title, f"章节 {index}")
            outline = self._outline_from_item(item)
            if not outline:
                outline = f"本章目标：推进「{title}」相关剧情。\n\n结尾钩子：为下一章留下明确推进点。"
            narrative_stage = self._normalize_stage_text(item.get("narrative_stage", "") or item.get("stage", "") or item.get("所属阶段", ""), index)
            normalized_item = {
                "index": index,
                "title": title,
                "target_words": self._target_words_text(item.get("target_words", "")),
                "narrative_stage": narrative_stage,
                "source_stage": str(item.get("source_stage", "") or "").strip(),
                "dominant_line": str(item.get("dominant_line", "") or "").strip(),
                "source_event_ids": [
                    value.upper() for value in self._string_list(item.get("source_event_ids", []))
                ],
                "outline": outline,
                "characters": self._string_list(item.get("characters", [])),
                "ending_hook": str(item.get("ending_hook", "") or "").strip(),
            }
            # These legacy fields are optional compatibility data. They are
            # deliberately absent from the planning prompt, but must survive
            # when a model returns them on its own or an older task resumes.
            for key in (
                "relationship_task", "investigation_scope", "chapter_function",
                "conflict_intensity", "setup_ratio", "character_task", "mainline_task",
                "planning_method", "start_state", "must_happen", "forbidden_reveal",
                "satisfaction_payoff", "emotional_resonance", "relationship_change",
                "exposition_compression", "variation_pattern", "foreshadow_task",
                "forbidden", "goal", "main_event", "conflict", "turning_point",
                "emotional_shift",
            ):
                value = str(item.get(key, "") or "").strip()
                if value:
                    normalized_item[key] = value
            for key in ("dynamic_modules", "settings", "foreshadows", "required_events"):
                values = self._string_list(item.get(key, []))
                if values:
                    normalized_item[key] = values
            normalized.append(normalized_item)
        normalized.sort(key=lambda item: item.get("index", 0))
        if not normalized:
            raise ValueError("AI 返回的章节规划为空。")
        if len(normalized) != self.chapter_count:
            raise ValueError(f"章节规划数量不一致：需要{self.chapter_count}章，实际{len(normalized)}章。")
        for index, item in enumerate(normalized, 1):
            item["index"] = index
        return {
            "target_words": self.target_words,
            "average_chapter_words": self.average_chapter_words,
            "chapter_count": self.chapter_count,
            "total_chapter_count": self.total_chapter_count,
            "existing_chapter_count": self.existing_chapter_count,
            "chapters": normalized,
        }

    def run(self):
        started = time.perf_counter()
        if not float(getattr(self, "diagnostic_started_at", 0.0) or 0.0):
            self.diagnostic_started_at = started
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not self.text.strip():
                raise Exception("没有可用于生成章节规划的项目资料。")
            self.progress.emit("正在生成章节规划...")
            response_format_supported, _stream_supported = self._analysis_request_capabilities()
            last_error = None
            for structure_attempt in range(2):
                parsed, response_format_supported = self._analyze_chunk_with_retries(
                    self._analysis_prompt(),
                    self.text,
                    1,
                    1,
                    response_format_supported,
                )
                if self._stop_requested or self.isInterruptionRequested():
                    self._finalize_analysis_diagnostics("stopped", started)
                    return
                try:
                    normalized = self._normalize_plan(parsed)
                    self._finalize_analysis_diagnostics("success", started)
                    self.result_ready.emit(normalized)
                    return
                except ValueError as e:
                    last_error = e
                    if structure_attempt == 0:
                        self._increment_analysis_diagnostic("structure_regeneration_count")
                        self.diagnostics["first_structure_error"] = str(e)[:1000]
                        self.progress.emit("当前批次章节数量或结构不完整，正在自动重做本批一次...")
            raise last_error or ValueError("当前批次章节规划格式不完整。")
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("error", started, e)
                self.failed.emit(str(e))
            else:
                self._finalize_analysis_diagnostics("stopped", started)


class ImageWorker(QThread):
    progress = Signal(str)
    result_ready = Signal(dict)
    failed = Signal(str)
    REQUEST_TIMEOUT = 600
    TOAPIS_TASK_INITIAL_WAIT_SECONDS = 2
    TOAPIS_TASK_POLL_SECONDS = 3
    TOAPIS_TASK_MAX_SECONDS = 600
    TOAPIS_TASK_PROGRESS_HEARTBEAT_SECONDS = 30

    SIZE_MAP = {
        "自动": "auto",
        "4096*4096": "4096x4096",
        "3840*3840（4K）": "3840x3840",
        "3840*2160（横屏4K）": "3840x2160",
        "3840*1920（2:1 4K）": "3840x1920",
        "2160*3840（竖屏4K）": "2160x3840",
        "2880*2880": "2880x2880",
        "2048*2048": "2048x2048",
        "2560*1440": "2560x1440",
        "2048*1024": "2048x1024",
        "1024*1536（竖屏）": "1024x1536",
        "1536*1024（横屏）": "1536x1024",
        "1024*1024": "1024x1024",
    }
    QUALITY_MAP = {"自动": "auto", "低": "low", "中": "medium", "高": "high"}
    TOAPIS_OFFICIAL_SIZE_MAP = {
        "自动": ("1:1", "1k"),
        "4096*4096": ("1:1", "4k"),
        "3840*3840（4K）": ("1:1", "4k"),
        "3840*2160（横屏4K）": ("16:9", "4k"),
        "3840*1920（2:1 4K）": ("2:1", "4k"),
        "2160*3840（竖屏4K）": ("9:16", "4k"),
        "2880*2880": ("1:1", "2k"),
        "2048*2048": ("1:1", "2k"),
        "2560*1440": ("16:9", "2k"),
        "2048*1024": ("2:1", "2k"),
        "1024*1536（竖屏）": ("2:3", "1k"),
        "1536*1024（横屏）": ("3:2", "1k"),
        "1024*1024": ("1:1", "1k"),
    }

    def __init__(self, base_url, api_key, model, size, quality, n, prompt, refs, proxy_url="", upload_optimization="高质量", proxy_mode="仅下载图片"):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.size = size
        self.quality = quality
        self.n = n
        self.prompt = prompt
        self.refs = list(refs or [])
        self.proxy_url = str(proxy_url or "").strip()
        self.upload_optimization = str(upload_optimization or "高质量").strip()
        self.proxy_mode = str(proxy_mode or "仅下载图片").strip()
        self._stop_requested = False
        self._session = requests.Session()
        self._session.trust_env = False
        self._response = None
        self._last_image_api_request = None

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_network_handles()

    def _close_network_handles(self):
        try:
            if self._response is not None:
                self._response.close()
        except Exception:
            pass
        finally:
            self._response = None

        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass
        finally:
            self._session = None

    def _raise_if_stopped(self):
        if self._stop_requested or self.isInterruptionRequested():
            raise Exception("任务已中止")

    def _submit_proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _download_proxies(self):
        if self.proxy_mode in ("仅下载图片", "提交和下载"):
            return requests_proxies(self.proxy_url)
        return None

    def _request(self, method, url, **kwargs):
        """
        图片生成请求必须显式控制代理。
        requests 在 macOS 上可能读取系统代理；这里关闭 trust_env，避免“仅下载图片”
        模式下提交接口仍被系统代理接管。
        """
        self._raise_if_stopped()
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        self._response = self._session.request(method, url, **kwargs)
        self._raise_if_stopped()
        return self._response

    def _set_last_image_api_request(self, method, url, started_at, resp=None, error=None):
        elapsed = None
        if started_at:
            try:
                elapsed = max(0.0, time.monotonic() - started_at)
            except Exception:
                elapsed = None
        status_code = None
        response_text = ""
        if resp is not None:
            status_code = getattr(resp, "status_code", None)
            response_text = safe_response_text(resp)
            if len(response_text) > 1000:
                response_text = response_text[:1000] + "..."
        self._last_image_api_request = {
            "method": str(method or "").upper(),
            "url": str(url or ""),
            "elapsed": elapsed,
            "status_code": status_code,
            "response_text": response_text,
            "error": str(error or ""),
        }

    def _emit_last_image_api_diagnostics(self):
        info = self._last_image_api_request or {}
        if not info:
            return
        method = info.get("method") or "请求"
        url = info.get("url") or "未知接口"
        elapsed = info.get("elapsed")
        elapsed_text = ""
        if isinstance(elapsed, (int, float)):
            elapsed_text = f"，耗时 {elapsed:.1f} 秒"
        status = info.get("status_code")
        status_text = f"，HTTP {status}" if status not in (None, "") else ""
        self.progress.emit(f"接口诊断：{method} {url}{status_text}{elapsed_text}")
        response_text = str(info.get("response_text") or "").strip()
        if response_text:
            self.progress.emit(f"接口返回片段：{response_text}")
        error_text = str(info.get("error") or "").strip()
        if error_text:
            self.progress.emit(f"接口异常：{error_text}")

    def _response_format_not_supported(self, resp):
        if resp is None or resp.status_code != 400:
            return False
        text = safe_response_text(resp).lower()
        return (
            "response_format" in text
            and (
                "not supported" in text
                or "unsupported" in text
                or "unsupportedparamserror" in text
                or "drop_params" in text
                or ("invalid" in text and "url" in text)
            )
        )

    def _post_json_image_request(self, url, headers, payload):
        started_at = time.monotonic()
        try:
            resp = self._request(
                "POST",
                url,
                headers={**headers, "Content-Type": "application/json"},
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
                proxies=self._submit_proxies(),
            )
            self._set_last_image_api_request("POST", url, started_at, resp=resp)
            return resp
        except Exception as e:
            self._set_last_image_api_request("POST", url, started_at, error=e)
            raise

    def _post_multipart_image_request(self, url, headers, data):
        files = []
        opened = []
        temp_paths = []
        try:
            for p in self.refs:
                self._raise_if_stopped()
                upload_path, mime, cleanup, message = prepare_image_upload_file(p, self.upload_optimization)
                if message:
                    self.progress.emit(f"已压缩参考图上传副本：{message}")
                if cleanup:
                    temp_paths.append(upload_path)
                f = open(upload_path, "rb")
                opened.append(f)
                files.append(("image[]", (os.path.basename(upload_path), f, mime)))
            started_at = time.monotonic()
            try:
                resp = self._request(
                    "POST",
                    url,
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=self.REQUEST_TIMEOUT,
                    proxies=self._submit_proxies(),
                )
                self._set_last_image_api_request("POST", url, started_at, resp=resp)
                return resp
            except Exception as e:
                self._set_last_image_api_request("POST", url, started_at, error=e)
                raise
        finally:
            for f in opened:
                try:
                    f.close()
                except Exception:
                    pass
            for path in temp_paths:
                safe_remove_file(path)

    def _post_with_response_format_fallback(self, post_func, payload_or_data):
        first = post_func(payload_or_data)
        if not self._response_format_not_supported(first):
            return first

        try:
            first.close()
        except Exception:
            pass

        retry_payload = dict(payload_or_data)
        current_format = retry_payload.get("response_format")
        if current_format == "url":
            retry_payload["response_format"] = "b64_json"
            self.progress.emit("接口不支持 URL 返回，已自动改用 b64_json 重试...")
            second = post_func(retry_payload)
            if not self._response_format_not_supported(second):
                return second
            try:
                second.close()
            except Exception:
                pass

        retry_payload.pop("response_format", None)
        self.progress.emit("接口不支持 response_format，已自动移除该参数重试...")
        return post_func(retry_payload)

    def _is_toapis_gpt_image_2_official(self):
        model = str(self.model or "").strip().lower()
        base_url = str(self.base_url or "").strip().lower()
        if model not in {"gpt-image-2", "gpt-image-2-vip"}:
            return False
        return "toapis.com" in base_url

    def _toapis_official_size_payload(self):
        size, resolution = self.TOAPIS_OFFICIAL_SIZE_MAP.get(
            str(self.size or "").strip(),
            self.TOAPIS_OFFICIAL_SIZE_MAP["自动"],
        )
        return size, resolution

    def _toapis_upload_reference_image(self, ref, headers, index, total):
        text = str(ref or "").strip()
        if not text:
            return ""
        if text.startswith(("http://", "https://")):
            return text
        if text.lower().startswith("data:image/"):
            raise Exception("官方渠道图生图不支持直接传 base64 图片，请使用本地图片或公网图片 URL。")
        if not os.path.exists(text):
            raise Exception(f"参考图不存在：{text}")

        upload_path, mime, cleanup, message = prepare_image_upload_file(text, self.upload_optimization)
        opened = None
        try:
            if message:
                self.progress.emit(f"已压缩参考图上传副本：{message}")
            self.progress.emit(f"正在上传参考图 {index}/{total}...")
            opened = open(upload_path, "rb")
            files = {
                "file": (
                    os.path.basename(upload_path),
                    opened,
                    mime or mimetypes.guess_type(upload_path or "")[0] or "image/png",
                )
            }
            resp = self._request(
                "POST",
                api_url(self.base_url, "/v1/uploads/images"),
                headers=headers,
                files=files,
                timeout=self.REQUEST_TIMEOUT,
                proxies=self._submit_proxies(),
            )
            if resp.status_code >= 400:
                raise Exception(f"参考图上传失败 {resp.status_code}：{extract_api_error(resp)}")
            data = resp.json()
            try:
                resp.close()
            except Exception:
                pass
            candidates = []
            if isinstance(data, dict):
                candidates.extend([
                    data.get("url"),
                    data.get("image_url"),
                ])
                nested = data.get("data")
                if isinstance(nested, dict):
                    candidates.extend([
                        nested.get("url"),
                        nested.get("image_url"),
                    ])
            for value in candidates:
                value = str(value or "").strip()
                if value.startswith(("http://", "https://")):
                    return value
            raise Exception("参考图已上传，但接口没有返回可用图片 URL。")
        finally:
            try:
                if opened is not None:
                    opened.close()
            except Exception:
                pass
            if cleanup:
                safe_remove_file(upload_path)

    def _toapis_reference_image_urls(self, headers):
        urls = []
        refs = list(self.refs or [])
        if len(refs) > 16:
            raise Exception("官方渠道最多支持 16 张参考图。")
        for index, ref in enumerate(refs, 1):
            self._raise_if_stopped()
            url = self._toapis_upload_reference_image(ref, headers, index, len(refs))
            if url:
                urls.append(url)
        if refs and not urls:
            raise Exception("图生图参考图无效。请使用本地图片或可访问的公网图片 URL。")
        return urls

    def _post_toapis_official_image_task(self, headers):
        size, resolution = self._toapis_official_size_payload()
        payload = {
            "model": self.model,
            "prompt": self.prompt,
            "n": int(self.n),
            "size": size,
            "resolution": resolution,
            "response_format": "url",
        }
        quality = self.QUALITY_MAP.get(self.quality, "auto")
        if quality and quality != "auto":
            payload["quality"] = quality

        if self.refs:
            image_urls = self._toapis_reference_image_urls(headers)
            if image_urls:
                payload["image_urls"] = image_urls

        return self._post_json_image_request(
            api_url(self.base_url, "/v1/images/generations"),
            headers,
            payload,
        )

    def _toapis_task_id(self, data):
        if not isinstance(data, dict):
            return ""
        for key in ("id", "task_id", "taskId"):
            value = str(data.get(key, "") or "").strip()
            if value:
                return value
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ("id", "task_id", "taskId"):
                value = str(nested.get(key, "") or "").strip()
                if value:
                    return value
        return ""

    def _toapis_task_status(self, data):
        if not isinstance(data, dict):
            return ""
        status = str(data.get("status", "") or "").strip().lower()
        if status:
            return status
        nested = data.get("data")
        if isinstance(nested, dict):
            return str(nested.get("status", "") or "").strip().lower()
        return ""

    def _toapis_task_result_items(self, data):
        if not isinstance(data, dict):
            return []
        result = data.get("result")
        if not isinstance(result, dict):
            nested = data.get("data")
            if isinstance(nested, dict):
                result = nested.get("result")
        if isinstance(result, dict):
            items = result.get("data")
            if isinstance(items, list):
                return items
            if isinstance(result.get("url"), str):
                return [result]
        items = data.get("data")
        if isinstance(items, list):
            return items
        return []

    def _toapis_task_error_text(self, data, fallback="图片生成失败"):
        if not isinstance(data, dict):
            return fallback
        candidates = [
            data.get("error"),
            data.get("message"),
            data.get("failed_reason"),
            data.get("failure_reason"),
        ]
        nested = data.get("data")
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("error"),
                nested.get("message"),
                nested.get("failed_reason"),
                nested.get("failure_reason"),
            ])
        for value in candidates:
            if isinstance(value, dict):
                text = value.get("message") or value.get("error") or value.get("code")
            else:
                text = value
            text = str(text or "").strip()
            if text:
                return text
        return fallback

    def _poll_toapis_official_task(self, task_id, headers):
        task_id = str(task_id or "").strip()
        if not task_id:
            raise Exception("官方渠道没有返回任务 ID。")
        self.progress.emit(f"任务已提交：{task_id}")
        deadline = time.monotonic() + self.TOAPIS_TASK_MAX_SECONDS
        first_wait = True
        last_progress_key = None
        last_progress_emit_at = 0
        while True:
            self._raise_if_stopped()
            wait_seconds = self.TOAPIS_TASK_INITIAL_WAIT_SECONDS if first_wait else self.TOAPIS_TASK_POLL_SECONDS
            first_wait = False
            end_wait = time.monotonic() + wait_seconds
            while time.monotonic() < end_wait:
                self._raise_if_stopped()
                time.sleep(min(0.2, max(0.0, end_wait - time.monotonic())))

            resp = self._request(
                "GET",
                api_url(self.base_url, f"/v1/images/generations/{task_id}"),
                headers=headers,
                timeout=self.REQUEST_TIMEOUT,
                proxies=self._submit_proxies(),
            )
            if resp.status_code >= 400:
                raise Exception(f"任务查询失败 {resp.status_code}：{extract_api_error(resp)}")
            data = resp.json()
            try:
                resp.close()
            except Exception:
                pass

            status = self._toapis_task_status(data)
            progress = ""
            if isinstance(data, dict) and data.get("progress") not in (None, ""):
                progress = f" {data.get('progress')}%"
            progress_key = (status or "未知", progress)
            now = time.monotonic()
            if (
                progress_key != last_progress_key
                or now - last_progress_emit_at >= self.TOAPIS_TASK_PROGRESS_HEARTBEAT_SECONDS
            ):
                prefix = "任务状态" if progress_key != last_progress_key else "任务仍在生成中"
                self.progress.emit(f"{prefix}：{status or '未知'}{progress}")
                last_progress_key = progress_key
                last_progress_emit_at = now
            if status in {"completed", "succeeded", "success"}:
                items = self._toapis_task_result_items(data)
                if not items:
                    raise Exception("任务完成，但没有返回图片结果。")
                return items
            if status in {"failed", "cancelled", "canceled", "error"}:
                raise Exception(f"图片生成失败：{self._toapis_task_error_text(data, status)}")
            if time.monotonic() >= deadline:
                raise Exception("图片生成任务超时，请稍后重试或到任务记录中查看。")

    def _is_agnes_image_21_flash(self):
        model = str(self.model or "").strip().lower()
        base_url = str(self.base_url or "").strip().lower()
        return "agnes-image-2.1-flash" in model or "apihub.agnes-ai.com" in base_url

    def _agnes_ref_to_data_uri_or_url(self, ref):
        text = str(ref or "").strip()
        if not text:
            return ""
        if text.startswith(("http://", "https://")):
            return text
        if text.lower().startswith("data:image/") and "base64," in text.lower():
            return text
        if not os.path.exists(text):
            return ""

        upload_path, mime, cleanup, message = prepare_image_upload_file(text, self.upload_optimization)
        try:
            if message:
                self.progress.emit(f"已压缩参考图上传副本：{message}")
            b64 = image_file_to_base64(upload_path)
            mime = mime or mimetypes.guess_type(upload_path or "")[0] or "image/png"
            return f"data:{mime};base64,{b64}"
        finally:
            if cleanup:
                safe_remove_file(upload_path)

    def _post_agnes_image_21_flash_request(self, headers):
        url = api_url(self.base_url, "/v1/images/generations")
        payload = {
            "model": self.model,
            "prompt": self.prompt,
            "size": self.SIZE_MAP.get(self.size, "auto"),
            "extra_body": {"response_format": "url"},
        }

        try:
            count = int(self.n)
            if count > 1:
                payload["n"] = count
        except Exception:
            pass

        if self.refs:
            images = []
            for ref in self.refs:
                value = self._agnes_ref_to_data_uri_or_url(ref)
                if value:
                    images.append(value)
            if not images:
                raise Exception("图生图参考图无效。请使用本地图片、可访问的公网图片 URL，或 Data URI Base64。")
            payload["image"] = images

        first = self._post_json_image_request(url, headers, payload)
        if self.refs and first.status_code in (400, 422):
            try:
                first.close()
            except Exception:
                pass
            retry_payload = dict(payload)
            images = retry_payload.pop("image", None)
            retry_extra = dict(payload.get("extra_body") or {})
            retry_extra["image"] = images
            retry_payload["extra_body"] = retry_extra
            self.progress.emit("接口未接受顶层 image，已自动改用 extra_body.image 重试...")
            return self._post_json_image_request(url, headers, retry_payload)

        return first

    def _save_image_result_item(self, item, idx, total):
        if not isinstance(item, dict):
            return ""

        b64_text = item.get("b64_json")
        if isinstance(b64_text, str) and b64_text.strip():
            return save_base64_to_image(b64_text, ".png")

        url_text = item.get("url")
        if not url_text and isinstance(item.get("image_url"), dict):
            url_text = item.get("image_url", {}).get("url")
        if isinstance(url_text, str):
            url_text = url_text.strip()
        else:
            url_text = ""

        if url_text.lower().startswith("data:image/") and "base64," in url_text.lower():
            return save_base64_to_image(url_text, ".png")

        if url_text.startswith(("http://", "https://")):
            self.progress.emit(f"正在下载图片 {idx}/{total}...")
            self.progress.emit(f"图片下载地址：{url_text}")
            primary_proxies = self._download_proxies()
            try:
                img_resp = self._request("GET", url_text, timeout=self.REQUEST_TIMEOUT, proxies=primary_proxies)
            except Exception as e:
                fallback_proxies = None if primary_proxies else requests_proxies(self.proxy_url)
                if fallback_proxies != primary_proxies:
                    try:
                        self.progress.emit("首次下载失败，正在切换代理策略重试下载...")
                        img_resp = self._request("GET", url_text, timeout=self.REQUEST_TIMEOUT, proxies=fallback_proxies)
                    except Exception as retry_e:
                        raise Exception(
                            f"图片已生成，但下载失败：{retry_e}\n"
                            f"首次错误：{e}\n下载地址：{url_text}\n"
                            f"可复制该地址到浏览器或下载工具重试。"
                        )
                else:
                    raise Exception(f"图片已生成，但下载失败：{e}\n下载地址：{url_text}\n可复制该地址到浏览器或下载工具重试。")
            try:
                img_resp.raise_for_status()
                suffix = image_suffix_from_content_type(img_resp.headers.get("Content-Type"))
                suffix = image_suffix_from_bytes(img_resp.content, suffix)
                return save_bytes_to_image(img_resp.content, suffix)
            except Exception as e:
                raise Exception(f"图片已生成，但保存下载内容失败：{e}\n下载地址：{url_text}\n可复制该地址到浏览器或下载工具重试。")
            finally:
                try:
                    img_resp.close()
                except Exception:
                    pass

        return ""

    def _post_image_request(self, headers):
        if self._is_toapis_gpt_image_2_official():
            return self._post_toapis_official_image_task(headers)

        if self._is_agnes_image_21_flash():
            return self._post_agnes_image_21_flash_request(headers)

        if not self.refs:
            url = api_url(self.base_url, "/v1/images/generations")
            payload = {
                "model": self.model,
                "prompt": self.prompt,
                "n": int(self.n),
                "size": self.SIZE_MAP.get(self.size, "auto"),
                "quality": self.QUALITY_MAP.get(self.quality, "auto"),
                "response_format": "url",
            }
            return self._post_with_response_format_fallback(
                lambda data: self._post_json_image_request(url, headers, data),
                payload,
            )

        url = api_url(self.base_url, "/v1/images/edits")
        data = {
            "model": self.model,
            "prompt": self.prompt,
            "n": str(int(self.n)),
            "size": self.SIZE_MAP.get(self.size, "auto"),
            "quality": self.QUALITY_MAP.get(self.quality, "auto"),
            "response_format": "url",
        }
        return self._post_with_response_format_fallback(
            lambda form_data: self._post_multipart_image_request(url, headers, form_data),
            data,
        )

    def run(self):
        try:
            if not self.base_url or not self.api_key:
                raise Exception("请先在设置中添加并选择厂商。")

            headers = {"Authorization": f"Bearer {self.api_key}"}
            self.progress.emit("正在提交任务...")
            if self._submit_proxies():
                self.progress.emit("提交请求代理：已启用")
            else:
                self.progress.emit("提交请求代理：未启用")

            r = self._post_image_request(headers)
            self._raise_if_stopped()

            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")

            self.progress.emit("正在解析图片结果...")
            resp = r.json()
            try:
                r.close()
            except Exception:
                pass

            images = []
            if self._is_toapis_gpt_image_2_official():
                data_items = self._poll_toapis_official_task(self._toapis_task_id(resp), headers)
            else:
                data_items = resp.get("data", [])
                if not isinstance(data_items, list):
                    data_items = []

            for idx, item in enumerate(data_items, start=1):
                self._raise_if_stopped()
                if not isinstance(item, dict):
                    continue

                saved_path = self._save_image_result_item(item, idx, len(data_items))
                if saved_path:
                    images.append(saved_path)

                try:
                    item["b64_json"] = ""
                    if isinstance(item.get("url"), str) and item.get("url", "").startswith("data:image/"):
                        item["url"] = ""
                except Exception:
                    pass

            try:
                resp.clear()
                data_items.clear()
                del resp
                del data_items
                gc.collect()
            except Exception:
                pass

            if not images:
                raise Exception("接口没有返回图片。请检查中转接口返回格式。")

            self.progress.emit("正在加入图片预览区...")

            self.result_ready.emit({
                "time": now_str(),
                "prompt": self.prompt,
                "refs": list(self.refs or []),
                "images": images,
                "model": self.model,
                "size": self.size,
                "quality": self.quality,
                "n": self.n,
            })
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.failed.emit("任务已中止")
            else:
                self._emit_last_image_api_diagnostics()
                self.failed.emit(str(e))
        finally:
            self._close_network_handles()


class ThumbnailWorker(QThread):
    thumbnail_ready = Signal(str, str)
    finished_path = Signal(str)

    def __init__(self, paths, width=210, height=210):
        super().__init__()
        self.paths = list(paths or [])
        self.width = int(width)
        self.height = int(height)

    def run(self):
        seen = set()
        for path in self.paths:
            if not isinstance(path, str) or path in seen:
                continue
            seen.add(path)
            try:
                cache_path = ensure_thumbnail_cache(path, self.width, self.height)
                if cache_path:
                    self.thumbnail_ready.emit(path, cache_path)
            except Exception:
                pass

        for path in seen:
            try:
                self.finished_path.emit(path)
            except Exception:
                pass


class VideoWorker(QThread):
    progress = Signal(str)
    result_ready = Signal(dict)
    failed = Signal(str)

    DONE_STATUSES = {"completed", "succeeded", "success", "done", "finished"}
    FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "timeout"}
    VIDEO_QUERY_MIN_INTERVAL = 8
    _video_query_lock = threading.Lock()
    _last_video_query_at = 0.0

    def __init__(self, base_url, api_key, model, prompt, width, height, num_frames, frame_rate, image_refs=None, proxy_url="", proxy_mode="仅下载图片"):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.prompt = prompt
        self.width = int(width)
        self.height = int(height)
        self.num_frames = int(num_frames)
        self.frame_rate = int(frame_rate)
        self.image_refs = [str(x).strip() for x in (image_refs or []) if str(x).strip()]
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "仅下载图片").strip()
        self._stop_requested = False
        self._session = requests.Session()
        self._session.trust_env = False
        self._response = None

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_network_handles()

    def _close_network_handles(self):
        try:
            if self._response is not None:
                self._response.close()
        except Exception:
            pass
        finally:
            self._response = None
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass

    def _raise_if_stopped(self):
        if self._stop_requested or self.isInterruptionRequested():
            raise Exception("任务已中止")

    def _sleep_with_stop(self, seconds):
        end_time = time.monotonic() + max(0, float(seconds or 0))
        while True:
            self._raise_if_stopped()
            remaining = end_time - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def _wait_for_video_query_slot(self):
        while True:
            self._raise_if_stopped()
            with VideoWorker._video_query_lock:
                now = time.monotonic()
                wait = VideoWorker._last_video_query_at + VideoWorker.VIDEO_QUERY_MIN_INTERVAL - now
                if wait <= 0:
                    VideoWorker._last_video_query_at = now
                    return
            self._sleep_with_stop(min(wait, 1))

    def _submit_proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _download_proxies(self):
        if self.proxy_mode in ("仅下载图片", "提交和下载"):
            return requests_proxies(self.proxy_url)
        return None

    def _request(self, method, url, **kwargs):
        self._raise_if_stopped()
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        self._response = self._session.request(method, url, **kwargs)
        self._raise_if_stopped()
        return self._response

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _extract_dict(self, data):
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict):
                return inner
            return data
        return {}

    def _extract_video_id(self, data):
        found = []

        def collect(obj):
            if isinstance(obj, dict):
                value = obj.get("video_id")
                if value:
                    found.append(str(value))
                    return
                for key in ("data", "output", "result"):
                    collect(obj.get(key))
            elif isinstance(obj, list):
                for item in obj:
                    collect(item)

        collect(data)
        if found:
            return found[0]
        return ""

    def _extract_status(self, data):
        obj = self._extract_dict(data)
        value = obj.get("status") or obj.get("state")
        return str(value or "").strip().lower()

    def _extract_error(self, data):
        obj = self._extract_dict(data)
        err = obj.get("error") or obj.get("message") or obj.get("fail_reason") or obj.get("reason")
        if isinstance(err, dict):
            return err.get("message") or json.dumps(err, ensure_ascii=False)
        return str(err or "").strip()

    def _extract_video_url(self, data):
        candidates = []

        def collect(obj):
            if isinstance(obj, dict):
                for key in (
                    "video_url",
                    "videoUrl",
                    "url",
                    "output_url",
                    "download_url",
                    "file_url",
                    "media_url",
                    "result_url",
                    "output_video_url",
                    "remixed_from_video_id",
                ):
                    value = obj.get(key)
                    if isinstance(value, str) and value.strip():
                        candidates.append(value.strip())
                for key in ("data", "output", "outputs", "videos", "result"):
                    collect(obj.get(key))
            elif isinstance(obj, list):
                for item in obj:
                    collect(item)
            elif isinstance(obj, str) and obj.strip().startswith(("http://", "https://")):
                candidates.append(obj.strip())

        collect(data)
        for value in candidates:
            if value.startswith(("http://", "https://")):
                return value
        return candidates[0] if candidates else ""

    def _create_task(self):
        payload = {
            "model": self.model,
            "prompt": self.prompt,
            "width": self.width,
            "height": self.height,
            "num_frames": self.num_frames,
            "frame_rate": self.frame_rate,
        }
        images = self._video_image_values()
        if len(images) == 1:
            payload["image"] = images[0]
        elif len(images) > 1:
            payload["extra_body"] = {"image": images}

        r = self._request(
            "POST",
            api_url(self.base_url, "/v1/videos"),
            headers=self._headers(),
            json=payload,
            timeout=(30, 120),
            proxies=self._submit_proxies(),
        )
        try:
            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")
            return r.json()
        finally:
            try:
                r.close()
            except Exception:
                pass

    def _video_image_values(self):
        values = []
        for ref in self.image_refs:
            self._raise_if_stopped()
            if ref.startswith(("http://", "https://")):
                values.append(ref)
                continue

            if os.path.exists(ref):
                mime = mimetypes.guess_type(ref)[0] or ""
                if not mime.startswith("image/"):
                    raise Exception(f"参考文件不是图片：{os.path.basename(ref)}")
                values.append(image_file_to_base64(ref))
                continue

            cleaned = ref
            if cleaned.lower().startswith("data:image/") and "base64," in cleaned.lower():
                cleaned = cleaned.split(",", 1)[1].strip()
            if cleaned:
                values.append(cleaned)
                continue

            raise Exception(f"参考图不存在或格式不支持：{ref}")

        return values

    def _query_video_result(self, video_id):
        url = api_url(self.base_url, "/agnesapi")
        deadline = time.time() + 60 * 30
        interval = 5
        last_status = ""
        last_progress = None
        not_ready_reported = False
        completed_without_url_count = 0

        while time.time() < deadline:
            self._raise_if_stopped()
            self._wait_for_video_query_slot()
            r = self._request(
                "GET",
                url,
                headers=self._headers(),
                params={"video_id": video_id},
                timeout=(10, 60),
                proxies=self._submit_proxies(),
            )
            wait_after_error = 0
            try:
                if r.status_code >= 400:
                    err_text = extract_api_error(r)
                    err_lower = str(err_text).lower()
                    if r.status_code == 400 and "task_not_exist" in err_lower:
                        if not not_ready_reported:
                            self.progress.emit("视频结果暂未就绪，继续查询...")
                            not_ready_reported = True
                        wait_after_error = interval
                    elif r.status_code == 429 or "rate limit" in err_lower:
                        retry_after = 0
                        try:
                            retry_after = int(r.headers.get("Retry-After", "0") or 0)
                        except Exception:
                            retry_after = 0
                        interval = min(60, max(15, interval * 2, retry_after))
                        self.progress.emit(f"视频状态查询触发限流，已降频等待 {interval} 秒...")
                        wait_after_error = interval
                    if not wait_after_error:
                        raise Exception(f"查询视频结果失败 {r.status_code}：{err_text}")
                    data = None
                else:
                    data = r.json()
            finally:
                try:
                    r.close()
                except Exception:
                    pass
            if wait_after_error:
                self._sleep_with_stop(wait_after_error)
                continue

            video_url = self._extract_video_url(data)
            status = self._extract_status(data)
            obj = self._extract_dict(data)
            progress = obj.get("progress") if isinstance(obj, dict) else None
            if status != last_status or progress != last_progress:
                if progress is not None:
                    self.progress.emit(f"视频生成状态：{status or '处理中'}，进度 {progress}%")
                elif status:
                    self.progress.emit(f"视频生成状态：{status}")
                last_status = status
                last_progress = progress

            if video_url and (not status or status in self.DONE_STATUSES):
                return data

            if status in self.DONE_STATUSES:
                completed_without_url_count += 1
                if completed_without_url_count >= 6:
                    keys = []
                    try:
                        obj_keys = list(obj.keys()) if isinstance(obj, dict) else []
                        keys = obj_keys[:12]
                    except Exception:
                        keys = []
                    raise Exception(f"视频已完成，但接口没有返回可下载视频地址。返回字段：{keys}")

            if status in self.FAILED_STATUSES:
                detail = self._extract_error(data)
                raise Exception(detail or f"视频生成失败：{status}")

            self._sleep_with_stop(interval)

        raise Exception("视频结果查询超时。")

    def _download_video(self, video_url):
        if not video_url.startswith(("http://", "https://")):
            raise Exception("接口返回的视频地址不是可下载 URL。")
        self.progress.emit("正在下载视频...")
        r = self._request(
            "GET",
            video_url,
            stream=True,
            timeout=(10, 900),
            proxies=self._download_proxies(),
        )
        try:
            r.raise_for_status()
            day = datetime.now().strftime("%Y-%m-%d")
            video_dir = os.path.join(VIDEO_DIR, day)
            os.makedirs(video_dir, exist_ok=True)
            name = f"{uuid.uuid4().hex}.mp4"
            path = os.path.join(video_dir, name)
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    self._raise_if_stopped()
                    if chunk:
                        f.write(chunk)
            if not os.path.exists(path) or os.path.getsize(path) <= 0:
                safe_remove_file(path)
                raise ValueError("视频文件保存后为空。")
            return path
        finally:
            try:
                r.close()
            except Exception:
                pass

    def run(self):
        try:
            if not self.base_url or not self.api_key:
                raise Exception("请先在设置中添加并选择厂商。")
            if not self.prompt.strip():
                raise Exception("请输入视频提示词。")

            self.progress.emit("正在创建视频任务...")
            created = self._create_task()
            video_id = self._extract_video_id(created)

            if not video_id:
                raise Exception("接口没有返回 video_id，当前已禁用旧 task_id 查询逻辑。")

            self.progress.emit(f"视频生成已提交：{video_id}")
            result = self._query_video_result(video_id)
            video_url = self._extract_video_url(result)

            if not video_url:
                raise Exception("视频生成完成，但接口没有返回 video_url。")

            local_path = self._download_video(video_url)
            self.result_ready.emit({
                "time": now_str(),
                "prompt": self.prompt,
                "model": self.model,
                "width": self.width,
                "height": self.height,
                "num_frames": self.num_frames,
                "frame_rate": self.frame_rate,
                "video_id": video_id,
                "video_url": video_url,
                "video": local_path,
                "image_refs": list(self.image_refs),
            })
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.failed.emit("任务已中止")
            else:
                self.failed.emit(str(e))
        finally:
            self._close_network_handles()
