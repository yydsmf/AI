# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/wanglibo/Desktop/GPT/image_only.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy', 'IPython', 'pytest', 'PyQt5', 'PyQt6', 'PIL', 'docx', 'pypdf', 'lxml'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GPTImageGenerator_arm64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
    icon=['/Users/wanglibo/Desktop/GPT/app_icon_trimmed.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GPTImageGenerator_arm64',
)
app = BUNDLE(
    coll,
    name='GPTImageGenerator_arm64.app',
    icon='/Users/wanglibo/Desktop/GPT/app_icon_trimmed.icns',
    bundle_identifier=None,
)
