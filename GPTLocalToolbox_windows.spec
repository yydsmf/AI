# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_dir = Path(SPECPATH).resolve()
icon_file = project_dir / "app_icon.ico"
blender_resources_dir = project_dir / "gpt_desktop" / "resources" / "blender"
blender_resource_names = (
    "modern_furniture_pack_293.blend",
    "wooden_mannequin_rigged_293.blend",
    "MODERN_FURNITURE_ATTRIBUTION.md",
    "WOODEN_MANNEQUIN_ATTRIBUTION.md",
)


def _collect_submodules(package):
    try:
        return collect_submodules(package)
    except Exception:
        return []


def _collect_data_files(package):
    try:
        return collect_data_files(package)
    except Exception:
        return []


hiddenimports = []
for package_name in ("docx", "pypdf", "edge_tts"):
    hiddenimports += _collect_submodules(package_name)

datas = []
datas += _collect_data_files("docx")
for resource_name in blender_resource_names:
    resource_path = blender_resources_dir / resource_name
    if resource_path.is_file():
        datas.append((str(resource_path), "gpt_desktop/resources/blender"))


a = Analysis(
    [str(project_dir / "factory_main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
        "gpt_desktop.novel_writing_v2_tab",
        "gpt_desktop.novel_v2_context",
        "gpt_desktop.novel_v2_import",
        "gpt_desktop.novel_v2_storage",
        "gpt_desktop.novel_v2_utils",
        "gpt_desktop.novel_v2_workers",
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
    name="GPTLocalToolbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_file) if icon_file.exists() else None,
)
