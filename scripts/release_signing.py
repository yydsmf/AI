from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _env(name: str) -> str:
    return str(os.environ.get(name, "")).strip()


def _run(cmd, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)


def sign_windows_file(path: str) -> bool:
    pfx_b64 = _env("WINDOWS_SIGNING_PFX_BASE64")
    if not pfx_b64:
        return False

    cert_password = _env("WINDOWS_SIGNING_PFX_PASSWORD")
    timestamp_url = _env("WINDOWS_TIMESTAMP_URL") or "http://timestamp.digicert.com"
    signtool = _env("WINDOWS_SIGNTOOL_PATH") or shutil.which("signtool.exe") or shutil.which("signtool")
    if not signtool:
        raise RuntimeError("找不到 signtool.exe。")

    with tempfile.NamedTemporaryFile(suffix=".pfx", delete=False) as fp:
        fp.write(base64.b64decode(pfx_b64))
        pfx_path = fp.name

    try:
        cmd = [
            signtool,
            "sign",
            "/fd",
            "SHA256",
            "/f",
            pfx_path,
            "/tr",
            timestamp_url,
            "/td",
            "SHA256",
        ]
        if cert_password:
            cmd += ["/p", cert_password]
        cmd.append(path)
        _run(cmd)
    finally:
        try:
            Path(pfx_path).unlink(missing_ok=True)
        except Exception:
            pass
    return True


def sign_macos_app(app_path: str) -> bool:
    identity = _env("MAC_CODESIGN_IDENTITY")
    if not identity:
        return False

    entitlements = _env("MAC_ENTITLEMENTS_PATH")
    codesign = shutil.which("codesign")
    if not codesign:
        raise RuntimeError("找不到 codesign。")

    cmd = [
        codesign,
        "--force",
        "--deep",
        "--options",
        "runtime",
        "--timestamp",
        "--sign",
        identity,
    ]
    if entitlements:
        cmd += ["--entitlements", entitlements]
    cmd.append(app_path)
    _run(cmd)
    return True


def sign_macos_dmg(dmg_path: str) -> bool:
    identity = _env("MAC_CODESIGN_IDENTITY")
    if not identity:
        return False

    codesign = shutil.which("codesign")
    if not codesign:
        raise RuntimeError("找不到 codesign。")

    _run([
        codesign,
        "--force",
        "--timestamp",
        "--sign",
        identity,
        dmg_path,
    ])
    return True


def notarize_macos_file(path: str) -> bool:
    apple_id = _env("MAC_NOTARY_APPLE_ID")
    team_id = _env("MAC_NOTARY_TEAM_ID")
    password = _env("MAC_NOTARY_PASSWORD")
    if not (apple_id and team_id and password):
        return False

    xcrun = shutil.which("xcrun")
    if not xcrun:
        raise RuntimeError("找不到 xcrun。")

    try:
        _run([
            xcrun,
            "notarytool",
            "submit",
            "--wait",
            "--apple-id",
            apple_id,
            "--team-id",
            team_id,
            "--password",
            password,
            path,
        ])
        _run([xcrun, "stapler", "staple", path])
        return True
    finally:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sign-windows", dest="sign_windows")
    parser.add_argument("--sign-macos", dest="sign_macos")
    parser.add_argument("--sign-macos-dmg", dest="sign_macos_dmg")
    parser.add_argument("--notarize-macos", dest="notarize_macos")
    args = parser.parse_args()

    if args.sign_windows:
        sign_windows_file(args.sign_windows)
    if args.sign_macos:
        sign_macos_app(args.sign_macos)
    if args.sign_macos_dmg:
        sign_macos_dmg(args.sign_macos_dmg)
    if args.notarize_macos:
        notarize_macos_file(args.notarize_macos)


if __name__ == "__main__":
    main()
