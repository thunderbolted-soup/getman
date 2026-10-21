# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller Getman.spec  ->  dist/Getman(.exe)
# All app code is plain Python modules discovered by import analysis
# (including the lazily imported importers/dialogs), so no datas are needed.

# Stdlib / third-party modules the app never uses: smaller exe, faster start.
excludes = [
    "tkinter", "unittest", "pydoc", "doctest", "pdb", "xmlrpc", "multiprocessing", "asyncio",
    "concurrent", "sqlite3", "lib2to3", "pygments", "httpx", "prance", "numpy",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtSvg",
    "PySide6.QtPrintSupport", "PySide6.QtConcurrent",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["yaml"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Getman",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressed Qt DLLs are known to crash on some machines
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
