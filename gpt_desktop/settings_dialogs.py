import os
import subprocess
import sys
import uuid

from PySide6.QtCore import QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .update_checker import check_latest_release, download_release_asset, launch_windows_updater
from .version import APP_RELEASES_URL, APP_VERSION
from .core import (
    AGENT_HISTORY_FILE,
    AGENT_SESSIONS_FILE,
    APP_DIR,
    HISTORY_DIR,
    IMAGE_DIR,
    IMAGE_HISTORY_FILE,
    IMAGE_TASK_LOG_FILE,
    INPUT_DRAFT_FILE,
    REFERENCE_DRAFT_DIR,
    REFERENCE_SNAPSHOT_DIR,
    VIDEO_DIR,
    VIDEO_HISTORY_FILE,
    format_cache_size,
    get_default_download_dir,
    get_path_size,
    load_input_drafts,
    load_json_file,
    now_str,
    open_local_file,
    open_local_file_after_app_exit,
    safe_clear_dir,
    safe_remove_file,
    save_input_drafts,
    save_json_file,
)


class UpdateCheckWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.result_ready.emit(check_latest_release())
        except Exception as e:
            self.failed.emit(str(e))


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)
    result_ready = Signal(str)
    failed = Signal(str)

    def __init__(self, asset, dest_dir, parent=None):
        super().__init__(parent)
        self.asset = asset
        self.dest_dir = dest_dir

    def run(self):
        try:
            path = download_release_asset(
                self.asset,
                self.dest_dir,
                progress_callback=lambda done, total: self.progress.emit(done, total),
            )
            self.result_ready.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


def _get_windows_process_memory_bytes(ctypes_module=None, wintypes_module=None):
    try:
        if ctypes_module is None:
            import ctypes as ctypes_module
        if wintypes_module is None:
            from ctypes import wintypes as wintypes_module

        class PROCESS_MEMORY_COUNTERS(ctypes_module.Structure):
            _fields_ = [
                ("cb", wintypes_module.DWORD),
                ("PageFaultCount", wintypes_module.DWORD),
                ("PeakWorkingSetSize", ctypes_module.c_size_t),
                ("WorkingSetSize", ctypes_module.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes_module.c_size_t),
                ("QuotaPagedPoolUsage", ctypes_module.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes_module.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes_module.c_size_t),
                ("PagefileUsage", ctypes_module.c_size_t),
                ("PeakPagefileUsage", ctypes_module.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes_module.sizeof(PROCESS_MEMORY_COUNTERS)
        process_handle = ctypes_module.windll.kernel32.GetCurrentProcess()
        get_memory_info = ctypes_module.windll.psapi.GetProcessMemoryInfo
        get_memory_info.argtypes = [
            wintypes_module.HANDLE,
            ctypes_module.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes_module.DWORD,
        ]
        get_memory_info.restype = wintypes_module.BOOL
        ok = get_memory_info(process_handle, ctypes_module.byref(counters), counters.cb)
        if not ok:
            return None
        value = int(counters.WorkingSetSize)
        return value if value > 0 else None
    except Exception:
        return None


def get_current_process_memory_bytes():
    """
    获取当前进程 RSS 内存占用。
    优先使用 psutil；Windows 使用系统 API 兜底；其他系统使用 ps / resource 兜底。
    """
    pid = os.getpid()

    try:
        import psutil
        return int(psutil.Process(pid).memory_info().rss)
    except Exception:
        pass

    if sys.platform.startswith("win"):
        return _get_windows_process_memory_bytes()

    try:
        out = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(pid)],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return int(out.split()[0]) * 1024
    except Exception:
        pass

    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        # macOS 返回 bytes，Linux 通常返回 KB
        if sys.platform == "darwin":
            return int(rss)
        return int(rss) * 1024
    except Exception:
        pass

    return None


class MemoryUsagePanel(QFrame):
    """
    设置页里的当前进程内存占用显示。
    精简版：只显示内存数值和操作按钮，把高度让给“已配置厂商”列表。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        title = QLabel("内存占用")
        title.setObjectName("sub_title")
        root.addWidget(title)

        self.value_label = QLabel("--")
        self.value_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 22px;
                font-weight: 800;
                background: transparent;
            }
        """)
        root.addWidget(self.value_label)

        self.button_row = QHBoxLayout()
        self.button_row.setContentsMargins(0, 2, 0, 0)
        self.button_row.setSpacing(8)
        self.button_row.addStretch()

        self.refresh_btn = QPushButton("立即刷新")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.setMinimumWidth(92)
        self.refresh_btn.clicked.connect(self.refresh_memory_usage)
        self.button_row.addWidget(self.refresh_btn)

        root.addLayout(self.button_row)

        self.timer = QTimer(self)
        self.timer.setInterval(60000)  # 60 秒自动刷新一次
        self.timer.timeout.connect(self.refresh_memory_usage)
        self.timer.start()

        self.refresh_memory_usage()

    def set_left_button(self, button):
        """
        在“立即刷新”左侧放一个外部按钮，例如“清理缓存”。
        """
        try:
            if button is None:
                return

            button.setParent(self)
            button.setMinimumWidth(92)
            self.refresh_btn.setMinimumWidth(92)

            # button_row 当前结构：
            # [stretch] [立即刷新]
            # 插入后：
            # [清理缓存] [stretch] [立即刷新]
            self.button_row.insertWidget(0, button)
        except Exception:
            pass

    def refresh_memory_usage(self):
        rss = get_current_process_memory_bytes()

        if rss is None:
            self.value_label.setText("无法获取")
            return

        self.value_label.setText(format_cache_size(rss))


