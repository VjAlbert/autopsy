"""Controlli di sicurezza per le operazioni che scrivono sulla memoria.

Scrivere su una memoria flash può rendere il dispositivo inservibile, quindi
qui stanno le regole che valgono per qualunque adattatore: backup prima,
verifica dell'immagine, conferma esplicita.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from drdeconstruct.core.errors import SafetyError


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class WriteGuard:
    """Condizioni da soddisfare prima di scrivere una nuova immagine.

    `confirmed` deve essere messo a True solo da una scelta esplicita
    dell'operatore (un pulsante, un flag in CLI), mai in automatico.
    """

    confirmed: bool
    backup_done: bool
    expected_size: int | None = None

    def check(self, image: bytes) -> None:
        if not self.backup_done:
            raise SafetyError("Scrittura bloccata: manca il backup dell'immagine originale.")
        if not self.confirmed:
            raise SafetyError("Scrittura bloccata: serve la conferma esplicita dell'operatore.")
        if not image:
            raise SafetyError("Scrittura bloccata: immagine vuota.")
        if self.expected_size is not None and len(image) != self.expected_size:
            raise SafetyError(
                f"Scrittura bloccata: l'immagine è {len(image)} byte, "
                f"attesi {self.expected_size} (dimensione del chip)."
            )


def verify_readback(written: bytes, readback: bytes) -> None:
    """Confronta ciò che si è scritto con una rilettura; alza SafetyError se differiscono."""
    if sha256(written) != sha256(readback):
        raise SafetyError(
            "Verifica fallita: la rilettura non coincide con l'immagine scritta. "
            "Non spegnere il dispositivo e riprova."
        )
