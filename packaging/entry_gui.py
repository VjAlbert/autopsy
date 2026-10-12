"""Entry point per PyInstaller (evita l'import indiretto via console_scripts)."""

from drdeconstruct.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
