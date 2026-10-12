"""Entry point for PyInstaller (avoids the indirect console_scripts import)."""

from drdeconstruct.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
