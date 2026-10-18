"""按需下载和缓存体积较大的可选运行组件。

主程序只携带运行这些功能所需的小依赖。首次使用时，组件会先下载到临时目录，
完成校验并写入完成标记后再原子移动到应用数据目录，避免中断留下半成品。
"""

import hashlib
import html
import importlib
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

from .core import APP_DIR
from .version import APP_RELEASE_REPO, APP_VERSION


PLAYWRIGHT_VERSION = "1.60.0"
PLAYWRIGHT_INDEX_URL = (
    "https://pypi.tuna.tsinghua.edu.cn/simple/playwright/"
)
BLENDER_ASSET_CACHE_VERSION = str(
    os.environ.get("GPT_TOOLBOX_BLENDER_ASSET_VERSION") or "1"
).strip()
BLENDER_ASSET_RELEASE_VERSION = str(
    os.environ.get("GPT_TOOLBOX_BLENDER_ASSET_RELEASE_VERSION") or APP_VERSION
).strip()
BLENDER_ASSET_FILENAME = "GPTLocalToolbox_BlenderAssets.zip"
BLENDER_ASSET_REQUIRED_FILES = (
    "modern_furniture_pack_293.blend",
    "wooden_mannequin_rigged_293.blend",
    "MODERN_FURNITURE_ATTRIBUTION.md",
    "WOODEN_MANNEQUIN_ATTRIBUTION.md",
)

_COMPONENT_ROOT = Path(APP_DIR) / "components"
_PLAYWRIGHT_ROOT = _COMPONENT_ROOT / "playwright" / PLAYWRIGHT_VERSION
_PLAYWRIGHT_SITE_PACKAGES = _PLAYWRIGHT_ROOT / "site-packages"
_BLENDER_ROOT = _COMPONENT_ROOT / "blender_assets" / BLENDER_ASSET_CACHE_VERSION
_COMPONENT_LOCK = threading.RLock()
_COMPONENT_FILE_LOCK_NAME = ".optional-components.lock"


class OptionalComponentError(RuntimeError):
    """可选组件下载或校验失败。"""


class _SimpleIndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(html.unescape(value))


def _emit_progress(callback, message, done=0, total=0):
    if not callback:
        return
    try:
        callback(str(message), int(done or 0), int(total or 0))
    except TypeError:
        callback(str(message))


