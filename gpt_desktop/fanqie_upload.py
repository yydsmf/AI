"""番茄小说批量上传的配置、校验和独立浏览器任务。

平台页面结构可能随后台改版变化，因此浏览器选择器集中在本模块；章节页负责配置
任务、启动线程和显示状态，支持保存草稿、直接发布和定时发布三种模式。
"""

import os
import json
import re
import signal
import threading
import time
from copy import deepcopy
from datetime import datetime
from html import unescape
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QDate, QTime, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
)

from .core import APP_DIR, clean_error_text, now_str
from .novel_storage import load_json_file, save_project_file
from .novel_utils import _normalize_fanqie_upload_state as normalize_fanqie_upload_state
from .optional_components import OptionalComponentError, load_playwright_sync_api


FANQIE_WRITER_ZONE_URL = "https://fanqienovel.com/writer/zone/"
FANQIE_AUTHOR_HOME_URL = "https://fanqienovel.com/main/writer/?enter_from=author_zone"
FANQIE_BOOK_MANAGE_URL = "https://fanqienovel.com/main/writer/book-manage"
FANQIE_PUBLISH_URL_TEMPLATE = "https://fanqienovel.com/main/writer/{work_id}/publish/"
FANQIE_PROFILE_DIR = os.path.join(APP_DIR, "fanqie_browser_profile")
FANQIE_UPLOAD_SCHEMA_VERSION = 1
FANQIE_UPLOAD_MODES = {"draft", "direct_publish", "scheduled_publish"}
FANQIE_WORK_TYPES = {"unknown", "serial", "completed"}
FANQIE_BROWSER_LAUNCH_TIMEOUT_MS = 30000
FANQIE_BROWSER_PROFILE_LOCK_TIMEOUT_SECONDS = 45
FANQIE_BROWSER_LAUNCH_RETRIES = 2
FANQIE_EDITOR_SAVE_SELECTORS = (
    "button.auto-editor-save-btn",
    "button[aria-label='存草稿']",
)
FANQIE_EDITOR_NEXT_SELECTORS = (
    "button.auto-editor-next",
    "button[aria-label='下一步']",
)
_PROJECT_WRITE_LOCK = threading.RLock()
# Playwright persistent contexts cannot open the same user-data directory at
# the same time.  Keep the login session shared while serializing browser
# access across projects and the work-list reader.
_BROWSER_PROFILE_LOCK = threading.Lock()


def _playwright_launched_pid(error):
    matches = re.findall(r"<launched>\s+pid=(\d+)", str(error or ""))
    if not matches:
        return 0
    try:
        return int(matches[-1])
    except (TypeError, ValueError):
        return 0


def _terminate_playwright_process(pid):
    """Stop only the browser process reported by the failed Playwright launch."""
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except Exception:
        return False
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except Exception:
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    except ProcessLookupError:
        pass
    except Exception:
        return False
    return True


class FanqieUploadError(RuntimeError):
    """上传流程可以直接展示给用户的错误。"""


class FanqieLoginRequired(FanqieUploadError):
    """独立浏览器没有可用的登录状态。"""


class FanqieUploadCancelled(FanqieUploadError):
    """用户中止了上传任务。"""


class FanqieDailyLimitError(FanqieUploadError):
    """番茄后台明确返回连载作品每日发布额度限制。"""


