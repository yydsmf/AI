"""番茄小说批量上传的配置、校验和独立浏览器任务。

平台页面结构可能随后台改版变化，因此浏览器选择器集中在本模块；章节页只负责
配置任务、启动线程和显示状态。默认只保存草稿，不执行发布动作。
"""

import os
import re
import threading
import time
from copy import deepcopy
from urllib.parse import parse_qs, urljoin, urlsplit

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .core import APP_DIR, clean_error_text, now_str
from .novel_storage import load_json_file, save_project_file
from .novel_utils import _normalize_fanqie_upload_state as normalize_fanqie_upload_state
from .optional_components import OptionalComponentError, load_playwright_sync_api


FANQIE_WRITER_ZONE_URL = "https://fanqienovel.com/writer/zone/"
FANQIE_AUTHOR_HOME_URL = "https://fanqienovel.com/main/writer"
FANQIE_PUBLISH_URL_TEMPLATE = "https://fanqienovel.com/main/writer/{work_id}/publish/"
FANQIE_PROFILE_DIR = os.path.join(APP_DIR, "fanqie_browser_profile")
FANQIE_UPLOAD_SCHEMA_VERSION = 1
_PROJECT_WRITE_LOCK = threading.RLock()
# Playwright persistent contexts cannot open the same user-data directory at
# the same time.  Keep the login session shared while serializing browser
# access across projects and the work-list reader.
_BROWSER_PROFILE_LOCK = threading.Lock()


class FanqieUploadError(RuntimeError):
    """上传流程可以直接展示给用户的错误。"""


class FanqieLoginRequired(FanqieUploadError):
    """独立浏览器没有可用的登录状态。"""


class FanqieUploadCancelled(FanqieUploadError):
    """用户中止了上传任务。"""


