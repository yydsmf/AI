import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gpt_desktop.workers import (
    BlenderDirectorWorker,
    BlenderStoryboardWorker,
    _is_usable_blender_executable,
    _known_unstable_blender_reason,
    blender_detection_issue,
    resolve_blender_executable,
)


class BlenderStoryboardWorkerTests(unittest.TestCase):
    def test_resolve_blender_executable_accepts_macos_app_bundle(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            exe = Path(tmp) / "Blender.app" / "Contents" / "MacOS" / "Blender"
            exe.parent.mkdir(parents=True)
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(0o755)

            with mock.patch("gpt_desktop.workers._probe_blender_background_startup", return_value=(True, "")):
                self.assertEqual(resolve_blender_executable(str(Path(tmp) / "Blender.app")), str(exe))

    def test_unusable_blender_script_is_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            exe = Path(tmp) / "blender"
            exe.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
            exe.chmod(0o755)

            self.assertFalse(_is_usable_blender_executable(str(exe)))
            self.assertIn("已找到 Blender，但无法启动", blender_detection_issue(str(exe)))

    def test_blender_45_on_old_intel_mac_is_flagged_unstable(self):
        display = "Chipset Model: Intel HD Graphics 6000\nMetal: Supported"
        with mock.patch("gpt_desktop.workers.platform.system", return_value="Darwin"), mock.patch(
            "gpt_desktop.workers.platform.machine", return_value="x86_64"
        ), mock.patch("gpt_desktop.workers._mac_display_summary", return_value=display):
            reason = _known_unstable_blender_reason("Blender 4.5.0")

        self.assertIn("Metal 初始化", reason)
        self.assertIn("Blender 2.93.18 LTS", reason)

    def test_blender_42_on_old_intel_mac_is_flagged_unstable(self):
        display = "Chipset Model: Intel HD Graphics 6000\nMetal: Supported"
        with mock.patch("gpt_desktop.workers.platform.system", return_value="Darwin"), mock.patch(
            "gpt_desktop.workers.platform.machine", return_value="x86_64"
        ), mock.patch("gpt_desktop.workers._mac_display_summary", return_value=display):
            reason = _known_unstable_blender_reason("Blender 4.2.0")

        self.assertIn("Metal 初始化", reason)

    def test_worker_uses_background_blender_and_returns_image(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            worker = BlenderStoryboardWorker("/fake/blender", "会议室里，男主站在门口，低角度中景。", 640, 360)
            captured = {}

            class FakeProcess:
                returncode = 0

                def poll(self):
                    return 0

                def communicate(self, timeout=None):
                    del timeout
                    Path(worker._output_path).write_bytes(b"fake image")
                    return "ok", ""

            def fake_popen(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                captured["script"] = Path(cmd[-1]).read_text(encoding="utf-8")
                return FakeProcess()

            with mock.patch("gpt_desktop.workers.resolve_blender_executable", return_value="/fake/blender"), mock.patch(
                "gpt_desktop.workers._dated_image_dir", return_value=tmp
            ), mock.patch("gpt_desktop.workers.subprocess.Popen", side_effect=fake_popen):
                path = worker._render_storyboard()

            self.assertTrue(os.path.exists(path))
            self.assertIn("--background", captured["cmd"])
            self.assertIn("--factory-startup", captured["cmd"])
            self.assertIn("会议室里", captured["script"])
            self.assertIn("WIDTH = int", captured["script"])

    def test_director_worker_uses_plan_and_returns_image(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            model_path = str(Path(tmp) / "hero.glb")
            Path(model_path).write_bytes(b"fake model")
            plan = {
                "asset_paths": [model_path],
                "scene_prompt": "街道夜景，有路口和灯光。",
                "character_prompt": "主角站在左侧，反派站在右侧。",
                "camera_prompt": "低角度中景，轻微推镜。",
                "render_prompt": "输出分镜参考图。",
            }
            worker = BlenderDirectorWorker("/fake/blender", plan, 640, 360)
            captured = {}

            class FakeProcess:
                returncode = 0

                def communicate(self, timeout=None):
                    del timeout
                    Path(worker._output_path).write_bytes(b"fake image")
                    return "ok", ""

            def fake_popen(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                captured["script"] = Path(cmd[-1]).read_text(encoding="utf-8")
                return FakeProcess()

            with mock.patch("gpt_desktop.workers.resolve_blender_executable", return_value="/fake/blender"), mock.patch(
                "gpt_desktop.workers._dated_image_dir", return_value=tmp
            ), mock.patch("gpt_desktop.workers.subprocess.Popen", side_effect=fake_popen):
                path = worker._render_director_frame()

            self.assertTrue(os.path.exists(path))
            self.assertIn("--background", captured["cmd"])
            self.assertIn("街道夜景", captured["script"])
            self.assertIn("低角度中景", captured["script"])
            self.assertIn(model_path, captured["script"])


if __name__ == "__main__":
    unittest.main()
