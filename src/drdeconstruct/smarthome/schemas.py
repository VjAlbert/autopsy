"""Output strutturato della guida smart home."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DeviceAdvice(BaseModel):
    device: str = Field(description="Nome, modello o indirizzo del dispositivo.")
    ecosystem: str
    reachable_now: bool = Field(description="Leggibile subito senza altre credenziali.")
    connection_path: str = Field(description="Canale e protocollo da usare.")
    requirements: list[str] = Field(description="Cosa deve procurarsi l'operatore.")
    firmware_path: str = Field(
        description="Percorso realistico per ispezionare o modificare il firmware, se esiste."
    )
    risks: list[str]
    confidence: Literal["high", "medium", "low"]


class SmartHomeGuide(BaseModel):
    summary: str
    devices: list[DeviceAdvice]
    not_reachable: list[str] = Field(
        description="Dispositivi o categorie che il PC non può raggiungere e perché."
    )
    next_steps: list[str]
