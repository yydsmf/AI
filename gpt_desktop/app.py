import os
import sys

from PySide6.QtCore import QEvent, QObject, QSize, QTimer
from PySide6.QtWidgets import QApplication, QLineEdit, QMainWindow, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget, QTabWidget

from .agent_tab import AgentTab
from .ai_workflow_tab import AIWorkflowTab
from .core import (
    APP_STYLE,
    CONTEXT_MENU_FEEDBACK_STYLE,
    load_config,
    log_debug,
    save_config,
    schedule_windows_process_force_exit,
)
from .image_tab import ImageGeneratorTab
from .novel_adaptation_tab import NovelAdaptationTab
from .novel_writing_tab import NovelWritingTab
from .settings_dialogs import ProviderManagerDialog
from .video_tab import VideoGeneratorTab
from .version import APP_NAME, APP_VERSION


class CompactTabWidget(QTabWidget):
    def minimumSizeHint(self):
        return QSize(720, 420)


def fit_window_to_screen(window, preferred_width, preferred_height, min_width=1000, min_height=520):
    screen = QApplication.primaryScreen()
    if screen is None:
        window.resize(preferred_width, preferred_height)
        return

    geo = screen.availableGeometry()
    max_width = max(720, geo.width() - 80)
    max_height = max(420, geo.height())
    width = min(preferred_width, max_width)
    height = max_height
    width = max(720, min(width, max_width))
    height = max(420, min(height, max_height))
    window.resize(width, height)
    window.move(
        geo.x() + max(0, (geo.width() - width) // 2),
        geo.y(),
    )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._shutdown_prepared = False
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        fit_window_to_screen(self, 1320, 880)
        self.setMinimumSize(720, 420)

        self.config = load_config()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = CompactTabWidget()
        self.tabs.setDocumentMode(True)
        self.image_tab = ImageGeneratorTab(self.config)
        self.video_tab = VideoGeneratorTab(self.config)
        self.ai_workflow_tab = AIWorkflowTab(self.config)
        self.novel_writing_tab = NovelWritingTab(self.config)
        self.adaptation_tab = NovelAdaptationTab(self.config, self.novel_writing_tab.get_current_project_snapshot)
        self.agent_tab = AgentTab(self.config)
        self.tabs.addTab(self.image_tab, "图片生成")
        self.tabs.addTab(self.video_tab, "视频生成")
        self.tabs.addTab(self.ai_workflow_tab, "AI工作流")
        self.tabs.addTab(self.novel_writing_tab, "小说写作")
        self.tabs.addTab(self.adaptation_tab, "改编")
        self.tabs.addTab(self.agent_tab, "智能体")
        layout.addWidget(self.tabs)

        self.image_tab.request_settings.connect(self.open_provider_manager)
        self.video_tab.request_settings.connect(self.open_provider_manager)
        self.novel_writing_tab.request_settings.connect(self.open_provider_manager)
        self.adaptation_tab.request_settings.connect(self.open_provider_manager)
        self.agent_tab.request_settings.connect(self.open_provider_manager)
        self.adaptation_tab.open_project_requested.connect(self.open_adaptation_project)
        self.tabs.currentChanged.connect(self._on_main_tab_changed)

        QTimer.singleShot(0, self.image_tab.load_models)
        QTimer.singleShot(0, self.video_tab.load_models)
        QTimer.singleShot(0, self.adaptation_tab.load_models)
        self.agent_tab.bar.set_status("未刷新模型列表")

    def on_cache_cleared(self, kind):
        """
        缓存清理后，刷新当前内存里的界面状态，避免磁盘已删除但界面还显示旧内容。
        """
        try:
            if kind in ("agent", "all"):
                self.agent_tab.load_persistent_chat()

            if kind in ("images", "image_history", "all"):
                self.image_tab.load_persistent_history()
                self.image_tab.load_persistent_task_log()
                self.video_tab.load_persistent_history()

            if kind in ("reference", "all"):
                self.image_tab.refs = []
                self.image_tab.ref_list.clear()
        except Exception as e:
            log_debug("刷新清理后的界面状态失败", e)

    def open_provider_manager(self):
        dlg = ProviderManagerDialog(self.config.get("providers", []), self)
        if not dlg.exec():
            return

        self.config["providers"] = dlg.get_providers()
        valid_ids = {p["id"] for p in self.config["providers"]}

        for key in ("image", "video", "agent"):
            if self.config[key].get("provider_id") not in valid_ids:
                self.config[key]["provider_id"] = (
                    self.config["providers"][0]["id"] if self.config["providers"] else ""
                )
        if self.config.setdefault("novel", {}).get("provider_id") not in valid_ids:
            self.config["novel"]["provider_id"] = (
                self.config["providers"][0]["id"] if self.config["providers"] else ""
            )

        save_config(self.config)
        self.image_tab.refresh_providers()
        self.image_tab.load_models()
        self.video_tab.refresh_providers()
        self.video_tab.load_models()
        self.agent_tab.refresh_providers()
        self.agent_tab.load_models()
        self.novel_writing_tab.refresh_providers()
        self.novel_writing_tab.load_models()
        self.adaptation_tab.refresh_providers()
        self.adaptation_tab.load_models()

    def _on_main_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.adaptation_tab:
            self.adaptation_tab.refresh_adaptation_projects()

    def open_adaptation_project(self, path):
        path = str(path or "").strip()
        if not path:
            return
        self.novel_writing_tab.open_project_file(path)
        self.tabs.setCurrentWidget(self.novel_writing_tab)

    def _stop_worker(self, worker):
        if worker is None:
            return
        try:
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                worker.requestInterruption()
        except Exception as e:
            log_debug("退出时请求后台任务停止失败", e)
        try:
            worker.requestInterruption()
        except Exception:
            pass
        try:
            worker.quit()
        except Exception:
            pass

    def _stop_worker_attrs(self, obj, names):
        for name in names:
            try:
                self._stop_worker(getattr(obj, name, None))
            except Exception as e:
                log_debug(f"退出时停止 {name} 失败", e)

    def prepare_for_shutdown(self):
        if self._shutdown_prepared:
            return
        self._shutdown_prepared = True

        try:
            save_config(self.config)
        except Exception as e:
            log_debug("退出前保存配置失败", e)

        try:
            self.image_tab.save_image_input_draft()
            self.image_tab.save_persistent_history()
            self.image_tab.save_persistent_task_log()
            self.image_tab.stop_generation()
            self._stop_worker_attrs(self.image_tab, ("worker", "model_worker", "thumbnail_worker"))
        except Exception as e:
            log_debug("退出前清理图片任务失败", e)

        try:
            self.video_tab.save_video_draft()
            self.video_tab.save_persistent_history()
            self.video_tab.stop_generation()
            self._stop_worker_attrs(self.video_tab, ("model_worker",))
            for worker in list(getattr(self.video_tab, "running_tasks", {}).values()):
                self._stop_worker(worker)
        except Exception as e:
            log_debug("退出前清理视频任务失败", e)

        try:
            self.ai_workflow_tab._save_workflow_state()
        except Exception as e:
            log_debug("退出前保存工作流失败", e)

        try:
            self.novel_writing_tab.stop_read_aloud(silent=True, keep_resume=True)
            self.novel_writing_tab.stop_import_candidate_analysis()
            self.novel_writing_tab.stop_chapter_ai_action()
            self._stop_worker_attrs(
                self.novel_writing_tab,
                (
                    "model_worker",
                    "analysis_worker",
                    "writing_worker",
                    "auto_summary_worker",
                    "auto_outline_worker",
                    "read_aloud_worker",
                ),
            )
            for worker in list(getattr(self.novel_writing_tab, "read_aloud_retired_workers", [])):
                self._stop_worker(worker)
            self.novel_writing_tab._save_current_work("退出前保存", refresh_project_list=False)
        except Exception as e:
            log_debug("退出前保存小说项目失败", e)

        try:
            self.adaptation_tab.stop_adaptation()
            self._stop_worker_attrs(self.adaptation_tab, ("model_worker", "adaptation_worker"))
        except Exception as e:
            log_debug("退出前清理改编任务失败", e)

        try:
            self.agent_tab.save_agent_input_draft()
            self.agent_tab.save_current_session_model_config(persist=True)
            self.agent_tab.save_persistent_chat()
            self.agent_tab.stop_current_task()
            self._stop_worker_attrs(self.agent_tab, ("worker", "model_worker"))
            for worker in list(getattr(self.agent_tab, "_zombie_workers", [])):
                self._stop_worker(worker)
        except Exception as e:
            log_debug("退出前清理智能体任务失败", e)

    def closeEvent(self, event):
        try:
            self.prepare_for_shutdown()
            schedule_windows_process_force_exit(delay_seconds=8)
        except Exception as e:
            log_debug("主窗口退出清理失败", e)
        super().closeEvent(event)

class ImageOnlyWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPT 图片生成器")
        fit_window_to_screen(self, 1180, 860, min_width=960, min_height=520)
        self.setMinimumSize(720, 420)

        self.config = load_config()

        self.image_tab = ImageGeneratorTab(self.config)
        self.setCentralWidget(self.image_tab)
        self.image_tab.request_settings.connect(self.open_provider_manager)

        QTimer.singleShot(0, self.image_tab.load_models)

    def open_provider_manager(self):
        dlg = ProviderManagerDialog(self.config.get("providers", []), self)
        if not dlg.exec():
            return

        self.config["providers"] = dlg.get_providers()
        valid_ids = {p["id"] for p in self.config["providers"]}

        if self.config["image"].get("provider_id") not in valid_ids:
            self.config["image"]["provider_id"] = (
                self.config["providers"][0]["id"] if self.config["providers"] else ""
            )

        save_config(self.config)
        self.image_tab.refresh_providers()
        self.image_tab.load_models()

# ============================================================
# 中文右键菜单：支持 QTextEdit / QLineEdit / QPlainTextEdit
# ============================================================

class ChineseContextMenuFilter(QObject):
    """
    中文右键菜单过滤器。

    支持：
    1. QLineEdit / QTextEdit / QPlainTextEdit：
       使用 Qt 原生 createStandardContextMenu()，只翻译文字，动作保持原生有效。

    """

    def eventFilter(self, obj, event):
        try:
            if event.type() != QEvent.ContextMenu:
                return super().eventFilter(obj, event)

            global_pos = event.globalPos()

            # 1. 先处理普通文本编辑控件
            editor = self._find_editor(obj, global_pos)
            if editor is not None:
                menu = self._create_editor_menu(editor, global_pos)
                if menu is None:
                    return super().eventFilter(obj, event)

                self._translate_menu(menu)
                try:
                    menu.exec(global_pos)
                finally:
                    menu.deleteLater()
                return True

        except Exception as e:
            log_debug("右键菜单处理失败", e)
            return False

        return super().eventFilter(obj, event)

    def _parents(self, w):
        result = []
        cur = w
        for _ in range(12):
            if cur is None:
                break
            result.append(cur)
            try:
                cur = cur.parent()
            except Exception:
                break
        return result

    def _candidate_widgets(self, obj, global_pos):
        candidates = []

        try:
            candidates.extend(self._parents(obj))
        except Exception as e:
            log_debug("右键菜单翻译失败", e)

        try:
            w = QApplication.widgetAt(global_pos)
            candidates.extend(self._parents(w))
        except Exception:
            pass

        try:
            fw = QApplication.focusWidget()
            candidates.extend(self._parents(fw))
        except Exception:
            pass

        out = []
        seen = set()
        for w in candidates:
            try:
                key = id(w)
                if key in seen:
                    continue
                seen.add(key)
                out.append(w)
            except Exception:
                pass

        return out

    def _find_editor(self, obj, global_pos):
        for w in self._candidate_widgets(obj, global_pos):
            try:
                if w.property("agent_clean_copy_context_menu"):
                    return None
            except Exception:
                pass
            if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)):
                return w
        return None

    def _create_editor_menu(self, editor, global_pos):
        try:
            local_pos = editor.mapFromGlobal(global_pos)
            return editor.createStandardContextMenu(local_pos)
        except Exception:
            try:
                return editor.createStandardContextMenu()
            except Exception:
                return None

    def _translate_menu(self, menu):
        try:
            for act in menu.actions():
                if act.isSeparator():
                    continue

                text = str(act.text() or "")
                clean = text.replace("&", "").split("\t")[0].strip()

                mapping = {
                    "Undo": "撤销",
                    "Redo": "重做",
                    "Cut": "剪切",
                    "Copy": "复制",
                    "Paste": "粘贴",
                    "Delete": "删除",
                    "Select All": "全选",
                    "Copy Link Location": "复制链接地址",
                    "Open Link": "打开链接",
                    "Copy Image": "复制图片",
                    "Save Image": "保存图片",
                    "Save Image As...": "图片另存为...",
                }

                if clean in mapping:
                    act.setText(mapping[clean])

                sub = act.menu()
                if sub:
                    self._translate_menu(sub)
        except Exception:
            pass


