import unittest

from gpt_desktop.device_status import (
    calculate_cpu_percent,
    parse_cpu_times,
    parse_memory_info,
    parse_nvidia_status,
)


class DeviceStatusTests(unittest.TestCase):
    def test_cpu_usage_uses_idle_and_total_deltas(self):
        previous = parse_cpu_times("cpu  100 0 50 850 0 0 0 0 0 0\n")
        current = parse_cpu_times("cpu  140 0 60 900 0 0 0 0 0 0\n")
        self.assertAlmostEqual(calculate_cpu_percent(previous, current), 50.0)

    def test_memory_usage_uses_available_memory(self):
        memory = parse_memory_info("MemTotal: 8192000 kB\nMemAvailable: 6144000 kB\n")
        self.assertEqual(memory[:2], (2048000, 8192000))
        self.assertAlmostEqual(memory[2], 25.0)

    def test_nvidia_status_parser(self):
        status = parse_nvidia_status("12, 43, 256, 3072\n")
        self.assertEqual(
            status,
            {"usage": 12.0, "temperature": 43.0, "memory_used": 256.0, "memory_total": 3072.0},
        )

    def test_invalid_nvidia_output_is_ignored(self):
        self.assertIsNone(parse_nvidia_status("NVIDIA-SMI failed"))


if __name__ == "__main__":
    unittest.main()
