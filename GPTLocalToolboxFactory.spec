# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_dir = Path(SPECPATH).resolve()
icon_file = project_dir / "app_icon_trimmed.icns"
blender_resources_dir = project_dir / "gpt_desktop" / "resources" / "blender"
novel_resources_dir = project_dir / "gpt_desktop" / "resources" / "novel"
blender_resource_names = (
    "modern_furniture_pack_293.blend",
    "wooden_mannequin_rigged_293.blend",
    "MODERN_FURNITURE_ATTRIBUTION.md",
    "WOODEN_MANNEQUIN_ATTRIBUTION.md",
)
novel_resource_names = ("default_style_profiles.json",)
datas = []
for resource_name in blender_resource_names:
    resource_path = blender_resources_dir / resource_name
    if resource_path.is_file():
        datas.append((str(resource_path), "gpt_desktop/resources/blender"))
for resource_name in novel_resource_names:
    resource_path = novel_resources_dir / resource_name
    if resource_path.is_file():
        datas.append((str(resource_path), "gpt_desktop/resources/novel"))


a = Analysis(
    [str(project_dir / "factory_main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    name='GPTLocalToolboxFactory',
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
    name='GPTLocalToolboxFactory',
)
app = BUNDLE(
    coll,
    name='GPTLocalToolboxFactory.app',
    icon=str(icon_file) if icon_file.exists() else None,
    bundle_identifier=None,
)
