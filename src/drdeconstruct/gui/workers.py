"""Thread di lavoro: tengono la finestra reattiva durante le operazioni lente."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


class Task(QThread):
    """Esegue una funzione in un thread separato ed emette il risultato o l'errore."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(
        self, fn: Callable[..., Any], parent: QObject | None = None, with_report: bool = False
    ):
        """Con `with_report`, `fn` riceve `report(obj)` per mandare aggiornamenti alla GUI."""
        super().__init__(parent)
        self._fn = fn
        self._with_report = with_report

    def report(self, payload: object) -> None:
        self.progress.emit(payload)

    def run(self) -> None:
        try:
            self.done.emit(self._fn(self.report) if self._with_report else self._fn())
        except Exception as exc:  # noqa: BLE001 - mostriamo l'errore all'utente
            self.failed.emit(str(exc))
