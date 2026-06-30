import ctypes
import unittest

from gpt_desktop.settings_dialogs import _get_windows_process_memory_bytes


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


if __name__ == "__main__":
    unittest.main()
