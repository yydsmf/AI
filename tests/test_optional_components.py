import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from gpt_desktop import optional_components


class OptionalComponentsTests(unittest.TestCase):
    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("../outside.txt", "bad")
            with self.assertRaises(optional_components.OptionalComponentError):
                optional_components._safe_extract_zip(archive, Path(tmp) / "out")

    def test_blender_assets_are_installed_from_archive_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_archive = root / "assets.zip"
            with zipfile.ZipFile(source_archive, "w") as package:
                for name in optional_components.BLENDER_ASSET_REQUIRED_FILES:
                    package.writestr(name, name)

            cache_root = root / "components" / "blender_assets" / "test"
            with mock.patch.object(optional_components, "_COMPONENT_ROOT", root / "components"), \
                mock.patch.object(optional_components, "_BLENDER_ROOT", cache_root), \
                mock.patch.object(optional_components, "BLENDER_ASSET_CACHE_VERSION", "test"), \
                mock.patch.object(optional_components, "_blender_asset_urls", return_value=["https://example.test/assets.zip"]), \
                mock.patch.object(
                    optional_components,
                    "_download_file",
                    side_effect=lambda _url, destination, *_args, **_kwargs: shutil.copy2(source_archive, destination),
                ):
                installed = optional_components.ensure_blender_assets()
                self.assertEqual(Path(installed), cache_root)
                self.assertTrue(optional_components.blender_assets_available())
                self.assertEqual(
                    (cache_root / "modern_furniture_pack_293.blend").read_text(),
                    "modern_furniture_pack_293.blend",
                )
                self.assertEqual(optional_components.ensure_blender_assets(), str(cache_root))

    def test_playwright_wheel_is_extracted_to_component_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_wheel = root / "playwright.whl"
            with zipfile.ZipFile(source_wheel, "w") as package:
                package.writestr("playwright/__init__.py", "")
                sync_api = zipfile.ZipInfo("playwright/sync_api/__init__.py")
                sync_api.external_attr = (0o755 & 0xFFFF) << 16
                package.writestr(sync_api, "def sync_playwright(): return None\n")
            cache_root = root / "components" / "playwright" / "test"
            site_packages = cache_root / "site-packages"
            with mock.patch.object(optional_components, "_COMPONENT_ROOT", root / "components"), \
                mock.patch.object(optional_components, "_PLAYWRIGHT_ROOT", cache_root), \
                mock.patch.object(optional_components, "_PLAYWRIGHT_SITE_PACKAGES", site_packages), \
                mock.patch.object(
                    optional_components,
                    "_playwright_wheel",
                    return_value=("https://example.test/playwright.whl", ""),
                ), \
                mock.patch.object(
                    optional_components,
                    "_download_file",
                    side_effect=lambda _url, destination, *_args, **_kwargs: shutil.copy2(source_wheel, destination),
                ):
                installed = optional_components.ensure_playwright()
                self.assertEqual(Path(installed), site_packages)
                self.assertTrue((site_packages / "playwright" / "sync_api" / "__init__.py").exists())
                self.assertEqual(
                    (site_packages / "playwright" / "sync_api" / "__init__.py").stat().st_mode & 0o777,
                    0o755,
                )
                self.assertTrue((cache_root / "install.json").exists())


if __name__ == "__main__":
    unittest.main()
