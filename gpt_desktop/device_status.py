import glob

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QLabel, QHBoxLayout, QWidget


def parse_cpu_times(text):
    first_line = str(text or "").splitlines()[0].split()
    if not first_line or first_line[0] != "cpu":
        return None
    values = [int(value) for value in first_line[1:]]
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values)


def calculate_cpu_percent(previous, current):
    if not previous or not current:
        return None
    idle_delta = current[0] - previous[0]
    total_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    value = 100.0 * (total_delta - idle_delta) / total_delta
    return max(0.0, min(100.0, value))


def parse_memory_info(text):
    values = {}
    for line in str(text or "").splitlines():
        key, separator, remainder = line.partition(":")
        if not separator:
            continue
        parts = remainder.strip().split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0])
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    if total <= 0:
        return None
    used = max(0, total - available)
    return used, total, 100.0 * used / total


def parse_nvidia_status(text):
    line = str(text or "").strip().splitlines()
    if not line:
        return None
    parts = [part.strip() for part in line[0].split(",")]
    if len(parts) < 4:
        return None
    try:
        return {
            "usage": float(parts[0]),
            "temperature": float(parts[1]),
            "memory_used": float(parts[2]),
            "memory_total": float(parts[3]),
        }
    except (TypeError, ValueError):
        return None


def read_cpu_times():
    try:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            return parse_cpu_times(handle.readline())
    except (OSError, ValueError):
        return None


def read_memory_info():
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            return parse_memory_info(handle.read())
    except OSError:
        return None


def read_cpu_temperature():
    temperatures = []
    paths = glob.glob("/sys/class/thermal/thermal_zone*/temp")
    paths.extend(glob.glob("/sys/class/hwmon/hwmon*/temp*_input"))
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = float(handle.read().strip())
            if value > 1000:
                value /= 1000.0
            if 0 < value < 130:
                temperatures.append(value)
        except (OSError, TypeError, ValueError):
            continue
    return max(temperatures) if temperatures else None


class DeviceStatusBar(QWidget):
    REFRESH_INTERVAL_MS = 10_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_cpu_times = read_cpu_times()
        self._cpu_percent = None
        self._cpu_temperature = read_cpu_temperature()
        self._memory = read_memory_info()
        self._gpu = None

        self.setFixedHeight(32)
        self.setStyleSheet(
            "DeviceStatusBar { background: #15171a; border-top: 1px solid #30343a; }"
            "QLabel { color: #c7cbd1; font-size: 12px; padding: 0 10px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)
        self.label = QLabel()
        layout.addStretch(1)
        layout.addWidget(self.label)

        self._gpu_process = QProcess(self)
        self._gpu_process.finished.connect(self._on_gpu_finished)

        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        self._update_label()
        QTimer.singleShot(0, self._start_gpu_query)
        QTimer.singleShot(1000, self.refresh)

    def refresh(self):
        current_cpu_times = read_cpu_times()
        self._cpu_percent = calculate_cpu_percent(self._last_cpu_times, current_cpu_times)
        if current_cpu_times:
            self._last_cpu_times = current_cpu_times
        self._cpu_temperature = read_cpu_temperature()
        self._memory = read_memory_info()
        self._update_label()
        self._start_gpu_query()

    def _start_gpu_query(self):
        if self._gpu_process.state() != QProcess.NotRunning:
            return
        self._gpu_process.start(
            "nvidia-smi",
            [
                "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
        )

    def _on_gpu_finished(self, exit_code, _exit_status):
        output = bytes(self._gpu_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._gpu = parse_nvidia_status(output) if exit_code == 0 else None
        self._update_label()

    def _update_label(self):
        cpu = "CPU --%" if self._cpu_percent is None else f"CPU {self._cpu_percent:.0f}%"
        if self._cpu_temperature is not None:
            cpu += f"  {self._cpu_temperature:.0f}°C"

        if self._memory:
            used, total, percent = self._memory
            memory = f"内存 {used / 1048576:.1f}/{total / 1048576:.1f} GB  {percent:.0f}%"
        else:
            memory = "内存 --"

        if self._gpu:
            gpu = (
                f"GPU {self._gpu['usage']:.0f}%  {self._gpu['temperature']:.0f}°C"
                f"    显存 {self._gpu['memory_used']:.0f}/{self._gpu['memory_total']:.0f} MB"
            )
        else:
            gpu = "GPU 读取中"
        self.label.setText(f"{cpu}    |    {memory}    |    {gpu}")