def _as_int(value, default=0, minimum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    return result


def _chapter_id(chapter, index):
    if isinstance(chapter, dict):
        value = str(chapter.get("id", "") or "").strip()
        if value:
            return value
    return f"chapter-{index + 1}"


def validate_chapter_upload_range(project, start_chapter, end_chapter):
    """Return errors/warnings for the selected local chapter range."""
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    start = _as_int(start_chapter, 1, 1)
    end = _as_int(end_chapter, len(chapters), 0)
    errors = []
    warnings = []
    if not chapters:
        errors.append("当前项目没有章节。")
        return {"errors": errors, "warnings": warnings, "count": 0}
    if end <= 0:
        end = len(chapters)
    if start > end:
        errors.append("起始章节不能大于结束章节。")
    if start > len(chapters) or end > len(chapters):
        errors.append(f"章节范围超出当前项目，共有 {len(chapters)} 章。")
    if errors:
        return {"errors": errors, "warnings": warnings, "count": 0}
    seen_ids = set()
    for number in range(start, end + 1):
        chapter = chapters[number - 1]
        if not isinstance(chapter, dict):
            errors.append(f"第{number}章数据不是有效章节记录。")
            continue
        title = str(chapter.get("title", "") or "").strip()
        text = str(chapter.get("text", "") or "").strip()
        if not title:
            errors.append(f"第{number}章缺少章节标题。")
        if not text:
            errors.append(f"第{number}章没有正文，不能上传。")
        chapter_id = _chapter_id(chapter, number - 1)
        if chapter_id in seen_ids:
            errors.append(f"第{number}章与范围内其他章节使用了重复章节 ID。")
        seen_ids.add(chapter_id)
        if len(text) < 80:
            warnings.append(f"第{number}章正文只有 {len(text)} 个字符，请确认不是空壳章节。")
    return {"errors": errors, "warnings": warnings, "count": max(0, end - start + 1)}


def build_fanqie_upload_task(project_path, config, project=None):
    """Build an immutable worker task from the dialog configuration."""
    config = config if isinstance(config, dict) else {}
    project = project if isinstance(project, dict) else load_json_file(project_path, {})
    if not isinstance(project, dict):
        raise FanqieUploadError("无法读取要上传的本地项目。")
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    start = _as_int(config.get("start_chapter", 1), 1, 1)
    end = _as_int(config.get("end_chapter", len(chapters)), len(chapters), 0)
    validation = validate_chapter_upload_range(project, start, end)
    if validation["errors"]:
        raise FanqieUploadError("\n".join(validation["errors"]))
    work_id = str(config.get("platform_work_id", "") or "").strip()
    work_title = str(config.get("platform_work_title", "") or "").strip()
    work_url = str(config.get("platform_work_url", "") or "").strip()
    if not work_id and not work_url:
        raise FanqieUploadError("请选择番茄后台的目标作品。")
    if not work_title:
        work_title = work_id or "番茄目标作品"
    return {
        "project_path": os.path.abspath(os.path.realpath(str(project_path))),
        "platform_work_id": work_id,
        "platform_work_title": work_title,
        "platform_work_url": work_url,
        "start_chapter": start,
        "end_chapter": end,
        "mode": "draft",
        "headless": bool(config.get("headless", True)),
        "resume": bool(config.get("resume", True)),
    }


def _extract_id_from_url(url):
    text = str(url or "").strip()
    if not text:
        return ""
    query = parse_qs(urlsplit(text).query)
    for key in ("book_id", "bookId", "id"):
        values = query.get(key) or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    for pattern in (r"/(?:book|works?|writer)/([0-9A-Za-z_-]+)", r"/(\d{5,})"):
        match = re.search(pattern, urlsplit(text).path)
        if match:
            return match.group(1)
    return ""


def _browser_executable_path():
    override = str(os.environ.get("FANQIE_BROWSER_EXECUTABLE", "") or "").strip()
    if override and os.path.isfile(override):
        return override
    candidates = []
    if os.name == "nt":
        candidates.extend([
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ])
    elif os.sys.platform == "darwin":
        candidates.extend([
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    else:
        candidates.extend(["/usr/bin/microsoft-edge", "/usr/bin/google-chrome", "/usr/bin/chromium"])
    return next((path for path in candidates if os.path.isfile(path)), "")


def _load_playwright_sync_api(progress_callback=None):
    """Load Playwright lazily, installing the optional runtime on first use."""
    try:
        return load_playwright_sync_api(progress_callback=progress_callback)
    except OptionalComponentError as exc:
        detail = clean_error_text(exc)
        raise FanqieUploadError(
            "番茄批量上传需要 Playwright 运行库，程序已尝试从国内源自动下载并安装。\n"
            "如果下载失败，可检查网络，或通过 GPT_TOOLBOX_PLAYWRIGHT_INDEX_URL 指定 PyPI 源。\n"
            f"诊断信息：{detail}"
        ) from exc


class _FanqieBrowserSession:
    def __init__(self, headless=False, progress_callback=None):
        self.headless = bool(headless)
        self.progress_callback = progress_callback
        self._playwright = None
        self.context = None
        self.page = None
        self._profile_lock_acquired = False

    def __enter__(self):
        sync_playwright = _load_playwright_sync_api(self.progress_callback)
        os.makedirs(FANQIE_PROFILE_DIR, exist_ok=True)
        _BROWSER_PROFILE_LOCK.acquire()
        self._profile_lock_acquired = True
        try:
            self._playwright = sync_playwright().start()
        except Exception:
            self.close()
            raise
        launch_kwargs = {
            "user_data_dir": FANQIE_PROFILE_DIR,
            "headless": self.headless,
            "viewport": {"width": 1440, "height": 900},
        }
        executable = _browser_executable_path()
        if not executable:
            self.close()
            raise FanqieUploadError(
                "没有找到可用的 Edge、Chrome 或 Chromium 浏览器。\n"
                "请先安装其中一个浏览器后重试；程序不会自动下载浏览器本体。"
            )
        launch_kwargs["executable_path"] = executable
        try:
            self.context = self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:
            self.close()
            raise FanqieUploadError(f"无法启动番茄独立浏览器：{clean_error_text(exc)}") from exc
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def close(self):
        try:
            if self.context is not None:
                self.context.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self.context = None
        self.page = None
        self._playwright = None
        if self._profile_lock_acquired:
            self._profile_lock_acquired = False
            _BROWSER_PROFILE_LOCK.release()

    def __exit__(self, *_args):
        self.close()

    def _goto(self, url, allow_login=False):
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            raise FanqieUploadError(f"打开番茄后台失败：{clean_error_text(exc)}") from exc
        try:
            self.page.wait_for_timeout(900)
        except Exception:
            pass
        if not allow_login and self._looks_like_login_page():
            raise FanqieLoginRequired("番茄后台登录状态已失效，请先点击读取作品列表并在独立浏览器中完成登录。")

    def _looks_like_login_page(self):
        try:
            url = str(self.page.url or "").lower()
            body = str(self.page.locator("body").inner_text(timeout=1500) or "")[:6000]
        except Exception:
            return False
        if any(token in url for token in ("login", "passport", "account")):
            return True
        return any(token in body for token in ("扫码登录", "手机号登录", "登录后管理作品", "请先登录", "请登录"))

    def _page_text(self):
        try:
            return str(self.page.locator("body").inner_text(timeout=3000) or "")
        except Exception:
            return ""

    def _click_text(self, names, exact=False):
        for name in names:
            try:
                locator = self.page.get_by_text(name, exact=exact)
                if locator.count():
                    locator.first.click(timeout=5000)
                    return True
            except Exception:
                continue
        return False

    def _fill_first(self, selectors, value):
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = min(locator.count(), 12)
                for index in range(count):
                    item = locator.nth(index)
                    if item.is_visible():
                        item.fill(str(value or ""), timeout=5000)
                        return True
            except Exception:
                continue
        return False

    def list_works(self, progress=None, login_wait_seconds=180, should_stop=None):
        progress = progress or (lambda _text: None)
        should_stop = should_stop or (lambda: False)
        self._goto(FANQIE_WRITER_ZONE_URL, allow_login=True)
        self._click_text(("立即登录",), exact=True)
        deadline = time.monotonic() + max(15, int(login_wait_seconds))
        works = []
        while time.monotonic() < deadline:
            if should_stop():
                raise FanqieUploadCancelled("作品列表读取已取消。")
            if self._looks_like_login_page():
                progress("请在番茄独立浏览器窗口中完成登录，登录后将自动读取作品列表...")
            else:
                if "/main/writer" not in str(self.page.url or ""):
                    self._goto(FANQIE_AUTHOR_HOME_URL, allow_login=True)
                works = self._extract_works()
                if works:
                    return works
                progress("已打开番茄后台，正在等待作品列表加载...")
            try:
                self.page.wait_for_timeout(1500)
            except Exception:
                time.sleep(1.5)
            if should_stop():
                raise FanqieUploadCancelled("作品列表读取已取消。")
        if self._looks_like_login_page():
            raise FanqieLoginRequired("等待登录超时，请完成登录后重新读取作品列表。")
        raise FanqieUploadError("没有从番茄后台读取到作品列表，请确认已进入作家后台。")

    def _extract_works(self):
        try:
            records = self.page.evaluate(
                """() => Array.from(document.querySelectorAll('a,button,[role="button"],[data-book-id],[data-id]')).map((el) => ({
                    text: (el.innerText || el.textContent || '').trim(),
                    href: el.href || '',
                    id: el.getAttribute('data-book-id') || el.getAttribute('data-id') || '',
                    title: el.getAttribute('title') || el.getAttribute('aria-label') || ''
                })).filter((item) => item.text || item.id || item.href)"""
            )
        except Exception:
            records = []
        result = []
        seen = set()
        for item in records if isinstance(records, list) else []:
            if not isinstance(item, dict):
                continue
            href = str(item.get("href", "") or "").strip()
            work_id = str(item.get("id", "") or "").strip() or _extract_id_from_url(href)
            title = str(item.get("title", "") or item.get("text", "") or "").strip()
            title = re.sub(r"\s+", " ", title)
            if not work_id or not title or len(title) > 100:
                continue
            if any(token in title for token in ("登录", "退出", "设置", "帮助", "作者中心")):
                continue
            key = (work_id, title)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "id": work_id,
                "title": title,
                "url": urljoin(str(self.page.url or FANQIE_AUTHOR_HOME_URL), href) if href else "",
            })
        return result[:100]

    def upload_chapter(self, work, chapter, progress=None):
        progress = progress or (lambda _text: None)
        work = work if isinstance(work, dict) else {}
        chapter = chapter if isinstance(chapter, dict) else {}
        work_url = str(work.get("url", "") or "").strip()
        if not work_url:
            work_id = str(work.get("id", "") or "").strip()
            work_url = (
                FANQIE_PUBLISH_URL_TEMPLATE.format(work_id=work_id)
                if work_id else FANQIE_AUTHOR_HOME_URL
            )
        self._goto(work_url)
        title = str(chapter.get("title", "") or "").strip()
        text = str(chapter.get("text", "") or "").strip()
        if not title or not text:
            raise FanqieUploadError("章节标题或正文为空，已跳过。")
        if not self._click_text(("新建章节", "创建章节", "新增章节", "写新章节", "章节管理")):
            raise FanqieUploadError("没有找到番茄后台的新增章节入口，请检查后台页面或更新页面适配器。")
        try:
            self.page.wait_for_timeout(700)
        except Exception:
            pass
        if not self._fill_first((
            "input[placeholder*='章节标题']",
            "input[placeholder*='章节名']",
            "input[name*='title']",
            "input[aria-label*='标题']",
            "input[placeholder*='标题']",
        ), title):
            fallback_filled = False
            try:
                inputs = self.page.locator("input[type='text']")
                for index in range(min(inputs.count(), 12)):
                    item = inputs.nth(index)
                    if not item.is_visible():
                        continue
                    placeholder = str(item.get_attribute("placeholder") or "").lower()
                    if any(token in placeholder for token in ("搜索", "search", "查询")):
                        continue
                    item.fill(title, timeout=5000)
                    fallback_filled = True
                    break
            except Exception:
                fallback_filled = False
            if not fallback_filled:
                raise FanqieUploadError("没有找到章节标题输入框。")
        filled = False
        for selector in ("[contenteditable='true']", ".ProseMirror", "textarea[placeholder*='正文']", "textarea"):
            try:
                locator = self.page.locator(selector)
                count = min(locator.count(), 8)
                for index in range(count):
                    item = locator.nth(index)
                    if item.is_visible():
                        item.fill(text, timeout=7000)
                        filled = True
                        break
                if filled:
                    break
            except Exception:
                continue
        if not filled:
            raise FanqieUploadError("没有找到章节正文编辑区。")
        progress(f"正在保存《{title}》草稿...")
        if not self._click_text(("保存草稿", "存为草稿", "保存"), exact=True):
            if self._click_text(("下一步", "继续"), exact=True):
                try:
                    self.page.wait_for_timeout(500)
                except Exception:
                    pass
            if not self._click_text(("保存草稿", "存为草稿", "保存"), exact=True):
                raise FanqieUploadError("没有找到保存草稿按钮，已停止以避免误触发布。")
        try:
            self.page.wait_for_timeout(900)
        except Exception:
            pass
        body = self._page_text()
        if "发布成功" in body and "保存成功" not in body:
            raise FanqieUploadError("页面进入了发布流程，已停止后续章节上传；请检查番茄后台设置。")
        return True


class FanqieWorkListWorker(QThread):
    progress = Signal(str)
    works_ready = Signal(list)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _is_stopped(self):
        return self._stop_event.is_set() or self.isInterruptionRequested()

    def run(self):
        try:
            with _FanqieBrowserSession(
                headless=False,
                progress_callback=self.progress.emit,
            ) as browser:
                works = browser.list_works(
                    progress=self.progress.emit,
                    should_stop=self._is_stopped,
                )
            self.works_ready.emit(works)
        except FanqieUploadCancelled:
            return
        except Exception as exc:
            self.failed.emit(clean_error_text(exc))


class FanqieBatchUploadWorker(QThread):
    progress = Signal(str)
    chapter_succeeded = Signal(dict)
    state_changed = Signal(dict)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = deepcopy(task if isinstance(task, dict) else {})
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _check_stopped(self):
        if self._stop_event.is_set() or self.isInterruptionRequested():
            raise FanqieUploadCancelled("番茄批量上传已中止。")

    def _persist_state(self, state):
        path = str(self.task.get("project_path", "") or "").strip()
        if not path:
            return
        with _PROJECT_WRITE_LOCK:
            data = load_json_file(path, {})
            if not isinstance(data, dict):
                raise FanqieUploadError("保存上传断点失败：项目文件不是有效 JSON。")
            data["fanqie_upload"] = normalize_fanqie_upload_state(state)
            save_project_file(path, data)
        self.state_changed.emit(deepcopy(data["fanqie_upload"]))

    def _initial_state(self, project):
        existing = normalize_fanqie_upload_state(project.get("fanqie_upload", {}))
        target_id = str(self.task.get("platform_work_id", "") or "").strip()
        target_url = str(self.task.get("platform_work_url", "") or "").strip()
        previous_target = (
            str(existing.get("platform_work_id", "") or "").strip(),
            str(existing.get("platform_work_url", "") or "").strip(),
        )
        same_target = (
            bool(target_id and previous_target[0] and target_id == previous_target[0])
            or bool(not target_id and not previous_target[0] and target_url == previous_target[1])
        )
        if any(previous_target) and not same_target:
            existing["completed_chapter_ids"] = []
            existing["failed_chapters"] = []
            existing["last_successful_chapter_id"] = ""
            existing["last_successful_chapter_number"] = 0
            existing["current_chapter"] = 0
            existing["current_chapter_id"] = ""
        configured = {
            **existing,
            "platform_work_id": target_id,
            "platform_work_title": str(self.task.get("platform_work_title", "") or "").strip(),
            "platform_work_url": str(self.task.get("platform_work_url", "") or "").strip(),
            "mode": "draft",
            "start_chapter": _as_int(self.task.get("start_chapter", 1), 1, 1),
            "end_chapter": _as_int(self.task.get("end_chapter", 0), 0, 0),
            "status": "pending",
            "error": "",
            "pause_reason": "",
        }
        if not bool(self.task.get("resume", True)):
            configured["completed_chapter_ids"] = []
            configured["failed_chapters"] = []
            configured["last_successful_chapter_id"] = ""
            configured["last_successful_chapter_number"] = 0
        return normalize_fanqie_upload_state(configured)

    def run(self):
        state = {}
        try:
            path = str(self.task.get("project_path", "") or "").strip()
            project = load_json_file(path, {})
            if not isinstance(project, dict):
                raise FanqieUploadError("无法读取本地小说项目。")
            task = build_fanqie_upload_task(path, self.task, project=project)
            self.task.update(task)
            state = self._initial_state(project)
            self._persist_state(state)
            chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
            validation = validate_chapter_upload_range(
                project, state["start_chapter"], state["end_chapter"]
            )
            if validation["warnings"]:
                self.progress.emit("；".join(validation["warnings"][:2]))
            work = {
                "id": state["platform_work_id"],
                "title": state["platform_work_title"],
                "url": state["platform_work_url"],
            }
            with _FanqieBrowserSession(
                headless=bool(self.task.get("headless", True)),
                progress_callback=self.progress.emit,
            ) as browser:
                for number in range(state["start_chapter"], state["end_chapter"] + 1):
                    self._check_stopped()
                    chapter = chapters[number - 1]
                    chapter_id = _chapter_id(chapter, number - 1)
                    if chapter_id in state["completed_chapter_ids"]:
                        continue
                    state["status"] = "running"
                    state["current_chapter"] = number
                    state["current_chapter_id"] = chapter_id
                    state["updated_at"] = now_str()
                    self._persist_state(state)
                    self.progress.emit(f"正在上传第{number}章：{chapter.get('title', '')}")
                    try:
                        browser.upload_chapter(
                            work,
                            chapter,
                            progress=self.progress.emit,
                        )
                    except FanqieLoginRequired:
                        raise
                    except Exception as exc:
                        error = clean_error_text(exc)
                        state["failed_chapters"] = [
                            item for item in state.get("failed_chapters", [])
                            if item.get("chapter_id") != chapter_id
                        ]
                        state["failed_chapters"].append({
                            "chapter_id": chapter_id,
                            "chapter_number": number,
                            "title": str(chapter.get("title", "") or "").strip(),
                            "error": error,
                            "updated_at": now_str(),
                        })
                        state["status"] = "failed"
                        state["error"] = error
                        state["updated_at"] = now_str()
                        self._persist_state(state)
                        raise
                    state["completed_chapter_ids"] = list(state.get("completed_chapter_ids", []))
                    if chapter_id not in state["completed_chapter_ids"]:
                        state["completed_chapter_ids"].append(chapter_id)
                    state["failed_chapters"] = [
                        item for item in state.get("failed_chapters", [])
                        if item.get("chapter_id") != chapter_id
                    ]
                    state["last_successful_chapter_id"] = chapter_id
                    state["last_successful_chapter_number"] = number
                    state["current_chapter"] = number
                    state["current_chapter_id"] = chapter_id
                    state["updated_at"] = now_str()
                    self._persist_state(state)
                    self.chapter_succeeded.emit({
                        "chapter_id": chapter_id,
                        "chapter_number": number,
                        "title": str(chapter.get("title", "") or "").strip(),
                    })
                state["status"] = "completed"
                state["current_chapter_id"] = ""
                state["error"] = ""
                state["updated_at"] = now_str()
                self._persist_state(state)
                self.completed.emit(deepcopy(state))
        except FanqieUploadCancelled as exc:
            state = normalize_fanqie_upload_state(state)
            state["status"] = "stopped"
            state["error"] = str(exc)
            state["updated_at"] = now_str()
            try:
                self._persist_state(state)
            except Exception:
                pass
            self.completed.emit(deepcopy(state))
        except FanqieLoginRequired as exc:
            state = normalize_fanqie_upload_state(state)
            state["status"] = "paused"
            state["pause_reason"] = clean_error_text(exc)
            state["error"] = state["pause_reason"]
            state["updated_at"] = now_str()
            try:
                self._persist_state(state)
            except Exception:
                pass
            self.completed.emit(deepcopy(state))
        except Exception as exc:
            message = clean_error_text(exc)
            if state:
                state = normalize_fanqie_upload_state(state)
                state["status"] = "failed"
                state["error"] = message
                state["updated_at"] = now_str()
                try:
                    self._persist_state(state)
                except Exception:
                    pass
            self.failed.emit(message)


class FanqieBatchUploadDialog(QDialog):
    """批量上传任务配置窗口。"""

    def __init__(self, project_summaries, current_project_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("番茄批量上传")
        self.setMinimumSize(720, 430)
        self.resize(820, 520)
        self._project_data_cache = {}
        self._work_list_worker = None
        self._close_after_work_list = False
        self._works = []
        self._project_summaries = list(project_summaries or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel("选择本地小说项目和番茄后台目标作品，按章节顺序保存为草稿。任务支持断点续传。")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)

        form = QFormLayout()
        self.project_combo = QComboBox()
        current_path = os.path.abspath(os.path.realpath(str(current_project_path or ""))) if current_project_path else ""
        selected_index = 0
        for index, item in enumerate(self._project_summaries):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "") or "").strip()
            title = str(item.get("title", "") or os.path.basename(path) or "未命名小说").strip()
            self.project_combo.addItem(title, path)
            if path and os.path.abspath(os.path.realpath(path)) == current_path:
                selected_index = self.project_combo.count() - 1
        if self.project_combo.count():
            self.project_combo.setCurrentIndex(selected_index)
        self.project_combo.currentIndexChanged.connect(self._refresh_chapter_range)
        form.addRow("本地小说项目", self.project_combo)

        work_row = QHBoxLayout()
        self.work_combo = QComboBox()
        self.work_combo.addItem("点击右侧读取番茄后台作品", {})
        self.work_combo.currentIndexChanged.connect(self._on_work_changed)
        work_row.addWidget(self.work_combo, 1)
        self.read_works_btn = QPushButton("读取作品列表")
        self.read_works_btn.setObjectName("ghost")
        self.read_works_btn.clicked.connect(self._read_works)
        work_row.addWidget(self.read_works_btn)
        form.addRow("番茄目标作品", work_row)

        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(1)
        self.start_spin.setMaximum(999999)
        self.start_spin.valueChanged.connect(self._refresh_preview)
        self.end_spin = QSpinBox()
        self.end_spin.setMinimum(0)
        self.end_spin.setMaximum(999999)
        self.end_spin.setSpecialValueText("末章")
        self.end_spin.valueChanged.connect(self._refresh_preview)
        range_row = QHBoxLayout()
        range_row.addWidget(self.start_spin)
        range_row.addWidget(QLabel("至"))
        range_row.addWidget(self.end_spin)
        range_row.addStretch(1)
        form.addRow("上传章节范围", range_row)

        self.headless_check = QCheckBox("上传时隐藏独立浏览器窗口")
        self.headless_check.setChecked(True)
        self.resume_check = QCheckBox("跳过已成功章节，继续上次断点")
        self.resume_check.setChecked(True)
        options = QHBoxLayout()
        options.addWidget(self.headless_check)
        options.addWidget(self.resume_check)
        options.addStretch(1)
        form.addRow("任务选项", options)
        root.addLayout(form)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setObjectName("hint")
        root.addWidget(self.preview_label)

        buttons = QDialogButtonBox()
        start_btn = buttons.addButton("开始上传草稿", QDialogButtonBox.AcceptRole)
        start_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_chapter_range()

    def _selected_project_path(self):
        return str(self.project_combo.currentData() or "").strip()

    def _load_selected_project(self):
        path = self._selected_project_path()
        if path not in self._project_data_cache:
            self._project_data_cache[path] = load_json_file(path, {})
        data = self._project_data_cache.get(path)
        return data if isinstance(data, dict) else {}

    def _refresh_chapter_range(self):
        project = self._load_selected_project()
        chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
        count = len(chapters)
        self.start_spin.setMaximum(max(1, count))
        self.end_spin.setMaximum(max(0, count))
        if self.start_spin.value() > max(1, count):
            self.start_spin.setValue(1)
        self.end_spin.setValue(count)
        self._refresh_preview()

    def _refresh_preview(self):
        project = self._load_selected_project()
        validation = validate_chapter_upload_range(
            project, self.start_spin.value(), self.end_spin.value()
        )
        text = f"当前范围：{validation['count']} 章"
        state = project.get("fanqie_upload", {}) if isinstance(project, dict) else {}
        if isinstance(state, dict) and str(state.get("platform_work_id", "") or "").strip():
            completed = state.get("completed_chapter_ids", [])
            failed = state.get("failed_chapters", [])
            completed_count = len(completed) if isinstance(completed, list) else 0
            failed_count = len(failed) if isinstance(failed, list) else 0
            status = str(state.get("status", "") or "").strip()
            text += (
                f"\n已有番茄断点：{completed_count} 章已成功，"
                f"{failed_count} 章失败，状态为“{status or '未开始'}”；"
                "选择同一作品并保留断点续传即可继续。"
            )
        if validation["errors"]:
            text += "\n" + "\n".join(validation["errors"][:4])
        elif validation["warnings"]:
            text += "\n提示：" + "；".join(validation["warnings"][:2])
        self.preview_label.setText(text)

    def _read_works(self):
        if self._work_list_worker is not None and self._work_list_worker.isRunning():
            return
        self.read_works_btn.setEnabled(False)
        self.read_works_btn.setText("读取中...")
        self.preview_label.setText("正在打开独立浏览器读取番茄作品列表；首次使用时请在窗口中完成登录。")
        worker = FanqieWorkListWorker(self)
        self._work_list_worker = worker
        worker.progress.connect(self.preview_label.setText)
        worker.works_ready.connect(self._on_works_ready)
        worker.failed.connect(self._on_works_failed)
        worker.finished.connect(self._cleanup_work_list_worker)
        worker.start()

    def reject(self):
        worker = self._work_list_worker
        if worker is not None and worker.isRunning():
            self._close_after_work_list = True
            worker.stop()
            worker.requestInterruption()
            self.preview_label.setText("正在关闭番茄独立浏览器，请稍候...")
            return
        super().reject()

    def closeEvent(self, event):
        worker = self._work_list_worker
        if worker is not None and worker.isRunning():
            self._close_after_work_list = True
            worker.stop()
            worker.requestInterruption()
            self.preview_label.setText("正在关闭番茄独立浏览器，请稍候...")
            event.ignore()
            return
        super().closeEvent(event)

    def _cleanup_work_list_worker(self):
        worker = self._work_list_worker
        self._work_list_worker = None
        self.read_works_btn.setEnabled(True)
        self.read_works_btn.setText("读取作品列表")
        if worker is not None:
            worker.deleteLater()
        if self._close_after_work_list:
            self._close_after_work_list = False
            super().reject()

    def _on_works_failed(self, message):
        self.preview_label.setText(str(message or "读取番茄作品列表失败。"))

    def _on_works_ready(self, works):
        self._works = [item for item in works if isinstance(item, dict)]
        self.work_combo.clear()
        for item in self._works:
            self.work_combo.addItem(
                str(item.get("title", "") or item.get("id", "") or "未命名作品"),
                deepcopy(item),
            )
        if self._works:
            state = self._load_selected_project().get("fanqie_upload", {})
            previous_id = str(state.get("platform_work_id", "") or "").strip() if isinstance(state, dict) else ""
            if previous_id:
                for index, item in enumerate(self._works):
                    if str(item.get("id", "") or "").strip() == previous_id:
                        self.work_combo.setCurrentIndex(index)
                        break
            self.preview_label.setText(f"已读取 {len(self._works)} 部番茄作品，请选择目标作品后开始上传。")
        else:
            self.work_combo.addItem("没有读取到作品", {})

    def _on_work_changed(self):
        item = self.work_combo.currentData()
        if isinstance(item, dict) and item.get("id"):
            self.preview_label.setText(
                f"目标作品：{item.get('title', '')}；上传模式：仅保存草稿。"
            )

    def _accept(self):
        project = self._load_selected_project()
        item = self.work_combo.currentData()
        if not isinstance(item, dict) or not str(item.get("id", "") or "").strip():
            QMessageBox.warning(self, "番茄批量上传", "请先读取并选择番茄后台目标作品。")
            return
        validation = validate_chapter_upload_range(
            project, self.start_spin.value(), self.end_spin.value()
        )
        if validation["errors"]:
            QMessageBox.warning(self, "番茄批量上传", "\n".join(validation["errors"]))
            return
        self._config = {
            "project_path": self._selected_project_path(),
            "platform_work_id": str(item.get("id", "") or "").strip(),
            "platform_work_title": str(item.get("title", "") or "").strip(),
            "platform_work_url": str(item.get("url", "") or "").strip(),
            "start_chapter": self.start_spin.value(),
            "end_chapter": self.end_spin.value(),
            "headless": self.headless_check.isChecked(),
            "resume": self.resume_check.isChecked(),
            "mode": "draft",
        }
        try:
            build_fanqie_upload_task(
                self._config["project_path"], self._config, project=project
            )
        except Exception as exc:
            QMessageBox.warning(self, "番茄批量上传", clean_error_text(exc))
            return
        self.accept()

    def config(self):
        return deepcopy(getattr(self, "_config", {}))
