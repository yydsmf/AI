import argparse
import os
import subprocess
import sys
import time

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .core import APP_STYLE, get_default_download_dir, log_debug
from .update_checker import ReleaseAsset, download_release_asset, safe_asset_filename
from .version import APP_NAME, APP_RELEASES_URL


class WindowsUpdateWorker(QThread):
    status_changed = Signal(str)
    progress_changed = Signal(int, int)
    finished_ready = Signal(str)
    failed = Signal(str)

    def __init__(self, asset, parent_pid=0, app_exe="", parent=None):
        super().__init__(parent)
        self.asset = asset
        self.parent_pid = int(parent_pid or 0)
        self.app_exe = str(app_exe or "").strip()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def _check_cancelled(self):
        if self._cancelled or self.isInterruptionRequested():
            raise RuntimeError("更新已取消。")

    def _parent_running(self):
        if self.parent_pid <= 0:
            return False
        if not sys.platform.startswith("win"):
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {self.parent_pid}"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
            output = (result.stdout or "") + (result.stderr or "")
            return str(self.parent_pid) in output
        except Exception:
            return False

    def _kill_parent(self):
        if self.parent_pid <= 0 or not sys.platform.startswith("win"):
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self.parent_pid)],
                capture_output=True,
                timeout=10,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
        except Exception as e:
            log_debug("更新器结束主程序 PID 失败", e)

    def _kill_app_name(self):
        app_exe = self.app_exe
        if not app_exe or not sys.platform.startswith("win"):
            return
        if app_exe.lower() in ("python.exe", "pythonw.exe"):
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", app_exe],
                capture_output=True,
                timeout=10,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
        except Exception as e:
            log_debug("更新器结束主程序进程名失败", e)

    def _wait_for_parent_exit(self, max_wait_seconds=20):
        if self.parent_pid <= 0:
            return

        self.status_changed.emit("正在等待主程序退出...")
        deadline = time.time() + max(1, int(max_wait_seconds))
        while time.time() < deadline:
            self._check_cancelled()
            if not self._parent_running():
                return
            time.sleep(0.5)

        if self._parent_running():
            self.status_changed.emit("主程序仍在后台运行，正在自动结束残留进程...")
            self._kill_parent()
            time.sleep(1)
        if self._parent_running():
            self._kill_app_name()
            time.sleep(1)

    def _start_installer(self, installer_path):
        if not installer_path or not os.path.exists(installer_path):
            raise RuntimeError("安装包不存在，无法启动安装。")

        self.status_changed.emit("正在打开安装包...")
        if sys.platform.startswith("win"):
            try:
                os.startfile(installer_path)  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        subprocess.Popen([installer_path], close_fds=True)

    def run(self):
        try:
            self._check_cancelled()
            dest_dir = get_default_download_dir()
            asset_name = safe_asset_filename(getattr(self.asset, "name", "") or "")
            self.status_changed.emit(f"正在下载到系统下载目录：{asset_name}")

            def report_progress(done, total):
                self._check_cancelled()
                self.progress_changed.emit(done, total)

            installer_path = download_release_asset(
                self.asset,
                dest_dir,
                progress_callback=report_progress,
            )

            self._check_cancelled()
            self._wait_for_parent_exit(max_wait_seconds=20)
            self._check_cancelled()
            self._start_installer(installer_path)
            self.finished_ready.emit(installer_path)
        except Exception as e:
            self.failed.emit(str(e))


class WindowsUpdaterWindow(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.worker = None
        self.installer_path = ""
        self.setWindowTitle(f"{APP_NAME} 更新器")
        self.resize(560, 280)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("正在准备更新")
        title.setObjectName("section_title")
        root.addWidget(title)

        self.status_label = QLabel("更新器已启动。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("hint")
        root.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.setMinimumHeight(90)
        self.detail.setText("请保持此窗口打开。更新器会下载新版安装包，确认主程序退出后自动打开安装包。")
        root.addWidget(self.detail, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.release_btn = QPushButton("打开发布页")
        self.cancel_btn = QPushButton("取消")
        buttons.addWidget(self.release_btn)
        buttons.addWidget(self.cancel_btn)
        root.addLayout(buttons)

        self.release_btn.clicked.connect(self.open_release_page)
        self.cancel_btn.clicked.connect(self.cancel_update)
        QTimer.singleShot(100, self.start_update)

    def open_release_page(self):
        url = str(getattr(self.args, "release_url", "") or APP_RELEASES_URL).strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def start_update(self):
        asset = ReleaseAsset(
            name=str(getattr(self.args, "name", "") or "GPTLocalToolbox_Update.exe"),
            url=str(getattr(self.args, "url", "") or ""),
        )
        self.worker = WindowsUpdateWorker(
            asset,
            parent_pid=int(getattr(self.args, "parent_pid", 0) or 0),
            app_exe=str(getattr(self.args, "app_exe", "") or ""),
            parent=self,
        )
        self.worker.status_changed.connect(self.on_status_changed)
        self.worker.progress_changed.connect(self.on_progress_changed)
        self.worker.finished_ready.connect(self.on_finished_ready)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_status_changed(self, text):
        self.status_label.setText(str(text or ""))
        self.detail.setText(str(text or ""))

    def on_progress_changed(self, done, total):
        if total:
            pct = max(0, min(100, int(done * 100 / total)))
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)
            self.status_label.setText(f"正在下载新版安装包：{pct}%")
            self.detail.setText(f"已下载 {done / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB")
        else:
            self.progress.setRange(0, 0)
            self.detail.setText(f"已下载 {done / 1024 / 1024:.1f} MB")

    def on_finished_ready(self, path):
        self.installer_path = str(path or "")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_label.setText("安装包已打开，请按安装向导完成更新。")
        self.detail.setText(f"安装包位置：{self.installer_path}")
        self.cancel_btn.setText("关闭")
        QTimer.singleShot(1500, self.close)

    def on_failed(self, err):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        if str(err or "").strip() == "更新已取消。":
            self.status_label.setText("更新已取消")
            self.detail.setText("已取消本次自动更新。")
        else:
            self.status_label.setText("自动更新失败")
            self.detail.setText(
                f"{err}\n\n"
                "可以点击“打开发布页”手动下载安装包。"
            )
        self.cancel_btn.setText("关闭")
        self.cancel_btn.setEnabled(True)

    def cancel_update(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("正在取消...")
            self.cancel_btn.setEnabled(False)
            return
        self.close()

    def closeEvent(self, event):
        try:
            if self.worker is not None and self.worker.isRunning():
                self.worker.cancel()
                self.status_label.setText("正在取消...")
                self.cancel_btn.setEnabled(False)
                event.ignore()
                return
        except Exception:
            pass
        super().closeEvent(event)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="GPT Toolbox Windows updater")
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", default="GPTLocalToolbox_Update.exe")
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--app-exe", default="GPTLocalToolbox.exe")
    parser.add_argument("--release-url", default=APP_RELEASES_URL)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(f"{APP_NAME} 更新器")
    app.setStyleSheet(APP_STYLE)
    window = WindowsUpdaterWindow(args)
    window.show()
    return app.exec()
