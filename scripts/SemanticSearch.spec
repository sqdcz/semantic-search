# -*- mode: python ; coding: utf-8 -*-
import os

APP_DIR = r'D:\SemanticSearch'
SCRIPTS = os.path.join(APP_DIR, 'scripts')

a = Analysis(
    [os.path.join(SCRIPTS, 'app.py')],
    pathex=[SCRIPTS],
    binaries=[],
    datas=[
        (os.path.join(SCRIPTS, 'search_core.py'), '.'),
        (os.path.join(SCRIPTS, 'everything_client.py'), '.'),
        (os.path.join(SCRIPTS, 'setup_deps.py'), '.'),
    ],
    hiddenimports=['pystray._win32', 'win32com.client', 'pythoncom', 'PIL.Image', 'PIL.ImageDraw'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['pkg_resources', 'setuptools'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SemanticSearch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=None,
)
