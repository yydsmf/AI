# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_dir = Path(SPECPATH).resolve()
icon_file = project_dir / "app_icon_trimmed.icns"
app_version = "1.0.5"


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


a = Analysis(
    [str(project_dir / 'main.py')],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy', 'IPython', 'pytest', 'PyQt5', 'PyQt6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GPTLocalToolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GPTLocalToolbox',
)
app = BUNDLE(
    coll,
    name='GPT工具箱.app',
    icon=str(icon_file) if icon_file.exists() else None,
    bundle_identifier='com.gptlocaltoolbox.app',
    version=app_version,
    info_plist={
        'CFBundleDisplayName': 'GPT工具箱',
        'CFBundleShortVersionString': app_version,
        'CFBundleVersion': app_version,
        'LSMinimumSystemVersion': '12.0',
    },
)
