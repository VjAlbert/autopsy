# PyInstaller spec: builds DrDeconstruct.exe (GUI window, single file).
# Usage: pyinstaller packaging/drdeconstruct.spec
import os

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

PKG = os.path.join(SPECPATH, "..", "src", "drdeconstruct")

hiddenimports = (
    collect_submodules("serial")
    + collect_submodules("usb")
    + ["libusb_package"]
    + collect_submodules("bleak")
    + collect_submodules("zeroconf")
    + collect_submodules("cryptography")
)

a = Analysis(
    ["entry_gui.py"],
    pathex=["src"],
    # libusb-1.0.dll: without it pyusb fails with "No backend available".
    binaries=collect_dynamic_libs("libusb_package"),
    # Non-Python files the package reads at runtime next to its modules.
    datas=[
        (os.path.join(PKG, "preprocess", "ghidra_scripts"), "drdeconstruct/preprocess/ghidra_scripts"),
        (os.path.join(PKG, "eval_cases"), "drdeconstruct/eval_cases"),
    ],
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
    icon=os.path.join(SPECPATH, "drdeconstruct.ico"),
)
