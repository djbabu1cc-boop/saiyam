# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the Windows build (used by GitHub Actions).

Run locally (not needed for the CI build):
    pyinstaller --noconfirm --clean InvoiceExtractor.spec
"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# RapidOCR ships ONNX model files inside its package; onnxruntime ships
# native libraries. Both must be collected in full.
for _pkg in ("rapidocr_onnxruntime", "onnxruntime"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# Pillow image plugins (jpeg, webp, tiff, ...)
_p, _pb, _ph = collect_all("PIL")
datas += _p
binaries += _pb
hiddenimports += _ph

datas += [("assets/icon.ico", "assets")]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pydoc", "lib2to3"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InvoiceExtractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI application: no console window
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="InvoiceExtractor",
)
