# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Linux build.

Used by ``linux/package.sh``. Produces a onedir bundle in ``build/Neptune-linux`` that the
AppImage wraps; the frozen app has no Python, no PySide6 and no mingw on the user's machine.
"""
import os

# Paths inside a spec resolve relative to the spec's own directory, so anchor to the project root.
root = os.path.abspath(os.path.join(SPECPATH, os.pardir))

datas = []
assets = os.path.join(root, 'assets')
if os.path.isdir(assets):
    datas.append((assets, 'assets'))

# Ship the helper inside the bundle. At runtime the port copies it to a writable XDG path
# first, because an AppImage mount is read-only and is torn down on exit.
helper = os.path.join(root, 'neptune_linux', 'neptune-bridge.exe')
if os.path.isfile(helper):
    datas.append((helper, 'neptune_linux'))

analysis = Analysis(
    [os.path.join(root, 'neptune', 'app.py')],
    pathex=[root],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'PySide6.QtMultimedia',
        'Xlib',
        'Xlib.ext.shape',
        'texture2ddecoder',
        # neptune_linux modules are behind platform-conditional imports that
        # PyInstaller's static analysis does not always follow.
        'neptune_linux',
        'neptune_linux.control',
        'neptune_linux.dispatch',
        'neptune_linux.gamewindow',
        'neptune_linux.input',
        'neptune_linux.prewarm',
        'neptune_linux.process',
        'neptune_linux.runtime',
        'neptune_linux.shell',
        'neptune_linux.transport',
        'neptune_linux.wheels',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'PIL',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore',
        'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtPdf', 'PySide6.QtSql', 'PySide6.QtTest',
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='Neptune',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name='Neptune-linux',
)
