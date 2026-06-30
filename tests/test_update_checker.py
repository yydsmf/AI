import unittest

from gpt_desktop.core import _build_windows_open_after_exit_script
from gpt_desktop.update_checker import (
    compare_versions,
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
        self.assertIn('tasklist /FI "IMAGENAME eq %APP_PROCESS%"', script)
        self.assertIn('start "" "%TARGET%"', script)


if __name__ == "__main__":
    unittest.main()
