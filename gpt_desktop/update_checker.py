import platform
import re
import sys
from dataclasses import dataclass
from typing import Optional

import requests

from .version import APP_RELEASES_API_URL, APP_RELEASES_URL, APP_VERSION


@dataclass
class ReleaseAsset:
    name: str
    url: str
    size: int = 0


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    has_update: bool
    release_url: str
    release_notes: str
    asset: Optional[ReleaseAsset] = None


def normalize_version(value):
    text = str(value or "").strip()
    if text.lower().startswith("v"):
        text = text[1:].strip()
    return text


def _version_numbers(value):
    text = normalize_version(value)
    parts = [int(x) for x in re.findall(r"\d+", text)]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def _is_prerelease(value):
    text = normalize_version(value).lower()
    return any(mark in text for mark in ("alpha", "beta", "rc", "preview", "dev"))


def compare_versions(left, right):
    left_nums = _version_numbers(left)
    right_nums = _version_numbers(right)
    if left_nums < right_nums:
        return -1
    if left_nums > right_nums:
        return 1
    left_pre = _is_prerelease(left)
    right_pre = _is_prerelease(right)
    if left_pre and not right_pre:
        return -1
    if right_pre and not left_pre:
        return 1
    return 0


def current_platform_key():
    if sys.platform.startswith("win"):
        return "windows-x64"
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            return "macos-arm64"
        return "macos-x64"
    return "unknown"


def _asset_score(asset_name, platform_key):
    name = str(asset_name or "").lower()
    if not name:
        return -1000

    score = 0
    if platform_key.startswith("windows"):
        if not any(token in name for token in ("win", "windows", "setup", ".msi", ".exe")):
            return -100
        if name.endswith(".exe"):
            score += 80
        if name.endswith(".msi"):
            score += 70
        if "setup" in name or "installer" in name:
            score += 60
        if "x64" in name or "amd64" in name:
            score += 30
        if "portable" in name:
            score -= 30
        return score

    if platform_key == "macos-arm64":
        if not any(token in name for token in ("mac", "macos", "darwin", ".dmg", ".pkg")):
            return -100
        if "arm64" in name or "aarch64" in name or "apple" in name or "silicon" in name:
            score += 90
        if "universal" in name or "universal2" in name:
            score += 80
        if name.endswith(".dmg"):
            score += 60
        if name.endswith(".pkg"):
            score += 50
        if name.endswith(".zip"):
            score += 35
        if any(token in name for token in ("x64", "x86_64", "intel")):
            score -= 80
        return score

    if platform_key == "macos-x64":
        if not any(token in name for token in ("mac", "macos", "darwin", ".dmg", ".pkg")):
            return -100
        if "x64" in name or "x86_64" in name or "intel" in name:
            score += 90
        if "universal" in name or "universal2" in name:
            score += 80
        if name.endswith(".dmg"):
            score += 60
        if name.endswith(".pkg"):
            score += 50
        if name.endswith(".zip"):
            score += 35
        if "arm64" in name or "aarch64" in name:
            score -= 80
        return score

    return -100


def select_release_asset(assets, platform_key=None):
    platform_key = platform_key or current_platform_key()
    candidates = []
    for asset in assets or []:
        if isinstance(asset, dict):
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or asset.get("url") or "")
            size = int(asset.get("size") or 0)
        else:
            name = str(getattr(asset, "name", "") or "")
            url = str(getattr(asset, "url", "") or "")
            size = int(getattr(asset, "size", 0) or 0)
        if not name or not url:
            continue
        score = _asset_score(name, platform_key)
        if score >= 0:
            candidates.append((score, ReleaseAsset(name=name, url=url, size=size)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def parse_github_release(data, current_version=APP_VERSION, platform_key=None):
    if not isinstance(data, dict):
        raise ValueError("GitHub 发布信息格式不正确。")

    latest = normalize_version(data.get("tag_name") or data.get("name") or "")
    if not latest:
        raise ValueError("GitHub 发布信息里没有版本号。")

    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    asset = select_release_asset(assets, platform_key=platform_key)
    release_url = str(data.get("html_url") or APP_RELEASES_URL)
    notes = str(data.get("body") or "").strip()
    has_update = compare_versions(current_version, latest) < 0
    return UpdateInfo(
        current_version=normalize_version(current_version),
        latest_version=latest,
        has_update=has_update,
        release_url=release_url,
        release_notes=notes,
        asset=asset,
    )


def check_latest_release(current_version=APP_VERSION, platform_key=None, timeout=15):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "GPTLocalToolbox-Updater",
    }
    resp = requests.get(APP_RELEASES_API_URL, headers=headers, timeout=timeout)
    if resp.status_code == 404:
        raise RuntimeError("没有找到 GitHub Release。请先在仓库里发布一个版本。")
    if resp.status_code >= 400:
        raise RuntimeError(f"检查更新失败：GitHub 返回 {resp.status_code}")
    return parse_github_release(resp.json(), current_version=current_version, platform_key=platform_key)


def safe_asset_filename(name):
    text = str(name or "").strip()
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = text.strip(" .")
    return text or "GPTLocalToolbox_Update"


def download_release_asset(asset, dest_dir, progress_callback=None, timeout=30):
    if asset is None:
        raise ValueError("没有可下载的更新包。")
    url = str(getattr(asset, "url", "") or "").strip()
    name = safe_asset_filename(getattr(asset, "name", "") or "")
    if not url:
        raise ValueError("更新包下载地址为空。")

    import os

    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, name)
    tmp_path = dest_path + ".download"
    headers = {"User-Agent": "GPTLocalToolbox-Updater"}

    with requests.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=True) as resp:
        if resp.status_code >= 400:
            raise RuntimeError(f"下载更新包失败：服务器返回 {resp.status_code}")
        total = int(resp.headers.get("content-length") or getattr(asset, "size", 0) or 0)
        done = 0
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_callback:
                    progress_callback(done, total)

    os.replace(tmp_path, dest_path)
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) <= 0:
        raise RuntimeError("更新包下载完成但文件为空。")
    return dest_path
