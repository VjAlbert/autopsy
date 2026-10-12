"""Thread di lavoro: tengono la finestra reattiva durante le operazioni lente."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from drdeconstruct.core.errors import RefusalError

REFUSAL_HELP = (
    "Il modello si è rifiutato di analizzare questo contenuto, anche dopo aver "
    "riprovato con il modello di riserva.\n\n"
    "Succede a volte con firmware e codice disassemblato. Cosa puoi provare:\n"
    "• scrivi nel contesto a cosa ti serve (es. «interoperabilità con il mio "
    "dispositivo»);\n"
    "• analizza una funzione alla volta invece del file intero;\n"
    "• scegli un altro motore dal menu (es. ollama, che gira sul tuo computer).\n\n"
    "Dettagli: {details}"
)


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
        except RefusalError as exc:
            self.failed.emit(REFUSAL_HELP.format(details=exc))
        except Exception as exc:  # noqa: BLE001 - mostriamo l'errore all'utente
            self.failed.emit(str(exc))
