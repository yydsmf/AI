import ctypes
import unittest
from unittest import mock

import gpt_desktop.settings_dialogs as settings_dialogs
from gpt_desktop.settings_dialogs import ProviderManagerDialog, _get_windows_process_memory_bytes
from gpt_desktop.update_checker import ReleaseAsset, UpdateInfo


class _FakeKernel32:
    def GetCurrentProcess(self):
        return 123


class _FakePsapi:
    def __init__(self, value):
        self.GetProcessMemoryInfo = _FakeGetProcessMemoryInfo(value)


class _FakeGetProcessMemoryInfo:
    def __init__(self, value):
        self.value = value
        self.argtypes = None
        self.restype = None

    def __call__(self, _handle, counters_ref, _size):
        counters = counters_ref._obj
        counters.WorkingSetSize = self.value
        return True


class _FakeWindll:
    def __init__(self, value):
        self.kernel32 = _FakeKernel32()
        self.psapi = _FakePsapi(value)


class _FakeCtypes:
    Structure = ctypes.Structure
    c_size_t = ctypes.c_size_t
    POINTER = staticmethod(ctypes.POINTER)
    byref = staticmethod(ctypes.byref)
    sizeof = staticmethod(ctypes.sizeof)

    def __init__(self, value):
        self.windll = _FakeWindll(value)


class WindowsMemoryUsageTests(unittest.TestCase):
    def test_windows_memory_fallback_reads_working_set_size(self):
        value = _get_windows_process_memory_bytes(ctypes_module=_FakeCtypes(123456789))

        self.assertEqual(value, 123456789)


class WindowsUpdateFlowTests(unittest.TestCase):
    def test_windows_update_download_keeps_main_app_open(self):
        dialog = ProviderManagerDialog.__new__(ProviderManagerDialog)
        downloads = []
        opened_urls = []
        dialog.start_update_download = lambda asset: downloads.append(asset)
        dialog._open_url = lambda url: opened_urls.append(url)
        info = UpdateInfo(
            current_version="1.0.0",
            latest_version="1.0.1",
            has_update=True,
            release_url="https://github.com/yydsmf/AI/releases/tag/v1.0.1",
            release_notes="",
            asset=ReleaseAsset(
                name="GPTLocalToolbox_Setup_v1.0.1_windows_x64.exe",
                url="https://download.test/setup.exe",
            ),
        )

        class FakeMessageBox:
            Information = object()
            AcceptRole = object()
            ActionRole = object()
            RejectRole = object()
            last = None

            def __init__(self, _parent=None):
                self.text = ""
                self.buttons = []
                self._clicked = None
                FakeMessageBox.last = self

            def setIcon(self, _icon):
                pass

            def setWindowTitle(self, _title):
                pass

            def setText(self, text):
                self.text = str(text or "")

            def addButton(self, text, _role):
                button = object()
                self.buttons.append((str(text or ""), button))
                if text == "下载新版安装包":
                    self._clicked = button
                return button

            def setDefaultButton(self, _button):
                pass

            def exec(self):
                pass

            def clickedButton(self):
                return self._clicked

        with mock.patch.object(settings_dialogs.sys, "platform", "win32"), mock.patch.object(
            settings_dialogs, "QMessageBox", FakeMessageBox
        ):
            dialog.on_update_checked(info)

        self.assertEqual(downloads, [info.asset])
        self.assertEqual(opened_urls, [])
        self.assertIn("程序会保持打开并显示下载进度", FakeMessageBox.last.text)
        self.assertIn("下载新版安装包", [label for label, _button in FakeMessageBox.last.buttons])


if __name__ == "__main__":
    unittest.main()