# ============================================================
# 厂商管理 / 缓存清理对话框
# ============================================================

class CacheCleanDialog(QDialog):
    """
    缓存清理对话框。

    放在设置入口内打开。
    每个清理动作都会先弹出警告确认，确认后才执行。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("清理缓存")
        self.resize(620, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("清理缓存")
        title.setObjectName("section_title")
        root.addWidget(title)

        hint = QLabel(
            "这里可以清理长期使用过程中积累的本地缓存。"
            "清理操作不可恢复，执行前会再次确认。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("""
            QLabel {
                background-color: #1a1b20;
                border: 1px solid #2a2c33;
                border-radius: 8px;
                padding: 12px;
                color: #d6d9df;
                line-height: 1.6;
            }
        """)
        root.addWidget(self.info_label)

        row1 = QHBoxLayout()
        self.clear_ref_btn = QPushButton("清理参考图草稿")
        self.clear_images_btn = QPushButton("清理生成图片")
        row1.addWidget(self.clear_ref_btn)
        row1.addWidget(self.clear_images_btn)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self.clear_agent_btn = QPushButton("清理智能体历史")
        self.clear_image_history_btn = QPushButton("清理图片任务历史")
        row2.addWidget(self.clear_agent_btn)
        row2.addWidget(self.clear_image_history_btn)
        root.addLayout(row2)

        row3 = QHBoxLayout()
        self.clear_all_btn = QPushButton("清理全部缓存")
        self.clear_all_btn.setObjectName("danger")
        self.refresh_btn = QPushButton("刷新占用统计")
        self.refresh_btn.setObjectName("ghost")
        row3.addWidget(self.clear_all_btn)
        row3.addWidget(self.refresh_btn)
        root.addLayout(row3)

        root.addStretch()

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self.clear_ref_btn.clicked.connect(self.clear_reference_drafts)
        self.clear_images_btn.clicked.connect(self.clear_generated_images)
        self.clear_agent_btn.clicked.connect(self.clear_agent_history)
        self.clear_image_history_btn.clicked.connect(self.clear_image_task_history)
        self.clear_all_btn.clicked.connect(self.clear_all_cache)
        self.refresh_btn.clicked.connect(self.refresh_info)

        self.refresh_info()

    def refresh_info(self):
        app_size = get_path_size(APP_DIR)
        image_size = get_path_size(IMAGE_DIR)
        video_size = get_path_size(VIDEO_DIR)
        history_size = get_path_size(HISTORY_DIR)
        ref_size = get_path_size(REFERENCE_DRAFT_DIR)

        agent_size = get_path_size(AGENT_HISTORY_FILE)
        image_history_size = (
            get_path_size(IMAGE_HISTORY_FILE)
            + get_path_size(IMAGE_TASK_LOG_FILE)
            + get_path_size(REFERENCE_SNAPSHOT_DIR)
        )
        draft_size = get_path_size(INPUT_DRAFT_FILE)

        self.info_label.setText(
            "当前本地占用：\n\n"
            f"应用目录总占用：{format_cache_size(app_size)}\n"
            f"生成图片目录：{format_cache_size(image_size)}\n"
            f"生成视频目录：{format_cache_size(video_size)}\n"
            f"历史目录：{format_cache_size(history_size)}\n"
            f"参考图草稿：{format_cache_size(ref_size)}\n"
            f"智能体历史：{format_cache_size(agent_size)}\n"
            f"图片任务历史：{format_cache_size(image_history_size)}\n"
            f"输入草稿：{format_cache_size(draft_size)}\n\n"
            f"目录：{APP_DIR}"
        )

    def confirm(self, title, text):
        ret = QMessageBox.warning(
            self,
            title,
            text + "\n\n此操作不可恢复，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        return ret == QMessageBox.Yes

    def _show_clear_result(self, title, failures, success_text):
        failures = [str(x) for x in (failures or []) if str(x).strip()]
        if not failures:
            QMessageBox.information(self, title, success_text)
            return
        shown = "\n".join(failures[:8])
        more = f"\n……还有 {len(failures) - 8} 项" if len(failures) > 8 else ""
        QMessageBox.warning(
            self,
            "部分清理失败",
            f"部分文件没有清理成功，可能正在被系统或程序占用：\n\n{shown}{more}"
        )

    def _notify_cache_changed(self, kind):
        """
        通知主窗口刷新内存中的界面状态。
        """
        try:
            w = self.parent()
            while w is not None:
                if hasattr(w, "on_cache_cleared"):
                    w.on_cache_cleared(kind)
                    return
                w = w.parent()
        except Exception:
            pass

    def _clear_reference_draft_records(self):
        data = load_input_drafts()
        data["image_refs"] = []
        save_input_drafts(data)

    def _clear_image_history_records(self):
        save_json_file(IMAGE_HISTORY_FILE, [])
        save_json_file(IMAGE_TASK_LOG_FILE, [])

    def clear_reference_drafts(self):
        if not self.confirm("清理参考图草稿", "将删除本地保存的参考图草稿，并移除当前参考图草稿记录。"):
            return

        failures = []
        failures += safe_clear_dir(REFERENCE_DRAFT_DIR)
        self._clear_reference_draft_records()

        self.refresh_info()
        self._notify_cache_changed("reference")
        self._show_clear_result("完成", failures, "参考图草稿已清理。")

    def clear_generated_images(self):
        if not self.confirm("清理生成图片", "将删除本地生成图片文件，并清空图片生成历史。"):
            return

        failures = []
        failures += safe_clear_dir(IMAGE_DIR)
        failures += safe_clear_dir(REFERENCE_SNAPSHOT_DIR)
        self._clear_image_history_records()

        self.refresh_info()
        self._notify_cache_changed("images")
        self._show_clear_result("完成", failures, "生成图片缓存已清理。")

    def clear_agent_history(self):
        _agent_history_clear_selective_dialog(self)
        self.refresh_info()
        self._notify_cache_changed("agent")

    def clear_image_task_history(self):
        if not self.confirm("清理图片任务历史", "将清空图片生成历史记录和任务进度记录，但不删除图片文件。"):
            return

        failures = []
        self._clear_image_history_records()
        failures += safe_clear_dir(REFERENCE_SNAPSHOT_DIR)

        self.refresh_info()
        self._notify_cache_changed("image_history")
        self._show_clear_result("完成", failures, "图片任务历史已清理。")

    def clear_all_cache(self):
        if not self.confirm(
            "清理全部缓存",
            "将清理生成图片、生成视频、参考图草稿、智能体历史、图片任务历史。配置中的 API 厂商和 Key 不会删除。"
        ):
            return

        failures = []
        failures += safe_clear_dir(IMAGE_DIR)
        failures += safe_clear_dir(VIDEO_DIR)
        failures += safe_clear_dir(REFERENCE_DRAFT_DIR)
        failures += safe_clear_dir(REFERENCE_SNAPSHOT_DIR)

        save_json_file(AGENT_HISTORY_FILE, [])
        ok, err = safe_remove_file(AGENT_SESSIONS_FILE)
        if not ok:
            failures.append(f"{AGENT_SESSIONS_FILE}: {err}")
        save_json_file(VIDEO_HISTORY_FILE, [])
        self._clear_image_history_records()
        self._clear_reference_draft_records()

        self.refresh_info()
        self._notify_cache_changed("all")
        self._show_clear_result("完成", failures, "全部缓存已清理。")


class ProviderManagerDialog(QDialog):
    def __init__(self, providers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 厂商管理")
        self.resize(820, 520)

        self.providers = [dict(p) for p in providers]
        self._idx = -1
        self._loading = False
        self.update_worker = None
        self.update_download_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("API 厂商管理")
        title.setObjectName("section_title")
        root.addWidget(title)

        hint = QLabel("可以添加多个厂商配置（名称 / 中转地址 / API Key），主界面可以快速切换。")
        hint.setObjectName("hint")
        root.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(14)

        # 左：列表
        left_card = QFrame()
        left_card.setObjectName("card")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(12, 12, 12, 12)
        left.setSpacing(10)

        lbl = QLabel("已配置厂商")
        lbl.setObjectName("sub_title")
        left.addWidget(lbl)

        self.list_widget = QListWidget()
        left.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("+ 新建")
        self.del_btn = QPushButton("删除")
        self.del_btn.setObjectName("danger")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch()
        left.addLayout(btn_row)

        self.cache_clean_btn = QPushButton("清理缓存")
        self.cache_clean_btn.setObjectName("ghost")
        self.cache_clean_btn.setToolTip("清理历史记录、生成图片、参考图草稿等本地缓存")

        self.memory_panel = MemoryUsagePanel(self)
        self.memory_panel.set_left_button(self.cache_clean_btn)
        left.addWidget(self.memory_panel)

        self.version_label = QLabel(f"当前版本：{APP_VERSION}")
        self.version_label.setObjectName("hint")
        left.addWidget(self.version_label)

        self.update_check_btn = QPushButton("检查更新")
        self.update_check_btn.setObjectName("ghost")
        self.update_check_btn.setToolTip("从 GitHub Releases 检查 Windows / macOS 安装包更新")
        left.addWidget(self.update_check_btn)

        # 右：详情
        right_card = QFrame()
        right_card.setObjectName("card")
        right = QVBoxLayout(right_card)
        right.setContentsMargins(16, 16, 16, 16)
        right.setSpacing(12)

        lbl2 = QLabel("厂商详情")
        lbl2.setObjectName("sub_title")
        right.addWidget(lbl2)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：OpenAI 官方 / 中转 A / Claude")

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://api.openai.com 或 https://你的中转域名")

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("sk-...")

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("可选，仅这个厂商走代理，例如：http://127.0.0.1:7890")

        self.proxy_mode_combo = QComboBox()
        self.proxy_mode_combo.addItems(["仅下载图片", "提交和下载", "不使用代理"])
        self.proxy_mode_combo.setToolTip("生图提交请求建议直连；返回图片 URL 下载失败时再使用代理")

        for label_text, widget in (("名称", self.name_input),
                                   ("中转地址", self.url_input),
                                   ("API Key", self.key_input),
                                   ("代理", self.proxy_input),
                                   ("代理用途", self.proxy_mode_combo)):
            lbl_w = QLabel(label_text)
            lbl_w.setObjectName("field_label")
            form.addRow(lbl_w, widget)

        right.addLayout(form)

        tip = QLabel(
            "中转地址兼容是否带 /v1。\n示例：\n"
            "  https://api.openai.com\n"
            "  https://api.openai.com/v1\n"
            "  https://api.example-relay.com"
        )
        tip.setObjectName("hint")
        right.addWidget(tip)
        right.addStretch()

        body.addWidget(left_card, 2)
        body.addWidget(right_card, 3)
        root.addLayout(body, 1)

        # 底部按钮
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("primary")
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)

        # 信号
        self.list_widget.currentRowChanged.connect(self.on_select)
        self.name_input.textChanged.connect(self.on_field_changed)
        self.url_input.textChanged.connect(self.on_field_changed)
        self.key_input.textChanged.connect(self.on_field_changed)
        self.proxy_input.textChanged.connect(self.on_field_changed)
        self.proxy_mode_combo.currentTextChanged.connect(self.on_field_changed)
        self.add_btn.clicked.connect(self.on_add)
        self.del_btn.clicked.connect(self.on_delete)
        self.cache_clean_btn.clicked.connect(self.open_cache_cleaner)
        self.update_check_btn.clicked.connect(self.check_for_updates)
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

        self.refresh_list()
        if self.providers:
            self.list_widget.setCurrentRow(0)
        else:
            self.set_form_enabled(False)

    def refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for p in self.providers:
            self.list_widget.addItem(p.get("name", "未命名"))
        self.list_widget.blockSignals(False)

    def set_form_enabled(self, enabled):
        self.name_input.setEnabled(enabled)
        self.url_input.setEnabled(enabled)
        self.key_input.setEnabled(enabled)
        self.proxy_input.setEnabled(enabled)
        self.proxy_mode_combo.setEnabled(enabled)
        self.del_btn.setEnabled(enabled)
        if not enabled:
            self._loading = True
            self.name_input.clear()
            self.url_input.clear()
            self.key_input.clear()
            self.proxy_input.clear()
            idx = self.proxy_mode_combo.findText("不使用代理")
            self.proxy_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._loading = False

    def on_select(self, idx):
        self._idx = idx
        if idx < 0 or idx >= len(self.providers):
            self.set_form_enabled(False)
            return
        self.set_form_enabled(True)
        p = self.providers[idx]
        self._loading = True
        self.name_input.setText(p.get("name", ""))
        self.url_input.setText(p.get("base_url", ""))
        self.key_input.setText(p.get("api_key", ""))
        self.proxy_input.setText(p.get("proxy_url", ""))
        proxy_mode = p.get("proxy_mode", "不使用代理")
        idx = self.proxy_mode_combo.findText(proxy_mode)
        fallback_idx = self.proxy_mode_combo.findText("不使用代理")
        self.proxy_mode_combo.setCurrentIndex(idx if idx >= 0 else fallback_idx if fallback_idx >= 0 else 0)
        self._loading = False

    def on_field_changed(self):
        if self._loading or self._idx < 0:
            return
        p = self.providers[self._idx]
        p["name"] = self.name_input.text().strip() or "未命名"
        p["base_url"] = self.url_input.text().strip()
        p["api_key"] = self.key_input.text().strip()
        p["proxy_url"] = self.proxy_input.text().strip()
        p["proxy_mode"] = self.proxy_mode_combo.currentText().strip()
        item = self.list_widget.item(self._idx)
        if item:
            item.setText(p["name"])

    def on_add(self):
        self.providers.append({
            "id": uuid.uuid4().hex[:8],
            "name": f"新厂商 {len(self.providers) + 1}",
            "base_url": "",
            "api_key": "",
            "proxy_url": "",
            "proxy_mode": "不使用代理",
        })
        self.refresh_list()
        self.list_widget.setCurrentRow(len(self.providers) - 1)
        self.name_input.setFocus()
        self.name_input.selectAll()

    def on_delete(self):
        if self._idx < 0:
            return
        del self.providers[self._idx]
        self.refresh_list()
        if self.providers:
            self.list_widget.setCurrentRow(min(self._idx, len(self.providers) - 1))
        else:
            self._idx = -1
            self.set_form_enabled(False)

    def open_cache_cleaner(self):
        dlg = CacheCleanDialog(self)
        dlg.exec()

    def check_for_updates(self):
        if self.update_worker is not None and self.update_worker.isRunning():
            return
        if self.update_download_worker is not None and self.update_download_worker.isRunning():
            return

        self.update_check_btn.setEnabled(False)
        self.update_check_btn.setText("正在检查...")
        self.update_worker = UpdateCheckWorker(self)
        self.update_worker.result_ready.connect(self.on_update_checked)
        self.update_worker.failed.connect(self.on_update_check_failed)
        self.update_worker.finished.connect(self.cleanup_update_worker)
        self.update_worker.start()

    def cleanup_update_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.update_worker is worker:
                    self.update_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
            if self.update_download_worker is not None and self.update_download_worker.isRunning():
                return
            self.update_check_btn.setEnabled(True)
            self.update_check_btn.setText("检查更新")

        QTimer.singleShot(0, cleanup)

    def _open_url(self, url):
        url = str(url or "").strip()
        if not url:
            return False
        return QDesktopServices.openUrl(QUrl(url))

    def on_update_checked(self, info):
        asset = getattr(info, "asset", None)
        asset_name = getattr(asset, "name", "") if asset else ""
        asset_url = getattr(asset, "url", "") if asset else ""
        release_url = getattr(info, "release_url", "") or APP_RELEASES_URL

        if not getattr(info, "has_update", False):
            extra = ""
            if not asset_name:
                extra = "\n\n提示：当前 GitHub 发布页里暂时没有找到适合本电脑系统的安装包。"
            QMessageBox.information(
                self,
                "已经是最新版本",
                f"当前版本：{getattr(info, 'current_version', APP_VERSION)}\n"
                f"最新版本：{getattr(info, 'latest_version', APP_VERSION)}"
                f"{extra}"
            )
            return

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("发现新版本")
        text = (
            f"当前版本：{getattr(info, 'current_version', APP_VERSION)}\n"
            f"最新版本：{getattr(info, 'latest_version', '')}\n\n"
        )
        if asset_name:
            action_text = "退出并自动安装" if sys.platform.startswith("win") else "下载并退出安装"
            text += (
                f"已找到适合本电脑的安装包：\n{asset_name}\n\n"
                f"点击“{action_text}”后会启动更新器。更新器会把安装包下载到系统“下载”目录，"
                "确认主程序退出后自动打开安装包。"
            )
        else:
            text += "没有自动匹配到适合本电脑的安装包，可以打开发布页手动下载。"
        msg.setText(text)

        download_btn = None
        if asset_url:
            download_text = "退出并自动安装" if sys.platform.startswith("win") else "下载并退出安装"
            download_btn = msg.addButton(download_text, QMessageBox.AcceptRole)
        release_btn = msg.addButton("打开发布页", QMessageBox.ActionRole)
        later_btn = msg.addButton("稍后", QMessageBox.RejectRole)
        msg.setDefaultButton(download_btn or release_btn)
        msg.exec()

        clicked = msg.clickedButton()
        if download_btn is not None and clicked is download_btn:
            if sys.platform.startswith("win"):
                self.start_windows_auto_update(asset, release_url)
            else:
                self.start_update_download(asset)
        elif clicked is release_btn:
            self._open_url(release_url)
        elif clicked is later_btn:
            return

    def start_update_download(self, asset):
        if asset is None:
            QMessageBox.warning(self, "无法下载", "没有找到适合本电脑的更新包。")
            return
        if self.update_download_worker is not None and self.update_download_worker.isRunning():
            return

        updates_dir = get_default_download_dir()
        self.update_check_btn.setEnabled(False)
        self.update_check_btn.setText("正在下载...")
        self.update_download_worker = UpdateDownloadWorker(asset, updates_dir, self)
        self.update_download_worker.progress.connect(self.on_update_download_progress)
        self.update_download_worker.result_ready.connect(self.on_update_downloaded)
        self.update_download_worker.failed.connect(self.on_update_download_failed)
        self.update_download_worker.finished.connect(self.cleanup_update_download_worker)
        self.update_download_worker.start()

    def _prepare_parent_for_shutdown(self):
        try:
            parent = self.parent()
            while parent is not None and not hasattr(parent, "prepare_for_shutdown"):
                parent = parent.parent()
            if parent is not None:
                parent.prepare_for_shutdown()
        except Exception:
            pass

    def _quit_application_soon(self):
        app = QApplication.instance()
        if app is None:
            return
        try:
            for window in QApplication.topLevelWidgets():
                window.close()
        except Exception:
            pass
        QTimer.singleShot(300, app.quit)

    def start_windows_auto_update(self, asset, release_url):
        if asset is None:
            QMessageBox.warning(self, "无法更新", "没有找到适合本电脑的更新包。")
            return

        started = launch_windows_updater(asset, release_url=release_url)
        if not started:
            QMessageBox.warning(
                self,
                "更新器启动失败",
                "没有找到独立更新器，已改为旧方式下载安装包。\n\n"
                "安装包仍会保存到系统“下载”目录。"
            )
            self.start_update_download(asset)
            return

        self.update_check_btn.setEnabled(False)
        self.update_check_btn.setText("正在退出...")
        self._prepare_parent_for_shutdown()
        self._quit_application_soon()

    def on_update_download_progress(self, done, total):
        try:
            if total:
                pct = max(0, min(100, int(done * 100 / total)))
                self.update_check_btn.setText(f"正在下载 {pct}%")
            else:
                self.update_check_btn.setText("正在下载...")
        except Exception:
            pass

    def cleanup_update_download_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.update_download_worker is worker:
                    self.update_download_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
            if self.update_worker is None or not self.update_worker.isRunning():
                self.update_check_btn.setEnabled(True)
                self.update_check_btn.setText("检查更新")

        QTimer.singleShot(0, cleanup)

    def on_update_downloaded(self, path):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("更新包已准备好")
        msg.setText(
            f"更新包已下载：\n{path}\n\n"
            "继续后，程序会自动退出，并在退出完成后打开安装包。"
        )
        install_btn = msg.addButton("退出并打开安装包", QMessageBox.AcceptRole)
        later_btn = msg.addButton("稍后手动安装", QMessageBox.RejectRole)
        msg.setDefaultButton(install_btn)
        msg.exec()

        if msg.clickedButton() is not install_btn:
            QMessageBox.information(self, "稍后安装", f"更新包保存在：\n{path}")
            return

        if not open_local_file_after_app_exit(path):
            opened = open_local_file(path)
            if not opened:
                QMessageBox.warning(self, "打开失败", f"自动打开失败，请手动打开这个文件安装：\n{path}")
                return

        self._prepare_parent_for_shutdown()
        self._quit_application_soon()

    def on_update_download_failed(self, err):
        QMessageBox.warning(
            self,
            "下载更新失败",
            f"更新包下载失败：\n\n{err}\n\n可以改为打开 GitHub 发布页手动下载：\n{APP_RELEASES_URL}"
        )

    def on_update_check_failed(self, err):
        QMessageBox.warning(
            self,
            "检查更新失败",
            f"暂时无法连接 GitHub 检查更新。\n\n{err}\n\n"
            f"也可以手动打开发布页：\n{APP_RELEASES_URL}"
        )

    def get_providers(self):
        return [
            p for p in self.providers
            if p.get("name") or p.get("base_url") or p.get("api_key")
        ]
def _agent_history_clear_live_tabs():
    app = QApplication.instance()
    if app is None:
        return []

    try:
        from .agent_tab import AgentTab
    except Exception:
        return []

    tabs = []
    for win in app.topLevelWidgets():
        try:
            tabs.extend(win.findChildren(AgentTab))
        except Exception:
            pass
    return tabs


def _agent_history_clear_session_title(sess, index):
    if not isinstance(sess, dict):
        return f"对话 {index + 1}"

    title = sess.get("title")

    if not title:
        msgs = sess.get("messages") if isinstance(sess.get("messages"), list) else []
        for msg in msgs:
            if isinstance(msg, dict):
                if msg.get("_local_status"):
                    continue
                content = str(msg.get("content", "") or msg.get("text", "")).strip()
                if content:
                    title = content[:40]
                    break

    if not title:
        sid = sess.get("id")
        if sid:
            title = f"对话 {str(sid)[:8]}"

    if not title:
        title = f"对话 {index + 1}"

    return str(title)


def _agent_history_clear_extract_sessions(container):
    """
    支持：
    - AgentTab.sessions: list[session_dict]
    - agent_sessions.json: dict{"sessions": list[session_dict]}
    """
    if isinstance(container, list):
        session_keys = ("messages", "title", "id", "created_at", "updated_at", "context_cutoff")
        return [
            x for x in container
            if isinstance(x, dict) and any(k in x for k in session_keys)
        ]

    if isinstance(container, dict):
        value = container.get("sessions")
        return _agent_history_clear_extract_sessions(value)

    return []


def _agent_history_clear_collect_sources_from_live_tabs():
    """
    从当前运行中的 AgentTab 读取真实对话列表。
    这是最可靠的数据源，因为它就是左侧/当前界面正在用的数据。
    """
    sources = []
    for tab in _agent_history_clear_live_tabs():
        try:
            sessions = tab.sessions
        except Exception:
            continue

        sessions = _agent_history_clear_extract_sessions(sessions)
        if not sessions:
            continue

        def save_func(t=tab):
            try:
                t._save_sessions_data()
            except Exception:
                pass

            try:
                t.save_persistent_chat()
            except Exception:
                pass

            try:
                t.render_chat(force=True)
            except Exception:
                pass

        sources.append({
            "label": "当前智能体对话列表",
            "sessions": sessions,
            "tab": tab,
            "save": save_func,
        })

    # 去重：同一批 session 对象只保留一次
    unique = []
    seen = set()
    for src in sources:
        ids = tuple(id(x) for x in src["sessions"])
        if ids in seen:
            continue
        seen.add(ids)
        unique.append(src)

    # 优先选数量较少且真实的列表。用户这里应该是 3 个。
    unique.sort(key=lambda s: (len(s["sessions"]), s["label"]))
    return unique


def _agent_history_clear_collect_sources():
    # 先用界面真实数据，避免拉错文件。
    live_sources = _agent_history_clear_collect_sources_from_live_tabs()
    if live_sources:
        return live_sources

    data = load_json_file(AGENT_SESSIONS_FILE, None)
    sessions = _agent_history_clear_extract_sessions(data)
    if not sessions:
        return []

    def save_func():
        save_json_file(AGENT_SESSIONS_FILE, data)

    return [{
        "label": f"会话文件：{os.path.basename(AGENT_SESSIONS_FILE)}",
        "sessions": sessions,
        "file": AGENT_SESSIONS_FILE,
        "data": data,
        "save": save_func,
    }]


def _agent_history_clear_refresh_tabs_after_clear(cleared_sess):
    cleared_id = cleared_sess.get("id") if isinstance(cleared_sess, dict) else None

    for tab in _agent_history_clear_live_tabs():
        try:
            current = tab._current_session()

            same = False
            if current is cleared_sess:
                same = True
            elif cleared_id is not None and isinstance(current, dict) and current.get("id") == cleared_id:
                same = True

            if same:
                try:
                    tab.messages = []
                except Exception:
                    pass

                try:
                    tab.render_chat(force=True)
                except Exception:
                    pass

                try:
                    tab.bar.set_status("已清理所选智能体对话历史")
                except Exception:
                    pass
        except Exception:
            pass


def _agent_history_clear_selective_dialog(parent=None):
    try:
        from PySide6.QtWidgets import (
            QComboBox,
        )
    except Exception as e:
        try:
            QMessageBox.warning(parent, "缺少依赖", str(e))
        except Exception:
            pass
        return

    sources = _agent_history_clear_collect_sources()

    if not sources:
        QMessageBox.information(
            parent,
            "没有可清理的对话",
            "未找到真实的智能体对话列表。\n\n如果智能体页面还没打开，请先打开智能体页面后再试。"
        )
        return

    dlg = QDialog(parent)
    dlg.setWindowTitle("选择要清理的智能体对话")
    dlg.resize(640, 480)

    layout = QVBoxLayout(dlg)

    tip = QLabel(
        "请选择要清理历史内容的智能体对话。\n\n"
        "说明：只会清空所选对话中的聊天消息，不会删除对话本身，也不会影响其他对话。"
    )
    tip.setWordWrap(True)
    layout.addWidget(tip)

    source_combo = None
    if len(sources) > 1:
        source_combo = QComboBox()
        for src in sources:
            source_combo.addItem(f"{src['label']}（{len(src['sessions'])} 个对话）")
        layout.addWidget(source_combo)

    list_widget = QListWidget()
    layout.addWidget(list_widget, 1)

    def fill_list(source_index=0):
        list_widget.clear()
        src = sources[source_index]
        sessions = src["sessions"]

        for i, sess in enumerate(sessions):
            title = _agent_history_clear_session_title(sess, i)
            messages = sess.get("messages") if isinstance(sess.get("messages"), list) else []
            count = len(messages)
            t = str(sess.get("updated_at") or sess.get("created_at") or "") if isinstance(sess, dict) else ""

            line = f"{title}\n消息数：{count}"
            if t:
                line += f"    更新时间：{t}"

            if count <= 0:
                line += "\n该对话当前没有可清理的历史消息"

            item = QListWidgetItem(line)
            item.setData(Qt.UserRole, i)
            list_widget.addItem(item)

        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)

    fill_list(0)

    if source_combo is not None:
        source_combo.currentIndexChanged.connect(fill_list)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)

    cancel_btn = QPushButton("取消")
    clear_btn = QPushButton("清理所选对话历史")

    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(clear_btn)
    layout.addLayout(btn_row)

    cancel_btn.clicked.connect(dlg.reject)

    def current_source_and_session():
        source_index = source_combo.currentIndex() if source_combo is not None else 0
        if source_index < 0 or source_index >= len(sources):
            QMessageBox.warning(dlg, "选择无效", "当前数据源无效。")
            return None, None, -1

        item = list_widget.currentItem()
        if item is None:
            QMessageBox.information(dlg, "请选择对话", "请先选择一个智能体对话。")
            return None, None, -1

        src = sources[source_index]
        sessions = src["sessions"]
        try:
            index = int(item.data(Qt.UserRole))
        except Exception:
            QMessageBox.warning(dlg, "选择无效", "当前选择的对话无效。")
            return None, None, -1

        if index < 0 or index >= len(sessions):
            QMessageBox.warning(dlg, "选择无效", "当前选择的对话不存在。")
            return None, None, -1

        return src, sessions[index], index

    def do_clear():
        src, sess, index = current_source_and_session()
        if sess is None:
            return

        title = _agent_history_clear_session_title(sess, index)
        messages = sess.get("messages") if isinstance(sess.get("messages"), list) else []
        count = len(messages)

        if count <= 0:
            QMessageBox.information(dlg, "无需清理", "该对话当前没有历史消息。")
            return

        ret = QMessageBox.warning(
            dlg,
            "确认清理",
            (
                f"确定要清理这个智能体对话的历史内容吗？\n\n"
                f"对话：{title}\n"
                f"当前消息数：{count}\n\n"
                f"此操作不可恢复，但不会删除对话本身。"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if ret != QMessageBox.Yes:
            return

        sess["messages"] = []
        sess["context_cutoff"] = 0
        sess["updated_at"] = now_str()

        try:
            save_func = src.get("save")
            if callable(save_func):
                save_func()
        except Exception as e:
            QMessageBox.critical(dlg, "保存失败", f"清理后保存失败：\n{e}")
            return

        _agent_history_clear_refresh_tabs_after_clear(sess)

        QMessageBox.information(
            dlg,
            "清理完成",
            f"已清理所选智能体对话的历史内容：\n\n{title}"
        )
        dlg.accept()

    clear_btn.clicked.connect(do_clear)

    dlg.exec()
