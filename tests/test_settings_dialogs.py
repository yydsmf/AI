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
    def test_windows_update_starts_independent_updater(self):
        dialog = ProviderManagerDialog.__new__(ProviderManagerDialog)
        started = []
        opened_urls = []
        dialog.start_update_download = lambda asset: self.fail("Windows 不应再走主程序下载流程")
        dialog.start_windows_update = lambda asset, release_url="": started.append((asset, release_url))
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
                if text == "打开独立更新器":
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

        self.assertEqual(started, [(info.asset, info.release_url)])
        self.assertEqual(opened_urls, [])
        self.assertIn("更新器会显示下载进度", FakeMessageBox.last.text)
        self.assertIn("打开独立更新器", [label for label, _button in FakeMessageBox.last.buttons])

    def test_start_windows_update_quits_after_updater_launch(self):
        dialog = ProviderManagerDialog.__new__(ProviderManagerDialog)
        prepared = []
        quit_called = []
        closed = []
        dialog._prepare_parent_for_shutdown = lambda **kwargs: prepared.append(kwargs)
        dialog._close_settings_for_update = lambda: closed.append(True)
        dialog._quit_application_soon = lambda: quit_called.append(True)
        warnings = []

        with mock.patch.object(settings_dialogs, "launch_windows_updater", return_value=True) as launch_mock, \
                mock.patch.object(settings_dialogs.QMessageBox, "information", side_effect=AssertionError("不应弹出阻塞提示框")), \
                mock.patch.object(settings_dialogs.QMessageBox, "warning", side_effect=lambda *args: warnings.append(args)):
            asset = ReleaseAsset(name="setup.exe", url="https://download.test/setup.exe")
            dialog.start_windows_update(asset, "https://release.test")

        launch_mock.assert_called_once_with(asset, release_url="https://release.test")
        self.assertEqual(prepared, [{"skip_force_exit": True}])
        self.assertEqual(closed, [True])
        self.assertEqual(quit_called, [True])
        self.assertEqual(warnings, [])

    def test_start_windows_update_warns_when_updater_missing(self):
        dialog = ProviderManagerDialog.__new__(ProviderManagerDialog)
        dialog._prepare_parent_for_shutdown = lambda **_kwargs: self.fail("启动失败时不应退出主程序")
        dialog._quit_application_soon = lambda: self.fail("启动失败时不应退出主程序")
        warnings = []

        with mock.patch.object(settings_dialogs, "launch_windows_updater", return_value=False), \
                mock.patch.object(settings_dialogs.QMessageBox, "warning", side_effect=lambda *args: warnings.append(args)):
            dialog.start_windows_update(ReleaseAsset(name="setup.exe", url="https://download.test/setup.exe"))

        self.assertEqual(len(warnings), 1)
        self.assertIn("启动更新器失败", str(warnings[0][1]))


if __name__ == "__main__":
    unittest.main()