def _normalize_upload_mode(value):
    mode = str(value or "draft").strip().lower()
    aliases = {
        "save_draft": "draft",
        "publish": "direct_publish",
        "direct": "direct_publish",
        "schedule": "scheduled_publish",
        "scheduled": "scheduled_publish",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in FANQIE_UPLOAD_MODES else "draft"


def _normalize_work_type(value):
    value = str(value or "unknown").strip().lower()
    aliases = {
        "serializing": "serial",
        "连载": "serial",
        "连载中": "serial",
        "finished": "completed",
        "finish": "completed",
        "完本": "completed",
        "完结": "completed",
        "已完结": "completed",
    }
    value = aliases.get(value, value)
    return value if value in FANQIE_WORK_TYPES else "unknown"


def _infer_work_type(*values):
    text = " ".join(str(value or "") for value in values).strip().lower()
    if not text:
        return "unknown"
    if any(token in text for token in ("完本", "完结", "已完结", "finished", "finish")):
        return "completed"
    if any(token in text for token in ("连载", "连载中", "serial", "serializing")):
        return "serial"
    return "unknown"


def _is_daily_limit_message(value):
    text = re.sub(r"\s+", "", str(value or ""))
    if not text:
        return False
    if re.search(r"(每日|今日|当天|当日).{0,24}(发布|更新|上传|提交|字数|章节).{0,24}(上限|限制|额度|超出|超过|不足|已满)", text):
        return True
    if re.search(r"(发布|更新|上传|提交).{0,24}(字数|章节).{0,24}(上限|限制|额度|超出|超过|已满)", text):
        return True
    if re.search(r"(每日|今日|当天|当日).{0,24}(字数|章节).{0,24}(超出|超过|不足|已满)", text):
        return True
    return bool(re.search(r"超出.{0,16}(每日|今日|当天|当日).{0,16}(上限|限制|额度)", text))


def _is_prior_scheduled_chapter_warning(value):
    text = re.sub(r"\s+", "", str(value or ""))
    return bool(
        text
        and "有定时待发布章节" in text
        and "建议本章定时发布" in text
    )


def _interpret_publish_response(body):
    """Return ``(success, message, daily_limit)`` for a publish response."""
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except (TypeError, ValueError):
        return None, "", False
    if not isinstance(payload, dict) or "code" not in payload:
        return None, "", False
    code = payload.get("code")
    message = payload.get("message") or payload.get("msg") or ""
    message = str(message or "").strip()
    if code in (0, "0"):
        return True, message, False
    return False, message or f"发布接口返回 code={code}", _is_daily_limit_message(message)


def validate_fanqie_schedule_config(start_date, start_time, *_legacy_args, **_legacy_kwargs):
    """Validate the date and time fields used by Tomato's publish settings."""
    date_text = str(start_date or "").strip()
    time_text = str(start_time or "").strip()
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError as exc:
        raise FanqieUploadError("定时发布起始日期必须是 YYYY-MM-DD。") from exc
    try:
        datetime.strptime(time_text, "%H:%M")
    except ValueError as exc:
        raise FanqieUploadError("定时发布首章时间必须是 HH:MM。") from exc
    return date_text, time_text


def build_fanqie_schedule_entries(start_date, start_time, *args, **kwargs):
    """Build one Tomato date/time entry for every selected chapter.

    Older callers may still pass interval and daily-count arguments. They are
    accepted for state migration but intentionally ignored because they are not
    part of Tomato's publish settings.
    """
    chapters = kwargs.get("chapters")
    if chapters is None:
        if len(args) == 1:
            chapters = args[0]
        elif len(args) >= 3:
            chapters = args[2]
        else:
            chapters = []
    date_text, time_text = validate_fanqie_schedule_config(start_date, start_time)
    result = []
    for index, item in enumerate(chapters if isinstance(chapters, list) else []):
        chapter_number = int(item.get("chapter_number", index + 1)) if isinstance(item, dict) else index + 1
        chapter_id = str(item.get("chapter_id", "") or "").strip() if isinstance(item, dict) else ""
        result.append({
            "chapter_id": chapter_id,
            "chapter_number": chapter_number,
            "publish_date": date_text,
            "publish_time": time_text,
        })
    return result


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
    mode = _normalize_upload_mode(config.get("mode", "draft"))
    requested_mode = str(config.get("mode", "draft") or "draft").strip().lower()
    if requested_mode not in FANQIE_UPLOAD_MODES and requested_mode not in {
        "save_draft", "publish", "direct", "schedule", "scheduled"
    }:
        raise FanqieUploadError(f"不支持的番茄上传模式：{requested_mode}")
    work_type = _normalize_work_type(config.get("work_type", "unknown"))
    schedule_entries = []
    schedule_start_date = str(config.get("schedule_start_date", "") or "").strip()
    schedule_start_time = str(config.get("schedule_start_time", "") or "").strip()
    if mode == "scheduled_publish":
        selected = []
        for number in range(start, end + 1):
            chapter = chapters[number - 1]
            selected.append({
                "chapter_id": _chapter_id(chapter, number - 1),
                "chapter_number": number,
            })
        schedule_entries = build_fanqie_schedule_entries(
            schedule_start_date,
            schedule_start_time,
            selected,
        )
    return {
        "project_path": os.path.abspath(os.path.realpath(str(project_path))),
        "platform_work_id": work_id,
        "platform_work_title": work_title,
        "platform_work_url": work_url,
        "start_chapter": start,
        "end_chapter": end,
        "mode": mode,
        "work_type": work_type,
        "publish_use_ai": bool(
            config.get("publish_use_ai", mode in {"direct_publish", "scheduled_publish"})
        ),
        "schedule_start_date": schedule_start_date,
        "schedule_start_time": schedule_start_time,
        "schedule_entries": schedule_entries,
        "headless": bool(config.get("headless", True)),
        "resume": bool(config.get("resume", True)),
    }


def _extract_id_from_url(url):
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    query = parse_qs(parsed.query)
    work_path = bool(re.search(r"/(?:main/writer|book|work|works?)(?:/|$)", parsed.path))
    if work_path:
        for key in ("book_id", "bookId", "bookID"):
            values = query.get(key) or []
            if values and str(values[0]).strip():
                return str(values[0]).strip()

    # The writer zone contains ordinary navigation links such as
    # ``/writer/zone/`` and ``/writer/copyright/``.  Do not treat the route
    # name as a book ID.  Work links use the main writer route (or a direct
    # book/work route), so only accept those paths here.
    for pattern in (
        r"/main/writer/(?:chapter-manage|book-info|preview)/([0-9A-Za-z_-]+)(?:[/&?]|$)",
        r"/main/writer/([0-9A-Za-z_-]+)(?:[/&?]|$)",
        r"/(?:book|works?)/([0-9A-Za-z_-]+)(?:/|$)",
    ):
        match = re.search(pattern, parsed.path)
        if match:
            candidate = match.group(1).strip()
            if candidate and (any(char.isdigit() for char in candidate) or len(candidate) >= 12):
                return candidate

    # A generic ``id`` query parameter is only useful on a path that already
    # looks like a work page.  This prevents unrelated navigation links from
    # being accepted merely because they contain an ID.
    if work_path:
        values = query.get("id") or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    return ""


def _looks_like_work_id(value):
    value = str(value or "").strip()
    return bool(value) and (any(char.isdigit() for char in value) or len(value) >= 12)


def _is_navigation_title(title):
    normalized = re.sub(r"\s+", "", str(title or "").strip())
    if not normalized:
        return True
    exact_titles = {
        "作家专区",
        "版权专区",
        "营业执照",
        "出版物经营许可证",
        "广播电视节目制作经营许可证",
    }
    if normalized in exact_titles:
        return True
    return normalized.startswith(("京ICP备", "沪ICP备", "粤ICP备"))


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
        if callable(self.progress_callback):
            self.progress_callback("正在启动番茄独立浏览器...")
        if not _BROWSER_PROFILE_LOCK.acquire(
            timeout=FANQIE_BROWSER_PROFILE_LOCK_TIMEOUT_SECONDS
        ):
            raise FanqieUploadError(
                "番茄独立浏览器正在被另一个上传任务占用，等待45秒后仍未释放；"
                "请关闭其他番茄批量上传任务后重试。"
            )
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
        launch_error = None
        for attempt in range(1, FANQIE_BROWSER_LAUNCH_RETRIES + 1):
            try:
                self.context = self._playwright.chromium.launch_persistent_context(
                    **launch_kwargs,
                    timeout=FANQIE_BROWSER_LAUNCH_TIMEOUT_MS,
                )
                break
            except Exception as exc:
                launch_error = exc
                launched_pid = _playwright_launched_pid(exc)
                if launched_pid:
                    _terminate_playwright_process(launched_pid)
                if attempt >= FANQIE_BROWSER_LAUNCH_RETRIES:
                    self.close()
                    detail = clean_error_text(exc)
                    raise FanqieUploadError(
                        "无法启动番茄独立浏览器。已等待并清理本次启动的残留进程，"
                        "但仍未成功；请关闭其他占用番茄独立浏览器配置的窗口后重试。"
                        f"\n诊断信息：{detail}"
                    ) from exc
                if callable(self.progress_callback):
                    self.progress_callback(
                        f"番茄独立浏览器启动未完成，正在清理后第{attempt + 1}次重试..."
                    )
                time.sleep(0.8)
        if self.context is None:
            self.close()
            detail = clean_error_text(launch_error) if launch_error else "未知启动错误"
            raise FanqieUploadError(f"无法启动番茄独立浏览器。\n诊断信息：{detail}")
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        if callable(self.progress_callback):
            self.progress_callback("番茄独立浏览器已启动，正在进入作品发布页...")
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
        return any(
            token in body
            for token in (
                "扫码登录",
                "手机号登录",
                "登录后管理作品",
                "请先登录",
                "请登录",
                "重新登录",
                "登录失效",
            )
        )

    def _page_text(self):
        try:
            return str(self.page.locator("body").inner_text(timeout=3000) or "")
        except Exception:
            return ""

    def _click_text(self, names, exact=False):
        for name in names:
            try:
                locator = self.page.get_by_text(name, exact=exact)
                count = min(locator.count(), 12)
                for index in range(count):
                    item = locator.nth(index)
                    try:
                        if not item.is_visible():
                            continue
                        item.click(timeout=5000)
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    def _click_save_draft_button(self):
        """Click the editor's actual save control after a re-render settles."""
        for selector in FANQIE_EDITOR_SAVE_SELECTORS:
            try:
                locator = self.page.locator(selector)
                for index in range(min(locator.count(), 8)):
                    item = locator.nth(index)
                    if not item.is_visible():
                        continue
                    try:
                        item.click(timeout=7000)
                    except Exception:
                        # The editor can replace the button between the
                        # visibility check and the click.  Force the click on
                        # the exact save selector after that short race.
                        try:
                            item.click(timeout=7000, force=True)
                        except Exception:
                            continue
                    return True
            except Exception:
                continue
        return self._click_editor_button_text(
            ("存草稿", "保存草稿", "存为草稿", "保存")
        )

    def _click_next_editor_button(self):
        """Click the chapter editor's top-right 下一步 action."""
        for selector in FANQIE_EDITOR_NEXT_SELECTORS:
            try:
                locator = self.page.locator(selector)
                for index in range(min(locator.count(), 8)):
                    item = locator.nth(index)
                    if not item.is_visible():
                        continue
                    try:
                        item.click(timeout=7000)
                    except Exception:
                        try:
                            item.click(timeout=7000, force=True)
                        except Exception:
                            continue
                    return True
            except Exception:
                continue
        return self._click_editor_button_text(("下一步",))

    def _click_editor_button_text(self, names):
        """Fallback to exact button text without searching arbitrary page text."""
        get_by_role = getattr(self.page, "get_by_role", None)
        if callable(get_by_role):
            for name in names:
                try:
                    locator = get_by_role("button", name=name, exact=True)
                    for index in range(min(locator.count(), 8)):
                        item = locator.nth(index)
                        if not item.is_visible():
                            continue
                        item.click(timeout=7000)
                        return True
                except Exception:
                    continue
        try:
            locator = self.page.locator("button")
            for index in range(min(locator.count(), 20)):
                item = locator.nth(index)
                if not item.is_visible():
                    continue
                label = str(item.inner_text(timeout=1000) or "").strip()
                if label not in names:
                    continue
                item.click(timeout=7000)
                return True
        except Exception:
            pass
        # Keep lightweight browser adapters and older page versions working.
        return self._click_text(names, exact=True)

    def _wait_for_editor_action(self, mode, timeout_ms=10000):
        """Wait for the one final action shared editor pages expose by mode."""
        if _normalize_upload_mode(mode) == "draft":
            selectors = FANQIE_EDITOR_SAVE_SELECTORS
            names = ("存草稿", "保存草稿", "存为草稿", "保存")
        else:
            selectors = FANQIE_EDITOR_NEXT_SELECTORS
            names = ("下一步",)
        deadline = time.monotonic() + max(0.1, float(timeout_ms) / 1000.0)
        while time.monotonic() < deadline:
            for selector in selectors:
                if self._has_visible((selector,)):
                    return True
            if self._wait_for_text(names, exact=True, timeout_ms=150):
                return True
            try:
                self.page.wait_for_timeout(100)
            except Exception:
                time.sleep(0.1)
        return any(self._has_visible((selector,)) for selector in selectors) or self._wait_for_text(
            names, exact=True, timeout_ms=100
        )

    def _wait_for_text(self, names, exact=False, timeout_ms=10000):
        """Wait for one of the visible text controls used by the editor."""
        get_by_text = getattr(self.page, "get_by_text", None)
        if not callable(get_by_text):
            return True
        deadline = time.monotonic() + max(0.1, float(timeout_ms) / 1000.0)
        while time.monotonic() < deadline:
            for name in names:
                try:
                    locator = get_by_text(name, exact=exact)
                    for index in range(min(locator.count(), 8)):
                        if locator.nth(index).is_visible():
                            return True
                except Exception:
                    continue
            try:
                self.page.wait_for_timeout(150)
            except Exception:
                time.sleep(0.15)
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

    def _read_controlled_input_value(self, item):
        """Read the value React is currently holding for a native input."""
        try:
            value = item.evaluate(
                """(element) => {
                    const key = Object.keys(element).find((name) => name.startsWith('__reactProps'));
                    return key && element[key] ? element[key].value : null;
                }"""
            )
            return None if value is None else str(value).strip()
        except Exception:
            return None

    def _input_value_matches(self, item, expected):
        expected = str(expected or "").strip()
        try:
            if str(item.input_value(timeout=3000) or "").strip() != expected:
                return False
        except Exception:
            return False
        controlled_value = self._read_controlled_input_value(item)
        return controlled_value is None or controlled_value == expected

    def _wait_for_input_value(self, item, expected, timeout_ms=1600):
        deadline = time.monotonic() + max(0.1, float(timeout_ms) / 1000.0)
        while time.monotonic() < deadline:
            if self._input_value_matches(item, expected):
                return True
            try:
                self.page.wait_for_timeout(80)
            except Exception:
                time.sleep(0.08)
        return self._input_value_matches(item, expected)

    def _fill_controlled_first(self, selectors, value):
        """Fill a controlled input and wait until its React value is updated."""
        value = str(value or "").strip()
        select_all_key = "Meta+A" if os.sys.platform == "darwin" else "Control+A"
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = min(locator.count(), 12)
                for index in range(count):
                    item = locator.nth(index)
                    if not item.is_visible():
                        continue
                    # Keep lightweight test doubles and alternate browser
                    # adapters on the existing fill path.
                    if not callable(getattr(item, "evaluate", None)):
                        try:
                            item.fill(value, timeout=5000)
                        except Exception:
                            continue
                        if self._wait_for_input_value(item, value):
                            return True
                        continue
                    try:
                        item.click(timeout=5000)
                        item.press(select_all_key, timeout=3000)
                        item.press("Backspace", timeout=3000)
                        self.page.keyboard.type(value, delay=0)
                        item.press("Tab", timeout=3000)
                    except Exception:
                        try:
                            item.fill(value, timeout=5000)
                        except Exception:
                            continue
                    if self._wait_for_input_value(item, value):
                        return True

                    try:
                        item.fill(value, timeout=5000)
                    except Exception:
                        pass
                    if self._wait_for_input_value(item, value):
                        return True

                    # Some versions of the platform input wrapper ignore a
                    # synthetic keyboard sequence after the editor re-renders.
                    # Trigger the native input event once as a fallback, then
                    # verify the controlled value again before saving.
                    try:
                        item.evaluate(
                            """(element, nextValue) => {
                                const setter = Object.getOwnPropertyDescriptor(
                                    HTMLInputElement.prototype,
                                    'value'
                                )?.set;
                                if (setter) setter.call(element, nextValue);
                                if (element._valueTracker) element._valueTracker.setValue('');
                                element.dispatchEvent(new Event('input', {bubbles: true}));
                                element.dispatchEvent(new Event('change', {bubbles: true}));
                            }""",
                            value,
                        )
                    except Exception:
                        pass
                    if self._wait_for_input_value(item, value):
                        return True
            except Exception:
                continue
        return False

    def _fill_chapter_metadata(self, title, chapter_number, title_selectors, number_selectors):
        """Fill and verify the two controlled fields used by a chapter draft."""
        title = str(title or "").strip()
        chapter_number = str(chapter_number or "").strip()
        title_filled = self._fill_controlled_first(title_selectors, title)
        if not title_filled:
            fallback_filled = False
            try:
                inputs = self.page.locator("input[type='text']")
                for index in range(min(inputs.count(), 12)):
                    item = inputs.nth(index)
                    if not item.is_visible():
                        continue
                    placeholder = str(item.get_attribute("placeholder") or "").lower()
                    class_name = str(item.get_attribute("class") or "").lower()
                    if any(token in placeholder for token in ("搜索", "search", "查询")):
                        continue
                    if "serial-input" in class_name:
                        continue
                    item.fill(title, timeout=5000)
                    fallback_filled = self._wait_for_input_value(item, title)
                    if fallback_filled:
                        break
            except Exception:
                fallback_filled = False
            if not fallback_filled:
                raise FanqieUploadError("没有找到章节标题输入框。")

        number_filled = not chapter_number or self._fill_controlled_first(
            number_selectors, chapter_number
        )
        if chapter_number and not number_filled:
            raise FanqieUploadError(
                f"没有找到章节号输入框，已停止上传第{chapter_number}章，避免生成“第 章”。"
            )

        actual_title = self._read_first_input_value(title_selectors)
        if actual_title != title:
            raise FanqieUploadError(
                f"章节标题回填校验失败：预期“{title}”，实际“{actual_title or '空'}”。"
            )
        if chapter_number:
            actual_number = self._read_first_input_value(number_selectors)
            if actual_number != chapter_number:
                raise FanqieUploadError(
                    f"章节号回填校验失败：预期第{chapter_number}章，实际为“{actual_number or '空'}”。"
                )
        return True

    def _read_first_input_value(self, selectors):
        """Read the first visible input value for a field verification step."""
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = min(locator.count(), 12)
                for index in range(count):
                    item = locator.nth(index)
                    if not item.is_visible():
                        continue
                    return str(item.input_value(timeout=3000) or "").strip()
            except Exception:
                continue
        return None

    def _has_visible(self, selectors):
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                count = min(locator.count(), 12)
                for index in range(count):
                    if locator.nth(index).is_visible():
                        return True
            except Exception:
                continue
        return False

    def _wait_for_visible(self, selectors, timeout_ms=5000):
        deadline = time.monotonic() + max(0.1, float(timeout_ms) / 1000.0)
        while time.monotonic() < deadline:
            if self._has_visible(selectors):
                return True
            try:
                self.page.wait_for_timeout(100)
            except Exception:
                time.sleep(0.1)
        return self._has_visible(selectors)

    def _fill_editor_text(self, locator, text):
        """Use editor input events so the platform updates its internal state."""
        locator.click(timeout=7000)
        try:
            select_all_key = "Meta+A" if os.sys.platform == "darwin" else "Control+A"
            locator.press(select_all_key, timeout=3000)
            locator.press("Backspace", timeout=3000)
        except Exception:
            pass
        self.page.keyboard.type(str(text or ""), delay=0)

    def _read_editor_word_count(self):
        """Read the platform's asynchronously updated正文计数."""
        body = self._page_text()
        match = re.search(r"正文字数\s*(\d+)", body)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _read_editor_text_length(self):
        """Read the editor's internal text, which is the value sent on save."""
        try:
            value = self.page.evaluate(
                """() => {
                    if (window.adapter && typeof window.adapter.getText === 'function') {
                        return window.adapter.getText() || '';
                    }
                    const editor = document.querySelector('.serial-editor .ProseMirror, .ProseMirror');
                    return editor ? (editor.innerText || editor.textContent || '') : '';
                }"""
            )
            return len(re.sub(r"\s+", "", str(value or "")))
        except Exception:
            return None

    def _wait_for_editor_ready(self, text, timeout_ms=8000):
        """Wait until the editor has counted the complete body before saving."""
        expected_count = len(re.sub(r"\s+", "", str(text or "")))
        if expected_count <= 0:
            return False
        deadline = time.monotonic() + max(0.1, float(timeout_ms) / 1000.0)
        while time.monotonic() < deadline:
            editor_length = self._read_editor_text_length()
            if editor_length is not None and editor_length >= max(1, int(expected_count * 0.98)):
                return True
            word_count = self._read_editor_word_count()
            if word_count is not None:
                # Fanqie normally counts non-whitespace characters.  Keep a
                # small tolerance for a platform-side punctuation difference,
                # while rejecting the partial count shown during re-rendering.
                minimum_count = max(1, int(expected_count * 0.98))
                if word_count >= minimum_count:
                    return True
            try:
                self.page.wait_for_timeout(100)
            except Exception:
                time.sleep(0.1)
        editor_length = self._read_editor_text_length()
        if editor_length is not None and editor_length >= max(1, int(expected_count * 0.98)):
            return True
        word_count = self._read_editor_word_count()
        return word_count is not None and word_count >= max(1, int(expected_count * 0.98))

    def _wait_for_save_completion(self, timeout_ms=12000, settle_ms=1800):
        """Wait for the platform's asynchronous draft save to settle."""
        deadline = time.monotonic() + max(0.2, float(timeout_ms) / 1000.0)
        started = time.monotonic()
        last_body = ""
        while time.monotonic() < deadline:
            last_body = self._page_text()
            if "保存失败" in last_body:
                raise FanqieUploadError("番茄后台草稿保存失败。")
            elapsed_ms = (time.monotonic() - started) * 1000
            if "已保存到云端" in last_body or "保存成功" in last_body:
                if elapsed_ms >= 800:
                    return True
            elif "已保存" in last_body and elapsed_ms >= settle_ms:
                # Some editor versions only expose the shorter success label.
                return True
            try:
                self.page.wait_for_timeout(180)
            except Exception:
                time.sleep(0.18)
        if any(token in last_body for token in ("已保存到云端", "已保存", "保存成功")):
            return True
        raise FanqieUploadError("番茄后台草稿保存状态未完成，已停止后续章节上传。")

    def _wait_for_metadata_stable(self, title_selectors, number_selectors, title, chapter_number,
                                  stable_ms=1800, timeout_ms=9000):
        """Require React metadata values to stay correct before saving."""
        deadline = time.monotonic() + max(0.2, float(timeout_ms) / 1000.0)
        stable_since = None
        while time.monotonic() < deadline:
            actual_title = self._read_first_input_value(title_selectors) or ""
            actual_number = self._read_first_input_value(number_selectors) or ""
            if actual_title == title and (not chapter_number or actual_number == chapter_number):
                if stable_since is None:
                    stable_since = time.monotonic()
                if (time.monotonic() - stable_since) * 1000 >= stable_ms:
                    return True
            else:
                stable_since = None
            try:
                self.page.wait_for_timeout(180)
            except Exception:
                time.sleep(0.18)
        return False

    def _save_request_matches_metadata(self, request, title, chapter_number, text=None):
        """Check that a save request contains metadata and the expected body."""
        try:
            if request.method != "POST" or "/api/author/article/cover_article/" not in str(request.url):
                return False
            payload = parse_qs(str(request.post_data or ""), keep_blank_values=True)
            actual_title = str((payload.get("title") or [""])[-1] or "")
            actual_title = re.sub(r"\s+", "", actual_title)
            expected_title = re.sub(r"\s+", "", f"第{chapter_number}章{title}")
            if actual_title != expected_title:
                return False
            if text is None:
                return True
            expected_body = re.sub(r"\s+", "", str(text or ""))
            content = str((payload.get("content") or [""])[-1] or "")
            content = re.sub(r"<[^>]*>", "", unescape(content))
            content = re.sub(r"\s+", "", content)
            if not expected_body or len(content) < max(1, int(len(expected_body) * 0.98)):
                return False
            marker_length = min(40, len(expected_body))
            return (
                expected_body[:marker_length] in content
                and expected_body[-marker_length:] in content
            )
        except Exception:
            return False

    def _save_draft_with_metadata_retry(self, title, chapter_number, title_selectors,
                                         number_selectors, text=None, max_attempts=3):
        """Save slowly and retry if the platform submits a blank metadata payload."""
        request_listener_supported = all(
            callable(getattr(self.page, name, None))
            for name in ("on", "remove_listener")
        )
        for attempt in range(1, max_attempts + 1):
            if not self._wait_for_metadata_stable(
                title_selectors,
                number_selectors,
                title,
                chapter_number,
            ):
                raise FanqieUploadError(
                    f"保存前元数据状态不稳定：预期第{chapter_number}章《{title}》。"
                )
            requests = []
            listener = None
            if request_listener_supported:
                listener = lambda request: requests.append(request)
                self.page.on("request", listener)
            try:
                if not self._wait_for_editor_action("draft", timeout_ms=15000):
                    raise FanqieUploadError("番茄后台保存控件尚未恢复，已停止保存。")
                if not self._click_save_draft_button():
                    raise FanqieUploadError("没有找到右上角“存草稿”按钮，已停止以避免误触发布。")
                if request_listener_supported:
                    deadline = time.monotonic() + 7
                    while time.monotonic() < deadline:
                        if any(
                            self._save_request_matches_metadata(
                                request, title, chapter_number, text=text
                            )
                            for request in requests
                        ):
                            self._wait_for_save_completion()
                            return True
                        try:
                            self.page.wait_for_timeout(180)
                        except Exception:
                            time.sleep(0.18)
                self._wait_for_save_completion()
                if not request_listener_supported or not requests:
                    return True
                if any(
                    self._save_request_matches_metadata(
                        request, title, chapter_number, text=text
                    )
                    for request in requests
                ):
                    return True
            finally:
                if listener is not None:
                    try:
                        self.page.remove_listener("request", listener)
                    except Exception:
                        pass
            if attempt < max_attempts:
                # The editor can autosave the body first with its default
                # "第 章" title. Re-enter both controlled fields and let the
                # metadata update settle before pressing save again.
                self._fill_chapter_metadata(
                    title, chapter_number, title_selectors, number_selectors
                )
                try:
                    self.page.wait_for_timeout(1000)
                except Exception:
                    time.sleep(1)
        raise FanqieUploadError(
            f"番茄后台连续{max_attempts}次提交的章节元数据仍不正确，已停止保存。"
        )

    def _read_transient_publish_feedback(self):
        """Read short lived toast/notification text without making a network call."""
        try:
            value = self.page.evaluate(
                """() => {
                    const selectors = [
                        '.arco-message', '.arco-message-wrapper',
                        '.arco-notification', '.arco-notification-wrapper',
                        '.semi-toast', '.semi-toast-wrapper', '[role="alert"]',
                        '[class*="toast"]', '[class*="notification"]',
                        '[class*="message"]', '.serial-editor-tip',
                        '.arco-modal', '[role="dialog"]'
                    ].join(',');
                    return Array.from(document.querySelectorAll(selectors))
                        .filter((node) => {
                            const style = window.getComputedStyle(node);
                            const rect = node.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0 &&
                                style.display !== 'none' && style.visibility !== 'hidden';
                        })
                        .map((node) => (node.innerText || node.textContent || '').trim())
                        .filter(Boolean)
                        .slice(-20);
                }"""
            )
            if isinstance(value, list):
                return "\n".join(str(item).strip() for item in value if str(item).strip())
            return str(value or "").strip()
        except Exception:
            return ""

    def _classify_publish_feedback(self, text):
        text = str(text or "").strip()
        if not text:
            return "", ""
        if _is_daily_limit_message(text):
            return "daily_limit", text
        normalized = re.sub(r"\s+", "", text)
        if _is_prior_scheduled_chapter_warning(normalized):
            return (
                "confirm_required",
                "番茄提示作品已有前置定时章节，正在再次确认当前发布。",
            )
        if re.search(r"(发布失败|提交失败|上传失败|发布异常|提交异常|内容未通过|无法发布|无法提交|请稍后再试)", normalized):
            return "failed", text
        return "", ""

    def _publish_response_handler(self, verdict_holder):
        def handle(response):
            url = str(getattr(response, "url", "") or "")
            if "publish_article" not in url and "modify_timer" not in url:
                return
            try:
                payload = response.json()
            except Exception:
                try:
                    payload = response.text()
                except Exception:
                    payload = ""
            success, message, daily_limit = _interpret_publish_response(payload)
            if success is None:
                return
            verdict_holder["success"] = bool(success)
            verdict_holder["message"] = str(message or "")
            verdict_holder["daily_limit"] = bool(daily_limit)
        return handle

    def _publish_settings_visible(self):
        try:
            modals = self.page.locator(".arco-modal,[role='dialog'],.byte-modal-wrapper")
            for index in range(min(modals.count(), 10)):
                modal = modals.nth(index)
                if not modal.is_visible():
                    continue
                if "发布设置" in str(modal.inner_text(timeout=1000) or ""):
                    return True
        except Exception:
            pass
        return False

    def _set_publish_ai_option(self, use_ai=False):
        target = "是" if use_ai else "否"
        try:
            clicked = self.page.evaluate(
                """(target) => {
                    const visible = (node) => {
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        return rect.width > 0 && rect.height > 0 &&
                            style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const labels = Array.from(document.querySelectorAll('label, span, div'));
                    for (const label of labels) {
                        if (!visible(label) || (label.textContent || '').trim() !== target) continue;
                        let parent = label;
                        for (let i = 0; i < 6 && parent; i += 1) {
                            if ((parent.textContent || '').includes('是否使用AI')) {
                                label.click();
                                return true;
                            }
                            parent = parent.parentElement;
                        }
                    }
                    return false;
                }""",
                target,
            )
            return bool(clicked)
        except Exception:
            return False

    def _set_schedule_toggle(self, enabled):
        try:
            result = self.page.evaluate(
                """(enabled) => {
                    const visible = (node) => {
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        return rect.width > 0 && rect.height > 0 &&
                            style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const switches = (root) => Array.from(root.querySelectorAll(
                        'button[role="switch"], .arco-switch, [role="switch"]'
                    )).filter(visible);
                    const texts = Array.from(document.querySelectorAll('label, span, div'));
                    for (const textNode of texts) {
                        if (!visible(textNode) || !(textNode.textContent || '').includes('定时发布')) continue;
                        let parent = textNode;
                        for (let i = 0; i < 6 && parent; i += 1) {
                            const sw = switches(parent)[0];
                            if (!sw) {
                                parent = parent.parentElement;
                                continue;
                            }
                            const checked = sw.getAttribute('aria-checked') === 'true' ||
                                sw.classList.contains('arco-switch-checked');
                            if (checked !== enabled) sw.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                bool(enabled),
            )
            return bool(result)
        except Exception:
            return False

    def _fill_schedule_picker(self, selectors, value, label):
        select_all_key = "Meta+A" if os.sys.platform == "darwin" else "Control+A"
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                for index in range(min(locator.count(), 8)):
                    item = locator.nth(index)
                    if not item.is_visible():
                        continue
                    item.click(timeout=4000)
                    try:
                        item.press(select_all_key, timeout=2000)
                        item.press("Backspace", timeout=2000)
                        self.page.keyboard.type(str(value), delay=45)
                    except Exception:
                        item.fill(str(value), timeout=4000)
                    item.press("Enter", timeout=3000)
                    try:
                        self.page.wait_for_timeout(450)
                    except Exception:
                        time.sleep(0.45)
                    actual = str(item.input_value(timeout=2000) or "").strip()
                    if actual.startswith(str(value)):
                        return True
            except Exception:
                continue
        raise FanqieUploadError(f"{label}没有正确写入，已停止发布。")

    def _configure_publish_settings(self, mode, scheduled_at, use_ai=True):
        use_ai = bool(use_ai)
        target_label = "是" if use_ai else "否"
        if not self._set_publish_ai_option(use_ai=use_ai):
            raise FanqieUploadError(
                f"没有找到“是否使用AI={target_label}”选项，已停止发布。"
            )
        if mode == "scheduled_publish":
            if not self._set_schedule_toggle(True):
                raise FanqieUploadError("没有找到番茄后台的定时发布开关。")
            if not scheduled_at:
                raise FanqieUploadError("定时发布缺少目标时间。")
            date_text, time_text = scheduled_at
            self._fill_schedule_picker(
                ("input[placeholder='请选择日期']", "input[placeholder*='日期']"),
                date_text,
                "定时日期",
            )
            self._fill_schedule_picker(
                ("input[placeholder='请选择时间']", "input[placeholder*='时间']"),
                time_text,
                "定时时间",
            )
        else:
            self._set_schedule_toggle(False)
        if not self._click_text(("确认发布", "确认提交"), exact=True):
            raise FanqieUploadError("没有找到发布设置确认按钮。")

    def _wait_for_publish_result(self, verdict_holder, mode, timeout_ms=22000):
        deadline = time.monotonic() + max(5.0, float(timeout_ms) / 1000.0)
        last_feedback = ""
        prior_schedule_confirmed = False
        while time.monotonic() < deadline:
            success = verdict_holder.get("success")
            if success is True:
                return True
            if success is False:
                message = verdict_holder.get("message") or "番茄发布接口返回失败。"
                if verdict_holder.get("daily_limit"):
                    raise FanqieDailyLimitError(message)
                if _is_prior_scheduled_chapter_warning(message) and not prior_schedule_confirmed:
                    if self._publish_settings_visible() and self._click_text(
                        ("确认发布", "确认提交"), exact=True
                    ):
                        prior_schedule_confirmed = True
                        verdict_holder.pop("success", None)
                        verdict_holder.pop("message", None)
                        verdict_holder.pop("daily_limit", None)
                        continue
                raise FanqieUploadError(message)
            feedback = self._read_transient_publish_feedback()
            if feedback:
                last_feedback = feedback
                kind, message = self._classify_publish_feedback(feedback)
                if kind == "daily_limit":
                    raise FanqieDailyLimitError(message)
                if kind == "confirm_required":
                    if not prior_schedule_confirmed and self._publish_settings_visible():
                        if self._click_text(("确认发布", "确认提交"), exact=True):
                            prior_schedule_confirmed = True
                            continue
                if kind == "failed":
                    raise FanqieUploadError(message)
            page_text = self._page_text()
            if any(token in page_text for token in ("发布成功", "提交成功", "定时发布成功", "已进入审核")):
                return True
            current_path = urlsplit(str(getattr(self.page, "url", "") or "")).path
            if "/chapter-manage/" in current_path and "/publish/" not in current_path:
                return True
            try:
                self.page.wait_for_timeout(450)
            except Exception:
                time.sleep(0.45)
        detail = last_feedback or "未收到发布接口成功响应或页面成功提示"
        raise FanqieUploadError(f"番茄{('定时' if mode == 'scheduled_publish' else '直接')}发布结果未确认：{detail}")

    def _publish_chapter(self, title, text, mode, scheduled_at, use_ai, progress):
        if mode not in {"direct_publish", "scheduled_publish"}:
            raise FanqieUploadError(f"不支持的发布模式：{mode}")
        progress(
            f"正在{('定时' if mode == 'scheduled_publish' else '直接')}发布《{title}》..."
        )
        verdict_holder = {}
        listener = self._publish_response_handler(verdict_holder)
        listener_supported = callable(getattr(self.page, "on", None))
        if listener_supported:
            self.page.on("response", listener)
        try:
            if not self._click_next_editor_button():
                raise FanqieUploadError("没有找到“下一步”按钮，已停止发布。")
            try:
                self.page.wait_for_timeout(300)
            except Exception:
                time.sleep(0.3)
            for _ in range(70):
                feedback = self._read_transient_publish_feedback()
                kind, message = self._classify_publish_feedback(feedback)
                if kind == "daily_limit":
                    raise FanqieDailyLimitError(message)
                if kind == "failed":
                    raise FanqieUploadError(message)
                if self._publish_settings_visible():
                    self._configure_publish_settings(mode, scheduled_at, use_ai=use_ai)
                    return self._wait_for_publish_result(verdict_holder, mode)
                modal_text = re.sub(r"\s+", "", feedback)
                if "检测到你还有错别字未修改" in modal_text and "是否确定提交" in modal_text:
                    if not self._click_text(("提交",), exact=True):
                        raise FanqieUploadError("错别字提交提示未能确认，已停止发布。")
                elif (
                    "请选择内容检测方式" in modal_text
                    or ("仅基础检测" in modal_text and "全面检测" in modal_text)
                ):
                    if not self._click_text(("仅基础检测",), exact=True):
                        raise FanqieUploadError("内容检测方式未能选择“仅基础检测”，已停止发布。")
                if verdict_holder.get("success") is False:
                    return self._wait_for_publish_result(verdict_holder, mode)
                try:
                    self.page.wait_for_timeout(450)
                except Exception:
                    time.sleep(0.45)
            raise FanqieUploadError("发布流程未进入发布设置，已停止后续章节。")
        finally:
            if listener_supported:
                try:
                    self.page.remove_listener("response", listener)
                except Exception:
                    pass

    def _verify_saved_draft(self, title, chapter_number, text, title_selectors, number_selectors):
        """Reload a newly created draft and verify the values persisted remotely."""
        page_url = str(getattr(self.page, "url", "") or "")
        if not re.search(r"/publish/[0-9A-Za-z_-]+(?:/|$)", page_url):
            return
        deadline = time.monotonic() + 12
        expected_body_length = len(re.sub(r"\s+", "", str(text or "")))
        last_actual_title = ""
        last_actual_number = ""
        last_actual_body_length = None
        for reload_attempt in range(3):
            try:
                if reload_attempt:
                    self.page.wait_for_timeout(1400)
                self.page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                raise FanqieUploadError(f"草稿保存后回读失败：{clean_error_text(exc)}") from exc
            while time.monotonic() < deadline:
                last_actual_title = self._read_first_input_value(title_selectors) or ""
                last_actual_number = self._read_first_input_value(number_selectors) or ""
                last_actual_body_length = self._read_editor_text_length()
                if (
                    last_actual_title == title
                    and (not chapter_number or last_actual_number == chapter_number)
                    and last_actual_body_length is not None
                    and last_actual_body_length >= max(1, int(expected_body_length * 0.98))
                ):
                    return
                try:
                    self.page.wait_for_timeout(250)
                except Exception:
                    time.sleep(0.25)
            deadline = time.monotonic() + 12
        actual_title = self._read_first_input_value(title_selectors) or ""
        actual_number = self._read_first_input_value(number_selectors) or ""
        actual_body_length = self._read_editor_text_length()
        raise FanqieUploadError(
            "草稿保存后回读校验失败："
            f"预期第{chapter_number or '空'}章《{title}》，"
            f"实际为第{actual_number or '空'}章《{actual_title or '空'}》，"
            f"正文长度 {actual_body_length or 0}/{expected_body_length}。"
        )

    def _dismiss_resume_prompt(self):
        """Discard a stale browser draft before creating the next chapter."""
        try:
            modals = self.page.locator(".byte-modal-wrapper,[role='dialog']")
            for index in range(min(modals.count(), 8)):
                modal = modals.nth(index)
                if not modal.is_visible():
                    continue
                modal_text = str(modal.inner_text(timeout=1000) or "")
                if "有刚刚更新的草稿" not in modal_text:
                    continue
                for name in ("放弃继续编辑", "放弃", "取消继续编辑"):
                    try:
                        locator = modal.get_by_text(name, exact=True)
                        if locator.count():
                            locator.first.click(timeout=3000)
                            try:
                                self.page.wait_for_timeout(400)
                            except Exception:
                                pass
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    def list_works(
        self,
        progress=None,
        login_wait_seconds=180,
        should_stop=None,
        interactive_login=True,
    ):
        progress = progress or (lambda _text: None)
        should_stop = should_stop or (lambda: False)
        work_list_payloads = []

        def capture_work_list_response(response):
            path = urlsplit(str(response.url or "")).path
            if path not in (
                "/api/author/book/book_list/v0/",
                "/api/author/homepage/book_list/v0/",
            ):
                return
            try:
                payload = response.json()
            except Exception:
                return
            if isinstance(payload, dict):
                work_list_payloads.append(payload)

        try:
            self.page.on("response", capture_work_list_response)
        except Exception:
            pass

        self._goto(FANQIE_WRITER_ZONE_URL, allow_login=True)
        self._click_text(("立即登录",), exact=True)
        wait_seconds = 35 if not interactive_login else max(15, int(login_wait_seconds))
        deadline = time.monotonic() + wait_seconds
        works = []
        try:
            while time.monotonic() < deadline:
                if should_stop():
                    raise FanqieUploadCancelled("作品列表读取已取消。")
                if self._looks_like_login_page():
                    if not interactive_login:
                        raise FanqieLoginRequired(
                            "番茄后台当前没有有效登录状态，需要打开浏览器完成登录。"
                        )
                    progress("请在番茄独立浏览器窗口中完成登录，登录后将自动读取作品列表...")
                else:
                    current_path = urlsplit(str(self.page.url or "")).path.rstrip("/")
                    if current_path != "/main/writer/book-manage":
                        self._goto(FANQIE_BOOK_MANAGE_URL, allow_login=True)
                    works = self._extract_works_from_payloads(work_list_payloads)
                    if not works:
                        works = self._extract_works()
                    if works:
                        return works
                    progress("已打开番茄作品管理页，正在等待作品列表加载...")
                try:
                    self.page.wait_for_timeout(1500)
                except Exception:
                    time.sleep(1.5)
                if should_stop():
                    raise FanqieUploadCancelled("作品列表读取已取消。")
            if self._looks_like_login_page():
                raise FanqieLoginRequired("等待登录超时，请完成登录后重新读取作品列表。")
            raise FanqieUploadError("没有从番茄后台读取到作品列表，请确认已进入作家后台。")
        finally:
            try:
                self.page.remove_listener("response", capture_work_list_response)
            except Exception:
                pass

    def _extract_works_from_payloads(self, payloads):
        result = []
        seen = set()
        for payload in payloads if isinstance(payloads, list) else []:
            data = payload.get("data") if isinstance(payload, dict) else None
            book_list = data.get("book_list") if isinstance(data, dict) else None
            if not isinstance(book_list, list):
                continue
            for item in book_list:
                if not isinstance(item, dict):
                    continue
                work_id = str(item.get("book_id", "") or "").strip()
                title = str(item.get("book_name", "") or "").strip()
                if not work_id or not title or _is_navigation_title(title):
                    continue
                status_text = " ".join(
                    str(item.get(key, "") or "").strip()
                    for key in (
                        "status",
                        "book_status",
                        "serial_status",
                        "book_serial_status",
                        "finish_status",
                    )
                )
                key = (work_id, title)
                if key in seen:
                    continue
                seen.add(key)
                result.append({
                    "id": work_id,
                    "title": re.sub(r"\s+", " ", title),
                    "url": FANQIE_PUBLISH_URL_TEMPLATE.format(work_id=work_id),
                    "status": status_text,
                    "work_type": _infer_work_type(title, status_text),
                })
        return result[:100]

    def _extract_works(self):
        try:
            records = self.page.evaluate(
                """() => {
                    const records = [];
                    const add = (text, href = '', bookId = '', id = '', title = '', card = false, status = '') => {
                        records.push({text, href, book_id: bookId, id, title, card, status});
                    };
                    const cards = Array.from(document.querySelectorAll('.home-book-item, .book-item-info'));
                    cards.forEach((card) => {
                        const titleNode = card.querySelector('.info-content-title, [class*="info-content-title"]');
                        const text = (titleNode?.innerText || '').trim();
                        const href = Array.from(card.querySelectorAll('a[href]'))
                            .map((el) => el.href || '')
                            .find((value) => /\\/main\\/writer\\//.test(value)) || '';
                        if (text && href) add(text, href, '', '', '', true, card.innerText || '');
                    });
                    Array.from(document.querySelectorAll('a,button,[role="button"],[data-book-id],[data-bookid],[data-work-id],[data-id]')).forEach((el) => add(
                        (el.innerText || el.textContent || '').trim(),
                        el.href || '',
                        el.getAttribute('data-book-id') || el.getAttribute('data-bookid') || el.getAttribute('data-work-id') || '',
                        el.getAttribute('data-id') || '',
                        el.getAttribute('title') || el.getAttribute('aria-label') || '',
                        false,
                        el.innerText || el.textContent || ''
                    ));
                    return records.filter((item) => item.text || item.id || item.href);
                }"""
            )
        except Exception:
            records = []
        result = []
        seen = set()
        records = records if isinstance(records, list) else []
        has_card_records = any(
            isinstance(item, dict) and bool(item.get("card")) for item in records
        )
        for item in records:
            if not isinstance(item, dict):
                continue
            href = str(item.get("href", "") or "").strip()
            explicit_work_id = str(item.get("book_id", "") or "").strip()
            generic_id = str(item.get("id", "") or "").strip()
            if has_card_records and not item.get("card") and not explicit_work_id:
                continue
            work_id = explicit_work_id or _extract_id_from_url(href)
            title = str(item.get("title", "") or item.get("text", "") or "").strip()
            title = re.sub(r"\s+", " ", title)
            if not work_id and _looks_like_work_id(generic_id):
                work_id = generic_id
            if not work_id or not title or len(title) > 100:
                continue
            if _is_navigation_title(title) or any(
                token in title for token in ("登录", "退出", "设置", "帮助", "作者中心")
            ):
                continue
            key = (work_id, title)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "id": work_id,
                "title": title,
                "url": FANQIE_PUBLISH_URL_TEMPLATE.format(work_id=work_id),
                "status": str(item.get("status", "") or "").strip(),
                "work_type": _infer_work_type(title, item.get("status", "")),
            })
        return result[:100]

    def upload_chapter(
        self,
        work,
        chapter,
        progress=None,
        chapter_number=None,
        mode="draft",
        scheduled_at=None,
        publish_use_ai=True,
    ):
        progress = progress or (lambda _text: None)
        mode = _normalize_upload_mode(mode)
        if mode not in FANQIE_UPLOAD_MODES:
            raise FanqieUploadError(f"不支持的番茄上传模式：{mode}")
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
        self._dismiss_resume_prompt()
        title = str(chapter.get("title", "") or "").strip()
        text = str(chapter.get("text", "") or "").strip()
        if chapter_number is None:
            chapter_number = chapter.get("chapter_number", chapter.get("number"))
        if chapter_number is not None and str(chapter_number).strip():
            chapter_number = str(chapter_number).strip()
            if not re.fullmatch(r"[1-9]\d*", chapter_number):
                raise FanqieUploadError(f"章节序号无效：{chapter_number}")
        else:
            chapter_number = ""
        if not title or not text:
            raise FanqieUploadError("章节标题或正文为空，已跳过。")

        title_selectors = (
            "input[placeholder='请输入标题']",
            "input[placeholder*='章节标题']",
            "input[placeholder*='章节名']",
            "input[name*='title']",
            "input[aria-label*='标题']",
            "input[placeholder*='标题']",
        )
        number_selectors = (
            "span.left-input input.serial-input",
            "input.serial-input:not([placeholder])",
            "input.serial-input",
        )
        body_selectors = (
            ".serial-editor .ProseMirror",
            ".ProseMirror",
            "[contenteditable='true']",
            "textarea[placeholder*='正文']",
            "textarea",
        )
        if not self._wait_for_visible(title_selectors, timeout_ms=15000):
            if not self._click_text(("新建章节", "创建章节", "新增章节", "写新章节", "章节管理")):
                # Directly opening the publish route can take several seconds
                # to create and redirect to a fresh draft, especially after
                # the draft box was emptied. Give that route one more chance
                # before reporting a page-adapter failure.
                try:
                    self.page.wait_for_timeout(1800)
                except Exception:
                    time.sleep(1.8)
                if not self._wait_for_visible(title_selectors, timeout_ms=5000):
                    raise FanqieUploadError("没有找到番茄后台的章节编辑入口，请检查后台页面或更新页面适配器。")
            try:
                self.page.wait_for_timeout(1500)
            except Exception:
                pass
            if not self._wait_for_visible(title_selectors, timeout_ms=15000):
                raise FanqieUploadError("没有找到章节标题输入框。")

        if not self._wait_for_visible(body_selectors, timeout_ms=15000):
            raise FanqieUploadError("没有找到章节正文编辑区。")
        if not self._wait_for_editor_action(mode, timeout_ms=10000):
            raise FanqieUploadError("番茄后台章节编辑页面尚未完成加载，已停止保存。")
        # Set the controlled metadata before typing the body.  This prevents
        # the editor's first autosave from creating a draft with "第 章".
        self._fill_chapter_metadata(
            title, chapter_number, title_selectors, number_selectors
        )
        if not self._wait_for_metadata_stable(
            title_selectors,
            number_selectors,
            title,
            chapter_number,
            stable_ms=1200,
            timeout_ms=9000,
        ):
            raise FanqieUploadError(
                f"正文输入前元数据状态不稳定：预期第{chapter_number}章《{title}》。"
            )
        filled = False
        for selector in body_selectors:
            try:
                locator = self.page.locator(selector)
                count = min(locator.count(), 8)
                for index in range(count):
                    item = locator.nth(index)
                    if item.is_visible():
                        self._fill_editor_text(item, text)
                        filled = True
                        break
                if filled:
                    break
            except Exception:
                continue
        if not filled:
            raise FanqieUploadError("没有找到章节正文编辑区。")
        # The platform re-renders the editor after the body is filled and
        # updates its word count asynchronously.  Re-apply metadata after the
        # body reaches its complete length because that re-render can replace
        # the controlled input nodes.
        if not self._wait_for_editor_ready(text):
            raise FanqieUploadError("番茄后台正文尚未完成同步，已停止保存以避免生成空正文草稿。")
        try:
            self.page.wait_for_timeout(2200)
        except Exception:
            time.sleep(2.2)
        self._fill_chapter_metadata(
            title, chapter_number, title_selectors, number_selectors
        )
        if not self._wait_for_metadata_stable(
            title_selectors,
            number_selectors,
            title,
            chapter_number,
            stable_ms=1800,
            timeout_ms=12000,
        ):
            raise FanqieUploadError(
                f"保存前元数据状态不稳定：预期第{chapter_number}章《{title}》。"
            )
        # The platform saves the editor asynchronously.  Give the controlled
        # metadata fields time to join the same save request before navigating
        # to the next chapter in a batch.
        try:
            self.page.wait_for_timeout(1200)
        except Exception:
            time.sleep(1.2)
        if mode == "draft":
            progress(f"正在保存《{title}》草稿...")
            self._save_draft_with_metadata_retry(
                title,
                chapter_number,
                title_selectors,
                number_selectors,
                text=text,
            )
            self._verify_saved_draft(
                title,
                chapter_number,
                text,
                title_selectors,
                number_selectors,
            )
            body = self._page_text()
            if "发布成功" in body and "保存成功" not in body:
                raise FanqieUploadError("页面进入了发布流程，已停止后续章节上传；请检查番茄后台设置。")
        else:
            if isinstance(scheduled_at, dict):
                scheduled_at = (
                    str(scheduled_at.get("publish_date", "") or "").strip(),
                    str(scheduled_at.get("publish_time", "") or "").strip(),
                )
            self._publish_chapter(
                title,
                text,
                mode,
                scheduled_at,
                bool(publish_use_ai),
                progress,
            )
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
            # Existing sessions are checked in a hidden context first.  A
            # visible browser is only needed when the saved session has
            # expired or this is the first login.
            works = []
            needs_interactive_login = False
            with _FanqieBrowserSession(
                headless=True,
                progress_callback=self.progress.emit,
            ) as browser:
                try:
                    works = browser.list_works(
                        progress=self.progress.emit,
                        should_stop=self._is_stopped,
                        interactive_login=False,
                    )
                except FanqieLoginRequired:
                    needs_interactive_login = True
            if needs_interactive_login:
                if self._is_stopped():
                    raise FanqieUploadCancelled("作品列表读取已取消。")
                self.progress.emit("当前番茄登录状态不可用，正在打开浏览器等待登录...")
                with _FanqieBrowserSession(
                    headless=False,
                    progress_callback=self.progress.emit,
                ) as browser:
                    works = browser.list_works(
                        progress=self.progress.emit,
                        should_stop=self._is_stopped,
                        interactive_login=True,
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
        target_mode = _normalize_upload_mode(self.task.get("mode", "draft"))
        target_work_type = _normalize_work_type(self.task.get("work_type", "unknown"))
        previous_target = (
            str(existing.get("platform_work_id", "") or "").strip(),
            str(existing.get("platform_work_url", "") or "").strip(),
        )
        same_target = (
            bool(target_id and previous_target[0] and target_id == previous_target[0])
            or bool(not target_id and not previous_target[0] and target_url == previous_target[1])
        )
        same_schedule = True
        if target_mode == "scheduled_publish":
            same_schedule = all(
                existing.get(key) == self.task.get(key)
                for key in (
                    "schedule_start_date",
                    "schedule_start_time",
                )
            )
        should_reset = (
            (any(previous_target) and not same_target)
            or existing.get("mode") != target_mode
            or existing.get("work_type") != target_work_type
            or not same_schedule
        )
        if should_reset:
            existing["completed_chapter_ids"] = []
            existing["failed_chapters"] = []
            existing["last_successful_chapter_id"] = ""
            existing["last_successful_chapter_number"] = 0
            existing["current_chapter"] = 0
            existing["current_chapter_id"] = ""
            existing["current_publish_time"] = ""
            existing["error"] = ""
            existing["error_kind"] = ""
            existing["daily_limit_scope"] = ""
        configured = {
            **existing,
            "platform_work_id": target_id,
            "platform_work_title": str(self.task.get("platform_work_title", "") or "").strip(),
            "platform_work_url": str(self.task.get("platform_work_url", "") or "").strip(),
            "mode": target_mode,
            "work_type": target_work_type,
            "publish_use_ai": bool(
                self.task.get(
                    "publish_use_ai",
                    target_mode in {"direct_publish", "scheduled_publish"},
                )
            ),
            "schedule_start_date": str(self.task.get("schedule_start_date", "") or "").strip(),
            "schedule_start_time": str(self.task.get("schedule_start_time", "") or "").strip(),
            "schedule_entries": deepcopy(self.task.get("schedule_entries", [])),
            "headless": bool(self.task.get("headless", True)),
            "resume": bool(self.task.get("resume", True)),
            "start_chapter": _as_int(self.task.get("start_chapter", 1), 1, 1),
            "end_chapter": _as_int(self.task.get("end_chapter", 0), 0, 0),
            "status": "pending",
            "error": "",
            "error_kind": "",
            "daily_limit_scope": "",
            "pause_reason": "",
        }
        if not bool(self.task.get("resume", True)):
            configured["completed_chapter_ids"] = []
            configured["failed_chapters"] = []
            configured["last_successful_chapter_id"] = ""
            configured["last_successful_chapter_number"] = 0
            configured["current_publish_time"] = ""
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
                schedule_by_id = {
                    str(item.get("chapter_id", "") or "").strip(): item
                    for item in state.get("schedule_entries", [])
                    if isinstance(item, dict) and str(item.get("chapter_id", "") or "").strip()
                }
                for number in range(state["start_chapter"], state["end_chapter"] + 1):
                    self._check_stopped()
                    chapter = chapters[number - 1]
                    chapter_id = _chapter_id(chapter, number - 1)
                    if chapter_id in state["completed_chapter_ids"]:
                        continue
                    state["status"] = "running"
                    state["current_chapter"] = number
                    state["current_chapter_id"] = chapter_id
                    schedule_entry = schedule_by_id.get(chapter_id)
                    if state.get("mode") == "scheduled_publish" and not schedule_entry:
                        raise FanqieUploadError(f"第{number}章缺少稳定的定时排期，已停止上传。")
                    state["current_publish_time"] = (
                        f"{schedule_entry.get('publish_date', '')} {schedule_entry.get('publish_time', '')}".strip()
                        if schedule_entry else ""
                    )
                    state["updated_at"] = now_str()
                    self._persist_state(state)
                    action = {
                        "draft": "保存草稿",
                        "direct_publish": "直接发布",
                        "scheduled_publish": "定时发布",
                    }.get(state.get("mode"), "上传")
                    self.progress.emit(f"正在{action}第{number}章：{chapter.get('title', '')}")
                    try:
                        browser.upload_chapter(
                            work,
                            chapter,
                            chapter_number=number,
                            progress=self.progress.emit,
                            mode=state.get("mode", "draft"),
                            scheduled_at=schedule_entry,
                            publish_use_ai=bool(state.get("publish_use_ai", False)),
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
                            "error_kind": "",
                            "updated_at": now_str(),
                        })
                        state["status"] = "failed"
                        state["error"] = error
                        state["error_kind"] = ""
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
                    state["error"] = ""
                    state["error_kind"] = ""
                    state["daily_limit_scope"] = ""
                    state["updated_at"] = now_str()
                    self._persist_state(state)
                    self.chapter_succeeded.emit({
                        "chapter_id": chapter_id,
                        "chapter_number": number,
                        "title": str(chapter.get("title", "") or "").strip(),
                        "mode": state.get("mode", "draft"),
                        "publish_time": state.get("current_publish_time", ""),
                    })
                state["status"] = "completed"
                state["current_chapter_id"] = ""
                state["current_publish_time"] = ""
                state["error"] = ""
                state["error_kind"] = ""
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
        except FanqieDailyLimitError as exc:
            state = normalize_fanqie_upload_state(state)
            state["status"] = "failed"
            state["error"] = clean_error_text(exc)
            if state.get("work_type") == "completed":
                state["error_kind"] = "publish_rejected"
                state["daily_limit_scope"] = "platform_rejected"
            else:
                state["error_kind"] = "daily_limit"
                state["daily_limit_scope"] = "serial"
            state["updated_at"] = now_str()
            try:
                self._persist_state(state)
            except Exception:
                pass
            self.failed.emit(state["error"])
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
                state["error_kind"] = ""
                state["updated_at"] = now_str()
                try:
                    self._persist_state(state)
                except Exception:
                    pass
            self.failed.emit(message)


class FanqieBatchUploadDialog(QDialog):
    """批量上传任务配置窗口。"""

    def __init__(self, current_project_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("番茄批量上传")
        self.setMinimumSize(760, 430)
        self.resize(900, 520)
        self._project_data_cache = {}
        self._work_list_worker = None
        self._close_after_work_list = False
        self._works = []
        self._restoring_saved_work = False
        self._current_project_path = (
            os.path.abspath(os.path.realpath(str(current_project_path or "")))
            if current_project_path else ""
        )
        project = self._load_selected_project()
        saved_state = project.get("fanqie_upload", {}) if isinstance(project, dict) else {}
        self._saved_upload_state = saved_state if isinstance(saved_state, dict) else {}
        self._has_saved_upload = bool(
            self._saved_upload_state.get("platform_work_id")
            or self._saved_upload_state.get("platform_work_url")
            or self._saved_upload_state.get("updated_at")
            or str(self._saved_upload_state.get("status", "") or "").strip()
            not in {"", "idle"}
        )
        saved_mode = (
            _normalize_upload_mode(self._saved_upload_state.get("mode", "draft"))
            if self._has_saved_upload else "draft"
        )
        saved_work_type = (
            _normalize_work_type(self._saved_upload_state.get("work_type", "unknown"))
            if self._has_saved_upload else "unknown"
        )
        saved_ai = (
            bool(self._saved_upload_state.get("publish_use_ai", True))
            if self._has_saved_upload else True
        )
        saved_date = QDate.fromString(
            str(self._saved_upload_state.get("schedule_start_date", "") or "").strip(),
            "yyyy-MM-dd",
        )
        if not saved_date.isValid():
            saved_date = QDate.currentDate().addDays(1)
        saved_time = QTime.fromString(
            str(self._saved_upload_state.get("schedule_start_time", "") or "").strip(),
            "HH:mm",
        )
        if not saved_time.isValid():
            saved_time = QTime(10, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel(
            "当前项目已由章节区锁定，只需选择番茄后台目标作品和上传方式。"
            "任务按章节串行执行，发布失败或触发每日上限会停止并保存断点。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)

        form = QFormLayout()
        meta = project.get("meta", {}) if isinstance(project, dict) else {}
        project_title = str(meta.get("title", "") or "").strip() if isinstance(meta, dict) else ""
        project_title = project_title or os.path.splitext(
            os.path.basename(self._current_project_path)
        )[0] or "未命名小说"
        self.project_name_edit = QLineEdit(project_title)
        self.project_name_edit.setReadOnly(True)
        self.project_name_edit.setToolTip(self._current_project_path or "当前项目尚未保存")

        work_row = QHBoxLayout()
        work_row.setSpacing(6)
        self.work_combo = QComboBox()
        self.work_combo.addItem("点击右侧读取番茄后台作品", {})
        self.work_combo.currentIndexChanged.connect(self._on_work_changed)
        work_row.addWidget(self.work_combo, 1)
        self.read_works_btn = QPushButton("读取作品列表")
        self.read_works_btn.setObjectName("ghost")
        self.read_works_btn.clicked.connect(self._read_works)
        work_row.addWidget(self.read_works_btn)

        # Reserve the same width as the list button so the two editable fields
        # line up while the dialog is resized.
        project_row = QHBoxLayout()
        project_row.setSpacing(0)
        project_row.addWidget(self.project_name_edit, 1)
        project_row.addSpacing(self.read_works_btn.sizeHint().width() + work_row.spacing())
        form.addRow("本地小说项目", project_row)
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

        self.mode_group, self.mode_buttons, mode_row = self._make_radio_row(
            (("上传草稿", "draft"), ("直接发布", "direct_publish"), ("定时发布", "scheduled_publish")),
            saved_mode,
        )
        self.mode_group.buttonClicked.connect(self._on_mode_changed)
        form.addRow("上传模式", mode_row)

        self.work_type_group, self.work_type_buttons, work_type_row = self._make_radio_row(
            (("自动识别", "unknown"), ("连载作品", "serial"), ("完本作品", "completed")),
            saved_work_type,
        )
        self.work_type_group.buttonClicked.connect(self._refresh_preview)
        form.addRow("作品状态", work_type_row)

        self.publish_ai_group, self.publish_ai_buttons, publish_ai_row = self._make_radio_row(
            (("是", "yes"), ("否", "no")),
            "yes" if saved_ai else "no",
        )
        self.publish_ai_group.buttonClicked.connect(self._refresh_preview)
        form.addRow("是否使用AI", publish_ai_row)

        self.schedule_date_edit = QDateEdit(saved_date)
        self.schedule_date_edit.setCalendarPopup(True)
        self.schedule_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.schedule_date_edit.dateChanged.connect(self._refresh_preview)

        self.schedule_time_edit = QTimeEdit(saved_time)
        self.schedule_time_edit.setDisplayFormat("HH:mm")
        self.schedule_time_edit.timeChanged.connect(self._refresh_preview)

        schedule_row = QHBoxLayout()
        schedule_row.setSpacing(6)
        schedule_row.addWidget(QLabel("日期"))
        schedule_row.addWidget(self.schedule_date_edit)
        schedule_row.addWidget(QLabel("时间"))
        schedule_row.addWidget(self.schedule_time_edit)
        schedule_row.addStretch(1)
        form.addRow("定时发布时间", schedule_row)

        self.headless_check = QCheckBox("上传时隐藏独立浏览器窗口")
        self.headless_check.setChecked(
            bool(self._saved_upload_state.get("headless", True))
            if self._has_saved_upload else True
        )
        self.resume_check = QCheckBox("跳过已成功章节，继续上次断点")
        self.resume_check.setChecked(
            bool(self._saved_upload_state.get("resume", True))
            if self._has_saved_upload else True
        )
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
        self.start_btn = buttons.addButton("开始上传草稿", QDialogButtonBox.AcceptRole)
        self.start_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_chapter_range()
        self._on_mode_changed()

    def _make_radio_row(self, options, checked_value):
        row = QHBoxLayout()
        row.setSpacing(14)
        group = QButtonGroup(self)
        buttons = {}
        for text, value in options:
            button = QRadioButton(text)
            button.setProperty("value", value)
            group.addButton(button)
            row.addWidget(button)
            buttons[value] = button
            if value == checked_value:
                button.setChecked(True)
        row.addStretch(1)
        return group, buttons, row

    @staticmethod
    def _radio_value(buttons, default):
        for value, button in buttons.items():
            if button.isChecked():
                return value
        return default

    def _selected_project_path(self):
        return self._current_project_path

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
        if self._has_saved_upload:
            saved_start = _as_int(self._saved_upload_state.get("start_chapter", 1), 1, 1)
            saved_end = _as_int(self._saved_upload_state.get("end_chapter", 0), 0, 0)
            saved_start = min(saved_start, max(1, count))
            saved_end = min(saved_end, count) if saved_end > 0 else count
            if saved_end > 0 and saved_start > saved_end:
                saved_start = 1
            self.end_spin.setValue(saved_end)
            self.start_spin.setValue(saved_start)
        self._refresh_preview()

    def _refresh_preview(self, *_args):
        project = self._load_selected_project()
        validation = validate_chapter_upload_range(
            project, self.start_spin.value(), self.end_spin.value()
        )
        text = f"当前范围：{validation['count']} 章"
        mode = self._radio_value(self.mode_buttons, "draft")
        mode_label = {
            "draft": "上传草稿",
            "direct_publish": "直接发布",
            "scheduled_publish": "定时发布",
        }.get(mode, "上传")
        work_type = self._radio_value(self.work_type_buttons, "unknown")
        work_type_label = {
            "unknown": "自动识别",
            "serial": "连载作品",
            "completed": "完本作品",
        }.get(work_type, "自动识别")
        text += f"\n当前模式：{mode_label}；作品状态：{work_type_label}。"
        if mode in {"direct_publish", "scheduled_publish"}:
            if work_type == "serial":
                text += "连载作品触发每日更新字数上限时会立即停止当前任务。"
            elif work_type == "completed":
                text += "完本作品不做连载每日额度预判；平台若实际拒绝仍会停止任务。"
            else:
                text += "作品状态未知时不做额度预判，平台返回每日上限提示会立即停止任务。"
        if mode == "scheduled_publish":
            text += (
                f"\n定时发布时间：{self.schedule_date_edit.date().toString('yyyy-MM-dd')} "
                f"{self.schedule_time_edit.time().toString('HH:mm')}。"
            )
            ai_label = "是" if self._radio_value(self.publish_ai_buttons, "yes") == "yes" else "否"
            text += f"是否使用 AI：{ai_label}。"
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

    def _on_mode_changed(self, *_args):
        mode = self._radio_value(self.mode_buttons, "draft")
        scheduled = mode == "scheduled_publish"
        publishing = mode in {"direct_publish", "scheduled_publish"}
        for widget in (
            self.schedule_date_edit,
            self.schedule_time_edit,
        ):
            widget.setEnabled(scheduled)
        for button in self.publish_ai_buttons.values():
            button.setEnabled(publishing)
        self.start_btn.setText({
            "draft": "开始上传草稿",
            "direct_publish": "开始直接发布",
            "scheduled_publish": "开始定时发布",
        }.get(mode, "开始上传"))
        self._refresh_preview()

    def _read_works(self):
        if self._work_list_worker is not None and self._work_list_worker.isRunning():
            return
        self.read_works_btn.setEnabled(False)
        self.read_works_btn.setText("读取中...")
        self.preview_label.setText(
            "正在后台检查番茄登录状态；只有需要登录时才会打开浏览器窗口。"
        )
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
        state = self._load_selected_project().get("fanqie_upload", {})
        previous_id = (
            str(state.get("platform_work_id", "") or "").strip()
            if isinstance(state, dict) else ""
        )
        self.work_combo.blockSignals(True)
        try:
            self.work_combo.clear()
            for item in self._works:
                self.work_combo.addItem(
                    str(item.get("title", "") or item.get("id", "") or "未命名作品"),
                    deepcopy(item),
                )
            restored_work = False
            if previous_id:
                for index, item in enumerate(self._works):
                    if str(item.get("id", "") or "").strip() == previous_id:
                        self.work_combo.setCurrentIndex(index)
                        restored_work = True
                        break
        finally:
            self.work_combo.blockSignals(False)
        if self._works:
            self._restoring_saved_work = bool(restored_work)
            try:
                self._on_work_changed()
            finally:
                self._restoring_saved_work = False
            self.preview_label.setText(f"已读取 {len(self._works)} 部番茄作品，请选择目标作品后开始上传。")
        else:
            self.work_combo.addItem("没有读取到作品", {})

    def _on_work_changed(self):
        item = self.work_combo.currentData()
        if isinstance(item, dict) and item.get("id"):
            preserve_saved_type = (
                self._restoring_saved_work
                and self._has_saved_upload
                and self._radio_value(self.work_type_buttons, "unknown") != "unknown"
            )
            if not preserve_saved_type:
                detected = _normalize_work_type(item.get("work_type", "unknown"))
                self.work_type_buttons[detected].setChecked(True)
            self._refresh_preview()

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
        mode = self._radio_value(self.mode_buttons, "draft")
        work_type = self._radio_value(self.work_type_buttons, "unknown")
        publish_use_ai = (
            mode in {"direct_publish", "scheduled_publish"}
            and self._radio_value(self.publish_ai_buttons, "yes") == "yes"
        )
        self._config = {
            "project_path": self._selected_project_path(),
            "platform_work_id": str(item.get("id", "") or "").strip(),
            "platform_work_title": str(item.get("title", "") or "").strip(),
            "platform_work_url": str(item.get("url", "") or "").strip(),
            "start_chapter": self.start_spin.value(),
            "end_chapter": self.end_spin.value(),
            "headless": self.headless_check.isChecked(),
            "resume": self.resume_check.isChecked(),
            "mode": mode,
            "work_type": work_type,
            "publish_use_ai": publish_use_ai,
            "schedule_start_date": self.schedule_date_edit.date().toString("yyyy-MM-dd"),
            "schedule_start_time": self.schedule_time_edit.time().toString("HH:mm"),
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
