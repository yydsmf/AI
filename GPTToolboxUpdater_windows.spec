# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys


project_dir = Path(SPECPATH).resolve()
icon_file = project_dir / "app_icon.ico"


def _windows_runtime_binaries():
    if not sys.platform.startswith("win"):
        return []
    names = (
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "concrt140.dll",
    )
    roots = []
    for value in (sys.base_prefix, sys.prefix, Path(sys.executable).parent):
        if value:
            roots.append(Path(value))
    system_root = os.environ.get("SystemRoot")
    if system_root:
        roots.append(Path(system_root) / "System32")
    binaries = []
    seen = set()
    for name in names:
        lower = name.lower()
        if lower in seen:
            continue
        for root in roots:
            path = root / name
            if path.exists():
                binaries.append((str(path), "."))
                seen.add(lower)
                break
    return binaries


a = Analysis(
    [str(project_dir / "updater_main.py")],
    pathex=[str(project_dir)],
    binaries=_windows_runtime_binaries(),
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
        "pytest",
        "PyQt5",
        "PyQt6",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GPTToolboxUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_file) if icon_file.exists() else None,
)
