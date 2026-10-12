"""Render the app logo to packaging/drdeconstruct.ico (and docs/logo.png).

QT_QPA_PLATFORM=offscreen python scripts/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from PySide6.QtGui import QGuiApplication

    from drdeconstruct.gui.icons import logo_pixmap

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    (ROOT / "docs").mkdir(exist_ok=True)
    logo_pixmap(256).save(str(ROOT / "docs" / "logo.png"))
    pix = logo_pixmap(256)
    if not pix.save(str(ROOT / "packaging" / "drdeconstruct.ico"), "ICO"):
        print("ICO writer unavailable; install Pillow and convert docs/logo.png", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
