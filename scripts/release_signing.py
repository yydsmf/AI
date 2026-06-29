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
    if entitlements and not Path(entitlements).exists():
        raise RuntimeError(f"找不到 macOS entitlements 文件：{entitlements}")

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
    _run([codesign, "--verify", "--deep", "--strict", "--verbose=2", app_path])
    return True


def sign_macos_internal_app(app_path: str) -> bool:
    codesign = shutil.which("codesign")
    if not codesign:
        raise RuntimeError("找不到 codesign。")

    _run([
        codesign,
        "--force",
        "--deep",
        "--sign",
        "-",
        app_path,
    ])
    _run([codesign, "--verify", "--deep", "--strict", "--verbose=2", app_path])
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
    _run([codesign, "--verify", "--verbose=2", dmg_path])
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
        _run([xcrun, "stapler", "validate", path])
        spctl = shutil.which("spctl")
        if spctl:
            suffix = Path(path).suffix.lower()
            if suffix == ".dmg":
                _run([
                    spctl,
                    "-a",
                    "-vv",
                    "-t",
                    "open",
                    "--context",
                    "context:primary-signature",
                    path,
                ])
            else:
                _run([spctl, "-a", "-vv", "-t", "exec", path])
        return True
    finally:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sign-windows", dest="sign_windows")
    parser.add_argument("--sign-macos", dest="sign_macos")
    parser.add_argument("--sign-macos-internal", dest="sign_macos_internal")
    parser.add_argument("--sign-macos-dmg", dest="sign_macos_dmg")
    parser.add_argument("--notarize-macos", dest="notarize_macos")
    args = parser.parse_args()

    if args.sign_windows:
        if not sign_windows_file(args.sign_windows):
            raise SystemExit("Windows signing skipped: no signing certificate configured.")
    if args.sign_macos:
        if not sign_macos_app(args.sign_macos):
            raise SystemExit("Mac signing skipped: no Developer ID identity configured.")
    if args.sign_macos_internal:
        sign_macos_internal_app(args.sign_macos_internal)
    if args.sign_macos_dmg:
        if not sign_macos_dmg(args.sign_macos_dmg):
            raise SystemExit("Mac DMG signing skipped: no Developer ID identity configured.")
    if args.notarize_macos:
        if not notarize_macos_file(args.notarize_macos):
            raise SystemExit("Mac notarization skipped: no Apple notarization credentials configured.")


if __name__ == "__main__":
    main()
