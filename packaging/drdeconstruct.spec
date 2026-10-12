# PyInstaller spec: costruisce DrDeconstruct.exe (finestra grafica, file unico).
# Uso: pyinstaller packaging/drdeconstruct.spec
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("serial")
    + collect_submodules("usb")
    + collect_submodules("bleak")
)

a = Analysis(
    ["entry_gui.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DrDeconstruct",
    console=False,
    onefile=True,
    upx=False,
)