def install_chinese_context_menu(app):
    """
    安装中文右键菜单过滤器。
    """
    try:
        filt = ChineseContextMenuFilter(app)
        app.installEventFilter(filt)
        app._chinese_context_menu_filter = filt
    except Exception as e:
        log_debug("安装中文右键菜单失败", e)


def main():
    # macOS 原生文件选择器中文化：
    #
    # 必须在 QApplication 创建之前，通过命令行参数告诉 Cocoa 使用中文。
    # 这样 NSOpenPanel / NSSavePanel 会显示：
    #   个人收藏 / 最近使用 / 应用程序 / 桌面 / 文稿 / 下载
    #   iCloud 云盘 / 共享 / 位置 / 标签
    #   打开 / 取消 / 新建文件夹 / 选项
    #   昨天 / 前 7 天 等日期分组
    #
    # 如果用户在命令行手动指定了 -AppleLanguages，就尊重用户配置。
    if sys.platform == "darwin":
        if "-AppleLanguages" not in sys.argv:
            sys.argv = sys.argv[:1] + ["-AppleLanguages", "(zh-Hans)"] + sys.argv[1:]

        # 同时设置环境变量，部分子进程或 Qt 路径会读取这些值
        os.environ.setdefault("LANG", "zh_CN.UTF-8")
        os.environ.setdefault("LC_ALL", "zh_CN.UTF-8")
        os.environ.setdefault("AppleLanguages", "(zh-Hans)")

    # macOS 原生文件选择器尽量使用中文界面
    if sys.platform == "darwin":
        os.environ.setdefault("AppleLanguages", "(zh-Hans)")
        os.environ.setdefault("AppleLocale", "zh_CN")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(APP_STYLE + CONTEXT_MENU_FEEDBACK_STYLE)

    # 安装中文右键菜单过滤器。
    # 关键：如果不调用这里，QTextEdit/QLineEdit 右键菜单仍会显示 Undo/Redo/Cut/Copy。
    try:
        install_chinese_context_menu(app)
    except Exception as e:
        log_debug("安装中文右键菜单失败", e)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
