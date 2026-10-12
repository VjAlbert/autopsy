"""Thread di lavoro: tengono la finestra reattiva durante le operazioni lente."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


class Task(QThread):
    """Esegue una funzione in un thread separato ed emette il risultato o l'errore."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent: QObject | None = None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - mostriamo l'errore all'utente
            self.failed.emit(str(exc))