def _request(url, timeout=30):
    request = urllib.request.Request(
        str(url),
        headers={"User-Agent": "GPTLocalToolbox-OptionalComponents"},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _download_file(url, destination, progress_callback=None, label="正在下载组件"):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _request(url) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(destination, "wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                done += len(chunk)
                _emit_progress(progress_callback, f"{label}：{done / 1024 / 1024:.1f} MB", done, total)
    if not destination.exists() or destination.stat().st_size <= 0:
        raise OptionalComponentError("组件下载完成但文件为空。")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_zip(archive_path, target_dir):
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            target = (target_dir / item.filename).resolve()
            if target != target_dir and target_dir not in target.parents:
                raise OptionalComponentError("组件压缩包包含非法路径。")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, open(target, "wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
            mode = (int(item.external_attr) >> 16) & 0o777
            if mode:
                os.chmod(target, mode)


def _write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _add_site_packages(path):
    path = str(Path(path).resolve())
    if path not in sys.path:
        sys.path.insert(0, path)


def _clear_module_tree(prefix):
    for name in list(sys.modules):
        if name == prefix or name.startswith(prefix + "."):
            sys.modules.pop(name, None)


@contextmanager
def _component_file_lock(timeout=600):
    """Serialize component installation across multiple app processes."""
    _COMPONENT_ROOT.mkdir(parents=True, exist_ok=True)
    lock_path = _COMPONENT_ROOT / _COMPONENT_FILE_LOCK_NAME
    started = time.monotonic()
    acquired = False
    while not acquired:
        try:
            lock_path.mkdir()
            (lock_path / "owner").write_text(
                f"pid={os.getpid()}\ntime={time.time()}\n", encoding="utf-8"
            )
            acquired = True
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > 1800:
                    shutil.rmtree(lock_path, ignore_errors=True)
                    continue
            except OSError:
                continue
            if time.monotonic() - started >= timeout:
                raise OptionalComponentError("另一个程序实例正在准备可选组件，请稍后重试。")
            time.sleep(0.2)
    try:
        yield
    finally:
        shutil.rmtree(lock_path, ignore_errors=True)


def _playwright_wheel():
    index_url = str(
        os.environ.get("GPT_TOOLBOX_PLAYWRIGHT_INDEX_URL") or PLAYWRIGHT_INDEX_URL
    ).strip()
    index_url = index_url.rstrip("/") + "/"
    try:
        with _request(index_url) as response:
            page = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise OptionalComponentError(
            f"无法读取 Playwright 国内源：{index_url}\n{exc}"
        ) from exc
    parser = _SimpleIndexParser()
    parser.feed(page)
    platform_tokens = _playwright_platform_tokens()
    expected_prefix = f"playwright-{PLAYWRIGHT_VERSION}-py3-none-"
    candidates = []
    for href in parser.hrefs:
        parsed = urllib.parse.urlsplit(href)
        name = Path(parsed.path).name
        if not name.startswith(expected_prefix) or not name.endswith(".whl"):
            continue
        candidates.append((name, href))
    for token in platform_tokens:
        for name, href in candidates:
            if not name.endswith(f"{token}.whl"):
                continue
            parsed = urllib.parse.urlsplit(href)
            fragment = urllib.parse.parse_qs(parsed.fragment)
            expected_sha256 = str((fragment.get("sha256") or [""])[0]).strip().lower()
            return urllib.parse.urljoin(index_url, href.split("#", 1)[0]), expected_sha256
    raise OptionalComponentError(
        f"国内源中没有找到适合当前系统（{sys.platform}/{platform.machine()}）的 "
        f"Playwright {PLAYWRIGHT_VERSION} wheel。"
    )


def _playwright_platform_tokens():
    system = str(sys.platform or "").lower()
    machine = str(platform.machine() or "").lower()
    if system.startswith("win"):
        if machine in {"arm64", "aarch64"}:
            return ("win_arm64", "win_amd64")
        if machine in {"x86", "i386", "i686"}:
            return ("win32", "win_amd64")
        return ("win_amd64", "win32")
    if system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return ("macosx_11_0_arm64", "macosx_11_0_universal2")
        return ("macosx_10_13_x86_64", "macosx_11_0_universal2")
    if system.startswith("linux"):
        if machine in {"arm64", "aarch64"}:
            return ("manylinux_2_17_aarch64.manylinux2014_aarch64",)
        return ("manylinux_2_17_x86_64", "manylinux1_x86_64")
    return ()


def _playwright_cache_ready():
    marker = _PLAYWRIGHT_ROOT / "install.json"
    return (
        _PLAYWRIGHT_SITE_PACKAGES.is_dir()
        and (_PLAYWRIGHT_SITE_PACKAGES / "playwright").is_dir()
        and marker.is_file()
    )


def ensure_playwright(progress_callback=None):
    """下载并将 Playwright Python wheel 加入当前进程的导入路径。"""
    with _COMPONENT_LOCK:
        _COMPONENT_ROOT.mkdir(parents=True, exist_ok=True)
        with _component_file_lock():
            if _playwright_cache_ready():
                _add_site_packages(_PLAYWRIGHT_SITE_PACKAGES)
                return str(_PLAYWRIGHT_SITE_PACKAGES)

            wheel_url, expected_sha256 = _playwright_wheel()
            temporary_root = Path(tempfile.mkdtemp(prefix="playwright-", dir=_COMPONENT_ROOT))
            try:
                wheel_path = temporary_root / "playwright.whl"
                _emit_progress(progress_callback, "正在下载 Playwright 运行库…")
                _download_file(wheel_url, wheel_path, progress_callback, "正在下载 Playwright")
                actual_sha256 = _sha256(wheel_path)
                if expected_sha256 and actual_sha256 != expected_sha256:
                    raise OptionalComponentError("Playwright 下载校验失败，文件可能已损坏。")
                extracted = temporary_root / "site-packages"
                _safe_extract_zip(wheel_path, extracted)
                if not (extracted / "playwright").is_dir():
                    raise OptionalComponentError("Playwright wheel 内容不完整。")
                _PLAYWRIGHT_ROOT.parent.mkdir(parents=True, exist_ok=True)
                if _PLAYWRIGHT_ROOT.exists():
                    shutil.rmtree(_PLAYWRIGHT_ROOT)
                _PLAYWRIGHT_ROOT.mkdir(parents=True, exist_ok=True)
                os.replace(extracted, _PLAYWRIGHT_SITE_PACKAGES)
                _write_json(
                    _PLAYWRIGHT_ROOT / "install.json",
                    {
                        "component": "playwright",
                        "version": PLAYWRIGHT_VERSION,
                        "wheel_sha256": actual_sha256,
                        "source": wheel_url,
                    },
                )
                _add_site_packages(_PLAYWRIGHT_SITE_PACKAGES)
                _emit_progress(progress_callback, "Playwright 运行库已准备完成。")
                return str(_PLAYWRIGHT_SITE_PACKAGES)
            except OptionalComponentError:
                raise
            except Exception as exc:
                raise OptionalComponentError(f"安装 Playwright 运行库失败：{exc}") from exc
            finally:
                shutil.rmtree(temporary_root, ignore_errors=True)


def load_playwright_sync_api(progress_callback=None):
    """优先使用现有环境，否则按需安装后加载 Playwright。"""
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except Exception:
        _clear_module_tree("playwright")
    try:
        ensure_playwright(progress_callback=progress_callback)
        _clear_module_tree("playwright")
        module = importlib.import_module("playwright.sync_api")
        return module.sync_playwright
    except Exception as exc:
        raise OptionalComponentError(
            "当前环境缺少 Playwright，且自动下载安装失败。\n"
            "程序使用清华 PyPI 国内源下载；可通过 GPT_TOOLBOX_PLAYWRIGHT_INDEX_URL 覆盖源地址。\n"
            f"诊断信息：{exc}"
        ) from exc


def _blender_asset_urls():
    configured = str(os.environ.get("GPT_TOOLBOX_BLENDER_ASSET_URL") or "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    tag = f"v{BLENDER_ASSET_RELEASE_VERSION}"
    direct = (
        f"https://github.com/{APP_RELEASE_REPO}/releases/download/"
        f"{tag}/{BLENDER_ASSET_FILENAME}"
    )
    return [
        f"https://gh-proxy.com/{direct}",
        f"https://ghfast.top/{direct}",
        direct,
    ]


def blender_asset_cache_path(filename):
    return _BLENDER_ROOT / str(filename or "").strip()


def blender_assets_available():
    return all(blender_asset_cache_path(name).is_file() for name in BLENDER_ASSET_REQUIRED_FILES)


def ensure_blender_assets(progress_callback=None):
    """下载并解压 Blender 导演台所需的独立资源包。"""
    with _COMPONENT_LOCK:
        _COMPONENT_ROOT.mkdir(parents=True, exist_ok=True)
        with _component_file_lock():
            if blender_assets_available():
                return str(_BLENDER_ROOT)
            temporary_root = Path(tempfile.mkdtemp(prefix="blender-assets-", dir=_COMPONENT_ROOT))
            archive_path = temporary_root / BLENDER_ASSET_FILENAME
            errors = []
            try:
                for url in _blender_asset_urls():
                    try:
                        _emit_progress(progress_callback, "正在下载 Blender 导演台资源…")
                        _download_file(url, archive_path, progress_callback, "正在下载 Blender 资源")
                        extracted = temporary_root / "extracted"
                        _safe_extract_zip(archive_path, extracted)
                        missing = [
                            name for name in BLENDER_ASSET_REQUIRED_FILES
                            if not (extracted / name).is_file()
                        ]
                        if missing:
                            raise OptionalComponentError("资源包缺少：" + "、".join(missing))
                        if _BLENDER_ROOT.exists():
                            shutil.rmtree(_BLENDER_ROOT)
                        _BLENDER_ROOT.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(extracted, _BLENDER_ROOT)
                        _write_json(
                            _BLENDER_ROOT / "install.json",
                            {
                                "component": "blender_assets",
                                "version": BLENDER_ASSET_CACHE_VERSION,
                                "source": url,
                            },
                        )
                        _emit_progress(progress_callback, "Blender 导演台资源已准备完成。")
                        return str(_BLENDER_ROOT)
                    except Exception as exc:
                        errors.append(f"{url}：{exc}")
                        if archive_path.exists():
                            archive_path.unlink()
                raise OptionalComponentError(
                    "Blender 导演台资源下载失败。\n" + "\n".join(errors)
                )
            finally:
                shutil.rmtree(temporary_root, ignore_errors=True)


__all__ = [
    "OptionalComponentError",
    "PLAYWRIGHT_VERSION",
    "BLENDER_ASSET_REQUIRED_FILES",
    "blender_asset_cache_path",
    "blender_assets_available",
    "ensure_blender_assets",
    "ensure_playwright",
    "load_playwright_sync_api",
]
