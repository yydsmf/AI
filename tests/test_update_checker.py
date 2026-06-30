import os
import sys
import tempfile
import unittest
from unittest import mock

from gpt_desktop.core import _build_windows_open_after_exit_script
from gpt_desktop.update_checker import (
    ReleaseAsset,
    build_windows_updater_command,
    check_latest_release,
    compare_versions,
    copy_windows_updater_to_temp,
    default_windows_app_exe_name,
    parse_github_release_page,
    parse_github_release,
    select_release_asset,
)


class UpdateCheckerTests(unittest.TestCase):
    def test_compare_versions_handles_v_prefix_and_prerelease(self):
        self.assertEqual(compare_versions("1.0.0", "v1.0.1"), -1)
        self.assertEqual(compare_versions("v1.2.0", "1.1.9"), 1)
        self.assertEqual(compare_versions("1.0.0-beta", "1.0.0"), -1)
        self.assertEqual(compare_versions("1.0", "1.0.0"), 0)

    def test_selects_windows_setup_asset(self):
        asset = select_release_asset(
            [
                {"name": "GPTLocalToolbox_v1.2.0_macos_arm64.app.zip", "browser_download_url": "mac"},
                {"name": "GPTLocalToolbox_Setup_v1.2.0_windows_x64.exe", "browser_download_url": "win"},
            ],
            platform_key="windows-x64",
        )

        self.assertIsNotNone(asset)
        self.assertEqual(asset.url, "win")

    def test_selects_macos_arm64_or_universal_asset(self):
        asset = select_release_asset(
            [
                {"name": "GPTLocalToolbox_v1.2.0_macos_intel.app.zip", "browser_download_url": "intel"},
                {"name": "GPTLocalToolbox_v1.2.0_macos_arm64.app.zip", "browser_download_url": "arm"},
            ],
            platform_key="macos-arm64",
        )

        self.assertIsNotNone(asset)
        self.assertEqual(asset.url, "arm")

        universal = select_release_asset(
            [
                {"name": "GPTLocalToolbox_v1.2.0_macos_universal2.dmg", "browser_download_url": "universal"},
            ],
            platform_key="macos-arm64",
        )
        self.assertIsNotNone(universal)
        self.assertEqual(universal.url, "universal")

    def test_parse_release_marks_update_and_asset(self):
        info = parse_github_release(
            {
                "tag_name": "v1.2.0",
                "html_url": "https://github.com/yydsmf/AI/releases/tag/v1.2.0",
                "body": "更新说明",
                "assets": [
                    {
                        "name": "GPTLocalToolbox_Setup_v1.2.0_windows_x64.exe",
                        "browser_download_url": "https://download.test/setup.exe",
                    }
                ],
            },
            current_version="1.0.0",
            platform_key="windows-x64",
        )

        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, "1.2.0")
        self.assertEqual(info.asset.name, "GPTLocalToolbox_Setup_v1.2.0_windows_x64.exe")

    def test_parse_release_page_fallback_selects_asset(self):
        html = """
        <a href="/yydsmf/AI/releases/download/v1.2.0/GPTLocalToolbox_Setup_v1.2.0_windows_x64.exe">win</a>
        <a href="/yydsmf/AI/releases/download/v1.2.0/GPTLocalToolbox_v1.2.0_macos_arm64.app.zip">arm</a>
        <a href="/yydsmf/AI/archive/refs/tags/v1.2.0.zip">source</a>
        """

        info = parse_github_release_page(
            html,
            final_url="https://github.com/yydsmf/AI/releases/tag/v1.2.0",
            current_version="1.0.0",
            platform_key="windows-x64",
        )

        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, "1.2.0")
        self.assertEqual(info.asset.name, "GPTLocalToolbox_Setup_v1.2.0_windows_x64.exe")
        self.assertTrue(info.asset.url.startswith("https://github.com/"))

    def test_check_latest_release_falls_back_to_page_when_api_assets_are_empty(self):
        api_response = mock.Mock()
        api_response.status_code = 200
        api_response.json.return_value = {
            "tag_name": "v1.2.0",
            "html_url": "https://github.com/yydsmf/AI/releases/tag/v1.2.0",
            "assets": [],
        }
        page_response = mock.Mock()
        page_response.status_code = 200
        page_response.url = "https://github.com/yydsmf/AI/releases/tag/v1.2.0"
        page_response.text = """
        <a href="/yydsmf/AI/releases/download/v1.2.0/GPTLocalToolbox_Setup_v1.2.0_windows_x64.exe">win</a>
        """

        with mock.patch("gpt_desktop.update_checker.requests.get", side_effect=[api_response, page_response]):
            info = check_latest_release(current_version="1.0.0", platform_key="windows-x64")

        self.assertTrue(info.has_update)
        self.assertIsNotNone(info.asset)
        self.assertEqual(info.asset.name, "GPTLocalToolbox_Setup_v1.2.0_windows_x64.exe")

    def test_windows_open_after_exit_script_waits_before_starting_installer(self):
        script = _build_windows_open_after_exit_script(
            r"C:\Users\Test User\Downloads\GPTLocalToolbox_Setup.exe",
            1234,
            "GPTLocalToolbox.exe",
            max_wait_seconds=30,
        )

        self.assertIn('set "APP_PID=1234"', script)
        self.assertIn('set "APP_PROCESS=GPTLocalToolbox.exe"', script)
        self.assertIn('tasklist /FI "PID eq %APP_PID%"', script)
        self.assertIn("taskkill /F /T /PID %APP_PID%", script)
        self.assertIn('taskkill /F /T /IM "%APP_PROCESS%"', script)
        self.assertIn('start "" "%TARGET%"', script)

    def test_build_windows_updater_command_contains_update_context(self):
        asset = ReleaseAsset(
            name='GPTLocalToolbox_Setup_v1.2.0_windows:x64?.exe',
            url="https://download.test/setup.exe",
        )

        cmd = build_windows_updater_command(
            asset,
            release_url="https://github.com/yydsmf/AI/releases/tag/v1.2.0",
            parent_pid=1234,
            updater_path=r"C:\Program Files\GPTLocalToolbox\GPTToolboxUpdater.exe",
            app_exe="GPTLocalToolbox.exe",
        )

        self.assertEqual(cmd[0], r"C:\Program Files\GPTLocalToolbox\GPTToolboxUpdater.exe")
        self.assertIn("--url", cmd)
        self.assertIn("https://download.test/setup.exe", cmd)
        self.assertIn("--name", cmd)
        self.assertIn("GPTLocalToolbox_Setup_v1.2.0_windows_x64_.exe", cmd)
        self.assertIn("--parent-pid", cmd)
        self.assertIn("1234", cmd)
        self.assertIn("--app-exe", cmd)
        self.assertIn("GPTLocalToolbox.exe", cmd)
        self.assertIn("--release-url", cmd)

    def test_default_windows_app_exe_avoids_python_name(self):
        with mock.patch.object(sys, "executable", r"C:\Python311\pythonw.exe"):
            self.assertEqual(default_windows_app_exe_name(), "GPTLocalToolbox.exe")
        with mock.patch.object(sys, "executable", r"C:\App\GPTLocalToolbox.exe"):
            self.assertEqual(default_windows_app_exe_name(), "GPTLocalToolbox.exe")

    def test_copy_windows_updater_to_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "GPTToolboxUpdater.exe")
            with open(source, "wb") as f:
                f.write(b"updater")
            with mock.patch.object(sys, "platform", "win32"):
                copied = copy_windows_updater_to_temp(source)

            self.assertTrue(copied.endswith(".exe"))
            self.assertTrue(os.path.exists(copied))
            with open(copied, "rb") as f:
                self.assertEqual(f.read(), b"updater")
            try:
                os.remove(copied)
            except OSError:
                pass

    def test_copy_windows_updater_to_temp_copies_runtime_dlls(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "GPTToolboxUpdater.exe")
            runtime = os.path.join(tmp, "vcruntime140.dll")
            with open(source, "wb") as f:
                f.write(b"updater")
            with open(runtime, "wb") as f:
                f.write(b"runtime")
            with mock.patch.object(sys, "platform", "win32"):
                copied = copy_windows_updater_to_temp(source)

            copied_runtime = os.path.join(os.path.dirname(copied), "vcruntime140.dll")
            self.assertTrue(os.path.exists(copied_runtime))
            with open(copied_runtime, "rb") as f:
                self.assertEqual(f.read(), b"runtime")
            for path in (copied, copied_runtime):
                try:
                    os.remove(path)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
