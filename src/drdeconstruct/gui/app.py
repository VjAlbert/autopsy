"""Punto d'ingresso dell'interfaccia grafica: `drdec-gui`."""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from drdeconstruct.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("DrDeconstruct")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
